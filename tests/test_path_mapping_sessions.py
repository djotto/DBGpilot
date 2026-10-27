"""Mapping across session models, real TCP/HTTP, CLI configuration and PHP."""

import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
import sys

import pytest

from dbgpilot import (
    BreakpointSpec, Client, Controller, PathMapping, PathMappingError,
    PlaywrightDebugger, RemoteError, Server,
)
from .helpers import Engine, fake_session, xml


MAPPINGS = [PathMapping("/local/project", "file:///app")]


async def paused_with_location(session, engine):
    task = asyncio.create_task(session.run_until_break())
    request = await engine.next_request()
    message = xml("message", filename="file:///app/index.php", lineno=9)
    breakpoint = xml("breakpoint", id="b", type="line", filename="file:///app/index.php", lineno=9)
    await engine.respond(request, status="break", reason="ok", payload=[message, breakpoint])
    result = await task
    event = await session.next_event(timeout=1)
    assert result.local_file == "/local/project/index.php"
    assert result.breakpoint.local_file == result.local_file
    assert event.result == result and session.last_result == result
    return result


async def test_session_initialization_execution_and_nested_stack_locations_preserve_engine_uris():
    async with fake_session(path_mappings=MAPPINGS) as (_, session, engine):
        assert session.info.file == "file:///app/index.php"
        assert session.info.local_file == "/local/project/index.php"
        assert session.info.attributes["fileuri"] == "file:///app/index.php"
        assert "file:///app/index.php" in session.info.xml
        result = await paused_with_location(session, engine)
        task = asyncio.create_task(session.stack())
        frame = xml("stack", level=0, filename="file:///app/index.php", lineno=9)
        frame.append(xml("input", level=1, filename="file:///app/input.php", lineno=2))
        await engine.respond(await engine.next_request(), payload=[frame])
        frames = await task
        assert frames[0].file == result.file and frames[0].local_file == result.local_file
        assert frames[0].inputs[0].local_file == "/local/project/input.php"
        assert frames[0].to_dict()["inputs"][0]["file"] == "file:///app/input.php"


async def test_breakpoint_source_and_spawnpoint_commands_map_local_inputs_and_results():
    async with fake_session(path_mappings=MAPPINGS) as (_, session, engine):
        task = asyncio.create_task(session.set_breakpoint("/local/project/src/a b.php", 8))
        request = await engine.next_request()
        assert request.arguments["f"] == "file:///app/src/a%20b.php"
        await engine.respond(request, id="b", state="enabled")
        point = await task
        assert point.file == request.arguments["f"] and point.local_file == "/local/project/src/a b.php"

        for call in (session.get_breakpoint("b"), session.breakpoints()):
            task = asyncio.create_task(call)
            node = xml("breakpoint", id="b", type="line", filename="file:///app/src/a%20b.php", lineno=8)
            await engine.respond(await engine.next_request(), payload=[node])
            result = await task
            actual = result[0] if isinstance(result, tuple) else result
            assert actual.local_file == point.local_file
            assert session.known_breakpoints["b"].local_file == point.local_file

        source = asyncio.create_task(session.source(point.local_file, begin=1, end=2))
        request = await engine.next_request()
        assert request.arguments == {"f": point.file, "b": "1", "e": "2"}
        response = xml("response", command="source", transaction_id=request.id, encoding="base64")
        response.text = "PD9waHA="
        await engine.send(response)
        assert await source == b"<?php"

        spawn = asyncio.create_task(session.set_spawnpoint("/local/project/child.tcl", 4))
        request = await engine.next_request()
        assert request.arguments["f"] == "file:///app/child.tcl"
        await engine.respond(request, id="s", state="enabled")
        assert (await spawn).local_file == "/local/project/child.tcl"
        for call in (session.get_spawnpoint("s"), session.spawnpoints()):
            task = asyncio.create_task(call)
            await engine.respond(await engine.next_request(), payload=[
                xml("spawnpoint", id="s", state="enabled", filename="file:///app/child.tcl", lineno=4),
            ])
            result = await task
            assert (result[0] if isinstance(result, tuple) else result).local_file == "/local/project/child.tcl"
        assert session.known_spawnpoints["s"].local_file == "/local/project/child.tcl"


