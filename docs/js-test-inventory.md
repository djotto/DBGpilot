# Python test migration inventory

The final audit accounts for all **34 archived test files and 309 named test-function families**.
See [the audit summary](migration-audit.md) and [case-by-case ledger](migration-audit.json)
for each function's disposition, JS evidence and scope differences. Parametrized
instances and generated samples are not a test-count equivalence claim.

| Python test file | Disposition | JavaScript work |
| --- | --- | --- |
| `test_protocol.py` | 12 retained | Framing, fragmentation, quoting, binary payloads, namespace/length validation in `protocol.test.js`; stalled-write deadlines and late write errors in `cleanup.test.js`; seeded fragmentation samples are covered in `migration-audit.test.js`. |
| `test_sessions.py` | 17 retained | State, operation guards, errors, late replies and explicit release in `session.test.js`; command availability and feature negotiation in `features.test.js`; remaining named scenarios reconciled in the case ledger. |
| `test_properties.py` | 10 retained | Binary/extended values, partial results, metadata, integers and nonfinite values in `values.test.js`; standard/extended/typemap value edge cases now covered in `migration-audit.test.js`. |
| `test_evaluation_events.py` | 6 retained | On-time evaluations do not duplicate stops or overflow the retained queue; abandoned success/error restores the pause and publishes recovery; expr/exec and HTTP replay portions excluded. |
| `test_cancellation.py` | 3 retained; 5 retired | AbortSignal execution/wait/event cancellation retains engine ownership and future events; RPC IDs/tombstones/client reconnect portions retire. |
| `test_binary_evaluation.py` | 4 retained; 2 retired | String/Buffer eval and assignment byte fidelity, targeting, and error recovery are covered in `migration-audit.test.js`; HTTP binary-envelope input is retired. |
| `test_review.py` | 22 retained; 5 retired | Engine/ownership limits and late-reply regressions retained; capture deadlines, late route installation, original-error preservation and bulk shutdown covered in `cleanup.test.js`/`listener.test.js`; daemon/client-only cases retire; remaining scenarios reconciled in the case ledger. |
| `test_review_findings.py` | 1 retained; 6 retired | Abandoning a close wait retains shared cleanup and releases PHP once; Python launch/auth/CLI/server-host portions retire. Core path semantics retain independent coverage. |
| `test_review_browser.py` | 2 retained | Real PHP navigation completes after disposal during breakpoint setup or DBGp connection loss; route-cleanup failure preserves the action error and permits retry. Persistent-server loss adapts to direct socket/cleanup failures. |
| `test_browser.py` | 6 retained | Navigation, mutation, copied snapshots, POST/AJAX and failure cleanup run through direct fixture ownership in `checkout.spec.js`/`capture.spec.js`. |
| `test_integration.py` | 7 retained; 1 retired | Inspection/mutation/paging in the compatibility/browser suites; independent sessions and stop in stress tests; live stepping, exact hit counts, temporary breakpoints, stdout modes and exception/eval-error recovery in `integration.test.js` (36 cases across six runtimes). HTTP snapshot adapts to same-test browser capture; cross-script client portions retire. Function-family audit is complete; lifetime/workload adaptations are explicit in the case ledger. |
| `test_conformance.py` | 30 retained; 3 retired | Encoding/base64 constraints, command capability gates, optional negotiation failures, refresh and late acknowledgements migrated to `features.test.js`; existing wire/data coverage in `conformance.test.js`; remaining scenarios reconciled in the case ledger. |
| `test_context_names.py` | 5 retained | Valid/missing/empty/nonnumeric/fractional IDs and caller validation in `api.test.js`; HTTP duplication retires with the service. |
| `test_paths.py` | 16 retained; 2 deferred | 35 mapping tests cover Windows/UNC, byte/Unicode URIs, traversal, normalized roots, case policies, round trips and overrides. TOML discovery adapts to JS options; see exceptions. |
| `test_path_mapping_sessions.py` | 8 retained; 3 retired | Mapped init/results/stack inputs/snapshot fallback/source/breakpoints/notifications in unit and actual Windows-to-Linux browser cases; HTTP/CLI/reconnect and optional spawnpoint portions excluded. |
| `test_compatibility.py` | 1 retained | All six PHP/Xdebug combinations passed in `tests/live/compatibility.test.js`, with independent runtime results in `compatibility-js.json`; reconnect portions removed. |
| `test_stress.py` | 4 retained; 1 retired | Real concurrent PHP processes, three simultaneous browser captures, explicit stop, owner shutdown and 35-second browser pause pass; daemon-restart/API retention portions retire. |
| `test_drupal.py` | 4 retained | Three real scenarios passed in `acceptance.spec.js`: render-only mutation with unchanged database, Form API saved mutation and fresh read, autocomplete/database query; reconnect and owned Python daemon portions removed. |
| `test_browser_diagnostics.py` | 1 deferred | User chose to defer the shared helper: existing Playwright traces and diagnostics added to individual tests are sufficient until repeated failures demonstrate a need. |
| `test_setup_browser.py` | 3 retained | Standalone Node and Playwright fixture entry points exercise real PHP/browser mutation and teardown; Python daemon ownership is removed. |
| `test_setup.py` | 1 retained; 14 retired | Python configuration/launch/readiness contracts are retired; direct capture deadlines and explicit JS configuration are retained. |
| `test_setup_network.py` | 2 retained; 3 retired | Daemon API host/auth/lifetime contracts are retired; direct bind conflicts and serialized startup are tested in `listener.test.js`. |
| `test_optional_commands.py` | 21 retired | Optional commands not supported by the tested Xdebug are outside the PHP-only replacement; raw command errors still covered. |
| `test_extensions.py` | 14 retired; 1 deferred | No additional language engines, stdin or interactive shell in the replacement scope. |
| `test_proxy.py` | 11 deferred | Proxy registration remains deferred until a consuming environment requires it; all original cases are recorded in the ledger. |
| `test_proxy_integration.py` | 2 deferred | Live proxy registration/routing remains deferred with the proxy API. |
| `test_pytest_plugin.py` | 1 retired | Replaced by actual Playwright fixture lifecycle and browser tests. |
| `test_server.py` | 10 retained; 10 retired | Ten engine/ownership/filter/validation scenarios adapt to direct APIs; ten HTTP API/reconnection/journal/schema contracts retire. |
| `test_client_transport.py` | 5 retired | HTTP client is removed from the target architecture. |
| `test_health.py` | 4 retired | No persistent HTTP health endpoint. |
| `test_server_hosts.py` | 6 retired | HTTP auth/host checks retire; listener address/bind coverage remains relevant. |
| `test_server_retention.py` | 2 retired | No daemon-retained session history; test in-process pruning instead. |
| `test_release.py` | 2 retained; 6 retired | Actual npm tarball payload, license, installed bytes, fresh external consumers, CJS/ESM exports and installed TypeScript checks pass in `check_js_package.mjs`. Wheel/source build-specific assertions retire. No npm reproducible-build claim is made. |
| `test_github_release.py` | 4 retired | Python uploader is archived. Local JS artifact/consumer checks replace wheel assumptions; GitHub publication remains a documented manual step. |

The supplied five JS Drupal proof tests are separate from `test_drupal.py`.
They run against this repository as smoke coverage (five passed);
they do not replace the original persisted-save and autocomplete scenarios.

The target excludes cross-script debugging. Same-process scripts remain useful:
`playwright-xdebug/core` provides test-independent controls, and the fixture adds
Playwright steps and automatic teardown over those same controls.
