"""Evaluation replies must distinguish active callers from abandoned waits."""

import asyncio

import pytest

from dbgpilot import CommandError, NotificationEvent, SessionStateError, StoppedEvent
from .helpers import fake_session, xml
from .test_server import pause as remote_pause, remote_session


async def pause(session, engine):
    pending = asyncio.create_task(session.run_until_break())
    await engine.respond(await engine.next_request(), status="break", reason="ok")
    result = await pending
    assert await session.next_event(timeout=1) == StoppedEvent(result)
    return result


async def evaluation_reply(engine, request, outcome="success"):
    # Xdebug eval replies have no status; optional expr/exec replies need only success.
    if outcome == "error":
        await engine.respond(request, payload=[xml("error", code=206)])
    elif outcome == "rejected":
        await engine.respond(request, success=0)
    else:
        prop = xml("property", type="int")
        prop.text = "42"
        await engine.respond(
            request, payload=[] if request.name == "exec" else [prop],
            **({"success": 1} if request.name in {"expr", "exec"} else {}),
        )


async def assert_no_extra_events(session, engine):
    # A following packet is a barrier: no sleeps or timing-based absence checks.
    await engine.send(xml("notify", name="after-evaluation"))
    event = await session.next_event(timeout=1)
    assert isinstance(event, NotificationEvent), f"Unexpected evaluation event: {event!r}"
    assert event.name == "after-evaluation"


@pytest.mark.parametrize("method,outcome", [
    ("evaluate", "success"), ("evaluate", "error"),
    ("expr", "success"), ("expr", "error"), ("expr", "rejected"),
    ("exec", "success"), ("exec", "error"), ("exec", "rejected"),
])
async def test_on_time_evaluation_does_not_emit_another_stop(method, outcome):
    async with fake_session() as (_, session, engine):
        stopped = await pause(session, engine)
        pending = asyncio.create_task(getattr(session, method)("work()"))
        await evaluation_reply(engine, await engine.next_request(), outcome)
        if outcome == "error":
            with pytest.raises(CommandError) as caught:
                await pending
            assert caught.value.code == 206
        else:
            result = await pending
            if outcome == "rejected":
                assert result is (False if method == "exec" else None)
            else:
                assert result is True if method == "exec" else result.value == 42
        assert session.state == "break" and not session.closed
        assert session.last_result == stopped
        await assert_no_extra_events(session, engine)


@pytest.mark.parametrize("method", ["evaluate", "expr", "exec"])
async def test_repeated_evaluations_do_not_overflow_event_queue(method):
    async with fake_session(event_queue_size=2) as (_, session, engine):
        await pause(session, engine)
        # Exceed the queue capacity without consuming events between evaluations.
        for _ in range(3):
            pending = asyncio.create_task(getattr(session, method)("work()"))
            await evaluation_reply(engine, await engine.next_request())
            await pending
        assert session.state == "break" and not session.closed
        await assert_no_extra_events(session, engine)


async def test_snapshot_expressions_do_not_emit_extra_stops():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        expressions = ["1 + 1", "2 + 2", "3 + 3"]
        pending = asyncio.create_task(session.snapshot(expressions=expressions))
        request = await engine.next_request()
        assert request.name == "stack_get"
        await engine.respond(request, payload=[
            xml("stack", level=0, filename="file:///app/index.php", lineno=7),
        ])
        for _ in expressions:
            request = await engine.next_request()
            assert request.name == "eval"
            await evaluation_reply(engine, request)
        snapshot = await pending
        assert list(snapshot.expressions) == expressions
        assert all(prop.value == 42 for prop in snapshot.expressions.values())
        await assert_no_extra_events(session, engine)


@pytest.mark.parametrize("abandon", ["cancel", "timeout"])
@pytest.mark.parametrize("outcome", ["success", "error"])
async def test_late_evaluate_reply_still_notifies_and_restores_inspection(abandon, outcome):
    async with fake_session() as (_, session, engine):
        stopped = await pause(session, engine)
        pending = asyncio.create_task(session.evaluate(
            "work()", timeout=2 if abandon == "cancel" else 0.02,
        ))
        request = await engine.next_request()
        if abandon == "cancel":
            pending.cancel()
        with pytest.raises(asyncio.CancelledError if abandon == "cancel" else TimeoutError):
            await pending
        assert session.state == "running" and not session.closed
        with pytest.raises(SessionStateError):
            await session.property_get("$x")
        await evaluation_reply(engine, request, outcome)
        assert await session.next_event(timeout=1) == StoppedEvent(stopped)
        assert session.state == "break" and not session.closed
        # The event must be emitted exactly once, and inspection must work again.
        await assert_no_extra_events(session, engine)
        inspection = asyncio.create_task(session.property_get("$x"))
        prop = xml("property", name="$x", type="int")
        prop.text = "7"
        await engine.respond(await engine.next_request(), payload=[prop])
        assert (await inspection).value == 7


async def test_real_step_still_emits_a_new_stop():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        pending = asyncio.create_task(session.step_over())
        await engine.respond(await engine.next_request(), status="break", reason="ok")
        result = await pending
        assert await session.next_event(timeout=1) == StoppedEvent(result)
        await assert_no_extra_events(session, engine)


async def test_remote_evaluation_does_not_publish_a_new_stop_or_advance_cursor():
    async with remote_session() as (_, _, remote, engine):
        await remote_pause(remote, engine)
        initial = await remote.events(timeout=1)
        assert [event["type"] for event in initial["events"]] == ["StoppedEvent"]
        pending = asyncio.create_task(remote.evaluate("work()"))
        await evaluation_reply(engine, await engine.next_request())
        assert (await pending)["value"] == 42
        # A marker also synchronizes the server's independent event collector.
        await engine.send(xml("notify", name="after-evaluation"))
        events = []
        cursor = initial["cursor"]
        async with asyncio.timeout(2):
            while not events or events[-1]["type"] != "NotificationEvent":
                batch = await remote.events(after=cursor, timeout=1)
                events.extend(batch["events"])
                cursor = batch["cursor"]
        assert [event["type"] for event in events] == ["NotificationEvent"]
        assert events[0]["data"]["name"] == "after-evaluation"
        assert cursor == initial["cursor"] + 1
