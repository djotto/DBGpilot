# DBGpilot conversation and implementation handoff

Snapshot date: 2026-10-28. Workspace: `/Users/djotto/projects/DBGpilot`.
Purpose: sufficient context for another LLM to continue this project without
repeating research, undoing agreed architecture, or mistaking planned work for
implemented functionality. This document summarizes the conversation and current
workspace; source files and `TODO.md` remain authoritative if they later change.

## 0. Immediate state / latest instructions

- Latest scope: make the wheel shareable through GitHub Releases. Added
  `scripts/github_release.py` to the existing local release wrapper, consumer
  quickstart and minimal pytest starter. It validates candidate hashes,
  generates consumer-facing release notes, supports a local `--dry-run`,
  defaults to uploading a draft prerelease and supports immediate `--publish`.
- The latest user request explicitly authorizes committing/pushing these release
  changes, tagging the matching source and publishing the validated candidate
  as `v0.1.0-testing.1` on GitHub. That workflow is complete; PyPI remains outside
  its scope.
- The user is still testing and explicitly permits manual testing rather than
  requiring a passing full suite before sharing artifacts. CI is optional for
  this handoff workflow. PyPI publishing remains deferred.
- Published testing prerelease:
  https://github.com/djotto/DBGpilot/releases/tag/v0.1.0-testing.1,
  published `2026-10-28T01:07:51Z` from commit
  `7130cac8405e7117c2d1b4768474f2032fb684d0`. Main and the annotated tag were
  pushed; all three public asset downloads matched the validated files.
- Published candidate build:
  `dist/release-candidate/20261028T002331074733Z-fe0aa851/`. Reproducible builds,
  archive checks and both fresh-install HTTP/TCP probes passed without full-suite
  evidence. Sixteen focused release/uploader tests passed. Candidate hashes and
  the tagged source match. Its `publication.json` records the successful upload
  and public-download verification separately from build-time `validation.json`.
  Main has subsequent publication-status documentation edits; build a new
  candidate before publishing changed package inputs. Usage is documented in
  `docs/releasing.md#github-release-command`.
- Local handoff candidate before the GitHub uploader additions:
  `dist/release-candidate/20261027T235458478745Z-e0868c44/`.
  Packaging/install validation passed without full-suite evidence. Nine release
  checks passed, both installed pytest examples collected, and the consumer
  starter from the source archive passed one real PHP/Xdebug/Chromium test
  against the installed wheel (18.67 seconds). Nothing was uploaded.
- TODO sections **1 and 2 are complete**, including the optional pytest integration.
  The independent parts of section 3 are implemented and rehearsed. Four later
  code-review findings, CR01–CR04, are also fixed and checked off.
- User chose to **keep Python**. Do not propose or begin a TypeScript/PHP rewrite.
- User explicitly rejected MCP: **"Remove referenes to MCP from TODO.md - we're
  not doing that."** All MCP references and its proposed work package were
  removed from `TODO.md`. It is not optional future scope in the agreed plan.
- `TODO.md` has **7 unchecked tasks**: CI in section 3 (1), and the standalone
  DBGpilot skill in section 4 (6). Section 4
  can proceed independently of CI or publication choices when requested. The
  user explicitly deferred build-pipeline decisions; do not choose them silently.
- Historical spec-audit checkboxes are all checked. This records completion of
  those tasks, not certification of complete DBGp conformance.
- Latest full check: **514 passed, 0 failures/errors/skips**, DDEV Python 3.13.5.
  JUnit time 297.360 seconds, timestamp `2026-10-27T21:05:51.143105+00:00`.
  `./scripts/check.sh` also completed reproducible builds, fresh wheel/source
  installs, real PHP onboarding and installed-wheel standalone/pytest Chromium
  examples. A focused setup/review/live-browser run passed 50 tests.
- Additional macOS/Python 3.12.9 fast checks are **not green**: existing short
  startup/handshake/CLI deadlines expired, with subsequent resource warnings.
  All new review regressions passed there except the unavailable `127.0.0.2`
  case, which skipped. Do not turn the Linux result into a claimed current
  passing host suite. Details and reports are in section 11 and `TODO.md`.
- Last full-suite-validated unpublished candidate, before the local handoff additions:
  `dist/release-candidate/20261027T211106676266Z-1993e889/`.
  Its packaged documentation predates the local handoff additions. Build a fresh
  candidate with `./scripts/release.sh` when inputs change again; the current
  local handoff candidate is listed above. Do not use old artifact hashes for
  these additions.
- Package version remains `0.1.0`; HTTP protocol remains `dbgpilot/1`. CI provider
  and runner/trigger policy remain deferred. GitHub origin is the public
  `djotto/DBGpilot`, and CLI authentication works. The first GitHub testing
  prerelease is published as described above. The uploader verifies remote tag
  existence but relies on the operator to match tag source to candidate source;
  the complete tagged package inventory was explicitly checked for this release.
- Workspace has a `.git` directory. Inspect Git state before reporting commits
  or branches; do not infer them from this handoff.

## 1. Product goal and user intent

The original goal is interactive PHP debugging controlled by Codex while Codex
continues writing ordinary **Python Playwright scripts** to reproduce bugs.
Scripts should combine browser actions with Xdebug breakpoints, variable checks,
stack inspection, evaluation/mutation, stepping, and final DOM assertions.

Essential requirement: **"break here and return"**. A call must return useful,
JSON-safe breakpoint details to the caller while PHP remains paused. Later calls,
including calls from a different Python client/process, must inspect or advance
that same PHP request. Returning a snapshot or closing an HTTP/Python client must
not implicitly resume PHP. A copied snapshot must not change when PHP later does.

Drupal 11 is the user's first substantial application target. It is already
available as a real test application, separate from the initial checkout demo.

Project name: **DBGpilot**. Python import/distribution name: `dbgpilot`.
License explicitly chosen by user: **MIT**. Dependency/reference provenance
matters: original implementation, no copied reference debugger implementation.

User collaboration preferences:

- Be candid about limitations and tradeoffs. User explicitly challenged advice
  that sounded like telling them what they wanted to hear.
- Distinguish implemented behaviour, scripted tests, and live engine support.
- Complete authorized implementation tasks; avoid repeated permission questions.
- Update TODO checkboxes from `[ ]` to `[x]` when each task actually completes,
  with relevant verification. Do not check tasks merely because they are planned.
- Keep progress updates concise and final replies focused.
- Current agent instructions prohibit spawning subagents unless the user or an
  applicable instruction explicitly requests delegation. An "independent review"
  TODO is not itself a request to spawn agents now.

## 2. Conversation trajectory and decisions

1. Brainstormed interactive Playwright + Xdebug approaches. User wanted to keep
   Codex's existing ability to write Playwright scripts rather than replace that
   with an opaque bundled workflow.
2. Explored adding debugging interactions to the scripts, including a breakpoint
   snapshot return that leaves execution suspended.
3. Researched Python DBGp implementations and documentation. Created a DDEV
   PHP/Xdebug/Python harness and proved the basic debug loop.
4. Compared the DBGp specification with Vdebug; inspected Komodo and Pugdebug as
   additional reference implementations. Initially included the references as
   development dependencies in a Poetry project.
5. User chose DBGpilot and MIT, with the explicit plan to build an original
   controller using those dependencies as source material, then remove them.
   Tests use pytest, pytest-asyncio, Hypothesis, scripted TCP engines, and live
   PHP/Xdebug; Playwright was added for browser acceptance checks.
6. Built the initial controller. User requested a spec-based implemented/missing
   inventory and then requested that inventory in `TODO.md` with checkboxes.
