# DBGpilot TODO

The active JavaScript replacement work is tracked in [MIGRATION.md](MIGRATION.md)
on `migration/playwright`. Its test-owned sessions supersede this document's
earlier Python/pytest and cross-script daemon direction. The entries below are
retained as historical implementation and test-coverage references during migration.

Audit baseline: DBGpilot 0.1.0, 2026-10-26, compared with
[DBGp 1.0, draft 22](https://xdebug.org/docs/dbgp).

Entries started unchecked. Labels describe the audit baseline; checked entries
are now implemented or verified. **Existing** means a code path was already present
and the task was to verify its coverage; **Partial** means implementation work
remains; **Raw only** means `session.command(...)` can send a request and return
XML, but no dedicated method or decoder exists; **Missing** means there is no
usable implementation of the feature.

As work is completed, update the corresponding `[ ]` to `[x]` in this file.
Check off an item only after its stated implementation or verification is
complete, with appropriate tests. Existing test coverage does not establish full
protocol conformance. Keep engine limitations separate from controller gaps.
Use `[-]` for findings explicitly declined or left unchanged; this does not
mean the proposed change was implemented.

## Core commands — section 7

- [x] **Raw only — `status`:** Add a dedicated method returning a structured
  result. Raw responses already update `session.state`.
- [x] **Existing — `feature_get`, `feature_set`:** Verify arbitrary feature
  queries and settings, including recognition versus the returned value.
- [x] **Existing — `run`:** Verify execution-stop results and
  `run_until_break()` distinguishing a breakpoint from completion.
- [x] **Existing — `step_into`, `step_over`, `step_out`:** Verify all three
  operations and their structured execution results.
- [x] **Partial — `stop`:** Accept an engine disconnecting without a reply as a
  permitted termination outcome. The command and connection cleanup exist, but
  that outcome currently raises an error.
- [x] **Partial — `detach`:** Check optional-command support before use and
  define cleanup behaviour when the engine does not support it. Detaching works
  in the current harness.
- [x] **Existing — `breakpoint_set` types/options:** Verify encoding and engine
  responses for the six type names, expressions, temporary flags, and hit
  conditions. Do not equate request encoding with engine support.
- [x] **Partial — `breakpoint_set` initial state:** Allow creating a disabled
  breakpoint using the state option.
- [x] **Partial — conditional breakpoint scope:** Allow filename-wide
  conditional breakpoints without requiring a line number.
- [x] **Partial — breakpoint metadata:** Preserve function and exception names
  and attribute-form expressions in `breakpoint_get`/`breakpoint_list` results.
- [x] **Partial — breakpoint creation result:** Preserve the returned initial
  state and represent known requested settings accurately in the returned model.
- [x] **Existing — `breakpoint_update`:** Verify state, line, hit value, and hit
  condition updates.
- [x] **Existing — `breakpoint_remove`:** Verify removal by opaque ID.
- [x] **Raw only — `stack_depth`:** Add a dedicated method and decode the depth.
- [x] **Existing — `stack_get` frame selection:** Verify retrieval of all
  frames and a selected depth.
- [x] **Partial — stack metadata:** Preserve instruction offsets and nested
  input/source locations.
- [x] **Existing — `context_names`, `context_get`:** Verify context and
  stack-depth selection.
- [x] **Raw only — `typemap_get`:** Add a method and decoder for engine type
  mappings.
- [x] **Existing — `property_get`:** Verify depth, context, page, maximum data,
  key, and address options. Property-model gaps are tracked below.
- [x] **Existing — `property_set`:** Verify assignment with depth, context, and
  type, including binary and empty values through the PHP assignment helpers.
- [x] **Partial — `property_set` address:** Expose address targeting.
- [x] **Partial — assignment portability:** Make PHP-specific assignment
  semantics explicit and define how other engines are handled.
- [x] **Existing — `property_value`:** Verify full-value byte retrieval,
  overriding the configured data limit.
- [x] **Partial — `property_value` options:** Expose page, key, and address
  targeting.
- [x] **Partial — `property_value` metadata:** Preserve the reported size so
  callers can assess the returned data.
- [x] **Existing — `source`:** Verify current/file source, line ranges, and
  unchanged `dbgp:` virtual-file URIs.
- [x] **Existing — `stdout`, `stderr`:** Verify disable, copy, and redirect
  modes and separate stream events. Current live coverage exercises stdout
  copying; distinguish other wire-level coverage from engine support.

## Extended commands and notifications — section 8

- [x] **Raw only — `stdin`:** Add input-redirection and data-sending methods,
  including delivery during execution where the engine permits it. Covered with
  async engines and synchronous engines sending stdin-read notifications.
- [x] **Existing, engine-dependent — `break`:** Verify `interrupt()` with an
  asynchronous scripted engine, including the separate outstanding run response.
  The tested Xdebug reports `supports_async=0`, so live interruption is unavailable
  there.
- [x] **Existing — `eval`:** Verify current-frame evaluation, result paging,
  and valid responses without a property result.
- [x] **Partial — evaluation depth:** Define capability-aware handling of
  nonzero depth. The current API rejects it because the tested Xdebug ignores
  it; this is not a universal limitation of the protocol.
- [x] **Partial — evaluation execution state:** Manage evaluation as execution,
  including concurrency guards, timeouts, cancellation, and interleaved events.
  It currently lacks the execution-state management used by run/step methods.
- [x] **Raw only — `expr`:** Add a dedicated method and result handling.
- [x] **Raw only — `exec`:** Add a dedicated method and result handling.
- [x] **Raw only — `spawnpoint_set`:** Add a dedicated method and model.
- [x] **Raw only — `spawnpoint_get`:** Add a dedicated method and decoder.
- [x] **Raw only — `spawnpoint_update`:** Add a dedicated method.
- [x] **Raw only — `spawnpoint_remove`:** Add a dedicated method.
- [x] **Raw only — `spawnpoint_list`:** Add a dedicated method and decoder.
- [x] **Existing — notification dispatch:** Verify independent notification
  events, name/XML preservation, and simple body decoding.
- [x] **Partial — `breakpoint_resolved`:** Decode a structured breakpoint event
  and define how callers receive updated breakpoint state.
- [x] **Partial — `error` notifications:** Decode structured error information
  while retaining vendor data.
- [x] **Defect — mixed-content notification bodies:** Include body data after
  child elements in `NotificationEvent.data`. The audit reproduced an empty
  result for a base64 body following a message child; the XML is retained.
- [x] **Missing — `interact`:** Add shell buffering/prompt results and support
  the `interactive` state, engine-owned buffering, reset, inspection, events,
  and cancellation/late replies.

## Sessions, transport, and data — sections 5–6 and 7.11–7.12

- [x] **Existing — listener and initialization:** Verify incoming engine
  connections, initialization validation, rejection reporting, and cleanup.
- [x] **Partial — initialization metadata:** Retain session cookie, thread,
  parent, proxied address, engine details, and other vendor information.
- [x] **Existing — multiple sessions:** Verify independent connections,
  transaction tables, and simultaneously paused sessions.
- [x] **Partial — process/thread relationships:** Expose retained thread and
  parent metadata for callers to relate sessions.
- [x] **Existing — framing:** Verify byte lengths, delimiters,
  fragmented/coalesced reads, encoding boundaries, and packet limits.
- [x] **Existing — command construction:** Verify unique transaction IDs,
  argument escaping, and base64 payloads, including binary and empty data.
- [x] **Existing — response/event dispatch:** Verify command-name/transaction
  correlation independently of streams and notifications.
- [x] **Existing — engine command errors:** Verify numeric codes/messages and
  recovery for subsequent commands.
- [x] **Partial — extended error information:** Preserve vendor error
  attributes/elements instead of discarding them.
- [x] **Existing — feature setup:** Verify configurable startup settings,
  asynchronous-support discovery, and unsupported optional-feature handling.
- [x] **Partial — capability discovery:** Add an engine capability inventory
  and capability-aware command handling, including optional commands,
  breakpoint types, and postmortem inspection.
- [x] **Partial — communication encoding:** Handle or explicitly constrain
  negotiated encodings consistently. XML follows its encoding declaration, but
  outbound commands and textual values currently assume UTF-8.
- [x] **Existing — properties:** Verify standard and extended formats, binary
  values, NUL-containing names, fullnames, class names, and child order.
- [x] **Existing — paging and truncation:** Verify direct-child pagination,
  full-value retrieval, and explicit truncation indicators.
- [x] **Partial — property facets/constants:** Preserve `facet` and `constant`
  metadata in property models and JSON.
- [x] **Partial — property identity in JSON:** Include key/address metadata in
  snapshot serialization; these currently survive only in Python properties.
- [x] **Existing — common types:** Verify direct decoding of supported PHP
  scalar types and JSON-safe binary/nonfinite values.
- [x] **Partial — engine-specific types:** Interpret engine-provided type
  mappings instead of relying only on hardcoded scalar names.
- [x] **Existing — file URIs:** Verify absolute-path conversion and preservation
  of explicit remote/virtual URIs. Automatic local/remote path mapping is a
  separate convenience feature.
- [x] **Missing — proxy registration:** Implement `proxyinit` and `proxystop`
  using the separate proxy connection workflow.
- [x] **Missing — proxy errors:** Handle `proxyerror` packets rather than
  rejecting them as unexpected packet types.

## DBGpilot conveniences and validation

- [x] **Existing — break and return:** Verify JSON-safe snapshots leave PHP
  paused and available for later inspection, stepping, mutation, or detach.
- [x] **Existing — snapshot independence:** Verify prior snapshots remain
  unchanged after later engine mutations.
- [x] **Existing — lifetime management:** Verify timeouts, cancellation/late
  replies, disconnects, event queue limits, and bounded cleanup.
- [x] **Completed — priority conformance coverage:** Add regression tests for
  audit priorities 1–5: notifications/evaluation, core wrappers, options/metadata,
  stop EOF, capability negotiation, and the associated protocol edge cases.
  The original baseline was 64 tests; validation and current counts are recorded
  in the completion notes below.
- [x] **Partial — remaining conformance coverage:** Cover optional extensions
  as they are implemented. Passing priority tests is not full DBGp conformance.
- [x] **Partial — engine/version coverage:** Test beyond the current PHP
  8.4.22 / Xdebug 3.5.3 harness and distinguish live, scripted-peer, and parser
  coverage in reports.

## Implementation order

Implementation followed notification-body decoding and evaluation concurrency,
then the three core wrappers (`status`, `stack_depth`, `typemap_get`), core
options/metadata, termination semantics, and capability negotiation. The optional
extensions now also have dedicated APIs and coverage. All entries in this audit
checklist are checked; this records completion of the listed tasks, not full
protocol conformance or live support in every engine.

Source references: [session API](src/dbgpilot/session.py),
[models and decoders](src/dbgpilot/models.py),
[transport](src/dbgpilot/protocol.py),
[controller](src/dbgpilot/controller.py), and [tests](tests/).

## Persistent server and script clients

- [x] Own the controller in a persistent server process, independently of client
  connections, and expose a local HTTP/JSON API.
- [x] Add an async Python `Client` and reconnectable `RemoteSession` handles with
  JSON-safe results and binary assignment support.
- [x] Provide `dbgpilot serve`, `dbgpilot call`, and `python -m dbgpilot` entry
  points, readiness output, structured CLI errors, and graceful signal handling.
- [x] Claim matching sessions by IDE key, cookie, application ID, or file without
  consuming unrelated requests; preserve stable IDs across client lifetimes.
- [x] Add `break_and_return` to return a snapshot while PHP remains paused.
- [x] Guard concurrent operations per session while keeping metadata, event
  polling, and supported asynchronous status/interrupt calls available.
- [x] Continuously drain debugger events into bounded, replayable histories with
  independent cursors, long polling, and explicit history-expiration errors.
- [x] Add explicit close/forget operations and bounded retention of closed
  sessions; do not evict or automatically resume idle live sessions.
- [x] Expose controller methods through an explicit allowlist, validate JSON
  requests/limits, and support optional bearer authentication.
- [x] Verify reconnects, independent clients, lost HTTP connections, timeouts,
  diagnostics, event replay, cleanup, and shutdown using real HTTP/TCP tests.
- [x] Prove a separate CLI client can return a live PHP HTTP snapshot and exit,
  after which another client mutates PHP and completes the same request.
- [x] Document the API, wire format, limits/lifetimes, client cancellation
  semantics, a runnable HTTP harness, and Python/JavaScript Playwright usage.
- [x] Run real browser acceptance tests for the Playwright helper, including
  navigation, form submission, AJAX, client reconnection, PHP mutation, and DOM
  assertions. Chromium is installed by `ddev test-setup`.

Server milestone validation: 155 tests passed in DDEV, including 8 live PHP/Xdebug tests
and 34 HTTP/server tests. The standalone server plus two-client HTTP example
passed. The wheel/source distribution build, and the wheel's imports and CLI
entry point work in a separate environment with no runtime dependencies.

## Completion notes — first five priorities

Implemented the five priorities from the audit discussion: fixed notification
body decoding and evaluation concurrency; added `status()`, `stack_depth()`, and
`typemap_get()`; preserved metadata and added missing core options; handled
permitted stop EOF and negotiated capabilities; and added regression coverage.

The API guide documents `property_value_info()` (metadata plus bytes), structured
notifications, read-only capability/type/breakpoint inventories, evaluation
cancellation, and the UTF-8 / Xdebug byte-framing policies. `stop()` and `detach()`
now return `ExecutionResult` objects. Postmortem inspection and optional commands
respect advertised engine support.

Controller milestone validation: 120 tests passed inside DDEV, including 7 live PHP/Xdebug tests.
The rest use scripted TCP peers and parser/property tests. The current real
engine at that milestone was PHP 8.4.22 / Xdebug 3.5.3. The expanded matrix below
now covers more PHP/Xdebug versions; optional extensions were still unchecked at
that milestone and are covered in the later completion notes.

## Browser helper, cancellation, compatibility, and stress tests

- [x] Build `PlaywrightDebugger`, `BreakpointSpec`, and `PausedBrowser` with
  one-request routing, unique trigger/IDE-key correlation, reusable capture
  specifications, snapshots, reconnects, and explicit/context-managed cleanup.
- [x] Exercise actual Chromium, PHP-FPM, Xdebug, and the server end to end;
  inspect/mutate through a later client and assert the rendered total.
- [x] Support form and AJAX actions, including clicks that complete before PHP,
  action/setup failures, capture deadlines, route cleanup, and long navigation
  pauses without a browser deadline.
- [x] Add explicit `RemoteRequest` IDs/results/cancellation and `cancel_request`
  acknowledgements; block delayed submission using bounded cancelled-ID history.
- [x] Cancel remote calls when a Python coroutine or Client closes, preserve
  engine execution state, and prevent cancelled waits from claiming future PHP.
- [x] Preserve replayable events across cancelled polls and late engine replies;
  reject ambiguous and self-cancellation rather than cancelling the wrong call.
- [x] Use native async HTTP for clients so long polls do not occupy a limited
  worker pool; verify malformed/truncated responses, limits, and correlation.
- [x] Run six real runtime combinations: PHP 8.2–8.5 with Xdebug 3.5.3, plus
  PHP 8.2/Xdebug 3.3.2 and PHP 8.3/Xdebug 3.4.7.
- [x] Provide checksum-pinned historical builds, browser installation, cache
  setup, matrix result JSON, JUnit output, and reproducible test commands.
- [x] Verify 64 pending waits with responsive health/cancellation, eight
  independently reconnecting sessions, and four simultaneous paused browsers.
- [x] Verify a 35-second pause after client closure and shutdown/restart during
  a paused browser request, including rejected old session IDs.
- [x] Update usage, cancellation semantics, helper API, and compatibility/stress
  documentation. Runtime dependencies remain empty; Playwright is a dev tool.

Validation for these four items: all 193 tests passed in DDEV, including the
actual Chromium helper tests, six PHP/Xdebug runtime combinations, 64 pending
waits, four simultaneous paused browser requests, a 35-second pause, and server
restart. Failed-setup capture retries are exercised repeatedly. The setup
command and runnable Chromium example also passed. JUnit and exact runtime
results are in `test-results/`; the tested combinations are documented in
[docs/compatibility.md](docs/compatibility.md).

## Proxy registration, proxy errors, stdin, and interactive shells

Implemented all four items through the direct controller, persistent server,
and Python client. Proxy control uses separate bounded connections, preserves
response metadata and opaque errors, and unregisters successfully owned keys
on shutdown. CLI startup can register before readiness. Proxy errors are handled
both before initialization and as independent established-session events.

Stdin supports configuration and text/binary data, independent input locking,
async/read-notification gating, and late acknowledgements. Interaction supports
the interactive state, structured prompts and continuation flags, engine-owned
buffering/reset, inspection, streamed events, and execution cancellation.
Both optional commands respect advertised support; the tested Xdebug rejects
them cleanly. Positive behaviour is covered by scripted TCP engines.

Validation: **248 tests passed in DDEV**, including live PHP through official
dbgpProxy 0.6.2, client reconnection, variable mutation, successful application
completion, duplicate registration errors, unregister on shutdown, and live
Xdebug capability rejection. The proxy binary is checksum-pinned development
tooling outside the package. Its suppressed terminal reply is handled only for
known/explicitly configured proxy sessions; execution results expose
`response_received` so inferred EOF remains distinguishable from a reply.

Usage and limitations: [proxies and optional shells](docs/proxies-and-shells.md).
Passing these tests does not establish support for the remaining unchecked
extensions or full protocol conformance.

## Expressions, code execution, spawnpoints, and extension coverage

Implemented the final four work packages: dedicated `expr` and `exec` methods,
the complete five-command spawnpoint family, and optional-extension conformance
coverage. The controller, server allowlist, and Python client expose all seven
commands with individual capability checks. Runtime dependencies remain empty.

Expr returns decoded properties (or None for explicit failure); exec returns a
boolean success flag. Both manage execution ownership, streams/notifications,
timeouts/cancellation, late replies, errors, and interactive/postmortem state.
Successful expr responses require a property; malformed results fail explicitly.

Spawnpoint APIs preserve opaque IDs, returned state, file/line, and vendor
metadata/XML in a separate model and read-only inventory. Set/get/list/update/
remove acknowledgements update that inventory even after caller cancellation.
Invalid responses do not commit partial inventories. Server metadata retains
the inventory for reconnecting clients.

Validation: **352 tests passed in DDEV**, including 104 new scripted TCP/HTTP
cases and the existing live browser, proxy, six-runtime matrix, and stress
checks. Actual Xdebug cleanly rejects all seven unsupported commands and remains
usable through PHP completion. Positive optional-command behaviour is tested
with scripted engines, not claimed as PHP/Tcl runtime support. Poetry lock
validation and wheel/source builds passed; the wheel installs/imports independently
without runtime dependencies or Playwright.

Usage and limits: [optional commands](docs/optional-commands.md). This completes
the existing audit checklist; broader engine testing and formal conformance
validation remain separate work.

## General-purpose path mapping

- [x] Add reusable configured directory-root mappings in both directions, with
  longest directory-prefix matching and explicit engine-URI bypass.
- [x] Support POSIX, Windows drives/UNC paths, URI escaping/application bytes,
  lexical normalization, case policies, and clear conflict/unmapped diagnostics.
- [x] Translate breakpoint/source/spawnpoint file arguments and server file
  filters, preserving raw command access to engine paths.
- [x] Preserve engine URIs and add local locations/diagnostics to initialization,
  stacks and nested inputs, execution/breakpoints, spawnpoints, notifications,
  snapshots, inventories, and replayed events.
- [x] Load project `dbgpilot.toml`, explicit config files, and repeatable CLI
  overrides; expose mapper configuration/translation through the async client
  and server without reading ambient configuration in library constructors.
- [x] Verify pure path behaviour, TCP/HTTP/CLI integration, real PHP breakpoint/
  source/snapshot translation, and actual Chromium with Windows paths against
  a Linux server, including client reconnection and PHP mutation.

Validation: **405 tests passed in DDEV**, including 53 new mapping tests.
Poetry configuration/lock checks and source/wheel builds passed. The wheel
installs and exposes the mapper/CLI without third-party runtime dependencies.
The mapping is environment-configured and does not infer mounts, follow symlinks,
copy source files, or alter network routing. See [path mapping](docs/path-mapping.md)
and [example configuration](dbgpilot.example.toml).

## Real application trial — Drupal 11

- [x] Add a separate DDEV Drupal 11 project with its own MariaDB database,
  pinned Composer dependencies, Drush tooling, and cross-container Xdebug routing.
- [x] Provide repeatable setup with a fixture-owned admin account, basic-page
  type/body/display, and page with fixed UUID; retain existing unrelated content
  and refuse to reinstall over a populated unbootstrappable database.
- [x] Break in actual Drupal core rendering, return node values and the active
  Fiber stack, reconnect, mutate/step/detach, and verify a fresh request still
  reads the original database title.
- [x] Submit the ordinary authenticated node form, pause before the entity save,
  reconnect/mutate/step/resume, and verify persisted content on a fresh request;
  delete the test-owned created node afterward.
- [x] Exercise the actual author-autocomplete AJAX widget, inspect/change its
  matcher query, step through the database lookup, resume, and assert a result
  in Drupal's menu while keeping browser-action/HTTP completion distinct.
- [x] Add focused/full test commands, required-fixture validation, runtime/frame
  JSON evidence, a screenshot, setup/network/path-mapping docs, and package
  exclusion checks for generated Drupal/vendor code.

Validation: **408 tests passed in DDEV, no skips**, including all three Drupal
acceptance scenarios. The fixture runs Drupal 11.4.11 / PHP 8.4.22 / Xdebug 3.5.3 /
MariaDB 11.8.8 with Drush 13.8.0. Setup was rerun successfully without reinstalling
the database. The public site returned HTTP 200. Composer validation passed with
`--strict --no-check-all` (exact version constraints are intentional fixture pins),
Poetry checks/builds passed, and both distributions exclude fixture/vendor code.
Python runtime dependencies remain empty. The actual render-Fiber boundary in
Xdebug's stack is preserved and documented; parent HttpKernel frames are not
invented. See [the Drupal guide](docs/drupal.md).

## Remaining work — Python integration and release readiness

The controller, persistent HTTP server, async Python Playwright helper, path
mapping, and Drupal trial are implemented. The work below builds on those APIs.
Keep the controller and session ownership in Python, keep the HTTP/JSON API
usable by other languages, and preserve the ability to return a snapshot while
PHP remains paused across client calls. A TypeScript rewrite is outside this plan.

Python usability and the fresh protocol/lifecycle review are complete.
Recommended next steps: write the skill against the settled Python API, then
finish release preparation. Completion status is recorded below;
the completed audit above remains a record of earlier work. The latest full-suite
baseline is 628 passing tests on 2026-10-30, including the required Drupal fixture.
The 2026-10-29–30 review below records the subsequent fixes and decisions.

### Follow-up code review (2026-10-27)

All four confirmed findings are fixed. The original nine expected-failure cases
are now ordinary passing regressions; five additional cases check required-token
validation, escaped path characters and rejection of an unconfigured Host.
See [test_review_findings.py](tests/test_review_findings.py). Its capture probe
uses a scripted engine over real HTTP/TCP, not live PHP/Chromium. The alternative
loopback case needs a host that can bind `127.0.0.2` (DDEV supports it); it skips
only when the operating system reports that address unavailable. All fourteen
cases passed in DDEV without skips or expected failures.

- [x] **CR01 — P2: retain cleanup ownership when `PausedBrowser.close()` is
  cancelled.** `src/dbgpilot/playwright.py` now uses a shared, shielded close task
  per capture. Cancelling a waiter leaves cleanup running and tracked until the
  session-close attempt and action cleanup finish. Concurrent handle/helper
  close calls await the same task. The regression verifies retained ownership,
  eventual session release, and exactly one cleanup RPC after cancellation.
  Regression: `test_cancelled_paused_close_still_allows_cleanup`.
- [x] **CR02 — P2: apply authentication precedence before requiring a configured
  environment variable.** Configuration loading now accepts API/CLI overrides
  before resolving `connection.token_env`. Explicit API tokens (including
  `None`), CLI `--token`, and CLI `DBGPILOT_TOKEN` can shadow a missing variable.
  Without an override, the configured variable remains required; three control
  cases verify that rejection through file, setup and CLI loading. Regressions:
  `test_api_token_override_does_not_require_shadowed_environment` and
  `test_cli_token_override_does_not_require_shadowed_environment`.
- [x] **CR03 — P2: serialize owned-launch mappings as valid TOML for Unicode
  paths.** `DebuggerSetup._launch()` writes UTF-8 strings without JSON surrogate
  pairs, preserving TOML-compatible escaping for quotes, backslashes and control
  characters, including DEL. Both an emoji path and a path containing escaped
  characters pass an actual owned CLI launch and remote path translation.
  Regression:
  `test_owned_launch_preserves_non_bmp_mapping_path`.
- [x] **CR04 — P2: align accepted loopback listeners and HTTP Host validation.**
  Host validation now accepts the configured listener in addition to the existing
  loopback aliases. `Server(host="127.0.0.2", ...)` accepts its own client URL;
  an unconfigured `127.0.0.2` Host still receives HTTP 403 when the listener is
  `127.0.0.1`. Existing unrelated-Host and Origin rejection tests also pass.
  Regression:
  `test_alternative_loopback_listener_accepts_its_advertised_url`.

Initial regression validation (2026-10-27): the focused DDEV run reproduced all **nine
strict expected failures**. Running the same tests with `--runxfail` produced
nine failures at the intended bug locations. The DDEV fast check passed with
**464 passed, 9 xfailed, 36 integration cases deselected**, in 95.88 seconds.
Evidence: `test-results/review-findings-junit.xml` and
`test-results/review-fast-junit.xml`. No implementation fixes had been applied
at that milestone.

Fix verification (2026-10-27): **50 focused tests passed** across the review
regressions, setup/network contracts and live browser cleanup. The required
`./scripts/check.sh` then passed **514 tests, zero failures/errors/skips**, plus
distribution metadata, contents, two byte-identical builds, separate fresh
wheel/source installations, real HTTP/TCP reconnect probes, real PHP onboarding
from both formats, and installed-wheel standalone/pytest Chromium examples.
Evidence: `test-results/review-fixes-junit.xml` and `test-results/junit.xml`
(297.360 seconds, timestamp `2026-10-27T21:05:51.143105+00:00`). Python was 3.13.5
in DDEV; Drupal and the six-runtime matrix remained required.

The updated unpublished candidate is
`dist/release-candidate/20261027T211106676266Z-1993e889/`.
Its source manifest matches the current release inputs and its recorded artifact
checksums were independently checked. It supersedes the earlier section 3
candidate for this code; nothing was published. SHA-256:

- Wheel: `8e50c81891d3387a5ca9527e6740c4a83b69b56cffad837fdc00299fc4485e67`
- Source: `8269a3a1a52ced20edc2232e855e8d5661d4d511146e09eeeb46b6af8686a263`

Additional host verification is **not green**. The Python 3.12.9/macOS fast
run passed the new regressions except the unavailable loopback address case,
but hit three existing two-second malformed-readiness deadlines. An isolated
probe confirmed that the child could produce no output before that deadline.
A temporary ten-second test budget resolved those cases on rerun, but other
existing short handshake/CLI/startup deadlines expired and a timed-out CLI test
left resource warnings observed in the stress test. That experimental budget
change was reverted; no unrelated test limits were relaxed. Host reports are
`test-results/review-fixes-fast-py312.xml` (474 passed, 3 failed, 1 skipped) and
`test-results/review-fixes-fast-py312-verified.xml` (473 passed, 4 failed,
1 skipped), each with 36 integration cases deselected. The latter filename
does not indicate a passing result. The reported CLI child was checked and had
exited. Stabilizing the host test deadlines and failure-path test cleanup remains
a separate verification follow-up; these host runs do not replace the passing
required DDEV check or establish a passing host fast suite.

### Follow-up code review (2026-10-29–30)

Consolidated from the former `POTENTIAL-BUGS.md` review against commit
`3836661`. The original item numbers are retained as PB01–PB12.
Nine fixes or cleanups are complete, two changes were explicitly declined,
and one path-mapping design decision remains open. Descriptions below record
the original failure and current outcome rather than proposing completed work
again. Source references use symbols/files instead of obsolete line numbers.

- [x] **PB01 — Defect: avoid duplicate stops for on-time evaluations.**
  Status-less `eval`, `expr`, and `exec` replies previously emitted an extra
  `StoppedEvent` for the existing pause. Repeated evaluations or snapshot
  expressions could fill the event queue and close the session; HTTP consumers
  could mistake the extra events for new pauses. `Session._dispatch_response`
  now identifies abandoned waits, including already-cancelled futures, and
  `_finish_execution` emits the recovery stop only for abandoned evaluations.
  Ordinary evaluation restores inspectability without publishing another stop.
  Coverage: [evaluation events](tests/test_evaluation_events.py), including
  repeated calls, snapshots, event cursors, late replies, and real step events.
- [x] **PB02 — Defect: preserve empty arrays after loading a typemap.**
  Mapping PHP `array` to the DBGp common type `hash` previously sent empty
  arrays through scalar decoding, producing `value == ''` and `raw_value == b''`.
  `parse_property` now treats `hash` as non-scalar: an empty array retains its
  array type with `value` and `raw_value` set to `None`; empty strings remain
  empty strings. Coverage: [property decoding](tests/test_properties.py) and
  [conformance](tests/test_conformance.py), with standard/extended properties,
  typemaps, nested arrays, and session read/evaluation paths.
- [x] **PB03 — Defect: accept authenticated hostname listeners.**
  `Server(host="myhost.example", token="secret")` previously raised while
  parsing the hostname as an IP literal. Authentication is now considered
  before literal-address validation. Startup resolves addresses and selects
  the matching IPv4/IPv6 socket family, trying resolved bind candidates and
  preserving no-token loopback restrictions. Coverage:
  [listener hosts](tests/test_server_hosts.py), including DNS failure cleanup,
  real HTTP requests, both address families, and unauthenticated-host controls.
- [ ] **PB04 — Design decision: allow overrides by remote mapping root?**
  `PathMapper.with_overrides` replaces a rule only when the normalized local
  root matches. Given `./src -> file:///var/www/html`, a CLI override from
  `./other` to that same remote root retains both rules and fails with
  `Duplicate remote mapping root`. This matches the documented contract in
  [path mapping](docs/path-mapping.md), so it is not a confirmed implementation
  defect. Decide whether to extend overrides to replace matching remote roots
  too; such a change should use the mapper's normalized remote-key comparison
  and retain ambiguity checks. Editing the configured mapping or using
  `--no-config` already permits selecting another checkout. No behaviour change
  has been approved or implemented for this item.
- [x] **PB05 — Defect: decode binary evaluation arguments over HTTP.**
  Client `bytes` arguments use a base64 JSON envelope. The server previously
  left `evaluate`'s envelope as a dictionary, causing an encoding `TypeError`
  reported as invalid caller parameters. The server now decodes `evaluate`'s
  `expression`, sharing binary handling with `expr`'s `expression` and `exec`'s
  `code`. `Session.evaluate` also declares `str | bytes`.
  Coverage: [binary evaluation](tests/test_binary_evaluation.py), including
  local/HTTP calls, UTF-8 and arbitrary bytes, NUL/empty payloads, explicit
  envelopes, engine errors, and malformed-envelope rejection.
- [x] **PB06 — Defect: round-trip preserved bytes in assignment expressions.**
  `property_set` previously rejected engine-native expression strings containing
  surrogateescaped bytes with `UnicodeEncodeError` before sending a command.
  It now encodes text with `utf-8` and `surrogateescape`, retaining pre-encoding
  and `len(raw)` so DBGp's payload length counts bytes. This was a write-path
  inconsistency: reading a non-UTF-8 PHP value already returns raw `bytes`, and
  passing raw bytes to `property_set` already worked. Eight cases in
  [conformance](tests/test_conformance.py), under
  `test_property_set_preserves_payload_bytes_and_byte_length`, verify exact
  wire bytes/lengths for text and bytes, including mixed UTF-8/non-UTF-8/NUL data.
- [x] **PB07 — Defect: classify malformed context IDs as protocol errors.**
  Missing or invalid `context_names` IDs previously escaped as `TypeError` or
  `ValueError`, so HTTP clients received `-32602` as though their arguments
  were invalid. `Session.contexts` now raises `ProtocolError`; HTTP clients
  receive `-32005`. Coverage: [context names](tests/test_context_names.py), with
  missing, empty, nonnumeric, and fractional IDs over local/HTTP calls, valid
  IDs/names, empty replies, and a control preserving genuine caller errors.
- [x] **PB08 — Efficiency: prune closed records on lifecycle changes.**
  `_collect_events` previously scanned all session records and sorted closed
  records under the shared condition lock for every event. It now prunes on
  `ClosedEvent`, retaining the existing cleanup when a session is registered.
  [Retention regressions](tests/test_server_retention.py) count record visits
  during ordinary events and verify eviction order, terminal events, retention
  limits of zero/one/three, and preservation of live sessions. The two scan
  cases failed before the fix and passed unchanged afterward.
  [Event collector benchmark](scripts/benchmark_event_collection.py): seven
  measured samples of 20,000 prebuffered events per case showed about 3.5x
  throughput with 128 closed sessions retained (5.4–6.2 seconds before,
  1.5–1.7 seconds after). No-history timings varied; this does not establish
  a 3.5x speedup for a complete debugging workflow. Raw samples and methodology
  are in `test-results/pruning-benchmark/`.
- [-] **PB09 — Declined: pipeline capability discovery.**
  `refresh_capabilities` currently makes 56 sequential `feature_get` queries:
  20 feature names and 36 command names, rather than the original estimate of
  about 38. Network round-trip latency can add to connection setup. The user
  declined optimizing this startup cost for the intended debugging workflow.
  Discovery remains sequential; concurrent queries or lazy capability loading
  have not been implemented or verified against supported engines.
- [-] **PB10 — Declined: remove duplicate record decoding/path mapping.**
  Breakpoint/spawnpoint response handlers decode records, map paths, and update
  inventories; public getters/listing methods then decode/map the reply again.
  The XML document itself is parsed once, so the original claim of two XML
  parses was inaccurate. No correctness failure was demonstrated; this is
  efficiency/maintenance cleanup that the user chose to leave unchanged.
  Returning the mutable inventory directly is not an established safe fix:
  later replies or notifications can update it before a waiting method resumes.
  Any future refactor must preserve the result belonging to the specific reply.
- [x] **PB11 — Cleanup: validate stdin acknowledgements once.**
  Removed the redundant success-flag check from `Session.stdin`; the response
  handler still validates every stdin acknowledgement before the method returns.
  No correctness defect was established in the duplicate check. Existing
  [stdin/interaction tests](tests/test_extensions.py) verify valid/failed
  acknowledgements, malformed replies, binary input, and cancellation/late
  replies. The full suite passed after removal, without changing the tests.
- [x] **PB12 — Defect: use failure HTTP statuses for failed health checks.**
  `GET /health` previously returned HTTP 200 even when the internal RPC
  dispatcher returned a structured error. `_Handler._dispatch` now sends 500
  for health-operation errors or 503 for `ConnectionClosed`, preserving error
  details. Successful health checks still return plain data with HTTP 200;
  ordinary POST RPC errors retain HTTP 200 and their structured error envelopes.
  Health reports DBGpilot's API state and does not probe PHP or the application
  under test. [Health regressions](tests/test_health.py): three failure cases
  failed before the fix and passed unchanged afterward; ten cases also verify
  success, authentication, error details, and ordinary RPC behaviour. The
  [server guide](docs/server.md) documents the status contract.

Validation (2026-10-30): **`./scripts/check.sh` passed all 628 tests with no
failures, errors, or skips**, including required Drupal, the six PHP/Xdebug
runtime combinations, real Chromium, proxy integration, and stress/restart
checks. Pytest completed in 234.66 seconds. All distribution checks also passed:
metadata/lock, archive contents, byte-reproducible builds, fresh wheel/source
installs and HTTP/TCP probes, live PHP onboarding from both formats, and
installed browser examples. Logs, JUnit, validation details, and the summary
are retained in `test-results/full-check-20261030-health/`; the validated,
unpublished candidate is
`dist/release-candidate/20261030T033048658775Z-a17e0c52/`.
The previously observed Drupal navigation and CLI subprocess timeouts did not
recur in that run; their root causes have not been established. Historical test
counts elsewhere in this file describe their dated milestones.

### 1. Polish the Python Playwright integration

Goal: let an application use DBGpilot from ordinary async Python Playwright
scripts with minimal setup, while retaining explicit control of debugger and
browser lifetimes. Build on `Client`, `PlaywrightDebugger`, and `PausedBrowser`.

- [x] **Define the public setup API and ownership rules.** Design a reusable
  async helper/context manager that can connect to an existing server or launch
  a local server when explicitly configured to do so. Specify what it owns,
  what survives its exit, and how callers deliberately shut down an owned
  process. Reusing a server must not confer ownership of that server or its
  other sessions. Closing a client must continue to leave PHP paused. Keep
  direct `Client` usage available for callers managing their own infrastructure.
- [x] **Implement server startup, readiness, and connection handling.** Use the
  current CLI/server rather than a second daemon implementation. Validate
  readiness and API compatibility within a bounded startup deadline; report
  launch failures, unavailable endpoints, authentication failures, occupied
  ports, and unexpected process exits clearly. Clean up failed launches and
  define concurrent-start behaviour so competing callers cannot silently attach
  to or terminate the wrong process. Make paused-session consequences explicit
  when a caller requests shutdown. Automatic startup must not require DDEV;
  document how a container-hosted server is reached or started separately.
- [x] **Unify project configuration.** Extend the existing `dbgpilot.toml`
  configuration with the connection, startup, timeout, and listener settings
  needed by the setup helper. Document precedence between explicit API arguments,
  CLI options, configuration, and defaults, including relative-path resolution
  across host/container boundaries. Preserve existing path-mapping behaviour
  and explicit opt-out/discovery controls. Keep configuration loading deliberate
  in library APIs and keep authentication values out of routine diagnostics.
- [x] **Provide optional pytest fixtures.** Add an opt-in integration for an
  existing async Playwright page and DBGpilot setup, with documented fixture
  scopes, overrides, and teardown ownership. Reuse the normal Python helper so
  pytest is not required by standalone scripts. Account for event-loop scope
  and parallel test workers: isolate capture correlation and avoid port/session
  collisions or shutdown of a server another worker still uses. Keep pytest
  and Playwright requirements optional for installed library consumers.
- [x] **Improve examples and failure diagnostics.** Show a standalone script
  and a pytest example that capture a breakpoint, assert snapshot values, close
  the first client, reconnect, inspect or mutate PHP, resume, and assert the DOM.
  Explain capture deadlines versus browser-action deadlines and the browser/
  event-loop lifetime needed during a pause. Include a Drupal/DDEV example and
  actionable setup errors for routing, triggers, and source-path mappings.
- [x] **Verify the integrated setup.** Cover reused versus owned servers,
  readiness failures, cancellation during startup, configuration precedence,
  teardown, and concurrent callers/workers. Run real browser/PHP acceptance
  checks through the new entry point and demonstrate that reconnecting still
  works after the original client closes. Update the public API and Playwright
  guides when the interface is settled.

Completion criteria: the documented standalone and pytest examples run from an
installed package; callers can either reuse a server or deliberately launch one;
ownership and shutdown are predictable; existing break-and-return and reconnect
behaviour remains covered by passing tests.

Implementation record (2026-10-27): `DebuggerSetup` and `SetupConfig` now provide
explicit reuse/owned CLI startup, readiness and process identity checks,
authenticated compatibility validation, cancellation cleanup, and deliberate
owned shutdown. Setup/client closure preserves the server and paused sessions;
helper closure releases its captures. The opt-in `dbgpilot.pytest_plugin` uses
function-scoped async fixtures and supports existing async pages. Shared TOML
connection/startup/listener settings retain the path-mapping configuration and
CLI overrides. See [Python setup](docs/python-setup.md),
[standalone example](examples/checkout_debug.py), and [pytest example](examples/pytest/).

Validation (2026-10-27): **`./scripts/check.sh` passed: 447 tests, no failures,
errors, or skips**, including all four required Drupal scenarios, real
HTTP/TCP setup/reuse, owned CLI processes, concurrent callers, actual Chromium,
the six-runtime PHP/Xdebug matrix, proxy integration, and existing stress tests.
The focused setup/network/pytest/browser run also passed all 38 tests. Readiness
and identity failures, authentication, startup/shutdown cancellation, child
cleanup, configuration precedence, and fixture teardown are covered separately
from live PHP acceptance.

The full check built both distributions and ran
`scripts/check_setup_examples.py --live`: a fresh environment installed the wheel
without dependencies and imported the core without pytest or Playwright. With
optional development dependencies exposed, both copied standalone and pytest
examples ran outside the source tree against actual PHP/Chromium, captured the
breakpoint, closed the original client, reconnected, mutated/stepped/detached,
and verified the DOM total of £85. Poetry metadata/lock validation also passed.
The core remains stdlib-only. The section 1 milestone recorded 447 tests,
78.525 seconds, timestamp `2026-10-27T11:53:23.566882+00:00`. Later full-suite
evidence is recorded in the dated review notes above; runtime and Drupal
evidence remain in `test-results/`. All section 1 criteria are verified.

### 2. Review protocol correctness and long-running process behaviour

Goal: assess the implementation independently of the assumptions in the current
tests, fix confirmed gaps, and describe remaining engine limitations accurately.
Review the implementation against the DBGp specification and documented public
contracts; do not treat the checked historical audit as proof of conformance.

- [x] **Perform a fresh protocol and state review.** Trace initialization,
  feature negotiation, command/transaction correlation, execution states,
  optional-command gating, property decoding, and termination through the
  controller, server, and client. Check malformed and vendor-specific responses,
  encoding boundaries, binary values, and proxy-specific EOF handling. Record
  findings with affected code, evidence, severity, and proposed resolution.
- [x] **Review concurrency and cancellation across all layers.** Follow a call
  from Playwright through HTTP to DBGp and back. Check simultaneous clients,
  per-session command ownership, cancelled or lost HTTP requests, late engine
  replies, delayed submissions, event replay, and reconnects. Verify that a
  timeout or client disconnect cannot make an executing engine appear idle,
  assign a session to a cancelled waiter, or deliver another caller's result.
- [x] **Review resource limits and lifecycle cleanup.** Inspect connection and
  task ownership, queues/history retention, closed-session eviction, packet and
  HTTP limits, startup failures, partial reads, and shutdown/restart paths.
  Verify bounded failure handling without automatically resuming idle live
  sessions. Include browser-route/action cleanup and diagnostic behaviour when
  the server is unavailable during cleanup.
- [x] **Resolve findings with focused regression coverage.** Fix confirmed
  implementation defects and add tests that reproduce their observable failure.
  Extend generated/scripted-peer cases where they expose missing invariants;
  use live PHP/browser tests where engine or application behaviour matters.
  Keep a review record linking findings to fixes or explicitly documented
  limitations, and rerun the affected checks plus the required full suite.
- [x] **Investigate live engines for optional extensions.** Identify a
  maintainable, legally usable engine that actually implements some of `stdin`,
  `interact`, `expr`, `exec`, or spawnpoints. If practical, add reproducible,
  version-recorded positive integration coverage for the commands it supports.
  If none is suitable, record the investigation and leave those commands
  explicitly labelled as scripted-peer coverage; do not claim live support or
  block the review indefinitely on an unavailable engine. Xdebug rejection
  tests remain useful evidence of capability handling.
- [x] **Publish the review outcome and support boundaries.** Update API,
  compatibility, and development documentation with findings, verification
  commands, tested versions, and any outstanding limitations. Distinguish
  parser tests, scripted engines, real Xdebug, and any additional live engine.
  State the scope reviewed rather than claiming complete DBGp certification.

Completion criteria: review findings are recorded and resolved or explicitly
dispositioned; regression checks and the required full suite pass; documentation
accurately separates controller capabilities from verified engine support.

Completion record (2026-10-27): the [review report](docs/protocol-review.md)
records the implementation trace, 14 findings with severity/evidence/resolution,
linked regressions, resource policy, engine investigation, and explicit support
boundaries. Fixes cover XML declaration-policy bypass, malformed metadata and
continuation replies, cancelled queue waits, late breakpoint/capability updates,
lost HTTP waiters, closed-session retention, command/connection limits,
concurrent listener starts and startup failures, postmortem gates, and active
browser capture/route/action cleanup. Xdebug's vendor `temporary` breakpoint
notification state is preserved. API, server, Playwright, compatibility and
development guides describe the resulting behavior.

Validation: **`./scripts/check.sh` passed all 491 tests with no failures, errors,
or skips**, including the required four Drupal scenarios, six PHP/Xdebug runtime
combinations, official dbgpProxy 0.6.2, real Chromium and existing stress/restart
checks. The 44 new regressions plus the existing live temporary-breakpoint case
passed together as a 45-case focused run. Both distributions built; both copied
standalone and pytest examples passed from the installed wheel against real
PHP/Chromium, including original-client closure and later inspection/mutation.
Fresh core imports still require neither pytest nor Playwright, and Poetry
metadata/lock validation passed. Runtime dependencies remain empty.

At that milestone, `test-results/junit.xml` recorded 491 tests in 80.164 seconds,
timestamp
`2026-10-27T14:03:20.445051+00:00`; `test-results/review-junit.xml` records 45
focused cases. Version evidence remains in `test-results/compatibility.json`
and `test-results/drupal11.json`.

The optional-engine investigation is reproducible with
`scripts/investigate_optional_engines.py`, using a checksum-pinned source archive
outside the package. `test-results/optional-engines.json` records the MIT-declared
Python candidate's version/commit, stdin/interact source handlers, and actual
Python 3.13.5 launcher failure on removed `imp`. Tcl redistribution suitability
was not established; ruby-debug-ide uses a different protocol. No suitable
additional live fixture was adopted. Optional-extension success remains
explicitly scripted-peer coverage; live Xdebug rejection is still verified.
The review's documented scope and limitations are not full DBGp certification.

### 3. Prepare a reproducible first release

Goal: make the package straightforward to install, verify, and release outside
the development checkout without shipping the PHP/Drupal development fixtures.

- [ ] **Add continuous integration.** Establish fast protocol/unit checks on
  supported Python versions and integration jobs for real TCP/HTTP, Xdebug,
  Chromium, the runtime matrix, and the required Drupal scenarios. Choose a
  practical split between per-change checks and heavier scheduled/release jobs.
  Reuse the existing setup/check scripts, cache pinned downloads appropriately,
  preserve JUnit/runtime evidence on failure, and make required-fixture jobs
  fail clearly rather than silently skip. Document supported runner assumptions.
- [x] **Automate distribution validation.** Check Poetry metadata/lock
  consistency, build both wheel and source distribution, inspect their contents,
  and install each into fresh environments. Verify public imports, the CLI,
  typing-marker inclusion, packaged licensing, and a small real client/server
  round trip. Confirm that generated Drupal/vendor code and reference projects
  are excluded. Preserve the stdlib-only core and test any optional integration
  extras independently, including an environment without Playwright or pytest.
- [x] **Finish installation and onboarding documentation.** Document supported
  Python versions, installation options, browser dependencies for examples,
  server startup and configuration, PHP/Xdebug connection direction, path
  mappings, and host/container networking. Provide a short successful first
  breakpoint walkthrough, troubleshooting for common setup failures, and links
  to the richer Drupal and Playwright examples. Verify the instructions using
  the built package rather than relying on imports from the source checkout.
- [x] **Define release metadata and compatibility policy.** Add a changelog
  describing the initial public API and known limitations; align package version,
  metadata, documentation, and CLI output. Describe API compatibility expectations,
  HTTP contract/version detection, and upgrade/restart effects on in-memory
  sessions. Keep MIT licensing and source/provenance information clear.
- [x] **Create and rehearse the release process.** Document reproducible build,
  validation, artifact inspection, and publication steps, including the chosen
  distribution destination and credentials supplied by the release operator.
  Produce reviewable artifacts and a release checklist from a clean environment.
  Publish the first release only when its destination and release authorization
  are established; distinguish a verified release candidate from a published
  release in the completion record.

Completion criteria: CI exercises the documented support scope, fresh installs
of both distributions work, onboarding instructions have been followed
successfully, and release artifacts/process are ready. Record actual publication
separately when it occurs.

Implementation and rehearsal record (2026-10-27): completed the work that does
not depend on CI/publishing decisions. `scripts/check_fast.sh` provides a
provider-independent fast entry point; `scripts/check.sh` retains required Drupal
and full live acceptance and now invokes the distribution validator afterward.
No CI provider, runner/trigger policy, package destination or credential has
been chosen, and nothing has been published.

`scripts/check_distribution.py` checks metadata/lock consistency, pins and
hash-verifies the existing Poetry 2.1.1 backend, makes two clean source exports,
normalizes build metadata, and requires byte-identical wheel/source builds.
Archive inventories/hashes verify the exact maintained payload, typing marker,
MIT license, NOTICE and zero runtime dependencies, excluding generated fixtures,
vendor/reference projects and local outputs. Both formats install independently
into fresh environments; the source uses isolated pip building from the verified
local backend wheel. `scripts/probe_install.py` verifies public exports,
console/module version output, health, and real HTTP/TCP snapshot/reconnection
without pytest or Playwright installed. Optional browser validation is explicit
and its development-tool versions are recorded separately; no extras are declared.

The new [installation guide](docs/installation.md) includes a local PHP CLI
walkthrough from installed artifacts using `examples/first_breakpoint.py`.
It generates temporary PHP, returns a snapshot, closes the first client,
reconnects/inspects/mutates/steps/detaches, and asserts real output 85. The full
rehearsal passed that walkthrough from both wheel and source installs, then the
standalone and pytest Chromium examples from the installed wheel. Shared routing,
mapping, browser dependencies and troubleshooting link to the existing guides.
`CHANGELOG.md`, `NOTICE.md`, public `__version__`, CLI `--version`, health package
version, and [compatibility policy](docs/release-policy.md) align on unpublished
0.1.0 and distinguish package version from HTTP protocol `dbgpilot/1`.

Validation: **500 full-suite tests passed, no failures/errors/skips**, including
required Drupal, runtime matrix, proxy, browser and stress coverage. The fast
suite passed **464 tests on each of Python 3.12.9/macOS and Python 3.13.5/Linux**
(36 integration cases deliberately deselected). Nine release regressions cover
version consistency and rejection of runtime dependencies, fixture payloads,
missing typing markers, traversal/symlinks and incomplete/failed JUnit evidence.
Poetry strict metadata/lock checks passed. The wheel and source were separately
reproducible within each rehearsal and also matched across the two tested
platform/interpreter combinations; this is observed evidence, not an unlimited
cross-platform reproducibility claim.

Reviewable full candidate:
`dist/release-candidate/20261027T162534350311Z-2e27a728/`.
It contains both artifacts, SHA256SUMS, exact source/archive inventories,
validation JSON, logs, copied full/fast/runtime evidence and CHECKLIST.md.
The Python 3.12 rehearsal is in
`dist/release-candidate-py312/20261027T162304864691Z-57ad3363/`.
Both report `validated-unpublished-candidate`, with publication false and
destination/authorization unset. Artifact SHA-256 values:

- Wheel: `d4408b982c130152c122d112fd172137f78b376f040eb0cf575c19669a9718cf`
- Source: `4041e7df330c3b553be075f05e1f4b7c16b737d505b98e1c1a52bbdbe07a6828`

`test-results/junit.xml` records 500 tests in 80.704 seconds, timestamp
`2026-10-27T16:24:12.482923+00:00`. `fast-py312.xml` and `fast-py313.xml` record
the supported-Python fast runs. The candidate preserves copies of that evidence.

Local artifact handoff follow-up (2026-10-27): the user permits manual testing
and does not require a passing full suite or CI before sharing a candidate.
`./scripts/release.sh` wraps the existing distribution validator without
requiring JUnit evidence or uploading files. The source archive now includes
`docs/consumer-quickstart.md` and a minimal `examples/consumer/` pytest starter
for an existing application and separately owned daemon. The release guide
documents manual file sharing and optional GitHub draft-prerelease uploads.
PyPI publishing remains deferred. These additions do not choose a host or
complete the CI/publication checkboxes below.

Verification: `./scripts/release.sh` produced the unpublished candidate
`dist/release-candidate/20261027T235458478745Z-e0868c44/` with reproducible
wheel/source builds, checked contents, fresh installs and both HTTP/TCP probes.
No full-suite evidence was supplied or required. All nine `tests/test_release.py`
checks passed. The installed-example checker collected both pytest examples
outside the checkout. The consumer starter extracted from this source archive
then passed against the installed wheel and actual PHP/Xdebug/Chromium in DDEV
(one test, 18.67 seconds). Artifact checksums and the current source manifest
were checked. No files were uploaded and no new full-suite pass is claimed.

GitHub release follow-up (2026-10-28): the user requested a way to share the
wheel through GitHub Releases. `scripts/github_release.py` validates a candidate
and its hashes, previews release notes with `--dry-run`, and uploads the three
artifact files to a draft prerelease by default (`--publish` makes it public
immediately). The repository defaults to GitHub `origin`, currently the public
`djotto/DBGpilot`; GitHub CLI authentication was verified. It requires an
existing pushed tag and does not commit/push source or tags. Sixteen focused
release/uploader tests passed, including refusal of changed files and a
read-only preview. A fresh `./scripts/release.sh` run passed packaging/install
validation without full-suite evidence and produced
`dist/release-candidate/20261028T002331074733Z-fe0aa851/`, including the uploader
and updated consumer/release docs. Artifact hashes/current source match; its
GitHub dry run passed.

Publication (2026-10-28): after explicit user authorization, committed and pushed
the release tooling/docs as `7130cac8405e7117c2d1b4768474f2032fb684d0`, verified
that commit's complete packaged-source inventory against the candidate manifest,
and pushed annotated tag `v0.1.0-testing.1`. Published
[the GitHub testing prerelease](https://github.com/djotto/DBGpilot/releases/tag/v0.1.0-testing.1)
at `2026-10-28T01:07:51Z`. Its wheel, source archive and `SHA256SUMS` were each
downloaded through their public URLs and matched byte-for-byte. The candidate's
`publication.json` records destination, authorization, commit/tag, release ID,
URLs, timestamps and hashes separately from the unchanged build validation.
Post-publication status edits on main do not change the tagged source or assets.

**Still pending:** CI wiring and its operational choices; section 4's standalone
skill. PyPI remains deferred. The [release guide](docs/releasing.md) documents
the manual workflow, and full-suite tests/CI are optional for that workflow.
Later package/source changes need a fresh candidate before the next publication.
The overall section 3 criteria are not all checked off because CI is unfinished.

### 4. Create a standalone DBGpilot skill

Goal: teach an LLM to investigate PHP requests interactively with DBGpilot,
including Python Playwright actions, without importing the existing UCAS
JavaScript test workflow into every investigation. Maintain the skill in the
sibling skills repository, following its repository guidance.

- [ ] **Create `../skills/dbgpilot/SKILL.md` with precise discovery scope.** Name
  the skill `dbgpilot`; describe interactive PHP/Xdebug debugging, breakpoint
  snapshots, inspection, mutation, stepping, and Python Playwright coordination.
  Support debugging without a browser too. Keep it self-contained and usable
  outside UCAS; do not require the existing Playwright skill or its JavaScript
  `@playwright/test` runner, `.tickets/` layout, fixed URL, or WSL/Apache setup.
- [ ] **Document setup discovery and the investigation loop.** Identify the
  actual PHP runtime, daemon endpoint, Xdebug connection direction, trigger
  configuration, and source mappings before capturing a request. Explain how
  to capture, inspect, form a hypothesis, step or deliberately mutate, resume,
  and verify application behaviour. Reuse DBGpilot's public APIs and maintained
  documentation rather than embedding a second controller or protocol manual.
- [ ] **Preserve pause ownership and browser concurrency.** Explain that a
  snapshot or closed client leaves PHP paused, while closing the helper releases
  its captures. Coordinate browser actions and debugger waits concurrently;
  distinguish action completion from PHP request completion and capture deadlines
  from browser deadlines. Keep the browser/event loop alive during a pause.
  Cover reconnection by session ID, daemon restart limitations, failure recovery,
  and explicit session release when an investigation finishes.
- [ ] **Add focused supporting references and runnable examples.** Put substantial
  Python Playwright examples in a linked reference, including navigation, form
  or AJAX capture, snapshot assertions, first-client closure, reconnection,
  inspection/mutation, resume, and final DOM verification. Keep DDEV and Drupal
  setup in separate references loaded only when relevant. Validate examples
  against the current installed package and real PHP/browser harness; avoid
  presenting fixture-specific assumptions as universal requirements.
- [ ] **Clarify authorization and connect the existing skill.** State how an
  explicit debugging request relates to creating/running temporary Python
  investigation scripts, honoring the user's existing authorization and the
  consuming project's rules without introducing repeated approval prompts.
  Add a short routing cross-reference in `../skills/playwright/SKILL.md` for
  DBGpilot investigations, preserving that skill's UCAS JavaScript test scope
  and explicit-request policy. Keep private-artifact conventions appropriate to
  the consuming project instead of silently imposing one shared layout.
- [ ] **Validate skill routing and operational guidance.** Check frontmatter,
  links, example commands, and skill-repository conventions. Evaluate ordinary
  browser testing, browser-driven PHP debugging, PHP debugging without a browser,
  and Drupal/DDEV debugging for correct routing and dependency assumptions.
  Verify that following the guidance preserves a paused session after client
  closure and allows later inspection/resume, without loading unrelated setup
  references or rewriting existing JavaScript tests into Python.

Completion criteria: the standalone skill supports the documented debugging
workflows with verified examples; the existing Playwright skill points to it
when appropriate; discovery, authorization, ownership, and cleanup instructions
are consistent with the actual APIs and consuming-project rules.
