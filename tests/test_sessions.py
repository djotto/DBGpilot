import asyncio
import base64
import xml.etree.ElementTree as ET

import pytest

from dbgpilot import (
    ClosedEvent, CommandError, ConnectionClosed, Controller, ExecutionFinished,
    NotificationEvent, ProtocolError, SessionStateError, StoppedEvent, StreamEvent,
)
from .helpers import Engine, fake_session, frame, xml


async def test_init_and_zero_feature_value():
    async with fake_session() as (_, session, _):
        assert session.info.protocol_version == "1.0"
        assert session.info.idekey == "test"
        assert session.supports_async is False


async def test_responses_can_arrive_out_of_order():
    async with fake_session() as (_, session, engine):
        first = asyncio.create_task(session.command("stack_depth"))
        second = asyncio.create_task(session.command("status"))
        a, b = await engine.next_request(), await engine.next_request()
        await engine.respond(b, status="starting")
        await engine.respond(a, depth="3")
        assert (await first).get("depth") == "3"
        assert (await second).get("status") == "starting"


async def test_streams_and_notifications_do_not_consume_command_response():
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run_until_break())
        request = await engine.next_request()
        stream = xml("stream", type="stdout", encoding="base64")
        stream.text = base64.b64encode(b"\xff\0hello").decode()
        await engine.send(stream)
        await engine.send(xml("notify", name="breakpoint_resolved"))
        assert not run.done()
        message = ET.Element("{https://xdebug.org/dbgp/xdebug}message", filename="file:///app.php", lineno="7")
        await engine.respond(request, status="break", reason="ok", payload=[message])
        result = await run
        assert result.line == 7
        assert result.file == "file:///app.php"
        event = await session.next_event(timeout=1)
        assert event == StreamEvent("stdout", b"\xff\0hello")
        assert isinstance(await session.next_event(timeout=1), NotificationEvent)
        assert isinstance(await session.next_event(timeout=1), StoppedEvent)
        assert session.state == "break"


@pytest.mark.parametrize("attrs", [{"transaction_id": "999"}, {"command": "source"}])
async def test_unmatched_responses_close_connection(attrs):
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.command("status"))
        request = await engine.next_request()
        await engine.respond(request, **attrs)
        with pytest.raises(ProtocolError):
            await pending
        assert session.closed


async def test_engine_error_does_not_destroy_session():
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.command("unknown"))
        request = await engine.next_request()
        error = xml("error", code=4)
        ET.SubElement(error, "{urn:debugger_protocol_v1}message").text = "not implemented"
        await engine.respond(request, payload=[error])
        with pytest.raises(CommandError) as caught:
            await pending
        assert caught.value.code == 4
        assert caught.value.command == "unknown"
        assert not session.closed
        next_command = asyncio.create_task(session.command("status"))
        await engine.respond(await engine.next_request(), status="starting")
        assert (await next_command).get("status") == "starting"


@pytest.mark.parametrize("cancel", [True, False])
async def test_late_response_after_cancellation_or_timeout_is_ignored(cancel):
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.command("status", timeout=0.02 if not cancel else 2))
        abandoned = await engine.next_request()
        if cancel:
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await pending
        await engine.respond(abandoned, status="starting")
        following = asyncio.create_task(session.command("stack_depth"))
        await engine.respond(await engine.next_request(), depth="2")
        assert (await following).get("depth") == "2"
        assert not session.closed


async def test_disconnect_fails_pending_commands_and_event_waiters():
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.command("status"))
        await engine.next_request()
        event = asyncio.create_task(session.next_event(timeout=1))
        await engine.close()
        with pytest.raises(ConnectionClosed):
            await pending
        assert isinstance(await event, ClosedEvent)


async def test_wait_for_session_is_released_when_controller_closes():
    controller = await Controller(port=0).start()
    waiter = asyncio.create_task(controller.wait_for_session())
    await asyncio.sleep(0)
    await controller.aclose()
    with pytest.raises(ConnectionClosed):
        await waiter


