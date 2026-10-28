"""Byte-oriented DBGp framing and command construction."""

import asyncio
import base64
from collections.abc import Mapping
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .errors import ConnectionClosed, ProtocolError

NAMESPACE = "urn:debugger_protocol_v1"
MAX_PACKET_SIZE = 16 * 1024 * 1024


def local_name(element: ET.Element) -> str:
    """Return an XML element's tag without its namespace prefix."""
    return element.tag.rsplit("}", 1)[-1]


async def _read_payload(reader, max_size, initial=b""):
    header = bytearray(initial)
    try:
        while True:
            char = await reader.readexactly(1)
            if char == b"\0":
                break
            if not char.isdigit() or len(header) >= 10:
                raise ProtocolError("Invalid DBGp packet length")
            header.extend(char)
        if not header or not 0 < int(header) <= max_size:
            raise ProtocolError("DBGp packet length is empty, zero, or exceeds the limit")
        body = await reader.readexactly(int(header))
        if await reader.readexactly(1) != b"\0":
            raise ProtocolError("Missing DBGp packet terminator")
    except asyncio.IncompleteReadError as error:
        raise ConnectionClosed(
            "Peer disconnected while reading a DBGp packet",
            clean_eof=not header and not error.partial,
        ) from error
    return body


def parse_xml(body, *, require_namespace=True, allow_proxy_error=False):
    """Parse DBGp XML, rejecting NUL bytes, DTDs, entities, and invalid namespaces."""
    if b"\0" in body:
        raise ProtocolError("DBGp XML requires an ASCII-compatible encoding without NUL bytes")
    if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
        raise ProtocolError("DTD and entity declarations are not supported")
    try:
        element = ET.fromstring(body)
    except ET.ParseError as error:
        raise ProtocolError(f"Invalid DBGp XML: {error}") from error
    if (require_namespace and not element.tag.startswith(f"{{{NAMESPACE}}}")
            and not (allow_proxy_error and element.tag == "proxyerror")):
        raise ProtocolError("Missing or invalid DBGp namespace")
    return element


async def read_packet(reader: asyncio.StreamReader, max_size: int = MAX_PACKET_SIZE, *,
                      xdebug_bytes=False, with_encoding=False) -> ET.Element:
    """Read a bounded DBGp packet and parse its XML.

    Optionally decode Xdebug's Latin-1 byte container. With with_encoding=True,
    return the element and declared encoding as a pair.
    """
    body = await _read_payload(reader, max_size)
    element = parse_xml(body, allow_proxy_error=True)
    declaration = re.match(br"\s*<\?xml\b[^?]*encoding\s*=\s*['\"]([^'\"]+)['\"]", body)
    encoding = declaration.group(1).decode("ascii").casefold() if declaration else "utf-8"
    if xdebug_bytes and encoding in {"iso-8859-1", "iso8859-1", "latin1", "latin-1"}:
        decode_xdebug_xml(element)
    return (element, encoding) if with_encoding else element


async def read_proxy_response(reader, max_size=1024 * 1024):
    """Proxy controls may return bare XML or an ordinary length-framed packet."""
    try:
        first = await reader.readexactly(1)
        if first.isdigit():
            return parse_xml(await _read_payload(reader, max_size, first), require_namespace=False)
        body = bytearray(first)
        while True:
            if len(body) > max_size:
                raise ProtocolError("Proxy response exceeds the packet limit")
            terminated = b"\0" in body
            payload = bytes(body).split(b"\0", 1)[0]
            if terminated and bytes(body).split(b"\0", 1)[1].strip():
                raise ProtocolError("Unexpected data after proxy response")
            # Reject declarations before trying an incomplete document too.
            if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
                raise ProtocolError("DTD and entity declarations are not supported")
            try:
                ET.fromstring(payload)
            except ET.ParseError:
                if terminated:
                    return parse_xml(payload, require_namespace=False)
            else:
                return parse_xml(payload, require_namespace=False)
            chunk = await reader.read(min(4096, max_size + 1 - len(body)))
            if not chunk:
                return parse_xml(payload, require_namespace=False)
            body.extend(chunk)
    except asyncio.IncompleteReadError as error:
        raise ConnectionClosed("Proxy disconnected without a response") from error


def decode_xdebug_xml(element: ET.Element):
    """Undo Xdebug's byte-container XML encoding without transcoding PHP data.

    Xdebug labels raw application bytes as Latin-1. Decode UTF-8 application
    names where valid and preserve other bytes through surrogateescape.
    """
    def decode(text):
        return text.encode("latin-1").decode("utf-8", "surrogateescape")

    for node in element.iter():
        node.attrib.update((key, decode(value)) for key, value in node.attrib.items())
        if node.text is not None:
            node.text = decode(node.text)
        if node.tail is not None:
            node.tail = decode(node.tail)


def _quote(value: object) -> str:
    if isinstance(value, bool):
        value = int(value)
    text = str(value)
    if not text or any(c.isspace() or c in '\\"\0' for c in text):
        text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\0", "\\0")
        return f'"{text}"'
    return text


def encode_command(
    name: str, transaction_id: int, arguments: Mapping[str, object] | None = None,
    data: str | bytes | None = None,
) -> bytes:
    """Encode a validated command with quoted arguments and optional base64 data.

    Text data uses UTF-8 with surrogateescape. The returned bytes include the
    transaction ID and terminating NUL byte.
    """
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", name):
        raise ValueError("Invalid command name")
    if transaction_id < 1:
        raise ValueError("Transaction IDs must be positive")
    parts = [name, "-i", str(transaction_id)]
    for key, value in (arguments or {}).items():
        if key == "i" or not re.fullmatch(r"[A-Za-z]", key):
            raise ValueError(f"Invalid or reserved argument: {key!r}")
        if value is not None:
            parts.extend((f"-{key}", _quote(value)))
    if data is not None:
        if isinstance(data, str):
            data = data.encode("utf-8", "surrogateescape")
        parts.extend(("--", base64.b64encode(data).decode("ascii")))
    return " ".join(parts).encode("utf-8", "surrogateescape") + b"\0"


def file_uri(file: str | Path) -> str:
    """Preserve explicit file: or dbgp: URIs, otherwise build an absolute file URI."""
    text = str(file)
    if text.startswith(("file:", "dbgp:")):
        return text
    return Path(file).absolute().as_uri()


def content_bytes(element: ET.Element, *, mixed=False) -> bytes:
    """Decode element body bytes, validating any declared base64 encoding.

    With mixed=True, include child tail text while excluding child content.
    Plain text uses UTF-8 with surrogateescape to preserve application bytes.
    """
    text = element.text or ""
    if mixed:
        # Notification body text belongs to the parent, including tails after
        # vendor metadata children. Child message text is not body data.
        text += "".join(child.tail or "" for child in element)
    encoding = element.get("encoding", "none")
    if encoding == "base64":
        try:
            return base64.b64decode("".join(text.split()), validate=True)
        except (ValueError, UnicodeError) as error:
            raise ProtocolError("Invalid base64 data") from error
    if encoding != "none":
        raise ProtocolError(f"Unsupported data encoding: {encoding}")
    return text.encode("utf-8", "surrogateescape")
