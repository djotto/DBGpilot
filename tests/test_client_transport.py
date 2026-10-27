"""Async HTTP response framing and error correlation at the client boundary."""

import asyncio
from contextlib import asynccontextmanager
import json

import pytest

from dbgpilot import Client, ProtocolError, RemoteError


@asynccontextmanager
async def endpoint(response):
    writers, tasks = set(), set()

    async def handle(reader, writer):
        writers.add(writer)
        try:
            headers = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            length = next(int(line.split(":", 1)[1]) for line in headers if line.lower().startswith("content-length:"))
            request = json.loads(await reader.readexactly(length))
            payload = response(request)
            # Deliberately split status/header/body boundaries across reads.
            for start in range(0, len(payload), 7):
                writer.write(payload[start:start + 7])
                await writer.drain()
                await asyncio.sleep(0)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writers.discard(writer)
            writer.close()
            await writer.wait_closed()

    def connected(reader, writer):
        task = asyncio.create_task(handle(reader, writer))
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    server = await asyncio.start_server(connected, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()
        for writer in tuple(writers):
            writer.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await server.wait_closed()


def message(request, **fields):
    body = json.dumps({"jsonrpc": "2.0", "id": request["id"], **fields}, ensure_ascii=False).encode()
    return f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body


async def test_fragmented_response_preserves_unicode_and_binary_envelope():
    expected = {"text": "café", "binary": {"encoding": "base64", "data": "/wA="}}
    async with endpoint(lambda req: message(req, result=expected)) as url, Client(url) as client:
        assert await client.health() == expected


@pytest.mark.parametrize("response", [
    b"HTTP/1.1 200 OK\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Length: 2\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\n???",
    b"HTTP/1.1 nope\r\nContent-Length: 2\r\n\r\n{}",
])
async def test_malformed_or_truncated_http_responses(response):
    async with endpoint(lambda req: response) as url, Client(url) as client:
        with pytest.raises(ProtocolError):
            await client.health()


async def test_response_limit_is_checked_before_reading_a_large_body():
    async with endpoint(lambda req: b"HTTP/1.1 200 OK\r\nContent-Length: 1000000\r\n\r\n") as url:
        async with Client(url, max_response_bytes=16) as client:
            with pytest.raises(ProtocolError, match="limit"):
                await client.health()


async def test_wrong_response_id_and_invalid_errors_are_rejected():
    for respond in (lambda req: message({"id": "wrong"}, result=True),
                    lambda req: message(req, error={"code": "bad", "message": 1})):
        async with endpoint(respond) as url, Client(url) as client:
            with pytest.raises(ProtocolError):
                await client.health()


async def test_valid_remote_error_retains_code_and_data():
    async with endpoint(lambda req: message(req, error={"code": -32010, "message": "cancelled", "data": {"type": "RequestCancelled"}})) as url:
        async with Client(url) as client:
            with pytest.raises(RemoteError) as caught:
                await client.health()
            assert caught.value.code == -32010 and caught.value.data["type"] == "RequestCancelled"
