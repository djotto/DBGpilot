"""DBGpilot: asynchronous, persistent control of Xdebug sessions."""

from ._version import __version__

from .controller import Controller
from .errors import (
    DBGpilotError, CommandError, ConnectionClosed, ExecutionFinished,
    PathMappingError, ProtocolError, ProxyError, SessionStateError,
)
from .models import (
    Breakpoint, ClosedEvent, ExecutionResult, Feature, Frame, NotificationEvent,
    NotificationMessage, Property, PropertyValue, SessionInfo, Snapshot, Spawnpoint, StoppedEvent,
    StreamEvent, TypeMapping, InteractiveResult, InteractiveEvent, ProxyErrorEvent, ProxyRegistration,
)
from .session import Session
from .client import Client, RemoteRequest, RemoteSession
from .server import Server
from .wire import RemoteError
from .playwright import BreakpointSpec, PausedBrowser, PlaywrightDebugger
from .proxy import ProxyClient
from .paths import PathMapper, PathMapping
from .config import SetupConfig
from .setup import DebuggerSetup, SetupError

__all__ = [
    "__version__",
    "Controller", "Session", "Breakpoint", "ClosedEvent", "ExecutionResult", "Feature",
    "Frame", "NotificationEvent", "Property", "SessionInfo", "Snapshot", "StoppedEvent",
    "StreamEvent", "DBGpilotError", "CommandError", "ConnectionClosed", "ExecutionFinished",
    "ProtocolError", "SessionStateError",
    "NotificationMessage", "PropertyValue", "TypeMapping",
    "Client", "RemoteSession", "Server", "RemoteError",
    "RemoteRequest",
    "BreakpointSpec", "PausedBrowser", "PlaywrightDebugger",
    "ProxyClient", "ProxyRegistration", "ProxyError", "ProxyErrorEvent",
    "InteractiveResult", "InteractiveEvent",
    "Spawnpoint",
    "PathMapper", "PathMapping", "PathMappingError",
    "SetupConfig", "DebuggerSetup", "SetupError",
]
