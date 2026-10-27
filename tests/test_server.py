"""Exercise the public API over actual HTTP and independent connections."""

import asyncio
import base64
from contextlib import asynccontextmanager
import json
import sys
from types import SimpleNamespace

import pytest

from dbgpilot import Client, ConnectionClosed, Controller, RemoteError, Server
from .helpers import Engine, frame, xml


@asynccontextmanager
async def remote_session(*, server_options=None, engine_options=None):
    async with Server(port=0, controller=Controller(port=0, features={}), **(server_options or {})) as server:
        engine = await Engine.connect(server.controller, **(engine_options or {}))
        async with Client(server.url, token=server.token) as client:
            try:
                remote = await client.wait_for_session(timeout=2)
                yield server, client, remote, engine
            finally:
                await server.aclose()
                await engine.close()


async def pause(remote, engine):
    run = asyncio.create_task(remote.run_until_break(timeout=2))
    await engine.respond(await engine.next_request(), status="break", reason="ok")
    assert (await run)["status"] == "break"


async def request(url, *, body=b"{}", headers=None, path="/rpc", method="POST"):
    port = int(url.rsplit(":", 1)[1])
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    fields = {"Host": f"127.0.0.1:{port}", "Content-Type": "application/json",
              "Content-Length": str(len(body)), **(headers or {})}
    payload = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{key}: {value}\r\n" for key, value in fields.items()) + "\r\n"
    writer.write(payload.encode() + body)
    await writer.drain()
    status = int((await reader.readline()).split()[1])
    while await reader.readline() != b"\r\n":
        pass
    data = json.loads(await reader.read())
    writer.close()
    await writer.wait_closed()
    return status, data


async def test_health_inventory_and_ids_survive_client_disconnect():
    async with remote_session() as (server, first, remote, engine):
        assert (await first.health())["xdebug_port"] == server.controller.port
        assert (await first.sessions())[0]["session_id"] == remote.id
        await pause(remote, engine)
        await first.aclose()
        with pytest.raises(ConnectionClosed):
            await first.health()
        async with Client(server.url) as second:
            again = second.session(remote.id)
            info = await again.info()
            assert info["state"] == "break" and not info["closed"]
            assert info["capabilities"]["eval"]["value"] == "1"
            task = asyncio.create_task(again.property_get("$x"))
            prop = xml("property", name="$x", type="int")
            prop.text = "42"
            await engine.respond(await engine.next_request(), payload=[prop])
            assert (await task)["value"] == 42


async def test_break_and_return_captures_snapshot_without_resuming_or_closing():
    async with remote_session() as (server, client, remote, engine):
        task = asyncio.create_task(remote.break_and_return(["$value"], timeout=2))
        await engine.respond(await engine.next_request(), status="break", reason="ok")
        stack = await engine.next_request()
        assert stack.name == "stack_get"
        await engine.respond(stack, payload=[xml("stack", level=0, filename="file:///app.php", lineno=9)])
        prop = xml("property", name="$value", fullname="$value", type="string", encoding="base64")
        prop.text = base64.b64encode(b"\xff\0").decode()
        await engine.respond(await engine.next_request(), payload=[prop])
        snapshot = await task
        assert snapshot["session_id"] == remote.id and snapshot["execution"]["status"] == "break"
        assert snapshot["frames"][0]["line"] == 9
        assert snapshot["variables"]["$value"]["value"] == {"encoding": "base64", "data": "/wA="}
        await client.aclose()
        async with Client(server.url) as later:
            assert (await later.session(remote.id).info())["state"] == "break"
        assert engine.requests.empty()


async def test_session_filters_do_not_consume_other_requests():
    async with Server(port=0, controller=Controller(port=0, features={})) as server:
        engines = [await Engine.connect(server.controller, idekey=key) for key in ("first", "second")]
        try:
            async with Client(server.url) as client:
                second = await client.wait_for_session(idekey="second", timeout=2)
                assert second.initial_info["info"]["idekey"] == "second"
                first = await client.wait_for_session(idekey="first", timeout=2)
                assert first.id != second.id
                with pytest.raises(RemoteError) as caught:
                    await client.wait_for_session(timeout=0.01)
                assert caught.value.code == -32003
                assert len(await client.sessions()) == 2
        finally:
            await server.aclose()
            for engine in engines:
                await engine.close()


