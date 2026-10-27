"""Actual browser/PHP entry points, including the optional pytest fixtures."""

import pytest

from dbgpilot import Client, DebuggerSetup
from tests.test_browser import BREAKPOINT, URL

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@pytest.fixture
def dbgpilot_options():
    # The fixture explicitly owns an isolated API process. PHP in this harness
    # connects to fixed port 9003, so these live tests run sequentially.
    return {"launch": True, "port": 0}


@pytest.fixture
def dbgpilot_page(browser_page):
    return browser_page


async def check_pause_and_reconnect(page, setup, debugger):
    paused = await debugger.goto(URL, breakpoints=[BREAKPOINT], variables=["$discount"])
    assert paused.snapshot["variables"]["$discount"]["value"] == 10
    await setup.client.aclose()
    async with Client(setup.url, token=setup.config.token) as later:
        remote = later.session(paused.session_id)
        assert (await remote.info())["state"] == "break"
        assert await remote.set_value("$discount", 15)
        await remote.step_over()
        assert (await remote.property_get("$total"))["value"] == 85
        await remote.detach()
    await paused.finished()
    assert await page.get_by_test_id("total").inner_text() == "£85"


async def test_owned_setup_standalone_browser_entry(browser_page):
    setup = DebuggerSetup(launch=True, port=0)
    try:
        async with setup, setup.debugger(browser_page) as debugger:
            await check_pause_and_reconnect(browser_page, setup, debugger)
        async with Client(setup.url) as later:
            assert (await later.health())["status"] == "ok"
    finally:
        await setup.shutdown(release_sessions=True)


async def test_pytest_entry_capture_reconnect_mutation_and_dom(
        dbgpilot_page, dbgpilot_setup, dbgpilot_debugger):
    await check_pause_and_reconnect(dbgpilot_page, dbgpilot_setup, dbgpilot_debugger)


async def test_reused_setup_browser_entry(browser_page):
    owner = await DebuggerSetup(launch=True, port=0).start()
    try:
        async with DebuggerSetup(url=owner.url) as setup, setup.debugger(browser_page) as debugger:
            await check_pause_and_reconnect(browser_page, setup, debugger)
        assert (await owner.health())["status"] == "ok"
    finally:
        await owner.shutdown(release_sessions=True)
