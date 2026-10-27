"""Actual Xdebug dbgpProxy binary routing a real PHP/Xdebug request."""

import asyncio
from contextlib import asynccontextmanager
from functools import partial
import json
from pathlib import Path
import platform
import signal
import socket

import pytest

from dbgpilot import Client, ProxyClient, ProxyError, Server

pytestmark = pytest.mark.integration


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@asynccontextmanager
async def official_proxy(tmp_path):
    binary = Path("/mnt/ddev-global-cache/dbgpilot/runtimes") / f"dbgpProxy-0.6.2-{platform.machine()}"
    assert binary.exists(), "Run ddev test-setup to install the pinned proxy test binary"
    control, engine = unused_port(), unused_port()
    while engine == control:
        engine = unused_port()
    log = tmp_path / "proxy.log"
    with log.open("wb") as output:
        process = await asyncio.create_subprocess_exec(
            str(binary), "-i", f"127.0.0.1:{control}", "-s", f"127.0.0.1:{engine}",
            stdout=output, stderr=asyncio.subprocess.STDOUT, cwd=tmp_path,
        )
        try:
            async with asyncio.timeout(5):
                while "Started client server" not in log.read_text() or "Started server server" not in log.read_text():
                    assert process.returncode is None, log.read_text()
                    await asyncio.sleep(0.01)
            yield control, engine
        except BaseException as error:
            error.add_note(log.read_text()[-6000:])
            raise
        finally:
            if process.returncode is None:
                process.send_signal(signal.SIGINT)
            try:
                async with asyncio.timeout(5):
                    await process.wait()
            except TimeoutError:
                process.kill()
                await process.wait()
    assert process.returncode == 0, log.read_text()


async def test_official_proxy_routes_php_and_unregisters_owned_key(ddev_runtime, tmp_path):
    path = tmp_path / "through-proxy.php"
    path.write_text('<?php\n$value = 42;\n$result = $value + 1;\necho json_encode(["result" => $result]);\n')
    async with asyncio.timeout(20), official_proxy(tmp_path) as (control_port, engine_port):
        async with Server(port=0, xdebug_port=0, proxy_host="127.0.0.1",
                          proxy_port=control_port, idekey="dbgpilot-live-proxy") as server:
            async with Client(server.url) as first:
                registration = (await first.proxy_registrations())[0]
                # 0.6.2 echoes the IDE endpoint, rather than the proxy's -s
                # engine endpoint described by the spec. Preserve raw metadata.
                assert registration["port"] == server.controller.port
                assert registration["listen_port"] == server.controller.port
                with pytest.raises(ProxyError):
                    await ProxyClient(port=control_port).register(9007, "dbgpilot-live-proxy")
                process = await asyncio.create_subprocess_exec(
                    "php", "-d", "xdebug.mode=debug", "-d", "xdebug.start_with_request=yes",
                    "-d", "xdebug.client_host=127.0.0.1", "-d", f"xdebug.client_port={engine_port}",
                    "-d", "xdebug.idekey=dbgpilot-live-proxy", str(path),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                try:
                    session = await first.wait_for_session(idekey="dbgpilot-live-proxy", timeout=5)
                    info = await session.info()
                    # The real proxy currently forwards init unchanged; the
                    # controller retains proxied metadata when a proxy adds it.
                    assert info["info"]["engine"] == "Xdebug"
                    await session.set_breakpoint(path, 3)
                    snapshot = await session.break_and_return(["$value"], timeout=5)
                    assert snapshot["variables"]["$value"]["value"] == 42
                    await first.aclose()
                    async with Client(server.url) as later:
                        resumed = later.session(session.id)
                        await resumed.set_value("$value", 50)
                        detached = await resumed.detach()
                        assert detached["status"] == "stopped" and not detached["response_received"]
                    stdout, stderr = await process.communicate()
                    assert process.returncode == 0, stderr.decode()
                    assert json.loads(stdout)["result"] == 51
                finally:
                    if process.returncode is None:
                        process.kill()
                        await process.communicate()
        # Shutdown sent proxystop; the same key is available again.
        proxy = ProxyClient(port=control_port)
        result = await proxy.register(9007, "dbgpilot-live-proxy")
        assert result.success
        await proxy.unregister("dbgpilot-live-proxy")


async def test_xdebug_rejects_unavailable_optional_commands_without_losing_session(ddev_runtime, tmp_path):
    path = tmp_path / "optional.php"
    path.write_text('<?php\n$value = 1;\necho $value;\n')
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        process = await asyncio.create_subprocess_exec(
            "php", "-d", "xdebug.mode=debug", "-d", "xdebug.start_with_request=yes",
            "-d", "xdebug.client_host=127.0.0.1", "-d", f"xdebug.client_port={server.controller.port}",
            str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            from dbgpilot import RemoteError
            session = await client.wait_for_session(timeout=5)
            await session.set_breakpoint(path, 2)
            await session.run_until_break(timeout=5)
            info = await session.info()
            commands = {
                "stdin": session.set_stdin, "interact": session.interact,
                "expr": partial(session.expr, "$value"),
                "exec": partial(session.exec, "$value = 2;"),
                "spawnpoint_set": session.set_spawnpoint,
                "spawnpoint_get": partial(session.get_spawnpoint, "missing"),
                "spawnpoint_update": partial(session.update_spawnpoint, "missing", state="disabled"),
                "spawnpoint_remove": partial(session.remove_spawnpoint, "missing"),
                "spawnpoint_list": session.spawnpoints,
            }
            for command, operation in commands.items():
                assert info["capabilities"][command]["value"] != "1"
                with pytest.raises(RemoteError) as caught:
                    await operation()
                assert caught.value.code == -32002
            assert not (await session.info())["closed"]
            await session.detach()
            stdout, stderr = await process.communicate()
            assert process.returncode == 0 and stdout == b"1", stderr.decode()
        finally:
            if process.returncode is None:
                process.kill()
                await process.communicate()
