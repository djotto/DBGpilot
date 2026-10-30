# Migration to JavaScript Playwright

Branch: `migration/playwright`. Approved scope, 2026-10-30: replace the Python
DBGpilot implementation with the JavaScript Playwright fixture. The Python
implementation stays available during migration as a behavioural reference;
release tags and Git history will preserve it after cutover.

Investigations run inside one Playwright test or one standalone Node script.
The owning test/script releases its PHP sessions on completion. Cross-script
debugging, the persistent HTTP daemon, its clients/CLI, and pytest integration
are outside the replacement's scope. A timeout does not pretend PHP stopped:
late replies must still restore the true state within the same investigation.

The fixture wraps a test-independent debugger core. Fast Node tests cover wire
handling and values, real TCP peers cover session ownership, and Playwright
tests cover PHP/Xdebug and browser behaviour. Protocol tests do not launch browsers.

## First milestone

- [x] Create the branch and an npm workspace with a checked-in dependency lock.
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

- [ ] Finish relevant debugger API coverage: breakpoint inventories/options,
  features, contexts, source/value retrieval, termination semantics and metadata.
- [ ] Port local/remote source mappings and their cross-platform regression cases.
- [ ] Add per-action capture coordination: precise request selection, action
  failure propagation, separate action/debugger deadlines, and bounded cleanup.
- [ ] Port the remaining relevant conformance, stress and cancellation cases,
  including concurrent PHP requests and long pauses. Track scenario coverage,
  not a target test count. See [test inventory](docs/js-test-inventory.md).
- [ ] Reproduce the PHP/Xdebug compatibility matrix using the JS implementation.
- [ ] Port Drupal rendering, persisted form save and autocomplete/database
  scenarios from the Python acceptance suite; remove reconnect-only portions.
- [ ] Complete standalone and fixture examples, TypeScript declarations, package
  validation, licensing payload, and installation/networking documentation.
- [ ] Replace the default setup/check/release entry points with the verified JS
  versions, then remove the retired Python implementation and dependencies.
- [ ] Reconcile every old test file with retained coverage or a documented
  retirement reason, then merge the replacement into `main`.

No new npm package publication, CI provider or release destination is selected
by this migration. The existing Python release assets remain historical.

## Run the new checks

Node 20+:

```sh
npm ci
npm test
```

`npm test` needs permission to bind loopback sockets, but no PHP, browser or
Python. For actual PHP/Xdebug/Chromium, use the existing DDEV environment:

```sh
ddev exec npm ci
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:browser
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:drupal
```

The browser suite creates and stops its own PHP server on ports 19434/19433
by default (`PW_PHP_PORT`/`PW_XDEBUG_PORT` override them). The Drupal suite uses
the existing separate Drupal fixture and its configured connection to port 9003
in the parent DDEV container. Its listener binds `0.0.0.0` for that connection.
These checks do not modify PHP-FPM settings or start the Python daemon.
Missing PHP/Xdebug, browser binaries or Drupal sources fail the relevant job;
they do not produce a silent success through skips.

The existing browser cache is reused. New environments can install matching
Chromium with `ddev exec npx playwright install --with-deps chromium`, setting
`PLAYWRIGHT_BROWSERS_PATH` to the cache above when using these commands.
Drupal fixture provisioning still uses the existing `ddev drupal-setup` harness
during migration; replacing that tooling is part of the final cutover.

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
