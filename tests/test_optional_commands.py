"""Spec sections 8.3.1–8.4: optional expression/code and spawnpoint APIs.

Positive cases use real TCP/HTTP with scripted engines: Xdebug advertises none
of these commands. Live rejection coverage is in test_proxy_integration.py.
"""

import asyncio
import base64
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from dbgpilot import (
    Client, CommandError, ConnectionClosed, ProtocolError, RemoteError,
    SessionStateError, Spawnpoint, StoppedEvent, StreamEvent,
)
from .helpers import fake_session, xml
from .test_conformance import pause
from .test_server import pause as remote_pause, remote_session


def property_node(value="42", **attributes):
    node = xml("property", **{"type": "int", **attributes})
    node.text = value
    return node


def point_node(id="opaque:spawn/α", **attributes):
    return xml("spawnpoint", **{
        "id": id, "state": "enabled", "filename": "file:///app/child.tcl", "lineno": "9",
        **attributes,
    })


async def successful_reply(engine, request):
    if request.name == "expr":
        await engine.respond(request, success=1, payload=[property_node()])
    elif request.name == "exec":
        await engine.respond(request, success=1)
    elif request.name == "spawnpoint_set":
        await engine.respond(request, id="opaque:spawn/α", state="enabled")
    elif request.name == "spawnpoint_get":
        await engine.respond(request, payload=[point_node(id=request.arguments["d"])])
    elif request.name == "spawnpoint_list":
        await engine.respond(request, payload=[point_node()])
    else:
        await engine.respond(request)


async def test_expr_decodes_paged_properties_with_depth_and_type_maps():
    async with fake_session(engine_options={"init_attributes": {"language": "Tcl"}}) as (_, session, engine):
        await pause(session, engine)
        types = asyncio.create_task(session.typemap_get())
        await engine.respond(await engine.next_request(), payload=[xml("map", name="whole", type="int")])
        await types
        task = asyncio.create_task(session.expr("café + 1", depth=2, page=3))
        request = await engine.next_request()
        assert request.name == "expr" and request.arguments == {"d": "2", "p": "3"}
        assert base64.b64decode(request.data) == "café + 1".encode()
        await engine.respond(request, success=1, payload=[property_node(type="whole", page=3)])
        result = await task
        assert result.value == 42 and result.type == "whole" and result.common_type == "int" and result.page == 3
        assert session.state == "break" and not session._execution_pending
        assert session._events.empty(), "An on-time expr reply must not emit another stop"


@pytest.mark.parametrize("command", ["expr", "exec"])
@pytest.mark.parametrize("code", ["café", b"\xff\0", b""])
async def test_code_payloads_are_binary_safe_and_exec_has_no_expression_options(command, code):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)(code))
        request = await engine.next_request()
        assert request.name == command
        assert request.arguments == ({"d": "0", "p": "0"} if command == "expr" else {})
        assert base64.b64decode(request.data) == (code.encode() if isinstance(code, str) else code)
        await successful_reply(engine, request)
        result = await task
        assert result.value == 42 if command == "expr" else result is True


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_code_execution_interleaves_events_and_guards_overlapping_operations(command):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)("work()"))
        request = await engine.next_request()
        assert session.state == "running"
        operations = (
            (session.expr, ("x",)), (session.exec, ("x = 1",)),
            (session.evaluate, ("x",)), (session.interact, ()),
            (session.run, ()), (session.property_get, ("x",)),
            (session.detach, ()), (session.stop, ()),
            (session.set_spawnpoint, ()),
        )
        for operation, args in operations:
            with pytest.raises(SessionStateError):
                await operation(*args)
        stream = xml("stream", type="stderr", encoding="base64")
        stream.text = base64.b64encode(b"output\0").decode()
        await engine.send(stream)
        await engine.send(xml("notify", name="custom"))
        assert await session.next_event(timeout=1) == StreamEvent("stderr", b"output\0")
        assert (await session.next_event(timeout=1)).name == "custom"
        await successful_reply(engine, request)
        await task
        assert session._events.empty(), "An on-time evaluation reply must not emit another stop"
        assert session.state == "break"