7. Implemented audit priorities 1–5: notification/evaluation handling, core
   wrappers, metadata/options, stop/detach semantics, capability negotiation and
   regression coverage. Controller milestone: 120 tests, up from the initial 64.
8. Built a long-running HTTP server around the controller, async client and CLI,
   so short-lived scripts can return and later reconnect. Server milestone: 155.
9. Built the Python Playwright helper, explicit cancellation, real engine matrix,
   browser/stress coverage. Milestone: 193.
10. Added proxy registration/errors and optional stdin/interactive shells.
    Milestone: 248. Actual Xdebug does not support those optional shell commands;
    positive behaviour is tested with scripted peers.
11. Added expr/exec and the full spawnpoint family, with state/cancellation and
    optional-extension coverage. Milestone: 352. Actual Xdebug rejects these
    unsupported commands cleanly; positive support is not claimed for Xdebug.
12. Implemented general-purpose, environment-configured local/remote path mapping.
    Milestone: 405. It handles lexical paths and URIs, not mount discovery or
    source-file synchronization.
13. Created separate Drupal 11.4.11 DDEV fixture and actual browser/Xdebug trials
    for core rendering, persisted form save, and author-autocomplete AJAX.
    Milestone: 408, all passed with the fixture required.
14. Discussed Playwright internals, extension mechanisms, language boundaries,
    and whether TypeScript would make more sense. Earlier TypeScript advice
    assumed JS/TS Playwright Test; the user clarified they drive Playwright from
    Python. Settled on keeping Python; no rewrite is planned.
15. Discussed MCP and briefly PHP SDK/DBGp alternatives. These were research and
    discussion only; no adapter or rewrite was implemented. The user subsequently
    explicitly removed MCP from the project plan. Do not revive it as open work.
16. Added high-level work packages to TODO, then removed MCP at the user's request.
    The original 17-task backlog is historical, not the current completion state.
17. Implemented section 1: `DebuggerSetup`, `SetupConfig`, opt-in pytest fixtures,
    deliberate startup/configuration/ownership, diagnostics and installed-package
    examples. Verified 447 full-suite tests, including a fourth Drupal test using
    the new owned setup. Later explicitly confirmed to the user that pytest
    integration is complete; CI execution is the remaining automation work.
18. Completed section 2: fresh protocol/lifecycle review, 14 fixed findings and
    44 new regressions, bounded resources, optional-engine investigation and
    support-boundary documentation. Full milestone: 491 tests.
19. User asked whether section 3 could proceed without pipeline decisions, then
    asked to build whatever could be done. Implemented provider-independent
    fast/distribution checks, onboarding, first-breakpoint example, changelog,
    version/provenance/compatibility policy and local release rehearsal. Full
    milestone: 500 tests; fast checks passed 464 tests on both 3.12/macOS and
    3.13/Linux at that milestone. CI and publication choices stayed pending.
20. User requested a bug-focused code review. Found and reproduced four P2 bugs:
    cancelled paused-handle cleanup lost ownership, token overrides were applied
    too late, non-BMP mapping paths broke generated TOML, and alternative loopback
    listeners rejected their own Host headers. At the user's request, recorded
    them in TODO and added nine strict expected-failure regressions.
21. User asked to fix them. All four are fixed; markers removed and five boundary
    cases added, for 14 ordinary regressions in `tests/test_review_findings.py`.
    Full check: 514 tests plus fresh installed/live examples and a new candidate.
22. Extra host fast runs exposed timing failures in existing tests. A temporary
    test startup budget increase was investigated and reverted; it is not part
    of the final change. The host fast suite is not claimed passing. A reported
    CLI child was checked and had exited. See the preserved evidence below.
23. Corrected this handoff's workspace path and Git-directory status after the
    checkout moved to `/Users/djotto/projects/DBGpilot`.
24. Added the local release wrapper, consumer pytest starter and quickstart,
    and manual upload instructions. Full tests remain a separate manual choice;
    PyPI and CI wiring remain deferred.
25. Added the GitHub release uploader, with a read-only preview, candidate hash
    checks, draft-prerelease default and explicit immediate-publish option.
    Verified public GitHub origin and authentication, passed 16 focused tests,
    and built a fresh validated candidate. No commits/tags were pushed and no
    release was created.
26. At the user's explicit request, committed/pushed the tooling/docs, verified
    the committed package inputs, pushed `v0.1.0-testing.1`, and published the
    GitHub testing prerelease. Downloaded all three public assets and verified
    their exact contents. Recorded publication separately from build validation
    and updated main's status documentation without changing release assets.

## 3. Architecture and non-negotiable lifetime semantics

```text
async Python Playwright script / optional opt-in pytest fixtures
       | supplies Page; uses PlaywrightDebugger + Client
       v
HTTP/JSON-RPC API (default 127.0.0.1:9004)
       v
persistent Python Server -> Controller -> independent Session per PHP request
                                             ^
                                             | DBGp TCP (default port 9003)
                                             |
                                  PHP's Xdebug initiates connection
```

- The daemon owns debugger TCP sockets, pending transactions, execution state,
  session IDs, inventories, and replayable event histories.
- HTTP is already language-independent. Other clients can call the API without
  any Playwright-internal extension or alternate daemon protocol.
- Session IDs are process-scoped; they do not survive server restart. There is
  no persistence/rehydration of live PHP sockets across daemon replacement.
- Closing `Client` cancels its outstanding RPCs but does not resume PHP.
- Caller timeout/cancellation does not pretend the engine stopped executing.
  Ownership/guards remain until an actual late reply/terminal outcome is handled.
- Explicit detach/stop/session close and daemon shutdown have separate semantics.
  Do not conflate client lifetime with daemon or PHP lifetime.
- Metadata and event polls remain available while execution is pending;
  conflicting session operations are guarded. Interrupt/input depend on engine
  capabilities and state.
- Live idle sessions are not automatically evicted or resumed to satisfy limits.
- A snapshot is a JSON-safe independent copy, not a live view into an engine.
- Browser process/page/event loop must remain alive for a paused browser action.
  The daemon preserves PHP debugging, not a browser that the caller destroys.
- Public library APIs are asynchronous. Sync Python Playwright support has not
  been implemented or established as a requirement.

## 4. Repository / package map

Package: `src/dbgpilot/`, built by Poetry. Python requirement `>=3.12,<3.14`.
Runtime dependencies: `[]` (Python standard library only).

- `controller.py`: listener, session acceptance/filtering, setup, ownership,
  pre-session errors, proxy registrations, path mapper.
- `session.py`: DBGp command APIs, state machine, transaction ownership,
  execution/inspection guards, capability-aware optional commands, snapshots.
- `protocol.py`: DBGp framing, command construction, wire validation/encoding.
- `models.py`: structured models, XML decoding, JSON-safe serialization.
- `errors.py`: local protocol/state/command/proxy/path errors.
- `proxy.py`: short-lived proxy control connections and response handling.
- `paths.py`: `PathMapping`, `PathMapper`, config discovery/loading and mapping.
- `server.py`: persistent HTTP/JSON-RPC facade, records, journals, cancellation,
  validation/authentication, command allowlist and lifecycle.
- `client.py`: async native-stream HTTP client, `RemoteSession`, `RemoteRequest`.
- `wire.py`: HTTP/RPC serialization and remote error representation.
- `cli.py`, `__main__.py`: `dbgpilot serve`, `dbgpilot call`, module entrypoint.
- `playwright.py`: `BreakpointSpec`, `PlaywrightDebugger`, `PausedBrowser`.
  Duck-types a supplied Playwright Page; no runtime Playwright import needed.
- `setup.py`, `config.py`: public `DebuggerSetup`, `SetupConfig`, deliberate
  config loading/overrides and reused versus explicitly owned CLI startup.
