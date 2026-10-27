"""A local PHP CLI walkthrough using only installed DBGpilot and the stdlib."""

import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import tempfile
import uuid

from dbgpilot import Client, DebuggerSetup

PHP = """<?php
$subtotal = 100;
$discount = 10;
$total = $subtotal - $discount;
echo $total;
"""


async def main(php):
    check = await asyncio.create_subprocess_exec(
        php, "-d", "xdebug.start_with_request=no", "-r", 'exit(extension_loaded("xdebug") ? 0 : 2);',
        env=dict(os.environ, XDEBUG_MODE="off"),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(check.communicate(), 5)
    finally:
        if check.returncode is None:
            with suppress(ProcessLookupError):
                check.kill()
            await check.communicate()
    if check.returncode != 0:
        raise RuntimeError("The selected PHP CLI must have Xdebug loaded; check php --version and php --ri xdebug")
    setup = DebuggerSetup(launch=True, port=0, xdebug_port=0)
    process = None
    try:
        async with setup, asyncio.timeout(20):
            health = await setup.health()
            with tempfile.TemporaryDirectory(prefix="dbgpilot-first-") as directory:
                source = Path(directory) / "checkout.php"
                source.write_text(PHP)
                idekey = "first-" + uuid.uuid4().hex
                env = dict(os.environ, XDEBUG_MODE="debug")
                env.pop("XDEBUG_CONFIG", None)
                process = await asyncio.create_subprocess_exec(
                    php, "-d", "xdebug.start_with_request=yes", "-d", "xdebug.client_host=127.0.0.1",
                    "-d", f"xdebug.client_port={health['xdebug_port']}", "-d", f"xdebug.idekey={idekey}",
                    str(source), env=env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                session = await setup.client.wait_for_session(idekey=idekey, timeout=5)
                await session.set_breakpoint(source, 4)
                snapshot = await session.break_and_return(["$subtotal", "$discount"], timeout=5)
                assert snapshot["variables"]["$discount"]["value"] == 10
                print(json.dumps({"event": "paused", "session_id": session.id, "discount": 10}), flush=True)
                await setup.client.aclose()  # PHP remains paused after this client closes.
                async with Client(setup.url) as later:
                    remote = later.session(session.id)
                    assert (await remote.info())["state"] == "break"
                    assert (await remote.property_get("$discount"))["value"] == 10
                    assert await remote.set_value("$discount", 15)
                    await remote.step_over()
                    assert (await remote.property_get("$total"))["value"] == 85
                    await remote.detach()
                stdout, stderr = await process.communicate()
                if process.returncode != 0 or stdout != b"85":
                    raise RuntimeError(f"PHP did not finish with total 85: {stderr.decode(errors='replace')}")
                print(json.dumps({"event": "complete", "total": 85, "reconnected": True}), flush=True)
    finally:
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)
        if process is not None and process.returncode is None:
            with suppress(ProcessLookupError):
                process.terminate()
            try:
                await asyncio.wait_for(process.communicate(), 3)
            except TimeoutError:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.communicate()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch", action="store_true", required=True,
                        help="Explicitly launch and own the temporary local DBGpilot server")
    parser.add_argument("--php", default="php", help="Local PHP CLI with Xdebug loaded")
    args = parser.parse_args()
    asyncio.run(main(args.php))