@pytest.mark.parametrize("command", ["expr", "exec"])
@pytest.mark.parametrize("cancel", [True, False])
@pytest.mark.parametrize("late_error", [True, False])
async def test_abandoned_execution_retains_guard_until_late_success_or_error(command, cancel, late_error):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)("work()", timeout=2 if cancel else 0.02))
        request = await engine.next_request()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        assert session._execution_pending and session.state == "running"
        with pytest.raises(SessionStateError):
            await session.expr("another()")
        if late_error:
            await engine.respond(request, payload=[xml("error", code=206)])
        else:
            await successful_reply(engine, request)
        assert isinstance(await session.next_event(timeout=1), StoppedEvent)
        assert not session._execution_pending and session.state == "break" and not session.closed
        # A new execution is usable after the actual reply, even after an error.
        again = asyncio.create_task(session.exec("next()"))
        await successful_reply(engine, await engine.next_request())
        assert await again


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_execution_deadline_before_write_preserves_paused_state(command):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        async with session._write_lock:
            with pytest.raises(TimeoutError):
                await getattr(session, command)("work()", timeout=0.01)
        assert session.state == "break" and not session._execution_pending and engine.requests.empty()


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_unsuccessful_expression_and_code_return_none_or_false(command):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)("work()"))
        await engine.respond(await engine.next_request(), success=0)
        result = await task
        assert result is (None if command == "expr" else False)
        assert session.state == "break" and not session.closed


@pytest.mark.parametrize("command,attributes,properties", [
    ("expr", {}, []), ("exec", {}, []),
    ("expr", {"success": "2"}, []), ("exec", {"success": "yes"}, []),
    ("expr", {"success": "1"}, []),
    ("expr", {"success": "1"}, [property_node(), property_node()]),
    ("expr", {"success": "1"}, [property_node("bad", type="int")]),
])
async def test_invalid_execution_results_close_the_session(command, attributes, properties):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)("work()"))
        await engine.respond(await engine.next_request(), payload=properties, **attributes)
        with pytest.raises(ProtocolError):
            await task
        assert session.closed


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_execution_uses_interactive_and_capability_gated_postmortem_states(command):
    async with fake_session(engine_options={"feature_values": {"supports_postmortem": "1"}}) as (_, session, engine):
        with pytest.raises(SessionStateError):
            await getattr(session, command)("work()")
        for state in ("interactive", "stopping"):
            status = asyncio.create_task(session.status())
            await engine.respond(await engine.next_request(), status=state)
            await status
            task = asyncio.create_task(getattr(session, command)("work()"))
            await successful_reply(engine, await engine.next_request())
            await task
            assert session.state == state
        session._capabilities["supports_postmortem"] = type(session.capabilities["supports_postmortem"])(True, "0")
        with pytest.raises(SessionStateError):
            await getattr(session, command)("work()")


@pytest.mark.parametrize("arguments", [
    {"depth": -1}, {"depth": True}, {"depth": "2"}, {"depth": 1},
    {"page": -1}, {"page": False}, {"page": 1.5},
])
async def test_expression_rejects_invalid_options_or_unconfigured_depth(arguments):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        with pytest.raises(ValueError):
            await session.expr("x", **arguments)
        assert engine.requests.empty()


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_code_requires_text_or_bytes(command):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        with pytest.raises(TypeError):
            await getattr(session, command)(123)
        assert engine.requests.empty()


CALLS = [
    ("expr", "expr", ("x",)), ("exec", "exec", ("x = 1",)),
    ("spawnpoint_set", "set_spawnpoint", ()),
    ("spawnpoint_get", "get_spawnpoint", ("opaque:spawn/α",)),
    ("spawnpoint_update", "update_spawnpoint", ("opaque:spawn/α",)),
    ("spawnpoint_remove", "remove_spawnpoint", ("opaque:spawn/α",)),
    ("spawnpoint_list", "spawnpoints", ()),
]


