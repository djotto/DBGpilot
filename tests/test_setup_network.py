"""Setup contracts over real loopback HTTP/TCP and the actual CLI."""

import asyncio
from types import SimpleNamespace

import pytest

from dbgpilot import Client, DebuggerSetup, Server, SetupError
from tests.helpers import Engine


async def test_real_reused_server_and_sessions_survive_setup_exit():
    async with Server(port=0, xdebug_port=0, token="test") as server:
        setup = DebuggerSetup(url=server.url, token="test")
        engine = await Engine.connect(server.controller)
        try:
            async with setup:
                remote = await setup.client.wait_for_session(timeout=2)
                session_id = remote.id
            async with Client(server.url, token="test") as later:
                assert (await later.session(session_id).info())["state"] == "starting"
                assert (await later.health())["live_sessions"] == 1
        finally:
            await engine.close()


async def test_real_authentication_rejection_does_not_stop_reused_server():
    async with Server(port=0, xdebug_port=0, token="correct-token") as server:
        setup = DebuggerSetup(url=server.url, token="incorrect-token")
        with pytest.raises(SetupError, match="Authentication"):
            await setup.start()
        async with Client(server.url, token="correct-token") as later:
            assert (await later.health())["status"] == "ok"


async def test_actual_cli_owned_server_survives_and_shutdown_releases_session():
    setup = DebuggerSetup(launch=True, port=0, xdebug_port=0, token="test")
    engine = None
    try:
        async with setup:
            health = await setup.health()
            engine = await Engine.connect(SimpleNamespace(host=health["xdebug_host"], port=health["xdebug_port"]))
            session_id = (await setup.client.wait_for_session(timeout=2)).id
        async with Client(setup.url, token="test") as later:
            assert (await later.session(session_id).info())["state"] == "starting"
        await setup.shutdown(release_sessions=True)
        assert setup._process.returncode == 0
        assert await asyncio.wait_for(engine.reader.read(), 2) == b""
    finally:
        await setup.shutdown(release_sessions=True)
        if engine:
            await engine.close()


async def test_competing_launch_cannot_attach_to_or_stop_existing_server():
    owner = await DebuggerSetup(launch=True, port=0, xdebug_port=0).start()
    try:
        contender = DebuggerSetup(launch=True, port=owner.client.port, xdebug_port=0)
        with pytest.raises(SetupError, match="occupied"):
            await contender.start()
        assert contender._process.returncode != 0
        assert (await owner.health())["status"] == "ok"
    finally:
        await owner.shutdown(release_sessions=True)


async def test_concurrent_launches_are_independent_and_same_handle_start_is_serialized():
    first = DebuggerSetup(launch=True, port=0, xdebug_port=0)
    second = DebuggerSetup(launch=True, port=0, xdebug_port=0)
    try:
        a, b, c = await asyncio.gather(first.start(), first.start(), second.start())
        assert a is b and a.pid != c.pid and a.url != c.url
        await first.shutdown(release_sessions=True)
        assert (await second.health())["status"] == "ok"
    finally:
        await first.shutdown(release_sessions=True)
        await second.shutdown(release_sessions=True)
