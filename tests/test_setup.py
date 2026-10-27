"""Public setup contracts, child ownership, failures, and real HTTP reuse."""

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dbgpilot import Client, DebuggerSetup, PathMapper, PlaywrightDebugger, SetupConfig, SetupError
from dbgpilot.cli import _settings
from dbgpilot.config import load_config
from dbgpilot.wire import RemoteError


def test_configuration_precedence_and_relative_paths(tmp_path, monkeypatch):
    config = tmp_path / "dbgpilot.toml"
    config.write_text('''[connection]
url = "http://localhost:8123"
timeout = 42
token_env = "DBGPILOT_TEST_SECRET"
[startup]
launch = true
timeout = 7
python = ".venv/bin/python"
working_directory = "app"
[listener]
port = 0
xdebug_host = "0.0.0.0"
xdebug_port = 9011
[[path_mappings]]
local = "."
remote = "file:///app"
''')
    monkeypatch.setenv("DBGPILOT_TEST_SECRET", "hidden-secret")
    monkeypatch.chdir(tmp_path)
    plain = DebuggerSetup()
    assert not plain.config.launch
    discovered = DebuggerSetup(discover=True, launch=False, request_timeout=12)
    assert not discovered.config.launch and discovered.config.request_timeout == 12
    assert discovered.config.startup_timeout == 7
    assert discovered.config.python == str(tmp_path / ".venv/bin/python")
    assert discovered.config.working_directory == str(tmp_path / "app")
    assert discovered.config.token == "hidden-secret"
    assert "hidden-secret" not in repr(discovered.config)
    assert PathMapper.from_file(config).to_remote(tmp_path / "a.php") == "file:///app/a.php"
    assert not DebuggerSetup(config=False, discover=True).config.launch
    existing = SetupConfig()
    assert load_config(existing) is existing
    args = SimpleNamespace(config=config, no_config=False, command="serve", host=None,
                           port=8124, xdebug_host=None, xdebug_port=None, token=None)
    assert _settings(args).port == 8124
    monkeypatch.setenv("DBGPILOT_TOKEN", "environment-token")
    assert _settings(args).token == "environment-token"
    args.token = "explicit-token"
    assert _settings(args).token == "explicit-token"
    args = SimpleNamespace(config=config, no_config=False, command="call", url="http://localhost:8999",
                           token=None, request_timeout=15)
    assert _settings(args).url == "http://localhost:8999"
    assert _settings(args).request_timeout == 15
    args.no_config = True
    assert _settings(args).path_mapper.mappings == ()


@pytest.mark.parametrize("body", [
    '[connection]\nunknown=1', '[startup]\nlaunch="yes"', '[listener]\nport=true',
    '[connection]\ntimeout=0', '[startup]\ntimeout=inf', '[listener]\nxdebug_port=65536',
    'startup="bad"', '[startup]\npython=23', '[startup]\nworking_directory=false',
    '[connection]\ntoken_env=3', '[connection]\nurl="https://localhost"',
])
def test_invalid_setup_configuration(tmp_path, body):
    config = tmp_path / "dbgpilot.toml"
    config.write_text(body)
    with pytest.raises(ValueError):
        SetupConfig.from_file(config)


async def test_reuse_health_uses_supplied_endpoint_not_advertised_container_url(monkeypatch):
    health = AsyncMock(return_value={"status": "ok", "protocol": "dbgpilot/1", "url": "http://internal:9004"})
    monkeypatch.setattr(Client, "health", health)
    setup = DebuggerSetup(url="http://external:8111")
    async with setup:
        assert setup.url == "http://external:8111"
        assert not setup.owns_server
        with pytest.raises(SetupError, match="does not own"):
            await setup.shutdown(release_sessions=True)
    assert setup.client._closed
    with pytest.raises(SetupError, match="closed"):
        await setup.start()


@pytest.mark.parametrize("result, message", [
    ({"status": "ok", "protocol": "other/2", "url": "http://localhost"}, "Incompatible"),
    (RemoteError(-32009, "secret-token"), "Authentication"),
    (OSError("secret-token"), "Cannot reach"),
])
async def test_reuse_failure_diagnostics_are_sanitized(monkeypatch, result, message):
    health = AsyncMock(**({"side_effect": result} if isinstance(result, Exception) else {"return_value": result}))
    monkeypatch.setattr(Client, "health", health)
    setup = DebuggerSetup(token="secret-token")
    with pytest.raises(SetupError, match=message) as caught:
        await setup.start()
    assert "secret-token" not in str(caught.value)
    assert setup.client._closed


async def test_readiness_deadline_is_bounded(monkeypatch):
    async def hang(self):
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "health", hang)
    setup = DebuggerSetup(startup_timeout=0.02)
    with pytest.raises(SetupError, match="deadline"):
        await setup.start()
    assert setup.client._closed


async def test_capture_deadline_reports_routing_trigger_and_mapping_checks(monkeypatch):
    async def hang(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "wait_for_session", hang)
    page = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock())
    async with Client() as client, PlaywrightDebugger(page, client) as debugger:
        with pytest.raises(TimeoutError) as caught:
            await debugger.capture(lambda: asyncio.Event().wait(), url_pattern="**/checkout", timeout=0.02)
        note = caught.value.__notes__[0]
        assert "XDEBUG_TRIGGER" in note and "path mappings" in note and "action deadlines" in note
        page.unroute.assert_awaited_once()