async def test_timed_out_wait_does_not_claim_future_session():
    async with Server(port=0, controller=Controller(port=0, features={})) as server:
        async with Client(server.url) as client:
            with pytest.raises(RemoteError) as caught:
                await client.wait_for_session(timeout=0.01)
            assert caught.value.code == -32003
            engine = await Engine.connect(server.controller)
            try:
                assert (await client.wait_for_session(timeout=2)).id
            finally:
                await server.aclose()
                await engine.close()


async def test_multiple_waiters_claim_distinct_sessions():
    async with Server(port=0, controller=Controller(port=0, features={})) as server:
        async with Client(server.url) as client:
            waiters = [asyncio.create_task(client.wait_for_session(timeout=2)) for _ in range(2)]
            engines = [await Engine.connect(server.controller, idekey=str(i)) for i in range(2)]
            try:
                first, second = await asyncio.gather(*waiters)
                assert first.id != second.id
            finally:
                await server.aclose()
                for engine in engines:
                    await engine.close()


async def test_events_replay_for_independent_cursors_and_long_poll():
    async with remote_session() as (_, client, remote, engine):
        first = asyncio.create_task(remote.events(after=0, timeout=2))
        stream = xml("stream", type="stdout", encoding="base64")
        stream.text = base64.b64encode(b"hello\0").decode()
        await engine.send(stream)
        batch = await first
        assert batch["events"][0]["type"] == "StreamEvent"
        assert batch["events"][0]["data"]["data"] == {"encoding": "base64", "data": "aGVsbG8A"}
        assert await remote.events(after=0, timeout=0) == batch
        empty = await remote.events(after=batch["cursor"], timeout=0.01)
        assert empty["events"] == [] and empty["cursor"] == batch["cursor"]
        await remote.close()
        closed = await remote.events(after=batch["cursor"], timeout=2)
        assert closed["closed"] and closed["events"][-1]["type"] == "ClosedEvent"


async def test_event_history_expiration_is_explicit():
    async with remote_session(server_options={"event_history": 2}) as (_, _, remote, engine):
        for i in range(4):
            await engine.send(xml("notify", name=str(i)))
        # Wait for the fourth event using each preceding cursor as a fence.
        cursor = 0
        try:
            while cursor < 4:
                cursor = (await remote.events(after=cursor, timeout=2))["cursor"]
        except RemoteError as error:
            assert error.code == -32008
            cursor = error.data["latest_cursor"]
        with pytest.raises(RemoteError) as caught:
            await remote.events(after=0, timeout=0)
        assert caught.value.code == -32008
        latest = await remote.events(after=caught.value.data["oldest_cursor"], timeout=0)
        assert [event["data"]["name"] for event in latest["events"]] == ["2", "3"]


async def test_execution_does_not_block_other_clients_or_interrupt():
    async with remote_session(engine_options={"feature_values": {"supports_async": "1"}}) as (server, client, remote, engine):
        run = asyncio.create_task(remote.run(timeout=2))
        running = await engine.next_request()
        async with Client(server.url) as second:
            assert (await second.health())["live_sessions"] == 1
            status = asyncio.create_task(second.session(remote.id).call("status"))
            await engine.respond(await engine.next_request(), status="running", reason="ok")
            assert (await status)["status"] == "running"
            with pytest.raises(RemoteError) as caught:
                await second.session(remote.id).snapshot()
            assert caught.value.code == -32002
            interrupt = asyncio.create_task(second.session(remote.id).interrupt())
            request = await engine.next_request()
            assert request.name == "break"
            await engine.respond(request, success=1)
            assert await interrupt == {"success": True}
            await engine.respond(running, status="break", reason="ok")
            assert (await run)["status"] == "break"


