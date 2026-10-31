# Development

[Documentation index](../README.md#documentation) · [Distribution](releasing.md)

## Repository layout

| Path | Purpose |
| --- | --- |
| `index.js`, `index.mjs`, `index.d.ts` | Playwright fixture entry points and types. |
| `core.js`, `core.mjs`, `core.d.ts` | Public standalone debugger exports and types. |
| `lib/dbgp.js`, `lib/encoding.js` | Internal transport, framing, command encoding and lossless bytes. |
| `lib/session.js`, `lib/records.js`, `lib/values.js` | Request execution, structured metadata and PHP values. |
| `lib/listener.js`, `lib/capture.js`, `lib/events.js` | Ownership, browser capture, shutdown and retained events. |
| `lib/paths.js` | Lexical source path namespaces. |
| `tests/unit/`, `tests/types/` | Scripted-peer regression tests and public type consumers. |
| `tests/browser/`, `tests/live/`, `tests/stress/` | Browser, real DBGp/runtime and concurrency checks. |
| `tests/drupal/`, `fixtures/drupal11/` | Drupal acceptance specs and separately provisioned application. |
| `tests/fixtures/` | Maintained checkout demo plus PHP fixtures used by live tests. |
| `examples/standalone.js` | Node/Playwright investigation without the Playwright Test runner. |
| `scripts/`, `.ddev/` | Setup, checks and local packaging. |
| `docs/` | Consumer, API, troubleshooting and contributor documentation. |

The package executes JavaScript directly; there is no generated build output to
commit. TypeScript is used to verify the public declaration contract. Python is
archived separately and is not part of the active toolchain.

## Fast checks

Use Node 20 or newer:

```sh
npm ci
npm run check:fast
```

`npm test` runs Node's unit tests with scripted engines and loopback sockets;
`npm run test:types` checks CommonJS and ESM TypeScript consumers. Neither needs
PHP or a browser. Environments that forbid binding loopback sockets must allow
that access before running the tests.

`./scripts/check_fast.sh` is a wrapper for the same fast checks. Use the locked
dependencies; the TypeScript compiler is portable across the host/container
checkout rather than requiring a platform-specific native compiler.

## Full environment

Install DDEV and its supported container engine, then run from the repository
root:

```sh
ddev start
ddev test-setup
ddev drupal-setup
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run check:all
```

`./scripts/check.sh` provisions the Drupal and test tooling and runs `check:all`.
`ddev drupal-setup` starts both projects, installs the pinned Composer dependencies
and seeds the separate Drupal database. Run setup only against these development
fixtures. Drupal's setup credentials and fixture data are described in its
[repository guide](https://github.com/djotto/DBGpilot/blob/main/fixtures/drupal11/README.md).

`ddev test-setup` installs locked npm dependencies, Chromium and system libraries,
then prepares historical Xdebug modules. Source downloads are checksum-verified
before compilation. The builder does not switch serving PHP-FPM to a historical
module. Cached browser executables and runtime modules live under
`/mnt/ddev-global-cache/dbgpilot/`.

A recreated DDEV container can retain cached browsers but lose installed system
libraries. Rerun `ddev test-setup` after recreation if tooling is missing. This
setup can download packages and compile modules; subsequent runs reuse caches.

## Demo and test servers

DDEV's document root is `tests/fixtures`. Open <https://xdebug.ddev.site/> or
<https://xdebug.ddev.site/checkout.php> for the form/AJAX checkout. Its two-line
root entry point loads the same checkout implementation used by browser tests.

The ordinary browser suite starts its own PHP CLI server on HTTP port `19434`,
with DBGp on `19433`, one test worker, and no reuse of an already-running server.
`PW_PHP_PORT` and `PW_XDEBUG_PORT` override those ports. Browser stress tests start
three independent PHP servers on the HTTP port and its next two ports; those
ports must remain separate from DBGp. Independent servers ensure each request
can reach Xdebug while another request is paused.

The Drupal fixture uses its own DDEV project, database and HTTPS URL,
`https://dbgpilot-drupal11.ddev.site`. It sends DBGp to `ddev-xdebug-web:9003` in
the parent project. The Drupal Playwright listener binds `0.0.0.0:9003` there.
`PW_DRUPAL_URL` changes the browser URL only; PHP's debugger destination must
still be configured separately. Run Drupal specs with one worker and no competing
IDE listener on that port.

## Test commands

| Command | What it checks |
| --- | --- |
| `npm test` | Transport/protocol, ownership, paths, values, events and failure regressions. |
| `npm run test:types` | Public CommonJS/ESM imports, fixture options and rejected invalid API uses. |
| `npm run test:browser` | Real Chromium/PHP navigation, capture, POST, AJAX, values, mapping and standalone operation. |
| `npm run test:compatibility` | End-to-end inspection/mutation smoke across six PHP/Xdebug profiles. |
| `npm run test:integration` | Function entry/return, hit counts, temporary breakpoints, stdout modes and eval-error recovery across those profiles. |
| `npm run test:drupal` | Actual render mutation, Form API persistence and autocomplete AJAX/database workflows. |
| `npm run test:stress` | Parallel CLI PHP sessions, release/stop, a 35-second browser pause, and three independent captures. |
| `npm run check:package` | Actual tarball contents and fresh installed CommonJS/ESM/TypeScript consumers. |
| `npm run check:fast` | Unit tests followed by types. |
| `npm run check:all` | All the above suites and package validation, in order. |

Run browser-dependent commands inside the parent DDEV container with the cache
variable, for example:

```sh
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:browser
ddev exec npm run test:integration
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:drupal
```

One browser test deliberately fails an assertion while PHP is paused and is
marked as an expected failure. The runner accepts it only when the expected
failure occurs; the following request verifies teardown released PHP.

## Runtime matrix

`tests/support/runtimes.js` is shared by compatibility and live integration:

| PHP | Xdebug | Module source |
| --- | --- | --- |
| 8.2 | 3.5.3 | Installed runtime |
| 8.3 | 3.5.3 | Installed runtime |
| 8.4 | 3.5.3 | Installed runtime |
| 8.5 | 3.5.3 | Installed runtime |
| 8.2 | 3.3.2 | Pinned cached historical module |
| 8.3 | 3.4.7 | Pinned cached historical module |

Missing executables/modules fail validation rather than silently skipping a
profile. `node scripts/prepare_test_runtimes.mjs` must run inside DDEV; it prepares
and verifies the two historical profiles. Integration contains six scenarios per
profile. Drupal 11.4.11 and Drush 13.8.0 are locked in the fixture's Composer files.

These checks establish support for the exercised workflows and versions. They
do not guarantee optional DBGp extensions absent from Xdebug.

## Reports and package verification

Ignored artifacts are written under `test-results/`:

- `playwright-js.xml` and `playwright-js/`: ordinary browser results and retained traces.
- `playwright-drupal-js.xml` and `playwright-drupal-js/`: Drupal results.
- `playwright-stress-js.xml` and `playwright-stress-js/`: browser stress results.
- `compatibility-js.json`, `integration-js.json`: actual runtime versions and outcomes.
- `js-package-validation.json`: package version, payload, artifact path, SHA-256 and clean-install evidence.

The package check packs an allowlisted payload, installs it outside the checkout,
compares installed bytes, and checks CJS, ESM, private export boundaries and
installed TypeScript consumers. The standalone core must load without importing
Playwright Test. Runtime modules, docs, declarations, notices and the standalone
example ship; development PHP/Drupal fixtures, tests, caches and reports do not.

The resulting local candidate is `dist/js-candidate/dbgpilot-<version>.tgz`.
Setup, tests and packaging do not upload it. See [distribution](releasing.md)
for installing or preparing a release.
