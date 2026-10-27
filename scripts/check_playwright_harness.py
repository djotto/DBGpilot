"""Run the actual browser/helper loop against a running DBGpilot server."""

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from dbgpilot import BreakpointSpec, Client, PlaywrightDebugger


async def main(args):
    target = Path(__file__).resolve().parents[1] / "src/checkout.php"
    line = next(i for i, text in enumerate(target.read_text().splitlines(), 1) if "// BREAKPOINT:" in text)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            page = await browser.new_page()
            async with Client(args.url) as first, PlaywrightDebugger(page, first) as debugger:
                paused = await debugger.goto(
                    "http://127.0.0.1/?code=SAVE10", breakpoints=[BreakpointSpec(str(target), line)],
                    variables=["$subtotal", "$discount"],
                )
                print(json.dumps({"event": "breakpoint", **paused.snapshot}), flush=True)
                assert not paused.action.done()
                await first.aclose()
                async with Client(args.url) as later:
                    session = paused.session(later)
                    assert await session.set_value("$discount", 15)
                    await session.step_over()
                    assert (await session.property_get("$total"))["value"] == 85
                    await session.detach()
                await paused.finished()
                total = await page.get_by_test_id("total").inner_text()
                assert total == "£85"
                print(json.dumps({"event": "complete", "session_id": paused.session_id, "page_total": total}), flush=True)
        finally:
            await browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9004")
    asyncio.run(main(parser.parse_args()))
