"""A real HTTP request controlled by DBGpilot. Run with ddev poetry run python ..."""

import asyncio
import json
from pathlib import Path
import sys
from urllib.request import ProxyHandler, build_opener

from dbgpilot import Controller

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/checkout.php"
LINE = next(
    number for number, text in enumerate(TARGET.read_text().splitlines(), 1)
    if "// BREAKPOINT:" in text
)


def get_json(path):
    opener = build_opener(ProxyHandler({}))
    with opener.open(f"http://127.0.0.1{path}", timeout=15) as response:
        return json.load(response)


async def main():
    health = await asyncio.to_thread(get_json, "/health.php")
    assert health["xdebug"], health
    async with asyncio.timeout(20), Controller() as controller:
        request = asyncio.create_task(asyncio.to_thread(
            get_json, "/?code=SAVE10&format=json&XDEBUG_TRIGGER=1",
        ))
        try:
            session = await controller.wait_for_session(timeout=5)
            await session.set_breakpoint(TARGET, LINE)
            await session.run_until_break(timeout=5)
            snapshot = await session.snapshot(["$subtotal", "$discount"])
            assert snapshot.variables["$subtotal"].value == 100
            assert snapshot.variables["$discount"].value == 10
            assert not request.done()
            # Return inspectable data while the PHP request is still paused.
            print(json.dumps({"event": "breakpoint", **snapshot.to_dict()}), flush=True)
            # These operations represent the caller's next debugging decisions.
            assert (await session.evaluate("$subtotal - $discount")).value == 90
            await session.step_over()
            assert (await session.property_get("$total")).value == 90
            await session.detach()
            checkout = await request
            assert checkout["total"] == 90
        finally:
            await controller.aclose()
            await asyncio.gather(request, return_exceptions=True)

    print(json.dumps({
        "event": "complete", "status": "ok", "python": sys.version.split()[0],
        "runtime": health, "checkout": checkout,
    }))


if __name__ == "__main__":
    asyncio.run(main())
