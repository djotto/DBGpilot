"""Exercise the opt-in plugin in a separate pytest run with real child cleanup."""

import asyncio
import json
import os
import sys

import pytest


async def test_opt_in_fixtures_override_pages_and_only_stop_owned_children(tmp_path):
    child = tmp_path / "python"
    child.write_text(f'''#!{sys.executable}
import json, os, signal, time
signal.signal(signal.SIGTERM, lambda *args: exit(0))
print(json.dumps({{"event":"ready", "pid":os.getpid(), "instance_id":"test-child",
"url":"http://127.0.0.1:9999", "status":"ok", "protocol":"dbgpilot/1"}}), flush=True)
while True: time.sleep(.01)
''')
    child.chmod(0o700)
    (tmp_path / "pytest.ini").write_text('''[pytest]
asyncio_mode = auto
asyncio_default_fixture_loop_scope = function
filterwarnings = error
''')
    (tmp_path / "conftest.py").write_text('''import pytest
from unittest.mock import AsyncMock
from dbgpilot import Client
pytest_plugins = ["dbgpilot.pytest_plugin"]

@pytest.fixture(autouse=True)
def readiness(monkeypatch):
    monkeypatch.setattr(Client, "health", AsyncMock(return_value={
        "status":"ok", "protocol":"dbgpilot/1", "url":"http://127.0.0.1:9999",
        "instance_id":"test-child"}))

@pytest.fixture
def page():
    return object()

@pytest.fixture
def dbgpilot_options(request):
    return {"launch": request.param, "python": ''' + repr(str(child)) + '''}
''')
    report = tmp_path / "pids.jsonl"
    (tmp_path / "test_example.py").write_text('''import json
from pathlib import Path
import pytest

@pytest.mark.parametrize("dbgpilot_options", [True, False, True], indirect=True)
async def test_fixture(page, dbgpilot_setup, dbgpilot_debugger):
    assert dbgpilot_debugger.page is page
    assert dbgpilot_debugger.client is dbgpilot_setup.client
    with Path(''' + repr(str(report)) + ''').open("a") as target:
        target.write(json.dumps({"pid": dbgpilot_setup.pid}) + "\\n")
''')
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "pytest", "-q", str(tmp_path), cwd=tmp_path,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    async with asyncio.timeout(15):
        out, err = await process.communicate()
    assert process.returncode == 0, out.decode() + err.decode()
    pids = [json.loads(line)["pid"] for line in report.read_text().splitlines()]
    assert pids[0] and pids[1] is None and pids[2] and pids[0] != pids[2]
    for pid in (pids[0], pids[2]):
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
