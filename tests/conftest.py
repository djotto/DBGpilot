import os

import pytest

pytest_plugins = ["dbgpilot.pytest_plugin"]


@pytest.fixture
def ddev_runtime():
    if not os.environ.get("DDEV_SITENAME"):
        pytest.skip("Run browser/runtime tests inside DDEV after ddev test-setup")


@pytest.fixture
async def browser_page(ddev_runtime):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        try:
            yield page
        finally:
            await context.close()
            await browser.close()