async def test_notification_locations_and_inventory_are_mapped_without_rewriting_xml():
    async with fake_session(path_mappings=MAPPINGS) as (_, session, engine):
        node = xml("notify", name="breakpoint_resolved")
        node.append(xml("breakpoint", id="b", filename="file:///app/index.php", lineno=9))
        node.append(xml("message", filename="file:///app/error.php", lineno=10, type="Notice"))
        await engine.send(node)
        event = await session.next_event(timeout=1)
        assert event.breakpoint.local_file == "/local/project/index.php"
        assert event.message.local_file == "/local/project/error.php"
        assert event.message.attributes["filename"] == "file:///app/error.php"
        assert "file:///app/error.php" in event.xml and "/local/project" not in event.xml
        assert session.known_breakpoints["b"].local_file == event.breakpoint.local_file


async def test_unmapped_and_virtual_locations_do_not_break_debugging_and_outgoing_misses_are_explicit():
    async with fake_session(path_mappings=MAPPINGS) as (_, session, engine):
        for operation in (session.set_breakpoint, session.set_spawnpoint, session.source):
            args = ("/elsewhere/a.php", 9) if operation != session.source else ("/elsewhere/a.php",)
            with pytest.raises(PathMappingError, match="no local root"):
                await operation(*args)
        assert engine.requests.empty()
        await paused_with_location(session, engine)
        task = asyncio.create_task(session.stack())
        await engine.respond(await engine.next_request(), payload=[
            xml("stack", level=0, filename="file:///vendor/lib.php", lineno=1),
            xml("stack", level=1, filename="dbgp:eval-42", lineno=1),
        ])
        frames = await task
        assert frames[0].local_file is None and "no remote root" in frames[0].path_mapping_error
        assert frames[0].file == "file:///vendor/lib.php"
        assert frames[1].local_file is None and frames[1].path_mapping_error is None
        task = asyncio.create_task(session.source("dbgp:eval-42"))
        request = await engine.next_request()
        assert request.arguments == {"f": "dbgp:eval-42"}
        await engine.respond(request)
        assert await task == b"" and not session.closed


async def test_snapshot_fallback_carries_local_file_from_stack():
    async with fake_session(path_mappings=MAPPINGS) as (_, session, engine):
        run = asyncio.create_task(session.run_until_break())
        await engine.respond(await engine.next_request(), status="break")
        await run
        snapshot = asyncio.create_task(session.snapshot())
        await engine.respond(await engine.next_request(), payload=[
            xml("stack", level=0, filename="file:///app/index.php", lineno=9),
        ])
        result = (await snapshot).to_dict()
        assert result["execution"]["local_file"] == "/local/project/index.php"
        assert result["execution"]["file"] == "file:///app/index.php"


async def test_server_mapping_helpers_filters_results_errors_and_reconnection():
    async with Server(port=0, xdebug_port=0, path_mappings=MAPPINGS) as server:
        engine = await Engine.connect(server.controller)
        try:
            async with Client(server.url) as client:
                assert (await client.path_mappings())[0]["local"] == "/local/project"
                assert (await client.health())["path_mappings"] == await client.path_mappings()
                assert await client.to_remote("/local/project/index.php") == "file:///app/index.php"
                assert await client.to_local("file:///app/index.php") == "/local/project/index.php"
                remote = await client.wait_for_session(file="/local/project/index.php", timeout=1)
                assert (await remote.info())["info"]["local_file"] == "/local/project/index.php"
                for call in (client.to_remote("/elsewhere/a.php"), client.to_local("file:///elsewhere/a.php")):
                    with pytest.raises(RemoteError) as caught:
                        await call
                    assert caught.value.code == -32012
                    assert caught.value.data["type"] == "PathMappingError"
                    assert "reason" in caught.value.data and "direction" in caught.value.data
                task = asyncio.create_task(remote.set_breakpoint("/local/project/index.php", 9))
                request = await engine.next_request()
                assert request.arguments["f"] == "file:///app/index.php"
                await engine.respond(request, id="b")
                assert (await task)["local_file"] == "/local/project/index.php"
                task = asyncio.create_task(remote.run_until_break())
                await engine.respond(await engine.next_request(), status="break", payload=[
                    xml("message", filename="file:///app/index.php", lineno=9),
                ])
                assert (await task)["local_file"] == "/local/project/index.php"
            async with Client(server.url) as later:
                remote = later.session(remote.id)
                info = await remote.info()
                assert info["execution"]["local_file"] == "/local/project/index.php"
                assert info["breakpoints"]["b"]["local_file"] == "/local/project/index.php"
                batch = await remote.events(timeout=1)
                assert batch["events"][-1]["data"]["result"]["local_file"] == "/local/project/index.php"
        finally:
            await engine.close()


