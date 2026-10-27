"""Regressions for the four follow-up code-review findings (CR01–CR04).

The session probe uses real HTTP/TCP and a scripted engine, not PHP or Chromium.
"""

import asyncio
import errno
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dbgpilot import Client, DebuggerSetup, PathMapper, PlaywrightDebugger, Server, SetupConfig
from dbgpilot.cli import _settings
from .helpers import Engine, xml
from .test_server import request


async def test_cancelled_paused_close_still_allows_cleanup(monkeypatch):
    page = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock())
    entered, release = asyncio.Event(), asyncio.Event()
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        debugger = PlaywrightDebugger(page, client, idekey="test")
        engine = await Engine.connect(server.controller)
        capture = closing = None
        try:
            capture = asyncio.create_task(debugger.capture(
                lambda: asyncio.Event().wait(), url_pattern="**/*",
            ))
            run = await engine.next_request()
            assert run.name == "run"
            await engine.respond(run, status="break", reason="ok")
            stack = await engine.next_request()
            assert stack.name == "stack_get"
            await engine.respond(stack, payload=[
                xml("stack", level=0, filename="file:///app/index.php", lineno=9),
            ])
            paused = await asyncio.wait_for(capture, 2)
            original_close = debugger._close_session
            close_calls = []

            async def delayed_close(session_id):
                # Deterministically cancel before the cleanup RPC is sent.
                close_calls.append(session_id)
                entered.set()
                await release.wait()
                await original_close(session_id)

            monkeypatch.setattr(debugger, "_close_session", delayed_close)
            closing = asyncio.create_task(paused.close())
            await asyncio.wait_for(entered.wait(), 2)
            closing.cancel()
            async with asyncio.timeout(5):
                await asyncio.gather(closing, return_exceptions=True)
                assert not paused._closed
                assert paused in debugger._captures
                release.set()
                await asyncio.gather(paused.close(), debugger.aclose())
            info = await paused.session().info()
            assert info["closed"], "Cancelled close lost ownership of a live paused session"
            assert close_calls == [paused.session_id]
            assert paused._closed and paused.action.done()
            assert paused not in debugger._captures
        finally:
            release.set()
            tasks = [task for task in (capture, closing) if task is not None]
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await debugger.aclose()
            await engine.close()


@pytest.fixture
def missing_token_config(tmp_path, monkeypatch):
    monkeypatch.delenv("DBGPILOT_REVIEW_MISSING_TOKEN", raising=False)
    monkeypatch.delenv("DBGPILOT_TOKEN", raising=False)
    config = tmp_path / "dbgpilot.toml"
    config.write_text('[connection]\ntoken_env = "DBGPILOT_REVIEW_MISSING_TOKEN"\n')
    return config


@pytest.mark.parametrize("token", ["explicit-token", None], ids=["explicit-token", "explicit-no-token"])
def test_api_token_override_does_not_require_shadowed_environment(missing_token_config, token):
    setup = DebuggerSetup(config=missing_token_config, token=token)
    assert setup.config.token == token


@pytest.mark.parametrize("command", ["serve", "call"])
@pytest.mark.parametrize("token_source", ["argument", "environment"])
def test_cli_token_override_does_not_require_shadowed_environment(
    missing_token_config, monkeypatch, command, token_source,
):
    if token_source == "environment":
        monkeypatch.setenv("DBGPILOT_TOKEN", "override-token")
    args = SimpleNamespace(
        command=command, config=missing_token_config, no_config=False,
        host=None, port=None, xdebug_host=None, xdebug_port=None,
        url=None, request_timeout=None,
        token="override-token" if token_source == "argument" else None,
    )
    assert _settings(args).token == "override-token"


@pytest.mark.parametrize("loader", ["file", "setup", "cli"])
def test_missing_required_token_still_fails_without_override(missing_token_config, loader):
    with pytest.raises(ValueError, match="DBGPILOT_REVIEW_MISSING_TOKEN is unset"):
        if loader == "file":
            SetupConfig.from_file(missing_token_config)
        elif loader == "setup":
            DebuggerSetup(config=missing_token_config)
        else:
            _settings(SimpleNamespace(
                command="call", config=missing_token_config, no_config=False,
                url=None, token=None, request_timeout=None,
            ))


@pytest.mark.parametrize("directory", ["source-\U0001f600", 'source-"\\\t\n\x7f'], ids=["non-bmp", "escaped-controls"])
async def test_owned_launch_preserves_non_bmp_mapping_path(tmp_path, directory):
    local = tmp_path / directory
    mapper = PathMapper([{"local": str(local), "remote": "file:///app"}])
    setup = DebuggerSetup(launch=True, port=0, xdebug_port=0, path_mapper=mapper)
    try:
        await setup.start()
        assert (await setup.health())["status"] == "ok"
        assert await setup.client.to_remote(local / "index.php") == "file:///app/index.php"
    finally:
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)


async def test_alternative_loopback_listener_accepts_its_advertised_url():
    server = Server(host="127.0.0.2", port=0, xdebug_port=0)
    try:
        try:
            await server.start()
        except OSError as error:
            if error.errno == errno.EADDRNOTAVAIL:
                pytest.skip("127.0.0.2 is not configured on this host; exercise this case in DDEV")
            raise
        async with Client(server.url) as client:
            assert (await client.health())["status"] == "ok"
    finally:
        await server.aclose()


async def test_unconfigured_loopback_host_is_still_rejected():
    async with Server(port=0, xdebug_port=0) as server:
        status, response = await request(server.url, headers={"Host": "127.0.0.2"})
        assert status == 403
        assert response["error"]["message"] == "Invalid Host header"
