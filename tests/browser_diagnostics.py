"""Best-effort artifacts for intermittent Drupal browser failures."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import threading
import time
import uuid


def run_directory(base):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = Path(base) / f"{stamp}-{uuid.uuid4().hex[:8]}"
    directory.mkdir(parents=True)
    return directory


def case_directory(base, name):
    label = re.sub(r"[^a-zA-Z0-9_.-]", "-", name)[:120]
    directory = Path(base) / f"{label}-{uuid.uuid4().hex[:8]}"
    directory.mkdir()
    return directory


@contextmanager
def system_metrics(directory, *, interval=2):
    """Sample available Linux counters; also work on hosts without /proc."""
    stopped = threading.Event()
    paths = (
        "/proc/loadavg", "/proc/meminfo", "/proc/pressure/cpu", "/proc/pressure/io",
        "/proc/pressure/memory", "/sys/fs/cgroup/cpu.stat", "/sys/fs/cgroup/io.stat",
        "/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory.events",
    )

    def sample():
        try:
            with (directory / "system-metrics.jsonl").open("w", buffering=1) as target:
                while not stopped.is_set():
                    record = {"time": time.time(), "cpu_count": os.cpu_count()}
                    for name in paths:
                        try:
                            record[name] = Path(name).read_text()
                        except OSError:
                            pass
                    target.write(json.dumps(record) + "\n")
                    stopped.wait(interval)
        except OSError as error:
            print(f"Drupal resource diagnostics unavailable: {error}", file=sys.stderr)

    thread = threading.Thread(target=sample, name="dbgpilot-test-metrics", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stopped.set()
        thread.join(timeout=5)


class BrowserDiagnostics:
    """Trace one page without changing navigation options or failure types."""

    def __init__(self, page, directory):
        self.page = page
        self.directory = Path(directory)
        self._started = time.monotonic()
        self._active = {}
        self._request_ids = {}
        self._listeners = []
        self._tracing = False
        self._original_goto = page.goto
        self._events = (self.directory / "events.jsonl").open("w", buffering=1)

    def _log(self, event, **details):
        record = {"time": time.time(), "seconds": round(time.monotonic() - self._started, 3),
                  "event": event, **details}
        try:
            self._events.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
        except OSError:
            # Artifact failures must not replace a test's original exception.
            pass

    def _request_details(self, request):
        identifier = self._request_ids.setdefault(request, len(self._request_ids) + 1)
        return {"id": identifier, "method": request.method, "url": request.url,
                "resource_type": request.resource_type,
                "navigation": request.is_navigation_request()}

    def _request(self, request):
        details = self._request_details(request)
        self._active[details["id"]] = {"started": time.time(), **details}
        self._log("request", **details)

    def _response(self, response):
        self._log("response", **self._request_details(response.request), status=response.status)

    def _finished(self, request):
        details = self._request_details(request)
        self._active.pop(details["id"], None)
        self._log("request_finished", **details, timing=request.timing)

    def _failed(self, request):
        details = self._request_details(request)
        self._active.pop(details["id"], None)
        self._log("request_failed", **details, failure=request.failure)

    async def start(self):
        listeners = {
            "request": self._request, "response": self._response,
            "requestfinished": self._finished, "requestfailed": self._failed,
            "console": lambda message: self._log("console", kind=message.type, text=message.text),
            "pageerror": lambda error: self._log("page_error", message=str(error)),
            "domcontentloaded": lambda: self._log("domcontentloaded", url=self.page.url),
            "load": lambda: self._log("load", url=self.page.url),
            "framenavigated": lambda frame: self._log(
                "frame_navigated", url=frame.url, main=frame == self.page.main_frame,
            ),
        }
        for event, callback in listeners.items():
            self.page.on(event, callback)
            self._listeners.append((event, callback))
        try:
            async with asyncio.timeout(10):
                await self.page.context.tracing.start(screenshots=True, snapshots=True, sources=True)
            self._tracing = True
        except Exception as error:
            self._log("diagnostic_error", operation="trace_start", message=str(error))
        self.page.goto = self._goto

    async def _goto(self, url, *args, **kwargs):
        self._log("goto_started", url=url, options=kwargs)
        try:
            response = await self._original_goto(url, *args, **kwargs)
        except Exception as error:
            self._log("goto_error", url=url, message=str(error))
            await self.capture("navigation-error")
            raise
        self._log("goto_completed", url=url, status=response.status if response else None)
        return response

    async def capture(self, label):
        state = {"url": self.page.url, "pending_requests": list(self._active.values())}
        try:
            async with asyncio.timeout(5):
                state.update(await self.page.evaluate("""() => ({
                    readyState: document.readyState,
                    title: document.title,
                    titleFields: [...document.querySelectorAll('input[name="title[0][value]"]')].map(el => ({
                        value: el.value, visible: !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length)
                    })),
                    body: document.body?.innerText.slice(0, 6000),
                    navigation: performance.getEntriesByType('navigation').map(entry => entry.toJSON())
                })"""))
                (self.directory / f"{label}.html").write_text(await self.page.content())
        except Exception as error:
            state["snapshot_error"] = str(error)
        try:
            (self.directory / f"{label}.json").write_text(json.dumps(state, indent=2) + "\n")
        except OSError as error:
            self._log("diagnostic_error", operation="state_write", message=str(error))
        try:
            async with asyncio.timeout(5):
                await self.page.screenshot(path=str(self.directory / f"{label}.png"), timeout=4000)
        except Exception as error:
            self._log("diagnostic_error", operation="screenshot", message=str(error))

    async def stop(self):
        self.page.goto = self._original_goto
        try:
            await self.capture("final-state")
            if self._tracing:
                try:
                    async with asyncio.timeout(10):
                        await self.page.context.tracing.stop(path=str(self.directory / "trace.zip"))
                except Exception as error:
                    self._log("diagnostic_error", operation="trace_stop", message=str(error))
        finally:
            for event, callback in self._listeners:
                self.page.remove_listener(event, callback)
            self._events.close()
            self._active.clear()
            self._request_ids.clear()