- `pytest_plugin.py`: opt-in function-scoped async setup/debugger fixtures.
- `queues.py`: internal retained FIFO; background notification tasks never
  consume the caller's event/session before cancellation is settled.
- `_version.py`: public package version shared by imports, CLI and health.
- `__init__.py`: public exports, including controller/server/client/helpers,
  models, errors, proxy and path mapper.
- `py.typed`: packaged typing marker. Do not assume annotations are complete.
- `src/checkout.php`, `public/`: small PHP checkout/health harness, separate from
  the Python package.
- `fixtures/drupal11/`: separately licensed Composer/DDEV test application.
- `scripts/`: check runners, runnable debug examples, runtime preparation.
- `tests/`: unit/property, scripted TCP/HTTP, live PHP, browser, matrix, stress,
  proxy, mapping, and Drupal tests.
- `docs/`: API, server, Playwright, path mapping, optional commands, proxy/shell,
  compatibility, Drupal, development and historical research/audit guides.
- `TODO.md`: historical completed audit plus the current actionable backlog.
- `dbgpilot.example.toml`: mapping example; not an active root config.
- `poetry.lock`, `pyproject.toml`, `LICENSE`, `README.md`.
- `CHANGELOG.md`, `NOTICE.md`, `docs/installation.md`, `docs/releasing.md`,
  `docs/release-policy.md`: implemented release/onboarding/provenance guidance.
- `scripts/check_fast.sh`, `check_distribution.py`, `probe_install.py`: reusable
  fast checks and isolated release validation. `examples/first_breakpoint.py`
  is the verified local PHP CLI onboarding example.
- `test-results/`, `.venv/`, `dist/`, caches and generated fixture code are ignored.

Current development dependencies:

```toml
pytest = ">=8.3,<10"
pytest-asyncio = ">=1.0,<2"
hypothesis = ">=6,<7"
playwright = "^1.64.1"
```

Pytest: asyncio auto mode, function default loop scope, warnings treated as
errors. Markers: integration, browser, compatibility, stress, drupal.
The pytest plugin is packaged but opt-in, not an automatically loaded entrypoint:
`pytest_plugins = ["dbgpilot.pytest_plugin"]`. The setup helper and changelog are
implemented. Pytest, pytest-asyncio and Playwright are installed separately when
needed; no package extras or runtime dependencies are declared. There is no CI
workflow or MCP dependency. Build backend is pinned to `poetry-core==2.1.1`.

## 5. Implemented controller / protocol capabilities

### Transport, initialization, and values

- Async listener; independently correlated sessions/transactions; validated init
  metadata including app/thread/parent/cookie/proxy/vendor information.
- Fragmented/coalesced TCP packets, byte-length framing, quoting/base64 including
  empty and binary payloads, limits, namespace checks, malformed packet handling.
- XML DTD/entity rejection; response command/transaction validation; distinct
  streams, notifications, stopped, interactive, proxy-error and closed events.
- Xdebug-specific byte-preserving Latin-1/ISO-8859 XML framing policy; normal
  supported communication profile elsewhere is UTF-8. Do not replace this with
  naive text decoding of application bytes.
- Structured standard/extended properties: binary/NUL names, fullnames, class,
  key/address/facet/constants, child order, direct-child paging, truncation,
  complete byte retrieval with reported size, type mappings and common scalars.
- JSON-safe binary and nonfinite values; retained vendor metadata/XML where
  needed for fidelity.

### Commands, capabilities, and execution

- Dedicated status, feature get/set, stack depth/get, context names/get, typemap.
- Breakpoint set/get/list/update/remove: line/conditional/exception/call/return,
  temporary and hit options; disabled initial state; filename-wide conditions;
  structured metadata and resolved-notification inventory updates.
- Run, run-until-break, stepping into/over/out, detach, stop; distinguish actual
  stop reply from permitted EOF using `ExecutionResult.response_received`.
- Property get/set/value and metadata/full-value helpers, options including
  depth/context/page/max data/key/address as applicable; PHP assignment helpers.
- Source retrieval, line ranges, preserved explicit file/dbgp virtual URIs.
- Eval manages execution ownership, late replies, events and cancellation.
  Tested Xdebug evaluates the current frame only; nonzero eval depth is handled
  according to engine capability/policy, not claimed as universally unsupported.
- stdout/stderr modes and independent stream events; capability-aware break/
  interrupt (tested Xdebug advertises `supports_async=0`).
- Capability inventory and startup feature negotiation, including unsupported
  optional features, breakpoint types and advertised postmortem inspection.
- Raw `Session.command(...)` remains available directly but is not exposed as
  arbitrary raw execution through the remote server allowlist.

### Proxy and optional commands

- `ProxyClient` supports separate bounded `proxyinit`/`proxystop` controls,
  bare/NUL/framed XML, quoting, opaque errors, cancellation/limits.
- Controller tracks owned registrations, exposes them remotely, unregisters on
  bounded shutdown. CLI can register before readiness. Proxy errors before init
  and within established sessions are retained and surfaced separately.
- Official dbgpProxy **0.6.2 drops final stopped responses**. Known owned/proxied
  sessions or explicit opt-in permit clean detach EOF. Direct connections remain
  strict, truncated packets still fail, and PHP completion is asserted separately.
- stdin configure/send accepts text or bytes, exactly mode or data, proper input
  state/locking and late acknowledgements. Async engines or synchronous stdin-read
  notifications permit input during execution; this is not ordinary run locking.
- interact supports engine-owned buffering, prompt/more/reset, interactive state,
  inspection, streams/events and late/cancelled execution results.
- expr returns decoded Property for successful property response, None for
  explicit failure; successful replies must contain exactly one property.
- exec returns a success boolean, ignores vendor property results, has no expr
  depth/page options. Both preserve execution state through late replies/errors.
- Spawnpoints are separate models/inventories, with all five set/get/update/
  remove/list wrappers. Opaque IDs, vendor XML, file/line/state; requested lines
  positive, received sentinel -1 preserved. Acknowledgements update inventory
  even after caller cancellation; malformed lists do not partially commit.
- Actual Xdebug rejects stdin/interact/expr/exec/spawnpoints. Positive paths use
  scripted engines; live rejection checks leave the PHP session usable. No
  additional supporting real engine has yet been integrated.

## 6. Persistent HTTP server and async client

- Defaults: API `http://127.0.0.1:9004`, debugger `127.0.0.1:9003`.
- `GET /health`, `POST /rpc`; JSON-RPC method contracts in `docs/server.md`.
- Standard-library threaded HTTP serving dispatches to the owning asyncio loop.
  Python Client uses native asyncio HTTP streams, not one worker thread per poll.
- Optional bearer token. Nonloopback API binding requires authentication.
  CLI token can come from `DBGPILOT_TOKEN`.
- Explicit RPC allowlist, structured validation/errors, body/response limits,
  scoped session IDs, reconnectable remote handles.
- Claim/filter by IDE key, cookie, application ID, file; unrelated sessions are
  retained. Session inventories/metadata stay accessible to reconnecting clients.
- Bounded replayable event journals, independent cursors, long polling, explicit
  expired-history errors; closed-record retention and explicit close/forget.
- `break_and_return` captures while leaving PHP paused. Most execution/capture
  deadlines default 30 seconds, max 300; Client transport has its own timeout.
- `RemoteRequest`: explicit ID, await/result/cancel/done; `cancel_request` handles
  cancellation races with bounded tombstones for delayed submission.
- HTTP disconnect/cancellation must not clear pending engine execution ownership.
- `Server(controller=...)` owns the supplied controller/event consumption.
- CLI has serve/call entrypoints, ready/error output and graceful signal handling.
- `DebuggerSetup` can reuse the API or explicitly launch the existing CLI. It
  validates PID/instance/protocol readiness and never adopts an existing server
  after bind failure. See section 7 for its separate ownership semantics.
