"""A persistent controller owner, with a local HTTP/JSON-RPC interface."""

import asyncio
from collections import OrderedDict, deque
from concurrent.futures import (
    CancelledError as FutureCancelledError,
    TimeoutError as FutureTimeoutError,
)
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import inspect
import ipaddress
import json
import logging
import math
import select
import socket
import threading
import uuid
from urllib.parse import urlsplit

from .controller import Controller
from ._version import __version__
from .errors import (
    CommandError, ConnectionClosed, ExecutionFinished, PathMappingError,
    ProtocolError, ProxyError, SessionStateError,
)
from .models import ClosedEvent
from .wire import RemoteError, binary_value, json_value

LOGGER = logging.getLogger(__name__)
SESSION_METHODS = frozenset((
    "status stack_depth typemap_get stack contexts context property_get property_children "
    "property_value property_value_info property_set set_value evaluate expr exec "
    "source set_output "
    "set_breakpoint get_breakpoint breakpoints update_breakpoint remove_breakpoint "
    "set_spawnpoint get_spawnpoint spawnpoints update_spawnpoint remove_spawnpoint "
    "feature_get feature_set refresh_capabilities run resume run_until_break "
    "step_into step_over step_out interrupt detach stop snapshot stdin set_stdin "
    "send_stdin interact"
).split())
EXECUTION_METHODS = frozenset(
    "run resume run_until_break step_into step_over step_out evaluate expr exec interact".split()
)


@dataclass
class _Record:
    session: object
    events: deque
    sequence: int = 0
    claimed: bool = False
    closed_at: float | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _invalid(message):
    return RemoteError(-32602, message, {"type": "InvalidParams"})


def _invalid_constant(value):
    raise ValueError(f"Non-finite JSON number: {value}")


def _error_response(request_id, error):
    if isinstance(error, RemoteError):
        detail = error.to_dict()
    else:
        code = -32603
        if isinstance(error, (ValueError, TypeError)):
            code = -32602
        elif isinstance(error, TimeoutError):
            code = -32003
        elif isinstance(error, SessionStateError):
            code = -32002
        elif isinstance(error, CommandError):
            code = -32004
        elif isinstance(error, ProtocolError):
            code = -32005
        elif isinstance(error, ConnectionClosed):
            code = -32006
        elif isinstance(error, ExecutionFinished):
            code = -32007
        elif isinstance(error, ProxyError):
            code = -32011
        elif isinstance(error, PathMappingError):
            code = -32012
        detail = {"code": code, "message": str(error), "data": json_value(error)}
    return {"jsonrpc": "2.0", "id": request_id, "error": detail}


