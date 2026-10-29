import os

import pytest

from .browser_diagnostics import BrowserDiagnostics, case_directory, run_directory, system_metrics

pytest_plugins = ["dbgpilot.pytest_plugin"]


@pytest.fixture(scope="session", autouse=True)
def drupal_diagnostics_run(request):
    if not os.environ.get("DDEV_SITENAME") or not any(
        item.get_closest_marker("drupal") for item in request.session.items
    ):
        yield None
        return
    directory = run_directory(request.config.rootpath / "test-results" / "drupal-diagnostics")
    with system_metrics(directory):
        yield directory


@pytest.fixture
def ddev_runtime():
    if not os.environ.get("DDEV_SITENAME"):
        pytest.skip("Run browser/runtime tests inside DDEV after ddev test-setup")


@pytest.fixture
async def browser_page(ddev_runtime, request, drupal_diagnostics_run):
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        diagnostics = None
        try:
            if request.node.get_closest_marker("drupal") and drupal_diagnostics_run is not None:
                directory = case_directory(drupal_diagnostics_run, request.node.name)
                request.node.user_properties.append(("drupal_diagnostics", str(directory)))
                diagnostics = BrowserDiagnostics(page, directory)
                await diagnostics.start()
            yield page
        finally:
            try:
                if diagnostics is not None:
                    await diagnostics.stop()
            finally:
                await context.close()
                await browser.close()