- Health/readiness include package `version` and `instance_id`; protocol
  compatibility is `dbgpilot/1`, not an exact client/server package-version match.
- Unauthenticated Host validation accepts the configured loopback listener and
  existing loopback aliases; unrelated Host and browser Origin rejection remain.

## 7. Python Playwright helper contract

Main public API (see `docs/playwright.md` and `src/dbgpilot/playwright.py`):

```python
BreakpointSpec(file=None, line=None, options={})
PlaywrightDebugger(page, client, idekey=None)  # idekey keyword-only
await debugger.goto(url, breakpoints=(), variables=(), expressions=(),
                    timeout=30, navigation_timeout=0)
await debugger.capture(action, url_pattern=..., breakpoints=(), variables=(),
                       expressions=(), timeout=30)
```

- Use the helper as an async context manager, or explicitly close it. It accepts
  an existing async Page and Client; it does not create browser/server processes.
- Routes one matching page request. Adds the same unique generated key to BOTH
  `XDEBUG_SESSION` and `XDEBUG_TRIGGER`; Xdebug may use the trigger as IDE key.
- Trigger URLs preserve other query parameters and POST method/body. Explicit
  `idekey` supports restricted trigger setups but reused keys cannot distinguish
  simultaneous captures. Arbitrary generated keys require permissive test config.
- `goto` uses a genuinely distinct navigation URL for each retry, then removes
  generated parameters using history.replaceState after successful navigation.
- Action and breakpoint wait run concurrently. A click/fill may finish while its
  AJAX PHP request remains paused; successful action completion must not end the
  breakpoint wait. Action failure should fail promptly.
- Capture timeout ends once paused handle is returned. Browser navigation timeout
  is separate and defaults disabled; callers may need `timeout=0` on actions.
- Returned `PausedBrowser` has `session_id`, independent snapshot, action task;
  `.session(client=None)`, `.events(client=None, timeout=30)`,
  `.finished(timeout=30)`, `.close()`.
- `.finished()` waits without itself resuming PHP and does not cancel the action
  merely because that wait times out.
- `PausedBrowser.close()` shares one shielded cleanup task. Cancelling a waiter
  leaves the session-close attempt/action cleanup running and tracked until it
  finishes. Concurrent handle/helper closes join it. Close a capture or helper
  outside its own browser action to avoid a task cycle.
- Helper scope exit releases its captures. To preserve the capture beyond a
  temporary client, keep helper/browser/event loop alive until explicit cleanup.
- Failed setup/action/deadline removes route, cancels pending waits, releases an
  attached session and settles action. Cleanup uses a fresh Client, so it works
  after the first client closes; server/network failure can still prevent it.
- Routing is page-scoped; separate pages for simultaneous captures. Service
  workers may bypass routing; document/use service_workers="block" as needed.
- Existing real browser tests cover navigation, form POST, AJAX, reconnect/mutate,
  failure/retry cleanup, Windows-to-Linux paths, 35-second pauses, four captures,
  and server restart. Installed standalone and opt-in pytest examples are verified.

### Setup, configuration and pytest ownership

Public setup usage and configuration are documented in `docs/python-setup.md`.
`DebuggerSetup(config=None, discover=False, **overrides)` has explicit library
discovery; CLI serve/call discover nearest `dbgpilot.toml` unless `--no-config`.
`config=False` disables discovery. `SetupConfig` is also accepted directly.

- Default setup reuses `http://127.0.0.1:9004`; `launch=True` explicitly starts
  the existing CLI under the configured Python interpreter/working directory.
- Config sections: connection (URL, request timeout, token environment name),
  startup (launch, startup timeout, Python, working directory), listener (API and
  debugger hosts/ports), and path mappings. See `dbgpilot.example.toml`.
- Explicit API overrides win over loaded settings/defaults. CLI `--token` wins
  over `DBGPILOT_TOKEN`, which wins over configured `connection.token_env`.
  Shadowed token environment variables need not exist; without an override the
  variable is required. Explicit API `token=None` clears the file's setting.
- Config-relative paths resolve on the reading machine; explicit API path
  overrides use caller context. Mapping roots are lexical. Owned children receive
  resolved mappings in a generated UTF-8 TOML file, including non-BMP Unicode and
  escaped controls. Tokens go through the child environment, not CLI arguments.
- Setup context exit / `aclose()` closes its client and preserves its server/PHP.
  Keep the owning setup handle for deliberate shutdown. Only
  `shutdown(release_sessions=True)` stops its child and releases all of that
  child's sessions; a reused setup cannot shut down someone else's daemon.
- Startup failure/cancellation reaps only its child. PID/instance identity,
  bounded readiness/health, occupied ports and concurrent starts are checked.
  Cleanup may run after the startup deadline; graceful termination has a
  five-second bound before killing the owned process. There is no supervisor.
- `setup.debugger(page)` supplies the connected Client to a normal helper. The
  helper releases captures on exit even though setup itself preserves the daemon.

The optional pytest plugin exposes `dbgpilot_options`, `dbgpilot_page`,
`dbgpilot_setup`, and `dbgpilot_debugger`. Override `dbgpilot_page` to reuse an
existing **async** Playwright Page; the default delegates to fixture `page`,
which must also be async. It does not adapt a synchronous pytest-playwright page.
Use function-scoped asyncio loops (`asyncio_mode=auto` or marked async tests).
Debugger teardown releases captures, then setup teardown closes the client and
explicitly stops an owned child. A reused daemon remains alive. Thus fixture
`launch=True` deliberately opts into owned-server shutdown at teardown, unlike
the ordinary setup context's preserve-server exit policy.

Parallel workers normally use a shared separately owned daemon, separate pages
and generated unique capture keys. Worker-owned daemons need isolated API and
debugger ports plus PHP routing to each listener; choosing port 0 alone does not
reconfigure Xdebug. Examples: `examples/checkout_debug.py`, `examples/pytest/`,
and the owned setup Drupal case. Pytest integration is complete for this scope.

## 8. General-purpose path mapping

- `PathMapping(local, remote, remote_case_sensitive=None)`;
  `PathMapper(mappings=(), base_dir=None)`; lexical, no source existence required.
- Bidirectional longest directory-component prefix matching. Supports POSIX,
  Windows drive/UNC paths independent of server OS, escaping/Unicode/application
  bytes, normalized encoded dot segments, file URI authorities and case rules.
- Windows local paths case-insensitive, POSIX local paths sensitive. Remote
  Windows-drive URIs default insensitive; other remote roots default sensitive,
  configurable. Duplicate roots/conflicting case policies and ambiguous round
  trips are rejected rather than guessing.
- Explicit outbound file:/dbgp: URIs bypass translation. Without mapping rules,
  legacy absolute file-URI conversion remains available.
- Strict `to_remote`/`to_local` raise `PathMappingError` on unmapped/ambiguous
  applicable paths. `location(uri)` is best-effort metadata annotation so an
  unmapped incoming source location does not kill debugging.
- Raw engine `file` URIs and XML retained. Models/snapshots/events/inventories add
  `local_file` and `path_mapping_error`, including nested frame/input/breakpoint
  locations. Virtual dbgp/<console> locations are treated separately.
- Outbound breakpoint/source/spawnpoint paths and session file filters use mapper.
- Configure Controller/Server explicitly with mapper/rules. If passing a custom
  Controller to Server, configure that Controller rather than conflicting knobs.
