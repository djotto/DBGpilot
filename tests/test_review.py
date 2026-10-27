"""Regression evidence from the fresh protocol and lifecycle review."""

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from dbgpilot import (
    Client, Controller, PlaywrightDebugger, ProtocolError, Server,
    Session, SessionStateError, StreamEvent,
)
from dbgpilot.models import parse_breakpoint, parse_property
from dbgpilot.protocol import parse_xml
from .helpers import Engine, fake_session, frame, xml


async def eventually(predicate, timeout=2):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_non_ascii_xml_cannot_bypass_the_dtd_rejection(encoding):
    body = '<?xml version="1.0"?><!DOCTYPE response [<!ENTITY x "expanded">]><response xmlns="urn:debugger_protocol_v1">&x;</response>'
    with pytest.raises(ProtocolError):
        parse_xml(body.encode(encoding))


@pytest.mark.parametrize("attribute", ["size", "numchildren", "page", "pagesize"])
def test_negative_property_metadata_is_rejected(attribute):
    node = xml("property", name="$x", type="string", **{attribute: -1})
    node.text = "value"
    with pytest.raises(ProtocolError):
        parse_property(node)


async def test_cancelled_event_wait_does_not_consume_an_arriving_event():
    session = Session(asyncio.StreamReader(), SimpleNamespace(close=lambda: None))
    waiter = asyncio.create_task(session.next_event())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    event = StreamEvent("stdout", b"retain this")
    session._emit(event)
    # Let the internal notification waiter wake, then cancel the public wait
    # before its result is delivered to the caller.
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert await session.next_event(timeout=0.1) == event


@pytest.mark.parametrize("state", [None, "invalid", "starting", "running"])
async def test_continuation_reply_requires_a_valid_state(state):
    async with fake_session() as (_, session, engine):
        running = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), **({} if state is None else {"status": state}))
        with pytest.raises(ProtocolError):
            await running
        assert session.closed


async def test_late_breakpoint_creation_updates_the_inventory():
    async with fake_session() as (_, session, engine):
        creation = asyncio.create_task(session.set_breakpoint("file:///app/index.php", 3))
        request = await engine.next_request()
        creation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await creation
        await engine.respond(request, id="late-breakpoint", state="enabled")
        await eventually(lambda: "late-breakpoint" in session.known_breakpoints)
        assert session.known_breakpoints["late-breakpoint"].line == 3


async def test_breakpoint_get_rejects_a_different_id():
    async with fake_session() as (_, session, engine):
        retrieval = asyncio.create_task(session.get_breakpoint("requested"))
        await engine.respond(await engine.next_request(), payload=[xml("breakpoint", id="different", type="line")])
        with pytest.raises(ProtocolError):
            await retrieval
        assert "different" not in session.known_breakpoints


@pytest.mark.parametrize("state", ["temporary", "vendor-pending"])
def test_breakpoint_metadata_preserves_vendor_states(state):
    point = parse_breakpoint(xml("breakpoint", id="point", type="line", state=state))
    assert point.state == state


@pytest.mark.parametrize("command", ["breakpoint_update", "breakpoint_remove"])
async def test_late_breakpoint_mutation_updates_the_inventory(command):
    async with fake_session() as (_, session, engine):
        creation = asyncio.create_task(session.set_breakpoint("file:///app/index.php", 3))
        await engine.respond(await engine.next_request(), id="point", state="enabled")
        await creation
        operation = (session.update_breakpoint("point", state="disabled", line=5)
                     if command == "breakpoint_update" else session.remove_breakpoint("point"))
        task = asyncio.create_task(operation)
        request = await engine.next_request()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await engine.respond(request)
        if command == "breakpoint_update":
            await eventually(lambda: session.known_breakpoints["point"].state == "disabled")
            assert session.known_breakpoints["point"].line == 5
        else:
            await eventually(lambda: not session.known_breakpoints)


@pytest.mark.parametrize("ids", [["same", "same"], ["valid", ""]])
async def test_invalid_breakpoint_list_never_commits_a_partial_inventory(ids):
    async with fake_session() as (_, session, engine):
        creation = asyncio.create_task(session.set_breakpoint("file:///app/index.php", 3))
        await engine.respond(await engine.next_request(), id="existing", state="enabled")
        await creation
        listing = asyncio.create_task(session.breakpoints())
        await engine.respond(await engine.next_request(), payload=[xml("breakpoint", id=id, type="line") for id in ids])
        with pytest.raises(ProtocolError):
            await listing
        assert list(session.known_breakpoints) == ["existing"]


async def test_unanswered_transactions_are_bounded_and_late_replies_free_capacity():
    async with fake_session(max_pending_commands=2) as (_, session, engine):
        requests = []
        for _ in range(2):
            pending = asyncio.create_task(session.command("source", timeout=0.02))
            requests.append(await engine.next_request())
            with pytest.raises(TimeoutError):
                await pending
        with pytest.raises(SessionStateError, match="limit"):
            await session.command("source")
        assert not session.closed and engine.requests.empty()
        await engine.respond(requests[0])
        await eventually(lambda: len(session._abandoned) == 1)
        pending = asyncio.create_task(session.command("source"))
        await engine.respond(await engine.next_request())
        assert (await pending).get("command") == "source"


