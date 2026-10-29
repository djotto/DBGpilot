"""Regression cases from the DBGp specification audit.

Scripted peers exercise protocol shapes/capabilities PHP cannot provide.
Live Xdebug assertions live separately in test_integration.py.
"""

import asyncio
import base64
import json
import xml.etree.ElementTree as ET

import pytest

from dbgpilot import (
    CommandError, ConnectionClosed, Controller, ExecutionResult, NotificationEvent,
    ProtocolError, SessionStateError, StoppedEvent, StreamEvent,
)
from dbgpilot.models import parse_breakpoint, parse_frame, parse_property
from .helpers import Engine, fake_session, xml


async def pause(session, engine):
    task = asyncio.create_task(session.run_until_break())
    await engine.respond(await engine.next_request(), status="break", reason="ok")
    await task
    assert isinstance(await session.next_event(timeout=1), StoppedEvent)


@pytest.mark.parametrize("encoding", ["base64", "none"])
async def test_notification_mixed_body_excludes_child_text_and_preserves_metadata(encoding):
    async with fake_session() as (_, session, engine):
        data = b"before\0after" if encoding == "base64" else b"before after"
        body = base64.b64encode(data).decode() if encoding == "base64" else data.decode()
        node = xml("notify", name="error", encoding=encoding)
        node.text = body[:4]
        message = ET.SubElement(node, "{urn:vendor}message", filename="file:///a.php",
                                lineno="9", type="Notice", extra="keep")
        message.text = "child text is metadata"
        message.tail = body[4:]
        await engine.send(node)
        event = await session.next_event(timeout=1)
        assert isinstance(event, NotificationEvent)
        assert event.data == data
        assert event.message.text == "child text is metadata"
        assert (event.message.file, event.message.line, event.message.type) == ("file:///a.php", 9, "Notice")
        assert event.message.attributes["extra"] == "keep"
        assert "child text is metadata" in event.xml


async def test_resolution_notifications_update_known_breakpoint_records():
    async with fake_session() as (_, session, engine):
        node = xml("notify", name="breakpoint_resolved")
        node.append(xml("breakpoint", id="opaque", type="call", function="work", resolved="resolved"))
        await engine.send(node)
        event = await session.next_event(timeout=1)
        assert event.breakpoint.function == "work"
        assert session.known_breakpoints["opaque"] == event.breakpoint
        with pytest.raises(TypeError):
            session.known_breakpoints["other"] = event.breakpoint


async def test_evaluation_blocks_overlapping_execution_and_dispatches_interleaved_events():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.evaluate("work()", page=2))
        request = await engine.next_request()
        assert request.name == "eval" and request.arguments == {"d": "0", "p": "2"}
        assert session.state == "running"
        for operation in (session.run, session.step_into, session.evaluate,
                          session.property_get, session.detach, session.stop):
            args = ("$value",) if operation in (session.evaluate, session.property_get) else ()
            with pytest.raises(SessionStateError):
                await operation(*args)
        assert not session.closed
        stream = xml("stream", type="stderr", encoding="base64")
        stream.text = base64.b64encode(b"output").decode()
        await engine.send(stream)
        await engine.send(xml("notify", name="custom"))
        prop = xml("property", type="int")
        prop.text = "42"
        await engine.respond(request, payload=[prop])  # eval need not have status
        assert (await task).value == 42
        assert session.state == "break"
        assert await session.next_event(timeout=1) == StreamEvent("stderr", b"output")
        assert (await session.next_event(timeout=1)).name == "custom"
        assert session._events.empty(), "An on-time evaluation reply must not emit another stop"


@pytest.mark.parametrize("cancel", [True, False])
@pytest.mark.parametrize("late_error", [True, False])
async def test_abandoned_eval_restores_state_on_late_success_or_error(cancel, late_error):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.evaluate("work()", timeout=2 if cancel else 0.02))
        request = await engine.next_request()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert session.state == "running"
        with pytest.raises(SessionStateError):
            await session.run()
        await engine.respond(request, payload=[xml("error", code=206)] if late_error else [])
        assert isinstance(await session.next_event(timeout=1), StoppedEvent)
        assert session.state == "break" and not session.closed
        assert not session._execution_pending
        # A subsequent execution must be allowed after the actual response.
        await pause(session, engine)


