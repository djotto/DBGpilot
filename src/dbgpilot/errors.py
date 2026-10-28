"""Errors reported by DBGpilot and the remote debugging engine."""


class DBGpilotError(Exception):
    """Base class for controller errors."""


class ProtocolError(DBGpilotError):
    """The peer sent an invalid or unexpected protocol message."""


class PathMappingError(DBGpilotError):
    """A path cannot be mapped unambiguously between local and engine roots."""

    def __init__(self, path, direction, reason):
        self.path, self.direction, self.reason = str(path), direction, reason
        super().__init__(f"Cannot map {self.path!r} {direction}: {reason}")


class ProxyError(DBGpilotError):
    """A proxy-reported error; its application-defined code stays opaque."""

    def __init__(self, message, *, code=None, command=None, attributes=None, xml=None):
        self.code, self.command = code, command
        self.message = message
        self.attributes, self.xml = dict(attributes or {}), xml
        super().__init__(message)


class ConnectionClosed(DBGpilotError):
    """The debugging connection is no longer available."""

    def __init__(self, message="Session closed", *, clean_eof=False):
        self.clean_eof = clean_eof
        super().__init__(message)


class SessionStateError(DBGpilotError):
    """An operation cannot be performed in the session's current state."""


class CommandError(DBGpilotError):
    """An engine-rejected DBGp command with its error code and response details."""

    def __init__(self, command: str, code: int, message: str, *, attributes=None, xml=None):
        self.command = command
        self.code = code
        self.message = message
        self.attributes = dict(attributes or {})
        self.xml = xml
        super().__init__(f"{command}: [{code}] {message}")


class ExecutionFinished(DBGpilotError):
    """Execution completed without reaching another breakpoint."""

    def __init__(self, result):
        self.result = result
        super().__init__(f"Execution reached {result.status!r} instead of a breakpoint")
