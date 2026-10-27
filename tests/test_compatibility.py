"""Actual installed PHPs plus checksum-pinned historical Xdebug modules."""

import asyncio
import base64
from contextlib import suppress
import json
from pathlib import Path
import subprocess

import pytest

from dbgpilot import Client, Server

pytestmark = [pytest.mark.integration, pytest.mark.compatibility]
CACHE = Path("/mnt/ddev-global-cache/dbgpilot/runtimes")
TARGETS = [(f"8.{minor}", "3.5.3", False) for minor in range(2, 6)] + [
    ("8.2", "3.3.2", True), ("8.3", "3.4.7", True),
]


@pytest.mark.parametrize("php_version,xdebug_version,historical", TARGETS,
                         ids=[f"php{php}-xdebug{xd}" for php, xd, _ in TARGETS])
async def test_real_runtime_round_trip(ddev_runtime, tmp_path, php_version, xdebug_version, historical):
    args = [f"/usr/bin/php{php_version}"]
    if historical:
        module = CACHE / f"php{php_version}-xdebug{xdebug_version}.so"
        assert module.exists(), "Run ddev test-setup before the compatibility suite"
        args += ["-n", "-d", f"zend_extension={module}"]
    info = json.loads(subprocess.check_output(args + ["-r", "echo json_encode([PHP_VERSION, phpversion('xdebug')]);"]))
    assert info[0].startswith(php_version + ".") and info[1] == xdebug_version
    report = Path("test-results/compatibility.json")
    report.parent.mkdir(exist_ok=True)
    reports = json.loads(report.read_text()) if report.exists() else {}
    key = f"PHP {info[0]} / Xdebug {info[1]}"
    reports[key] = {"php": info[0], "xdebug": info[1], "status": "running"}
    report.write_text(json.dumps(reports, indent=2) + "\n")
    path = tmp_path / "compatibility é.php"
    code = '''<?php
function calculate($subtotal, $discount) {
    $data = ["a\\0b" => 1, "é" => 2];
    $binary = "\\xff\\x00";
    $many = range(0, 69);
    $long = str_repeat("abc", 1024);
    $total = $subtotal - $discount; // BREAK
    return $total;
}
echo json_encode(["total" => calculate(100, 10)]);
'''
    path.write_text(code)
    line = next(i for i, text in enumerate(code.splitlines(), 1) if "// BREAK" in text)
    process = None
    try:
        async with asyncio.timeout(20), Server(port=0, xdebug_port=0) as server:
            process = await asyncio.create_subprocess_exec(
                *args, "-d", "xdebug.mode=debug", "-d", "xdebug.start_with_request=yes",
                "-d", "xdebug.client_host=127.0.0.1", "-d", f"xdebug.client_port={server.controller.port}",
                "-d", "xdebug.idekey=compatibility", str(path),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            async with Client(server.url) as first:
                remote = await first.wait_for_session(idekey="compatibility", timeout=5)
                assert (await remote.info())["info"]["engine_version"] == xdebug_version
                await remote.set_breakpoint(path, line, condition="$discount === 10")
                snapshot = await remote.break_and_return(["$subtotal", "$discount", "$data", "$binary"])
                assert snapshot["variables"]["$discount"]["value"] == 10
                assert snapshot["variables"]["$binary"]["value"] == {"encoding": "base64", "data": "/wA="}
                assert snapshot["variables"]["$data"]["children"][0]["name"] == "a\0b"
                assert snapshot["variables"]["$data"]["children"][1]["name"] == "é"
                id = remote.id
            async with Client(server.url) as later:
                remote = later.session(id)
                assert (await remote.call("stack_depth")) == 2
                assert (await remote.evaluate("$subtotal - $discount"))["value"] == 90
                assert await remote.call("typemap_get")
                children = await remote.call("property_children", name="$many")
                assert [child["value"] for child in children] == list(range(70))
                value = await remote.call("property_value_info", name="$long")
                assert base64.b64decode(value["data"]["data"]) == b"abc" * 1024
                assert value["size"] == 3072 and not value["truncated"]
                assert await remote.set_value("$discount", 15)
                await remote.step_over()
                assert (await remote.property_get("$total"))["value"] == 85
                await remote.detach()
            stdout, stderr = await process.communicate()
            assert process.returncode == 0, stderr.decode()
            assert json.loads(stdout)["total"] == 85
        reports[key]["status"] = "passed"
    except BaseException:
        reports[key]["status"] = "failed"
        raise
    finally:
        report.write_text(json.dumps(reports, indent=2) + "\n")
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.communicate()
