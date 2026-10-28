"""Structured results, with faithful bytes and JSON-safe snapshots."""

import base64
from dataclasses import dataclass, field
import math
import xml.etree.ElementTree as ET

from .errors import ProtocolError, ProxyError
from .protocol import content_bytes


def _text(node: ET.Element, name: str, default: str = "") -> str:
    attribute = node.get(name)
    if attribute is not None:
        return attribute
    child = node.find(f"{{*}}{name}")
    return default if child is None else content_bytes(child).decode("utf-8", "surrogateescape")


def _integer(node: ET.Element, name: str, default=None):
    text = node.get(name)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError as error:
        raise ProtocolError(f"Invalid {name}: {text!r}") from error


def _json_value(value):
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


@dataclass(frozen=True)
class Property:
    name: str
    fullname: str
    type: str
    value: object = None
    classname: str | None = None
    children: tuple["Property", ...] = ()
    total_children: int = 0
    has_children: bool = False
    size: int | None = None
    page: int = 0
    page_size: int | None = None
    raw_value: bytes | None = None
    key: str | None = None
    address: str | None = None
    facets: tuple[str, ...] = ()
    constant: bool | None = None
    common_type: str | None = None

    @property
    def value_truncated(self) -> bool:
        return (
            self.raw_value is not None and self.size is not None
            and self.size > len(self.raw_value)
        )

    @property
    def children_truncated(self) -> bool:
        return self.has_children and (self.page != 0 or self.total_children > len(self.children))

    def to_dict(self) -> dict:
        return {
            "name": self.name, "fullname": self.fullname, "type": self.type,
            "classname": self.classname, "value": _json_value(self.value),
            "children": [child.to_dict() for child in self.children],
            "total_children": self.total_children, "has_children": self.has_children,
            "size": self.size, "page": self.page, "page_size": self.page_size,
            "value_truncated": self.value_truncated,
            "children_truncated": self.children_truncated,
            "key": self.key, "address": self.address,
            "facets": list(self.facets), "constant": self.constant,
            "common_type": self.common_type,
        }


def parse_property(node: ET.Element, type_map=None) -> Property:
    for attribute in ("numchildren", "size", "page", "pagesize"):
        number = _integer(node, attribute)
        if number is not None and number < 0:
            raise ProtocolError(f"Property {attribute} must be nonnegative")
    kind = node.get("type", "unknown")
    mapping = (type_map or {}).get(kind)
    common = mapping.common_type if mapping is not None else kind
    children = tuple(parse_property(child, type_map) for child in node.findall("{*}property"))
    total = _integer(node, "numchildren", len(children))
    has_children = node.get("children") == "1" or total > 0
    value_node = node.find("{*}value")
    raw = None
    value = None
    if not has_children and common not in {"array", "object", "null", "uninitialized"}:
        raw = content_bytes(value_node if value_node is not None else node)
        try:
            if common in {"int", "integer"}:
                value = int(raw)
            elif common in {"bool", "boolean"}:
                if raw not in {b"0", b"1", b"false", b"true"}:
                    raise ValueError("Invalid boolean")
                value = raw in {b"1", b"true"}
            elif common in {"float", "double"}:
                value = float(raw)
            else:
                try:
                    value = raw.decode("utf-8")
                except UnicodeDecodeError:
                    value = raw
        except ValueError as error:
            raise ProtocolError(f"Invalid {kind} property value") from error
    return Property(
        name=_text(node, "name"), fullname=_text(node, "fullname"), type=kind,
        classname=_text(node, "classname") or None, value=value, raw_value=raw,
        children=children, total_children=total, has_children=has_children,
        size=_integer(node, "size"), page=_integer(node, "page", 0),
        page_size=_integer(node, "pagesize"), key=node.get("key"), address=node.get("address"),
        facets=tuple(node.get("facet", "").split()),
        constant=None if node.get("constant") is None else node.get("constant") == "1",
        common_type=mapping.common_type if mapping is not None else None,
    )


@dataclass(frozen=True)
class SessionInfo:
    id: str
    appid: str
    idekey: str
    language: str
    protocol_version: str
    file: str
    cookie: str | None = None
    thread: str | None = None
    parent: str | None = None
    proxied: str | None = None
    engine: str | None = None
    engine_version: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    xml: str = ""
    local_file: str | None = None
    path_mapping_error: str | None = None


