"""A real PHP/browser example, intended to run outside the source checkout."""

import os

import pytest

from dbgpilot import BreakpointSpec, Client


@pytest.mark.asyncio
async def test_paused_checkout(page, dbgpilot_setup, dbgpilot_debugger):
    paused = await dbgpilot_debugger.goto(
        os.environ.get("DBGPILOT_EXAMPLE_PAGE_URL", "http://127.0.0.1/?code=SAVE10"),
        breakpoints=[BreakpointSpec(os.environ["DBGPILOT_EXAMPLE_SOURCE"],
                                    int(os.environ.get("DBGPILOT_EXAMPLE_LINE", "11")))],
        variables=["$discount"],
    )
    assert paused.snapshot["variables"]["$discount"]["value"] == 10
    await dbgpilot_setup.client.aclose()
    async with Client(dbgpilot_setup.url, token=dbgpilot_setup.config.token) as later:
        session = later.session(paused.session_id)
        assert (await session.info())["state"] == "break"
        assert (await session.property_get("$discount"))["value"] == 10
        assert await session.set_value("$discount", 15)
        await session.step_over()
        assert (await session.property_get("$total"))["value"] == 85
        await session.detach()
    await paused.finished()
    assert await page.get_by_test_id("total").inner_text() == "£85"