@pytest.mark.parametrize("feature,method,args", CALLS)
@pytest.mark.parametrize("support", ["0", None])
async def test_optional_commands_require_their_own_advertised_capability(feature, method, args, support):
    async with fake_session(engine_options={"feature_values": {feature: support}}) as (_, session, engine):
        await pause(session, engine)
        options = {"state": "disabled"} if method == "update_spawnpoint" else {}
        with pytest.raises(SessionStateError, match=feature):
            await getattr(session, method)(*args, **options)
        assert engine.requests.empty() and not session.closed


async def test_spawnpoint_crud_preserves_opaque_ids_actual_state_and_vendor_metadata():
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.set_spawnpoint(Path("/app/café child.tcl"), 9, state="disabled"))
        request = await engine.next_request()
        assert request.arguments == {"f": "file:///app/caf%C3%A9%20child.tcl", "n": "9", "s": "disabled"}
        assert request.data is None
        await engine.respond(request, id="opaque:spawn/α", state="enabled")
        created = await task
        assert isinstance(created, Spawnpoint) and created.type == "spawn" and created.state == "enabled"
        assert created.file == request.arguments["f"] and created.line == 9
        assert session.known_spawnpoints[created.id] == created
        assert not session.known_breakpoints
        with pytest.raises(TypeError):
            session.known_spawnpoints["no"] = created

        task = asyncio.create_task(session.get_spawnpoint(created.id))
        request = await engine.next_request()
        assert request.arguments == {"d": created.id}
        node = point_node(lineno="-1", **{"{urn:vendor}extra": "preserved"})
        ET.SubElement(node, "{urn:vendor}child").text = "details"
        await engine.respond(request, payload=[node])
        fetched = await task
        assert fetched.line == -1  # Preserve an engine's unset-line sentinel.
        assert fetched.attributes["{urn:vendor}extra"] == "preserved" and "details" in fetched.xml
        task = asyncio.create_task(session.update_spawnpoint(created.id, state="disabled", line=12))
        request = await engine.next_request()
        assert request.arguments == {"d": created.id, "s": "disabled", "n": "12"}
        await engine.respond(request)
        assert await task is None
        assert session.known_spawnpoints[created.id].line == 12
        assert session.known_spawnpoints[created.id].state == "disabled"
        assert session.known_spawnpoints[created.id].xml == fetched.xml

        task = asyncio.create_task(session.spawnpoints())
        assert (request := await engine.next_request()).arguments == {}
        await engine.respond(request, payload=[point_node(id="other", state="disabled")])
        assert [point.id for point in await task] == ["other"]
        assert set(session.known_spawnpoints) == {"other"}
        task = asyncio.create_task(session.remove_spawnpoint("other"))
        request = await engine.next_request()
        assert request.arguments == {"d": "other"}
        await engine.respond(request)
        assert await task is None and not session.known_spawnpoints


async def test_spawnpoints_accept_omitted_location_and_empty_list():
    async with fake_session() as (_, session, engine):
        task = asyncio.create_task(session.set_spawnpoint())
        request = await engine.next_request()
        assert request.arguments == {"s": "enabled"}
        await engine.respond(request, id="no-location", state="enabled")
        assert (await task).file is None and session.known_spawnpoints["no-location"].line is None
        task = asyncio.create_task(session.spawnpoints())
        await engine.respond(await engine.next_request())
        assert await task == () and not session.known_spawnpoints


@pytest.mark.parametrize("method,args,options", [
    ("set_spawnpoint", (), {"line": 0}), ("set_spawnpoint", (), {"line": True}),
    ("set_spawnpoint", (), {"state": "temporary"}), ("set_spawnpoint", (), {"state": None}),
    ("set_spawnpoint", (), {"file": 123}), ("set_spawnpoint", ("dbgp:console",), {}),
    ("get_spawnpoint", (None,), {}), ("get_spawnpoint", ("",), {}),
    ("remove_spawnpoint", (5,), {}), ("update_spawnpoint", ("id",), {}),
    ("update_spawnpoint", ("id",), {"line": -1}),
    ("update_spawnpoint", ("id",), {"state": "temporary"}),
])
async def test_invalid_spawnpoint_arguments_are_not_sent(method, args, options):
    async with fake_session() as (_, session, engine):
        with pytest.raises((ValueError, TypeError)):
            await getattr(session, method)(*args, **options)
        assert engine.requests.empty()


