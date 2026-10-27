# Compatibility and stress coverage

The [fresh protocol/lifecycle review](protocol-review.md) records findings,
regressions, resource policies, and support boundaries. Its optional-engine
investigation actually attempted the pinned MIT-licensed Python candidate;
the current launcher fails on Python 3.13 because it requires `imp` (removed
in 3.12). No additional live optional-command support is claimed. Reproduce the
investigation with `ddev poetry run python scripts/investigate_optional_engines.py`;
version/checksum/runtime evidence is in `test-results/optional-engines.json`.
Parser, scripted-peer, real Xdebug and actual application evidence remain
distinct. Returned breakpoint state strings include Xdebug's vendor `temporary`
notification state and are preserved rather than constrained to request enums.

Run the full environment setup and suite inside DDEV:

```sh
ddev test-setup
ddev poetry run pytest --junitxml=test-results/junit.xml
# Focused suites:
ddev poetry run pytest -m browser
ddev poetry run pytest -m compatibility
ddev poetry run pytest -m stress
```

`test-setup` installs development dependencies, the Playwright-matched Chromium
build/system libraries, two historical Xdebug modules, and official dbgpProxy
0.6.2. Browser binaries, the proxy binary, and compiled modules live in DDEV's
persistent global cache. Rerun setup after a
fresh container/rebuild to restore system libraries. This does not install
Playwright, the proxy, or historical Xdebug into the Python package's runtime
dependencies.

## Real runtime matrix

These six combinations passed the representative server/controller round trip:

| PHP | Xdebug | Source |
| --- | --- | --- |
| 8.2.35 | 3.5.3 | Installed DDEV CLI |
| 8.3.36 | 3.5.3 | Installed DDEV CLI |
| 8.4.22 | 3.5.3 | Installed DDEV CLI; also the PHP-FPM browser harness |
| 8.5.7 | 3.5.3 | Installed DDEV CLI |
| 8.2.35 | 3.3.2 | Checksum-pinned source build |
| 8.3.36 | 3.4.7 | Checksum-pinned source build |

Matrix tests check initialization/capabilities, conditional breakpoints, returned
snapshots, extended/NUL keys, Unicode names and paths, binary strings, stacks,
evaluation, type maps, paging/full values, assignment, stepping, reconnecting,
detach, and final PHP output. `test-results/compatibility.json` records the
actual PHP/Xdebug versions and pass/fail status for each run; PHP patch versions
may advance when the harness packages are updated.

Historical modules are compiled with the corresponding PHP development tools
from official [Xdebug source releases](https://xdebug.org/download/historical).
The exact source URLs and SHA-256 hashes are pinned in
`scripts/prepare_test_runtimes.py`. Builds use temporary source directories and
keep logs/modules in `/mnt/ddev-global-cache/dbgpilot/runtimes`. Tests select a
historical module explicitly using `php -n -d zend_extension=...`; they do not
replace the application's installed extension or PHP-FPM configuration. The
historical engine sources/modules are development test tooling, not code
distributed in DBGpilot's wheel.

This is representative compatibility coverage, not full DBGp conformance or a
claim about every combination of PHP and Xdebug. Other debugger engines and
optional protocol extensions remain outside this matrix.

## Proxy and optional command coverage

The suite runs the official Linux dbgpProxy 0.6.2 with actual PHP/Xdebug, verifies
registration and duplicate-key rejection, and reconnects to a paused session to
inspect/mutate PHP and finish its request. Shutdown releases the key for a new
registration. Setup verifies the downloaded x86-64 or ARM64 binary against the
SHA-256 pinned in `scripts/prepare_test_runtimes.py`; binaries are cached outside
the repository and are not included in the wheel.

That proxy suppresses final `stopped` replies. Tests verify clean detach EOF for
known proxy sessions while retaining strict direct-session and truncated-packet
handling. Application output verifies successful PHP completion independently
of the inferred EOF result. See [proxy behaviour](proxies-and-shells.md).

Stdin and interactive-shell success paths use scripted engines, including both
async input delivery and synchronous stdin-read notifications. A live Xdebug
test verifies that its unsupported stdin/interact capabilities cause clean
rejection and leave the session usable. Implementing these DBGp APIs does not
add those commands to Xdebug itself.

Expression-only evaluation (`expr`), code-fragment execution (`exec`), and the
five spawnpoint operations also have scripted TCP/HTTP coverage. It checks
capability gating, results, metadata, errors, cancellation/late replies, and
reconnection. The live rejection test checks these seven commands alongside
stdin/interact and verifies PHP can still complete normally. These positive
scripted tests do not add another real language engine to the runtime matrix.

## Browser and stress scenarios

The separate [Drupal 11.4.11 fixture](drupal.md) adds actual core rendering,
authenticated Form API/database persistence, and the author-autocomplete AJAX
widget. Its tested stack is PHP 8.4.22 / Xdebug 3.5.3 / MariaDB 11.8.8, with
Drush 13.8.0 and locked Composer dependencies. Cross-container debugger routing,
local source mapping, render-Fiber stacks, reconnects, and mutation are exercised
without modifying Drupal core. `test-results/drupal11.json` records the runtime
and three scenarios; the browser screenshot is `test-results/drupal11.png`.

After recreating the parent container during setup, the six-variant suite also
passed with PHP 8.2.31 and 8.3.31 replacing the earlier 8.2.35 and 8.3.36 builds;
the 8.4.22/8.5.7 entries remain the same. Reports retain observed passed versions
across runs. This does not imply every recorded combination ran in one suite.

- Actual headless Chromium/Playwright to PHP-FPM/Xdebug, with snapshots returned
  before the browser action finishes, a new client changing PHP, and final DOM
  assertions.
- Four simultaneous browser requests paused and resumed independently with
  distinct session IDs/IDE keys and distinct resulting totals.
- A 35-second paused navigation after the first client closes, followed by
  reconnection and successful completion. No browser navigation timeout or
  automatic debugger idle detach interrupts the pause.
- Server shutdown during a paused browser request, successful PHP completion,
  and restart on the same API/Xdebug ports with old IDs explicitly rejected.
- Eight simultaneous scripted sessions with client closure, late break replies,
  independent reconnection/event replay, and explicit detach.
- 64 outstanding session waits while health and cancellation remain responsive.
  The client uses asyncio HTTP streams rather than one worker thread per wait.
- Explicit and automatic cancellation, pre-submission cancellation, waiter
  claiming races, replayable events, and bounded cancellation history.
- Fragmented/malformed/truncated HTTP responses, response size limits, and error
  correlation for the async client transport.
- Configured directory mappings with real PHP/Xdebug source and breakpoint
  requests, plus Windows-style local paths in a Chromium/Playwright capture
  against the Linux server. Reconnection retains local paths and engine URIs;
  mutation completes the request with the expected rendered total.

The long-pause test defaults to 35 seconds. Set `DBGPILOT_TEST_PAUSE_SECONDS` when
deliberately shortening or extending that scenario; report the actual duration
with your results. These controlled stress cases establish specific behaviours,
not a throughput benchmark or unlimited-session guarantee.
