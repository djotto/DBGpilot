# Migration to JavaScript Playwright

Implementation: `main`, migrated through `migration/playwright`. Approved scope, 2026-10-30: replace the Python
DBGpilot implementation with the JavaScript Playwright fixture. The Python
implementation is preserved on [archive/python](https://github.com/djotto/DBGpilot/tree/archive/python)
as a behavioural reference. The active tree contains the JavaScript implementation.

Investigations run inside one Playwright test or one standalone Node script.
The owning test/script releases its PHP sessions on completion. Cross-script
debugging, the persistent HTTP daemon, its clients/CLI, and pytest integration
are outside the replacement's scope. A timeout does not pretend PHP stopped:
late replies must still restore the true state within the same investigation.

The fixture wraps a test-independent debugger core. Fast Node tests cover wire
handling and values, real TCP peers cover session ownership, and Playwright
tests cover PHP/Xdebug and browser behaviour. Protocol tests do not launch browsers.

## First milestone

- [x] Create the migration branch and a checked-in npm dependency lock.
- [x] Retain timed-out commands and process late execution/error replies.
- [x] Guard inspection, mutation and evaluation against overlapping operations.
- [x] Preserve binary strings, large integers, nonfinite floats and partial data.
- [x] Validate packet framing, XML, namespaces and response correlation; bound
  packets, pending transactions, incoming sessions, pagination and nesting.
- [x] Own initializing/preparing connections and clean up test-disposal races.
- [x] Expose same-process controls without a Playwright Test runtime dependency.
- [x] Add JSON-safe copied snapshots and cancellation of pending session waits.
- [x] Establish maintained Node protocol/value/session/listener regressions.
- [x] Add repository-owned PHP/Chromium tests for navigation, POST, AJAX,
  mutation, snapshots, late replies, exceptions and failure cleanup.
- [x] Adapt and verify the supplied Drupal proof specs against this repository's
  pinned fixture, without depending on the external `.tickets` workspace.

## Remaining migration

- [x] Finish relevant debugger API coverage: breakpoint inventories/options,
  features, contexts, source/value retrieval, termination semantics and metadata.
- [x] Port feature negotiation safeguards: encoding/base64 requirements,
  unavailable-command guards, optional feature rejection, cached capability
  helpers and late feature acknowledgement updates. See `features.test.js`.
- [x] Port the remaining selected real-Xdebug scenarios: stepping into/out of
  functions, exact hit counts and temporary breakpoints, stdout routing and
  recovery after an evaluation error, across all six runtime combinations.
- [x] Port the selected failure/cleanup regressions: stalled writes, setup and
  execution disconnects, late execution ownership, shared close after an abandoned
  wait, slow/late route installation and preservation of primary/cleanup errors.
- [x] Review the browser diagnostics helper and defer it by user decision;
  keep existing traces and add diagnostics to individual tests when needed.
- [x] Port local/remote source mappings and their cross-platform regression cases.
- [x] Add per-action capture coordination: precise request selection, action
  failure propagation, separate action/debugger deadlines, and bounded cleanup.
- [x] Port retained in-process events and AbortSignal cancellation, including
  late evaluation errors and prevention of duplicate stop events.
- [x] Verify independent concurrent PHP requests, releasing one while others
  remain paused, owner shutdown, and actual execution termination.
- [x] Verify browser concurrency and a 35-second pause beyond the capture deadline.
- [x] Audit all 309 named legacy test functions across 34 files and reconcile
  retained, adapted, retired and deferred scenarios in the [case ledger](docs/migration-audit.json).
- [ ] Validate GitHub-installed consumption in the actual target environment;
  the user confirmed that environment is unavailable on this machine.
- [ ] Publish the first JS release after target-environment acceptance. The
  validated local candidate remains unpublished.
- [x] Reproduce the PHP/Xdebug compatibility matrix using the JS implementation.
- [x] Port Drupal rendering, persisted form save and autocomplete/database
  scenarios from the Python acceptance suite; remove reconnect-only portions.
- [x] Complete standalone and fixture examples, TypeScript declarations, package
  validation, licensing payload, and installation/networking documentation.
- [x] Replace setup/check/candidate-release entry points with JS versions; remove
  the retired Python implementation, Poetry dependencies and pytest tooling.
- [x] Preserve the final Python main on `archive/python` and unpublish both
  Python GitHub releases as drafts, retaining their assets and historical tags.
- [x] Move the JS package to the repository root for direct GitHub installation.
- [x] Account for every old test file in the inventory with retained coverage,
  documented retirement/deferment reasons; the function-family audit is complete.
- [x] Validate the root-package cutover and merge the replacement into `main`.

No npm registry publication or CI provider is selected by this migration.
GitHub source installation is supported; the first JS release remains pending.
The Python release assets remain retained in unpublished drafts.
Track limitations, exclusions and deferred decisions in
[migration exceptions](docs/migration-exceptions.md); ordinary pending work
stays on the checklist above.

## Run the new checks

Node 20+:

```sh
npm ci
npm test
npm run test:types
```

`npm test` needs permission to bind loopback sockets, but no PHP, browser or
Python. For actual PHP/Xdebug/Chromium, use the existing DDEV environment:

```sh
ddev exec npm ci
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:browser
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:drupal
ddev exec npm run test:compatibility
ddev exec npm run test:integration
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:stress
ddev exec npm run check:package
```

The browser suite creates and stops its own PHP server on ports 19434/19433
by default (`PW_PHP_PORT`/`PW_XDEBUG_PORT` override them). The Drupal suite uses
the existing separate Drupal fixture and its configured connection to port 9003
in the parent DDEV container. Its listener binds `0.0.0.0` for that connection.
These checks do not modify PHP-FPM settings or start the Python daemon.
`ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run check:all`
runs the fast, type, browser, compatibility, live integration, Drupal, stress and package checks
in sequence. `ddev test-setup` now installs Node dependencies, Chromium and
pinned historical Xdebug modules using the JavaScript runtime builder.
Missing PHP/Xdebug, browser binaries or Drupal sources fail the relevant job;
they do not produce a silent success through skips.

The existing browser cache is reused. New environments can install matching
Chromium with `ddev exec npx playwright install --with-deps chromium`, setting
`PLAYWRIGHT_BROWSERS_PATH` to the cache above when using these commands.
Drupal fixture provisioning uses `ddev drupal-setup`; `ddev drupal-test` now
runs the JS acceptance suite. No active setup or check entry point uses Python.

## Evidence

Node checks: the initial 72 passed on macOS/Node 25.2.1; all 75 current
regressions passed on DDEV/Node 24.18.0. The Chromium/PHP suite
passed all eight accepted outcomes on DDEV Node 24.18.0 / Playwright 1.64.1 /
PHP 8.4.22 / Xdebug 3.5.3, including one intentionally expected assertion failure.
JUnit and traces are under `test-results/playwright-js*`.
The five supplied Drupal smoke scenarios also passed against the repository's
separate Drupal fixture (2.6 seconds); JUnit is `test-results/playwright-drupal-js.xml`.
These are initial replacement checks, not a claim that the historical Python
suite has been fully migrated or rerun.

Second milestone (2026-10-30): 139 Node regressions passed. A Linux PHP/Chromium
case verifies Windows local paths, mapped breakpoint inventories, source reads,
contexts, type maps and full binary/property-page retrieval. Six capture cases
passed for navigation, POST and AJAX, action/setup failures, deadlines, aborts
and teardown. The six original PHP/Xdebug combinations passed using the JS
core, with Unicode source paths, NUL/binary data, paging, mutation, stepping and
verified PHP output. Versions and results are in
`test-results/compatibility-js.json`. All eight Drupal checks passed, including
the three ported rendering, database persistence and autocomplete scenarios.
TOML/CLI discovery is replaced by explicit Playwright/core options, as recorded
in the exceptions list.

Additional conformance/stress coverage: cancellation retains engine ownership,
cancelled event waits preserve future events, bounded event queues retain terminal
errors, late breakpoint replies update inventories, mixed notification bodies
exclude child metadata, raw vendor XML/error fields are retained, and raw Xdebug
byte-container names are preserved. Four concurrent PHP processes, release of
multiple paused requests and explicit stop passed. Chromium also passed a
35-second pause and three independently paused page requests.

Final checks for this batch: `npm run check:all` passed in DDEV, with 166 Node
regressions, TypeScript consumers, 16 browser outcomes (one expected assertion
failure), all six PHP/Xdebug combinations, eight Drupal checks, three live PHP
stress cases and two browser stress cases. The standalone Node example ran
through real PHP/Chromium and verifies source-file preservation; its settings
use `DBGPILOT_SCRIPT_*` to avoid Playwright's reserved `DEBUG_FILE` log setting.
The package validator installed the actual 20-file tarball outside the checkout,
compared file bytes, and checked CommonJS/ESM exports plus installed TypeScript
consumers. Its unpublished candidate and hash are recorded in
`test-results/js-package-validation.json`; artifacts are under `dist/js-candidate/`.
Declaration checks also pass on the macOS host. They use the portable TypeScript
5.9.3 compiler; TypeScript 7's native platform package conflicted with sharing
`node_modules` between macOS and Linux/DDEV during validation.

JS-only cutover (2026-10-30): the 166 unit checks and declarations passed on
macOS and DDEV. All 16 browser outcomes, six runtime combinations, eight Drupal
checks and five stress checks passed from the root package. The initial package
check rejected leftover ignored Python bytecode under examples; the runtime
allowlist now names only JS modules and the standalone example, and the clean
20-file package check passes. The Node-only DDEV setup entry point also passed.
Scenario-level audit items above remain open; archiving Python does not claim
that every historical assertion has been reproduced.

Feature negotiation migration: startup now discovers command availability,
negotiates encoding before PHP evaluation, tolerates optional settings rejected
with success=0 or unsupported-command/argument errors, and enables supported
notification/breakpoint detail settings. Cached command/async helpers and
late capability acknowledgements remain accurate. Regression cases include
rejection without PHP state changes, required-encoding failure and listener
recovery, boolean wire values, and cleanup when detach is unavailable. Runtime
matrix assertions verify these helpers and encoding guards against real Xdebug.

Validation for the feature safeguards: 199 Node regressions (including 33
feature cases), source TypeScript declarations, all 16 browser outcomes, six
PHP/Xdebug combinations, eight Drupal checks and five stress checks pass.
The package check verifies the final 20-file tarball with fresh CJS/ESM and
installed TypeScript consumers, including the new capability helpers.

Live integration migration (2026-10-31): `tests/live/integration.test.js` ports
the archived Python stepping/hit-count, output-event and exception/evaluation
error scenarios. Six cases per runtime cover function entry/return and locals,
the exact third hit followed by a disabled one-shot breakpoint on the next
iteration, stdout off/copy/redirect with NUL/invalid UTF-8/Unicode bytes, and
evaluation failure followed by inspection, successful evaluation, mutation and
detach. Process stdout, stderr and exit status are verified independently of
debugger events. All 36 cases pass across the six PHP/Xdebug combinations;
Node also reports their six parent groups (42 passing test entries).
The matrix profiles are shared with the compatibility smoke suite. Run with
`ddev exec npm run test:integration`; `check:all` includes it. Versioned evidence
is recorded in ignored `test-results/integration-js.json`. No runtime API changes
were required. Remaining conformance, failure/cleanup and diagnostic audits are
still tracked separately.

Failure/cleanup migration (2026-10-31): socket-write backpressure deadlines,
late write errors, execution disconnects and stop-callback execution ownership
are retained in the JS regressions. Python write-lock/cancelled-task cases adapt
to pre-write abort checks and abandoned waits over shared JS cleanup promises.
New setup-disconnect cases prove the listener remains usable, including a failed
release during failed preparation. The original preparation/action error reaches
the caller, and secondary cleanup failures are reported separately.

The regressions exposed and fixed late-installed route leaks, loss of falsy
original rejections, child-disposal errors replacing action errors, and shutdown
returning before other captures finished. Expired routes are inert and removed
again after late installation; cleanup waits remain bounded. Multiple close
failures are collected, and listener shutdown closes sockets and frees its port
even when an owner fails. Three real browser/PHP cases verify setup disposal,
original-error preservation with retry, and DBGp socket loss during navigation.

The concurrent-browser stress check also exposed PHP CLI prefork scheduling:
one worker accepted two sockets, so pausing its first request prevented its
second request from reaching Xdebug. The harness now starts three independent
PHP servers on consecutive loopback HTTP ports, sharing one debugger listener.
The three-capture case passed three consecutive repetitions after this change.
Arbitrary action/routing promises still cannot be forcibly cancelled; their
handling and this limitation remain in the exceptions list.

Validation: 221 Node regressions (22 added for cleanup/setup), TypeScript, 19
browser outcomes (one expected assertion failure), six compatibility profiles,
36 live integration scenarios, eight Drupal checks and five stress checks pass.
The early full-check run exposed the CLI-worker scheduling issue above; the
stress job passed after that harness fix, and package validation then passed
for the final 20-file tarball and fresh CJS/ESM/TypeScript consumers.

Final coverage audit (2026-10-31): AST enumeration confirms 309 top-level
test functions in 34 archived files. A preliminary text count of 310 included
an embedded pytest example; that example is not a separate archived test.
The ledger classifies 87 covered, 89 adapted, 116 retired and 17 deferred
functions. Every function is accounted for once, and every referenced JS
evidence path exists. This is a function-family/scope reconciliation, not a
claim of identical parametrized cases, APIs or workload counts.

The audit adds 67 Node regressions: 63 protocol/value/conformance cases and
four listener admission/wait cases. Generated packet and byte-value samples
use fixed seeds for reproducibility. The only runtime fix rejects invalid
snapshot arrays, context and depth before any engine command is sent.

Validation: the full DDEV check command passed with 288 Node regressions,
source and installed TypeScript checks, 19 browser outcomes (one expected
assertion failure), six compatibility profiles, 36 live integration cases,
eight Drupal checks, five stress checks and clean 20-file package installation.
The unpublished 0.1.0 tarball and hash remain under dist/js-candidate and
test-results/js-package-validation.json. The actual target environment is
unavailable here, so its acceptance check and JS release publication remain
outstanding. Optional proxy/TOML/diagnostics work stays deferred.
