"""Exercise diagnostics with an actual page whose image never finishes loading."""

import asyncio
from contextlib import asynccontextmanager, suppress
import json
from unittest.mock import AsyncMock
import zipfile

import pytest

from .browser_diagnostics import BrowserDiagnostics

pytestmark = [pytest.mark.integration, pytest.mark.browser]


@asynccontextmanager
async def unfinished_page():
    release = asyncio.Event()
    tasks, writers = set(), set()

    async def handle(reader, writer):
        writers.add(writer)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            if headers.startswith(b"GET /held-image "):
                await release.wait()
                body = b""
            else:
                body = (b'<!doctype html><title>Diagnostic fixture</title>'
                        b'<input name="title[0][value]" value="Ready form">'
                        b'<img src="/held-image">')
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: "
                         + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
            await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writers.discard(writer)
            writer.close()
            with suppress(OSError):
                await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/"
    finally:
        release.set()
        server.close()
        for writer in tuple(writers):
            writer.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()


@pytest.mark.parametrize("screenshot_fails", [False, True], ids=["normal-artifacts", "artifact-error"])
async def test_navigation_timeout_preserves_original_error_and_diagnostics(
        browser_page, tmp_path, monkeypatch, screenshot_fails):
    from playwright.async_api import TimeoutError as NavigationTimeout

    if screenshot_fails:
        monkeypatch.setattr(browser_page, "screenshot", AsyncMock(side_effect=RuntimeError("Image unavailable")))
    recorder = BrowserDiagnostics(browser_page, tmp_path)
    async with unfinished_page() as url:
        await recorder.start()
        try:
            with pytest.raises(NavigationTimeout, match="Timeout 1000ms exceeded") as caught:
                await browser_page.goto(url, timeout=1000)
            state = json.loads((tmp_path / "navigation-error.json").read_text())
            assert state["url"] == url and state["readyState"] == "interactive"
            assert state["titleFields"] == [{"value": "Ready form", "visible": True}]
            assert any(request["url"] == url + "held-image" for request in state["pending_requests"])
            assert "Ready form" in (tmp_path / "navigation-error.html").read_text()
        finally:
            await recorder.stop()
        assert zipfile.is_zipfile(tmp_path / "trace.zip")
        events = [json.loads(line) for line in (tmp_path / "events.jsonl").read_text().splitlines()]
        failure = next(event for event in events if event["event"] == "goto_error")
        assert str(caught.value) == failure["message"]
        assert any(event["event"] == "response" and event["status"] == 200 for event in events)
        if screenshot_fails:
            assert any(event["event"] == "diagnostic_error" and "Image unavailable" in event["message"]
                       for event in events)
        else:
            assert (tmp_path / "navigation-error.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        # Stopping restores ordinary navigation and removes event listeners.
        saved = (tmp_path / "events.jsonl").read_bytes()
        await browser_page.goto("data:text/html,diagnostics-stopped")
        assert (tmp_path / "events.jsonl").read_bytes() == saved
