"""Real Chromium, PHP-FPM, Xdebug, server, and independently reconnecting clients."""

import asyncio
from pathlib import Path

import pytest

from dbgpilot import BreakpointSpec, Client, PlaywrightDebugger, RemoteError, Server

pytestmark = [pytest.mark.integration, pytest.mark.browser]
ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/checkout.php"
LINE = next(i for i, line in enumerate(TARGET.read_text().splitlines(), 1) if "// BREAKPOINT:" in line)
BREAKPOINT = BreakpointSpec(str(TARGET), LINE)
URL = "http://127.0.0.1/?code=SAVE10"


async def test_browser_returns_paused_snapshot_reconnects_mutates_and_checks_page(browser_page):
    async with Server(port=0) as server, Client(server.url) as first:
        async with PlaywrightDebugger(browser_page, first) as debugger:
            paused = await debugger.goto(URL, breakpoints=[BREAKPOINT], variables=["$subtotal", "$discount"])
            assert paused.snapshot["variables"]["$discount"]["value"] == 10
            assert paused.snapshot["execution"]["status"] == "break"
            assert not paused.action.done()
            id = paused.session_id
            await first.aclose()
            async with Client(server.url) as later:
                remote = paused.session(later)
                info = await remote.info()
                assert info["session_id"] == id and info["state"] == "break"
                assert info["info"]["idekey"].startswith("dbgpilot-")
                assert (await remote.evaluate("$subtotal - $discount"))["value"] == 90
                assert await remote.set_value("$discount", 15)
                await remote.step_over()
                assert (await remote.property_get("$total"))["value"] == 85
                await remote.detach()
                events = await paused.events(client=later, timeout=2)
                assert any(item["type"] == "StoppedEvent" for item in events["events"])
            assert (await paused.finished()).status == 200
            assert await browser_page.get_by_test_id("total").inner_text() == "£85"
            assert paused.snapshot["variables"]["$discount"]["value"] == 10


async def test_helper_coordinates_form_submission(browser_page):
    await browser_page.goto("http://127.0.0.1/")
    await browser_page.get_by_label("Discount code").fill("SAVE10")
    async with Server(port=0) as server, Client(server.url) as client:
        async with PlaywrightDebugger(browser_page, client) as debugger:
            paused = await debugger.capture(
                lambda: browser_page.get_by_role("button", name="Apply").click(timeout=0),
                url_pattern="http://127.0.0.1/**", breakpoints=[BREAKPOINT], variables=["$discount"],
            )
            assert paused.snapshot["variables"]["$discount"]["value"] == 10
            await paused.session().detach()
            await paused.finished()
            assert await browser_page.get_by_test_id("total").inner_text() == "£90"
            # Routing is removed; a subsequent normal navigation does not attach.
            await browser_page.goto("http://127.0.0.1/")
            assert (await client.health())["live_sessions"] == 0


async def test_successful_click_can_finish_before_its_ajax_breakpoint(browser_page):
    await browser_page.goto("http://127.0.0.1/")
    await browser_page.evaluate("""() => {
      const button = document.createElement('button');
      button.textContent = 'Load checkout';
      button.onclick = () => fetch('/?code=SAVE10&format=json').then(r => r.json()).then(data => {
        document.querySelector('[data-testid=total]').textContent = String(data.total);
      });
      document.body.append(button);
    }""")
    async with Server(port=0) as server, Client(server.url) as client:
        async with PlaywrightDebugger(browser_page, client) as debugger:
            paused = await debugger.capture(
                lambda: browser_page.get_by_role("button", name="Load checkout").click(),
                url_pattern=lambda url: "format=json" in url,
                breakpoints=[BREAKPOINT], variables=["$discount"],
            )
            await paused.finished()  # click completion is not PHP completion
            assert (await paused.session().info())["state"] == "break"
            await paused.session().detach()
            await browser_page.wait_for_function("document.querySelector('[data-testid=total]').textContent === '90'")


async def test_helper_timeout_cancels_attachment_and_removes_route(browser_page):
    async with Server(port=0) as server, Client(server.url) as client:
        async with PlaywrightDebugger(browser_page, client) as debugger:
            with pytest.raises(TimeoutError):
                await debugger.capture(lambda: asyncio.Event().wait(), url_pattern="**/*", timeout=0.1)
            assert await client.sessions() == []
            assert not server._request_ids
            await browser_page.goto(URL)
            assert (await client.health())["live_sessions"] == 0


async def test_browser_failure_releases_the_pending_session_wait(browser_page):
    from playwright.async_api import Error

    async with Server(port=0) as server, Client(server.url) as client:
        async with PlaywrightDebugger(browser_page, client) as debugger:
            with pytest.raises(Error):
                await debugger.goto("http://127.0.0.1:1/", breakpoints=[BREAKPOINT], timeout=3)
            assert not server._request_ids
            assert await client.sessions() == []


async def test_failed_setup_and_explicit_helper_cleanup_release_php(browser_page):
    requests = []
    browser_page.on("request", lambda request: requests.append(request.url))
    async with Server(port=0) as server, Client(server.url) as client:
        debugger = PlaywrightDebugger(browser_page, client)
        for attempt in range(8):
            with pytest.raises(RemoteError):
                await debugger.goto(URL, breakpoints=[BreakpointSpec(str(TARGET), LINE, {"kind": "watch", "condition": "$x"})], timeout=5)
            assert (await client.health())["live_sessions"] == 0
            try:
                paused = await debugger.goto(URL, breakpoints=[BREAKPOINT], timeout=5)
            except BaseException as error:
                error.add_note("attempt=" + str(attempt))
                error.add_note("sessions=" + str(await client.sessions()))
                error.add_note("cookies=" + str(await browser_page.context.cookies()))
                error.add_note("url=" + browser_page.url)
                error.add_note("requests=" + str(requests))
                raise
            await paused.session().detach()
            await paused.finished()
            await paused.close()
        paused = await debugger.goto(URL, breakpoints=[BREAKPOINT], timeout=5)
        await debugger.aclose()
        assert (await paused.session().info())["closed"]
        assert (await client.health())["live_sessions"] == 0