@asynccontextmanager
async def cli_server(cwd, *args):
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dbgpilot", "serve", "--port", "0", "--xdebug-port", "0", *args,
        cwd=cwd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(5):
            line = await process.stdout.readline()
            assert line, (await process.stderr.read()).decode()
            ready = json.loads(line)
        yield ready
    finally:
        if process.returncode is None:
            process.terminate()
        async with asyncio.timeout(5):
            _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()


async def test_cli_discovers_project_config_from_subdirectory_and_accepts_override(tmp_path):
    config = tmp_path / "dbgpilot.toml"
    config.write_text('[[path_mappings]]\nlocal="."\nremote="file:///original"\n')
    child = tmp_path / "src"
    child.mkdir()
    async with cli_server(child, "--path-map", str(tmp_path), "file:///override") as ready:
        assert ready["path_mappings"][0]["remote"] == "file:///override"
        async with Client(ready["url"]) as client:
            assert await client.to_remote(tmp_path / "a.php") == "file:///override/a.php"
    async with cli_server(child, "--no-config") as ready:
        assert ready["path_mappings"] == []


async def test_cli_explicit_config_and_mapping_affect_an_engine_connection(tmp_path):
    config = tmp_path / "custom.toml"
    config.write_text('[[path_mappings]]\nlocal="/local/project"\nremote="file:///app"\n')
    async with cli_server(tmp_path, "--config", str(config)) as ready:
        engine = await Engine.connect(SimpleNamespace(host=ready["xdebug_host"], port=ready["xdebug_port"]))
        try:
            async with Client(ready["url"]) as client:
                remote = await client.wait_for_session(file="/local/project/index.php", timeout=1)
                assert (await remote.info())["info"]["local_file"] == "/local/project/index.php"
                task = asyncio.create_task(remote.set_breakpoint("/local/project/index.php", 3))
                request = await engine.next_request()
                assert request.arguments["f"] == "file:///app/index.php"
                await engine.respond(request, id="b")
                assert (await task)["local_file"] == "/local/project/index.php"
        finally:
            await engine.close()


async def test_cli_bad_config_exits_with_structured_error_without_readiness(tmp_path):
    config = tmp_path / "broken.toml"
    config.write_text('[[path_mappings]]\nlocal="/work"\nremtoe="file:///app"\n')
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dbgpilot", "serve", "--port", "0", "--xdebug-port", "0", "--config", str(config),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(5):
        stdout, stderr = await process.communicate()
    assert process.returncode == 1 and not stdout
    assert json.loads(stderr)["error"]["type"] == "ValueError"


@pytest.mark.integration
async def test_real_php_uses_local_alias_for_breakpoint_source_and_snapshot(ddev_runtime, tmp_path):
    from .test_integration import php, output

    path = tmp_path / "café fixture.php"
    path.write_text('<?php\n$value = 42;\n$result = $value + 1;\necho json_encode(["result" => $result]);\n')
    local = "/local/project/café fixture.php"
    async with Controller(port=0, path_mappings=[PathMapping("/local/project", tmp_path.as_uri())]) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            assert session.info.local_file == local
            assert session.info.file == path.as_uri()
            await session.set_breakpoint(local, 3)
            await session.run_until_break(timeout=5)
            snapshot = await session.snapshot(["$value"])
            assert snapshot.variables["$value"].value == 42
            assert snapshot.frames[0].local_file == local
            assert snapshot.execution.local_file == local
            assert b"$value = 42" in await session.source(local)
            await session.set_value("$value", 50)
            await session.detach()
            assert json.loads(await output(process))["result"] == 51


@pytest.mark.integration
@pytest.mark.browser
async def test_real_browser_uses_windows_local_paths_with_a_linux_debug_server(browser_page):
    from .test_browser import LINE, ROOT, URL

    mappings = [PathMapping(r"C:\Work\site", ROOT.as_uri())]
    local = r"C:\Work\site\src\checkout.php"
    async with Server(port=0, path_mappings=mappings) as server, Client(server.url) as first:
        async with PlaywrightDebugger(browser_page, first) as debugger:
            paused = await debugger.goto(URL, breakpoints=[BreakpointSpec(local, LINE)], variables=["$discount"])
            assert paused.snapshot["execution"]["local_file"] == local
            assert paused.snapshot["frames"][0]["local_file"] == local
            assert paused.snapshot["execution"]["file"] == (ROOT / "src/checkout.php").as_uri()
            await first.aclose()
            async with Client(server.url) as later:
                remote = paused.session(later)
                assert (await remote.info())["execution"]["local_file"] == local
                await remote.set_value("$discount", 15)
                await remote.detach()
            assert (await paused.finished()).status == 200
            assert await browser_page.get_by_test_id("total").inner_text() == "£85"