async def test_evaluation_error_preserves_vendor_data_and_restores_state():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.evaluate("bad()"))
        error = xml("error", code=206)
        error.set("{urn:vendor}detail", "keep")
        ET.SubElement(error, "{urn:vendor}message").text = "invalid code"
        ET.SubElement(error, "{urn:vendor}extra").text = "extended details"
        await engine.respond(await engine.next_request(), payload=[error])
        with pytest.raises(CommandError) as caught:
            await task
        assert caught.value.attributes["{urn:vendor}detail"] == "keep"
        assert "extended details" in caught.value.xml
        assert caught.value.message == "invalid code"
        assert session.state == "break" and not session.closed


async def test_eval_timeout_before_write_does_not_leave_engine_running():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        async with session._write_lock:
            with pytest.raises(TimeoutError):
                await session.evaluate("work()", timeout=0.01)
        assert session.state == "break" and not session._execution_pending
        assert engine.requests.empty()


async def test_previous_execution_cleanup_cannot_reset_a_new_execution(monkeypatch):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        original = session.command
        consumed, release = asyncio.Event(), asyncio.Event()
        first = True

        async def delayed_command(name, *args, **kwargs):
            nonlocal first
            delay = name == "run" and first
            if delay:
                first = False
            result = await original(name, *args, **kwargs)
            if delay:
                consumed.set()
                await release.wait()
            return result

        monkeypatch.setattr(session, "command", delayed_command)
        previous = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), status="break", reason="ok")
        await consumed.wait()
        async with session._write_lock:
            following = asyncio.create_task(session.evaluate("$x"))
            await asyncio.sleep(0)
            release.set()
            assert (await previous).paused
            assert session.state == "running"
            with pytest.raises(SessionStateError):
                await session.property_get("$x")
        await engine.respond(await engine.next_request())
        assert await following is None
        assert session.state == "break"


async def test_non_php_eval_depth_and_engine_native_assignment():
    async with fake_session(engine_options={"init_attributes": {"language": "Python"}}) as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.evaluate("x + 1", depth=2, page=3))
        request = await engine.next_request()
        assert request.arguments == {"d": "2", "p": "3"}
        await engine.respond(request, success=1)
        assert await task is None
        with pytest.raises(SessionStateError, match="PHP"):
            await session.set_value("x", "value")
        assignment = asyncio.create_task(session.property_set("x", b"\xff", address="0xabc", depth=2))
        request = await engine.next_request()
        assert request.arguments["a"] == "0xabc" and request.arguments["l"] == "1"
        assert base64.b64decode(request.data) == b"\xff"
        await engine.respond(request, success=1)
        assert await assignment


async def test_php_eval_depth_override_is_explicit():
    async with fake_session(eval_depth_supported=True) as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.evaluate("$x", depth=1))
        assert (request := await engine.next_request()).arguments["d"] == "1"
        await engine.respond(request)
        assert await task is None


async def test_late_run_error_restores_state_after_cancellation():
    async with fake_session(engine_options={"feature_values": {"supports_async": "1"}}) as (_, session, engine):
        task = asyncio.create_task(session.run())
        request = await engine.next_request()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await engine.respond(request, payload=[xml("error", code=5)])
        # A later response fences the preceding late error on the same socket.
        status = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="starting", reason="ok")
        await status
        assert session.state == "starting" and not session._execution_pending
        await pause(session, engine)


