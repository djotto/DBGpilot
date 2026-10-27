import asyncio
import os

import pytest

from dbgpilot import Client, Controller, PlaywrightDebugger, RemoteError, Server
from .helpers import Engine, xml
from .test_browser import BREAKPOINT, URL

pytestmark = pytest.mark.stress


async def test_64_pending_waits_do_not_starve_health_or_cancellation():
    async with asyncio.timeout(15), Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        pending = [client.request("wait_for_session", idekey=str(i), timeout=30) for i in range(64)]
        while len(server._request_ids) < 64:
            await asyncio.sleep(0.01)
        assert (await client.health())["status"] == "ok"
        acknowledgements = await asyncio.gather(*(item.cancel() for item in pending))
        assert all(item["cancelled"] for item in acknowledgements)
        results = await asyncio.gather(*(item.result() for item in pending), return_exceptions=True)
        assert all(isinstance(item, RemoteError) and item.code == -32010 for item in results)
        assert not server._request_ids


async def test_parallel_sessions_reconnect_and_replay_independently():
    async with asyncio.timeout(15), Server(port=0, controller=Controller(port=0, features={})) as server:
        engines = await asyncio.gather(*(Engine.connect(server.controller, idekey=str(i)) for i in range(8)))
        try:
            async with Client(server.url) as first:
                sessions = await asyncio.gather(*(first.wait_for_session(idekey=str(i), timeout=5) for i in range(8)))
                runs = [remote.request("run", timeout=30) for remote in sessions]
                requests = await asyncio.gather(*(engine.next_request() for engine in engines))
                await first.aclose()
                results = await asyncio.gather(*(run.result() for run in runs), return_exceptions=True)
                assert all(isinstance(item, RemoteError) and item.code == -32010 for item in results)
            async with Client(server.url) as later:
                for engine, request, session in zip(engines, requests, sessions):
                    await engine.respond(request, status="break", reason="ok")
                    remote = later.session(session.id)
                    assert (await remote.events(timeout=2))["events"][-1]["type"] == "StoppedEvent"
                    assert (await remote.info())["info"]["idekey"] == session.initial_info["info"]["idekey"]
                    await remote.detach()
                assert (await later.health())["live_sessions"] == 0
        finally:
            await server.aclose()
            await asyncio.gather(*(engine.close() for engine in engines))


@pytest.mark.integration
@pytest.mark.browser
async def test_four_browser_requests_pause_and_resume_independently(browser_page):
    pages = [browser_page] + [await browser_page.context.new_page() for _ in range(3)]
    async with asyncio.timeout(30), Server(port=0) as server, Client(server.url) as client:
        debuggers = [PlaywrightDebugger(page, client) for page in pages]
        try:
            paused = await asyncio.gather(*(debugger.goto(URL, breakpoints=[BREAKPOINT], variables=["$discount"], timeout=15)
                                            for debugger in debuggers))
            assert len({item.session_id for item in paused}) == 4
            infos = await asyncio.gather(*(item.session().info() for item in paused))
            assert len({info["info"]["idekey"] for info in infos}) == 4
            assert all(not item.action.done() for item in paused)
            for i, item in enumerate(paused):
                assert await item.session().set_value("$discount", i + 1)
                await item.session().detach()
            await asyncio.gather(*(item.finished() for item in paused))
            assert [await page.get_by_test_id("total").inner_text() for page in pages] == ["£99", "£98", "£97", "£96"]
        finally:
            await asyncio.gather(*(debugger.aclose() for debugger in debuggers))
            await asyncio.gather(*(page.close() for page in pages[1:]))


@pytest.mark.integration
@pytest.mark.browser
async def test_long_pause_survives_client_disconnect_without_navigation_timeout(browser_page):
    seconds = float(os.environ.get("DBGPILOT_TEST_PAUSE_SECONDS", "35"))
    assert seconds > 0
    async with Server(port=0) as server, Client(server.url) as first:
        async with PlaywrightDebugger(browser_page, first) as debugger:
            paused = await debugger.goto(URL, breakpoints=[BREAKPOINT], variables=["$discount"])
            await first.aclose()
            await asyncio.sleep(seconds)
            assert not paused.action.done()
            async with Client(server.url) as later:
                remote = paused.session(later)
                assert (await remote.info())["state"] == "break"
                assert (await remote.property_get("$discount"))["value"] == 10
                await remote.detach()
            await paused.finished()
            assert await browser_page.get_by_test_id("total").inner_text() == "£90"


@pytest.mark.integration
@pytest.mark.browser
async def test_server_restart_releases_browser_and_invalidates_old_ids(browser_page):
    server = await Server(port=0).start()
    client = Client(server.url)
    debugger = PlaywrightDebugger(browser_page, client)
    try:
        paused = await debugger.goto(URL, breakpoints=[BREAKPOINT])
        url, port, id = server.url, server.port, paused.session_id
        await server.aclose()
        await paused.finished()
        assert await browser_page.get_by_test_id("total").inner_text() == "£90"
        async with Server(port=port) as replacement, Client(url) as later:
            with pytest.raises(RemoteError) as caught:
                await later.session(id).info()
            assert caught.value.code == -32001
            assert await later.sessions() == []
            await debugger.aclose()  # forgotten old IDs are safe to clean up
    finally:
        await debugger.aclose()
        await client.aclose()
        await server.aclose()
