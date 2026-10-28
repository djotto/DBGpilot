"""Async HTTP client suitable for Playwright scripts and later reconnects."""

import asyncio
from contextlib import suppress
import json
from urllib.parse import urlsplit
import uuid

from .errors import ConnectionClosed, ProtocolError
from .wire import RemoteError, json_value


def _arguments(value):
    if isinstance(value, bytes):
        return json_value(value)
    if isinstance(value, dict):
        return {key: _arguments(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_arguments(item) for item in value]
    return value


class Client:
    """Closing this client never closes server-owned debugging sessions.

    Each call uses its own HTTP connection, so long-polling and execution may
    run concurrently without blocking other clients or requiring a shared SDK.
    Results are JSON dictionaries, lists, and scalar values.
    """

    def __init__(self, url="http://127.0.0.1:9004", *, token=None, timeout=35,
                 max_response_bytes=64 * 1024 * 1024):
        parsed = urlsplit(url)
        if (parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
            raise ValueError("Use an HTTP server origin, such as http://127.0.0.1:9004")
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout
        self.host, self.port = parsed.hostname, parsed.port or 80
        self.max_response_bytes = max_response_bytes
        self._closed = False
        self._inflight = {}
        if token is not None and (
            not isinstance(token, str) or not token.isascii() or "\r" in token or "\n" in token
        ):
            raise ValueError("Bearer tokens must be ASCII without newlines")

    async def __aenter__(self):
        if self._closed:
            raise ConnectionClosed("Client closed")
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    async def aclose(self):
        """Close this client and cancel its requests; server-owned sessions stay open."""
        self._closed = True
        await asyncio.gather(*(
            self._cancel_remote(id) for id, method in tuple(self._inflight.items())
            if method != "cancel_request"
        ))

    async def call(self, method, **params):
        """Await a JSON-RPC result, raising RemoteError for a server-reported failure."""
        return await self._call(uuid.uuid4().hex, method, params)

    def request(self, method, **params):
        """Start a request with an explicit ID, result, and remote cancellation."""
        if self._closed:
            raise ConnectionClosed("Client closed")
        return RemoteRequest(self, method, params)

    async def cancel_request(self, request_id):
        """Ask the server to cancel a request by ID without resuming PHP."""
        return await self.call("cancel_request", request_id=request_id)

    async def _cancel_remote(self, request_id):
        request = {"jsonrpc": "2.0", "id": uuid.uuid4().hex, "method": "cancel_request",
                   "params": {"request_id": request_id}}
        body = json.dumps(request).encode()
        try:
            return await self._request(request["id"], body, 2)
        except (OSError, RemoteError, ProtocolError):
            return None

    async def _call(self, request_id, method, params):
        if self._closed:
            raise ConnectionClosed("Client closed")
        request = {"jsonrpc": "2.0", "id": request_id,
                   "method": method, "params": _arguments(params)}
        # Encoding arguments is strict even though returned engine values can
        # represent non-finite numbers as text.
        body = json.dumps(request, ensure_ascii=True, allow_nan=False).encode("utf-8")
        timeout = self.timeout
        wait = params.get("timeout")
        if isinstance(wait, (int, float)) and not isinstance(wait, bool) and 0 <= wait <= 3600:
            timeout = max(timeout, wait + 5)
        self._inflight[request_id] = method
        try:
            return await self._request(request["id"], body, timeout)
        except asyncio.CancelledError:
            if method != "cancel_request":
                cleanup = asyncio.create_task(self._cancel_remote(request_id))
                try:
                    await asyncio.shield(cleanup)
                except asyncio.CancelledError:
                    pass
            raise
        except (OSError, ProtocolError):
            if method != "cancel_request":
                await self._cancel_remote(request_id)
            raise
        finally:
            self._inflight.pop(request_id, None)

    async def _request(self, request_id, body, timeout):
        authority = f"[{self.host}]" if ":" in self.host else self.host
        headers = (f"POST /rpc HTTP/1.1\r\nHost: {authority}:{self.port}\r\n"
                   f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
                   "Connection: close\r\n")
        if self.token is not None:
            headers += f"Authorization: Bearer {self.token}\r\n"
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(self.host, self.port, limit=64 * 1024)
            try:
                writer.write((headers + "\r\n").encode("ascii") + body)
                await writer.drain()
                raw_headers = await reader.readuntil(b"\r\n\r\n")
                lines = raw_headers.decode("ascii").split("\r\n")
                status_line = lines[0].split(" ", 2)
                if len(status_line) < 2 or status_line[0] not in {"HTTP/1.0", "HTTP/1.1"}:
                    raise ProtocolError("Invalid HTTP response status")
                status = int(status_line[1])
                lengths = []
                for line in lines[1:]:
                    if not line:
                        continue
                    name, value = line.split(":", 1)
                    if name.casefold() == "content-length":
                        lengths.append(value.strip())
                    if name.casefold() == "transfer-encoding":
                        raise ProtocolError("Chunked API responses are not supported")
                if len(lengths) != 1 or not lengths[0].isdigit():
                    raise ProtocolError("Expected one response Content-Length")
                length = int(lengths[0])
                if length > self.max_response_bytes:
                    raise ProtocolError("Server response exceeds the configured limit")
                result = json.loads(await reader.readexactly(length))
                if not isinstance(result, dict) or result.get("jsonrpc") != "2.0":
                    raise ProtocolError("Server returned an invalid JSON-RPC response")
                if status == 200 and result.get("id") != request_id:
                    raise ProtocolError("Server response does not match this request")
                if "error" in result:
                    error = result["error"]
                    if (
                        not isinstance(error, dict) or not isinstance(error.get("code"), int)
                        or not isinstance(error.get("message"), str)
                    ):
                        raise ProtocolError("Server returned an invalid error")
                    raise RemoteError(error["code"], error["message"], error.get("data"))
                if status != 200 or result.get("id") != request_id or "result" not in result:
                    raise ProtocolError("Server response does not match this request")
                return result["result"]
            except (
                ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
            ) as error:
                raise ProtocolError("Invalid HTTP/JSON response") from error
            finally:
                writer.close()
                with suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()

    async def health(self):
        """Return server identity, listener settings, and health metadata."""
        return await self.call("health")

    async def sessions(self):
        """Return summaries of the server's retained live and closed sessions."""
        return await self.call("sessions")

    async def errors(self):
        """Return recent controller errors retained by the server."""
        return await self.call("errors")

    async def path_mappings(self):
        """Return the server's normalized source path mappings."""
        return await self.call("paths.mappings")

    async def to_remote(self, path):
        """Ask the server to map a local path to an engine URI."""
        return await self.call("paths.to_remote", path=str(path))

    async def to_local(self, uri):
        """Ask the server to map an engine file URI to a local path."""
        return await self.call("paths.to_local", path=str(uri))

    async def register_proxy(self, host="127.0.0.1", port=9001, *, idekey,
                             listen_port=None, multiple_sessions=True, timeout=5):
        """Register a proxy IDE key for the server's debugger listener or supplied port."""
        return await self.call(
            "proxy.register", host=host, port=port, idekey=idekey,
            listen_port=listen_port, multiple_sessions=multiple_sessions, timeout=timeout,
        )

    async def unregister_proxy(self, host="127.0.0.1", port=9001, *, idekey, timeout=5):
        """Ask the server to unregister an IDE key from a proxy."""
        return await self.call(
            "proxy.unregister", host=host, port=port, idekey=idekey, timeout=timeout,
        )

    async def proxy_registrations(self):
        """Return proxy registrations owned by the server's controller."""
        return await self.call("proxy.registrations")

    async def wait_for_session(
        self, *, idekey=None, cookie=None, appid=None, file=None, timeout=30,
    ):
        """Claim an unclaimed open session matching the supplied filters.

        Wait up to timeout seconds and return a RemoteSession. The file filter uses
        the server's source path mappings.
        """
        result = await self.call("wait_for_session", idekey=idekey, cookie=cookie,
                                 appid=appid, file=file, timeout=timeout)
        return RemoteSession(self, result["session_id"], result)

    def session(self, session_id):
        """Reconnect to a known ID without claiming another PHP request."""
        return RemoteSession(self, session_id)


class RemoteRequest:
    """An awaitable, cancellable RPC handle. Cancellation does not resume PHP."""

    def __init__(self, client, method, params):
        self.client, self.id = client, uuid.uuid4().hex
        self._task = asyncio.create_task(client._call(self.id, method, params))
        # A caller may explicitly cancel a handle without awaiting its result.
        self._task.add_done_callback(lambda task: None if task.cancelled() else task.exception())

    def __await__(self):
        return self.result().__await__()

    async def result(self):
        """Await the request result, propagating failures or cancellation."""
        return await self._task

    async def cancel(self):
        """Request server-side cancellation without resuming the debugging session."""
        return await self.client.cancel_request(self.id)

    def done(self):
        """Return whether the local request task has completed, failed, or been cancelled."""
        return self._task.done()


class RemoteSession:
    """Send commands and retrieve events for a server-owned session by ID.

    The session can be accessed through another client using the same ID.
    close() explicitly releases the debugging session on the server.
    """

    def __init__(self, client, session_id, initial_info=None):
        self.client, self.id = client, session_id
        self.initial_info = initial_info

    async def call(self, method, **params):
        """Await a session RPC result using this session's ID."""
        return await self.client.call("session." + method, session_id=self.id, **params)

    def request(self, method, **params):
        """Start a session RPC and return an awaitable handle with explicit cancellation."""
        return self.client.request("session." + method, session_id=self.id, **params)

    async def info(self):
        """Return session state, capabilities, type mappings, and known breakpoints."""
        return await self.call("info")

    async def events(self, *, after=0, timeout=30, limit=100):
        """Poll retained events after a cursor, returning a batch and its next cursor."""
        return await self.call("events", after=after, timeout=timeout, limit=limit)

    async def close(self):
        """Explicitly detach/close this PHP debugging session on the server."""
        return await self.call("close")

    async def forget(self):
        """Remove the server's retained record for this session after it has been closed."""
        return await self.call("forget")

    async def set_breakpoint(self, file=None, line=None, **options):
        """Create a breakpoint using the server's source mappings and supplied options."""
        return await self.call("set_breakpoint", file=str(file) if file is not None else None,
                               line=line, **options)

    async def snapshot(self, variables=(), *, expressions=(), depth=0, context=0):
        """Read stack and variable data and evaluate requested expressions while paused."""
        return await self.call("snapshot", variables=list(variables), expressions=list(expressions),
                               depth=depth, context=context)

    async def break_and_return(
        self, variables=(), *, expressions=(), depth=0, context=0, timeout=30,
    ):
        """Run to a breakpoint, return a snapshot, and leave PHP paused."""
        return await self.call(
            "break_and_return", variables=list(variables), expressions=list(expressions),
            depth=depth, context=context, timeout=timeout,
        )

    async def run(self, *, timeout=30):
        """Resume execution and return the next execution result as a dictionary."""
        return await self.call("run", timeout=timeout)

    async def resume(self, *, timeout=30):
        """Resume execution through run() and return its result."""
        return await self.call("resume", timeout=timeout)

    async def run_until_break(self, *, timeout=30):
        """Run to a breakpoint, raising a remote execution-finished error if none is hit."""
        return await self.call("run_until_break", timeout=timeout)

    async def step_into(self, *, timeout=30):
        """Advance execution into the next statement or function and return its result."""
        return await self.call("step_into", timeout=timeout)

    async def step_over(self, *, timeout=30):
        """Advance past the next statement without stepping into called functions."""
        return await self.call("step_over", timeout=timeout)

    async def step_out(self, *, timeout=30):
        """Run until the current function returns and report the next execution state."""
        return await self.call("step_out", timeout=timeout)

    async def evaluate(self, expression, *, depth=0, page=0, timeout=30):
        """Evaluate code through the server; evaluation may have side effects in PHP."""
        return await self.call(
            "evaluate", expression=expression, depth=depth, page=page, timeout=timeout,
        )

    async def expr(self, expression, *, depth=0, page=0, timeout=30):
        """Evaluate an engine-supported expression and return its property metadata."""
        return await self.call(
            "expr", expression=expression, depth=depth, page=page, timeout=timeout,
        )

    async def exec(self, code, *, timeout=30):
        """Execute an engine-supported code fragment and return its success flag."""
        return await self.call("exec", code=code, timeout=timeout)

    async def set_spawnpoint(self, file=None, line=None, *, state="enabled"):
        """Configure a source location where the engine may start another debug session."""
        return await self.call("set_spawnpoint", file=str(file) if file is not None else None,
                               line=line, state=state)

    async def get_spawnpoint(self, id):
        """Return the engine's spawnpoint record for an ID."""
        return await self.call("get_spawnpoint", id=id)

    async def spawnpoints(self):
        """Return all spawnpoint records reported by the engine."""
        return await self.call("spawnpoints")

    async def update_spawnpoint(self, id, *, state=None, line=None):
        """Change a spawnpoint's state or line through the server."""
        return await self.call("update_spawnpoint", id=id, state=state, line=line)

    async def remove_spawnpoint(self, id):
        """Remove a spawnpoint by ID through the server."""
        return await self.call("remove_spawnpoint", id=id)

    async def stdin(self, *, mode=None, data=None, timeout=5):
        """Configure stdin redirection or send input data, supplying exactly one of them."""
        params = {"timeout": timeout}
        if mode is not None:
            params["mode"] = mode
        if data is not None:
            params["data"] = data
        return await self.call("stdin", **params)

    async def set_stdin(self, enabled=True, *, timeout=5):
        """Enable or disable engine stdin redirection and return the success flag."""
        return await self.call("set_stdin", enabled=enabled, timeout=timeout)

    async def send_stdin(self, data, *, timeout=5):
        """Send text or binary input to an engine with stdin redirection enabled."""
        return await self.call("send_stdin", data=data, timeout=timeout)

    async def interact(self, code="", *, mode=1, timeout=30):
        """Submit interactive code or clear its buffer and return status and prompt data."""
        return await self.call("interact", code=code, mode=mode, timeout=timeout)

    async def property_get(self, name, **options):
        """Read a property with the requested context, depth, paging, and target options."""
        return await self.call("property_get", name=name, **options)

    async def set_value(self, name, value, **options):
        """Assign a Python scalar through the server's PHP value conversion."""
        return await self.call("set_value", name=name, value=value, **options)

    async def interrupt(self):
        """Request an asynchronous break from an engine that supports interrupting PHP."""
        return await self.call("interrupt")

    async def detach(self):
        """Detach the debugger and allow PHP to continue, closing the session connection."""
        return await self.call("detach")

    async def stop(self):
        """Terminate PHP execution and close the debugging session."""
        return await self.call("stop")
