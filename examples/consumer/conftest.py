"""Copy into your suite, or merge these fixtures into its root conftest.py."""

import os

from playwright.async_api import async_playwright
import pytest
import pytest_asyncio

pytest_plugins = ["dbgpilot.pytest_plugin"]


@pytest.fixture
def dbgpilot_options():
    # Reuse a separately started daemon. These fixtures never shut it down.
    return {
        "url": os.environ.get("DBGPILOT_URL", "http://127.0.0.1:9004"),
        "token": os.environ.get("DBGPILOT_TOKEN"),
    }


@pytest_asyncio.fixture
async def dbgpilot_page():
    # If your suite has an async page already, return it from this fixture instead.
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        try:
            yield await browser.new_page(service_workers="block")
        finally:
            await browser.close()
