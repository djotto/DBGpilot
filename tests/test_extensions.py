"""Optional stdin/shell capabilities using scripted DBGp engines."""

import asyncio
import base64

import pytest

from dbgpilot import (
    InteractiveEvent, ProtocolError, ProxyError, ProxyErrorEvent, SessionStateError,
    StoppedEvent, StreamEvent,
)
from .helpers import fake_session, xml
from .test_conformance import pause
from .test_server import remote_session


async def enable_input(session, engine):
    task = asyncio.create_task(session.set_stdin())
    request = await engine.next_request()
    assert request.name == "stdin" and request.arguments == {"c": "1"} and request.data is None
    await engine.respond(request, success=1)
    assert await task and session.stdin_redirected


@pytest.mark.parametrize("data", [b"\xff\0\n", b"", "café\n"])
async def test_stdin_configuration_and_binary_safe_data(data):
    async with fake_session() as (_, session, engine):
        await enable_input(session, engine)
        task = asyncio.create_task(session.send_stdin(data))
        request = await engine.next_request()
        assert request.name == "stdin" and request.arguments == {}
        assert base64.b64decode(request.data) == (data.encode() if isinstance(data, str) else data)
        await engine.respond(request, success=1)
        assert await task
        task = asyncio.create_task(session.set_stdin(False))
        request = await engine.next_request()
        assert request.arguments == {"c": "0"} and request.data is None
        await engine.respond(request, success=1)
        assert await task and not session.stdin_redirected
        with pytest.raises(SessionStateError):
            await session.send_stdin("not redirected")


@pytest.mark.parametrize("arguments", [{}, {"mode": 1, "data": "x"}, {"mode": 2}, {"mode": True}, {"data": 1}])
async def test_invalid_stdin_combinations_never_reach_engine(arguments):
    async with fake_session() as (_, session, engine):
        with pytest.raises((ValueError, TypeError)):
            await session.stdin(**arguments)
        assert engine.requests.empty()


@pytest.mark.parametrize("async_support", ["0", "1"])
async def test_stdin_is_available_during_run_with_async_or_read_notification(async_support):
    async with fake_session(engine_options={"feature_values": {"supports_async": async_support}}) as (_, session, engine):
        await enable_input(session, engine)
        run = asyncio.create_task(session.run())
        run_request = await engine.next_request()
        if async_support == "0":
            with pytest.raises(SessionStateError):
                await session.send_stdin("premature")
            await engine.send(xml("notify", name="stdin"))
            assert (await session.next_event(timeout=1)).name == "stdin"
        data = asyncio.create_task(session.send_stdin("input\n"))
        request = await engine.next_request()
        assert request.name == "stdin"
        await engine.respond(request, success=1)
        assert await data and not run.done()
        await engine.respond(run_request, status="break", reason="ok")
        assert (await run).paused and not session.stdin_waiting


async def test_failed_stdin_configuration_does_not_enable_input():
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.set_stdin())
        await engine.respond(await engine.next_request(), success=0)
        assert not await task and not session.stdin_redirected
        with pytest.raises(SessionStateError):
            await session.send_stdin(b"x")


async def test_stdin_deadline_includes_waiting_for_another_input_command():
    async with fake_session() as (_, session, engine):
        await enable_input(session, engine)
        async with session._stdin_lock:
            with pytest.raises(TimeoutError):
                await session.send_stdin("queued", timeout=0.01)
        assert engine.requests.empty()


@pytest.mark.parametrize("success", [None, "invalid"])
async def test_invalid_stdin_acknowledgements_close_the_session(success):
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.set_stdin())
        await engine.respond(await engine.next_request(), **({} if success is None else {"success": success}))
        with pytest.raises(ProtocolError):
            await task
        assert session.closed


async def test_cancelled_stdin_configuration_uses_late_ack_and_ignores_stale_ack():
    async with fake_session() as (_, session, engine):
        first = asyncio.create_task(session.set_stdin())
        first_request = await engine.next_request()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(session.set_stdin(False))
        second_request = await engine.next_request()
        await engine.respond(second_request, success=1)
        assert await second
        await engine.respond(first_request, success=1)
        status = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="starting")
        await status
        assert not session.stdin_redirected


@pytest.mark.parametrize("feature,call", [("stdin", "set_stdin"), ("interact", "interact")])
async def test_unsupported_optional_commands_are_rejected_without_sending(feature, call):
    async with fake_session(engine_options={"feature_values": {feature: "0"}}) as (_, session, engine):
        await pause(session, engine)
        with pytest.raises(SessionStateError, match=feature):
            await getattr(session, call)()
        assert engine.requests.empty() and not session.closed


