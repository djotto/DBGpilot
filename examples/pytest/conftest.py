"""This example supplies a page; existing suites can reuse their async page."""

import os

from playwright.async_api import async_playwright
import pytest
import pytest_asyncio

pytest_plugins = ["dbgpilot.pytest_plugin"]


@pytest.fixture
def dbgpilot_options():
    options = {"config": os.environ.get("DBGPILOT_EXAMPLE_CONFIG")}
    if "DBGPILOT_EXAMPLE_LAUNCH" in os.environ:
        options.update(launch=os.environ["DBGPILOT_EXAMPLE_LAUNCH"] == "1", port=0)
    return options


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            yield await browser.new_page(service_workers="block")
        finally:
            await browser.close()
