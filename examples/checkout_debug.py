"""Run with an installed dbgpilot and Playwright; see docs/python-setup.md."""

import argparse
import asyncio

from playwright.async_api import async_playwright

from dbgpilot import BreakpointSpec, Client, DebuggerSetup


async def main(args):
    options = {key: value for key, value in {
        "url": args.url, "launch": args.launch, "port": args.port,
    }.items() if value is not None}
    setup = DebuggerSetup(config=args.config, **options)
    try:
        async with setup, async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            try:
                page = await browser.new_page(service_workers="block")
                async with setup.debugger(page) as debugger:
                    paused = await debugger.goto(
                        args.page_url, breakpoints=[BreakpointSpec(args.source, args.line)],
                        variables=["$subtotal", "$discount"], timeout=30,
                    )
                    assert paused.snapshot["variables"]["$discount"]["value"] == 10
                    print("Paused session:", paused.session_id, flush=True)
                    await setup.client.aclose()
                    # PHP stays paused while the browser and its event loop live.
                    async with Client(setup.url, token=setup.config.token) as later:
                        session = later.session(paused.session_id)
                        assert (await session.info())["state"] == "break"
                        assert (await session.property_get("$discount"))["value"] == 10
                        assert await session.set_value("$discount", 15)
                        await session.step_over()
                        assert (await session.property_get("$total"))["value"] == 85
                        await session.detach()
                    await paused.finished()
                    assert await page.get_by_test_id("total").inner_text() == "£85"
                    print("Verified DOM total: £85", flush=True)
            finally:
                await browser.close()
    finally:
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)
        else:
            await setup.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="Existing DBGpilot API origin")
    parser.add_argument("--launch", action="store_true", default=None, help="Explicitly launch the installed CLI")
    parser.add_argument("--port", type=int, help="Owned API port; use 0 for an isolated ephemeral port")
    parser.add_argument("--config", help="Explicit project TOML file; no implicit discovery")
    parser.add_argument("--page-url", default="http://127.0.0.1/?code=SAVE10")
    parser.add_argument("--source", required=True, help="Checkout PHP source path in the configured local namespace")
    parser.add_argument("--line", required=True, type=int, help="Line calculating $total, before it executes")
    asyncio.run(main(parser.parse_args()))