async def test_core_wrappers_decode_status_stack_depth_and_type_maps():
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="starting", reason="ok")
        assert await task == ExecutionResult("starting", "ok")
        await pause(session, engine)
        task = asyncio.create_task(session.stack_depth())
        await engine.respond(await engine.next_request(), depth=3)
        assert await task == 3
        task = asyncio.create_task(session.typemap_get())
        mapping = xml("map", name="custom_integer", type="int")
        mapping.set("{http://www.w3.org/2001/XMLSchema-instance}type", "xsd:integer")
        await engine.respond(await engine.next_request(), payload=[mapping])
        entries = await task
        assert entries[0].schema_type == "xsd:integer"
        assert entries[0].language_type == "custom_integer"
        assert session.type_map["custom_integer"] == entries[0]
        for method, args in [(session.property_get, ("$custom",)), (session.context, ()),
                             (session.evaluate, ("$custom",))]:
            task = asyncio.create_task(method(*args))
            prop = xml("property", name="$custom", type="custom_integer")
            prop.text = "123"
            await engine.respond(await engine.next_request(), payload=[prop])
            result = await task
            if isinstance(result, tuple):
                result = result[0]
            assert result.value == 123 and result.type == "custom_integer"
            assert result.common_type == "int"


@pytest.mark.parametrize("value", [None, "bad", "-1"])
async def test_invalid_stack_depth_is_rejected(value):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.stack_depth())
        await engine.respond(await engine.next_request(), **({} if value is None else {"depth": value}))
        with pytest.raises(ProtocolError):
            await task


async def test_missing_status_or_typemap_fields_are_rejected():
    async with fake_session() as (_, session, engine):
        for method, payload in [(session.status, []), (session.typemap_get, [xml("map", name="x")])]:
            task = asyncio.create_task(method())
            await engine.respond(await engine.next_request(), payload=payload)
            with pytest.raises(ProtocolError):
                await task


@pytest.mark.parametrize("kind", ["call", "return", "exception", "conditional", "watch", "line"])
async def test_breakpoint_creation_preserves_options_and_disabled_state(kind):
    async with fake_session(engine_options={"feature_values": {
        "breakpoint_types": "line call return exception conditional watch",
    }}) as (_, session, engine):
        options = dict(kind=kind, state="disabled", temporary=True, hit_value=3, hit_condition="%")
        if kind in {"call", "return"}:
            options["function"] = "work"
        if kind == "exception":
            options["exception"] = "Example"
        if kind in {"conditional", "watch"}:
            options["condition"] = "$x > 2"
        if kind in {"line", "conditional"}:
            options["file"] = "file:///app.php"
        if kind == "line":
            options["line"] = 4
        task = asyncio.create_task(session.set_breakpoint(**options))
        request = await engine.next_request()
        assert request.arguments["s"] == "disabled"
        assert request.arguments["h"] == "3" and request.arguments["o"] == "%"
        if kind == "conditional":
            assert "n" not in request.arguments
        await engine.respond(request, id="opaque", state="disabled", resolved="unresolved")
        bp = await task
        assert bp.state == "disabled" and bp.hit_value == 3 and bp.temporary
        assert bp.function == options.get("function") and bp.exception == options.get("exception")
        assert bp.expression == options.get("condition")
        assert session.known_breakpoints[bp.id] == bp


def test_breakpoint_frame_and_property_metadata_are_preserved_and_json_safe():
    bp = parse_breakpoint(xml("breakpoint", id="id", type="call", function="work", exception="Example",
                             expression="$x > 1", temporary=1, hit_count=4))
    assert bp.function == "work" and bp.exception == "Example"
    assert bp.expression == "$x > 1" and bp.temporary and bp.hit_count == 4
    child = xml("expression", encoding="base64")
    child.text = base64.b64encode(b"child expression").decode()
    node = xml("breakpoint", id="id", expression="attribute expression")
    node.append(child)
    assert parse_breakpoint(node).expression == "child expression"
    stack = xml("stack", level=0, filename="file:///transform.xsl", lineno=4,
                cmdbegin="4:2", cmdend="4:8", where="work", type="eval")
    stack.append(xml("input", level=0, filename="dbgp:input", lineno=9))
    frame = parse_frame(stack)
    assert frame.cmdbegin == "4:2" and frame.cmdend == "4:8"
    assert frame.inputs[0].file == "dbgp:input"
    assert frame.to_dict()["inputs"][0]["line"] == 9
    prop = xml("property", name="$x", fullname="$x", type="int", facet="private constant",
               constant=1, key="key", address="0x123")
    prop.text = "1"
    data = parse_property(prop).to_dict()
    assert data["facets"] == ["private", "constant"] and data["constant"] is True
    assert data["key"] == "key" and data["address"] == "0x123"
    json.dumps({"breakpoint": bp.to_dict(), "frame": frame.to_dict(), "property": data})