- CLI nearest-ancestor `dbgpilot.toml` discovery; `--config`, `--no-config`, repeated
  `--path-map LOCAL REMOTE`. Config-relative roots resolve against config file;
  CLI-relative roots against cwd. Overrides match normalized local root.
- Library constructors do not implicitly read ambient config.
- Client exposes path_mappings/to_remote/to_local; health includes rules;
  RPC path failures have code -32012 and path/direction/reason.
- This does not infer Docker mounts, copy source, resolve symlinks or fix network
  routing. Map the namespace sent by the script, including host paths when the
  daemon is in Linux. See `dbgpilot.example.toml`, `docs/path-mapping.md`.

## 9. Development environment and commands

Host at handoff: macOS, bash, timezone Europe/London; host `.venv` uses Python
3.12. DDEV web image has Python 3.13 / Poetry 2.1.1. Keep macOS and Linux virtual
environments separate. Current sandbox can prohibit host TCP binds; run complete
TCP/HTTP/browser suites inside DDEV. No applicable ancestor/project AGENTS.md was
found in earlier checks; a vendored Drush AGENTS.md is not project-wide guidance.

Root DDEV project:

- name `xdebug`, type php, docroot `public`, nginx-fpm, PHP 8.4, Xdebug enabled.
- https://xdebug.ddev.site; container project path `/var/www/html`.
- No root database container (`omit_containers: [db]`). Drupal has its own DB.
- Xdebug debug/develop, trigger mode, client discovery off, client host127.0.0.1,
  port9003, idekeyxdebug-harness. Daemon is normally inside same web container.
- Checkout demo: £100 subtotal, SAVE10 discount £10; health.php reports runtime;
  `/?code=SAVE10&format=json` returns calculation.
- To listen on host would require deliberately changing Xdebug client_host to
  host.docker.internal and appropriate routing; no such change is in current plan.

`.ddev/commands/web/poetry` sets:

```text
POETRY_VIRTUALENVS_IN_PROJECT=false
POETRY_CACHE_DIR=/mnt/ddev-global-cache/poetry/${DDEV_SITENAME}
POETRY_VIRTUALENVS_PATH=${POETRY_CACHE_DIR}/virtualenvs
PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright
```

Useful commands (from root unless stated):

```sh
poetry install
poetry run pytest -m "not integration"
poetry check --lock
poetry build
./scripts/check_fast.sh test-results/fast-junit.xml
poetry run python scripts/check_distribution.py

ddev start
ddev test-setup
ddev poetry run pytest
ddev poetry run pytest -m browser
ddev poetry run pytest -m compatibility
ddev poetry run pytest -m stress

# Full required-fixture setup/check; may recreate/start containers and seed fixture:
./scripts/check.sh

# Ordered setup and full test run (distribution validation follows in check.sh):
ddev drupal-setup
ddev test-setup
ddev exec env DBGPILOT_REQUIRE_DRUPAL=1 /mnt/ddev_config/commands/web/poetry run pytest --junitxml=test-results/junit.xml
ddev poetry run python scripts/check_distribution.py --live-php --live-browser --suite-junit test-results/junit.xml

# Manual daemon; leave running in its own terminal:
ddev poetry run dbgpilot serve
ddev poetry run dbgpilot call health
ddev poetry run python scripts/check_server_harness.py
ddev poetry run python scripts/check_playwright_harness.py

# Direct controller / HTTP checkout example:
ddev poetry run python scripts/check_harness.py
```

- `test-setup` runs Poetry install, Playwright Chromium install with system
  dependencies, then `scripts/prepare_test_runtimes.py` for historical modules
  and proxy binary. Downloads/modules/browsers are cached outside distributions.
- Rerun `ddev test-setup` after container recreation: persistent browser binaries
  survive but installed system libraries may not. A previous missing libnspr4
  failure was fixed by setup. Do Drupal project startup before browser setup.
- `ddev composer ...` intermittently produced Docker socket permission issues
  under the tool sandbox. `ddev exec composer ...` worked; setup uses that form.
- Sandbox restrictions can block Docker/socket access or host TCP binds even
  when DDEV itself works. The user is in a CLI environment and was frustrated by
  repeated permission questions and references to a graphical message box.
  Use the execution tool's `require_escalated` approval mechanism when needed;
  `ddev` and `./scripts/check.sh` prefixes were already approved in this session.
  Retry an important sandbox-related failure with escalation instead of asking
  the user to repeat permission they already granted. Current tool policy wins
  if a future session has a different permissions profile.
- A harmless shell LC_ALL/C.UTF-8 warning appears in host exec output.
- Last known both DDEV sites were running; this is historical runtime state,
  last exercised by the passing 514-test check, not newly checked for this
  documentation turn. No intentionally persistent DBGpilot daemon was left
  running. Inspect ports/processes before manual debug or integration.
- A prior isolated wheel-check environment exists at
  `/private/tmp/dbgpilot-wheel-check`; do not assume it contains the latest build.
- No tests need rerunning solely for these Markdown edits; do meaningful checks
  when implementation changes begin.

## 10. Drupal 11 fixture: exact design and observed behaviour

Path `fixtures/drupal11`; separate DDEV name `dbgpilot-drupal11`, type drupal11,
docrootweb, PHP8.4, MariaDB11.8. Locked Drupal11.4.11 and Drush13.8.0.
Last verified runtime: PHP8.4.22, Xdebug3.5.3, MariaDB11.8.8.

- Public URL https://dbgpilot-drupal11.ddev.site.
- Internal parent-container URL http://ddev-dbgpilot-drupal11-web, trusted host.
- Owned fixture credentials **admin / dbgpilot-admin**, `/user/login`.
- Seed page title **DBGpilot seeded page**, initially node1; fixed UUID
  `2c05a3bd-8ed1-4e80-b6df-5f8af2cbd001`. Read fixture-state for actual node ID.
- Xdebug points to **ddev-xdebug-web:9003**, discovery off, trigger mode.
  Parent daemon must bind debugger host **0.0.0.0** for cross-container requests.
  API can stay loopback.
- Parent local `/var/www/html/fixtures/drupal11/` maps to Drupal remote
  `file:///var/www/html/`; covers both core and vendor. Fixture dbgpilot.toml
  local "." is resolved relative to the fixture config, not root cwd.
- Manual parent daemon:

```sh
ddev poetry run dbgpilot serve --xdebug-host 0.0.0.0 --config fixtures/drupal11/dbgpilot.toml
```

Do not run this while Drupal tests need fixed debugger port9003.

Fixture files and setup:

- composer.json derives from the canonical recommended-project11.4.11 template;
  exact core pins, Drush dev dependency, composer.lock (89 packages at setup).
- `.ddev/commands/web/fixture-setup` includes settings once, installs only into
  an empty DB when bootstrap absent, refuses destructive reinstall over populated
  unbootstrappable DB, runs seed/cache rebuild. XDEBUG_MODEoff for setup tooling.
- `seed.php` explicitly creates page content type, body storage/field/form/view
  display, sets owned admin and seed node/frontpage/site name/state marker, writes
  ignored `fixture-state.json` with runtime and URLs. Idempotent re-seeding was
  verified to retain nodeID and unrelated content.
- Explicit creation was necessary: assumed Standard-profile body/page config
  was not present in this setup. Do not replace it with deprecated body helper.
- settings.dbgpilot.php + services.dbgpilot.yml disable render/page/dynamic caches
  using NullBackendFactory and asset aggregation; include trusted hosts.
- Core/vendor files remain unmodified; breakpoints are located by unique source
  statements in pinned code, not instrumentation added to Drupal.
- vendor/, web/, fixture-state.json ignored; development Drupal GPL-2.0-or-later
  license remains separate from MIT Python. Neither distribution includes them.