async def test_multiple_requests_are_independent():
    async with asyncio.timeout(5), Controller(port=0, features={}) as controller:
        first = await Engine.connect(controller, idekey="first")
        second = await Engine.connect(controller, idekey="second")
        try:
            sessions = [await controller.wait_for_session(timeout=2) for _ in range(2)]
            by_key = {session.info.idekey: session for session in sessions}
            assert len({session.info.id for session in sessions}) == 2
            run = asyncio.create_task(by_key["first"].run())
            first_request = await first.next_request()
            other = asyncio.create_task(by_key["second"].command("status"))
            await second.respond(await second.next_request(), status="starting")
            assert (await other).get("status") == "starting"
            assert not run.done()
            await first.respond(first_request, status="break")
            assert (await run).paused
        finally:
            await controller.aclose()
            await first.close()
            await second.close()


async def test_inspection_while_running_is_rejected_without_blocking():
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run())
        request = await engine.next_request()
        with pytest.raises(SessionStateError):
            await session.property_get("$value")
        with pytest.raises(SessionStateError):
            await session.command("status")
        with pytest.raises(SessionStateError):
            await session.run()
        with pytest.raises(SessionStateError):
            await session.interrupt()
        await engine.respond(request, status="break")
        await run


async def test_completion_before_breakpoint_is_explicit():
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run_until_break())
        await engine.respond(await engine.next_request(), status="stopping")
        with pytest.raises(ExecutionFinished) as caught:
            await run
        assert caught.value.result.status == "stopping"


async def test_cancelled_event_wait_does_not_consume_future_event():
    async with fake_session() as (_, session, engine):
        with pytest.raises(TimeoutError):
            await session.next_event(timeout=0.01)
        await engine.send(xml("notify", name="later"))
        event = await session.next_event(timeout=1)
        assert event.name == "later"


async def test_bad_handshake_is_reported_and_listener_recovers():
    async with Controller(port=0, features={}) as controller:
        reader, writer = await asyncio.open_connection(controller.host, controller.port)
        writer.write(frame(xml("response", command="status", transaction_id="1")))
        await writer.drain()
        assert isinstance(await controller.next_error(timeout=2), ProtocolError)
        assert await reader.read() == b""
        writer.close()
        await writer.wait_closed()
        engine = await Engine.connect(controller)
        assert (await controller.wait_for_session(timeout=2)).info.language == "PHP"
        await controller.aclose()
        await engine.close()


async def test_unconsumed_event_overflow_closes_session():
    async with fake_session(event_queue_size=1) as (_, session, engine):
        pending = asyncio.create_task(session.command("status"))
        await engine.next_request()
        await engine.send(xml("notify", name="first"))
        await engine.send(xml("notify", name="second"))
        with pytest.raises(ProtocolError, match="overflow"):
            await pending


async def test_frame_and_page_options_reach_engine():
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), status="break")
        await run
        get = asyncio.create_task(session.property_get("$array", depth=2, context=1, page=3))
        request = await engine.next_request()
        assert request.arguments == {"n": "$array", "d": "2", "c": "1", "p": "3"}
        await engine.respond(request, payload=[xml("property", name="$array", type="array", page=3)])
        assert (await get).page == 3
        with pytest.raises(ValueError, match="current frame"):
            await session.evaluate("$x + 1", depth=2)
        evaluate = asyncio.create_task(session.evaluate("$x + 1"))
        request = await engine.next_request()
        assert request.arguments["d"] == "0"
        assert base64.b64decode(request.data) == b"$x + 1"
        prop = xml("property", type="int")
        prop.text = "42"
        await engine.respond(request, payload=[prop])
        assert (await evaluate).value == 42


async def test_cancelling_run_preserves_later_breakpoint_for_inspection():
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run())
        request = await engine.next_request()
        run.cancel()
        with pytest.raises(asyncio.CancelledError):
            await run
        assert not session.closed
        assert session.state == "running"
        await engine.respond(request, status="break")
        assert isinstance(await session.next_event(timeout=1), StoppedEvent)
        assert session.state == "break"
        get = asyncio.create_task(session.property_get("$value"))
        prop = xml("property", name="$value", type="int")
        prop.text = "123"
        await engine.respond(await engine.next_request(), payload=[prop])
        assert (await get).value == 123


async def test_close_during_incomplete_handshake_releases_connection():
    async with asyncio.timeout(3):
        controller = await Controller(port=0).start()
        reader, writer = await asyncio.open_connection(controller.host, controller.port)
        await asyncio.sleep(0)
        await controller.aclose()
        assert await reader.read() == b""
        writer.close()
        await writer.wait_closed()
