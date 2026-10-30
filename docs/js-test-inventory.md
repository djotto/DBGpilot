# Python test migration inventory

Every existing `tests/test_*.py` file is accounted for below. This is a coverage
plan, not a declaration of equivalent coverage. A file marked partial contains
some behaviour exercised by the JS foundation; its other cases still need review.
Counts of parametrized pytest cases are not a migration target.

| Python test file | Disposition | JavaScript work |
| --- | --- | --- |
| `test_protocol.py` | Partial | Framing, fragmentation, quoting, binary payloads, namespace/length validation migrated to `protocol.test.js`; expand randomized/backpressure cases. |
| `test_sessions.py` | Partial | State, operation guards, errors, late replies and explicit release in `session.test.js`; complete remaining session APIs. |
| `test_properties.py` | Partial | Binary/extended values, partial results, metadata, integers and nonfinite values in `values.test.js`; remaining format cases pending. |
| `test_evaluation_events.py` | Partial | On-time eval avoids duplicate stops; abandoned eval restores state; extend retained in-process event coverage. |
| `test_cancellation.py` | Adapt | AbortSignal waiter cancellation started; retire RPC cancellation/tombstones/client reconnect cases. |
| `test_binary_evaluation.py` | Adapt | Raw binary command payload coverage started; retire HTTP binary-envelope input cases. |
| `test_review.py` | Review individually | Preserve engine/lifecycle regressions; retire daemon/client-only cases. |
| `test_review_findings.py` | Review individually | Preserve fixture cleanup/cancellation cases; retire Python setup/config-only cases. |
| `test_review_browser.py` | Adapt | Navigation/POST/AJAX, copied snapshots, late stops and assertion-failure cleanup started. |
| `test_browser.py` | Adapt | Core browser behaviours started in `checkout.spec.js`; replace daemon connections with fixture ownership. |
| `test_integration.py` | Port | Complete live command coverage and engine error/termination assertions. |
| `test_conformance.py` | Port | Port relevant PHP/Xdebug wire and data cases; no HTTP transport requirement. |
| `test_context_names.py` | Port | Add context discovery and invalid context metadata regressions. |
| `test_paths.py` | Port | Local/remote roots, Windows paths, URI preservation and ambiguity checks. |
| `test_path_mapping_sessions.py` | Adapt | Port mapped breakpoints/results; remove client reconnect steps. |
| `test_compatibility.py` | Adapt | Preserve real PHP/Xdebug version matrix and byte/value/path assertions. |
| `test_stress.py` | Adapt | Retain concurrent requests, limits and long pauses; replace daemon restart with owner/worker lifecycle tests. |
| `test_drupal.py` | Adapt | Preserve rendering, form/database persistence and autocomplete AJAX; remove reconnect and daemon setup portions. |
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
| `test_release.py` | Replace | npm package content/install/license/export checks replace wheel/source-distribution checks. |
| `test_github_release.py` | Review at cutover | Current uploader is Python-wheel specific; replace artifact assumptions if continuing GitHub Releases. |

The supplied five JS Drupal proof tests are separate from `test_drupal.py`.
They now run against this repository as initial smoke coverage (five passed);
they do not replace the original persisted-save and autocomplete scenarios.

The target excludes cross-script debugging. Same-process scripts remain useful:
`playwright-xdebug/core` provides test-independent controls, and the fixture adds
Playwright steps and automatic teardown over those same controls.
