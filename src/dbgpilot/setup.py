"""Connect to a daemon or explicitly launch the existing CLI in a process.

Context exit closes only the client. Owned daemons survive until shutdown is
explicitly requested, including when the creating event loop exits.
"""

import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile

from .client import Client
from .config import load_config
from .errors import DBGpilotError
from .playwright import PlaywrightDebugger
from .wire import RemoteError


class SetupError(DBGpilotError):
    """A connection, readiness, identity, or owned-process lifecycle failure."""


class DebuggerSetup:
    """Connect to an existing server or launch and validate an owned process.

    Context exit closes the client while the server and paused sessions survive.
    shutdown(release_sessions=True) explicitly terminates an owned server.
    """

    def __init__(self, *, config=None, discover=False, **overrides):
        self.config = load_config(config, discover=discover, **overrides)
        self.client = None
        self.ready = None
        self._process = None
        self._output = self._errors = self._settings_file = None
        self._started = self._closed = False
        self._lock = asyncio.Lock()

    @property
    def owns_server(self):
        """Return whether this setup launched and retains a server process handle."""
        return self._process is not None

    @property
    def pid(self):
        """Return the owned server's process ID, or None when using an existing server."""
        return None if self._process is None else self._process.pid

    @property
    def url(self):
        """Return the connected API URL, falling back to readiness or configured settings."""
        if self.client is not None:
            return self.client.url
        return self.ready["url"] if self.ready else self.config.url

    def _check_process(self):
        if self._process is not None and self._process.poll() is not None:
            raise SetupError(
                f"Owned DBGpilot process {self.pid} exited (code {self._process.returncode})",
            )

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.aclose()

    async def start(self):
        """Launch if configured, connect a client, and validate server readiness and identity.

        Repeated calls reuse a started setup after checking its owned process. Failed
        or cancelled startup closes the client and terminates any owned child.
        """
        async with self._lock:
            if self._closed:
                raise SetupError("Setup closed; create another setup or reconnect using Client")
            if self._started:
                self._check_process()
                return self
            try:
                async with asyncio.timeout(self.config.startup_timeout):
                    if self.config.launch:
                        self._launch()
                        self.ready = await self._read_ready()
                    self.client = Client(
                        self.url, token=self.config.token, timeout=self.config.request_timeout,
                    )
                    health = await self.client.health()
                    self._validate_health(health)
                    self._check_process()
                    self.ready = health
                    self._started = True
                    self._close_files()
                    return self
            except BaseException as error:
                exited = self._process is not None and self._process.poll() is not None
                # Cancellation and failed launches must never leave a child behind.
                cleanup = asyncio.create_task(self._failed_start())
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    await cleanup
                if isinstance(error, asyncio.CancelledError):
                    raise
                if isinstance(error, SetupError):
                    raise
                if isinstance(error, RemoteError):
                    detail = (
                        "Authentication failed; check the configured bearer token"
                        if error.code == -32009 else "Server rejected the readiness request"
                    )
                elif isinstance(error, TimeoutError):
                    detail = "Startup/readiness deadline expired"
                elif isinstance(error, OSError) and self.config.launch and self._process is None:
                    detail = (
                        "Cannot launch DBGpilot; check the Python executable and working directory"
                    )
                elif exited:
                    detail = (
                        "Owned DBGpilot process exited during startup "
                        f"(code {self._process.returncode})"
                    )
                else:
                    detail = (
                        "Cannot reach a compatible DBGpilot API; "
                        "check the endpoint, server and authentication"
                    )
                raise SetupError(detail) from None

    def _launch(self):
        settings = self.config
        self._output = tempfile.TemporaryFile()
        self._errors = tempfile.TemporaryFile()
        # A generated config transmits resolved mappings without command-line
        # secrets or accidental discovery in a different child working directory.
        handle, name = tempfile.mkstemp(prefix="dbgpilot-", suffix=".toml")
        self._settings_file = Path(name)
        with os.fdopen(handle, "w", encoding="utf-8") as target:
            for mapping in settings.path_mapper.mappings:
                target.write("[[path_mappings]]\n")
                for key, value in mapping.to_dict().items():
                    if value is None:
                        continue
                    if isinstance(value, bool):
                        encoded = str(value).lower()
                    else:
                        # TOML uses Unicode scalar escapes, not JSON surrogate
                        # pairs. DEL must still be escaped in a basic string.
                        encoded = json.dumps(value, ensure_ascii=False).replace("\x7f", "\\u007f")
                    target.write(f"{key} = {encoded}\n")
        env = dict(os.environ)
        env.pop("DBGPILOT_TOKEN", None)
        if settings.token is not None:
            env["DBGPILOT_TOKEN"] = settings.token
        command = [settings.python, "-m", "dbgpilot", "serve", "--host", settings.host,
                   "--port", str(settings.port), "--xdebug-host", settings.xdebug_host,
                   "--xdebug-port", str(settings.xdebug_port), "--config", name]
        self._process = subprocess.Popen(command, cwd=settings.working_directory, env=env,
                                         stdin=subprocess.DEVNULL, stdout=self._output,
                                         stderr=self._errors, start_new_session=True)

    async def _read_ready(self):
        while True:
            self._output.seek(0)
            line = self._output.readline(65537)
            if len(line) > 65536:
                raise SetupError("Owned process emitted oversized readiness output")
            if line.endswith(b"\n"):
                try:
                    ready = json.loads(line)
                except (ValueError, UnicodeError):
                    raise SetupError("Owned process emitted invalid readiness output") from None
                if (
                    not isinstance(ready, dict) or ready.get("event") != "ready"
                    or type(ready.get("pid")) is not int or ready.get("pid") != self.pid
                    or not isinstance(ready.get("instance_id"), str) or not ready["instance_id"]
                ):
                    raise SetupError("Owned process readiness identity did not match")
                if (not isinstance(ready.get("url"), str) or ready.get("protocol") != "dbgpilot/1"
                        or ready.get("status") != "ok"):
                    raise SetupError("Owned process emitted incompatible readiness output")
                return ready
            if self._process.poll() is not None:
                self._errors.seek(0)
                # Report CLI failure categories without echoing paths/tokens or
                # arbitrary child output into routine diagnostics.
                error = self._errors.read(65536).decode("utf-8", "replace")
                reason = (
                    "listener port is occupied" if "address already in use" in error.casefold()
                    else "check the Python executable, installation, "
                    "working directory and listener settings"
                )
                raise SetupError(
                    "Owned DBGpilot process exited before readiness "
                    f"(code {self._process.returncode}); {reason}"
                )
            await asyncio.sleep(0.02)

    def _validate_health(self, health):
        if (
            not isinstance(health, dict) or health.get("status") != "ok"
            or health.get("protocol") != "dbgpilot/1" or not isinstance(health.get("url"), str)
        ):
            raise SetupError("Incompatible DBGpilot API; expected protocol dbgpilot/1")
        if self._process is not None and health.get("instance_id") != self.ready.get("instance_id"):
            raise SetupError("Endpoint belongs to a different server process")

    async def health(self):
        """Check the owned process and validate health metadata returned by the server."""
        self._check_process()
        if self.client is None:
            raise SetupError("Start setup before using its client")
        health = await self.client.health()
        self._validate_health(health)
        return health

    def debugger(self, page, *, idekey=None):
        """Create a Playwright debugger for an async page after setup has started."""
        self._check_process()
        if not self._started or self._closed:
            raise SetupError("Start setup before creating a Playwright debugger")
        return PlaywrightDebugger(page, self.client, idekey=idekey)

    async def aclose(self):
        """Close this client; the server and all paused PHP sessions survive."""
        async with self._lock:
            await self._close_client()

    async def _close_client(self):
        self._closed = True
        if self.client is not None:
            await self.client.aclose()

    async def shutdown(self, *, release_sessions=False):
        """Stop only our child; this releases ALL of its debugger sessions.

        release_sessions=True is the caller's deliberate acknowledgement of
        that consequence, rather than a check vulnerable to new-session races.
        """
        async with self._lock:
            if not self.owns_server:
                raise SetupError("Cannot shut down a reused server; this setup does not own it")
            if release_sessions is not True:
                raise SetupError("Shutdown releases all PHP sessions; pass release_sessions=True")
            async def close_owned():
                try:
                    await self._close_client()
                finally:
                    await self._terminate()

            cleanup = asyncio.create_task(close_owned())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise

    async def _terminate(self):
        process = self._process
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                async with asyncio.timeout(5):
                    while process.poll() is None:
                        await asyncio.sleep(0.02)
            except TimeoutError:
                process.kill()
        await asyncio.to_thread(process.wait)

    async def _failed_start(self):
        try:
            await self._close_client()
        finally:
            try:
                await self._terminate()
            finally:
                self._close_files()

    def _close_files(self):
        for stream in (self._output, self._errors):
            if stream is not None:
                stream.close()
        if self._settings_file is not None:
            self._settings_file.unlink(missing_ok=True)