@pytest.fixture
def child_python(tmp_path):
    """A real child process with CLI readiness output but no network requirement."""
    path = tmp_path / "python"
    path.write_text(f'''#!{sys.executable}
import json, os, signal, time
signal.signal(signal.SIGTERM, lambda *args: exit(0))
print(json.dumps({{"event":"ready", "pid":os.getpid(), "instance_id":"child-id",
                  "url":"http://127.0.0.1:9999", "protocol":"dbgpilot/1", "status":"ok"}}), flush=True)
while True: time.sleep(.01)
''')
    path.chmod(0o700)
    return str(path)


async def test_owned_child_survives_client_exit_and_only_explicit_shutdown_stops_it(child_python, monkeypatch):
    monkeypatch.setattr(Client, "health", AsyncMock(return_value={
        "status": "ok", "protocol": "dbgpilot/1", "url": "http://127.0.0.1:9999", "instance_id": "child-id"}))
    setup = DebuggerSetup(launch=True, python=child_python)
    try:
        async with setup:
            assert setup.owns_server and setup.pid
            assert (await setup.health())["instance_id"] == "child-id"
            assert await setup.start() is setup
        assert setup._process.poll() is None
        assert not setup._settings_file.exists()
        with pytest.raises(SetupError, match="release_sessions=True"):
            await setup.shutdown()
        assert setup._process.poll() is None
    finally:
        await setup.shutdown(release_sessions=True)
    assert setup._process.poll() == 0
    await setup.shutdown(release_sessions=True)


async def test_mismatched_identity_cleans_child(child_python, monkeypatch):
    monkeypatch.setattr(Client, "health", AsyncMock(return_value={
        "status": "ok", "protocol": "dbgpilot/1", "url": "http://127.0.0.1:9999", "instance_id": "other"}))
    setup = DebuggerSetup(launch=True, python=child_python)
    with pytest.raises(SetupError, match="different server"):
        await setup.start()
    assert setup._process.poll() == 0


async def test_cancellation_during_startup_reaps_child(child_python, monkeypatch):
    entered = asyncio.Event()
    async def hang(self):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "health", hang)
    setup = DebuggerSetup(launch=True, python=child_python)
    task = asyncio.create_task(setup.start())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup._process.poll() == 0
    assert not setup._settings_file.exists()
    assert setup.client._closed


async def test_cancellation_before_readiness_reaps_child(child_python, monkeypatch):
    entered = asyncio.Event()
    async def hang():
        entered.set()
        await asyncio.Event().wait()
    setup = DebuggerSetup(launch=True, python=child_python)
    monkeypatch.setattr(setup, "_read_ready", hang)
    task = asyncio.create_task(setup.start())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup._process.poll() is not None
    assert not setup._settings_file.exists()


async def test_cancelled_shutdown_still_reaps_owned_child(child_python, monkeypatch):
    monkeypatch.setattr(Client, "health", AsyncMock(return_value={
        "status": "ok", "protocol": "dbgpilot/1", "url": "http://127.0.0.1:9999", "instance_id": "child-id"}))
    setup = await DebuggerSetup(launch=True, python=child_python).start()
    entered, gate = asyncio.Event(), asyncio.Event()
    async def close():
        entered.set()
        await gate.wait()
    monkeypatch.setattr(setup.client, "aclose", close)
    task = asyncio.create_task(setup.shutdown(release_sessions=True))
    await entered.wait()
    task.cancel()
    gate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert setup._process.poll() == 0


@pytest.mark.parametrize("output, message", [
    ("invalid json\n", "invalid readiness"),
    (json.dumps({"event": "ready", "pid": -1, "instance_id": "wrong"}) + "\n", "identity"),
    ("a" * 65537, "oversized"),
], ids=["invalid-json", "wrong-pid", "oversized"])
async def test_bad_readiness_is_rejected_and_child_is_reaped(tmp_path, output, message):
    path = tmp_path / "python"
    path.write_text(f"#!{sys.executable}\nimport sys, time\nsys.stdout.write({output!r}); sys.stdout.flush()\ntime.sleep(30)\n")
    path.chmod(0o700)
    setup = DebuggerSetup(launch=True, python=str(path), startup_timeout=2)
    with pytest.raises(SetupError, match=message):
        await setup.start()
    assert setup._process.poll() is not None
    assert not setup._settings_file.exists()


async def test_missing_executable_cleans_launch_files():
    setup = DebuggerSetup(launch=True, python="/no/such/python")
    with pytest.raises(SetupError, match="executable"):
        await setup.start()
    assert setup._output.closed and setup._errors.closed
    assert not setup._settings_file.exists()


async def test_launched_config_preserves_resolved_mappings_and_ignores_ambient_config(child_python, tmp_path):
    mapper = PathMapper([{"local": ".", "remote": "file:///app", "remote_case_sensitive": True}], base_dir=tmp_path)
    setup = DebuggerSetup(launch=True, python=child_python, path_mapper=mapper)
    try:
        setup._launch()
        settings = SetupConfig.from_file(setup._settings_file)
        assert settings.path_mapper.to_remote(tmp_path / "a.php") == "file:///app/a.php"
        assert settings.path_mapper.mappings[0].remote_case_sensitive is True
    finally:
        await setup._failed_start()


async def test_unexpected_child_exit_is_reported(child_python, monkeypatch):
    monkeypatch.setattr(Client, "health", AsyncMock(return_value={
        "status": "ok", "protocol": "dbgpilot/1", "url": "http://127.0.0.1:9999", "instance_id": "child-id"}))
    setup = await DebuggerSetup(launch=True, python=child_python).start()
    setup._process.terminate()
    await asyncio.to_thread(setup._process.wait)
    with pytest.raises(SetupError, match="exited"):
        await setup.health()
    await setup.shutdown(release_sessions=True)


