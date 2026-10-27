# Local paths and engine file URIs

Path mappings describe corresponding directory roots. The same mapper supports
containers, SSH deployments, Windows workstations, and multiple source mounts.
Configuration supplies the environment's actual relationships; DBGpilot does
not infer them from filenames or read a remote filesystem.

## Project configuration

Create `dbgpilot.toml` in the project:

```toml
[[path_mappings]]
local = "/Users/you/projects/site"
remote = "file:///var/www/html"

[[path_mappings]]
local = "/Users/you/projects/shared"
remote = "file:///opt/shared"
```

`dbgpilot serve` discovers the nearest `dbgpilot.toml` in its working directory
or parents. `--config FILE` chooses an explicit file; `--no-config` disables
discovery. Invalid configuration fails before the server emits readiness.
Each table requires `local` and `remote`; unknown keys are rejected. Relative
local roots are resolved against the configuration file's directory. Relative
paths submitted to the server then use that same directory as their base.

The supplied [example configuration](../dbgpilot.example.toml) maps its project
directory to the included DDEV document root:

```sh
ddev poetry run dbgpilot serve --config dbgpilot.example.toml
```

The **local namespace is configured on the server**. When the server runs inside
DDEV, `local = "."` resolves inside DDEV. To submit host paths from a client to
that server, configure the absolute host root (for example `/Users/you/site` or
`C:\Work\site`) even if that path does not exist in the container. No source
files need to exist on the server at the local path. The remote root must match
the engine's actual file URIs.

CLI mappings can be repeated and override a configured mapping with the same
normalized local root. New roots are added. Conflicting remote roots still fail:

```sh
dbgpilot serve --path-map /Users/you/site file:///var/www/html \
  --path-map /Users/you/shared file:///opt/shared
# Ignore any project configuration:
dbgpilot serve --no-config --path-map /work/site file:///var/www/html
```

CLI relative roots use the server's working directory. These options configure
path translation; Xdebug networking, proxy routing, and mounts are configured
separately. No DDEV-specific path discovery is required by the mapper.

## Python configuration

Library constructors do not read ambient project configuration. Supply roots
explicitly, or load a file:

```python
from dbgpilot import Controller, PathMapper, PathMapping, Server

mapper = PathMapper([
    PathMapping("/Users/you/site", "file:///var/www/html"),
])
# Alternatively: mapper = PathMapper.from_file("dbgpilot.toml")

async with Controller(port=9003, path_mappings=mapper) as controller:
    session = await controller.wait_for_session(timeout=30)
    breakpoint = await session.set_breakpoint("/Users/you/site/src/cart.php", 12)
    await session.run_until_break(timeout=30)
    frames = await session.stack()
    print(frames[0].file)        # file:///var/www/html/src/cart.php
    print(frames[0].local_file)  # /Users/you/site/src/cart.php
    await session.detach()

# A persistent server can take the same mapper or a list of PathMapping records:
server = Server(path_mappings=mapper)
```

Configuration dictionaries with the same fields are also accepted. If supplying
an existing `Controller` to `Server`, configure its mappings on that controller.
All of its sessions share the mapper; clients do not need their own mapping copy.
Mapping configuration is fixed for that controller's lifetime.

## Commands and results

Local file arguments are translated for breakpoint creation, source retrieval,
spawnpoint creation, and the server's `wait_for_session(file=...)` filter. Paths
use the longest matching directory root, with component boundaries: `/work/app`
does not match `/work/application`. Normalization is lexical, and does not follow
symlinks. Add explicit roots for aliases and generated sources where needed.

Explicit outbound `file:` and `dbgp:` URIs pass through unchanged. This lets
callers target remote libraries or virtual files outside the local roots. Raw
`session.command()` also continues to use engine arguments directly. With no
mappings configured, local paths retain the existing absolute-file-URI behaviour.

Results preserve the original engine `file` URI and add:

| Field | Meaning |
| --- | --- |
| `local_file` | Mapped absolute local path, or null |
| `path_mapping_error` | Mapping diagnostic, or null |

These fields appear in session initialization, stack frames (including nested
input frames), execution results and nested breakpoints, breakpoint/spawnpoint
records, and notification messages. Snapshots, inventories, JSON results, and
replayed events retain them. Vendor attributes and raw XML keep the original
engine filenames.

An unmapped engine file still returns its engine URI, with a diagnostic and no
local path. It does not close the session or hide a stack frame. Virtual sources
such as `dbgp:` and `<console>` intentionally have no local mapping or diagnostic.
With mapping disabled, both additional fields are null.

Configured outbound local paths that match no root raise `PathMappingError`
before sending an engine command. Its `path`, `direction`, and `reason` explain
the failure. Duplicate normalized local/remote roots are rejected at startup.
Overlapping roots use the longest match independently in both directions;
translations that would round-trip to a different file raise a mapping error.

## Windows, escaping, and case

Windows drive and UNC local roots are supported even when the Python server
runs on POSIX. Backslashes in TOML can use literal strings:

```toml
[[path_mappings]]
local = 'C:\Work\site'
remote = "file:///var/www/html"
```

Remote Windows drive roots use file URIs such as `file:///C:/inetpub/site`.
Local Windows roots compare case-insensitively; POSIX roots compare sensitively.
Remote drive roots default to insensitive comparison, other remote roots to
sensitive comparison. Set `remote_case_sensitive = false` for a Windows UNC
engine root such as `file://server/share/site`, or explicitly choose either case
policy. Overlapping remote roots must agree on that policy. This is lexical
matching, not filesystem case-sensitivity detection.

URI output escapes spaces, Unicode, `#`, `?`, `%`, and application bytes correctly.
Incoming URI paths are decoded and normalized before matching, including encoded
`..` segments. Components that introduce Windows separators or drive syntax
while mapping from POSIX are rejected rather than reinterpreted as a different
path. The mapper neither checks existence nor copies files between machines.

## Inspecting server configuration

```python
from dbgpilot import Client

async with Client() as client:
    print(await client.path_mappings())
    print(await client.to_remote("/Users/you/site/src/cart.php"))
    print(await client.to_local("file:///var/www/html/src/cart.php"))
```

The corresponding RPCs are `paths.mappings`,
`paths.to_remote`, and `paths.to_local`; the latter two take a `path` string and
return a translated string. `to_local` is strict and reports unmapped/ambiguous
paths. Health and CLI readiness include `path_mappings`. Mapping failures use
RPC code `-32012` with structured path/direction/reason data; invalid arguments
or configuration are separate validation errors.

The [Playwright helper](playwright.md) uses these same server mappings. Supply
local paths in `BreakpointSpec`; returned snapshots carry both representations.
