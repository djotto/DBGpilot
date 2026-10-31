# Python test migration inventory

Every historical `tests/test_*.py` file is accounted for below. The files
are preserved on [archive/python](https://github.com/djotto/DBGpilot/tree/archive/python/tests). This is a coverage
plan, not a declaration of equivalent coverage. A file marked partial contains
some behaviour exercised by the JS foundation; its other cases still need review.
Counts of parametrized pytest cases are not a migration target.

| Python test file | Disposition | JavaScript work |
| --- | --- | --- |
| `test_protocol.py` | Partial | Framing, fragmentation, quoting, binary payloads, namespace/length validation in `protocol.test.js`; stalled-write deadlines and late write errors in `cleanup.test.js`; remaining randomized-case audit pending. |
| `test_sessions.py` | Partial | State, operation guards, errors, late replies and explicit release in `session.test.js`; command availability and feature negotiation in `features.test.js`; remaining scenario audit pending. |
| `test_properties.py` | Partial | Binary/extended values, partial results, metadata, integers and nonfinite values in `values.test.js`; remaining format cases pending. |
| `test_evaluation_events.py` | Migrated/adapted | On-time evaluations do not duplicate stops or overflow the retained queue; abandoned success/error restores the pause and publishes recovery; expr/exec and HTTP replay portions excluded. |
| `test_cancellation.py` | Migrated/adapted | AbortSignal execution/wait/event cancellation retains engine ownership and future events; RPC IDs/tombstones/client reconnect portions retire. |
| `test_binary_evaluation.py` | Adapt | Raw binary command payload coverage started; retire HTTP binary-envelope input cases. |
| `test_review.py` | Partial | Engine/ownership limits and late-reply regressions retained; capture deadlines, late route installation, original-error preservation and bulk shutdown covered in `cleanup.test.js`/`listener.test.js`; daemon/client-only cases retire; remaining per-scenario audit pending. |
| `test_review_findings.py` | Migrated/adapted | Abandoning a close wait retains shared cleanup and releases PHP once; Python launch/auth/CLI/server-host portions retire. Core path semantics retain independent coverage. |
| `test_review_browser.py` | Migrated/adapted | Real PHP navigation completes after disposal during breakpoint setup or DBGp connection loss; route-cleanup failure preserves the action error and permits retry. Persistent-server loss adapts to direct socket/cleanup failures. |
| `test_browser.py` | Adapt | Core browser behaviours started in `checkout.spec.js`; replace daemon connections with fixture ownership. |
| `test_integration.py` | Migrated/adapted scenarios | Inspection/mutation/paging in the compatibility/browser suites; independent sessions and stop in stress tests; live stepping, exact hit counts, temporary breakpoints, stdout modes and exception/eval-error recovery in `integration.test.js` (36 cases across six runtimes). HTTP snapshot adapts to same-test browser capture; cross-script client portions retire. Per-assertion audit remains on the migration checklist. |
| `test_conformance.py` | Partial | Encoding/base64 constraints, command capability gates, optional negotiation failures, refresh and late acknowledgements migrated to `features.test.js`; existing wire/data coverage in `conformance.test.js`; remaining per-scenario audit pending. |
| `test_context_names.py` | Migrated | Valid/missing/empty/nonnumeric/fractional IDs and caller validation in `api.test.js`; HTTP duplication retires with the service. |
| `test_paths.py` | Migrated/adapted | 35 mapping tests cover Windows/UNC, byte/Unicode URIs, traversal, normalized roots, case policies, round trips and overrides. TOML discovery adapts to JS options; see exceptions. |
| `test_path_mapping_sessions.py` | Migrated/adapted | Mapped init/results/stack inputs/snapshot fallback/source/breakpoints/notifications in unit and actual Windows-to-Linux browser cases; HTTP/CLI/reconnect and optional spawnpoint portions excluded. |
| `test_compatibility.py` | Migrated | All six PHP/Xdebug combinations passed in `tests/live/compatibility.test.js`, with independent runtime results in `compatibility-js.json`; reconnect portions removed. |
| `test_stress.py` | Migrated/adapted | Real concurrent PHP processes, three simultaneous browser captures, explicit stop, owner shutdown and 35-second browser pause pass; daemon-restart/API retention portions retire. |
| `test_drupal.py` | Migrated/adapted | Three real scenarios passed in `acceptance.spec.js`: render-only mutation with unchanged database, Form API saved mutation and fresh read, autocomplete/database query; reconnect and owned Python daemon portions removed. |
| `test_browser_diagnostics.py` | Adapt | Use Playwright traces, screenshots and request diagnostics; preserve useful failure evidence. |
| `test_setup_browser.py` | Adapt | Replace owned Python daemon setup with fixture setup/teardown failure tests. |
| `test_setup.py` | Retire/adapt | Retire Python configuration and CLI ownership; retain relevant JS configuration validation. |
| `test_setup_network.py` | Retire/adapt | Retire daemon API host/auth checks; retain debugger-listener bind failures and cleanup. |
| `test_optional_commands.py` | Retire dedicated wrappers | Optional commands not supported by the tested Xdebug are outside the PHP-only replacement; raw command errors still covered. |
| `test_extensions.py` | Retire dedicated wrappers | No additional language engines, stdin or interactive shell in the replacement scope. |
| `test_proxy.py` | Defer | No proxy support promised by the first fixture milestone; explicitly resolve before cutover if consuming sites require it. |
| `test_proxy_integration.py` | Defer | Same proxy scope decision; do not imply compatibility from raw command support. |
| `test_pytest_plugin.py` | Retire | Replaced by actual Playwright fixture lifecycle and browser tests. |
| `test_server.py` | Retire/adapt | Retire HTTP API/reconnection/journals; retain any engine ownership/limits regressions in listener/session tests. |
| `test_client_transport.py` | Retire | HTTP client is removed from the target architecture. |
| `test_health.py` | Retire | No persistent HTTP health endpoint. |
| `test_server_hosts.py` | Retire/adapt | HTTP auth/host checks retire; listener address/bind coverage remains relevant. |
| `test_server_retention.py` | Retire | No daemon-retained session history; test in-process pruning instead. |
| `test_release.py` | Migrated/adapted | Actual npm tarball payload, license, installed bytes, fresh external consumers, CJS/ESM exports and installed TypeScript checks pass in `check_js_package.mjs`. Wheel/source build-specific assertions retire. No npm reproducible-build claim is made. |
| `test_github_release.py` | Retire/adapt | Python uploader is archived. Local JS artifact/consumer checks replace wheel assumptions; GitHub publication remains a documented manual step. |

The supplied five JS Drupal proof tests are separate from `test_drupal.py`.
They now run against this repository as initial smoke coverage (five passed);
they do not replace the original persisted-save and autocomplete scenarios.

The target excludes cross-script debugging. Same-process scripts remain useful:
`playwright-xdebug/core` provides test-independent controls, and the fixture adds
Playwright steps and automatic teardown over those same controls.