@dataclass(frozen=True)
class TypeMapping:
    language_type: str
    common_type: str
    schema_type: str | None = None
    xml: str = ""


@dataclass(frozen=True)
class PropertyValue:
    data: bytes
    size: int
    encoding: str = "none"
    page: int | None = None
    key: str | None = None
    address: str | None = None

    @property
    def truncated(self):
        return len(self.data) < self.size

    def to_dict(self):
        return {**vars(self), "data": _json_value(self.data), "truncated": self.truncated}


@dataclass(frozen=True)
class Feature:
    supported: bool
    value: str

    @property
    def enabled(self) -> bool:
        return self.supported and self.value == "1"


@dataclass(frozen=True)
class Frame:
    level: int
    file: str
    line: int
    function: str
    type: str = "file"
    cmdbegin: str | None = None
    cmdend: str | None = None
    inputs: tuple["Frame", ...] = ()
    local_file: str | None = None
    path_mapping_error: str | None = None

    def to_dict(self) -> dict:
        return {**vars(self), "inputs": [frame.to_dict() for frame in self.inputs]}


def parse_frame(node: ET.Element) -> Frame:
    level, line = _integer(node, "level"), _integer(node, "lineno")
    if level is None or line is None:
        raise ProtocolError("Invalid stack frame")
    return Frame(
        level, node.get("filename", ""), line, node.get("where", ""),
        node.get("type", "file"), node.get("cmdbegin"), node.get("cmdend"),
        tuple(
            parse_frame(child) for child in node
            if child.tag.rsplit("}", 1)[-1] in {"input", "stack"}
        ),
    )


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason: str
    file: str | None = None
    line: int | None = None
    exception: str | None = None
    message: str | None = None
    breakpoint_id: str | None = None
    breakpoint: "Breakpoint | None" = None
    response_received: bool = True
    local_file: str | None = None
    path_mapping_error: str | None = None

    @property
    def paused(self) -> bool:
        return self.status == "break"

    def to_dict(self) -> dict:
        return {**vars(self), "breakpoint": self.breakpoint.to_dict() if self.breakpoint else None}


@dataclass(frozen=True)
class InteractiveResult:
    status: str
    more: bool
    prompt: str
    reason: str = "ok"

    def to_dict(self):
        return vars(self).copy()


def parse_interaction(node):
    if node.get("more") not in {"0", "1"} or node.get("prompt") is None:
        raise ProtocolError("interact response requires more and prompt attributes")
    if node.get("status") is None:
        raise ProtocolError("interact response requires an execution state")
    return InteractiveResult(node.get("status"), node.get("more") == "1",
                             node.get("prompt"), node.get("reason", "ok"))


@dataclass(frozen=True)
class ProxyRegistration:
    command: str
    idekey: str
    proxy_host: str
    proxy_port: int
    listen_port: int | None = None
    multiple_sessions: bool | None = None
    address: str | None = None
    port: int | None = None
    success: bool = True
    attributes: dict[str, str] = field(default_factory=dict)
    xml: str = ""


def proxy_error(node, command=None):
    error = node.find("{*}error")
    error = error if error is not None else node
    message = error.find("{*}message")
    text = "".join(message.itertext()) if message is not None else (error.text or "").strip()
    return ProxyError(
        text or f"{command or 'DBGp proxy'} failed", code=error.get("code", error.get("id")),
        command=command or node.get("command"), attributes=error.attrib,
        xml=ET.tostring(node, encoding="unicode"),
    )


def execution_result(node: ET.Element) -> ExecutionResult:
    message = node.find("{*}message")
    bp = node.find("{*}breakpoint")
    return ExecutionResult(
        status=node.get("status", "unknown"), reason=node.get("reason", "ok"),
        file=message.get("filename") if message is not None else None,
        line=_integer(message, "lineno") if message is not None else None,
        exception=message.get("exception") if message is not None else None,
        message=message.text if message is not None else None,
        breakpoint_id=bp.get("id") if bp is not None else None,
        breakpoint=parse_breakpoint(bp) if bp is not None else None,
        response_received=node.get("dbgpilot_eof") != "1",
    )