- `scripts/setup_drupal.sh`, root host custom `ddev drupal-setup`, and web custom
  `ddev drupal-test` make setup and focused acceptance repeatable.

`tests/test_drupal.py` scenarios (real Chromium/PHP-FPM/Xdebug):

1. **core_view**: break EntityViewController.php at `$page = $this->entityTypeManager`
   (line132 for pinned core), snapshot node/view mode/ID/label and mapped stack,
   close first Client, reconnect, eval-change label, step, detach, verify changed
   rendered H1 and unchanged database title on fresh request.
2. **form_save**: login, ordinary `/node/add/page` form, unique title, pause at
   NodeForm.php `$node->save();` (line281), inspect new node/FormSubmitter stack,
   reconnect, mutate title, step actual DB save, inspect ID, detach, follow
   redirect, verify H1 and persisted title on fresh GET. Delete test-owned node
   through ordinary delete form in cleanup.
3. **author_autocomplete**: login/node form, open author details, fill actual
   `uid[0][target_id]` input with adm; capture user-autocomplete AJAX, pause at
   EntityAutocompleteController.php `$matches = $this->matcher->getMatches`,
   snapshot targettype/query, change query to admin, step DB matcher, inspect
   matches, detach, assert admin appears in real autocomplete menu. Typing
   completes before PHP AJAX does; helper must keep waiting correctly.
4. **owned_setup**: launch through `DebuggerSetup` using the Drupal config and
   cross-container debugger listener; capture core rendering, verify local mapped
   path, close the original client, reconnect/mutate/detach, assert changed H1,
   and explicitly shut down the owned server. This fourth pytest case was added
   with section 1; the JSON report separately records the three scenarios above.

Important observed engine behaviour: Drupal core rendering runs in a PHP Fiber.
Xdebug reports the active Fiber's stack and stops at its entry, without parent
Symfony HttpKernel frames. Initial incorrect test expectation was fixed; preserve
and document engine output instead of inventing a parent stack.

Login redirects are not guaranteed `/user/1`; tests prove login by access to
node creation form instead of that assumption.

Reports: `test-results/drupal11.json` records runtime and three passed scenarios,
source/execution/frame evidence; `test-results/drupal11.png` shows seeded front
page. Avoid exporting full sensitive object snapshots into routine artifacts.

Tests skip outside DDEV or absent optional state in ordinary pytest. Setting
DBGPILOT_REQUIRE_DRUPAL=1 (full check and drupal-test do this) requires setup and
fails if absent. Prepared but unreachable site fails. Tests run sequentially
because debugger port is shared.

Setup was rerun idempotently; public URL returned200. Composer validation used
`ddev exec composer validate --strict --no-check-all`: exact fixture pins trigger
style warnings under unrestricted strict validation; no-check-all suppresses
those while validating metadata. Do not unpin core just to silence this warning.

## 11. Verification history and evidence boundaries

Milestones: initial64 -> controller120 -> server155 -> browser/cancel/matrix/
stress193 -> proxy/shell248 -> expr/exec/spawnpoints352 -> paths405 -> Drupal408
-> setup/pytest447 -> protocol review491 -> release preparation500 -> follow-up
review fixes514. Counts describe specific milestones, not a current host result.

Latest full command and evidence:

```sh
./scripts/check.sh
```

- **514 passed, no failures/errors/skips**, DDEV Python 3.13.5. Current
  `test-results/junit.xml` reports time 297.360 seconds and timestamp
  `2026-10-27T21:05:51.143105+00:00`. Includes all four required Drupal cases,
  six runtime combinations, real proxy/browser, setup, cancellation and stress.
- **50 focused tests passed** in `test-results/review-fixes-junit.xml`: the 14
  current review regressions, setup/network tests and real browser cleanup.
- The full script also passed strict Poetry metadata/lock checks, two identical
  builds, exact archive inspections, bare wheel/source installs and HTTP/TCP
  snapshot/reconnect probes. Core imports require neither pytest nor Playwright.
- Both installed formats ran the real PHP first-breakpoint walkthrough; the
  installed wheel ran standalone and pytest examples using actual Chromium/PHP.
  These close the first client, reconnect/mutate/step/detach, and verify output
  or DOM. The core remains stdlib-only. See the candidate below for copied logs.
- At the earlier 500-test milestone, fast suites passed 464 tests on each of
  macOS/Python 3.12.9 and Linux/Python 3.13.5, with 36 integration cases deselected.
  Those earlier artifacts also matched between platforms. This observation does
  not establish a passing latest host check or universal build reproducibility.
- Tests were not rerun merely to update this handoff. Existing XML/manifests and
  source were checked; the current implementation matches the validated candidate.

### Fresh protocol/lifecycle review (section 2)

`docs/protocol-review.md` records the trace and **14 fixed findings (R01–R14)**;
regressions are in `tests/test_review.py` and `test_review_browser.py`. The review
added 44 cases and reached 491 full-suite tests. Fixes cover UTF-16 DTD bypass,
negative property metadata, invalid continuation states, cancelled queue claims,
late breakpoint/capability acknowledgements, lost HTTP requests, bounded closed
retention/handshakes/commands/HTTP workers, concurrent startup/failure cleanup,
postmortem gates, HTTP writer cleanup and browser capture/route/action cleanup.
Preserve Xdebug's vendor `state="temporary"` breakpoint notifications; restricting
reply states to enabled/disabled previously broke real Xdebug.

Default resource policy: engine packets 16 MiB; pending plus abandoned commands
1024/session; live plus initializing engine connections 256; controller error
history 50; event queue/history 1024; HTTP workers 128; request body 1 MiB; client
response 64 MiB; retained closed records 128. Existing idle live sessions are not
resumed/evicted to admit new ones. Limits count records/packets, not total heap
bytes. See the review for constructors and documented direct-shutdown, handshake
deadline, raw-command, outage and no-exactly-once limitations.

Optional live-engine investigation is complete, not pending adoption:
`scripts/investigate_optional_engines.py` and
`test-results/optional-engines.json` record pinned `agroszer/komodo-python3-dbgp`
commit `aa277c0055dffb597777bba49d4eb65d30af02a0`, version `11.1.2.dev0`, declared
MIT Python component and stdin/interact handlers. Its actual launcher fails on
Python 3.13.5 because `imp` was removed in 3.12. The recorded upstream check
found the same commit at head, not an overlooked newer working version. Tcl
redistribution suitability was not established; ruby-debug-ide speaks a different
protocol. No additional live fixture or third-party runtime dependency was added.
Optional-extension successes remain explicitly scripted-peer coverage.

### Follow-up bug review and fixes (CR01–CR04)

The user requested a separate bug-focused review, then probes/TODOs, then fixes.
All four P2 issues are now fixed in the normal suite:

1. `playwright.py`: cancelled `PausedBrowser.close()` previously marked the
   capture closed and discarded ownership before its RPC finished. A shared,
   shielded cleanup task stays tracked through session/action cleanup. The test
   cancels before RPC submission, joins concurrent close calls, and proves the
   session is released with exactly one cleanup request.
2. `config.py`, `setup.py`, `cli.py`: file token lookup previously ran before
   explicit overrides. Overrides now reach loading first. API token/None and CLI
   argument/environment precedence work even if the shadowed variable is absent;
   an unshadowed required variable still raises. Config structure remains checked.
3. `setup.py`: generated config previously used JSON surrogate-pair escapes,
   rejected by TOML for emoji/non-BMP paths. It now writes UTF-8 and compatible
   escapes, including DEL. Actual owned launches test Unicode/control paths and
   path translation.
4. `server.py`: a configured alternative loopback listener such as 127.0.0.2
   previously rejected its advertised URL's Host header. That configured endpoint
   is accepted; an unconfigured alternative loopback, unrelated Host and Origin
   remain rejected.