async def test_selected_stack_frame_retains_nested_locations():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.stack(depth=2))
        request = await engine.next_request()
        assert request.arguments == {"d": "2"}
        node = xml("stack", level=2, filename="dbgp:code", lineno=5, cmdbegin="5:0", cmdend="5:9")
        node.append(xml("input", level=2, filename="file:///input.xml", lineno=8))
        await engine.respond(request, payload=[node])
        result = (await task)[0]
        assert result.level == 2 and result.inputs[0].line == 8


async def test_property_value_options_metadata_and_bytes_compatibility():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.property_value_info("$x", depth=2, context=1,
                                                              page=3, key="k", address="a", max_data=2))
        request = await engine.next_request()
        assert request.arguments == {"n": "$x", "d": "2", "c": "1", "p": "3",
                                     "k": "k", "a": "a", "m": "2"}
        node = xml("response", command=request.name, transaction_id=request.id,
                   size=10, encoding="base64", page=3)
        node.text = base64.b64encode(b"\xff\0").decode()
        await engine.send(node)
        value = await task
        assert value.data == b"\xff\0" and value.size == 10 and value.truncated
        assert value.page == 3 and value.key == "k" and value.address == "a"
        json.dumps(value.to_dict())
        task = asyncio.create_task(session.property_value("$x"))
        request = await engine.next_request()
        assert request.arguments["m"] == "0"
        node = xml("response", command=request.name, transaction_id=request.id, size=5)
        node.text = "hello"
        await engine.send(node)
        assert await task == b"hello"


@pytest.mark.parametrize("ending", ["reply", "clean_eof", "partial_header", "partial_body", "error", "malformed"])
async def test_stop_accepts_only_a_reply_or_clean_packet_boundary_eof(ending):
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.stop())
        request = await engine.next_request()
        assert request.name == "stop"
        if ending == "reply":
            await engine.respond(request, status="stopped", reason="ok")
        elif ending == "error":
            await engine.respond(request, payload=[xml("error", code=5)])
        elif ending == "malformed":
            engine.writer.write(b"1\0<\0")
            await engine.writer.drain()
        else:
            payload = {"clean_eof": b"", "partial_header": b"12", "partial_body": b"12\0<res"}[ending]
            engine.writer.write(payload)
            await engine.writer.drain()
            await engine.close()
        if ending in {"reply", "clean_eof"}:
            assert (await task).status == "stopped"
            assert session.state == "stopped"
        else:
            error = CommandError if ending == "error" else ProtocolError if ending == "malformed" else ConnectionClosed
            with pytest.raises(error):
                await task
        assert session.closed


async def test_capabilities_gate_optional_commands_and_breakpoint_types():
    async with fake_session(engine_options={"feature_values": {"eval": None, "detach": "0"}}) as (_, session, engine):
        assert not session.supports_command("eval") and not session.supports_command("detach")
        assert not session.capabilities["eval"].supported
        with pytest.raises(TypeError):
            session.capabilities["eval"] = None
        with pytest.raises(SessionStateError, match="detach"):
            await session.detach()
        assert not session.closed
        await pause(session, engine)
        with pytest.raises(SessionStateError, match="eval"):
            await session.evaluate("$x")
        with pytest.raises(SessionStateError, match="watch"):
            await session.set_breakpoint(kind="watch", condition="$x")
        assert engine.requests.empty()


async def test_capability_refresh_and_successful_settings_are_observable():
    async with fake_session(engine_options={"feature_set_results": {"max_depth": "0"}}) as (_, session, engine):
        assert not session.supports_async
        engine.features["supports_async"] = "1"
        assert (await session.refresh_capabilities())["supports_async"].enabled
        assert session.supports_async
        assert await session.feature_set("max_children", 12)
        assert session.capabilities["max_children"].value == "12"
        before = session.capabilities.get("max_depth")
        assert not await session.feature_set("max_depth", 12)
        assert session.capabilities.get("max_depth") == before


