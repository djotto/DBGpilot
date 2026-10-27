import asyncio
from contextlib import asynccontextmanager
import shlex
import xml.etree.ElementTree as ET

import pytest

from dbgpilot import Client, ConnectionClosed, Controller, ProtocolError, ProxyClient, ProxyError, RemoteError, Server
from .helpers import Engine, fake_session, frame, xml


@asynccontextmanager
async def proxy_peer(*, framing="bare", respond=None, keep_open=False):
    requests, writers, handlers = [], set(), set()
    closed = asyncio.Event()

    async def handle(reader, writer):
        writers.add(writer)
        try:
            packet = (await reader.readuntil(b"\0"))[:-1].decode()
            parts = shlex.split(packet)
            command = parts.pop(0)
            arguments = dict(zip((key.removeprefix("-") for key in parts[::2]), parts[1::2]))
            requests.append((command, arguments))
            node = (respond(command, arguments) if respond is not None else
                    ET.Element(command, success="1", idekey=arguments["k"], address="127.0.0.1", port="9123"))
            if node is not None:
                payload = ET.tostring(node, encoding="utf-8") if isinstance(node, ET.Element) else node
                if framing == "framed":
                    payload = frame(payload)
                elif framing == "nul":
                    payload += b"\0"
                for start in range(0, len(payload), 7):
                    writer.write(payload[start:start + 7])
                    await writer.drain()
                    await asyncio.sleep(0)
            if keep_open:
                assert await reader.read() == b""
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            closed.set()
            writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        handlers.add(task)
        task.add_done_callback(handlers.discard)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1], requests, closed
    finally:
        server.close()
        for writer in tuple(writers):
            writer.close()
        await asyncio.gather(*handlers, return_exceptions=True)
        await server.wait_closed()


@pytest.mark.parametrize("framing", ["bare", "nul", "framed"])
async def test_proxy_registration_uses_separate_short_lived_connections(framing):
    async with proxy_peer(framing=framing, keep_open=True) as (port, requests, closed):
        proxy = ProxyClient(port=port)
        registration = await proxy.register(9007, "alice", multiple_sessions=True)
        assert registration.success and registration.listen_port == 9007
        assert registration.address == "127.0.0.1" and registration.port == 9123
        await asyncio.wait_for(closed.wait(), 1)
        assert (await proxy.unregister("alice")).command == "proxystop"
        assert requests == [("proxyinit", {"p": "9007", "k": "alice", "m": "1"}),
                            ("proxystop", {"k": "alice"})]


async def test_proxy_key_escaping_and_single_session_flag():
    async with proxy_peer() as (port, requests, _):
        key = 'a "quoted" key'
        await ProxyClient(port=port).register(9007, key, multiple_sessions=False)
        assert requests[0][1] == {"p": "9007", "k": key, "m": "0"}


async def test_controller_owns_registrations_and_unregisters_on_close():
    async with proxy_peer() as (port, requests, _):
        controller = Controller(port=0)
        result = await controller.register_proxy(port=port, idekey="owned")
        assert result.listen_port == controller.port
        assert controller.proxy_registrations == (result,)
        with pytest.raises(ValueError, match="already owns"):
            await controller.register_proxy(port=port, idekey="owned")
        await controller.aclose()
        assert not controller.proxy_registrations
        assert requests[-1] == ("proxystop", {"k": "owned"})


async def test_server_startup_and_client_proxy_operations():
    async with proxy_peer() as (port, requests, _):
        async with Server(port=0, xdebug_port=0, proxy_host="127.0.0.1", proxy_port=port, idekey="startup") as server:
            async with Client(server.url) as client:
                assert (await client.health())["proxies"][0]["idekey"] == "startup"
                assert len(await client.proxy_registrations()) == 1
                other = await client.register_proxy(port=port, idekey="another", listen_port=9008)
                assert other["listen_port"] == 9008
                assert (await client.unregister_proxy(port=port, idekey="another"))["success"]
                assert len(await client.proxy_registrations()) == 1
        assert requests[-1] == ("proxystop", {"k": "startup"})


def failure(command, arguments):
    node = ET.Element(command, success="0", idekey=arguments["k"])
    error = ET.SubElement(node, "error", id="duplicate-key", extra="kept")
    ET.SubElement(error, "message").text = "already registered"
    return node