async def test_controller_releases_closed_sessions_without_inventory_reads():
    async with Server(port=0, xdebug_port=0, max_closed_sessions=0) as server, Client(server.url) as client:
        for _ in range(4):
            engine = await Engine.connect(server.controller)
            try:
                session = await client.wait_for_session(timeout=2)
                await session.close()
            finally:
                await engine.close()
        await eventually(lambda: not server._records)
        assert server.controller._sessions == []


async def test_controller_bounds_rejected_handshake_history():
    async with Controller(port=0, error_queue_size=2) as controller:
        for _ in range(4):
            reader, writer = await asyncio.open_connection(controller.host, controller.port)
            writer.write(frame(xml("response")))
            await writer.drain()
            assert await asyncio.wait_for(reader.read(), 2) == b""
            writer.close()
            await writer.wait_closed()
        assert controller._errors.qsize() == 2


async def test_controller_connection_cap_rejects_only_new_handshakes():
    async with Controller(port=0, max_sessions=2) as controller:
        connections = [await asyncio.open_connection(controller.host, controller.port) for _ in range(2)]
        try:
            await eventually(lambda: len(controller._connections) == 2)
            reader, writer = await asyncio.open_connection(controller.host, controller.port)
            try:
                assert await asyncio.wait_for(reader.read(), 1) == b""
                assert isinstance(await controller.next_error(timeout=1), SessionStateError)
                assert len(controller._connections) == 2
            finally:
                writer.close()
                await writer.wait_closed()
        finally:
            for _, writer in connections:
                writer.close()
                await writer.wait_closed()


async def test_closed_unclaimed_sessions_leave_no_ready_queue_references():
    async with Controller(port=0, features={}) as controller:
        engine = await Engine.connect(controller)
        await eventually(lambda: controller._ready.qsize() == 1)
        await engine.close()
        await eventually(lambda: not controller._sessions)
        assert controller._ready.empty()


async def test_concurrent_controller_start_creates_one_listener(monkeypatch):
    original = asyncio.start_server
    listeners = []
    async def start(*args, **kwargs):
        listener = await original(*args, **kwargs)
        listeners.append(listener)
        return listener
    monkeypatch.setattr(asyncio, "start_server", start)
    controller = Controller(port=0)
    try:
        await asyncio.gather(*(controller.start() for _ in range(4)))
        assert len(listeners) == 1
    finally:
        await controller.aclose()
        for listener in listeners:
            listener.close()
            await listener.wait_closed()


async def test_concurrent_server_start_creates_one_http_listener():
    server = Server(port=0, xdebug_port=0)
    try:
        results = await asyncio.gather(*(server.start() for _ in range(4)))
        assert all(result is server for result in results)
        async with Client(server.url) as client:
            assert (await client.health())["status"] == "ok"
    finally:
        await server.aclose()


async def test_http_thread_start_failure_closes_both_listeners_without_hanging(monkeypatch):
    original = threading.Thread.start
    def start(thread):
        if thread.name == "dbgpilot-http":
            raise RuntimeError("thread startup failed")
        return original(thread)
    monkeypatch.setattr(threading.Thread, "start", start)
    server = Server(port=0, xdebug_port=0)
    async with asyncio.timeout(2):
        with pytest.raises(RuntimeError, match="thread startup failed"):
            await server.start()
    assert server.controller._closed.is_set()
    assert server._http.socket.fileno() == -1


async def test_http_worker_cap_and_shutdown_release_partial_connections():
    server = await Server(port=0, xdebug_port=0, max_http_connections=2).start()
    connections = [await asyncio.open_connection("127.0.0.1", server.port) for _ in range(2)]
    try:
        await eventually(lambda: len(server._http.connections) == 2)
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        try:
            assert await asyncio.wait_for(reader.read(), 1) == b""
        finally:
            writer.close()
            await writer.wait_closed()
        async with asyncio.timeout(2):
            await server.aclose()
        for reader, _ in connections:
            assert await asyncio.wait_for(reader.read(), 1) == b""
    finally:
        for _, writer in connections:
            writer.close()
            await writer.wait_closed()
        await server.aclose()


