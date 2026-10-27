"""Coordinate async Playwright actions with server-owned PHP breakpoints.

Playwright is duck-typed here and is not a runtime dependency of DBGpilot.
"""

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import logging
import math
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import uuid

from .client import Client
from .errors import ConnectionClosed, SessionStateError
from .wire import RemoteError

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class BreakpointSpec:
    file: str | None = None
    line: int | None = None
    options: dict = field(default_factory=dict)

    def parameters(self):
        return {"file": str(self.file) if self.file is not None else None,
                "line": self.line, **self.options}


@dataclass(eq=False)
class PausedBrowser:
    session_id: str
    snapshot: dict
    action: asyncio.Task
    _owner: object = field(repr=False)
    cursor: int = 0
    _closed: bool = False
    _close_task: asyncio.Task | None = field(default=None, init=False, repr=False)

    def session(self, client=None):
        """Use the original client or reconnect with a later client."""
        return (client or self._owner.client).session(self.session_id)

    async def events(self, *, client=None, timeout=30):
        batch = await self.session(client).events(after=self.cursor, timeout=timeout)
        self.cursor = batch["cursor"]
        return batch

    async def finished(self, *, timeout=30):
        """Wait for the browser action; this does not advance PHP."""
        async with asyncio.timeout(timeout):
            return await asyncio.shield(self.action)

    async def close(self):
        if asyncio.current_task() is self.action:
            raise SessionStateError("Close the capture from its owning task, outside its browser action")
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close(self):
        try:
            await self._owner._close_session(self.session_id)
        finally:
            try:
                if not self.action.done():
                    with suppress(Exception, asyncio.CancelledError):
                        async with asyncio.timeout(1):
                            await asyncio.shield(self.action)
                if not self.action.done():
                    self.action.cancel()
                await asyncio.gather(self.action, return_exceptions=True)
            finally:
                self._closed = True
                self._owner._captures.discard(self)