async def test_proxy_rejection_preserves_opaque_error_and_http_serialization():
    async with proxy_peer(respond=failure) as (port, requests, _):
        with pytest.raises(ProxyError) as caught:
            await ProxyClient(port=port).register(9007, "duplicate")
        assert caught.value.code == "duplicate-key" and caught.value.command == "proxyinit"
        assert caught.value.attributes["extra"] == "kept"
        assert "already registered" in caught.value.xml
        async with Server(port=0, xdebug_port=0) as server, Client(server.url) as client:
            with pytest.raises(RemoteError) as remote:
                await client.register_proxy(port=port, idekey="duplicate")
            assert remote.value.code == -32011 and remote.value.data["code"] == "duplicate-key"
            assert not await client.proxy_registrations()
        # Failed registrations were not owned, so cleanup must not delete them.
        assert all(command == "proxyinit" for command, _ in requests)


@pytest.mark.parametrize("response", [
    b"<proxystop success='1'/>", b"<proxyinit/>", b"<proxyinit success='2'/>",
    b"<proxyinit success='1' idekey='wrong'/>", b"<proxyinit success='1' port='-1'/>",
    b"<proxyinit success='1' port='bad'/>", b"<proxyinit success='1'",
    b"<!DOCTYPE x><proxyinit success='1'/>",
])
async def test_malformed_proxy_responses_are_rejected(response):
    async with proxy_peer(respond=lambda cmd, args: response) as (port, _, _):
        with pytest.raises(ProtocolError):
            await ProxyClient(port=port).register(9007, "key")


async def test_proxy_timeout_cancellation_and_limits_close_the_control_socket():
    async with proxy_peer(respond=lambda cmd, args: None, keep_open=True) as (port, _, closed):
        with pytest.raises(TimeoutError):
            await ProxyClient(port=port, timeout=0.02).register(9007, "key")
        await asyncio.wait_for(closed.wait(), 1)
    async with proxy_peer(respond=lambda cmd, args: None, keep_open=True) as (port, requests, closed):
        task = asyncio.create_task(ProxyClient(port=port).register(9007, "key"))
        async with asyncio.timeout(1):
            while not requests:
                await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(closed.wait(), 1)
    async with proxy_peer(respond=lambda cmd, args: b"<proxyinit " + b"x" * 100) as (port, _, _):
        with pytest.raises(ProtocolError, match="limit"):
            await ProxyClient(port=port, max_response_bytes=32).register(9007, "key")


async def test_controller_shutdown_is_bounded_when_proxy_stops_responding():
    allow = True

    def respond(command, args):
        return ET.Element(command, success="1", idekey=args["k"]) if allow else None

    async with proxy_peer(respond=respond, keep_open=True) as (port, _, _):
        controller = Controller(port=0)
        await controller.register_proxy(port=port, idekey="key")
        allow = False
        async with asyncio.timeout(2):
            await controller.aclose()
        assert isinstance(await controller.next_error(), TimeoutError)


async def test_proxy_error_before_init_is_reported_and_listener_recovers():
    async with Controller(port=0, features={}) as controller:
        reader, writer = await asyncio.open_connection(controller.host, controller.port)
        node = ET.Element("proxyerror", code="routing.failed")
        ET.SubElement(node, "message").text = "no route"
        writer.write(frame(node))
        await writer.drain()
        assert isinstance(await controller.next_error(timeout=1), ProxyError)
        assert await reader.read() == b""
        writer.close()
        await writer.wait_closed()
        engine = await Engine.connect(controller)
        try:
            assert (await controller.wait_for_session(timeout=1)).info.idekey == "test"
        finally:
            await controller.aclose()
            await engine.close()


@pytest.mark.parametrize("allow_eof,ending", [(False, "clean"), (True, "clean"),
                                              (True, "partial"), (True, "reply")])
async def test_proxy_detach_eof_is_explicit_and_never_hides_truncation(allow_eof, ending):
    async with fake_session(allow_detach_eof=allow_eof, engine_options={"auto_detach": False}) as (_, session, engine):
        detach = asyncio.create_task(session.detach())
        request = await engine.next_request()
        assert request.name == "detach"
        if ending == "reply":
            await engine.respond(request, status="stopped", reason="ok")
        else:
            if ending == "partial":
                engine.writer.write(b"100\0<response")
                await engine.writer.drain()
            await engine.close()
        if ending == "reply" or (ending == "clean" and allow_eof):
            result = await detach
            assert result.status == "stopped"
            assert result.response_received == (ending == "reply")
        else:
            with pytest.raises(ConnectionClosed):
                await detach


async def test_proxy_metadata_enables_detach_eof_compatibility():
    async with fake_session(engine_options={"init_attributes": {"proxied": "192.0.2.1"}}) as (_, session, _):
        assert session.allow_detach_eof
