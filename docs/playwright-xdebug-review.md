# Review of the Playwright migration

Historical review of the initial supplied port. Subsequent scope excludes
cross-script debugging and selects a JavaScript replacement backend. Fixes and
verification are tracked in [MIGRATION.md](../MIGRATION.md); the findings below
describe the pre-migration code, not its current status.

Reviewed 2026-10-30 against the `playwright-xdebug/` directory supplied in this
checkout and the current Python sources. This is a review, not an implementation
change. The older instructions in `HANDOFF.md` to retain Python describe an
earlier understanding of the consuming environment; this review follows the
current requirement for JavaScript Playwright scripts and tests.

The migration is a working, deliberately reduced debugger for investigations
contained in one Playwright Test. It is not yet a replacement for DBGpilot's
original interactive workflow. A fixture is an appropriate integration point,
but this implementation also replaces the debugger backend and changes its
lifetime, correlation, data representation, and recovery semantics.

The distinction between the Playwright library and the Playwright Test runner
matters here. A temporary `*.spec.js` investigation can use this fixture. An
ordinary `node investigate.js` script using `chromium.launch()` cannot use its
public debugging methods as supplied. Neither choice requires pytest.

| Capability | Original DBGpilot | Migration |
| --- | --- | --- |
| PHP pause within one browser investigation | Supported | Supported; verified live |
| Line, conditional, temporary and exception breakpoints | Supported | Dedicated wrappers present |
| Run, step into/over/out, detach, stop | Supported, with execution ownership | Wrappers present; recovery defects below |
| Stack and frame-specific reads/writes | Structured frames/properties; context selection | Stack, local context, `getVariable`/`setVariable` with `frame` |
| Evaluate PHP in the current frame | Supported | Supported; verified live |
| Convenient JS values | Original Python methods return structured properties | Plain scalars/arrays/objects; convenient but lossy |
| Assign arrays/objects conveniently | `set_value` accepts scalars; native expressions can assign containers | `setVariable` also converts JS arrays/objects through PHP `json_decode`; verified live |
| Read all direct array children | Paged reads with validation and a page bound | Paged reads work normally; missing validation/bound |
| Return while PHP remains paused | Snapshot and session handle | `runUntilBreak` returns a location; later inspection stays paused |
| Aggregate copied snapshot | Execution, stack, requested variables and expressions | No snapshot helper; values can be assembled manually |
| Reconnect from another script/client | Daemon-owned sockets, session IDs, HTTP API and CLI | Absent; numeric IDs are labels with no reconnect API |
| Ordinary standalone Playwright scripts | Supported independently of pytest | Public operations require the Playwright Test runner |
| Select one browser request | Unique IDE key per capture; route first matching request | Cookie enables matching PHP requests across the test context; wait by path/RegExp |
| Concurrent PHP sessions | Supported | Separate connections and transaction tables; basic support retained |
| Concurrent test workers/clients sharing one listener | Daemon can serve independent clients | Listener per worker; fixed port requires serial debug workers or separately configured PHP routing |
| Local/remote path mappings | Configurable roots, including different OS path namespaces | Absent; caller supplies server paths |
| Complete value fidelity | Raw bytes, property metadata, explicit truncation, extended properties | UTF-8 strings and JS numbers; partial containers become placeholder strings |
| Breakpoint get/list/update, hit conditions, other breakpoint options | Dedicated APIs and inventory | Raw command access only for unwrapped commands |
| Context discovery, globals, status, stack depth, source, features/type maps | Dedicated APIs | Raw command access only for unwrapped commands |
| Streams, notifications, stop events and replay | Structured events and daemon history | Incoming stream/notification packets discarded; no event history |
| Setup/configuration and failure diagnostics | Config files, server setup, health, handshake error queue | Listener options, cookies and site-specific README; preparation errors hidden |
| Proxy and optional DBGp extensions | APIs present; live engine support explicitly limited | No dedicated proxy workflow or optional-command wrappers |
| Playwright reporting | Python helper/optional pytest integration | Debugger calls appear as `test.step`; useful improvement for JS specs |

“Raw command access” means a caller can send a command and decode its parsed
response manually. It does not supply the missing structured API, inventory,
events, or execution-state handling. Raw continuation commands also bypass the
migration's state updates.

The original optional stdin, shell, `expr`/`exec` and spawnpoint success tests
use scripted engines. The tested Xdebug rejects those unsupported commands.
Their omission is a reasonable scope reduction for a PHP/Xdebug-only tool;
porting them would not add those facilities to Xdebug.

The following defects and limitations matter most.

