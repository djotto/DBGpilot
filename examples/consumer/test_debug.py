"""Break in your PHP request, reconnect, and let the browser finish."""

import os

import pytest

from dbgpilot import BreakpointSpec, Client


@pytest.mark.asyncio
async def test_php_breakpoint(dbgpilot_setup, dbgpilot_debugger):
    paused = await dbgpilot_debugger.goto(
        os.environ["DBGPILOT_TEST_URL"],
        breakpoints=[BreakpointSpec(
            os.environ["DBGPILOT_TEST_FILE"],
            int(os.environ["DBGPILOT_TEST_LINE"]),
        )],
        timeout=30,
    )

    # Closing the first client leaves this request paused in the daemon.
    await dbgpilot_setup.client.aclose()
    async with Client(dbgpilot_setup.url, token=dbgpilot_setup.config.token) as later:
        session = later.session(paused.session_id)
        assert (await session.info())["state"] == "break"
        # Add application-specific variable/stack assertions here.
        await session.detach()

    response = await paused.finished(timeout=30)
    assert response is not None and response.ok
    # Add your final DOM assertions using dbgpilot_debugger.page here.