async def test_rejected_optional_features_do_not_reject_the_connection():
    async with Controller(port=0) as controller:
        engine = await Engine.connect(
            controller, feature_values={"max_depth": "2", "notify_ok": "0"},
            feature_errors={"spawnpoint_set": 3, "interact": 4},
            feature_set_results={"max_depth": 3, "notify_ok": 4},
        )
        try:
            session = await controller.wait_for_session(timeout=2)
            assert not session.supports_command("spawnpoint_set")
            assert not session.supports_command("interact")
            assert session.capabilities["max_depth"].value == "2"
            assert not session.capabilities["notify_ok"].enabled
            engine.features["supports_async"] = "1"
            await session.refresh_capabilities()
            assert session.supports_async
            engine.feature_errors["supports_async"] = 3
            await session.refresh_capabilities()
            assert not session.supports_async
        finally:
            await controller.aclose()
            await engine.close()


async def test_remaining_core_targeting_and_breakpoint_update_options():
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(session.property_get("$array", depth=2, context=1, page=3,
                                                       max_data=64, key="opaque-key", address="0x123"))
        request = await engine.next_request()
        assert request.arguments == {"n": "$array", "d": "2", "c": "1", "p": "3",
                                     "m": "64", "k": "opaque-key", "a": "0x123"}
        await engine.respond(request, payload=[xml("property", type="array", page=3)])
        assert (await task).page == 3
        task = asyncio.create_task(session.set_breakpoint("file:///app.php", 5))
        await engine.respond(await engine.next_request(), id="opaque")
        bp = await task
        task = asyncio.create_task(session.update_breakpoint(bp.id, state="disabled", line=8,
                                                            hit_value=3, hit_condition="=="))
        request = await engine.next_request()
        assert request.arguments == {"d": "opaque", "s": "disabled", "n": "8", "h": "3", "o": "=="}
        await engine.respond(request)
        await task
        assert session.known_breakpoints[bp.id].state == "disabled"
        assert session.known_breakpoints[bp.id].line == 8
        task = asyncio.create_task(session.remove_breakpoint(bp.id))
        await engine.respond(await engine.next_request())
        await task
        assert bp.id not in session.known_breakpoints


@pytest.mark.parametrize("uri", [None, "dbgp:opaque-code"])
async def test_source_ranges_and_virtual_or_current_file(uri):
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.source(uri, begin=2, end=4))
        request = await engine.next_request()
        assert request.arguments == {"b": "2", "e": "4", **({"f": uri} if uri else {})}
        node = xml("response", command="source", transaction_id=request.id, success=1, encoding="base64")
        node.text = base64.b64encode(b"source\0\xff").decode()
        await engine.send(node)
        assert await task == b"source\0\xff"


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
@pytest.mark.parametrize("mode", [0, 1, 2])
async def test_output_modes_and_stream_names(stream, mode):
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.set_output(stream, mode=mode))
        request = await engine.next_request()
        assert request.name == stream and request.arguments == {"c": str(mode)}
        await engine.respond(request, success=1)
        assert await task


async def test_asynchronous_interrupt_has_its_own_response_before_run_stops():
    async with fake_session(engine_options={"feature_values": {"supports_async": "1"}}) as (_, session, engine):
        run = asyncio.create_task(session.run())
        run_request = await engine.next_request()
        status = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="running", reason="ok")
        assert (await status).status == "running"
        interrupt = asyncio.create_task(session.interrupt())
        request = await engine.next_request()
        assert request.name == "break"
        await engine.respond(request, success=1)
        await interrupt
        assert not run.done() and session.state == "running"
        await engine.respond(run_request, status="break", reason="ok")
        assert (await run).paused