`tests/test_review_findings.py` originally had nine strict xfails. They were
verified as real failures with `--runxfail`; after fixes all markers were removed
and five boundary cases added. **All 14 pass in DDEV**. The capture probe uses a
scripted peer over real HTTP/TCP, not PHP/Chromium. Other tests cover live cleanup.

### Current release workflow and unpublished artifacts

Provider-independent implementation is finished; no hosted pipeline is selected.

- `scripts/check_fast.sh [junit-path]`: strict metadata/lock validation and
  `pytest -m 'not integration'`. Needs dev dependencies and loopback sockets;
  does not need Docker/PHP/browser. Current collection is 514 total, 478 selected.
- `scripts/check_distribution.py`: stdlib frontend around fixed Poetry core
  2.1.1 with checksum-verified backend wheel, clean allowlisted exports, normalized
  modes/times and SOURCE_DATE_EPOCH (default 315532800). Builds wheel/source twice,
  compares bytes and verifies exact archive inventories/hashes, typing/license/
  NOTICE/CLI metadata and absence of runtime dependencies/extras/vendor fixtures.
- Independent fresh wheel and sdist environments run copied
  `scripts/probe_install.py` outside the checkout. Source installation uses pip
  isolation and the local verified backend wheelhouse. The core round trip is a
  real HTTP/TCP exchange with an original scripted engine, not a live PHP claim.
- `--live-php` runs `examples/first_breakpoint.py` from both formats: generated
  temporary PHP, snapshot, first-client closure, reconnect/inspect/mutate/step,
  detach, real output 85. `--live-browser` runs `check_setup_examples.py` against
  the wheel; optional tool versions are recorded separately from runtime deps.
- `--suite-junit` rejects failures/errors/skips and incomplete required-fixture
  evidence. Reports are copied as supplied, not cryptographic attestations of an
  arbitrary source state. `check.sh` runs tests then validation in one checkout.
- Source archive includes maintained code/docs/examples/scripts/lock/license;
  excludes generated fixtures/vendor/reference code, tests, handoffs/TODO and
  local evidence. Validate before claiming support or publishing changed inputs.

Full-suite-validated candidate before the local handoff additions (supersedes
the earlier 500-test candidate for the reviewed implementation):

`dist/release-candidate/20261027T211106676266Z-1993e889/`

- Wheel SHA-256: `8e50c81891d3387a5ca9527e6740c4a83b69b56cffad837fdc00299fc4485e67`
- Source SHA-256: `8269a3a1a52ced20edc2232e855e8d5661d4d511146e09eeeb46b6af8686a263`
- `validation.json` status `validated-unpublished-candidate`; all requested
  checks true, copied full suite 514. `published=false`, destination null and
  authorization false. Source manifest/inputs and artifact hashes were checked
  at that milestone; packaged docs/examples have since changed.
- Includes artifacts, `SHA256SUMS`, source/contents inventories, logs, copied
  evidence and `CHECKLIST.md`. Every validation invocation makes a new directory.
- Historical pre-fix runs: `dist/release-candidate/20261027T162534350311Z-2e27a728/`
  and `dist/release-candidate-py312/20261027T162304864691Z-57ad3363/`. Their platform
  equality was observed then; do not use their hashes for the fixed code.

See `docs/installation.md`, `docs/releasing.md`, `docs/release-policy.md`,
`CHANGELOG.md`, `NOTICE.md`. Package/import/CLI/health version is 0.1.0; wire
protocol is independently dbgpilot/1. Pre-1.0 API compatibility and restart policy
are documented. Installing a new package does not upgrade a running daemon;
restart loses IDs and cannot rehydrate live debugging sockets. Future source or
packaged-documentation changes require a fresh candidate/hash check before any
publication. HANDOFF/TODO-only edits do not change distribution inputs.

### Latest host verification limitation: do not report it as passing

The macOS/Python 3.12.9 fast checks after the fixes are **not green**. The new
regressions passed except `127.0.0.2`, which the host cannot bind (EADDRNOTAVAIL).
That case passes in DDEV; do not silently remove it or broaden Host acceptance.

- `test-results/review-fixes-fast-py312.xml`: 474 passed, 3 failed, 1 skipped,
  36 integration cases deselected. Existing malformed-readiness child tests hit
  their two-second startup limit. The isolated three-case run reproduced those
  deadlines in `review-fixes-readiness-py312.xml`.
- An instrumented child probe saw no stdout before a two-second deadline;
  a subsequent ten-second-budget run delivered the malformed line in 1.759s.
  This is timing evidence, not proof that every host failure is environmental.
- A temporary change to that test budget (2 -> 10 seconds) was tried, then
  **reverted**. Current `tests/test_setup.py` retains its original two seconds.
- `test-results/review-fixes-fast-py312-verified.xml`: 473 passed, 4 failed,
  1 skipped, 36 deselected. The filename is misleading: the run did not pass.
  Failures: optional spawnpoint late-ack case timed out in handshake with its
  0.05s command budget; multi-process CLI test exceeded aggregate 8s; cancellation
  startup test exceeded its 5s entry wait; stress test saw unclosed subprocess/
  pipe warnings following the CLI failure. Reported CLI PID 25502 was checked
  afterward and had exited; do not kill a later unrelated process reusing its PID.

No unrelated timeout limits were relaxed and no production fix was inferred
solely from these host failures. Host deadline/test-failure cleanup stabilization
remains a separate verification follow-up. Preserve failures and inspect root
causes if asked to resolve it. The passing required DDEV check establishes the
recorded Linux behavior, not a passing current macOS suite.

Real runtime matrix: PHP8.2/8.3/8.4/8.5 with Xdebug3.5.3 plus PHP8.2/Xdebug3.3.2
and PHP8.3/Xdebug3.4.7. Earlier DDEV binaries were8.2.35/8.3.36; after container
recreation8.2.31/8.3.31 also passed.8.4.22/8.5.7 unchanged. compatibility.json
accumulates observations; ten recorded version pairs do not mean ten variants
were all run in a single suite. Historical source URLs/hashes are pinned in
scripts/prepare_test_runtimes.py; source/modules are dev tooling, not shipped.

Other meaningful tested scenarios:

- Protocol properties/framing fragmentation, arbitrary bytes, malformed XML,
  extended properties, notification mixed bodies, late/out-of-order replies.
- HTTP reconnects, auth/limits/error correlation, cancellation before submission,
  cancellation claiming races, event expiry and replay, async response handling.
- 64 pending session waits with responsive health/cancellation; eight independent
  scripted sessions; four simultaneous paused browser requests.
- 35-second pause after initial client closes; later client reconnects and
  completes browser request. DBGPILOT_TEST_PAUSE_SECONDS can deliberately vary
  this duration; report actual value if altered.
- Daemon shutdown/restart with paused browser and rejection of old IDs.
- Official dbgpProxy0.6.2 route, duplicate registration rejection, reconnect/
  mutation/completion, unregister cleanup, scoped stopped-EOF compatibility.
- General paths:42 path unit/property cases plus integration coverage (53 new
  cases at mapping milestone), Windows script paths against Linux server.
- Optional-command positive behaviour scripted only; actual Xdebug rejection is
  separately tested. No full-protocol or unlimited-throughput claim is justified.

### Local artifact handoff verification

`./scripts/release.sh` passed on host Python 3.12.9 with loopback access. The
first sandboxed attempt failed starting the installed probe's server; the
unsandboxed rerun passed without changing the validator. The successful run is
`dist/release-candidate/20261027T235458478745Z-e0868c44/`. It includes the new
quickstart, consumer starter and release wrapper in the source archive. Current
source hashes and artifact checksums match. It deliberately has no `full_suite`
evidence and remains unpublished.

