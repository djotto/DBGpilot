"""Lexical, host-independent directory mappings; no remote filesystem access."""

from dataclasses import dataclass
import ntpath
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
import posixpath
import re
from urllib.parse import quote, unquote, urlsplit

from .errors import PathMappingError


def _text(path):
    if not isinstance(path, (str, PurePath)) or not str(path) or "\0" in str(path):
        raise ValueError("Paths must be nonempty text without NUL characters")
    return str(path)


def _local(path, base):
    text = _text(path)
    windows = (
        isinstance(path, PureWindowsPath) or bool(re.match(r"^[A-Za-z]:", text))
        or text.startswith("\\\\")
    )
    if windows:
        result = PureWindowsPath(ntpath.normpath(text))
        if not result.is_absolute():
            raise ValueError("Windows paths must include an absolute drive or UNC share")
        return result
    if not text.startswith("/"):
        text = str(base / text)
    return PurePosixPath(posixpath.normpath(text))


@dataclass(frozen=True)
class _Remote:
    host: str
    parts: tuple[str, ...]
    windows: bool

    @property
    def uri(self):
        """Return an escaped absolute file URI for this normalized engine path."""
        path = "/" + "/".join(self.parts)
        if self.windows and len(self.parts) == 1:
            path += "/"
        return "file://" + self.host + quote(path, safe="/:", errors="surrogateescape")


def _remote(uri):
    text = _text(uri)
    if re.search(r"%(?![0-9a-fA-F]{2})", text):
        raise ValueError("File URI contains an invalid percent escape")
    parsed = urlsplit(text)
    if (
        parsed.scheme != "file" or not parsed.path.startswith("/") or parsed.query
        or parsed.fragment or parsed.username is not None or parsed.password is not None
        or parsed.port is not None or parsed.netloc.endswith(":")
    ):
        raise ValueError(
            "Remote roots and paths must be absolute file:// URIs without query/fragment/userinfo",
        )
    host = "" if parsed.netloc.casefold() == "localhost" else parsed.netloc.casefold()
    decoded = unquote(parsed.path, errors="surrogateescape")
    if "\0" in decoded:
        raise ValueError("File URI contains a NUL character")
    windows = bool(re.match(r"^/[A-Za-z]:/", decoded + "/"))
    if windows:
        path = PureWindowsPath(ntpath.normpath(decoded[1:]))
        parts = (path.drive, *path.parts[1:])
    else:
        # Normalize before prefix matching, including percent-encoded '..'.
        parts = PurePosixPath(posixpath.normpath("/" + decoded.lstrip("/"))).parts[1:]
    return _Remote(host, tuple(parts), windows)


@dataclass(frozen=True)
class PathMapping:
    """A local directory and engine URI root with an optional remote case policy."""

    local: str
    remote: str
    remote_case_sensitive: bool | None = None

    def to_dict(self):
        """Return a copy of the directory roots and remote case policy."""
        return vars(self).copy()


@dataclass(frozen=True)
class _Rule:
    mapping: PathMapping
    local: PurePath
    remote: _Remote
    case_sensitive: bool

    def remote_key(self, parts):
        """Return path components normalized according to the rule's remote case policy."""
        return tuple(parts) if self.case_sensitive else tuple(part.casefold() for part in parts)


