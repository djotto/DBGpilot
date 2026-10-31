# Development

Node 20+ is required. Install the locked dependencies with `npm ci`, then run
`npm run check:fast` for the protocol, ownership, value and TypeScript checks.
These tests need loopback sockets. They do not need PHP or a browser.

For the full PHP/Xdebug, Chromium and Drupal suite:

```sh
ddev start
ddev test-setup
ddev drupal-setup
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run check:all
```

`./scripts/check.sh` provisions both fixtures and runs the full suite.
`./scripts/check_fast.sh` runs the fast checks in the current Node environment.
`ddev test-setup` installs npm dependencies, Chromium and the pinned historical
Xdebug modules. The runtime builder is JavaScript and verifies downloaded source
checksums before compiling. It does not change the application's PHP-FPM runtime.
The DBGp proxy is deferred and is not downloaded by setup.

The browser suite starts its own PHP server on HTTP port 19434 and Xdebug port
19433. `PW_PHP_PORT` and `PW_XDEBUG_PORT` override these. Browser stress tests
start three independent PHP servers using the HTTP port and its next two ports.
The runtime matrix tests PHP 8.2–8.5 with the
installed Xdebug, plus cached PHP 8.2/Xdebug 3.3.2 and PHP 8.3/Xdebug 3.4.7.
Missing runtimes, Chromium or Drupal sources fail their checks.

`ddev exec npm run test:integration` runs the remaining selected real-Xdebug
scenarios without a browser: function entry/return, exact hit counts and temporary
breakpoints, all three stdout routing modes, and recovery from an invalid PHP
evaluation. It runs 36 scenario checks across those same six runtime combinations.
Both live suites share `tests/support/runtimes.js`. Runtime versions and case
results are written to `test-results/integration-js.json`; `check:all` includes
this suite after the compatibility smoke checks.

The [separate Drupal fixture](../fixtures/drupal11/README.md) sends debugger
connections to port 9003 in the parent DDEV container. Run its specs with one
worker and no competing IDE listener. Test-owned PHP sessions are released on
success or failure. No process retains them after the test or script exits.

Reports, traces and screenshots are under `test-results/`. The package check
builds an allowlisted tarball, installs it outside the repository, compares its
bytes and checks CommonJS, ESM and installed TypeScript consumers. Its report is
`test-results/js-package-validation.json`; the candidate is under `dist/js-candidate/`.
