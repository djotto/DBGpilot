"""Malformed context IDs are engine protocol errors, including over HTTP."""

import asyncio

import pytest

from dbgpilot import ProtocolError, RemoteError
from .helpers import fake_session, xml
from .test_server import remote_session


INVALID_IDS = [
    pytest.param(None, id="missing"),
    pytest.param("", id="empty"),
    pytest.param("oops", id="nonnumeric"),
    pytest.param("1.5", id="fractional"),
]


def malformed_contexts(identifier):
    attributes = {} if identifier is None else {"id": identifier}
    return [xml("context", id=0, name="Locals"), xml("context", name="Broken", **attributes)]


@pytest.mark.parametrize("identifier", INVALID_IDS)
async def test_contexts_rejects_malformed_ids_as_protocol_errors(identifier):
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.contexts(depth=3))
        request = await engine.next_request()
        assert request.name == "context_names" and request.arguments == {"d": "3"}
        await engine.respond(request, payload=malformed_contexts(identifier))
        with pytest.raises(ProtocolError):
            await pending


@pytest.mark.parametrize("identifier", INVALID_IDS)
async def test_remote_contexts_reports_malformed_ids_as_protocol_errors(identifier):
    async with remote_session() as (_, _, remote, engine):
        pending = asyncio.create_task(remote.call("contexts", depth=3))
        request = await engine.next_request()
        assert request.name == "context_names" and request.arguments == {"d": "3"}
        await engine.respond(request, payload=malformed_contexts(identifier))
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32005
        assert caught.value.data["type"] == "ProtocolError"


def valid_contexts():
    return [
        xml("context", id=7, name="Globals"),
        xml("context", id=0, name="Locals"),
        xml("context", id=2),
    ]


@pytest.mark.parametrize("empty", [False, True], ids=["named-and-unnamed", "empty"])
async def test_contexts_preserves_valid_ids_and_names(empty):
    async with fake_session() as (_, session, engine):
        pending = asyncio.create_task(session.contexts(depth=3))
        request = await engine.next_request()
        assert request.name == "context_names" and request.arguments == {"d": "3"}
        await engine.respond(request, payload=[] if empty else valid_contexts())
        assert await pending == ({} if empty else {7: "Globals", 0: "Locals", 2: ""})


@pytest.mark.parametrize("empty", [False, True], ids=["named-and-unnamed", "empty"])
async def test_remote_contexts_preserves_valid_ids_and_names(empty):
    async with remote_session() as (_, _, remote, engine):
        pending = asyncio.create_task(remote.call("contexts", depth=3))
        request = await engine.next_request()
        assert request.name == "context_names" and request.arguments == {"d": "3"}
        await engine.respond(request, payload=[] if empty else valid_contexts())
        # JSON object keys are strings on the HTTP API.
        assert await pending == ({} if empty else {"7": "Globals", "0": "Locals", "2": ""})


async def test_remote_contexts_keeps_invalid_caller_arguments_as_invalid_params():
    async with remote_session() as (_, _, remote, engine):
        with pytest.raises(RemoteError) as caught:
            await remote.call("contexts", depth="oops")
        assert caught.value.code == -32602
        assert caught.value.data["type"] == "InvalidParams"
        assert engine.requests.empty()
