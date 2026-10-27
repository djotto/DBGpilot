# Developing DBGpilot

The runtime uses only the Python standard library and is MIT licensed. Poetry
builds `src/dbgpilot`; `src/checkout.php` is part of the separate DDEV test site
and is not included in the Python package.

## Tests

The [protocol/lifecycle review](protocol-review.md) links confirmed findings to
fixes and explicit limitations. `tests/test_review.py` covers malformed XML and
metadata, cancellation arrival races, late breakpoint/capability replies,
lost HTTP calls, resource caps, concurrent starts and failure cleanup.
`tests/test_review_browser.py` verifies actual PHP release during in-progress
capture shutdown and diagnostics when the server is unavailable. Run the focused
review with `ddev poetry run pytest tests/test_review.py tests/test_review_browser.py
--junitxml=test-results/review-junit.xml`; `./scripts/check.sh` remains the
required full check, including Drupal, builds and installed browser examples.
The optional investigation script is separate development tooling; it does not
install an engine dependency or add an unmaintained engine to the runtime matrix.

The development tools are pytest, pytest-asyncio, Hypothesis, and Playwright.

`tests/test_setup.py` checks shared configuration, process readiness/identity,
authentication, deadlines, cancellation and ownership. `tests/test_setup_network.py`
checks competing/independent CLI launches and reuse over real HTTP/TCP.
`tests/test_pytest_plugin.py` runs the opt-in fixtures in a separate
pytest process with real child teardown. `tests/test_setup_browser.py` exercises
owned/reused setup and the plugin against actual Chromium/PHP; the Drupal suite
also exercises configured owned startup. After building the wheel,
`scripts/check_setup_examples.py --live` runs copied standalone and pytest
examples against the installed package outside the source tree. Without
`--live`, it checks imports/help/collection only. See [Python setup](python-setup.md).

```sh
poetry install
poetry run pytest -m "not integration"
ddev test-setup
ddev poetry run pytest -m integration
ddev poetry run pytest
poetry build
```

Protocol/data tests cover arbitrary binary payloads, packet fragmentation,
multibyte text split across reads, coalesced packets, malformed framing/XML,
base64, command escaping, extended properties, types, and truncation.

Session tests use a scripted engine over real loopback TCP: interleaved events,
out-of-order responses, errors, cancellation/late responses, disconnects, queue
limits, partial handshakes, concurrent sessions, and cleanup. Some host
sandboxes prohibit TCP binds; the complete suite also runs in DDEV.

`tests/test_conformance.py` covers the first audit priorities: mixed-content
notification bodies, structured metadata, evaluation concurrency and late/error
responses, core wrappers/type maps, remaining core options, clean versus
truncated stop EOF, capability gating, postmortem inspection, encoding profiles,
and asynchronous break/status responses. These scripted peers deliberately
exercise behaviour unavailable in PHP. They do not establish support for every
optional DBGp extension. The real multi-version matrix is described below.

`tests/test_server.py` exercises real HTTP connections, filtering/claiming,
reconnection, replay/expiry of event cursors, concurrent control, validation,
authentication, cleanup, and subprocess CLI clients. The live integration suite
also starts a standalone server process, obtains a paused HTTP snapshot through
a client process that exits, and then uses another client to mutate PHP and
finish that same HTTP response. The HTTP/server-only tests need no browser.

`tests/test_browser.py` now runs real Chromium against PHP-FPM with the reusable
helper. `tests/test_cancellation.py` verifies explicit/automatic remote
cancellation and delayed-submission protection. `tests/test_compatibility.py`
tests six real PHP/Xdebug combinations, including checksum-pinned historical
source builds. `tests/test_stress.py` covers concurrent clients/requests, long
pauses, and shutdown/restart; `tests/test_client_transport.py` verifies the native
async HTTP transport. Setup, exact matrix versions, and report locations are in
[compatibility.md](compatibility.md).

Integration tests run actual PHP CLI/Xdebug and a PHP-FPM HTTP request. They
verify returning snapshots while PHP remains paused, further inspection,
extended/binary properties, frame selection, paging/full values, mutation,
stepping, breakpoints, streams, exceptions, and independent live sessions. They
skip outside DDEV and fail if PHP/Xdebug is absent inside the harness.

