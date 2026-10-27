"""A scripted debugger engine on a real TCP socket."""

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
import shlex
import xml.etree.ElementTree as ET

from dbgpilot import Controller
from dbgpilot.protocol import NAMESPACE


def xml(kind, **attrs):
    return ET.Element(f"{{{NAMESPACE}}}{kind}", {key: str(value) for key, value in attrs.items()})


def frame(node):
    payload = ET.tostring(node, encoding="utf-8") if isinstance(node, ET.Element) else node
    return str(len(payload)).encode() + b"\0" + payload + b"\0"


@dataclass
class Request:
    name: str
    id: str
    arguments: dict
    data: str | None


class Engine:
    def __init__(self, reader, writer, *, feature_values=None, auto_detach=True,
                 feature_set_results=None, feature_errors=None):
        self.reader, self.writer = reader, writer
        self.requests = asyncio.Queue()
        self.features = {
            "supports_async": "0", "encoding": "UTF-8", "supports_postmortem": "0",
            "breakpoint_types": "line conditional call return exception",
            "language_name": "PHP", "language_version": "8.4", "language_supports_threads": "0",
            **(feature_values or {}),
        }
        self.auto_detach = auto_detach
        self.feature_set_results = feature_set_results or {}
        self.feature_errors = feature_errors or {}
        self.task = asyncio.create_task(self._read())

    @classmethod
    async def connect(cls, controller, *, idekey="test", init_attributes=None, init_children=(), **options):
        reader, writer = await asyncio.open_connection(controller.host, controller.port)
        engine = cls(reader, writer, **options)
        init = xml("init", **{
            "language": "PHP", "protocol_version": "1.0", "idekey": idekey,
            "appid": "123", "fileuri": "file:///app/index.php", **(init_attributes or {}),
        })
        init.extend(init_children)
        await engine.send(init)
        return engine

    async def _read(self):
        try:
            while True:
                packet = (await self.reader.readuntil(b"\0"))[:-1].decode("utf-8", "surrogateescape")
                parts = shlex.split(packet)
                data = None
                if "--" in parts:
                    index = parts.index("--")
                    data = parts[index + 1] if index + 1 < len(parts) else ""
                    parts = parts[:index]
                arguments = {parts[i][1:]: parts[i + 1] for i in range(1, len(parts), 2)}
                request = Request(parts[0], arguments.pop("i"), arguments, data)
                if request.name == "feature_get":
                    if request.arguments["n"] in self.feature_errors:
                        await self.respond(request, payload=[xml("error", code=self.feature_errors[request.arguments["n"]])])
                        continue
                    value = self.features.get(request.arguments["n"], "1")
                    node = xml("response", command=request.name, transaction_id=request.id,
                               supported="0" if value is None else "1")
                    node.text = value or ""
                    await self.send(node)
                elif request.name == "feature_set":
                    name = request.arguments["n"]
                    success = self.feature_set_results.get(name, "1")
                    if isinstance(success, int):
                        await self.respond(request, payload=[xml("error", code=success)])
                        continue
                    if success == "1":
                        self.features[name] = request.arguments["v"]
                    await self.respond(request, success=success)
                elif request.name == "detach" and self.auto_detach:
                    await self.respond(request, status="stopped", reason="ok")
                    self.writer.close()
                    return
                else:
                    await self.requests.put(request)
        except (asyncio.IncompleteReadError, ConnectionError):
            pass

    async def send(self, node):
        self.writer.write(frame(node))
        await self.writer.drain()

    async def respond(self, request, *, payload=(), command=None, transaction_id=None, **attrs):
        node = xml("response", command=command or request.name,
                   transaction_id=transaction_id or request.id, **attrs)
        node.extend(payload)
        await self.send(node)

    async def next_request(self):
        async with asyncio.timeout(2):
            return await self.requests.get()

    async def close(self):
        self.writer.close()
        self.task.cancel()
        with suppress(asyncio.CancelledError, ConnectionError):
            await self.task
            await self.writer.wait_closed()


@asynccontextmanager
async def fake_session(*, engine_options=None, **options):
    async with Controller(port=0, features={}, **options) as controller:
        engine = await Engine.connect(controller, **(engine_options or {}))
        session = await controller.wait_for_session(timeout=2)
        try:
            yield controller, session, engine
        finally:
            await session.aclose()
            await engine.close()
