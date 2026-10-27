"""Exercise the independent controller against actual PHP/Xdebug in DDEV."""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.request import ProxyHandler, build_opener

import pytest

from dbgpilot import Client, CommandError, Controller, SessionStateError, StreamEvent

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def require_ddev():
    if not os.environ.get("DDEV_SITENAME"):
        pytest.skip("Run live tests with ddev poetry run pytest -m integration")
    assert shutil.which("php"), "PHP is required inside DDEV"
    result = subprocess.run(
        ["php", "-r", "echo extension_loaded('xdebug') ? 'yes' : 'no';"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout == "yes", "Enable Xdebug in DDEV"


@asynccontextmanager
async def php(controller, path, *args, idekey="dbgpilot"):
    process = await asyncio.create_subprocess_exec(
        "php", "-d", "xdebug.mode=debug", "-d", "xdebug.start_with_request=yes",
        "-d", "xdebug.client_host=127.0.0.1", "-d", f"xdebug.client_port={controller.port}",
        "-d", f"xdebug.idekey={idekey}", str(path), *map(str, args),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        yield process
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                async with asyncio.timeout(3):
                    await process.communicate()
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.communicate()


async def output(process):
    async with asyncio.timeout(5):
        stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode(errors="replace")
    return stdout


def write_php(tmp_path, code):
    path = tmp_path / "fixture with spaces.php"
    path.write_text(code)
    line = next(i for i, text in enumerate(code.splitlines(), 1) if "// BREAK" in text)
    return path, line


async def test_inspection_snapshot_paging_mutation_and_step(tmp_path):
    code = '''<?php
class ExampleItem {
    private string $secret = "value";
}
$outer = 42;
function calculate($subtotal, $discount) {
    $data = ["a\\0b" => 1, "é" => "text"];
    $binary = "\\xff\\x00";
    $many = range(0, 69);
    $long = str_repeat("abc", 1024);
    $object = new ExampleItem();
    $é = 123;
    $total = $subtotal - $discount; // BREAK
    return $total;
}
$result = calculate(100, 10);
echo json_encode(["total" => $result]);
'''
    path, line = write_php(tmp_path, code)
    async with asyncio.timeout(25), Controller(port=0) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            assert session.info.protocol_version == "1.0"
            assert session.info.language == "PHP"
            assert session.info.engine == "Xdebug"
            assert session.capabilities["encoding"].value == "iso-8859-1"
            assert session.supports_command("eval") and session.supports_command("detach")
            assert (await session.status()).status == "starting"
            mappings = await session.typemap_get()
            assert any(mapping.language_type == "int" for mapping in mappings)
            bp = await session.set_breakpoint(path, line)
            listed = await session.breakpoints()
            assert any(item.id == bp.id for item in listed)
            assert (await session.get_breakpoint(bp.id)).line == line
            stopped = await session.run_until_break()
            assert stopped.line == line
            assert stopped.file == path.as_uri()
            assert session.state == "break"
            assert await session.stack_depth() == 2
            assert (await session.status()).paused
            assert (await session.property_get("$é")).name == "$é"
            assert (await session.property_get("$é")).value == 123
            assert any("private" in child.facets for child in (await session.property_get("$object")).children)

            snapshot = await session.snapshot(
                ["$subtotal", "$discount", "$data", "$binary"],
                expressions=["$subtotal - $discount"],
            )
            assert snapshot.variables["$subtotal"].value == 100
            assert snapshot.variables["$discount"].value == 10
            assert snapshot.variables["$binary"].value == b"\xff\0"
            assert snapshot.variables["$data"].children[0].name == "a\0b"
            assert snapshot.variables["$data"].children[1].name == "é"
            assert (await session.property_get(snapshot.variables["$data"].children[0].fullname)).value == 1
            assert snapshot.expressions["$subtotal - $discount"].value == 90
            assert snapshot.frames[0].function == "calculate"
            json.dumps(snapshot.to_dict(), allow_nan=False)
            # Returning a snapshot must leave the session available for new decisions.
            assert (await session.property_get("$outer", depth=1)).value == 42
            with pytest.raises(ValueError, match="current frame"):
                await session.evaluate("$outer + 1", depth=1)
            assert any(prop.name == "$subtotal" for prop in await session.context())
            assert "Locals" in (await session.contexts()).values()
            assert b"function calculate" in await session.source(path)

            await session.feature_set("max_children", 8)
            first_page = await session.property_get("$many")
            assert first_page.children_truncated
            assert len(first_page.children) == 8
            children = await session.property_children("$many")
            assert [prop.value for prop in children] == list(range(70))

            await session.feature_set("max_data", 16)
            truncated = await session.property_get("$long")
            assert truncated.value_truncated
            assert await session.property_value("$long") == b"abc" * 1024
            value = await session.property_value_info("$long")
            assert value.size == 3072 and not value.truncated
            assert await session.set_value("$binary", b"\0\xff")
            assert (await session.property_get("$binary")).value == b"\0\xff"
            assert await session.set_value("$binary", b"")
            assert (await session.property_get("$binary")).value == ""
            assert await session.set_value("$binary", "café")
            assert (await session.property_get("$binary")).value == "café"
            assert await session.property_set("$discount", "15", type="int")
            await session.step_over()
            assert (await session.property_get("$total")).value == 85
            # A prior snapshot is a copied value, not a live reference.
            assert snapshot.variables["$discount"].value == 10
            await session.detach()
            assert json.loads(await output(process)) == {"total": 85}


async def test_conditional_breakpoint_updates_and_output_events(tmp_path):
    path, line = write_php(tmp_path, '''<?php
for ($i = 0; $i < 4; $i++) {
    $value = $i; // BREAK
}
echo "finished";
''')
    async with asyncio.timeout(20), Controller(port=0) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            bp = await session.set_breakpoint(path, line, condition="$i === 2")
            await session.update_breakpoint(bp.id, state="disabled")
            assert (await session.get_breakpoint(bp.id)).state == "disabled"
            await session.update_breakpoint(bp.id, state="enabled")
            await session.run_until_break()
            assert (await session.property_get("$i")).value == 2
            await session.remove_breakpoint(bp.id)
            assert not await session.breakpoints()
            assert await session.set_output("stdout", mode=1)
            result = await session.run()
            assert result.status == "stopping"
            streams = []
            # Stop events and breakpoint-resolution notifications may precede stdout.
            while True:
                event = await session.next_event(timeout=2)
                if isinstance(event, StreamEvent):
                    streams.append(event.data)
                    break
            assert b"".join(streams) == b"finished"
            await session.detach()
            assert await output(process) == b"finished"


async def test_exception_breakpoint_and_engine_errors(tmp_path):
    path, _ = write_php(tmp_path, '''<?php
try {
    throw new RuntimeException("example"); // BREAK
} catch (RuntimeException $error) {
    echo "caught";
}
''')
    async with asyncio.timeout(20), Controller(port=0) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            await session.set_breakpoint(kind="exception", exception="RuntimeException")
            result = await session.run_until_break()
            assert result.exception == "RuntimeException"
            with pytest.raises(CommandError):
                await session.evaluate("this is not valid PHP!")
            assert not session.closed
            await session.detach()
            assert await output(process) == b"caught"


async def test_two_php_sessions_can_remain_paused_independently(tmp_path):
    path, line = write_php(tmp_path, '''<?php
$number = (int) $argv[1];
$result = $number * 2; // BREAK
echo $result;
''')
    async with asyncio.timeout(20), Controller(port=0) as controller:
        async with php(controller, path, 10, idekey="first") as first:
            async with php(controller, path, 20, idekey="second") as second:
                sessions = [await controller.wait_for_session(timeout=5) for _ in range(2)]
                by_key = {session.info.idekey: session for session in sessions}
                for session in sessions:
                    await session.set_breakpoint(path, line)
                await asyncio.gather(*(session.run_until_break() for session in sessions))
                assert (await by_key["first"].property_get("$number")).value == 10
                assert (await by_key["second"].property_get("$number")).value == 20
                await by_key["second"].detach()
                assert await output(second) == b"40"
                assert by_key["first"].state == "break"
                await by_key["first"].detach()
                assert await output(first) == b"20"


async def test_real_http_request_returns_snapshot_before_response():
    path = ROOT / "src/checkout.php"
    line = next(i for i, text in enumerate(path.read_text().splitlines(), 1) if "// BREAKPOINT:" in text)

    def request():
        opener = build_opener(ProxyHandler({}))
        with opener.open("http://127.0.0.1/?code=SAVE10&format=json&XDEBUG_TRIGGER=1", timeout=15) as response:
            return json.load(response)

    async with asyncio.timeout(20), Controller(port=9003) as controller:
        request_task = asyncio.create_task(asyncio.to_thread(request))
        try:
            session = await controller.wait_for_session(timeout=5)
            await session.set_breakpoint(path, line)
            await session.run_until_break()
            snapshot = await session.snapshot(["$subtotal", "$discount"])
            assert snapshot.variables["$discount"].value == 10
            assert not request_task.done()
            assert (await session.evaluate("$subtotal - $discount")).value == 90
            await session.detach()
            assert (await request_task)["total"] == 90
        finally:
            await controller.aclose()
            await asyncio.gather(request_task, return_exceptions=True)


async def test_temporary_hit_count_breakpoint_and_step_into_out(tmp_path):
    path, line = write_php(tmp_path, '''<?php
function double_number($number) {
    return $number * 2;
}
for ($i = 0; $i < 4; $i++) {
    $result = double_number($i); // BREAK
    $after = $result;
}
echo $result;
''')
    async with asyncio.timeout(20), Controller(port=0) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            bp = await session.set_breakpoint(path, line, hit_value=3, hit_condition="==")
            await session.run_until_break()
            assert (await session.property_get("$i")).value == 2
            assert (await session.get_breakpoint(bp.id)).hit_count == 3
            await session.remove_breakpoint(bp.id)
            await session.step_into()
            assert (await session.stack())[0].function == "double_number"
            assert (await session.property_get("$number")).value == 2
            await session.step_out()
            assert (await session.property_get("$result")).value == 4
            temporary = await session.set_breakpoint(path, line, temporary=True)
            await session.run_until_break()
            assert (await session.property_get("$i")).value == 3
            assert (await session.get_breakpoint(temporary.id)).state == "disabled"
            await session.detach()
            assert await output(process) == b"6"


async def test_live_stop_and_capability_gating(tmp_path):
    path, line = write_php(tmp_path, '''<?php
function work() {
    $value = 1; // BREAK
    echo "must not finish";
}
work();
''')
    async with asyncio.timeout(20), Controller(port=0) as controller:
        async with php(controller, path) as process:
            session = await controller.wait_for_session(timeout=5)
            assert not session.supports_async
            assert not session.supports_command("interact")
            with pytest.raises(SessionStateError, match="watch"):
                await session.set_breakpoint(kind="watch", condition="$value")
            bp = await session.set_breakpoint(kind="call", function="work", state="disabled")
            record = await session.get_breakpoint(bp.id)
            assert record.function == "work" and record.state == "disabled"
            await session.remove_breakpoint(bp.id)
            await session.set_breakpoint(path, line)
            await session.run_until_break()
            result = await session.stop()
            assert result.status == "stopped" and session.closed
            async with asyncio.timeout(5):
                stdout, stderr = await process.communicate()
            assert b"must not finish" not in stdout
            assert not stderr


async def test_server_process_returns_snapshot_then_another_client_controls_http(tmp_path):
    """The controller, returning client, and later client have separate lifetimes."""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dbgpilot", "serve", "--port", "0", "--xdebug-port", "9003",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    request = None
    try:
        async with asyncio.timeout(25):
            ready = json.loads(await process.stdout.readline())
            assert ready["event"] == "ready"

            def get_checkout():
                opener = build_opener(ProxyHandler({}))
                with opener.open("http://127.0.0.1/?code=SAVE10&format=json&XDEBUG_TRIGGER=1", timeout=20) as response:
                    return json.load(response)

            request = asyncio.create_task(asyncio.to_thread(get_checkout))
            async with Client(ready["url"]) as first:
                remote = await first.wait_for_session(timeout=5)
                id = remote.id

            async def cli(method, params):
                child = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "dbgpilot", "call", method, "--url", ready["url"],
                    "--session", id, "--params", json.dumps(params),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await child.communicate()
                    assert child.returncode == 0, stderr.decode()
                    return json.loads(stdout)
                finally:
                    if child.returncode is None:
                        child.kill()
                        await child.communicate()

            path = ROOT / "src/checkout.php"
            line = next(i for i, text in enumerate(path.read_text().splitlines(), 1) if "// BREAKPOINT:" in text)
            await cli("session.set_breakpoint", {"file": str(path), "line": line})
            snapshot = await cli("session.break_and_return", {
                "variables": ["$subtotal", "$discount"], "expressions": ["$subtotal - $discount"], "timeout": 5,
            })
            assert snapshot["session_id"] == id
            assert snapshot["variables"]["$discount"]["value"] == 10
            assert snapshot["expressions"]["$subtotal - $discount"]["value"] == 90
            assert not request.done() and process.returncode is None
            # The snapshot-producing client process has exited; PHP is still paused.
            async with Client(ready["url"]) as later:
                remote = later.session(id)
                assert (await remote.info())["state"] == "break"
                assert await remote.set_value("$discount", 15)
                await remote.step_over(timeout=5)
                assert (await remote.property_get("$total"))["value"] == 85
                assert snapshot["variables"]["$discount"]["value"] == 10
                await remote.detach()
                events = await remote.events(after=0, timeout=2)
                assert any(event["type"] == "StoppedEvent" for event in events["events"])
            assert (await request)["total"] == 85
    finally:
        if process.returncode is None:
            process.terminate()
        async with asyncio.timeout(5):
            _, stderr = await process.communicate()
        if request is not None:
            await asyncio.gather(request, return_exceptions=True)
    assert process.returncode == 0, stderr.decode()