class PathMapper:
    """Use the longest directory prefix; preserve explicit outbound file/dbgp URIs.

    Relative local paths use base_dir. Roots are lexical: symlinks are not
    followed, paths need not exist, and Windows roots work on POSIX hosts.
    """

    def __init__(self, mappings=(), *, base_dir=None):
        self.base_dir = Path.cwd() if base_dir is None else Path(base_dir).absolute()
        rules = []
        for entry in mappings:
            if isinstance(entry, dict):
                try:
                    entry = PathMapping(**entry)
                except TypeError as error:
                    raise ValueError(
                        "Each mapping requires local and remote, "
                        "and optionally remote_case_sensitive"
                    ) from error
            if not isinstance(entry, PathMapping):
                raise TypeError(
                    "Mappings must be PathMapping records or configuration dictionaries",
                )
            if entry.remote_case_sensitive is not None and not isinstance(
                entry.remote_case_sensitive, bool,
            ):
                raise ValueError("remote_case_sensitive must be a boolean")
            local, remote = _local(entry.local, self.base_dir), _remote(entry.remote)
            case_sensitive = (
                not remote.windows if entry.remote_case_sensitive is None
                else entry.remote_case_sensitive
            )
            mapping = PathMapping(str(local), remote.uri, entry.remote_case_sensitive)
            rule = _Rule(mapping, local, remote, case_sensitive)
            for other in rules:
                if local == other.local:
                    raise ValueError(f"Duplicate local mapping root: {local}")
                if remote.host == other.remote.host and remote.windows == other.remote.windows:
                    # Mixed case policies for overlapping roots are ambiguous.
                    folded, other_folded = (
                        tuple(p.casefold() for p in remote.parts),
                        tuple(p.casefold() for p in other.remote.parts),
                    )
                    overlap = (
                        folded[:len(other_folded)] == other_folded
                        or other_folded[:len(folded)] == folded
                    )
                    if overlap and case_sensitive != other.case_sensitive:
                        raise ValueError("Overlapping remote roots must use the same case policy")
                    if rule.remote_key(remote.parts) == other.remote_key(other.remote.parts):
                        raise ValueError(f"Duplicate remote mapping root: {remote.uri}")
            rules.append(rule)
        self._rules = tuple(rules)

    @property
    def mappings(self):
        """Return the normalized mapping records in configuration order."""
        return tuple(rule.mapping for rule in self._rules)

    def with_overrides(self, mappings, *, base_dir=None):
        """Replace mappings sharing an override's local root and retain all other roots."""
        overrides = PathMapper(mappings, base_dir=base_dir)
        retained = [rule.mapping for rule in self._rules
                    if not any(rule.local == other.local for other in overrides._rules)]
        return PathMapper([*retained, *overrides.mappings], base_dir=self.base_dir)

    @classmethod
    def from_file(cls, path):
        """Load source path mappings from a DBGpilot TOML configuration file."""
        from .config import SetupConfig

        return SetupConfig.from_file(path).path_mapper

    @staticmethod
    def find_config(directory=None):
        """Find the nearest dbgpilot.toml in a directory or its ancestors, or return None."""
        directory = Path.cwd() if directory is None else Path(directory).absolute()
        for parent in (directory, *directory.parents):
            candidate = parent / "dbgpilot.toml"
            if candidate.is_file():
                return candidate
        return None

    def _outbound(self, path):
        matches = []
        for rule in self._rules:
            if type(path) is type(rule.local) and path.is_relative_to(rule.local):
                matches.append((len(rule.local.parts), rule, path.relative_to(rule.local).parts))
        if not matches:
            raise PathMappingError(
                path, "to_remote",
                "no local root matches; use an explicit engine URI for remote files",
            )
        _, rule, suffix = max(matches, key=lambda item: item[0])
        if rule.remote.windows and any("\\" in part or ":" in part for part in suffix):
            raise PathMappingError(
                path, "to_remote",
                "a path component cannot be represented on the remote Windows filesystem",
            )
        return _Remote(rule.remote.host, rule.remote.parts + tuple(suffix), rule.remote.windows)

    def _inbound(self, path):
        matches = []
        for rule in self._rules:
            root = rule.remote
            if (
                root.host == path.host and root.windows == path.windows
                and rule.remote_key(path.parts[:len(root.parts)]) == rule.remote_key(root.parts)
            ):
                matches.append((len(root.parts), rule, path.parts[len(root.parts):]))
        if not matches:
            raise PathMappingError(path.uri, "to_local", "no remote root matches")
        _, rule, suffix = max(matches, key=lambda item: item[0])
        if isinstance(rule.local, PureWindowsPath) and any(
            "\\" in part or ":" in part for part in suffix
        ):
            raise PathMappingError(
                path.uri, "to_local",
                "a path component cannot be represented on the local Windows filesystem",
            )
        return rule.local.joinpath(*suffix)

    def to_remote(self, path):
        """Map a local path to an engine URI and verify that the mapping round-trips.

        Preserve explicit file: and dbgp: URIs. With no configured mappings, convert
        the normalized local path directly to an absolute file URI.
        """
        text = _text(path)
        if text.startswith(("file:", "dbgp:")):
            return text
        local = _local(path, self.base_dir)
        if not self._rules:
            return local.as_uri()
        remote = self._outbound(local)
        if self._inbound(remote) != local:
            raise PathMappingError(
                path, "to_remote", "overlapping mappings do not round-trip to the same local file",
            )
        return remote.uri

    def to_local(self, uri):
        """Map an engine file URI to a local path and reject ambiguous round-trips."""
        try:
            remote = _remote(uri)
        except ValueError as error:
            raise PathMappingError(uri, "to_local", str(error)) from error
        local = self._inbound(remote)
        forward = self._outbound(local)
        # URI drive letters are case-insensitive; the rule's full case policy
        # was already used while choosing the inbound mapping.
        rule = max(
            (
                rule for rule in self._rules
                if type(local) is type(rule.local) and local.is_relative_to(rule.local)
            ),
            key=lambda item: len(item.local.parts),
        )
        if (
            forward.host != remote.host
            or rule.remote_key(forward.parts) != rule.remote_key(remote.parts)
        ):
            raise PathMappingError(
                uri, "to_local", "overlapping mappings do not round-trip to the same engine file",
            )
        return str(local)

    def location(self, uri):
        """Best-effort result metadata: preserve engine URIs even on a map miss."""
        if not self._rules or not uri or not uri.startswith("file:"):
            return {"local_file": None, "path_mapping_error": None}
        try:
            return {"local_file": self.to_local(uri), "path_mapping_error": None}
        except PathMappingError as error:
            return {"local_file": None, "path_mapping_error": str(error)}
