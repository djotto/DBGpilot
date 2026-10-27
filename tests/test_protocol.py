import asyncio
import base64
from pathlib import Path
import xml.etree.ElementTree as ET

from hypothesis import given, settings, strategies as st
import pytest

from dbgpilot import ConnectionClosed, ProtocolError
from dbgpilot.protocol import content_bytes, encode_command, file_uri, read_packet
from .helpers import frame, xml


@given(st.binary(), st.lists(st.integers(1, 50), min_size=1, max_size=12))
@settings(max_examples=50)
def test_arbitrary_binary_payload_and_socket_fragmentation(data, sizes):
    async def check():
        node = xml("stream", type="stdout", encoding="base64")
        node.text = base64.b64encode(data).decode()
        packet = frame(node)
        reader = asyncio.StreamReader()

        async def feed():
            offset = 0
            for size in sizes:
                reader.feed_data(packet[offset:offset + size])
                offset += size
                await asyncio.sleep(0)
                if offset >= len(packet):
                    break
            reader.feed_data(packet[offset:])
            reader.feed_eof()

        task = asyncio.create_task(feed())
        parsed = await read_packet(reader)
        await task
        assert content_bytes(parsed) == data

    asyncio.run(check())


async def test_utf8_split_inside_multibyte_character_and_coalesced_packets():
    node = xml("notify", name="example")
    node.text = "é£🙂"
    first = frame(node)
    second = frame(xml("response", command="status", transaction_id="1"))
    reader = asyncio.StreamReader()

    async def feed():
        for byte in first + second:
            reader.feed_data(bytes([byte]))
            await asyncio.sleep(0)

    task = asyncio.create_task(feed())
    assert (await read_packet(reader)).text == "é£🙂"
    assert (await read_packet(reader)).get("transaction_id") == "1"
    await task


@pytest.mark.parametrize("data", [b"\0", b"0\0", b"-1\0", b"abc\0", b"9" * 11 + b"\0", b"99999\0"])
async def test_invalid_or_oversize_lengths(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    with pytest.raises(ProtocolError):
        await read_packet(reader, max_size=1024)


@pytest.mark.parametrize("data", [b"", b"20\0abc", b"3\0abc"])
async def test_truncated_frames(data):
    reader = asyncio.StreamReader()
    reader.feed_data(data)
    reader.feed_eof()
    with pytest.raises(ConnectionClosed):
        await read_packet(reader)


@pytest.mark.parametrize("payload", [
    b"<response/>", b"<broken", b'<response xmlns="wrong"/>',
    b'<!DOCTYPE foo [<!ENTITY x "hello">]><foo/>',
])
async def test_invalid_xml_namespace_or_declarations(payload):
    reader = asyncio.StreamReader()
    reader.feed_data(frame(payload))
    with pytest.raises(ProtocolError):
        await read_packet(reader)


async def test_invalid_terminator():
    reader = asyncio.StreamReader()
    reader.feed_data(b"4\0<a/>x")
    with pytest.raises(ProtocolError, match="terminator"):
        await read_packet(reader)


@given(st.binary())
def test_command_data_is_base64_without_line_wrapping(data):
    packet = encode_command("eval", 123, {"d": 2}, data)
    header, body = packet.split(b" -- ", 1)
    assert header == b"eval -i 123 -d 2"
    assert base64.b64decode(body[:-1], validate=True) == data
    assert packet.count(b"\0") == 1
    assert b"\n" not in body


def test_property_name_escaping_and_unicode():
    command = encode_command("property_get", 1, {"n": '$a["a\\b\0 é"]', "d": 0})
    assert command == 'property_get -i 1 -n "$a[\\"a\\\\b\\0 é\\"]" -d 0\0'.encode()
    assert command.count(b"\0") == 1


@pytest.mark.parametrize("name,args", [("bad name", {}), ("status", {"i": "9"}), ("status", {"long": 3})])
def test_reject_command_injection(name, args):
    with pytest.raises(ValueError):
        encode_command(name, 1, args)


def test_paths_and_virtual_source_uris():
    assert "%20" in file_uri(Path("a b.php"))
    assert file_uri("dbgp://3") == "dbgp://3"
    assert file_uri("file:///app/a.php") == "file:///app/a.php"


def test_invalid_base64():
    node = xml("property", encoding="base64")
    node.text = "not valid!"
    with pytest.raises(ProtocolError):
        content_bytes(node)


async def test_command_timeout_also_bounds_socket_backpressure():
    from dbgpilot import Session

    class SlowWriter:
        def write(self, packet):
            pass

        async def drain(self):
            await asyncio.sleep(10)

        def close(self):
            pass

        async def wait_closed(self):
            pass

    session = Session(asyncio.StreamReader(), SlowWriter())
    try:
        async with asyncio.timeout(1):
            with pytest.raises(TimeoutError):
                await session.command("status", timeout=0.01)
    finally:
        await session.aclose(detach=False)