@pytest.mark.parametrize("feature,method,args", CALLS)
async def test_engine_errors_preserve_vendor_details_and_leave_inventory_unchanged(feature, method, args):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        options = {"state": "disabled"} if method == "update_spawnpoint" else {}
        task = asyncio.create_task(getattr(session, method)(*args, **options))
        error = xml("error", code=207, **{"{urn:vendor}extra": "keep"})
        ET.SubElement(error, "{urn:vendor}message").text = "cannot perform command"
        await engine.respond(await engine.next_request(), payload=[error])
        with pytest.raises(CommandError) as caught:
            await task
        assert caught.value.command == feature and caught.value.code == 207
        assert caught.value.message == "cannot perform command"
        assert caught.value.attributes["{urn:vendor}extra"] == "keep"
        assert not session.known_spawnpoints and session.state == "break" and not session.closed


@pytest.mark.parametrize("command,attributes,points", [
    ("spawnpoint_set", {"state": "enabled"}, []),
    ("spawnpoint_set", {"id": "id", "state": "temporary"}, []),
    ("spawnpoint_get", {}, []),
    ("spawnpoint_get", {}, [point_node(id="wrong")]),
    ("spawnpoint_get", {}, [point_node(), point_node()]),
    ("spawnpoint_list", {}, [point_node(), point_node()]),
    ("spawnpoint_list", {}, [point_node(type="line")]),
    ("spawnpoint_list", {}, [point_node(lineno="bad")]),
    ("spawnpoint_list", {}, [point_node(state="unknown")]),
])
async def test_malformed_spawnpoint_responses_are_not_committed(command, attributes, points):
    async with fake_session() as (_, session, engine):
        methods = {"spawnpoint_set": session.set_spawnpoint,
                   "spawnpoint_get": lambda: session.get_spawnpoint("opaque:spawn/α"),
                   "spawnpoint_list": session.spawnpoints}
        task = asyncio.create_task(methods[command]())
        await engine.respond(await engine.next_request(), payload=points, **attributes)
        with pytest.raises(ProtocolError):
            await task
        assert session.closed and not session.known_spawnpoints


@pytest.mark.parametrize("command,method,args", CALLS[2:])
@pytest.mark.parametrize("cancel", [True, False])
async def test_spawnpoint_inventory_processes_late_acknowledgements(command, method, args, cancel):
    async with fake_session(command_timeout=0.05) as (_, session, engine):
        seed = asyncio.create_task(session.spawnpoints())
        await engine.respond(await engine.next_request(), payload=[point_node()])
        await seed
        options = {"state": "disabled"} if method == "update_spawnpoint" else {}
        task = asyncio.create_task(getattr(session, method)(*args, **options))
        request = await engine.next_request()
        if cancel:
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
            await task
        await successful_reply(engine, request)
        # A following response is a reader barrier for the earlier late reply.
        status = asyncio.create_task(session.status())
        await engine.respond(await engine.next_request(), status="starting")
        await status
        if command == "spawnpoint_remove":
            assert not session.known_spawnpoints
        elif command == "spawnpoint_update":
            assert session.known_spawnpoints["opaque:spawn/α"].state == "disabled"
        else:
            assert "opaque:spawn/α" in session.known_spawnpoints
        assert not session.closed


