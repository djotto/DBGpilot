"""Real browser/PHP evidence for shutdown during an active capture."""

import asyncio

import pytest

from dbgpilot import Client, PlaywrightDebugger, Server, Session
from .test_browser import BREAKPOINT, URL

pytestmark = [pytest.mark.integration, pytest.mark.browser]


async def test_closing_helper_during_setup_releases_real_php(browser_page, monkeypatch):
    entered = asyncio.Event()
    async def pending_breakpoint(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(Session, "set_breakpoint", pending_breakpoint)
    async with Server(port=0) as server, Client(server.url) as client:
        debugger = PlaywrightDebugger(browser_page, client)
        capture = asyncio.create_task(debugger.goto(URL, breakpoints=[BREAKPOINT]))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await debugger.aclose()
            with pytest.raises(asyncio.CancelledError):
                await capture
            assert (await client.health())["live_sessions"] == 0
            await browser_page.get_by_test_id("total").wait_for()
            assert await browser_page.get_by_test_id("total").inner_text() == "£90"
        finally:
            capture.cancel()
            await asyncio.gather(capture, return_exceptions=True)
            await debugger.aclose()


async def test_unavailable_server_cleanup_reports_failure_and_settles_action(browser_page):
    async with Server(port=0) as server, Client(server.url) as client:
        debugger = PlaywrightDebugger(browser_page, client)
        paused = await debugger.goto(URL, breakpoints=[BREAKPOINT])
        await server.aclose()
        async with asyncio.timeout(6):
            with pytest.raises(ExceptionGroup, match="cleanup failed"):
                await debugger.aclose()
        assert paused.action.done()
        assert not debugger._captures
