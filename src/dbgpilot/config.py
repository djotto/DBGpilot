"""Deliberately loaded project settings shared by setup and the CLI."""

from dataclasses import dataclass, field, replace

from ._settings import ProjectSettings, read_config
from .paths import PathMapper


@dataclass(frozen=True)
class SetupConfig(ProjectSettings):
    """Validated connection, process startup, and source path mapping settings."""

    path_mapper: PathMapper = field(default_factory=PathMapper, repr=False)

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.path_mapper, PathMapper):
            raise ValueError("path_mapper must be a PathMapper")

    def with_overrides(self, **values):
        """Return a validated copy with the supplied settings replaced."""
        return replace(self, **values)

    @classmethod
    def from_file(cls, path, **overrides):
        """Load TOML settings, resolve paths relative to the file, and apply overrides."""
        path, values, mappings = read_config(path, token_overridden="token" in overrides)
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
