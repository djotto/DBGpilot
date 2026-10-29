"""One independently controlled DBGp connection."""

import asyncio
import base64
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
import uuid
import math
import xml.etree.ElementTree as ET

from ._arguments import keyword_aliases
from .errors import (
    CommandError, ConnectionClosed, DBGpilotError, ExecutionFinished,
    ProtocolError, SessionStateError,
)
from .models import (
    Breakpoint, ClosedEvent, ExecutionResult, Feature, Frame, InteractiveEvent,
    InteractiveResult, NotificationEvent, PropertyValue, ProxyErrorEvent, Spawnpoint,
    SessionInfo, Snapshot, StoppedEvent, StreamEvent, TypeMapping, execution_result,
    parse_breakpoint, parse_frame, parse_interaction, parse_notification, parse_property,
    parse_spawnpoint, proxy_error,
)
from .protocol import (
    MAX_PACKET_SIZE, content_bytes, decode_xdebug_xml, encode_command,
    local_name, read_packet,
)
from .paths import PathMapper
from .queues import RetainedQueue

_DEFAULT = object()
_EVALUATIONS = {"eval", "expr", "exec"}
_CONTINUATIONS = {
    "run", "step_into", "step_over", "step_out", "stop", "detach", "break", "interact",
} | _EVALUATIONS
_SPAWNPOINT_COMMANDS = {"spawnpoint_" + name for name in ("set", "get", "update", "remove", "list")}
_STATES = {"starting", "running", "break", "stopping", "stopped", "interactive"}
_COMMANDS = (
    "status feature_get feature_set run step_into step_over step_out stop detach "
    "breakpoint_set breakpoint_get breakpoint_update breakpoint_remove breakpoint_list "
    "stack_depth stack_get context_names context_get typemap_get property_get property_set "
    "property_value source stdout stderr stdin break eval expr exec interact "
    "spawnpoint_set spawnpoint_get spawnpoint_update spawnpoint_remove spawnpoint_list"
).split()
_FEATURES = (
    "language_supports_threads language_name language_version encoding protocol_version "
    "supports_async data_encoding breakpoint_languages breakpoint_types multiple_sessions "
    "max_children max_data max_depth breakpoint_details extended_properties notify_ok "
    "resolved_breakpoints supported_encodings supports_postmortem show_hidden"
).split()


async def wait_queue(queue, closed: asyncio.Event, timeout: float | None, error):
    """Wait for availability, then consume synchronously in the caller's task."""
    async with asyncio.timeout(timeout):
        while True:
            if not queue.empty():
                return queue.get_nowait()
            if closed.is_set():
                raise error
            ready = asyncio.create_task(queue.available.wait())
            close = asyncio.create_task(closed.wait())
            try:
                await asyncio.wait((ready, close), return_when=asyncio.FIRST_COMPLETED)
            finally:
                ready.cancel()
                close.cancel()
                await asyncio.gather(ready, close, return_exceptions=True)