@dataclass(frozen=True)
class Breakpoint:
    id: str
    type: str
    file: str | None = None
    line: int | None = None
    state: str = "enabled"
    resolved: str | None = None
    hit_count: int = 0
    hit_value: int = 0
    hit_condition: str | None = None
    expression: str | None = None
    function: str | None = None
    exception: str | None = None
    temporary: bool | None = None
    local_file: str | None = None
    path_mapping_error: str | None = None

    def to_dict(self):
        return vars(self).copy()


def parse_breakpoint(node: ET.Element) -> Breakpoint:
    if not node.get("id") or not node.get("state", "enabled"):
        raise ProtocolError("Breakpoint requires an ID and nonempty state")
    expression = node.find("{*}expression")
    return Breakpoint(
        id=node.get("id", ""), type=node.get("type", "line"),
        file=node.get("filename"), line=_integer(node, "lineno"),
        state=node.get("state", "enabled"), resolved=node.get("resolved"),
        hit_count=_integer(node, "hit_count", 0), hit_value=_integer(node, "hit_value", 0),
        hit_condition=node.get("hit_condition"),
        expression=content_bytes(expression).decode("utf-8", "surrogateescape")
        if expression is not None else node.get("expression"),
        function=node.get("function"), exception=node.get("exception"),
        temporary=None if node.get("temporary") is None else node.get("temporary") == "1",
    )


@dataclass(frozen=True)
class Spawnpoint:
    id: str
    file: str | None = None
    line: int | None = None
    state: str = "enabled"
    type: str = "spawn"
    attributes: dict[str, str] = field(default_factory=dict)
    xml: str = ""
    local_file: str | None = None
    path_mapping_error: str | None = None

    def to_dict(self):
        return {**vars(self), "attributes": self.attributes.copy()}


def parse_spawnpoint(node: ET.Element) -> Spawnpoint:
    if not node.get("id") or node.get("state") not in {"enabled", "disabled"}:
        raise ProtocolError("Spawnpoint requires an ID and valid state")
    if node.get("type", "spawn") != "spawn":
        raise ProtocolError("Invalid spawnpoint type")
    return Spawnpoint(
        node.get("id"), node.get("filename"), _integer(node, "lineno"),
        node.get("state"), attributes=dict(node.attrib),
        xml=ET.tostring(node, encoding="unicode"),
    )


@dataclass(frozen=True)
class StreamEvent:
    stream: str
    data: bytes


@dataclass(frozen=True)
class NotificationEvent:
    name: str
    xml: str
    data: bytes
    breakpoint: Breakpoint | None = None
    message: "NotificationMessage | None" = None


@dataclass(frozen=True)
class NotificationMessage:
    text: str
    file: str | None = None
    line: int | None = None
    type: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    local_file: str | None = None
    path_mapping_error: str | None = None


def parse_notification(node: ET.Element) -> NotificationEvent:
    bp = node.find("{*}breakpoint")
    message = node.find("{*}message")
    return NotificationEvent(
        node.get("name", ""), ET.tostring(node, encoding="unicode"),
        content_bytes(node, mixed=True),
        parse_breakpoint(bp) if bp is not None else None,
        NotificationMessage(
            "".join(message.itertext()), message.get("filename"),
            _integer(message, "lineno"), message.get("type"), dict(message.attrib),
        ) if message is not None else None,
    )


@dataclass(frozen=True)
class StoppedEvent:
    result: ExecutionResult


@dataclass(frozen=True)
class ClosedEvent:
    error: Exception


@dataclass(frozen=True)
class ProxyErrorEvent:
    error: ProxyError


@dataclass(frozen=True)
class InteractiveEvent:
    result: InteractiveResult


@dataclass(frozen=True)
class Snapshot:
    session_id: str
    execution: ExecutionResult
    frames: tuple[Frame, ...]
    variables: dict[str, Property] = field(default_factory=dict)
    expressions: dict[str, Property | None] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id, "execution": self.execution.to_dict(),
            "frames": [frame.to_dict() for frame in self.frames],
            "variables": {name: value.to_dict() for name, value in self.variables.items()},
            "expressions": {
                code: value.to_dict() if value is not None else None
                for code, value in self.expressions.items()
            },
        }
