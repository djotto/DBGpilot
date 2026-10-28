"""A listener and owner for independent incoming PHP debugging sessions."""

import asyncio
from contextlib import suppress

from .errors import ConnectionClosed, SessionStateError
from .session import Session, wait_queue
from .proxy import ProxyClient
from .paths import PathMapper
from .queues import RetainedQueue

DEFAULT_FEATURES = {
    "extended_properties": 1,
    "max_depth": 1,
    "max_children": 32,
    "max_data": 1024,
    "multiple_sessions": 1,
    "notify_ok": 1,
    "resolved_breakpoints": 1,
    "breakpoint_details": 1,
}


class Controller:
    """Accept DBGp connections and own their sessions and proxy registrations.

    Incoming sessions complete the handshake before becoming available through
    wait_for_session(). Closing the controller closes its sessions and listener.
    """

    def __init__(
        self, host="127.0.0.1", port=9003, *, command_timeout=5.0,
        execution_timeout=None, handshake_timeout=5.0, max_packet_size=16 * 1024 * 1024,
        event_queue_size=1024, features=None, eval_depth_supported=None, allow_detach_eof=False,
        path_mappings=(), max_pending_commands=1024, error_queue_size=50, max_sessions=256,
    ):
        if max_packet_size < 1 or event_queue_size < 1:
            raise ValueError("Packet and event queue limits must be positive")
        if any(
            type(value) is not int or value < 1
            for value in (max_pending_commands, error_queue_size, max_sessions)
        ):
            raise ValueError("Command, error queue and session limits must be positive integers")
        self.max_sessions = max_sessions
        self.host = host
        self.port = port
        self.features = dict(DEFAULT_FEATURES if features is None else features)
        self.path_mapper = (
            path_mappings if isinstance(path_mappings, PathMapper) else PathMapper(path_mappings)
        )
        self._options = dict(
            command_timeout=command_timeout, execution_timeout=execution_timeout,
            handshake_timeout=handshake_timeout, max_packet_size=max_packet_size,
            event_queue_size=event_queue_size,
            eval_depth_supported=eval_depth_supported,
            allow_detach_eof=allow_detach_eof,
            path_mappings=self.path_mapper,
            max_pending_commands=max_pending_commands,
        )
        self._server = None
        self._sessions = []
        self._connections = set()
        self._handlers = set()
        self._ready = RetainedQueue()
        self._errors = RetainedQueue(maxsize=error_queue_size)
        self._closed = asyncio.Event()
        self._proxies = {}
        self._proxy_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    @property
    def proxy_registrations(self):
        return tuple(result for _, result in self._proxies.values())

    async def register_proxy(self, host="127.0.0.1", port=9001, *, idekey,
                             listen_port=None, multiple_sessions=True, timeout=5):
        await self.start()
        client = ProxyClient(host, port, timeout=timeout)
        async with asyncio.timeout(timeout), self._proxy_lock:
            if self._closed.is_set():
                raise ConnectionClosed("Controller closed")
            key = (host, port, idekey)
            if key in self._proxies:
                raise ValueError("This controller already owns that proxy registration")
            result = await client.register(self.port if listen_port is None else listen_port,
                                           idekey, multiple_sessions=multiple_sessions)
            self._proxies[key] = (client, result)
            for session in self.sessions:
                if session.info.idekey == idekey:
                    session.allow_detach_eof = True
            if self._closed.is_set():
                raise ConnectionClosed("Controller closed during proxy registration")
            return result

    async def unregister_proxy(self, host="127.0.0.1", port=9001, *, idekey, timeout=5):
        client = ProxyClient(host, port, timeout=timeout)
        async with asyncio.timeout(timeout), self._proxy_lock:
            if self._closed.is_set():
                raise ConnectionClosed("Controller closed")
            result = await client.unregister(idekey)
            self._proxies.pop((host, port, idekey), None)
            return result

    @property
    def sessions(self) -> tuple[Session, ...]:
        self._sessions = [session for session in self._sessions if not session.closed]
        return tuple(self._sessions)

    async def start(self):
        async with self._start_lock:
            if self._closed.is_set():
                raise ConnectionClosed("A closed controller cannot be restarted")
            if self._server is None:
                listener = await asyncio.start_server(self._connected, self.host, self.port)
                if self._closed.is_set():
                    listener.close()
                    await listener.wait_closed()
                    raise ConnectionClosed("Controller closed during startup")
                self._server = listener
                self.port = self._server.sockets[0].getsockname()[1]
            return self

    async def __aenter__(self):
        return await self.start()

    async def __aexit__(self, *exc):
        await self.aclose()

    def _connected(self, reader, writer):
        if self._closed.is_set():
            writer.close()
            return
        if len(self._connections) + len(self.sessions) >= self.max_sessions:
            writer.close()
            self._report_error(SessionStateError(
                "Controller session limit reached; new connection rejected",
            ))
            return
        self._connections.add(writer)
        task = asyncio.create_task(self._accept(reader, writer), name="dbgpilot-handshake")
        self._handlers.add(task)
        task.add_done_callback(self._handlers.discard)

    async def _accept(self, reader, writer):
        try:
            session = await Session.connect(reader, writer, features=self.features, **self._options)
            if any(result.idekey == session.info.idekey for _, result in self._proxies.values()):
                session.allow_detach_eof = True
            if self._closed.is_set():
                await session.aclose()
            else:
                self._sessions.append(session)
                self._ready.put_nowait(session)
                session._reader_task.add_done_callback(lambda task: self._forget_session(session))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._report_error(error)
        finally:
            self._connections.discard(writer)

    def _forget_session(self, session):
        if session in self._sessions:
            self._sessions.remove(session)
        self._ready.discard(session)

    def _report_error(self, error):
        if self._errors.full():
            self._errors.get_nowait()
        self._errors.put_nowait(error)

    async def wait_for_session(self, *, timeout=None) -> Session:
        async with asyncio.timeout(timeout):
            while True:
                session = await wait_queue(
                    self._ready, self._closed, None, ConnectionClosed("Controller closed"),
                )
                if not session.closed:
                    return session

    async def next_error(self, *, timeout=None) -> Exception:
        """Retrieve a rejected connection's handshake/initialization error."""
        return await wait_queue(
            self._errors, self._closed, timeout, ConnectionClosed("Controller closed"),
        )

    async def aclose(self):
        if self._closed.is_set():
            return
        self._closed.set()
        if self._server is not None:
            self._server.close()
        async with self._proxy_lock:
            async def unregister(key, client):
                try:
                    await ProxyClient(client.host, client.port, timeout=1).unregister(key[2])
                    self._proxies.pop(key, None)
                except Exception as error:
                    self._report_error(error)
            await asyncio.gather(*(
                unregister(key, client) for key, (client, _) in tuple(self._proxies.items())
            ))
        await asyncio.gather(*(session.aclose() for session in self.sessions))
        for writer in tuple(self._connections):
            writer.close()
        for task in tuple(self._handlers):
            task.cancel()
        await asyncio.gather(*self._handlers, return_exceptions=True)
        for writer in tuple(self._connections):
            with suppress(OSError):
                await writer.wait_closed()
        # Python 3.13's Server.wait_closed also waits for accepted transports.
        if self._server is not None:
            await self._server.wait_closed()