@pytest.mark.parametrize("postmortem", ["0", "1"])
async def test_postmortem_inspection_is_capability_aware(postmortem):
    async with fake_session(engine_options={"feature_values": {"supports_postmortem": postmortem}}) as (_, session, engine):
        run = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), status="stopping", reason="ok")
        await run
        if postmortem == "0":
            with pytest.raises(SessionStateError):
                await session.context()
        else:
            task = asyncio.create_task(session.context())
            await engine.respond(await engine.next_request())
            assert await task == ()


async def test_utf8_constraint_and_negotiation_are_explicit():
    async with fake_session(engine_options={"feature_values": {"encoding": "ISO-8859-1"}}) as (_, session, engine):
        assert session.capabilities["encoding"].value == "UTF-8"
        assert engine.features["encoding"] == "UTF-8"
        with pytest.raises(ValueError, match="UTF-8"):
            await session.feature_set("encoding", "ISO-8859-1")
        with pytest.raises(ValueError, match="base64"):
            await session.feature_set("data_encoding", "none")


async def test_engine_rejecting_utf8_is_rejected_without_disabling_listener():
    async with Controller(port=0, features={}) as controller:
        engine = await Engine.connect(controller, feature_values={"encoding": "ASCII"},
                                      feature_set_results={"encoding": "0"})
        try:
            error = await controller.next_error(timeout=2)
            assert isinstance(error, ProtocolError) and "UTF-8" in str(error)
            assert not controller.sessions
        finally:
            await engine.close()


async def test_init_retains_relationship_engine_and_vendor_information():
    engine_info = xml("engine", version="3.5.3")
    engine_info.text = "Xdebug"
    vendor = ET.Element("{urn:vendor}custom", secret="kept")
    options = {"init_attributes": {"session": "cookie", "thread": "thread-id", "parent": "parent-id",
                                   "proxied": "192.0.2.1", "extra": "kept"},
               "init_children": [engine_info, vendor]}
    async with fake_session(engine_options=options) as (_, session, _):
        info = session.info
        assert (info.cookie, info.thread, info.parent, info.proxied) == ("cookie", "thread-id", "parent-id", "192.0.2.1")
        assert info.engine == "Xdebug" and info.engine_version == "3.5.3"
        assert info.attributes["extra"] == "kept" and "secret" in info.xml


@pytest.mark.parametrize("raw_name,raw_value", [
    ("$café".encode(), "café".encode()), (b"$binary\xff", b"\xff"),
])
async def test_xdebug_byte_xml_names_round_trip_without_transcoding(raw_name, raw_value):
    engine_info = xml("engine", version="3.5.3")
    engine_info.text = "Xdebug"
    async with fake_session(engine_options={"init_children": [engine_info], "feature_values": {
        "encoding": "iso-8859-1", "supported_encodings": "iso-8859-1",
    }}) as (_, session, engine):
        assert session.capabilities["encoding"].value == "iso-8859-1"
        await pause(session, engine)
        name = raw_name.decode("utf-8", "surrogateescape")
        task = asyncio.create_task(session.property_get(name))
        request = await engine.next_request()
        assert request.arguments["n"].encode("utf-8", "surrogateescape") == raw_name
        payload = (f'<?xml version="1.0" encoding="iso-8859-1"?>'
                   f'<response xmlns="urn:debugger_protocol_v1" command="property_get" transaction_id="{request.id}">'
                   f'<property name="{name}" fullname="{name}" type="string" size="{len(raw_value)}">').encode("utf-8", "surrogateescape")
        payload += raw_value + b'</property></response>'
        await engine.send(payload)
        prop = await task
        assert prop.name == name
        assert prop.raw_value == raw_value and not prop.value_truncated
        assert prop.value == (raw_value if b"\xff" in raw_value else raw_value.decode())


async def test_continuation_breakpoint_details_are_json_safe():
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.run())
        await engine.respond(await engine.next_request(), status="break", payload=[
            xml("breakpoint", id="id", type="call", function="work", hit_count=2),
        ])
        result = await task
        assert result.breakpoint_id == "id" and result.breakpoint.function == "work"
        assert result.to_dict()["breakpoint"]["hit_count"] == 2
        json.dumps(result.to_dict())