async def test_interact_chunks_prompts_inspection_and_reset():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        first = asyncio.create_task(session.interact("if True:"))
        request = await engine.next_request()
        assert request.arguments == {"m": "1"}
        assert base64.b64decode(request.data) == b"if True:"
        with pytest.raises(SessionStateError):
            await session.property_get("x")
        await engine.respond(request, status="interactive", more=1, prompt="... ")
        result = await first
        assert result.more and result.prompt == "... "
        assert session.state == "interactive"
        assert isinstance(await session.next_event(timeout=1), InteractiveEvent)
        with pytest.raises(SessionStateError):
            await session.run()
        second = asyncio.create_task(session.interact("    print('ok')"))
        request = await engine.next_request()
        assert base64.b64decode(request.data) == b"    print('ok')"  # engine owns buffering
        stream = xml("stream", type="stdout", encoding="base64")
        stream.text = base64.b64encode(b"ok\n").decode()
        await engine.send(stream)
        await engine.respond(request, status="interactive", more=0, prompt="λ> ")
        assert (await second).prompt == "λ> "
        assert isinstance(await session.next_event(timeout=1), StreamEvent)
        assert isinstance(await session.next_event(timeout=1), InteractiveEvent)
        get = asyncio.create_task(session.property_get("x"))
        prop = xml("property", name="x", type="int")
        prop.text = "42"
        await engine.respond(await engine.next_request(), payload=[prop])
        assert (await get).value == 42
        reset = asyncio.create_task(session.interact(mode=0))
        request = await engine.next_request()
        assert request.arguments == {"m": "0"} and request.data == ""
        await engine.respond(request, status="break", more=0, prompt="")
        assert (await reset).status == "break"
        assert isinstance(await session.next_event(timeout=1), InteractiveEvent)
        assert isinstance(await session.next_event(timeout=1), StoppedEvent)


@pytest.mark.parametrize("cancel", [True, False])
async def test_abandoned_interact_updates_shell_state_when_reply_arrives(cancel):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.interact("work()", timeout=2 if cancel else 0.02))
        request = await engine.next_request()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert session.state == "running"
        await engine.respond(request, status="interactive", more=0, prompt="> ")
        event = await session.next_event(timeout=1)
        assert isinstance(event, InteractiveEvent)
        assert session.last_interaction.prompt == "> " and session.state == "interactive"


@pytest.mark.parametrize("attributes", [
    {"status": "interactive", "prompt": "> "},
    {"status": "interactive", "more": "2", "prompt": "> "},
    {"status": "interactive", "more": "0"},
    {"more": "0", "prompt": "> "},
    {"status": "unexpected", "more": "0", "prompt": "> "},
])
async def test_malformed_interact_response_fails_pending_call(attributes):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.interact("work()"))
        await engine.respond(await engine.next_request(), **attributes)
        with pytest.raises(ProtocolError):
            await task
        assert session.closed


async def test_interactive_only_engine_discovers_state_and_snapshot():
    async with fake_session() as (_, session, engine):
        status = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="interactive")
        assert (await status).status == "interactive"
        task = asyncio.create_task(session.snapshot())
        await engine.respond(await engine.next_request(), payload=[xml("stack", level=0, filename="<console>", lineno=1)])
        assert (await task).execution.status == "interactive"


async def test_interact_engine_error_restores_shell_and_can_reset_buffer():
    from dbgpilot import CommandError

    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        first = asyncio.create_task(session.interact("if True:"))
        await engine.respond(await engine.next_request(), status="interactive", more=1, prompt="... ")
        await first
        bad = asyncio.create_task(session.interact("invalid"))
        await engine.respond(await engine.next_request(), payload=[xml("error", code=206)])
        with pytest.raises(CommandError):
            await bad
        assert session.state == "interactive" and session.last_interaction.prompt == "... "
        reset = asyncio.create_task(session.interact(mode=0))
        await engine.respond(await engine.next_request(), status="break", more=0, prompt="")
        assert not (await reset).more


@pytest.mark.parametrize("bare", [True, False])
async def test_proxy_errors_are_events_and_do_not_steal_engine_responses(bare):
    async with fake_session() as (_, session, engine):
        run = asyncio.create_task(session.run())
        request = await engine.next_request()
        node = xml("proxyerror")
        if bare:
            node.tag = "proxyerror"
        error = xml("error", id="proxy.warning")
        message = xml("message")
        message.text = "proxy warning"
        error.append(message)
        node.append(error)
        await engine.send(node)
        event = await session.next_event(timeout=1)
        assert isinstance(event, ProxyErrorEvent) and isinstance(event.error, ProxyError)
        assert event.error.code == "proxy.warning" and not run.done() and not session.closed
        await engine.respond(request, status="break")
        assert (await run).paused


async def test_http_stdin_bypasses_run_guard_and_interact_results_are_structured():
    async with remote_session(engine_options={"feature_values": {"supports_async": "1"}}) as (_, _, remote, engine):
        enable = asyncio.create_task(remote.set_stdin())
        await engine.respond(await engine.next_request(), success=1)
        assert await enable
        run = asyncio.create_task(remote.run())
        run_request = await engine.next_request()
        data = asyncio.create_task(remote.send_stdin(b"\xff\0"))
        assert base64.b64decode((request := await engine.next_request()).data) == b"\xff\0"
        await engine.respond(request, success=1)
        assert await data and not run.done()
        await engine.respond(run_request, status="break")
        await run
        call = asyncio.create_task(remote.interact("print('ok')"))
        await engine.respond(await engine.next_request(), status="interactive", more=0, prompt="> ")
        assert (await call)["prompt"] == "> "
        assert (await remote.info())["interaction"]["status"] == "interactive"
        batch = await remote.events(timeout=0)
        assert any(event["type"] == "InteractiveEvent" for event in batch["events"])