The nine release contract checks passed. The installed-example checker verified
core isolation, standalone help and collection of both pytest examples outside
the checkout. A separate one-off check extracted `examples/consumer/` from the
source archive and ran it with the installed wheel against actual PHP/Xdebug
and Chromium in DDEV: one test passed in 18.67 seconds, including first-client
closure, reconnect, detach and successful browser navigation. This is focused
verification, not a new full-suite or fast-suite claim.

After the checkout move, `poetry install` repaired the host editable install.
DDEV's stale old-path registry entries were cleared and the parent project
started at the new path. Browser system dependencies were reinstalled in its
recreated container. The parent project was stopped after this focused check;
the Drupal fixture was not started or tested in this follow-up.

## 12. Remaining work: current agreed plan

Read `TODO.md`'s "Remaining work — Python integration and release readiness"
section for exact checkboxes. Sections 1 and 2 and CR01–CR04 are checked complete.
There is no remaining pytest integration implementation task for the agreed scope.
The current seven unchecked items are:

### Section 3: deferred operational choices (1 unchecked)

1. **CI:** choose provider, runners, per-change/scheduled/release triggers and
   required checks. Wire the existing fast/full/distribution scripts into that
   service with caches and retained failure evidence. No provider chosen yet.

Release publication is complete for the GitHub testing prerelease. The release
process, distribution automation, onboarding and metadata/compatibility policy
are checked off. PyPI remains deferred. Full-suite tests and hosted CI are
optional for this manual artifact handoff.

The user deliberately requested the build-pipeline-independent work. Keep those
deferred choices deferred unless a subsequent request changes the scope.

### Section 4: standalone DBGpilot skill (6 unchecked)

1. Create `../skills/dbgpilot/SKILL.md`, following that repository's guidance and
   precise discovery scope for interactive PHP/Xdebug debugging, with or without
   Python Playwright. This is not the removed MCP work package.
2. Document runtime/endpoint/trigger/mapping discovery and the investigation
   loop using the settled public APIs, not a second debugger controller.
3. Preserve pause ownership, concurrent browser actions, reconnectability,
   timeout distinctions, explicit cleanup and daemon/browser lifetime limits.
4. Add focused references and runnable examples verified against installed
   DBGpilot and actual PHP/browser; isolate DDEV/Drupal guidance when relevant.
5. Explain debugging authorization under consuming-project rules and connect
   `../skills/playwright/SKILL.md` through a short routing cross-reference,
   preserving its UCAS JavaScript test scope and explicit-request policy.
6. Validate frontmatter, links, routing and operational guidance for ordinary
   browser tests, browser/PHP debugging, PHP-only and Drupal/DDEV cases.

This skill work can proceed independently of CI/publication decisions when the
user asks. It has not been created or validated in this conversation. Read the
skill-creation workflow and actual sibling-repository guidance before editing.

Separate verification follow-up: investigate/stabilize the latest host fast-test
failures described in section 11 if requested. Do not silently relabel failures
as skips/xfails or equate the earlier green 3.12 milestone with a current pass.

## 13. Playwright architecture discussion: retain these conclusions

These points explain the language decision; avoid reopening the same mistaken
assumption on the next turn.

- Playwright has language-specific public APIs. Shared implementation/driver is
  largely TypeScript compiled to JavaScript, running on Node. Python's transport
  launches bundled Node/cli.js with run-driver and exchanges framed protocol
  messages; Python calls do not pass through a user's public JavaScript API wrapper.
- Diagram conceptually: Python API -> pipe -> shared Node backend -> browser
  protocol -> browser -> site. JS has its own client path into the shared backend.
- Extending or monkeypatching the public JS API does not automatically expose a
  feature to Python, Java, or .NET. Modifying internal driver protocol/bindings is
  a different, invasive integration and is not a documented universal plugin API.
- Documented extension patterns include fixtures (`test.extend` for JS runner,
  pytest fixtures for Python), Page Object Model/wrappers, custom selector engines,
  and JS custom matchers (`expect.extend`). Our helper fits Python wrapper/fixture
  patterns without forking Playwright internals.
- A Python pytest-level integration is directly Python-specific, but a persistent
  HTTP backend can serve clients in other languages. Each binding can have a thin
  convenience layer if a real need appears; TypeScript does not remove that work.
- User scripts are Python, so Python is the chosen implementation ecosystem.
  Earlier advice favouring TypeScript was corrected after this clarification.

MCP/PHP research was exploratory: an adapter over existing HTTP would preserve
daemon ownership better than replacing the debugger core, PHP long-running TCP
is technically possible, and a PHP DBGp library was found but not audited.
**User has rejected this direction.** There is no adapter work to resume.

## 14. Research sources / where to look next

These are sources already used in this conversation, not fresh validations of
their current contents. Recheck upstream documentation if making new claims.

- DBGp1.0draft22: https://xdebug.org/docs/dbgp (primary protocol specification).
- Proxy docs: https://xdebug.org/docs/dbgpProxy.
- Xdebug implementation: https://github.com/xdebug/xdebug/blob/master/src/debugger/handler_dbgp.c
  and src/debugger/debugger.c. Prefer spec/live engine evidence over references.
- Historical Python references and inspected revisions (removed dependencies):
  Komodo https://github.com/agroszer/komodo-python3-dbgp/tree/aa277c0055dffb597777bba49d4eb65d30af02a0;
  Vdebug https://github.com/vim-vdebug/vdebug/tree/66517871178779ac54e19ed0f34d66805b820664;
  Pugdebug https://github.com/Mte90/pugdebug/tree/d07044536f0bd5ab3cef3d178cc35a2e51e0e7a2.
  No implementation code is included/imported; Qt/transitive/vendor refs removed.
- Playwright: https://playwright.dev/docs/languages,
  https://playwright.dev/docs/library,
  https://playwright.dev/python/docs/library,
  https://playwright.dev/python/docs/test-runners,
  https://playwright.dev/docs/test-fixtures,
  https://playwright.dev/python/docs/extensibility,
  https://playwright.dev/python/docs/pom,
  https://playwright.dev/docs/test-assertions#add-custom-matchers-using-expectextend.
- Driver/client/server sources previously examined:
  microsoft/playwright-python playwright/_impl/_driver.py, installed _transport.py
  and _browser_type.py; microsoft/playwright packages/playwright-core/src/client/
  browserType.ts and server/dispatchers/browserTypeDispatcher.ts.
- Drupal fixture release: https://www.drupal.org/project/drupal/releases/11.4.11.
- DDEV: https://docs.ddev.com/en/stable/users/quickstart/#drupal,
  https://docs.ddev.com/en/stable/users/usage/architecture/.
- Local historical research: docs/python-xdebug-options.md,
  docs/vdebug-dbgp-audit.md; current design/provenance: docs/development.md.

## 15. Resumption checklist for the next LLM

1. Read the latest user message; this handoff is context, not automatic permission
   to execute every backlog item. Follow the scope of the latest user request.
2. Consult current TODO/source; preserve checked completed tasks and the user's
   decisions: Python, MIT, no reference runtime dependencies, no MCP.
3. If authorized to continue implementation, start with the requested remaining
   work package; inspect relevant files and settle routine API choices directly.
4. Preserve ownership/cancellation/late-response invariants and optional-engine
   evidence boundaries. Avoid implementing a second controller in integrations.
5. Run appropriate checks in DDEV; set required Drupal flag for a claimed full
   suite. Reinstall browser system dependencies after container recreation.
6. Update corresponding TODO checkboxes and documentation only when work is
   actually complete. Report tests/results and material limitations accurately.
