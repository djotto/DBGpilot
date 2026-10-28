"""Deliberately loaded project settings shared by setup and the CLI."""

from dataclasses import dataclass, field, replace
import math
import os
from pathlib import Path
import sys
import tomllib

from .client import Client
from .paths import PathMapper


@dataclass(frozen=True)
class SetupConfig:
    """Validated connection, process startup, and source path mapping settings."""

    url: str = "http://127.0.0.1:9004"
    token: str | None = field(default=None, repr=False)
    request_timeout: float = 35
    launch: bool = False
    startup_timeout: float = 10
    python: str = sys.executable
    working_directory: str | None = None
    host: str = "127.0.0.1"
    port: int = 9004
    xdebug_host: str = "127.0.0.1"
    xdebug_port: int = 9003
    path_mapper: PathMapper = field(default_factory=PathMapper, repr=False)

    def __post_init__(self):
        Client(self.url, token=self.token)
        if not isinstance(self.launch, bool):
            raise ValueError("startup.launch must be a boolean")
        for name in ("request_timeout", "startup_timeout"):
            value = getattr(self, name)
            if (
                isinstance(value, bool) or not isinstance(value, (float, int))
                or not math.isfinite(value) or value <= 0
            ):
                raise ValueError(f"{name} must be a finite positive number")
        for name in ("port", "xdebug_port"):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 65535:
                raise ValueError(f"{name} must be between 0 and 65535")
        for name in ("host", "xdebug_host", "python"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"{name} must be a nonempty string")
        if self.working_directory is not None and not isinstance(self.working_directory, str):
            raise ValueError("working_directory must be a path string")
        if not isinstance(self.path_mapper, PathMapper):
            raise ValueError("path_mapper must be a PathMapper")

    def with_overrides(self, **values):
        """Return a validated copy with the supplied settings replaced."""
        return replace(self, **values)

    @classmethod
    def from_file(cls, path, **overrides):
        """Load TOML settings, resolve paths relative to the file, and apply overrides."""
        path = Path(path).absolute()
        with path.open("rb") as source:
            data = tomllib.load(source)
        if set(data) - {"connection", "startup", "listener", "path_mappings"}:
            raise ValueError("Unknown DBGpilot configuration key")
        values = {}
        sections = {
            "connection": {"url": "url", "timeout": "request_timeout", "token_env": "token_env"},
            "startup": {"launch": "launch", "timeout": "startup_timeout", "python": "python",
                        "working_directory": "working_directory"},
            "listener": {name: name for name in ("host", "port", "xdebug_host", "xdebug_port")},
        }
        for name, keys in sections.items():
            section = data.get(name, {})
            if not isinstance(section, dict) or set(section) - keys.keys():
                raise ValueError(f"Invalid DBGpilot {name} settings")
            values.update({keys[key]: value for key, value in section.items()})
        if "token_env" in values:
            name = values.pop("token_env")
            if not isinstance(name, str) or not name:
                raise ValueError("connection.token_env must name an environment variable")
            if "token" not in overrides:
                if name not in os.environ:
                    raise ValueError(
                        f"Required authentication environment variable {name} is unset",
                    )
                values["token"] = os.environ[name]
        for key in ("working_directory", "python"):
            if key in values:
                value = values[key]
                if not isinstance(value, str):
                    raise ValueError(f"{key} must be a path string")
                if key == "working_directory" or "/" in value or "\\" in value:
                    values[key] = str((path.parent / value).resolve())
        mappings = data.get("path_mappings", [])
        if not isinstance(mappings, list) or any(not isinstance(entry, dict) for entry in mappings):
            raise ValueError("path_mappings must be an array of tables")
        values["path_mapper"] = PathMapper(mappings, base_dir=path.parent)
        return cls(**(values | overrides))


def load_config(config=None, *, discover=False, **overrides):
    """No ambient file access unless discovery or an explicit file is requested."""
    if isinstance(config, SetupConfig):
        return config.with_overrides(**overrides) if overrides else config
    if config is False:
        return SetupConfig(**overrides)
    if config is None and discover:
        config = PathMapper.find_config()
    return (
        SetupConfig.from_file(config, **overrides)
        if config is not None else SetupConfig(**overrides)
    )