async def test_lost_http_wait_is_cancelled_before_future_php_arrives():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        _, writer = await asyncio.open_connection("127.0.0.1", server.port)
        body = json.dumps({"jsonrpc": "2.0", "id": "gone", "method": "wait_for_session", "params": {"timeout": 30}}).encode()
        writer.write((f"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        await eventually(lambda: "gone" in server._request_ids)
        writer.close()
        await writer.wait_closed()
        await eventually(lambda: "gone" not in server._request_ids)
        engine = await Engine.connect(server.controller)
        try:
            assert (await client.wait_for_session(timeout=2)).id
        finally:
            await engine.close()


async def test_lost_execution_http_keeps_the_engine_running_until_its_late_reply():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        engine = await Engine.connect(server.controller)
        try:
            session = await client.wait_for_session(timeout=2)
            _, writer = await asyncio.open_connection("127.0.0.1", server.port)
            body = json.dumps({"jsonrpc": "2.0", "id": "gone-run", "method": "session.run",
                               "params": {"session_id": session.id, "timeout": 30}}).encode()
            writer.write((f"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
            await writer.drain()
            request = await engine.next_request()
            writer.close()
            await writer.wait_closed()
            await eventually(lambda: "gone-run" not in server._request_ids)
            assert (await session.info())["state"] == "running"
            assert engine.requests.empty()
            await engine.respond(request, status="break", reason="ok")
            assert (await session.events(timeout=2))["events"][-1]["type"] == "StoppedEvent"
            assert (await session.info())["state"] == "break"
        finally:
            await engine.close()


@pytest.mark.parametrize("method", ["source", "contexts", "typemap_get"])
async def test_postmortem_metadata_queries_respect_engine_support(method):
    async with fake_session() as (_, session, engine):
        execution = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), status="stopping")
        await execution
        with pytest.raises(SessionStateError):
            await getattr(session, method)()
        assert engine.requests.empty()


async def test_helper_close_cancels_capture_still_waiting_for_php(monkeypatch):
    attached = asyncio.Event()
    async def wait(*args, **kwargs):
        attached.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "wait_for_session", wait)
    page = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock())
    async with Client() as client:
        debugger = PlaywrightDebugger(page, client)
        pending = asyncio.create_task(debugger.capture(lambda: asyncio.Event().wait(), url_pattern="**/*"))
        try:
            await attached.wait()
            await debugger.aclose()
            assert pending.done()
            with pytest.raises(asyncio.CancelledError):
                await pending
            page.unroute.assert_awaited_once()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)


async def test_route_cleanup_keeps_the_original_action_error(monkeypatch):
    async def wait(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "wait_for_session", wait)
    page = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock(side_effect=RuntimeError("browser unavailable")))
    async def action():
        raise ValueError("original action failure")
    async with Client() as client, PlaywrightDebugger(page, client) as debugger:
        with pytest.raises(ValueError, match="original action failure") as caught:
            await debugger.capture(action, url_pattern="**/*")
        assert any("route" in note.casefold() for note in caught.value.__notes__)


async def test_action_cannot_deadlock_its_own_capture_by_closing_the_helper(monkeypatch):
    async def wait(*args, **kwargs):
        await asyncio.Event().wait()
    monkeypatch.setattr(Client, "wait_for_session", wait)
    page = SimpleNamespace(route=AsyncMock(), unroute=AsyncMock())
    async with Client() as client, PlaywrightDebugger(page, client) as debugger:
        async with asyncio.timeout(1):
            with pytest.raises(SessionStateError, match="owning task"):
                await debugger.capture(debugger.aclose, url_pattern="**/*")


async def test_capture_deadline_also_bounds_route_installation():
    async def route(*args, **kwargs):
        await asyncio.Event().wait()
    page = SimpleNamespace(route=route, unroute=AsyncMock())
    async with Client() as client, PlaywrightDebugger(page, client) as debugger:
        with pytest.raises(TimeoutError):
            await debugger.capture(lambda: asyncio.Event().wait(), url_pattern="**/*", timeout=0.02)
        page.unroute.assert_awaited_once()


@pytest.mark.parametrize("command", ["feature_get", "feature_set"])
@pytest.mark.parametrize("value", ["0", "1"])
async def test_late_capability_acknowledgement_updates_async_gating(command, value):
    async with fake_session(engine_options={"feature_values": {"supports_async": "1" if value == "0" else "0"}}) as (_, session, engine):
        engine.writer.transport.pause_reading()
        try:
            operation = (session.feature_get("supports_async") if command == "feature_get"
                         else session.feature_set("supports_async", value))
            pending = asyncio.create_task(operation)
            await eventually(lambda: bool(session._pending))
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            engine.features["supports_async"] = value
        finally:
            engine.writer.transport.resume_reading()
        await eventually(lambda: session.supports_async == (value == "1"))
        assert session.capabilities["supports_async"].value == value


async def test_client_timeout_also_bounds_writer_cleanup(monkeypatch):
    class Reader:
        async def readuntil(self, *args):
            await asyncio.Event().wait()
    class Writer:
        def write(self, data):
            pass
        async def drain(self):
            pass
        def close(self):
            pass
        async def wait_closed(self):
            await asyncio.Event().wait()
    async def connect(*args, **kwargs):
        return Reader(), Writer()
    monkeypatch.setattr(asyncio, "open_connection", connect)
    async with asyncio.timeout(2):
        with pytest.raises(TimeoutError):
            await Client()._request("id", b"{}", 0.02)