async def test_remote_expression_code_and_spawnpoint_results_survive_client_reconnection():
    async with remote_session() as (server, first, remote, engine):
        await remote_pause(remote, engine)
        task = asyncio.create_task(remote.expr(b"\xff\0"))
        request = await engine.next_request()
        assert base64.b64decode(request.data) == b"\xff\0"
        await engine.respond(request, success=1, payload=[property_node("/wA=", type="string", encoding="base64")])
        assert (await task)["value"] == {"encoding": "base64", "data": "/wA="}
        task = asyncio.create_task(remote.exec(b"\xff\0"))
        assert base64.b64decode((request := await engine.next_request()).data) == b"\xff\0"
        await successful_reply(engine, request)
        assert await task is True
        task = asyncio.create_task(remote.set_spawnpoint("/app/child.tcl", 9))
        await successful_reply(engine, await engine.next_request())
        point = await task
        assert point["type"] == "spawn" and point["file"] == "file:///app/child.tcl"
        await first.aclose()
        async with Client(server.url) as later:
            resumed = later.session(remote.id)
            info = await resumed.info()
            assert info["spawnpoints"][point["id"]]["line"] == 9 and info["state"] == "break"
            task = asyncio.create_task(resumed.get_spawnpoint(point["id"]))
            await successful_reply(engine, await engine.next_request())
            assert (await task)["id"] == point["id"]
            task = asyncio.create_task(resumed.update_spawnpoint(point["id"], line=15))
            await successful_reply(engine, await engine.next_request())
            assert await task is None
            assert (await resumed.info())["spawnpoints"][point["id"]]["line"] == 15
            task = asyncio.create_task(resumed.spawnpoints())
            await successful_reply(engine, await engine.next_request())
            assert len(await task) == 1
            task = asyncio.create_task(resumed.remove_spawnpoint(point["id"]))
            await successful_reply(engine, await engine.next_request())
            assert await task is None and not (await resumed.info())["spawnpoints"]
            assert any(event["type"] == "StoppedEvent" for event in (await resumed.events(timeout=0))["events"])


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_remote_cancellation_and_deadline_keep_execution_guard_until_late_reply(command):
    async with remote_session() as (_, client, remote, engine):
        await remote_pause(remote, engine)
        key = "expression" if command == "expr" else "code"
        pending = remote.request(command, **{key: "work()"})
        request = await engine.next_request()
        assert (await pending.cancel())["cancelled"]
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32010
        with pytest.raises(RemoteError) as caught:
            await remote.exec("other()")
        assert caught.value.code == -32002
        await successful_reply(engine, request)
        # Metadata is local; poll events until the late stop is journalled.
        events = await remote.events(timeout=0)
        cursor = events["cursor"]
        if (await remote.info())["state"] == "running":
            await remote.events(after=cursor, timeout=1)
        assert (await remote.info())["state"] == "break"
        task = asyncio.create_task(getattr(remote, command)("work()", timeout=0.02))
        request = await engine.next_request()
        with pytest.raises(RemoteError) as caught:
            await task
        assert caught.value.code == -32003
        await successful_reply(engine, request)


@pytest.mark.parametrize("command,params", [
    ("expr", {"expression": {"encoding": "base64", "data": "bad!"}}),
    ("exec", {"code": 42}), ("expr", {"expression": "x", "depth": True}),
    ("exec", {"code": "x", "depth": 1}),
    ("update_spawnpoint", {"id": "id"}), ("remove_spawnpoint", {"id": ""}),
])
async def test_remote_validation_errors_do_not_reach_engine(command, params):
    async with remote_session() as (_, _, remote, engine):
        await remote_pause(remote, engine)
        with pytest.raises(RemoteError) as caught:
            await remote.call(command, **params)
        assert caught.value.code == -32602 and engine.requests.empty()


@pytest.mark.parametrize("command", ["expr", "exec"])
async def test_disconnect_during_optional_execution_fails_pending_call(command):
    async with fake_session() as (_, session, engine):
        await pause(session, engine)
        task = asyncio.create_task(getattr(session, command)("work()"))
        await engine.next_request()
        await engine.close()
        with pytest.raises(ConnectionClosed):
            await task
        assert session.closed