class Session:
    """A live session. Inspection never closes or resumes the PHP request."""

    def __init__(
        self, reader, writer, *, command_timeout=5.0, execution_timeout=None,
        max_packet_size=MAX_PACKET_SIZE, event_queue_size=1024,
        eval_depth_supported=None, allow_detach_eof=False,
        path_mappings=(), max_pending_commands=1024,
    ):
        if type(max_pending_commands) is not int or max_pending_commands < 1:
            raise ValueError("max_pending_commands must be a positive integer")
        self._reader = reader
        self._writer = writer
        self.command_timeout = command_timeout
        self.execution_timeout = execution_timeout
        self.max_packet_size = max_packet_size
        self.max_pending_commands = max_pending_commands
        self.state = "starting"
        self.supports_async = False
        self.last_result = ExecutionResult("starting", "ok")
        self._pending = {}
        self._abandoned = {}
        self._transaction = 0
        self._write_lock = asyncio.Lock()
        self._events = RetainedQueue(maxsize=event_queue_size)
        self._closed = asyncio.Event()
        self._error = ConnectionClosed("Session closed")
        self._reader_task = None
        self._execution_pending = False
        self._execution_owner = None
        self._executions = {}
        self._eof_commands = {}
        self._capabilities = {}
        self._feature_requests = {}
        self._type_map = {}
        self._breakpoints = {}
        self._breakpoint_requests = {}
        self._spawnpoints = {}
        self._spawnpoint_requests = {}
        self.supports_eval_depth = eval_depth_supported
        self._xdebug_bytes = False
        self.stdin_redirected = False
        self.stdin_waiting = False
        self.last_interaction = None
        self._stdin_lock = asyncio.Lock()
        self._stdin_modes = {}
        self._stdin_mode_transaction = 0
        self._interaction_modes = {}
        self.allow_detach_eof = allow_detach_eof
        self.path_mapper = (
            path_mappings if isinstance(path_mappings, PathMapper) else PathMapper(path_mappings)
        )

    @classmethod
    async def connect(cls, reader, writer, *, handshake_timeout=5.0, features=None, **options):
        """Initialize a session on an open DBGp stream and negotiate its capabilities.

        Read the initialization packet within handshake_timeout, set requested
        features, and start response dispatch. Close the session if setup fails.
        """
        session = cls(reader, writer, **options)
        try:
            async with asyncio.timeout(handshake_timeout):
                init, xml_encoding = await read_packet(
                    reader, session.max_packet_size, with_encoding=True,
                )
            if local_name(init) == "proxyerror":
                raise proxy_error(init)
            if local_name(init) != "init" or not init.get("language"):
                raise ProtocolError("Expected a DBGp initialization packet")
            version = init.get("protocol_version")
            if version not in {"1", "1.0"}:
                raise ProtocolError(f"Unsupported DBGp protocol version: {version!r}")
            engine = init.find("{*}engine")
            session._xdebug_bytes = (
                engine is not None and (engine.text or "").casefold() == "xdebug"
            )
            if session._xdebug_bytes and xml_encoding in {
                "iso-8859-1", "iso8859-1", "latin1", "latin-1",
            }:
                decode_xdebug_xml(init)
            session.info = session._located(SessionInfo(
                uuid.uuid4().hex, init.get("appid", ""), init.get("idekey", ""),
                init.get("language"), version, init.get("fileuri", ""),
                cookie=init.get("session"), thread=init.get("thread"),
                parent=init.get("parent"), proxied=init.get("proxied"),
                engine=engine.text if engine is not None else None,
                engine_version=engine.get("version") if engine is not None else None,
                attributes=dict(init.attrib), xml=ET.tostring(init, encoding="unicode"),
            ))
            if session.info.proxied:
                session.allow_detach_eof = True
            if session.supports_eval_depth is None:
                session.supports_eval_depth = session.info.language.casefold() != "php"
            session._reader_task = asyncio.create_task(
                session._read_loop(), name=f"dbgpilot-reader-{session.info.id}",
            )
            await session.refresh_capabilities()
            encoding = session._capabilities["encoding"]
            xdebug_latin1 = (
                session._xdebug_bytes
                and encoding.value.casefold() in {"iso-8859-1", "iso8859-1", "latin1", "latin-1"}
            )
            if (
                encoding.supported and encoding.value.casefold().replace("-", "") != "utf8"
                and not xdebug_latin1
            ):
                if not await session.feature_set("encoding", "UTF-8"):
                    raise ProtocolError("The engine must support UTF-8 session encoding")
            for name, value in (features or {}).items():
                try:
                    await session.feature_set(name, value)
                except CommandError as error:
                    if error.code not in {3, 4}:
                        raise
            return session
        except BaseException:
            await session.aclose(detach=False)
            raise

    @property
    def closed(self) -> bool:
        """Return whether the debugging connection has been shut down."""
        return self._closed.is_set()

    @property
    def capabilities(self):
        """Read-only inventory of the most recently observed feature values."""
        return MappingProxyType(self._capabilities)

    @property
    def type_map(self):
        """Return a read-only view of the most recently fetched engine type mappings."""
        return MappingProxyType(self._type_map)

    @property
    def known_breakpoints(self):
        """Last observed breakpoint records, including resolution notifications."""
        return MappingProxyType(self._breakpoints)

    @property
    def known_spawnpoints(self):
        """Last acknowledged spawnpoint records, including late responses."""
        return MappingProxyType(self._spawnpoints)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self.aclose()

    def _emit(self, event):
        try:
            self._events.put_nowait(event)
        except asyncio.QueueFull as error:
            raise ProtocolError("Event queue overflow; consume session events") from error

    def _located(self, value):
        """Add local locations without rewriting engine filenames or raw XML."""
        changes = {}
        if hasattr(value, "local_file"):
            changes.update(self.path_mapper.location(value.file))
        if isinstance(value, Frame):
            changes["inputs"] = tuple(self._located(frame) for frame in value.inputs)
        if isinstance(value, ExecutionResult) and value.breakpoint is not None:
            changes["breakpoint"] = self._located(value.breakpoint)
        if isinstance(value, NotificationEvent):
            if value.breakpoint is not None:
                changes["breakpoint"] = self._located(value.breakpoint)
            if value.message is not None:
                changes["message"] = self._located(value.message)
        return replace(value, **changes) if changes else value

    def _shutdown(self, error):
        if self.closed:
            return
        self._error = error
        self._closed.set()
        self._writer.close()
        for _, future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        self._abandoned.clear()
        self._executions.clear()
        self._eof_commands.clear()
        self._execution_pending = False
        self._execution_owner = None
        self._stdin_modes.clear()
        self._interaction_modes.clear()
        self._spawnpoint_requests.clear()
        self._breakpoint_requests.clear()
        self._feature_requests.clear()
        self.stdin_redirected = self.stdin_waiting = False
        if self._events.full():
            self._events.get_nowait()
        self._events.put_nowait(ClosedEvent(error))

    async def _read_loop(self):
        try:
            while True:
                node = await read_packet(
                    self._reader, self.max_packet_size, xdebug_bytes=self._xdebug_bytes,
                )
                kind = local_name(node)
                if kind == "stream":
                    self._emit(StreamEvent(node.get("type", "stdout"), content_bytes(node)))
                elif kind == "notify":
                    event = self._located(parse_notification(node))
                    if event.name == "stdin":
                        self.stdin_waiting = True
                    if event.breakpoint is not None:
                        self._breakpoints[event.breakpoint.id] = event.breakpoint
                    self._emit(event)
                elif kind == "response":
                    self._dispatch_response(node)
                elif kind == "proxyerror":
                    self._emit(ProxyErrorEvent(proxy_error(node)))
                else:
                    raise ProtocolError(f"Unexpected packet type: {kind}")
        except asyncio.CancelledError:
            raise
        except ConnectionClosed as error:
            if error.clean_eof:
                for transaction, command in tuple(self._eof_commands.items()):
                    # Infer termination only at a complete packet boundary,
                    # and explicitly distinguish it from a received response.
                    node = ET.Element("response", command=command, transaction_id=str(transaction),
                                      status="stopped", reason="ok", dbgpilot_eof="1")
                    self._dispatch_response(node)
            self._shutdown(error)
        except (DBGpilotError, OSError) as error:
            self._shutdown(error)
        except Exception as error:
            self._shutdown(ProtocolError(f"Invalid response: {error}"))

    def _dispatch_response(self, node):
        try:
            transaction = int(node.get("transaction_id", ""))
        except ValueError as error:
            raise ProtocolError("Missing or invalid transaction ID") from error
        pending = self._pending.get(transaction)
        expected = pending[0] if pending else self._abandoned.get(transaction)
        if expected is None:
            raise ProtocolError(f"Unknown transaction ID: {transaction}")
        name, future = pending if pending else (expected, None)
        # Cancellation can reach the future before command() records abandonment.
        abandoned = future is None or future.cancelled()
        if node.get("command") != expected:
            raise ProtocolError(f"Response command does not match transaction {transaction}")
        error = node.find("{*}error")
        if error is not None:
            try:
                code = int(error.get("code", ""))
            except ValueError as exc:
                raise ProtocolError("Invalid command error code") from exc
            message = error.find("{*}message")
            result_error = CommandError(
                name, code, "".join(message.itertext()) if message is not None else "",
                attributes=error.attrib, xml=ET.tostring(error, encoding="unicode"),
            )
            self._finish_execution(transaction, node, failed=True, abandoned=abandoned)
            self._pending.pop(transaction, None)
            self._abandoned.pop(transaction, None)
            self._eof_commands.pop(transaction, None)
            if future is not None and not future.done():
                future.set_exception(result_error)
            return
        self._finish_execution(transaction, node, abandoned=abandoned)
        self._pending.pop(transaction, None)
        self._abandoned.pop(transaction, None)
        self._eof_commands.pop(transaction, None)
        if future is not None and not future.done():
            future.set_result(node)

    def _finish_execution(self, transaction, node, *, failed=False, abandoned=False):
        command = node.get("command")
        feature_arguments = self._feature_requests.pop(transaction, None)
        if feature_arguments is not None and not failed:
            name = feature_arguments.get("n")
            flag = "supported" if command == "feature_get" else "success"
            if node.get(flag) not in {"0", "1"}:
                raise ProtocolError(f"{command} response requires a valid {flag} flag")
            if command == "feature_get":
                feature = Feature(node.get("supported") == "1", (node.text or "").strip())
            elif node.get("success") == "1":
                value = feature_arguments.get("v")
                feature = Feature(True, str(int(value) if isinstance(value, bool) else value))
            else:
                feature = None
            if feature is not None:
                self._capabilities[name] = feature
                if name == "supports_async":
                    self.supports_async = feature.enabled
        if (
            not failed
            and command in {
                "run", "step_into", "step_over", "step_out", "stop", "detach", "interact",
            }
            and node.get("status") not in _STATES - {"starting", "running"}
        ):
            raise ProtocolError(f"{command} response requires a valid execution state")
        breakpoint_request = self._breakpoint_requests.pop(transaction, None)
        if breakpoint_request is not None and not failed:
            self._finish_breakpoint(command, *breakpoint_request, node)
        if command in {"expr", "exec"} and not failed:
            if node.get("success") not in {"0", "1"}:
                raise ProtocolError(f"{command} response requires a success flag")
            if command == "expr" and node.get("success") == "1":
                properties = node.findall("{*}property")
                if len(properties) != 1:
                    raise ProtocolError("Successful expr requires one property")
                parse_property(properties[0], self._type_map)
        spawnpoint_arguments = self._spawnpoint_requests.pop(transaction, None)
        if spawnpoint_arguments is not None and not failed:
            self._finish_spawnpoint(command, spawnpoint_arguments, node)
        if node.get("command") == "stdin" and not failed and node.get("success") not in {"0", "1"}:
            raise ProtocolError("stdin response requires a success flag")
        stdin_mode = self._stdin_modes.pop(transaction, None)
        if (stdin_mode is not None and not failed and node.get("success") == "1"
                and transaction >= self._stdin_mode_transaction):
            self._stdin_mode_transaction = transaction
            self.stdin_redirected = stdin_mode == 1
            if not self.stdin_redirected:
                self.stdin_waiting = False
        interaction_mode = self._interaction_modes.pop(transaction, None)
        if node.get("command") == "interact" and not failed:
            result = parse_interaction(node)
            if interaction_mode == 0 and (result.prompt or result.more):
                raise ProtocolError("Clearing interact must return an empty prompt and buffer")
        operation = self._executions.pop(transaction, None)
        previous = operation[0] if operation is not None else None
        if operation is not None:
            self.stdin_waiting = False
            if self._execution_owner is operation[1]:
                self._execution_pending = False
                self._execution_owner = None
            if failed or (command in _EVALUATIONS and node.get("status") is None):
                self.state = previous
        if not failed:
            self._update_state(node)
        if (abandoned and previous is not None
                and command in _EVALUATIONS and node.get("status") is None):
            # Late/cancelled evaluation replies restore inspectability too.
            if self.state == "break":
                self._emit(StoppedEvent(self.last_result))

    def _update_state(self, node):
        state = node.get("status")
        if state is not None:
            if state not in _STATES:
                raise ProtocolError(f"Unexpected execution state: {state}")
            self.state = state
            if state != "running":
                self.stdin_waiting = False
        if node.get("command") in _CONTINUATIONS and state is not None:
            self.last_result = self._located(execution_result(node))
            if node.get("command") == "interact":
                self.last_interaction = parse_interaction(node)
                self._emit(InteractiveEvent(self.last_interaction))
            if state == "break":
                self._emit(StoppedEvent(self.last_result))

    async def command(self, name, arguments=None, data=None, *, timeout=_DEFAULT,
                      _continuation=False, _execution_previous=None, _allow_eof=False,
                      _stdin_mode=None, _interaction_mode=None):
        """Issue a command and await its matching response; events are dispatched separately.

        Timeout/cancellation abandons the response, not the PHP execution. The
        session remains owned by the caller, who can wait for events or close it.
        """
        if self.closed:
            raise self._error
        if (self.state == "running" or self._execution_pending) and not _continuation:
            asynchronous = self.supports_async and name in {"status", "break", "stdin"}
            waiting_input = (name == "stdin" and data is not None and self.stdin_redirected
                             and self.stdin_waiting and self.supports_command("stdin"))
            if not asynchronous and not waiting_input:
                raise SessionStateError(
                    "The engine cannot accept this command while PHP is running",
                )
        if timeout is _DEFAULT:
            timeout = self.command_timeout
        transaction = None
        future = None
        try:
            async with asyncio.timeout(timeout):
                async with self._write_lock:
                    if self.closed:
                        raise self._error
                    if len(self._pending) + len(self._abandoned) >= self.max_pending_commands:
                        raise SessionStateError(
                            "Outstanding DBGp command limit reached; "
                            "await replies or explicitly close the session"
                        )
                    self._transaction += 1
                    transaction = self._transaction
                    packet = encode_command(name, transaction, arguments, data)
                    future = asyncio.get_running_loop().create_future()
                    self._pending[transaction] = (name, future)
                    if _execution_previous is not None:
                        self._executions[transaction] = (_execution_previous, self._execution_owner)
                    if _stdin_mode is not None:
                        self._stdin_modes[transaction] = _stdin_mode
                    if _interaction_mode is not None:
                        self._interaction_modes[transaction] = _interaction_mode
                    if name in _SPAWNPOINT_COMMANDS:
                        self._spawnpoint_requests[transaction] = dict(arguments or {})
                    if name in {"feature_get", "feature_set"}:
                        self._feature_requests[transaction] = dict(arguments or {})
                    if name in {
                        "breakpoint_set", "breakpoint_get", "breakpoint_list",
                        "breakpoint_update", "breakpoint_remove",
                    }:
                        self._breakpoint_requests[transaction] = (dict(arguments or {}), data)
                    try:
                        self._writer.write(packet)
                        if _allow_eof:
                            self._eof_commands[transaction] = name
                        await self._writer.drain()
                    except (OSError, ConnectionError) as error:
                        self._shutdown(ConnectionClosed(f"Cannot write DBGp command: {error}"))
                return await future
        finally:
            if transaction in self._pending:
                self._pending.pop(transaction)
                self._abandoned[transaction] = name
                if future is not None:
                    future.cancel()

    async def next_event(self, *, timeout=None):
        """Return the next queued session event, optionally limiting the wait."""
        return await wait_queue(self._events, self._closed, timeout, self._error)

    async def feature_get(self, name) -> Feature:
        """Query an engine feature's support flag and value, updating the capability cache."""
        node = await self.command("feature_get", {"n": name})
        return Feature(node.get("supported") == "1", (node.text or "").strip())

    async def feature_set(self, name, value) -> bool:
        """Set an engine feature and return whether the engine accepted it."""
        if name == "encoding":
            normalized = str(value).casefold().replace("-", "")
            if normalized != "utf8" and not (
                self._xdebug_bytes and normalized in {"iso88591", "latin1"}
            ):
                raise ValueError("DBGpilot requires UTF-8 or Xdebug's Latin-1 byte framing")
        if name == "data_encoding" and value != "base64":
            raise ValueError("DBGpilot requires base64 command data")
        node = await self.command("feature_set", {"n": name, "v": value})
        return node.get("success") == "1"

    async def refresh_capabilities(self):
        """Query known features and commands and return the refreshed capability view."""
        for name in (*_FEATURES, *_COMMANDS):
            try:
                await self.feature_get(name)
            except CommandError as error:
                if error.code not in {3, 4}:
                    raise
                self._capabilities[name] = Feature(False, "")
                if name == "supports_async":
                    self.supports_async = False
        return self.capabilities

    def supports_command(self, name):
        """Return whether the cached engine capability advertises this command as enabled."""
        feature = self._capabilities.get(name)
        return feature.enabled if feature is not None else False

    async def _require_command(self, name):
        if name not in self._capabilities:
            await self.feature_get(name)
        if not self.supports_command(name):
            raise SessionStateError(f"The engine does not advertise support for {name}")

    async def status(self) -> ExecutionResult:
        """Query the engine's execution state and return validated execution metadata."""
        node = await self.command("status")
        if node.get("status") not in _STATES:
            raise ProtocolError("status returned no valid execution state")
        result = self._located(execution_result(node))
        if not self._execution_pending and self.last_result.status != result.status:
            self.last_result = result
        return result

    async def stack_depth(self) -> int:
        """Return the validated stack depth while the session is inspectable."""
        self._require_paused()
        node = await self.command("stack_depth")
        try:
            depth = int(node.get("depth", ""))
            if depth < 0:
                raise ValueError
            return depth
        except ValueError as error:
            raise ProtocolError("Invalid stack depth") from error

    async def typemap_get(self) -> tuple[TypeMapping, ...]:
        """Fetch and cache the engine's language-to-common-type mappings."""
        if self.state == "stopping":
            self._require_paused()
        node = await self.command("typemap_get")
        mappings = []
        for entry in node.findall("{*}map"):
            if not entry.get("name") or not entry.get("type"):
                raise ProtocolError("Invalid type mapping")
            mappings.append(TypeMapping(
                entry.get("name"), entry.get("type"),
                entry.get("{http://www.w3.org/2001/XMLSchema-instance}type"),
                ET.tostring(entry, encoding="unicode"),
            ))
        self._type_map = {entry.language_type: entry for entry in mappings}
        return tuple(mappings)

    def _require_paused(self):
        if self.closed:
            raise self._error
        postmortem = self._capabilities.get("supports_postmortem", Feature(False, "")).enabled
        if self._execution_pending or (
            self.state not in {"break", "interactive"}
            and not (self.state == "stopping" and postmortem)
        ):
            raise SessionStateError(
                f"Inspection requires a breakpoint, current state is {self.state}",
            )

    async def _continue(self, name, *, timeout=_DEFAULT):
        node = await self._execute(name, timeout=timeout)
        return self._located(execution_result(node))

    async def _execute(
        self, name, arguments=None, data=None, *, timeout=_DEFAULT, _interaction_mode=None,
    ):
        if self.closed:
            raise self._error
        allowed = ({"break", "interactive", "stopping"} if name in _EVALUATIONS else
                   {"break", "interactive"} if name == "interact" else {"starting", "break"})
        if self._execution_pending or self.state not in allowed:
            raise SessionStateError(f"Cannot {name} in state {self.state}")
        previous = self.state
        self.state = "running"
        self._execution_pending = True
        owner = self._execution_owner = object()
        if timeout is _DEFAULT:
            timeout = self.execution_timeout
        try:
            return await self.command(name, arguments, data, timeout=timeout,
                                      _continuation=True, _execution_previous=previous,
                                      _interaction_mode=_interaction_mode)
        finally:
            if self._execution_owner is owner and not self._executions:
                self._execution_pending = False
                self._execution_owner = None
                if not self.closed and self.state == "running":
                    self.state = previous

    async def run(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Resume execution and await the engine's next execution result.

        Timeout or cancellation abandons the response wait while execution remains
        owned by this session; it does not stop PHP.
        """
        return await self._continue("run", timeout=timeout)

    async def resume(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Resume execution through run() and return its execution result."""
        return await self.run(timeout=timeout)

    async def run_until_break(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Run until paused at a breakpoint, raising ExecutionFinished for other results."""
        result = await self.run(timeout=timeout)
        if not result.paused:
            raise ExecutionFinished(result)
        return result

    async def step_into(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Advance execution into the next statement or function and return its result."""
        return await self._continue("step_into", timeout=timeout)

    async def step_over(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Advance past the next statement without stepping into called functions."""
        return await self._continue("step_over", timeout=timeout)

    async def step_out(self, *, timeout=_DEFAULT) -> ExecutionResult:
        """Run until the current function returns and report the next execution state."""
        return await self._continue("step_out", timeout=timeout)

    async def interrupt(self):
        """Request a break while PHP is running, requiring engine support for async commands."""
        if self.state != "running" or not self.supports_async:
            raise SessionStateError("This engine cannot interrupt running PHP through DBGp")
        await self._require_command("break")
        return await self.command("break")

    async def stdin(self, *, mode=None, data=None, timeout=_DEFAULT) -> bool:
        """Configure stdin OR send data; the protocol forbids combining them."""
        if (mode is None) == (data is None):
            raise ValueError("Provide exactly one of stdin mode or data")
        if mode is not None and (type(mode) is not int or mode not in {0, 1}):
            raise ValueError("stdin mode must be 0 (off) or 1 (redirect)")
        if data is not None and not isinstance(data, (str, bytes)):
            raise TypeError("stdin data must be text or bytes")
        await self._require_command("stdin")
        async with (
            asyncio.timeout(self.command_timeout if timeout is _DEFAULT else timeout),
            self._stdin_lock,
        ):
            if data is not None and not self.stdin_redirected:
                raise SessionStateError("Enable stdin redirection before sending input")
            node = await self.command("stdin", {"c": mode}, data, timeout=timeout, _stdin_mode=mode)
            if node.get("success") not in {"0", "1"}:
                raise ProtocolError("stdin response requires a success flag")
            return node.get("success") == "1"

    async def set_stdin(self, enabled=True, *, timeout=_DEFAULT) -> bool:
        """Enable or disable stdin redirection and return whether the engine accepted it."""
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean")
        return await self.stdin(mode=int(enabled), timeout=timeout)

    async def send_stdin(self, data, *, timeout=_DEFAULT) -> bool:
        """Send text or bytes to engine stdin after redirection has been enabled."""
        return await self.stdin(data=data, timeout=timeout)

    async def interact(self, code="", *, mode=1, timeout=_DEFAULT) -> InteractiveResult:
        """Send one code chunk; the engine owns compilation and buffering."""
        if type(mode) is not int or mode not in {0, 1}:
            raise ValueError("interact mode must be 0 (clear) or 1 (submit)")
        if not isinstance(code, (str, bytes)):
            raise TypeError("interact code must be text or bytes")
        if self._execution_pending or self.state not in {"break", "interactive"}:
            raise SessionStateError(f"Cannot interact in state {self.state}")
        await self._require_command("interact")
        node = await self._execute(
            "interact", {"m": mode}, code, timeout=timeout, _interaction_mode=mode,
        )
        return parse_interaction(node)

    async def detach(self):
        """Detach from the engine, allowing PHP to continue, then close the connection.

        Reject detaching while execution is outstanding. Once detach is sent, close
        the session even if awaiting its response fails.
        """
        if self._execution_pending or self.state == "running":
            raise SessionStateError("Cannot detach while execution is outstanding")
        await self._require_command("detach")
        try:
            return self._located(execution_result(
                await self.command("detach", _allow_eof=self.allow_detach_eof),
            ))
        finally:
            await self.aclose(detach=False)

    async def stop(self):
        """Terminate PHP execution. Use detach() to allow the request to finish."""
        if self._execution_pending or self.state == "running":
            raise SessionStateError("Cannot stop while execution is outstanding; interrupt first")
        try:
            node = await self.command("stop", _allow_eof=True)
            self.state = node.get("status", "stopped")
            return self._located(execution_result(node))
        finally:
            await self.aclose(detach=False)

    async def stack(self, *, depth=None) -> tuple[Frame, ...]:
        """Read stack frames at the requested depth, or all depths when depth is None."""
        self._require_paused()
        node = await self.command("stack_get", {"d": depth})
        return tuple(self._located(parse_frame(frame)) for frame in node.findall("{*}stack"))

    async def contexts(self, *, depth=0) -> dict[int, str]:
        """Return the engine's context IDs and names for the requested stack depth."""
        if self.state == "stopping":
            self._require_paused()
        node = await self.command("context_names", {"d": depth})
        return {int(child.get("id")): child.get("name", "") for child in node.findall("{*}context")}

    async def context(self, *, context=0, depth=0):
        """Read the properties in a context at the requested stack depth while paused."""
        self._require_paused()
        node = await self.command("context_get", {"c": context, "d": depth})
        return tuple(parse_property(child, self._type_map) for child in node.findall("{*}property"))

    async def property_get(
        self, name, *, context=0, depth=0, page=0, max_data=None, key=None, address=None,
    ):
        """Read one property page with optional value-size, key, and address targeting."""
        self._require_paused()
        node = await self.command("property_get", {
            "n": name, "c": context, "d": depth, "p": page, "m": max_data, "k": key, "a": address,
        })
        prop = node.find("{*}property")
        if prop is None:
            raise ProtocolError("property_get returned no property")
        return parse_property(prop, self._type_map)

    async def property_children(
        self, name, *, context=0, depth=0, max_pages=1024, key=None, address=None,
    ):
        """Fetch all direct children. Nested children remain explicit properties."""
        children = []
        for page in range(max_pages):
            prop = await self.property_get(name, context=context, depth=depth, page=page,
                                           key=key, address=address)
            if prop.page != page:
                raise ProtocolError("Engine returned the wrong property page")
            children.extend(prop.children)
            if len(children) >= prop.total_children:
                return tuple(children)
            if not prop.children:
                raise ProtocolError("Property pagination stopped before all children were returned")
        raise ProtocolError("Property pagination exceeded max_pages")

    async def property_value(self, name, *, context=0, depth=0, page=None, key=None,
                             address=None, max_data=0) -> bytes:
        """Return raw property value bytes using the supplied paging and target options."""
        return (await self.property_value_info(
            name, context=context, depth=depth, page=page, key=key,
            address=address, max_data=max_data,
        )).data

    async def property_value_info(self, name, *, context=0, depth=0, page=None,
                                  key=None, address=None, max_data=0) -> PropertyValue:
        """Retrieve value bytes and engine size/targeting metadata."""
        self._require_paused()
        node = await self.command("property_value", {
            "n": name, "c": context, "d": depth, "m": max_data,
            "p": page, "k": key, "a": address,
        })
        data = content_bytes(node)
        try:
            size = int(node.get("size", len(data)))
            result_page = (
                int(node.get("page", page)) if node.get("page", page) is not None else None
            )
            if size < 0 or (result_page is not None and result_page < 0):
                raise ValueError
        except ValueError as error:
            raise ProtocolError("Invalid property value metadata") from error
        return PropertyValue(data, size, node.get("encoding", "none"), result_page,
                             node.get("key", key), node.get("address", address))

    @keyword_aliases(type="property_type")
    async def property_set(self, name, expression: str | bytes, *, property_type=None, context=0,
                           depth=0, address=None) -> bool:
        """Assign an engine-native payload; Xdebug evaluates it as PHP code."""
        self._require_paused()
        if not isinstance(expression, (str, bytes)):
            raise TypeError(
                "property_set expects an engine-native string or bytes; "
                "use set_value for Python values"
            )
        raw = expression.encode("utf-8") if isinstance(expression, str) else expression
        node = await self.command("property_set", {
            "n": name, "c": context, "d": depth, "t": property_type, "l": len(raw), "a": address,
        }, raw)
        return node.get("success") == "1"

    async def set_value(self, name, value, *, context=0, depth=0, address=None) -> bool:
        """Assign a Python scalar, safely representing strings and binary data in PHP."""
        if self.info.language.casefold() != "php":
            raise SessionStateError(
                "set_value represents PHP scalars; use property_set for this engine",
            )
        if isinstance(value, (str, bytes)):
            raw = value.encode("utf-8", "surrogateescape") if isinstance(value, str) else value
            expression = "base64_decode('" + base64.b64encode(raw).decode("ascii") + "')"
        elif value is None:
            expression = "null"
        elif isinstance(value, bool):
            expression = "true" if value else "false"
        elif isinstance(value, int):
            expression = str(value)
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(
                    "Use property_set with an explicit PHP expression for non-finite values",
                )
            expression = repr(value)
        else:
            raise TypeError("set_value accepts strings, bytes, numbers, booleans, or None")
        return await self.property_set(
            name, expression, context=context, depth=depth, address=address,
        )

    async def evaluate(self, expression: str, *, depth=0, page=0, timeout=_DEFAULT):
        """Evaluate PHP code; unlike property reads, this can have side effects."""
        self._require_paused()
        if depth < 0:
            raise ValueError("Stack depth cannot be negative")
        if depth != 0 and not self.supports_eval_depth:
            raise ValueError(
                "Xdebug evaluates in the current frame; use property_get/context for other frames",
            )
        await self._require_command("eval")
        node = await self._execute("eval", {"d": depth, "p": page}, expression, timeout=timeout)
        prop = node.find("{*}property")
        return parse_property(prop, self._type_map) if prop is not None else None

    def _evaluation_options(self, code, *, depth=0, page=0):
        if not isinstance(code, (str, bytes)):
            raise TypeError("Code must be text or bytes")
        for name, value in (("depth", depth), ("page", page)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")
        if depth and not self.supports_eval_depth:
            raise ValueError("This engine is configured for current-frame evaluation only")

    async def expr(self, expression: str | bytes, *, depth=0, page=0, timeout=_DEFAULT):
        """Evaluate an expression, returning a property or None on success=0."""
        self._require_paused()
        self._evaluation_options(expression, depth=depth, page=page)
        await self._require_command("expr")
        node = await self._execute("expr", {"d": depth, "p": page}, expression, timeout=timeout)
        if node.get("success") == "0":
            return None
        return parse_property(node.find("{*}property"), self._type_map)

    async def exec(self, code: str | bytes, *, timeout=_DEFAULT) -> bool:
        """Execute a code fragment, returning its success flag, without a value."""
        self._require_paused()
        self._evaluation_options(code)
        await self._require_command("exec")
        node = await self._execute("exec", data=code, timeout=timeout)
        return node.get("success") == "1"

    async def source(self, file: str | Path | None = None, *, begin=None, end=None) -> bytes:
        """Fetch source bytes for an optional mapped file and optional begin/end line range."""
        if self.state == "stopping":
            self._require_paused()
        node = await self.command("source", {
            "f": self.path_mapper.to_remote(file) if file is not None else None,
            "b": begin, "e": end,
        })
        if node.get("success") == "0":
            raise ProtocolError("Engine could not retrieve source")
        return content_bytes(node)

    async def set_output(self, stream="stdout", *, mode=1) -> bool:
        """Set stdout/stderr handling to 0 (off), 1 (copy), or 2 (redirect)."""
        if stream not in {"stdout", "stderr"} or mode not in {0, 1, 2}:
            raise ValueError("Choose stdout/stderr and mode 0 (off), 1 (copy), or 2 (redirect)")
        node = await self.command(stream, {"c": mode})
        return node.get("success") == "1"

    async def set_breakpoint(
        self, file: str | Path | None = None, line: int | None = None, *, kind="line",
        condition=None, function=None, exception=None, temporary=False,
        hit_value=None, hit_condition=None, state="enabled",
    ) -> Breakpoint:
        """Create a validated breakpoint and return its engine record.

        Map local source paths to engine URIs. Supplying a condition for a line
        breakpoint selects the conditional breakpoint type.
        """
        if condition is not None and kind == "line":
            kind = "conditional"
        if kind not in {"line", "conditional", "call", "return", "exception", "watch"}:
            raise ValueError("Invalid breakpoint type")
        if kind == "line" and (file is None or line is None or line < 1):
            raise ValueError("Line breakpoints need a file and positive line number")
        if kind == "conditional" and (file is None or (line is not None and line < 1)):
            raise ValueError(
                "Conditional breakpoints need a file and an optional positive line number",
            )
        if kind in {"conditional", "watch"} and condition is None:
            raise ValueError("This breakpoint requires a condition")
        if kind in {"call", "return"} and not function:
            raise ValueError("This breakpoint requires a function name")
        if kind == "exception" and not exception:
            raise ValueError("This breakpoint requires an exception name")
        if state not in {"enabled", "disabled"}:
            raise ValueError("Invalid breakpoint state")
        types = self._capabilities.get("breakpoint_types")
        if types is not None and types.supported and kind not in types.value.split():
            raise SessionStateError(f"The engine does not advertise {kind} breakpoints")
        if hit_condition not in {None, ">=", "==", "%"} or (
            hit_value is not None and hit_value < 0
        ):
            raise ValueError("Invalid breakpoint hit condition")
        uri = self.path_mapper.to_remote(file) if file is not None else None
        node = await self.command("breakpoint_set", {
            "t": kind, "f": uri, "n": line, "m": function, "x": exception,
            "r": int(temporary), "h": hit_value, "o": hit_condition, "s": state,
        }, condition)
        return self._created_breakpoint({"t": kind, "f": uri, "n": line, "s": state,
                                        "h": hit_value, "o": hit_condition, "m": function,
                                        "x": exception, "r": temporary}, condition, node)

    def _created_breakpoint(self, arguments, data, node):
        state = node.get("state", arguments.get("s") or "enabled")
        if not node.get("id") or not state:
            raise ProtocolError("breakpoint_set requires an ID and nonempty state")
        return self._located(Breakpoint(
            node.get("id"), arguments.get("t", "line"), arguments.get("f"), arguments.get("n"),
            state=state, resolved=node.get("resolved"), hit_value=arguments.get("h") or 0,
            hit_condition=arguments.get("o"), expression=data, function=arguments.get("m"),
            exception=arguments.get("x"), temporary=bool(arguments.get("r", False)),
        ))

    def _finish_breakpoint(self, command, arguments, data, node):
        breakpoint_id = arguments.get("d")
        if command == "breakpoint_set":
            point = self._created_breakpoint(arguments, data, node)
            self._breakpoints[point.id] = point
        elif command == "breakpoint_get":
            points = node.findall("{*}breakpoint")
            if len(points) != 1:
                raise ProtocolError("breakpoint_get requires one breakpoint")
            point = self._located(parse_breakpoint(points[0]))
            if point.id != breakpoint_id:
                raise ProtocolError("breakpoint_get returned a different ID")
            self._breakpoints[breakpoint_id] = point
        elif command == "breakpoint_list":
            points = tuple(
                self._located(parse_breakpoint(child)) for child in node.findall("{*}breakpoint")
            )
            if len({point.id for point in points}) != len(points):
                raise ProtocolError("breakpoint_list returned duplicate IDs")
            self._breakpoints.clear()
            self._breakpoints.update((point.id, point) for point in points)
        elif command == "breakpoint_update" and breakpoint_id in self._breakpoints:
            changes = {key: arguments[option] for key, option in (
                ("state", "s"), ("line", "n"), ("hit_value", "h"), ("hit_condition", "o"),
            ) if arguments.get(option) is not None}
            self._breakpoints[breakpoint_id] = replace(self._breakpoints[breakpoint_id], **changes)
        elif command == "breakpoint_remove":
            self._breakpoints.pop(breakpoint_id, None)

    @keyword_aliases(id="breakpoint_id")
    async def get_breakpoint(self, breakpoint_id: str) -> Breakpoint:
        """Fetch a breakpoint by ID and return its mapped source metadata."""
        node = await self.command("breakpoint_get", {"d": breakpoint_id})
        bp = node.find("{*}breakpoint")
        if bp is None:
            raise ProtocolError("breakpoint_get returned no breakpoint")
        result = self._located(parse_breakpoint(bp))
        return result

    async def breakpoints(self) -> tuple[Breakpoint, ...]:
        """Return all engine breakpoints with source path mapping metadata."""
        node = await self.command("breakpoint_list")
        results = tuple(
            self._located(parse_breakpoint(child)) for child in node.findall("{*}breakpoint")
        )
        return results

    @keyword_aliases(id="breakpoint_id")
    async def update_breakpoint(
        self, breakpoint_id, *, state=None, line=None, hit_value=None, hit_condition=None,
    ):
        """Update a breakpoint's state, line, or hit condition after validating options."""
        if state not in {None, "enabled", "disabled"}:
            raise ValueError("Invalid breakpoint state")
        if line is not None and line < 1:
            raise ValueError("Line numbers must be positive")
        if hit_condition not in {None, ">=", "==", "%"} or (
            hit_value is not None and hit_value < 0
        ):
            raise ValueError("Invalid breakpoint hit condition")
        await self.command("breakpoint_update", {
            "d": breakpoint_id, "s": state, "n": line, "h": hit_value, "o": hit_condition,
        })

    @keyword_aliases(id="breakpoint_id")
    async def remove_breakpoint(self, breakpoint_id):
        """Remove a breakpoint from the engine by ID."""
        await self.command("breakpoint_remove", {"d": breakpoint_id})

    @staticmethod
    def _spawnpoint_options(*, spawnpoint_id=None, line=None, state=None):
        if spawnpoint_id is not None and (not isinstance(spawnpoint_id, str) or not spawnpoint_id):
            raise ValueError("Spawnpoint ID must be a nonempty string")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or line < 1):
            raise ValueError("Spawnpoint line must be a positive integer")
        if state is not None and state not in {"enabled", "disabled"}:
            raise ValueError("Invalid spawnpoint state")

    def _finish_spawnpoint(self, command, arguments, node):
        """Validate before updating the inventory, also for abandoned requests."""
        spawnpoint_id = arguments.get("d")
        if command == "spawnpoint_set":
            point = parse_spawnpoint(node)
            point = self._located(replace(point, file=arguments.get("f"), line=arguments.get("n")))
            self._spawnpoints[point.id] = point
        elif command == "spawnpoint_get":
            points = node.findall("{*}spawnpoint")
            if len(points) != 1:
                raise ProtocolError("spawnpoint_get requires one spawnpoint")
            point = self._located(parse_spawnpoint(points[0]))
            if point.id != spawnpoint_id:
                raise ProtocolError("spawnpoint_get returned a different ID")
            self._spawnpoints[point.id] = point
        elif command == "spawnpoint_list":
            points = tuple(
                self._located(parse_spawnpoint(child)) for child in node.findall("{*}spawnpoint")
            )
            if len({point.id for point in points}) != len(points):
                raise ProtocolError("spawnpoint_list returned duplicate IDs")
            self._spawnpoints.clear()
            self._spawnpoints.update((point.id, point) for point in points)
        elif command == "spawnpoint_update" and spawnpoint_id in self._spawnpoints:
            changes = {key: arguments[option] for key, option in (("state", "s"), ("line", "n"))
                       if arguments.get(option) is not None}
            # XML/attributes remain the last actual engine response, not invented metadata.
            self._spawnpoints[spawnpoint_id] = replace(self._spawnpoints[spawnpoint_id], **changes)
        elif command == "spawnpoint_remove":
            self._spawnpoints.pop(spawnpoint_id, None)

    async def set_spawnpoint(self, file: str | Path | None = None, line: int | None = None,
                             *, state="enabled") -> Spawnpoint:
        """Create an engine spawnpoint using an optional mapped source file and line."""
        self._spawnpoint_options(line=line, state=state)
        if state is None:
            raise ValueError("Invalid spawnpoint state")
        if file is not None and not isinstance(file, (str, Path)):
            raise TypeError("Spawnpoint file must be a path or file URI")
        uri = self.path_mapper.to_remote(file) if file is not None else None
        if uri is not None and not uri.startswith("file://"):
            raise ValueError("Spawnpoints require file:// URIs")
        await self._require_command("spawnpoint_set")
        node = await self.command("spawnpoint_set", {"f": uri, "n": line, "s": state})
        return self._located(replace(parse_spawnpoint(node), file=uri, line=line))

    @keyword_aliases(id="spawnpoint_id")
    async def get_spawnpoint(self, spawnpoint_id: str) -> Spawnpoint:
        """Fetch a spawnpoint by ID after confirming engine support for the command."""
        if spawnpoint_id is None:
            raise ValueError("Spawnpoint ID must be a nonempty string")
        self._spawnpoint_options(spawnpoint_id=spawnpoint_id)
        await self._require_command("spawnpoint_get")
        node = await self.command("spawnpoint_get", {"d": spawnpoint_id})
        return self._located(parse_spawnpoint(node.find("{*}spawnpoint")))

    async def spawnpoints(self) -> tuple[Spawnpoint, ...]:
        """Return all engine spawnpoints with source path mapping metadata."""
        await self._require_command("spawnpoint_list")
        node = await self.command("spawnpoint_list")
        return tuple(
            self._located(parse_spawnpoint(child)) for child in node.findall("{*}spawnpoint")
        )

    @keyword_aliases(id="spawnpoint_id")
    async def update_spawnpoint(self, spawnpoint_id: str, *, state=None, line=None):
        """Change a spawnpoint's state or line, requiring at least one supplied update."""
        if spawnpoint_id is None:
            raise ValueError("Spawnpoint ID must be a nonempty string")
        self._spawnpoint_options(spawnpoint_id=spawnpoint_id, line=line, state=state)
        if state is None and line is None:
            raise ValueError("Provide at least one spawnpoint update")
        await self._require_command("spawnpoint_update")
        await self.command("spawnpoint_update", {"d": spawnpoint_id, "s": state, "n": line})

    @keyword_aliases(id="spawnpoint_id")
    async def remove_spawnpoint(self, spawnpoint_id: str):
        """Remove a spawnpoint by ID after confirming engine support for the command."""
        if spawnpoint_id is None:
            raise ValueError("Spawnpoint ID must be a nonempty string")
        self._spawnpoint_options(spawnpoint_id=spawnpoint_id)
        await self._require_command("spawnpoint_remove")
        await self.command("spawnpoint_remove", {"d": spawnpoint_id})

    async def snapshot(
        self, variables: Iterable[str] = (), *, expressions: Iterable[str] = (), depth=0, context=0,
    ):
        """Read paused execution, stack, variables, and requested expression results.

        Expressions are evaluated in PHP and may have side effects. Read the supplied
        variables from the requested stack depth and context.
        """
        self._require_paused()
        frames = await self.stack()
        properties = {}
        evaluated = {}
        for name in variables:
            properties[name] = await self.property_get(name, depth=depth, context=context)
        for code in expressions:
            evaluated[code] = await self.evaluate(code, depth=depth)
        execution = self.last_result
        if execution.file is None and frames:
            execution = self._located(replace(execution, file=frames[0].file, line=frames[0].line))
        return Snapshot(self.info.id, execution, frames, properties, evaluated)

    async def aclose(self, *, detach=True):
        """Close the session and its response reader, attempting detach when appropriate.

        With detach=True, try to release an idle, detachable engine before closing.
        With execution outstanding, close the connection without sending detach.
        """
        try:
            if (not self.closed and detach and not self._execution_pending
                    and self.state in {"starting", "break", "stopping", "interactive"}
                    and self.supports_command("detach")):
                with suppress(DBGpilotError, TimeoutError, OSError):
                    await self.command("detach", timeout=1.0)
        finally:
            self._shutdown(ConnectionClosed("Session closed"))
            if self._reader_task is not None and self._reader_task is not asyncio.current_task():
                self._reader_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._reader_task
            with suppress(OSError, TimeoutError):
                async with asyncio.timeout(1):
                    await self._writer.wait_closed()