async def test_run_timeout_keeps_later_stop_available():
    async with remote_session() as (_, _, remote, engine):
        run = asyncio.create_task(remote.run(timeout=0.02))
        request = await engine.next_request()
        with pytest.raises(RemoteError) as caught:
            await run
        assert caught.value.code == -32003
        assert (await remote.info())["state"] == "running"
        await engine.respond(request, status="break", reason="ok")
        events = await remote.events(after=0, timeout=2)
        assert events["events"][-1]["type"] == "StoppedEvent"
        assert (await remote.info())["state"] == "break"


async def test_lost_http_connection_does_not_abandon_the_php_session():
    async with remote_session() as (server, _, remote, engine):
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        body = json.dumps({"jsonrpc": "2.0", "id": "lost-client", "method": "session.run",
                           "params": {"session_id": remote.id, "timeout": 2}}).encode()
        writer.write((f"POST /rpc HTTP/1.1\r\nHost: 127.0.0.1:{server.port}\r\n"
                      f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        await writer.drain()
        request = await engine.next_request()
        writer.close()
        await writer.wait_closed()
        await engine.respond(request, status="break", reason="ok")
        assert (await remote.events(timeout=2))["events"][-1]["type"] == "StoppedEvent"
        assert (await remote.info())["state"] == "break"
        assert engine.requests.empty()


async def test_rejected_handshakes_are_visible_without_disabling_the_api():
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        reader, writer = await asyncio.open_connection(server.controller.host, server.controller.port)
        writer.write(frame(xml("response", command="status", transaction_id="1")))
        await writer.drain()
        assert await reader.read() == b""
        writer.close()
        await writer.wait_closed()
        errors = await client.errors()
        assert errors and errors[-1]["type"] == "ProtocolError"
        assert (await client.health())["status"] == "ok"


async def test_binary_assignment_and_structured_engine_errors():
    async with remote_session() as (_, _, remote, engine):
        await pause(remote, engine)
        task = asyncio.create_task(remote.set_value("$binary", b"\xff\0"))
        request = await engine.next_request()
        assert request.name == "property_set"
        assert base64.b64decode(request.data) == b"base64_decode('/wA=')"
        await engine.respond(request, success=1)
        assert await task
        task = asyncio.create_task(remote.evaluate("bad()"))
        error = xml("error", code=206)
        error.append(xml("message"))
        error[0].text = "bad expression"
        await engine.respond(await engine.next_request(), payload=[error])
        with pytest.raises(RemoteError) as caught:
            await task
        assert caught.value.code == -32004
        assert caught.value.data["code"] == 206 and caught.value.data["command"] == "eval"
        assert (await remote.info())["state"] == "break"


async def test_explicit_forget_and_closed_record_retention():
    async with remote_session(server_options={"max_closed_sessions": 1}) as (server, client, remote, engine):
        with pytest.raises(RemoteError) as caught:
            await remote.forget()
        assert caught.value.code == -32002
        await remote.close()
        assert (await remote.events(timeout=2))["closed"]
        other_engine = await Engine.connect(server.controller, idekey="other")
        try:
            other = await client.wait_for_session(idekey="other", timeout=2)
            await other.close()
            assert (await other.events(timeout=2))["closed"]
            with pytest.raises(RemoteError) as caught:
                await remote.info()
            assert caught.value.code == -32001
            assert (await other.forget())["forgotten"]
            assert await client.sessions() == []
        finally:
            await other_engine.close()


@pytest.mark.parametrize("method,params,code", [
    ("unknown", {}, -32601), ("session.__getattribute__", {"session_id": "x"}, -32601),
    ("session.info", {"session_id": "missing"}, -32001),
    ("health", {"unexpected": True}, -32602),
    ("wait_for_session", {"timeout": -1}, -32602),
    ("wait_for_session", {"timeout": None}, -32602),
    ("wait_for_session", {"timeout": 301}, -32602),
    ("wait_for_session", {"idekey": []}, -32602),
])
async def test_invalid_rpc_calls_are_structured(method, params, code):
    async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
        with pytest.raises(RemoteError) as caught:
            await client.call(method, **params)
        assert caught.value.code == code
        assert (await client.health())["status"] == "ok"


@pytest.mark.parametrize("params", [{"variables": "$x"}, {"expressions": [1]}, {"depth": True}])
async def test_invalid_snapshot_params_do_not_reach_the_engine(params):
    async with remote_session() as (_, client, remote, engine):
        with pytest.raises(RemoteError) as caught:
            await client.call("session.snapshot", session_id=remote.id, **params)
        assert caught.value.code == -32602
        assert engine.requests.empty()


@pytest.mark.parametrize("body,status,code", [
    (b"not json", 400, -32700), (b'{"value":NaN}', 400, -32700),
    (b"[]", 200, -32600),
    (b'{"jsonrpc":"2.0","method":"health"}', 200, -32600),
    (b'{"jsonrpc":"2.0","id":true,"method":"health"}', 200, -32600),
    (b'{"jsonrpc":"2.0","id":1,"method":"health","params":[]}', 200, -32600),
])
async def test_http_json_errors(body, status, code):
    async with Server(port=0, xdebug_port=0) as server:
        actual, response = await request(server.url, body=body)
        assert actual == status and response["error"]["code"] == code


async def test_http_body_limits_content_type_and_health():
    async with Server(port=0, xdebug_port=0, max_request_bytes=64) as server:
        assert (await request(server.url, body=b"x" * 65))[0] == 413
        assert (await request(server.url, headers={"Content-Type": "text/plain"}))[0] == 415
        assert (await request(server.url, headers={"Transfer-Encoding": "chunked"}))[0] == 400
        assert (await request(server.url, headers={"Origin": "http://example.test"}))[0] == 403
        assert (await request(server.url, headers={"Host": "example.test"}))[0] == 403
        assert (await request(server.url, headers={"Host": "[invalid"}))[0] == 403
        status, body = await request(server.url, path="/health", method="GET")
        assert status == 200 and body["status"] == "ok"


async def test_token_authentication_and_no_token_in_public_responses():
    async with Server(port=0, xdebug_port=0, token="test-token") as server:
        async with Client(server.url) as unauthorized:
            with pytest.raises(RemoteError) as caught:
                await unauthorized.health()
            assert caught.value.code == -32009
        async with Client(server.url, token="test-token") as client:
            assert "test-token" not in json.dumps(await client.health())
    with pytest.raises(ValueError, match="token"):
        Server(host="0.0.0.0")


async def test_server_shutdown_releases_waiters_and_debugging_connections():
    async with remote_session() as (server, client, remote, engine):
        run = asyncio.create_task(remote.run(timeout=10))
        await engine.next_request()
        waiting = asyncio.create_task(client.wait_for_session(timeout=10))
        await asyncio.sleep(0.01)
        async with asyncio.timeout(3):
            await server.aclose()
            results = await asyncio.gather(run, waiting, return_exceptions=True)
        assert all(isinstance(result, (RemoteError, OSError)) for result in results)
        assert await engine.reader.read() == b""


async def test_real_server_process_and_separate_cli_clients():
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "dbgpilot", "serve", "--port", "0", "--xdebug-port", "0",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    engine = None
    try:
        async with asyncio.timeout(8):
            ready = json.loads(await process.stdout.readline())
            assert ready["event"] == "ready" and ready["pid"] == process.pid
            engine = await Engine.connect(SimpleNamespace(host=ready["xdebug_host"], port=ready["xdebug_port"]))

            async def cli(method, *args):
                child = await asyncio.create_subprocess_exec(
                    sys.executable, "-m", "dbgpilot", "call", method, "--url", ready["url"], *args,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await child.communicate()
                assert child.returncode == 0, stderr.decode()
                return json.loads(stdout)

            assert (await cli("health"))["status"] == "ok"
            first = await cli("wait_for_session")
            id = first["session_id"]
            assert (await cli("session.info", "--session", id))["state"] == "starting"
            assert (await cli("session.close", "--session", id))["closed"]
    finally:
        if process.returncode is None:
            process.terminate()
        async with asyncio.timeout(5):
            _, stderr = await process.communicate()
        if engine is not None:
            await engine.close()
    assert process.returncode == 0, stderr.decode()
