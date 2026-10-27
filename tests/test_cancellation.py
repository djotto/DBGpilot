import asyncio
import json
import uuid

import pytest

from dbgpilot import Client, Controller, RemoteError, Server
from .helpers import Engine, xml
from .test_server import pause, remote_session, request


async def test_explicit_cancellation_releases_a_waiter_and_does_not_claim_future_php():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        pending = client.request("wait_for_session", timeout=30)
        acknowledgement = await pending.cancel()
        assert acknowledgement["submission_blocked"]
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32010
        engine = await Engine.connect(server.controller)
        try:
            remote = await client.wait_for_session(timeout=2)
            assert remote.id
            assert not server._request_ids
        finally:
            await server.aclose()
            await engine.close()


async def test_cancelling_a_python_coroutine_cancels_its_remote_wait():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        pending = asyncio.create_task(client.wait_for_session(timeout=30))
        await asyncio.sleep(0)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        engine = await Engine.connect(server.controller)
        try:
            assert (await client.wait_for_session(timeout=2)).id
            assert not server._request_ids
        finally:
            await server.aclose()
            await engine.close()


async def test_closing_client_cancels_outstanding_waits_without_closing_php():
    async with remote_session() as (server, first, remote, engine):
        await pause(remote, engine)
        pending = first.request("wait_for_session", timeout=30)
        # Wait until the request has started locally, before closing its client.
        await asyncio.sleep(0)
        await first.aclose()
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32010
        async with Client(server.url) as later:
            assert (await later.session(remote.id).info())["state"] == "break"


async def test_cancellation_before_submission_is_remembered():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        id = uuid.uuid4().hex
        acknowledgement = await client.cancel_request(id)
        assert not acknowledgement["cancelled"] and acknowledgement["submission_blocked"]
        body = json.dumps({"jsonrpc": "2.0", "id": id, "method": "wait_for_session", "params": {"timeout": 30}}).encode()
        status, result = await request(server.url, body=body)
        assert status == 200 and result["error"]["code"] == -32010
        assert not server._request_ids


async def test_cancelled_execution_remains_running_until_the_real_break():
    async with remote_session() as (_, client, remote, engine):
        pending = remote.request("run", timeout=30)
        run = await engine.next_request()
        assert (await pending.cancel())["cancelled"]
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32010
        assert (await remote.info())["state"] == "running"
        assert engine.requests.empty()  # no stop/detach/resume was sent
        await engine.respond(run, status="break", reason="ok")
        assert (await remote.events(timeout=2))["events"][-1]["type"] == "StoppedEvent"
        assert (await remote.info())["state"] == "break"
        task = asyncio.create_task(remote.property_get("$x"))
        prop = xml("property", name="$x", type="int")
        prop.text = "42"
        await engine.respond(await engine.next_request(), payload=[prop])
        assert (await task)["value"] == 42


async def test_cancel_event_poll_keeps_events_replayable():
    async with remote_session() as (_, _, remote, engine):
        pending = remote.request("events", after=0, timeout=30)
        await pending.cancel()
        with pytest.raises(RemoteError) as caught:
            await pending
        assert caught.value.code == -32010
        await engine.send(xml("notify", name="after-cancellation"))
        assert (await remote.events(timeout=2))["events"][0]["data"]["name"] == "after-cancellation"


async def test_ambiguous_ids_are_not_cancelled_and_tombstones_are_bounded():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        body = {"jsonrpc": "2.0", "id": "same", "method": "wait_for_session", "params": {"timeout": 30}}
        first = asyncio.create_task(server.rpc(body))
        second = asyncio.create_task(server.rpc(body))
        await asyncio.sleep(0)
        with pytest.raises(RemoteError) as caught:
            await client.cancel_request("same")
        assert caught.value.code == -32602
        assert not first.done() and not second.done()
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second)
        for i in range(1100):
            server._cancel_request(f"preflight-{i}")
        assert len(server._cancelled) == 1024
        assert "preflight-0" not in server._cancelled


@pytest.mark.parametrize("id", [None, True, [], {}])
async def test_invalid_cancellation_ids(id):
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        with pytest.raises(RemoteError) as caught:
            await client.cancel_request(id)
        assert caught.value.code == -32602
