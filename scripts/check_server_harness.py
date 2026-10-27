"""Exercise an already-running DBGpilot server using two client lifetimes.

Start `ddev poetry run python -m dbgpilot serve` in another terminal, then run
`ddev poetry run python scripts/check_server_harness.py`.
"""

import argparse
import asyncio
import json
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from dbgpilot import Client


def checkout():
    opener = build_opener(ProxyHandler({}))
    with opener.open("http://127.0.0.1/?code=SAVE10&format=json&XDEBUG_TRIGGER=1", timeout=30) as response:
        return json.load(response)


async def main(args):
    path = Path(__file__).resolve().parents[1] / "src/checkout.php"
    line = next(i for i, text in enumerate(path.read_text().splitlines(), 1) if "// BREAKPOINT:" in text)
    request = None
    remote = None
    async with asyncio.timeout(35):
        try:
            async with Client(args.url) as first:
                await first.health()
                request = asyncio.create_task(asyncio.to_thread(checkout))
                remote = await first.wait_for_session(timeout=5)
                await remote.set_breakpoint(path, line)
                snapshot = await remote.break_and_return(["$subtotal", "$discount"], timeout=5)
                assert not request.done()
                print(json.dumps({"event": "breakpoint", **snapshot}), flush=True)
            # The first client has closed; ownership stays with the server.
            async with Client(args.url) as later:
                resumed = later.session(remote.id)
                assert (await resumed.info())["state"] == "break"
                assert await resumed.set_value("$discount", 15)
                await resumed.step_over(timeout=5)
                assert (await resumed.property_get("$total"))["value"] == 85
                await resumed.detach()
                result = await request
                assert result["total"] == 85
                print(json.dumps({"event": "complete", "session_id": remote.id, "checkout": result}), flush=True)
        finally:
            if remote is not None:
                async with Client(args.url) as cleanup:
                    await cleanup.session(remote.id).close()
            if request is not None:
                await asyncio.gather(request, return_exceptions=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:9004")
    asyncio.run(main(parser.parse_args()))