class Server:
    """Own live sessions independently of HTTP clients.

    HTTP parsing runs in stdlib server threads. All debugging state and RPC
    operations run on the single owning asyncio event loop.
    """

    def __init__(self, host="127.0.0.1", port=9004, *, controller=None,
                 xdebug_host="127.0.0.1", xdebug_port=9003, token=None,
                 event_history=1024, max_closed_sessions=128, max_wait=300,
                 max_request_bytes=1024 * 1024, proxy_host=None, proxy_port=9001,
                 idekey=None, proxy_listen_port=None, path_mappings=None,
                 max_http_connections=128):
        if event_history < 1 or max_closed_sessions < 0 or max_wait < 1 or max_request_bytes < 1:
            raise ValueError("Invalid server limits")
        if type(max_http_connections) is not int or max_http_connections < 1:
            raise ValueError("max_http_connections must be a positive integer")
        self.max_http_connections = max_http_connections
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback and not token:
            raise ValueError("A non-loopback API listener requires a token")
        self.host, self.port, self.token = host, port, token
        self.instance_id = uuid.uuid4().hex
        if controller is not None and path_mappings is not None:
            raise ValueError("Configure mappings on the supplied controller")
        self.controller = controller if controller is not None else Controller(
            xdebug_host, xdebug_port, path_mappings=() if path_mappings is None else path_mappings,
        )
        if (proxy_host is None) != (idekey is None):
            raise ValueError("Provide both proxy_host and idekey for proxy startup")
        self._proxy_settings = None if proxy_host is None else dict(
            host=proxy_host, port=proxy_port, idekey=idekey, listen_port=proxy_listen_port,
        )
        self.event_history, self.max_closed_sessions = event_history, max_closed_sessions
        self.max_wait, self.max_request_bytes = max_wait, max_request_bytes
        self._records = {}
        self._condition = asyncio.Condition()
        self._errors = deque(maxlen=50)
        self._background = set()
        self._requests = set()
        self._request_ids = {}
        self._cancelled = OrderedDict()
        self._http = self._thread = self._loop = None
        self._closing = False
        self._start_lock = asyncio.Lock()

    @property
    def url(self):
        """Return the API origin, using a connectable host for wildcard listeners."""
        host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(self.host, self.host)
        return f"http://{'[' + host + ']' if ':' in host else host}:{self.port}"

    async def start(self):
        """Start the API and debugger listeners once, returning this server."""
        async with self._start_lock:
            return await self._start()

    async def _start(self):
        if self._closing:
            raise ConnectionClosed("A closed server cannot be restarted")
        if self._http is not None:
            return self
        self._loop = asyncio.get_running_loop()
        try:
            await self.controller.start()
            if self._closing:
                raise ConnectionClosed("Server closed during startup")
            if self._proxy_settings is not None:
                await self.controller.register_proxy(**self._proxy_settings)
            owner = self

            class Handler(_Handler):
                """Bind HTTP request handling to this server instance."""

                pilot = owner

            class HTTPServer(ThreadingHTTPServer):
                """Limit concurrent connections and track sockets for shutdown."""

                address_family = socket.AF_INET6 if ":" in owner.host else socket.AF_INET
                request_queue_size = 64
                slots = threading.BoundedSemaphore(owner.max_http_connections)
                connections = set()
                connections_lock = threading.Lock()

                def process_request(self, request, address):
                    if owner._closing or not self.slots.acquire(blocking=False):
                        self.shutdown_request(request)
                        return
                    with self.connections_lock:
                        self.connections.add(request)
                    try:
                        super().process_request(request, address)
                    except BaseException:
                        with self.connections_lock:
                            self.connections.discard(request)
                        self.slots.release()
                        raise

                def process_request_thread(self, request, address):
                    try:
                        super().process_request_thread(request, address)
                    finally:
                        with self.connections_lock:
                            self.connections.discard(request)
                        self.slots.release()

                def close_connections(self):
                    """Shut down and close all tracked client sockets."""
                    with self.connections_lock:
                        connections = tuple(self.connections)
                    for connection in connections:
                        with suppress(OSError):
                            connection.shutdown(socket.SHUT_RDWR)
                        connection.close()

            self._http = HTTPServer((self.host, self.port), Handler)
            self._http.daemon_threads = True
            self.port = self._http.server_address[1]
            self._thread = threading.Thread(
                target=partial(self._http.serve_forever, poll_interval=0.05),
                name="dbgpilot-http", daemon=True,
            )
            self._thread.start()
            self._spawn(self._collect_sessions())
            self._spawn(self._collect_errors())
            return self
        except BaseException:
            await self.aclose()
            raise

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.aclose()

    def _spawn(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task

    async def _collect_sessions(self):
        try:
            while True:
                session = await self.controller.wait_for_session()
                record = _Record(session, deque(maxlen=self.event_history))
                async with self._condition:
                    self._records[session.info.id] = record
                    self._prune()
                    self._condition.notify_all()
                self._spawn(self._collect_events(record))
        except ConnectionClosed:
            return

    async def _collect_errors(self):
        try:
            while True:
                error = await self.controller.next_error()
                self._errors.append({
                    "time": datetime.now(timezone.utc).isoformat(), **json_value(error),
                })
        except ConnectionClosed:
            return

    async def _collect_events(self, record):
        try:
            while True:
                event = await record.session.next_event()
                async with self._condition:
                    record.sequence += 1
                    record.events.append({"sequence": record.sequence,
                                          "type": type(event).__name__, "data": json_value(event)})
                    if isinstance(event, ClosedEvent):
                        record.closed_at = self._loop.time()
                    self._prune()
                    self._condition.notify_all()
                if isinstance(event, ClosedEvent):
                    return
        except ConnectionClosed:
            return

    def _prune(self):
        closed = sorted(((record.closed_at, id) for id, record in self._records.items()
                         if record.closed_at is not None))
        for _, id in closed[:max(0, len(closed) - self.max_closed_sessions)]:
            del self._records[id]

    def _record(self, session_id):
        if not isinstance(session_id, str):
            raise _invalid("session_id must be a string")
        if session_id not in self._records:
            raise RemoteError(
                -32001, "Unknown or expired session",
                {"type": "UnknownSession", "session_id": session_id},
            )
        return self._records[session_id]

    def _summary(self, record):
        session = record.session
        return {"session_id": session.info.id, "state": session.state, "closed": session.closed,
                "claimed": record.claimed, "info": json_value(session.info),
                "execution": session.last_result.to_dict(), "event_cursor": record.sequence,
                "stdin_redirected": session.stdin_redirected,
                "stdin_waiting": session.stdin_waiting,
                "interaction": json_value(session.last_interaction)}

    def health(self):
        """Return API identity, listener settings, live session count, and mappings."""
        return {"status": "ok", "protocol": "dbgpilot/1", "url": self.url,
                "version": __version__,
                "instance_id": self.instance_id,
                "xdebug_host": self.controller.host, "xdebug_port": self.controller.port,
                "live_sessions": sum(
                    not record.session.closed for record in self._records.values()
                ),
                "proxies": json_value(self.controller.proxy_registrations),
                "path_mappings": json_value(self.controller.path_mapper.mappings)}

    def _timeout(self, value=30):
        if (
            isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not 0 <= value <= self.max_wait
        ):
            raise _invalid(f"timeout must be between 0 and {self.max_wait} seconds")
        return value

    def _prune_cancellations(self):
        now = self._loop.time()
        while self._cancelled:
            id, expiry = next(iter(self._cancelled.items()))
            if expiry > now and len(self._cancelled) <= 1024:
                break
            self._cancelled.pop(id)

    def _cancel_request(self, request_id):
        if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
            raise _invalid("request_id must be a string or integer")
        self._prune_cancellations()
        tasks = self._request_ids.get(request_id, set())
        if len(tasks) > 1:
            raise _invalid("Ambiguous request id; use unique IDs for cancellation")
        if asyncio.current_task() in tasks:
            raise _invalid("A request cannot cancel itself")
        # A cancellation may beat the original HTTP request to this event loop.
        # Retain a bounded tombstone so that delayed submission cannot claim PHP.
        self._cancelled.pop(request_id, None)
        self._cancelled[request_id] = self._loop.time() + self.max_wait + 5
        self._prune_cancellations()
        cancelled = any(task.cancel() for task in tuple(tasks))
        return {"request_id": request_id, "cancelled": cancelled, "submission_blocked": True}

    async def _wait_for_session(
        self, *, idekey=None, cookie=None, appid=None, file=None, timeout=30,
    ):
        timeout = self._timeout(timeout)
        filters = {"idekey": idekey, "cookie": cookie, "appid": appid, "file": file}
        if any(value is not None and not isinstance(value, str) for value in filters.values()):
            raise _invalid("Session filters must be strings")
        if file is not None:
            filters["file"] = self.controller.path_mapper.to_remote(file)
        async with asyncio.timeout(timeout), self._condition:
            while True:
                if self._closing:
                    raise ConnectionClosed("Server closed")
                for record in self._records.values():
                    if record.claimed or record.session.closed:
                        continue
                    if all(
                        value is None or getattr(record.session.info, key) == value
                        for key, value in filters.items()
                    ):
                        record.claimed = True
                        return self._summary(record)
                await self._condition.wait()

    async def _events(self, record, *, after=0, timeout=30, limit=100):
        timeout = self._timeout(timeout)
        if isinstance(after, bool) or not isinstance(after, int) or after < 0:
            raise _invalid("after must be a nonnegative event cursor")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise _invalid("limit must be between 1 and 1000")
        async with self._condition:
            if after > record.sequence:
                raise _invalid("Event cursor is ahead of this session")
            try:
                async with asyncio.timeout(timeout):
                    while (
                        after == record.sequence and record.closed_at is None
                        and not self._closing
                    ):
                        await self._condition.wait()
            except TimeoutError:
                pass
            oldest = record.events[0]["sequence"] if record.events else record.sequence + 1
            if after < oldest - 1:
                raise RemoteError(-32008, "Event history expired", {
                    "type": "EventHistoryLost", "oldest_cursor": oldest - 1,
                    "latest_cursor": record.sequence,
                })
            events = [event for event in record.events if event["sequence"] > after][:limit]
            return {"events": events, "cursor": events[-1]["sequence"] if events else after,
                    "closed": record.closed_at is not None, "oldest_cursor": oldest - 1}

    def _validate_params(self, params):
        for name in ("variables", "expressions"):
            if name in params and (not isinstance(params[name], list) or len(params[name]) > 256
                                   or any(not isinstance(item, str) for item in params[name])):
                raise _invalid(f"{name} must be an array of at most 256 strings")
        for name in (
            "depth", "context", "page", "line", "max_pages", "max_data",
            "hit_value", "begin", "end", "mode",
        ):
            value = params.get(name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise _invalid(f"{name} must be a nonnegative integer")
        for name in (
            "file", "name", "kind", "function", "exception", "state",
            "hit_condition", "stream", "id", "key", "address",
        ):
            value = params.get(name)
            if value is not None and not isinstance(value, str):
                raise _invalid(f"{name} must be a string")
        if "temporary" in params and not isinstance(params["temporary"], bool):
            raise _invalid("temporary must be a boolean")
        if "timeout" in params:
            self._timeout(params["timeout"])

    async def _invoke(self, method, params):
        if self._closing:
            raise ConnectionClosed("Server closed")
        if method == "health":
            if params:
                raise _invalid("health takes no parameters")
            return self.health()
        if method == "sessions":
            if params:
                raise _invalid("sessions takes no parameters")
            return [self._summary(record) for record in self._records.values()]
        if method == "errors":
            if params:
                raise _invalid("errors takes no parameters")
            return list(self._errors)
        if method == "paths.mappings":
            if params:
                raise _invalid("paths.mappings takes no parameters")
            return self.controller.path_mapper.mappings
        if method in {"paths.to_remote", "paths.to_local"}:
            if set(params) != {"path"} or not isinstance(params["path"], str):
                raise _invalid(f"{method} requires a path string")
            target = getattr(self.controller.path_mapper, method.removeprefix("paths."))
            return target(params["path"])
        if method == "proxy.registrations":
            if params:
                raise _invalid("proxy.registrations takes no parameters")
            return self.controller.proxy_registrations
        if method in {"proxy.register", "proxy.unregister"}:
            self._validate_params(params)
            target = (
                self.controller.register_proxy if method == "proxy.register"
                else self.controller.unregister_proxy
            )
            inspect.signature(target).bind(**params)
            return await target(**params)
        if method == "cancel_request":
            if set(params) != {"request_id"}:
                raise _invalid("cancel_request requires only request_id")
            return self._cancel_request(params["request_id"])
        if method == "wait_for_session":
            inspect.signature(self._wait_for_session).bind(**params)
            return await self._wait_for_session(**params)
        if not method.startswith("session."):
            raise RemoteError(-32601, "Unknown method", {"type": "MethodNotFound"})
        name = method.removeprefix("session.")
        if name not in SESSION_METHODS | {"info", "events", "close", "forget", "break_and_return"}:
            raise RemoteError(-32601, "Unknown method", {"type": "MethodNotFound"})
        params = dict(params)
        record = self._record(params.pop("session_id", None))
        session = record.session
        if name == "events":
            inspect.signature(self._events).bind(record, **params)
            return await self._events(record, **params)
        if name in {"info", "close", "forget"}:
            if params:
                raise _invalid(f"session.{name} takes only session_id")
            if name == "info":
                return {**self._summary(record), "capabilities": json_value(session.capabilities),
                        "type_map": json_value(session.type_map),
                        "breakpoints": json_value(session.known_breakpoints),
                        "spawnpoints": json_value(session.known_spawnpoints)}
            if name == "close":
                await session.aclose()
                return self._summary(record)
            if not session.closed:
                raise SessionStateError("Close a session before forgetting it")
            del self._records[session.info.id]
            return {"session_id": session.info.id, "forgotten": True}
        if session.closed:
            raise ConnectionClosed("Session closed")
        self._validate_params(params)
        if name in {"property_set", "set_value"}:
            key = "expression" if name == "property_set" else "value"
            if key in params:
                params[key] = binary_value(params[key])
        if name in {"stdin", "send_stdin"} and "data" in params:
            params["data"] = binary_value(params["data"])
        if name == "interact" and "code" in params:
            params["code"] = binary_value(params["code"])
        if name in {"expr", "exec"}:
            key = "expression" if name == "expr" else "code"
            if key in params:
                params[key] = binary_value(params[key])
        if name in EXECUTION_METHODS:
            params.setdefault("timeout", 30)
        target = (
            partial(self._break_and_return, session) if name == "break_and_return"
            else getattr(session, name)
        )
        inspect.signature(target).bind(**params)
        if name in {"interrupt", "status"}:
            response = await target(**params)
            return {"success": response.get("success") == "1"} if name == "interrupt" else response
        if name in {"stdin", "set_stdin", "send_stdin"}:
            return await target(**params)
        if record.lock.locked():
            raise SessionStateError("Another operation is in progress for this session")
        async with record.lock:
            return await target(**params)

    async def _break_and_return(
        self, session, *, variables=(), expressions=(), depth=0, context=0, timeout=30,
    ):
        await session.run_until_break(timeout=timeout)
        return await session.snapshot(
            variables, expressions=expressions, depth=depth, context=context,
        )

    async def rpc(self, request):
        """Dispatch a JSON-RPC request and return its result or structured error.

        Track the request ID for cancellation and bound execution by the server's
        maximum wait. Shutdown cancellation propagates to the caller.
        """
        task = asyncio.current_task()
        self._requests.add(task)
        request_id = None
        registered = False
        try:
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise RemoteError(-32600, "Expected a JSON-RPC 2.0 request object")
            request_id = request.get("id")
            if isinstance(request_id, bool) or not isinstance(request_id, (str, int)):
                request_id = None
                raise RemoteError(-32600, "A string or integer request id is required")
            method, params = request.get("method"), request.get("params", {})
            if not isinstance(method, str) or not isinstance(params, dict):
                raise RemoteError(-32600, "method must be a string and params an object")
            self._prune_cancellations()
            if request_id in self._cancelled:
                raise RemoteError(-32010, "Request cancelled", {"type": "RequestCancelled"})
            self._request_ids.setdefault(request_id, set()).add(task)
            registered = True
            async with asyncio.timeout(self.max_wait + 5):
                result = await self._invoke(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": json_value(result)}
        except asyncio.CancelledError:
            if self._closing:
                raise
            return _error_response(
                request_id,
                RemoteError(-32010, "Request cancelled", {"type": "RequestCancelled"}),
            )
        except Exception as error:
            if not isinstance(error, (
                RemoteError, ValueError, TypeError, TimeoutError, SessionStateError,
                CommandError, PathMappingError, ProtocolError, ProxyError,
                ConnectionClosed, ExecutionFinished,
            )):
                LOGGER.exception("RPC failed")
                error = RemoteError(-32603, "Internal server error", {"type": "InternalError"})
            return _error_response(request_id, error)
        finally:
            self._requests.discard(task)
            if registered:
                tasks = self._request_ids[request_id]
                tasks.discard(task)
                if not tasks:
                    del self._request_ids[request_id]

    async def aclose(self):
        """Cancel active requests and close sessions, listeners, and HTTP connections."""
        if self._closing:
            return
        self._closing = True
        async with self._condition:
            self._condition.notify_all()
        requests = tuple(self._requests)
        for task in requests:
            task.cancel()
        await asyncio.gather(*requests, return_exceptions=True)
        if self._http is not None:
            if self._thread is not None and self._thread.is_alive():
                await asyncio.to_thread(self._http.shutdown)
            self._http.close_connections()
        await self.controller.aclose()
        background = tuple(self._background)
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        if self._http is not None:
            self._http.server_close()
        if self._thread is not None and self._thread.ident is not None:
            await asyncio.to_thread(self._thread.join, 1)


class _Handler(BaseHTTPRequestHandler):
    # Bound by the per-server Handler subclass before requests are handled.
    pilot: Server
    protocol_version = "HTTP/1.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, format, *args):
        LOGGER.debug(format, *args)

    def _send(self, status, value):
        body = json.dumps(value, ensure_ascii=True, allow_nan=False).encode("utf-8")
        self.close_connection = True
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (OSError, TimeoutError):
            # Disconnecting an HTTP client never detaches its PHP session.
            pass

    def _authorize(self):
        if self.pilot.token:
            actual = self.headers.get("Authorization", "")
            if not hmac.compare_digest(
                actual.encode("utf-8"), ("Bearer " + self.pilot.token).encode("utf-8"),
            ):
                self._send(401, _error_response(None, RemoteError(-32009, "Unauthorized")))
                return False
        else:
            try:
                host = urlsplit("http://" + self.headers.get("Host", "")).hostname
            except ValueError:
                host = None
            if host not in {"127.0.0.1", "localhost", "::1", self.pilot.host}:
                self._send(403, _error_response(None, RemoteError(-32009, "Invalid Host header")))
                return False
        if self.headers.get("Origin"):
            self._send(403, _error_response(
                None, RemoteError(-32009, "Browser-origin requests are not accepted"),
            ))
            return False
        return True

    def do_GET(self):
        """Authorize and serve the health endpoint, rejecting other paths."""
        if not self._authorize():
            return
        if self.path != "/health":
            self._send(404, _error_response(None, RemoteError(-32601, "Unknown endpoint")))
            return
        self._dispatch({"jsonrpc": "2.0", "id": "health", "method": "health"}, plain=True)

    def do_POST(self):
        """Authorize, validate, and dispatch a bounded JSON request to the RPC endpoint."""
        if not self._authorize():
            return
        if self.path != "/rpc":
            self._send(404, _error_response(None, RemoteError(-32601, "Unknown endpoint")))
            return
        if self.headers.get_content_type() != "application/json":
            self._send(415, _error_response(
                None, _invalid("Content-Type must be application/json"),
            ))
            return
        lengths = self.headers.get_all("Content-Length", [])
        if self.headers.get("Transfer-Encoding") or len(lengths) != 1 or not lengths[0].isdigit():
            self._send(400, _error_response(
                None, _invalid("One Content-Length and no Transfer-Encoding are required"),
            ))
            return
        length = int(lengths[0])
        if length > self.pilot.max_request_bytes:
            self._send(413, _error_response(None, _invalid("Request body exceeds the limit")))
            return
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise ValueError("Incomplete body")
            request = json.loads(body.decode("utf-8"), parse_constant=_invalid_constant)
        except (ValueError, OSError, RecursionError) as error:
            self._send(400, _error_response(
                None, RemoteError(-32700, f"Invalid JSON request: {error}"),
            ))
            return
        self._dispatch(request)

    def _dispatch(self, request, *, plain=False):
        coroutine = self.pilot.rpc(request)
        try:
            future = asyncio.run_coroutine_threadsafe(coroutine, self.pilot._loop)
        except RuntimeError:
            coroutine.close()
            self._send(503, _error_response(None, ConnectionClosed("Server closed")))
            return
        while True:
            try:
                response = future.result(timeout=0.05)
                break
            except FutureTimeoutError:
                try:
                    readable, _, _ = select.select([self.connection], [], [], 0)
                    disconnected = (
                        bool(readable) and self.connection.recv(1, socket.MSG_PEEK) == b""
                    )
                except (OSError, ValueError):
                    disconnected = True
                if disconnected:
                    future.cancel()
                    return
            except FutureCancelledError:
                self._send(503, _error_response(None, ConnectionClosed("Server closed")))
                return
        self._send(200, response.get("result", response) if plain else response)
