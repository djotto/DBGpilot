"""The separate, short-lived DBGp proxy registration connection."""

import asyncio
from contextlib import suppress
import math
import xml.etree.ElementTree as ET

from .errors import ConnectionClosed, ProtocolError
from .models import ProxyRegistration, proxy_error
from .protocol import NAMESPACE, _quote, read_proxy_response


class ProxyClient:
    """Register or unregister an IDE key using a separate connection per command."""

    def __init__(self, host="127.0.0.1", port=9001, *, timeout=5, max_response_bytes=1024 * 1024):
        if not isinstance(host, str) or not host:
            raise ValueError("Proxy host must be a nonempty string")
        self._port(port)
        if (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("Proxy timeout must be positive and finite")
        if not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise ValueError("Proxy response limit must be positive")
        self.host, self.port, self.timeout = host, port, timeout
        self.max_response_bytes = max_response_bytes

    @staticmethod
    def _port(value):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
            raise ValueError("Proxy and advertised ports must be between 1 and 65535")

    @staticmethod
    def _key(idekey):
        if not isinstance(idekey, str) or not idekey:
            raise ValueError("IDE key must be a nonempty string")

    async def register(self, listen_port, idekey, *, multiple_sessions=True):
        """Advertise a debugger listener port for an IDE key and return the proxy response."""
        self._port(listen_port)
        self._key(idekey)
        if not isinstance(multiple_sessions, bool):
            raise ValueError("multiple_sessions must be a boolean")
        return await self._exchange(
            "proxyinit", idekey, {"p": listen_port, "k": idekey, "m": int(multiple_sessions)},
            listen_port=listen_port, multiple_sessions=multiple_sessions,
        )

    async def unregister(self, idekey):
        """Remove an IDE key's proxy registration and return the proxy response."""
        self._key(idekey)
        return await self._exchange("proxystop", idekey, {"k": idekey})

    async def _exchange(self, command, idekey, arguments, **settings):
        parts = [command]
        for key, value in arguments.items():
            parts.extend(("-" + key, _quote(value)))
        packet = " ".join(parts).encode("utf-8", "surrogateescape") + b"\0"
        writer = None
        try:
            async with asyncio.timeout(self.timeout):
                reader, writer = await asyncio.open_connection(
                    self.host, self.port, limit=self.max_response_bytes + 32,
                )
                writer.write(packet)
                await writer.drain()
                node = await read_proxy_response(reader, self.max_response_bytes)
                if node.tag not in {command, f"{{{NAMESPACE}}}{command}"}:
                    if node.tag in {"proxyerror", f"{{{NAMESPACE}}}proxyerror"}:
                        raise proxy_error(node, command)
                    raise ProtocolError("Proxy response does not match the control command")
                if node.find("{*}error") is not None or node.get("success") == "0":
                    raise proxy_error(node, command)
                if node.get("success") != "1":
                    raise ProtocolError("Proxy response has no valid success flag")
                if node.get("idekey", idekey) != idekey:
                    raise ProtocolError("Proxy returned a different IDE key")
                port = node.get("port")
                if port is not None:
                    try:
                        port = int(port)
                        self._port(port)
                    except ValueError as error:
                        raise ProtocolError("Proxy returned an invalid engine port") from error
                return ProxyRegistration(
                    command, idekey, self.host, self.port, **settings,
                    address=node.get("address"), port=port,
                    attributes=dict(node.attrib), xml=ET.tostring(node, encoding="unicode"),
                )
        except OSError as error:
            if isinstance(error, TimeoutError):
                raise
            raise ConnectionClosed(
                f"Cannot contact DBGp proxy at {self.host}:{self.port}: {error}",
            ) from error
        finally:
            if writer is not None:
                writer.close()
                with suppress(OSError, TimeoutError):
                    async with asyncio.timeout(1):
                        await writer.wait_closed()