class PlaywrightDebugger:
    def __init__(self, page, client, *, idekey=None):
        self.page, self.client = page, client
        self.idekey = idekey
        self._captures = set()
        self._operations = set()
        self._actions = set()
        self._closed = False
        self._close_task = None

    async def __aenter__(self):
        if self._closed:
            raise ConnectionClosed("Playwright debugger closed")
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    @staticmethod
    def trigger_url(url, idekey):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("A debugging request needs an absolute HTTP(S) URL")
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if key not in {"XDEBUG_SESSION", "XDEBUG_TRIGGER"}]
        query.extend((("XDEBUG_SESSION", idekey), ("XDEBUG_TRIGGER", idekey)))
        return urlunsplit(parsed._replace(query=urlencode(query)))

    async def goto(self, url, *, breakpoints=(), variables=(), expressions=(), timeout=30,
                   navigation_timeout=0):
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("goto needs an absolute HTTP(S) URL")
        idekey = self.idekey or "dbgpilot-" + uuid.uuid4().hex
        target = self.trigger_url(url, idekey)
        routed = urlsplit(target)
        pattern = urlunsplit(routed._replace(path=routed.path or "/", fragment=""))

        async def navigate():
            # A distinct navigation URL correlates retries with a new request
            # even while a previous aborted goto is still settling.
            response = await self.page.goto(target, timeout=navigation_timeout * 1000)
            current = urlsplit(self.page.url)
            query = [(key, value) for key, value in parse_qsl(current.query, keep_blank_values=True)
                     if not (key in {"XDEBUG_SESSION", "XDEBUG_TRIGGER"} and value == idekey)]
            clean = urlunsplit(current._replace(query=urlencode(query)))
            if clean != self.page.url:
                await self.page.evaluate("url => history.replaceState(history.state, '', url)", clean)
            return response

        return await self._capture(
            navigate, idekey=idekey,
            url_pattern=pattern, breakpoints=breakpoints, variables=variables,
            expressions=expressions, timeout=timeout,
        )

    async def capture(self, action, *, url_pattern, breakpoints=(), variables=(),
                      expressions=(), timeout=30):
        """Debug the first page request matching url_pattern during an action.

        Supports navigation, clicks, form submission, and XHR/fetch. A completed
        click is not assumed to mean that its PHP request has completed.
        """
        return await self._capture(
            action, idekey=self.idekey or "dbgpilot-" + uuid.uuid4().hex,
            url_pattern=url_pattern, breakpoints=breakpoints, variables=variables,
            expressions=expressions, timeout=timeout,
        )

    async def _capture(self, action, **options):
        if self._closed:
            raise ConnectionClosed("Playwright debugger closed")
        operation = asyncio.create_task(self._capture_request(action, **options))
        self._operations.add(operation)
        try:
            return await operation
        finally:
            self._operations.discard(operation)

    async def _capture_request(self, action, *, idekey, url_pattern, breakpoints=(), variables=(),
                       expressions=(), timeout=30):
        if self._closed:
            raise ConnectionClosed("Playwright debugger closed")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 300:
            raise ValueError("timeout must be greater than zero and at most 300 seconds")
        specs = tuple(breakpoints)
        if any(not isinstance(spec, BreakpointSpec) for spec in specs):
            raise TypeError("breakpoints must contain BreakpointSpec objects")
        session = None
        waiter = browser = None
        failure = None
        route_installed = False

        async def route_request(route):
            await route.continue_(url=self.trigger_url(route.request.url, idekey))

        async def perform():
            return await action()

        try:
            async with asyncio.timeout(timeout):
                route_installed = True
                await self.page.route(url_pattern, route_request, times=1)
                waiter = asyncio.create_task(self.client.wait_for_session(idekey=idekey, timeout=timeout))
                browser = asyncio.create_task(perform())
                self._actions.add(browser)
                browser.add_done_callback(self._actions.discard)
                session = await self._race(waiter, browser)
                for spec in specs:
                    await session.call("set_breakpoint", **spec.parameters())
                snapshot = await self._race(
                    session.break_and_return(variables, expressions=expressions, timeout=timeout), browser,
                )
                async with asyncio.timeout(4):
                    await self.page.unroute(url_pattern, route_request)
                route_installed = False
                paused = PausedBrowser(session.id, snapshot, browser, self)
                self._captures.add(paused)
                return paused
        except BaseException as error:
            failure = error
            if isinstance(error, TimeoutError):
                error.add_note(
                    "Breakpoint capture deadline expired. Check that the page route matches the PHP request, "
                    "Xdebug connects to the server's debugger listener, and XDEBUG_TRIGGER/XDEBUG_SESSION "
                    "values are allowed. Verify breakpoint source paths against the server's path mappings. "
                    "Browser action deadlines are separate; keep the page and event loop alive during a pause."
                )
            elif isinstance(error, RemoteError):
                error.add_note("Check server path mappings and the engine URI/line for each breakpoint; use Client.to_remote() to verify a local source path.")
            if waiter is not None and not waiter.done():
                waiter.cancel()
            if waiter is not None:
                results = await asyncio.gather(waiter, return_exceptions=True)
                if session is None and not isinstance(results[0], BaseException):
                    session = results[0]
            if session is not None:
                try:
                    await self._close_session(session.id)
                except Exception:
                    LOGGER.exception("Could not close failed capture %s", session.id)
            if browser is not None:
                if session is not None and not browser.done():
                    # Let the now-detached HTTP navigation settle before the
                    # next capture; cancelling goto does not stop browser I/O.
                    with suppress(Exception, asyncio.CancelledError):
                        async with asyncio.timeout(1):
                            await asyncio.shield(browser)
                if not browser.done():
                    browser.cancel()
                await asyncio.gather(browser, return_exceptions=True)
            raise
        finally:
            if route_installed:
                try:
                    async with asyncio.timeout(4):
                        await self.page.unroute(url_pattern, route_request)
                except Exception as error:
                    if failure is None:
                        raise
                    failure.add_note(f"Browser route cleanup failed: {error}")

    @staticmethod
    async def _race(operation, action):
        task = asyncio.ensure_future(operation)
        try:
            done, _ = await asyncio.wait((task, action), return_when=asyncio.FIRST_COMPLETED)
            if task in done:
                return await task
            # Errors should fail quickly; successful clicks/XHR dispatch can
            # legitimately finish before PHP attaches or reaches a breakpoint.
            await action
            return await task
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def _close_session(self, session_id):
        # Cleanup still works if the capture's original Client has closed.
        async with asyncio.timeout(4), Client(self.client.url, token=self.client.token, timeout=3) as cleanup:
            try:
                await cleanup.session(session_id).close()
            except RemoteError as error:
                if error.code != -32001:
                    raise

    async def aclose(self):
        if asyncio.current_task() in self._actions:
            raise SessionStateError("Close the debugger from its owning task, outside the browser action")
        if self._close_task is None:
            self._closed = True
            self._close_task = asyncio.create_task(self._close_all())
            self._close_task.add_done_callback(lambda task: None if task.cancelled() else task.exception())
        await asyncio.shield(self._close_task)

    async def _close_all(self):
        operations = tuple(self._operations)
        for operation in operations:
            operation.cancel()
        await asyncio.gather(*operations, return_exceptions=True)
        results = await asyncio.gather(*(capture.close() for capture in tuple(self._captures)), return_exceptions=True)
        errors = [error for error in results if isinstance(error, Exception)]
        if errors:
            raise ExceptionGroup("Playwright capture cleanup failed", errors)
