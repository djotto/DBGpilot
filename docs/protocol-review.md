# Protocol and process-lifecycle review

Review date: 2026-10-27. Package: DBGpilot 0.1.0. Starting baseline: 447 tests.
This review traced implementation and public contracts afresh; the checked
historical audit and existing tests were not treated as conformance proof.
This is a scoped implementation review, not DBGp certification or an independent
third-party security assessment.

The reference is [DBGp 1.0 draft 22](https://xdebug.org/docs/dbgp), particularly
initialization/proxy control (section 5), framing/correlation/encoding (6),
states/features/properties/continuations (7), and optional commands/events (8).
Regressions were derived from code paths and failure interleavings rather than
repeating existing expected results.

## Review trace

| Area | Code and evidence |
| --- | --- |
| Initialization | `Controller._accept` → `Session.connect` → feature discovery/settings. Namespace/version validation, recognition versus feature value, encoding negotiation, failed handshakes, and optional-command gating were traced. Scripted sessions and six live runtime combinations verify these paths. |
| Transport and values | `read_packet` → XML → `_dispatch_response` → models/JSON. Byte lengths, fragments, delimiters, unique transaction correlation, error/vendor XML, independent streams/notifications, binary/NUL values, extended properties, type maps, paging/truncation, locations and snapshot independence were checked. |
| Execution | `_execute` → `command` → response dispatch. Timeout/cancellation ownership, late success/errors, async status/break, stdin locking, interactive state, postmortem gates, stop EOF and restricted proxy detach EOF were traced. |
| Cross-client work | Playwright route/action → native HTTP client → RPC/per-session lock → engine. Explicit/lost-request cancellation, delayed submissions, claims, ambiguous IDs, replay cursors and reconnects were checked against their contracts. |
| Lifecycle | Listeners/tasks/transports, controller queues, pending transactions, server journals/retention, partial HTTP requests, startup failures and browser cleanup were inspected. Existing live sessions must not be evicted/resumed to satisfy limits. |
| Application behavior | Real checkout navigation/form/AJAX, official dbgpProxy 0.6.2, Chromium, the runtime matrix, stress checks and four required Drupal cases remain required. New browser regressions close the helper during attached setup and report cleanup failure after server loss. |

Executable findings are in [test_review.py](../tests/test_review.py) and
[test_review_browser.py](../tests/test_review_browser.py). The first 17-case
regression run had 16 failures and one existing rejection (UTF-32). Further
cases cover code-inspection findings, resource admission, capability transitions,
and cleanup. Severity below describes impact in a trusted debugging environment.

## Confirmed findings and fixes

All findings below are fixed, with focused regressions. Full validation results
and completion status are recorded in [TODO.md](../TODO.md).

| ID / severity | Affected code and failure evidence | Resolution / regression |
| --- | --- | --- |
| R01 — High | `protocol.parse_xml`: the byte filter missed UTF-16 DTDs; ElementTree expanded an internal entity despite the declared rejection policy. | Reject NUL-containing XML, incompatible with DBGp's byte framing. `test_non_ascii_xml_cannot_bypass_the_dtd_rejection` covers UTF-16/32; existing UTF-8/Xdebug profile coverage remains. |
| R02 — Medium | `models.parse_property` accepted negative sizes/counts/pages, yielding misleading paging/truncation results. | Validate nonnegative property metadata. `test_negative_property_metadata_is_rejected` covers all four fields without rejecting engine location sentinels. |
| R03 — Medium | `Session._finish_execution` accepted missing continuation status, returning an unknown result while leaving a running state without an outstanding continuation. | Validate completion states before committing replies. `test_continuation_reply_requires_a_valid_state` covers missing, invalid, starting and running states. Evaluation may omit status and restore its prior state; async break acknowledgements remain distinct from run completion. |
| R04 — High | `wait_queue` used a background `get()` that could consume an event/session just before caller cancellation. | Wait for availability only, then dequeue synchronously in the caller. `test_cancelled_event_wait_does_not_consume_an_arriving_event` reproduces the race. The same FIFO handles readiness, diagnostics and events. |
| R05 — Medium | Breakpoint wrappers lost inventory updates on cancelled acknowledgements; get accepted another ID and list accepted empty/duplicate IDs. | Apply validated acknowledgements in dispatch, including abandoned calls; validate lists before mutation. Late creation/update/removal, wrong-ID and atomic invalid-list tests cover these cases. Wrappers no longer overwrite a later notification on resumption. |
| R06 — High | `_Handler._dispatch` did not observe lost HTTP connections; an abandoned waiter could claim future PHP. | Cancel pending RPCs on observed socket EOF/reset. Lost-wait and lost-execution tests verify that future PHP remains claimable while an already executing engine stays running until its real late reply. |
| R07 — Medium | `Controller` retained closed sessions until inventory reads; unclaimed closed sessions/errors could accumulate and handshakes had no admission cap. | Release closed references automatically, bound diagnostic history, and cap live/initializing admissions. Closed-retention, ready-reference, error-history and connection-cap tests verify that existing sessions survive overload. |
| R08 — Medium | Concurrent controller starts created multiple listeners; server starts could conflict. A failed HTTP thread start could hang cleanup on an unstarted thread. | Serialize startup and close listeners created during shutdown; only shut down/join started HTTP threads. Concurrent controller/server and failed-thread-start regressions verify cleanup. |
| R09 — Medium | Unanswered, timed-out commands accumulated in abandoned-transaction tables indefinitely. | Bound pending plus abandoned commands; reject new commands before sending at capacity. Late replies free capacity without closing/resuming the session. `test_unanswered_transactions_are_bounded_and_late_replies_free_capacity` verifies recovery. |
| R10 — Medium | HTTP threads were unbounded and partial-request sockets were left to read timeouts during shutdown. | Limit admitted HTTP workers/connections and close accepted sockets during shutdown. `test_http_worker_cap_and_shutdown_release_partial_connections` verifies both behaviors. |
| R11 — High | Helper shutdown ignored active setup; route installation/removal could exceed deadlines, route errors masked action errors, and an action could deadlock by closing its own helper. | Own/cancel active capture tasks, preserve cleanup ownership, include route setup in deadlines, bound removal, preserve original errors with notes, and reject self-closing actions. Focused fake-page and two real PHP/browser tests verify cleanup and server-loss diagnostics. |
| R12 — Medium | Source/context-name/type-map queries bypassed the stopping-state postmortem gate used by stack/property/evaluation reads. | Apply that gate consistently while preserving startup queries. `test_postmortem_metadata_queries_respect_engine_support` verifies unsupported requests never reach the engine. |
| R13 — Low | Client writer cleanup could hang after its transport deadline had already fired. | Add a separate one-second cleanup bound. `test_client_timeout_also_bounds_writer_cleanup` uses an unresponsive writer. |
| R14 — Medium | Cancelled feature replies left the capability inventory and async-command gate stale. | Apply feature acknowledgements during dispatch and validate support/success flags. `test_late_capability_acknowledgement_updates_async_gating` covers get/set and both async transitions. |

## Resource policy

Breakpoint reply/notification states preserve nonempty engine/vendor strings,
including Xdebug 3.5.3's `temporary` state in resolution notifications. Only
creation/update request options are restricted to enabled/disabled; metadata
validation must not turn those vendor replies into connection failures.

| Resource | Default / configuration |
| --- | --- |
| Engine packet | 16 MiB, `Controller(max_packet_size=...)` |
| Pending plus abandoned commands per session | 1024, `Controller(max_pending_commands=...)` or direct `Session` |
| Live plus initializing engine connections | 256, `Controller(max_sessions=...)`; only new connections are rejected |
| Recent controller errors | 50, `Controller(error_queue_size=...)`; oldest diagnostics are dropped |
| Session event queue | 1024 entries, `Controller(event_queue_size=...)`; overflow explicitly closes that session |
| HTTP connections/workers | 128, `Server(max_http_connections=...)`; excess connections close before worker creation |
| HTTP request / client response | 1 MiB / 64 MiB |
| Journal / closed-session retention | 1024 events per session / 128 closed sessions |
| Delayed-submission cancellation history | 1024 IDs for `max_wait + 5` seconds |

Pass a configured controller to `Server(controller=...)` to change controller
limits. CLI startup uses defaults. Live idle sessions are never evicted to make
room. Counts and packet sizes are not aggregate heap-byte quotas; inventories
also scale with the breakpoints/spawnpoints callers request.

## Optional-engine investigation

The Python candidate was downloaded and actually launched. Reproduce with:

```sh
ddev poetry run python scripts/investigate_optional_engines.py
```

The script checks a pinned archive checksum, extracts outside the package,
records source version/handlers and attempts the unmodified launcher with a
ten-second deadline. Evidence is `test-results/optional-engines.json`.

| Candidate | Evidence and disposition |
| --- | --- |
| [komodo-python3-dbgp](https://github.com/agroszer/komodo-python3-dbgp), version 11.1.2.dev0, commit `aa277c0055dffb597777bba49d4eb65d30af02a0` | Its pinned license inventory declares the Python component MIT and `bin/pydbgp` has an MIT header. Source contains `do_stdin` and `do_interact`; no corresponding expr/exec/spawnpoint handlers were found. On Python 3.13.5 the actual launcher exits 1 with `ModuleNotFoundError: No module named 'imp'`. Python documents [imp's removal in 3.12](https://docs.python.org/3/library/imp.html), outside the candidate's compatible range and inside DBGpilot's supported 3.12/3.13 range. Source compilation or the obsolete `dbgpClient.py` stub's exit 0 is not a working debugger. A compatibility fork/legacy runtime was not adopted as a maintainable fixture. |
| Komodo Tcl debugger | The distribution's [license inventory](https://github.com/agroszer/komodo-python3-dbgp/blob/aa277c0055dffb597777bba49d4eb65d30af02a0/LICENSE.txt) assigns Tcl debugging to the Komodo IDE license. A clear, maintainable redistribution route for a runnable Tcl fixture was not established. No Tcl binary was added/executed and no live support is claimed. |
| [ruby-debug-ide](https://github.com/ruby-debug/ruby-debug-ide/blob/master/protocol-spec.md) | Its primary protocol document specifies its own commands/XML events, rather than DBGp framing/transactions. It is not a drop-in engine; writing an adapter would not validate these optional DBGp commands. |

Pinned archive SHA-256:
`be699d79e4e1a4885972b4628aa3a9db863d350ab385d3fca935f3e29dcd7a6e`.
These candidates yielded no practical additional live engine in this review;
this is not a claim that none exists. No third-party engine code or runtime
dependency was added to DBGpilot.

The repository's default branch was checked on the review date: its head was
the pinned commit above (commit date 2019-01-25). The launcher failure was not
inferred from an arbitrarily older revision while overlooking a newer head.

## Support boundaries and explicit dispositions

- Parser tests check decoding. Scripted peers check selected state/transport
  interleavings and optional commands. Neither establishes positive support in
  a real language engine. Live coverage remains PHP/Xdebug, the official proxy,
  Chromium and Drupal. `stdin`, `interact`, `expr`, `exec` and spawnpoint success
  remain **scripted-peer coverage only**; Xdebug rejection/usability is live.
- Pending HTTP work is cancelled when socket EOF/reset is observed. Keep the
  writing side open until the response: a TCP write half-close is abandonment.
  Detection/cancellation cannot undo a committed claim or command. Recover
  unknown delivery through `sessions()`/metadata, not automatic retries/resume.
- Unique request IDs and cancellation tombstones handle delayed submissions;
  ambiguous IDs are rejected. Journals preserve independent replay and explicit
  expired-cursor errors. There is no exactly-once execution/retry contract.
- Raw `Session.command()` is an escape hatch. Use typed continuation methods
  for managed execution and late-reply handling; unknown vendor execution
  semantics cannot be inferred. Direct users coordinate their own multi-command
  operations; the server guards compound snapshots/captures per session.
- Late replies update state and acknowledged inventories. Detailed errors from
  abandoned calls are not a separate durable audit stream. Inventories contain
  last-observed data, not proof of every external engine change.
- UTF-8 negotiation and the specific Xdebug Latin-1 byte-container profile are
  supported; arbitrary negotiated encodings are not. Vendor XML/attributes and
  engine locations are retained without inventing missing framework frames.
- Handshake packet reads and negotiation commands are bounded individually;
  `handshake_timeout` is not a single deadline for all feature discovery. HTTP
  reads use inactivity timeouts rather than an absolute slow-request lifetime;
  admission is bounded and shutdown closes accepted sockets.
- A server outage can prevent remote browser cleanup. The helper settles its
  local action and reports failure; recover by ID if the same server returns.
  Restart loses IDs. Close the helper from its owning task, outside the browser
  action passed to `capture()`.
- Direct controller/server shutdown must be awaited to completion. Code that
  can cancel those owner-cleanup tasks should shield them or terminate the
  owning process. Their direct methods do not promise restartable cleanup
  after an externally interrupted shutdown; setup/helper cleanup has its own
  explicit shielding policy.

## Verification

```sh
ddev poetry run pytest tests/test_review.py tests/test_review_browser.py \
  --junitxml=test-results/review-junit.xml
./scripts/check.sh
```

The full check requires Drupal, includes the runtime matrix/stress tests,
builds both distributions, and runs standalone/pytest examples against the
installed wheel and actual PHP/Chromium. See [compatibility](compatibility.md)
and [TODO](../TODO.md) for runtime versions, final results and evidence files.

Final validation on 2026-10-27: **491 passed, no failures/errors/skips** in the
required full check; **45 passed** in the focused run (44 new cases plus the
existing live temporary-breakpoint scenario). Wheel/source builds, installed
standalone and pytest PHP/Chromium examples, stdlib-only core imports, and Poetry
metadata/lock validation passed. JUnit evidence is `test-results/junit.xml`
(80.164 seconds, `2026-10-27T14:03:20.445051+00:00`) and
`test-results/review-junit.xml`. The actual browser/Drupal runtime was PHP 8.4.22 /
Xdebug 3.5.3 with Drupal 11.4.11 and MariaDB 11.8.8; Python was 3.13.5. The
six-combination matrix and its historical observations are documented separately
in the compatibility guide and JSON evidence.
