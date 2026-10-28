# Version and compatibility policy

The current package version is **0.1.0**, available as GitHub testing prerelease
[v0.1.0-testing.1](https://github.com/djotto/DBGpilot/releases/tag/v0.1.0-testing.1).
Stable/package-index publication remains pending.
The source version, Poetry metadata, `dbgpilot.__version__`, CLI `--version`
and server health/readiness must agree. Validation fails if they disagree.
Candidate status is recorded in the release manifest; it is not an extra version
suffix and does not imply that a release has been uploaded or tagged.

## Python API and runtime scope

Supported interpreters are Python 3.12 and 3.13 (`>=3.12,<3.14`). The core remains
stdlib-only and async. Playwright and pytest integrations are optional and use
their own installed tools. Public APIs are the documented exports and methods;
underscore-prefixed implementation details are not compatibility promises.

For 0.1.x, preserve documented behavior for valid public calls. Additive APIs,
bug/security fixes, and stricter rejection of malformed inputs may be patch
changes and must be described in the changelog. A breaking public Python API
change before 1.0 requires a new minor version and migration notes. This is a
policy for future releases, not a claim that a 1.0 date or broader OS/engine
support has been established.

Tests distinguish parser checks, scripted engines, actual Xdebug, proxy and
application/browser acceptance. Controller support does not imply engine
support. Optional `stdin`/`interact`/`expr`/`exec`/spawnpoint success remains
scripted-peer coverage; Xdebug's clean rejection is verified live. See
[compatibility](compatibility.md) and the [review](protocol-review.md).

## HTTP contract

The HTTP contract identifier is **`dbgpilot/1`**, independent of package and
engine versions. Call health before controlling requests. Current servers also
advertise `version`; older compatible development servers may omit that field.
`DebuggerSetup` validates the supported protocol rather than requiring the
server package version to equal the client's version.

Within protocol 1, clients should ignore additional response fields and discover
optional methods/engine features as documented. Existing field meanings, request
ownership, error codes and session-lifetime semantics must remain compatible.
An incompatible wire change requires a new protocol identifier and documented
migration; a Python package version bump alone is not sufficient negotiation.
No exactly-once mutation/execution or transparent retry guarantee exists.

## Upgrade and restart

Installing a new package does not migrate or restart an existing daemon.
Check its health/version explicitly. A running process keeps its loaded code
until restart; reconnectable session IDs, journals, pending requests and sockets
exist only in that process.

Before a deliberate restart, finish investigations and explicitly detach/stop
or close sessions as appropriate. Stopping an owned setup with
`shutdown(release_sessions=True)` releases all of its sessions. A setup that
reused a server does not own it. Restart invalidates every old session ID and
cannot rehydrate PHP debugging sockets. Closing only an HTTP/Python client still
leaves PHP paused; browser investigations also require the original page/loop
to remain alive.

## Release status and provenance

MIT licensing is packaged in LICENSE, and NOTICE.md identifies the source and
reference provenance. The source archive contains the maintained implementation;
generated fixtures, vendor trees, reference engines and local evidence are not
distribution contents. Source and testing artifacts are hosted on GitHub at
https://github.com/djotto/DBGpilot. CI provider/runners/triggers and any future
package-index publication remain operator decisions. See [releasing](releasing.md)
for the local build and manual GitHub publication process.