1. **Continuation timeouts permanently lose the next stop.**
   [`dbgp.js`](../playwright-xdebug/lib/dbgp.js#L71) deletes a timed-out transaction
   and discards its eventual response. [`Session.#continue`](../playwright-xdebug/lib/session.js#L198)
   updates state only after a successful await. Reproduced: `run` times out,
   the peer subsequently returns `status="break"`, but `session.state` stays
   `running` and `stepOver()` rejects. An engine error response also leaves the
   state at `running`, even though execution was rejected. Closing the connection
   is effectively the remaining high-level recovery path.

   Original DBGpilot retains abandoned transaction ownership, processes late
   replies and restores the actual state. A fix needs response-driven state
   handling, including errors; setting the state to `break` on every timeout
   would falsely claim PHP has stopped.

2. **Inspection and evaluation lack execution guards.**
   [`Session.locals`, `getVariable`, `evaluate`, and `setVariable`](../playwright-xdebug/lib/session.js#L128)
   send commands without checking for a running/pending engine operation.
   Evaluation itself is not tracked as execution. Reproduced: calling `locals()`
   with `run()` pending sends `context_get` immediately. Xdebug does not generally
   process inspection commands while running; overlapping calls can time out or
   execute later against a different pause than the caller intended. Original
   DBGpilot explicitly guards these operations and owns evaluations until their
   real replies. Sequential happy-path examples avoid this defect.

3. **Value conversion silently changes application data.**
   [`values.js`](../playwright-xdebug/lib/values.js#L4) decodes every string as
   UTF-8 and every integer/float through `Number`. Confirmed with real PHP:
   bytes `ff 00 78` become the JS string `\uFFFD\u0000x`; PHP integer
   `9223372036854775807` becomes JS number `9223372036854776000`; PHP `INF`
   becomes JS `NaN`, which JSON serialization renders as `null`.
   `toPhp(Infinity)` also produces `Infinity`, an invalid PHP constant expression.

   Containers lose fullname, visibility, size, address/key, and truncation
   metadata. A partially returned container becomes a string such as
   `[array(250)]`, discarding even the fetched children and making it ambiguous
   with a real PHP string of that value. Binary-safe and large-integer-safe
   representations should be available, with a convenient plain-value view
   layered on top. Structured partial values should retain fetched children.

4. **Listener shutdown can wait indefinitely for an uninitialized socket.**
   [`Listener.#accept`](../playwright-xdebug/lib/listener.js#L30) starts tracking
   a session only after `init` and owner lookup. There is no initialization
   deadline or inventory of all accepted sockets.
   [`close()`](../playwright-xdebug/lib/listener.js#L25) waits for Node's server
   close callback, which needs those sockets to close. Reproduced with an open
   TCP connection that sends no initialization packet: shutdown remained pending
   until the probe explicitly destroyed the peer. Track all sockets from accept,
   bound initialization, and close accepted/preparing connections during shutdown.

5. **Test disposal races with asynchronous session preparation.**
   [`Listener`](../playwright-xdebug/lib/listener.js#L34) captures the owner,
   awaits preparation, then offers the session without checking ownership again.
   [`Xdebug.dispose`](../playwright-xdebug/lib/listener.js#L124) neither marks
   the owner disposed nor waits for preparation. Reproduced: disposal returns
   while the initial evaluation is pending; its subsequent reply delivers an
   open paused session to the already disposed owner. The unclaimed timer can
   eventually release it, but immediate test cleanup has been missed. Queued
   sessions that close are also not removed: a waiter can claim a stopped session.

   Normal assertion-failure teardown does work; this finding concerns sessions
   arriving or preparing during teardown. A disposed flag, preparation ownership,
   queue pruning and cancellation-aware cleanup are needed.

6. **Wire validation and resource bounds have been substantially removed.**
   [`Connection.#receive`](../playwright-xdebug/lib/dbgp.js#L85) does not validate
   the length header, trailing NUL, namespaces or initialization metadata, impose
   a packet limit, or contain parser failures. Response matching uses only the
   transaction number, not the expected command. Reproduced: a pending `status`
   accepted an `eval` response and a packet ending in `X` instead of NUL.
   This is a reliability regression even in a local development tool.

   There are no session or pending-command admission limits. `max_data=0` asks
   for unlimited string data globally, and nested reads fan out with unbounded
   `Promise.all`. Explicit limits are useful when inspecting large Drupal graphs.

7. **Pagination can make no progress indefinitely.**
   [`Session.#fetch`](../playwright-xdebug/lib/session.js#L178) concatenates
   pages until it reaches the advertised child count, with no overall page
   bound or validation of returned page numbers. Reproduced: a peer advertising
   two children but returning `property: []` on every page keeps receiving page
   requests; the probe interrupted it on the fifth call. Normal 250-element
   Xdebug pagination passed. Add no-progress/wrong-page checks and a total bound.

8. **The supplied onboarding and tests belong to a different checkout.**
   The [README](../playwright-xdebug/README.md#L35) assumes an existing
   `.tickets/package.json` workspace; this repository has none. The
   [spec](../playwright-xdebug/tests/fixture.spec.js#L8) resolves
   `../../../docroot` to `/Users/djotto/projects/docroot` here, whereas this
   project's Drupal fixture uses `fixtures/drupal11/web`. Its core line numbers
   and host PHP-FPM/systemd instructions are application-specific. There is no
   supplied Playwright config to define `baseURL` or a self-contained installation
   walkthrough. This does not disprove the original consuming-site proof, but
   prevents treating it as reproducible migration validation in this repository.

Several other workflow differences deserve an explicit decision.

- The generated trigger cookie is test-wide. AJAX, redirects and background PHP
  requests also connect and pause; unmatched requests wait two seconds by default.
  A path selector cannot distinguish GET from POST, different pages or different
  origins using the same URI. A RegExp can distinguish query strings, but the
  exposed request metadata has no host and the selector has no method predicate.
  Per-action correlation or an opt-in single-request capture helper would make
  investigations more predictable. Cookie triggering can still be useful when
  intentionally following an entire request chain.
- There is no configurable allowed IDE key for a site with restricted
  `xdebug.trigger_value`; generated random keys must be allowed by PHP configuration.
  Preparation failures are swallowed and turn into generic attachment timeouts.
- The caller owns every browser-action promise. There is no equivalent of
  `capture()` racing action failures against attachment and cleaning both up.
  A successful click can return before its AJAX request finishes; awaiting that
  click is not a request-completion guarantee. Failed navigation also needs a
  rejection handler while debugger waits are pending.
- Playwright Test's default overall deadline is 30 seconds, independently of the
  debugger wait and browser-action deadlines. The fixture does not extend it.
  Longer interactive pauses require deliberate runner and action configuration.
  See [Playwright's timeout documentation](https://playwright.dev/docs/test-timeouts).
- There are no TypeScript declarations or reusable package installation/release
  instructions. `private: true` is reasonable for a local workspace package,
  but the current folder is not a prepared independently distributed package.

I would use a JavaScript API with a thin Playwright fixture over the existing
DBGpilot HTTP daemon as the default next step. The existing
[server guide already includes a JavaScript `fetch` example](server.md#L362).
Browser scripts and tests would remain entirely JavaScript; Python would run
the debugger service, with no pytest requirement. This preserves the tested
protocol handling, path mappings, structured values and reconnectable sessions
without maintaining a second DBGp implementation. Browser/page lifetime still
needs to be maintained separately during a cross-script investigation.

The JavaScript client still needs a safe-integer policy: ordinary
`response.json()` also rounds large integers in the daemon's JSON number fields.
Use lossless JSON parsing or agree a safe representation at that boundary.
Reusing the backend does not by itself solve JavaScript's numeric limits.

If a self-contained Node debugger is a requirement, keeping this port is also
reasonable, but it needs the recovery, lifecycle and fidelity fixes above and
an API usable independently of `test.step`. Then decide explicitly whether
cross-script session retention is required. A fixture can manage cleanup for
tests, while an independent owner provides longer-lived investigations.
Full parity with every optional DBGp extension is not necessary for this goal.

Verification performed for this review:

- Installed `@playwright/test` 1.64.1 and `fast-xml-parser` 5.11.2 into a temporary
  directory. The latter satisfies the migration's declared `^5.2.0` range.
- Real PHP 8.4.22 / Xdebug 3.5.3 in the existing DDEV container: cookie/IDE-key
  correlation, URI selection, conditional/temporary breakpoint, stack, evaluation,
  nested reads, 250-child pagination, array/scalar mutation, stepping, detach,
  missed-breakpoint release and automatic unclaimed-request release passed.
  The HTTP response reflected a changed total of 85.
- Real Chromium through the unmodified Playwright fixture: browser pause,
  mutation, step, detach and final DOM passed. An intentional assertion failure
  while PHP was paused was expected by the runner; the following browser request
  completed. Runner result: three accepted outcomes in 3.5 seconds, including
  that expected failure.
- Scripted peers/fake sockets reproduced the state, concurrency, framing,
  pagination and lifecycle defects described above. Standalone use was tested
  against the real `test.step`, which rejected outside a test. Core probes then
  replaced step reporting only to isolate transport/session behavior.
- Temporary probe sources and a machine-readable record are retained under
  `test-results/playwright-xdebug-review/` (ignored by Git). Dependencies remain
  outside the project. PHP settings were passed only to temporary child servers;
  the project's PHP-FPM configuration was not changed.

The supplied Drupal specs, the original full Python suite, other engine versions,
and a JavaScript client over the existing daemon were not rerun in this review.
The root TODO records an earlier 628-test full Python validation; that is historical
evidence, not a fresh result or inherited coverage for this independent port.
