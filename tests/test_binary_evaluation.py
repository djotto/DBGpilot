"""Binary evaluation payloads must survive the HTTP and DBGp boundaries."""

import asyncio
import base64
from contextlib import asynccontextmanager

import pytest

from dbgpilot import RemoteError
from .helpers import fake_session, xml
from .test_conformance import pause as local_pause
from .test_server import pause, remote_session


PAYLOADS = [
    pytest.param(b"1 + 1", id="ascii-bytes"),
    pytest.param('strlen("café")'.encode(), id="utf8-bytes"),
    pytest.param(b'strlen("\xff")', id="non-utf8-bytes"),
    pytest.param(b'strlen("a\0b")', id="embedded-nul"),
    pytest.param(b"", id="empty-bytes"),
]


@asynccontextmanager
async def engine_request(operation, engine):
    pending = asyncio.create_task(operation)
    incoming = asyncio.create_task(engine.next_request())
    try:
        done, _ = await asyncio.wait((pending, incoming), return_when=asyncio.FIRST_COMPLETED)
        if pending in done:
            # Report an early RPC error directly instead of timing out on the engine.
            await pending
            pytest.fail("Evaluation finished before the engine received its command")
        yield await incoming, pending
    finally:
        pending.cancel()
        incoming.cancel()
        await asyncio.gather(pending, incoming, return_exceptions=True)


async def reply_with_integer(engine, request):
    prop = xml("property", type="int")
    prop.text = "42"
    await engine.respond(request, payload=[prop])


@pytest.mark.parametrize("expression", PAYLOADS)
async def test_local_evaluate_accepts_binary_payloads(expression):
    async with fake_session() as (_, session, engine):
        await local_pause(session, engine)
        async with engine_request(session.evaluate(expression), engine) as (request, pending):
            assert request.name == "eval"
            assert base64.b64decode(request.data, validate=True) == expression
            await reply_with_integer(engine, request)
            assert (await pending).value == 42


@pytest.mark.parametrize("expression", PAYLOADS)
async def test_remote_evaluate_preserves_binary_payloads_and_options(expression):
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        async with engine_request(remote.evaluate(expression, page=3), engine) as (request, pending):
            assert request.name == "eval" and request.arguments == {"d": "0", "p": "3"}
            assert base64.b64decode(request.data, validate=True) == expression
            await reply_with_integer(engine, request)
            result = await pending
            assert result["type"] == "int" and result["value"] == 42
        info = await remote.info()
        assert info["state"] == "break" and not info["closed"]


@pytest.mark.parametrize("expression", ["1 + 1", 'strlen("café")'])
async def test_remote_evaluate_preserves_text_payloads(expression):
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        async with engine_request(remote.evaluate(expression), engine) as (request, pending):
            assert request.name == "eval"
            assert base64.b64decode(request.data, validate=True) == expression.encode("utf-8")
            await reply_with_integer(engine, request)
            assert (await pending)["value"] == 42


@pytest.mark.parametrize("expression", [b'strlen("\xff")', b""], ids=["non-utf8", "empty"])
async def test_evaluate_accepts_explicit_json_binary_envelope(expression):
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        envelope = {"encoding": "base64", "data": base64.b64encode(expression).decode("ascii")}
        operation = remote.call("evaluate", expression=envelope)
        async with engine_request(operation, engine) as (request, pending):
            assert request.name == "eval"
            assert base64.b64decode(request.data, validate=True) == expression
            # Binary results must retain their JSON envelope, too.
            prop = xml("property", type="string", encoding="base64", size=2)
            prop.text = "/wA="
            await engine.respond(request, payload=[prop])
            assert (await pending)["value"] == {"encoding": "base64", "data": "/wA="}


async def test_binary_evaluate_preserves_engine_errors_and_paused_session():
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        async with engine_request(remote.evaluate(b'bad("\xff")'), engine) as (request, pending):
            assert request.name == "eval"
            assert base64.b64decode(request.data, validate=True) == b'bad("\xff")'
            error = xml("error", code=206)
            message = xml("message")
            message.text = "Evaluation failed in the engine"
            error.append(message)
            await engine.respond(request, payload=[error])
            with pytest.raises(RemoteError) as caught:
                await pending
            assert caught.value.code == -32004
            assert caught.value.data["code"] == 206 and caught.value.data["command"] == "eval"
        info = await remote.info()
        assert info["state"] == "break" and not info["closed"]


@pytest.mark.parametrize("envelope,message", [
    ({"encoding": "base64", "data": "bad!"}, "Invalid base64 argument"),
    ({"encoding": "hex", "data": "ff"}, "Binary values require encoding='base64'"),
    ({"encoding": "base64", "data": 42}, "Binary data must be a base64 string"),
    ({"encoding": "base64"}, "Binary values require encoding='base64'"),
], ids=["invalid-base64", "wrong-encoding", "non-string-data", "missing-data"])
async def test_malformed_evaluation_envelopes_fail_before_reaching_engine(envelope, message):
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        with pytest.raises(RemoteError) as caught:
            await remote.call("evaluate", expression=envelope)
        assert caught.value.code == -32602
        assert message in caught.value.message
        assert engine.requests.empty()
        info = await remote.info()
        assert info["state"] == "break" and not info["closed"]
