# Changelog

## 0.1.1 — Unreleased

Patch update for the GitHub testing prerelease channel. Stable/package-index
publication remains pending.

- Avoid duplicate stop events and event-queue overflow after ordinary evaluation
  replies, while retaining recovery events for abandoned evaluations.
- Preserve empty PHP arrays when the engine typemap maps arrays to `hash`.
- Accept authenticated hostname listeners and bind resolved IPv4/IPv6 addresses
  using the appropriate socket family.
- Decode binary evaluation arguments through the HTTP API and preserve
  surrogateescaped bytes and byte lengths in assignment expressions.
- Report malformed context IDs as protocol errors rather than caller errors.
- Prune closed-session history on lifecycle changes instead of every event.
- Return HTTP 500/503 for failed `/health` operations while preserving ordinary
  RPC error responses and successful health checks.
- Remove redundant stdin acknowledgement validation; response validation remains
  in the dispatcher.
- Retain Drupal browser diagnostics for future failures, including traces,
  request events, page snapshots and resource samples.

## 0.1.0 — Testing prerelease (2026-10-28)

Stable/package-index publication is pending. A testing prerelease was published
on 2026-10-28 as
[v0.1.0-testing.1](https://github.com/djotto/DBGpilot/releases/tag/v0.1.0-testing.1),
with the validated wheel, source archive and checksums from commit `7130cac`.

- Async stdlib-only DBGp controller, structured values/snapshots, capability
  discovery, breakpoints, stepping, PHP evaluation/mutation and bounded cleanup.
- Persistent HTTP/JSON API `dbgpilot/1`, reconnectable async clients, event
  replay and cancellation that preserves outstanding engine execution.
- Python Playwright helpers, deliberate server setup/ownership, project TOML
  configuration, path mappings and opt-in async pytest fixtures.
- Proxy registration and optional stdin, interactive, expr/exec and spawnpoint
  APIs. Their positive coverage is scripted-peer only; live Xdebug rejects
  unsupported extensions cleanly.
- Protocol/lifecycle review fixes for cancellation races, malformed data,
  late acknowledgements, retention/admission limits and startup/browser cleanup.
- Follow-up fixes preserve capture cleanup through cancellation, apply token
  overrides before environment lookup, preserve Unicode mapping paths during
  owned startup, and accept the configured loopback listener's Host header.
- Real PHP/Xdebug runtime matrix, Chromium and Drupal acceptance coverage;
  reproducible distribution validation and installed-package examples.
- Public `dbgpilot.__version__`, CLI `dbgpilot --version`, and package version
  in server health/readiness. Package version and HTTP protocol version are
  separate compatibility signals.

Known boundaries: async Python 3.12/3.13; UTF-8 plus the specific Xdebug byte
profile; in-memory sessions do not survive daemon restart. Browser actions
need their original page/event loop alive. Raw commands require caller-managed
execution semantics. No full DBGp certification or additional live optional
engine support is claimed. See `docs/release-policy.md` and
`docs/protocol-review.md` for the detailed contracts and verified scope.