`tests/test_extensions.py` covers stdin configuration, binary input while run is
pending, synchronous stdin-read notifications, late/out-of-order acknowledgements,
interactive prompts/buffers/reset, interactive-only engines, execution guards,
and remote event replay. `tests/test_proxy.py` covers short-lived proxy control
connections, framing variants, validation, opaque proxy errors, owned cleanup,
timeouts/cancellation, and strict versus proxy-compatible detach EOF.
`tests/test_proxy_integration.py` starts official dbgpProxy 0.6.2, routes real
PHP/Xdebug through it, reconnects/mutates/detaches, verifies PHP output and key
cleanup, and confirms that actual Xdebug rejects unsupported stdin/interact.
The positive shell/stdin tests use scripted peers, not PHP engine support.

`tests/test_optional_commands.py` exercises expr/exec and all five spawnpoint
commands over real TCP and HTTP. Cases cover per-command capability gating,
text/binary code, paged/type-mapped results, explicit failure flags, malformed
responses, opaque IDs/vendor XML, inventory updates, cancellation/deadlines and
late acknowledgements, engine errors, execution guards, disconnects, and client
reconnection. Positive cases use scripted engines; the live rejection test checks
all seven commands against actual Xdebug and then finishes the same PHP request.
These checks extend the audit's optional-command coverage, not a certification
of full DBGp conformance or support in other language engines.

`tests/test_paths.py` covers lexical directory-prefix matching and both mapping
directions, URI escaping/application bytes, encoded traversal, root conflicts,
round-trip ambiguity, Windows drives/UNC paths, case policies, symlink aliases,
configuration discovery/overrides, malformed TOML, and generated suffixes.
`tests/test_path_mapping_sessions.py` exercises model/event/inventory locations,
outbound commands, source retrieval, remote diagnostics/filtering/reconnection,
CLI discovery and explicit configuration, actual PHP breakpoints, and Chromium
using Windows local paths against the Linux server. Path mapping adds no runtime
dependency or filesystem-existence requirement.

The [Drupal 11 fixture](drupal.md) is a separately locked Composer/DDEV application
with its own database. `tests/test_drupal.py` covers real core rendering inside
a Fiber, a persisted Form API save after reconnect/mutation, and the ordinary
database-backed author-autocomplete AJAX widget. Setup seeds only fixture-owned
records, and the save test deletes its newly created content. `./scripts/check.sh`
starts/seeds this fixture before browser setup and requires it for the full suite.
`ddev drupal-test` runs just those cases; absent fixture state skips them only in
ordinary optional pytest runs. Core/vendor downloads are ignored and excluded
from DBGpilot distributions; the Python runtime still uses only the stdlib.

## Design references and provenance

DBGpilot is an original implementation using the
[DBGp 1.0 draft 22 specification](https://xdebug.org/docs/dbgp). The specification
and live Xdebug define expected results. These projects were inspected as
architecture/edge-case references:

- [Komodo Python DBGp](https://github.com/agroszer/komodo-python3-dbgp/tree/aa277c0055dffb597777bba49d4eb65d30af02a0):
  correlation, event dispatch, sessions, and paging.
- [Vdebug](https://github.com/vim-vdebug/vdebug/tree/66517871178779ac54e19ed0f34d66805b820664):
  basic operations and reproduced framing/property regressions.
- [Pugdebug](https://github.com/Mte90/pugdebug/tree/d07044536f0bd5ab3cef3d178cc35a2e51e0e7a2):
  Xdebug 3 integration and separation from GUI event handling.

No upstream implementation code is included or imported. The three reference
dependencies, their Qt dependencies, and vendored snapshots were removed after
independent tests passed. The audit documents retain the historical research.

Live tests exposed Xdebug-specific behaviour documented in the API guide:
current-frame-only eval, expression-based assignment, explicit full-value
requests, temporary breakpoints, and fixed Latin-1 XML framing over application
bytes. The library has a specific byte-preserving Xdebug profile and otherwise
requires UTF-8 communication. Secondary implementation references:
[handler_dbgp.c](https://github.com/xdebug/xdebug/blob/master/src/debugger/handler_dbgp.c),
[debugger.c](https://github.com/xdebug/xdebug/blob/master/src/debugger/debugger.c).
