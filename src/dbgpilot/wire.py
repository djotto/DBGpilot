"""JSON values and errors shared by the local server and its client."""

import base64
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
import math

from .errors import CommandError, DBGpilotError, ExecutionFinished, PathMappingError, ProxyError


class RemoteError(DBGpilotError):
    """A structured error returned by the DBGpilot server."""

    def __init__(self, code, message, data=None):
        self.code, self.message, self.data = code, message, data or {}
        super().__init__(message)

    def to_dict(self):
        """Return the JSON-RPC error code, message, and structured data."""
        return {"code": self.code, "message": self.message, "data": self.data}


def json_value(value):
    """Recursively convert results to JSON-safe values, preserving binary data as base64."""
    if isinstance(value, BaseException):
        result = {"type": type(value).__name__, "message": str(value)}
        if isinstance(value, (CommandError, ProxyError)):
            result.update(command=value.command, code=value.code,
                          attributes=value.attributes, xml=value.xml)
        if isinstance(value, ExecutionFinished):
            result["result"] = value.result.to_dict()
        if isinstance(value, PathMappingError):
            result.update(path=value.path, direction=value.direction, reason=value.reason)
        return result
    if isinstance(value, bytes):
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if hasattr(value, "to_dict"):
        return json_value(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return {field.name: json_value(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value


def binary_value(value):
    """Decode the explicit binary argument envelope, leaving scalars alone."""
    if isinstance(value, dict):
        if set(value) != {"encoding", "data"} or value["encoding"] != "base64":
            raise ValueError("Binary values require encoding='base64' and a data string")
        if not isinstance(value["data"], str):
            raise ValueError("Binary data must be a base64 string")
        try:
            return base64.b64decode(value["data"], validate=True)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Invalid base64 argument") from error
    return value
