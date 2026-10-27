"""Opt-in fixtures: pytest_plugins = [\"dbgpilot.pytest_plugin\"].

Importing dbgpilot itself never imports pytest or Playwright. These fixtures
have function scope and use the test's function-scoped asyncio loop.
"""

import pytest
import pytest_asyncio

from .setup import DebuggerSetup


@pytest.fixture
def dbgpilot_options():
    """Override with DebuggerSetup keyword arguments; no config discovery by default."""
    return {}


@pytest.fixture
def dbgpilot_page(page):
    """An existing ASYNC Playwright page; override to use your page fixture."""
    return page


@pytest_asyncio.fixture
async def dbgpilot_setup(dbgpilot_options):
    setup = DebuggerSetup(**dbgpilot_options)
    try:
        await setup.start()
        yield setup
    finally:
        if setup.owns_server:
            await setup.shutdown(release_sessions=True)
        else:
            await setup.aclose()


@pytest_asyncio.fixture
async def dbgpilot_debugger(dbgpilot_setup, dbgpilot_page):
    async with dbgpilot_setup.debugger(dbgpilot_page) as debugger:
        yield debugger
