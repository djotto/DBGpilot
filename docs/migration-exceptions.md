# Migration exceptions and decisions

Keep this list separate from unfinished work in [MIGRATION.md](../MIGRATION.md).
An item being pending does not mean it cannot be implemented in JavaScript.
Nothing here is silently removed from the Python reference before cutover.

| Item | Why it does not migrate directly | Current handling / discussion |
| --- | --- | --- |
| Cross-script paused-session retention | Requires a service that owns sockets beyond the script/test; incompatible with the agreed test-owned lifetime. | Explicitly excluded by the user. Same-process timeout recovery is retained. |
| HTTP daemon, RPC clients, health endpoint, replay cursors, cancellation tombstones | The replacement has no remote control service. Porting these would recreate the excluded architecture. | Retire service-specific cases; migrate engine ownership, cancellation and limits to direct/fixture tests. |
| pytest plugin and Python asyncio fixture configuration | Playwright Test owns fixture and browser lifetimes. | Replace with actual Playwright setup/failure/teardown checks. |
| Python wheels, Poetry metadata and wheel/source reproducibility checks | JavaScript packages have different artifact/install semantics. | Replace with npm package content, clean-install, exports, license and examples checks before cutover. |
| Python-specific release uploader | Assumes wheel and Python source artifacts. | Keep existing releases historical; decide the JS release artifact workflow before replacing the uploader. No publication authorized by this migration. |
| Optional stdin, interactive shells, expr/exec and spawnpoints | The tested Xdebug does not support these commands; original success tests use simulated non-Xdebug engines. | Dedicated wrappers are outside the initial PHP target. Keep raw-command errors correct. Discuss if another engine becomes a requirement. |
| Interrupting running PHP | The tested Xdebug advertises `supports_async=0`; neither a JS port nor a fixture adds engine support. | Preserve accurate state and explicit release; do not promise interruption. |
| Evaluating PHP in an arbitrary older stack frame | The tested Xdebug ignores eval depth. | Keep current-frame evaluation; frame-specific property/context reads and writes remain supported. |
| DBGp proxy | Feasible in JavaScript, but not included in the supplied fixture and requires a distinct registration/listener workflow. | Deferred decision, **not** a technical impossibility. Original proxy tests remain in the inventory for discussion before cutover. |
| Historical PB04 path override semantics | Two mappings with different local roots and the same remote root are currently rejected, matching the original contract. | Keep that contract during the port; discussion can decide whether remote-root replacement should be added later. |
| Cancelling arbitrary browser-action tasks | JavaScript promises cannot be forcibly cancelled like an asyncio task. Closing a browser page would also destroy caller-owned state. | Abort helper waits, release PHP, remove routes and wait up to one second for the action. An arbitrary callback that remains pending stays caller-owned; its rejection is handled. Discuss page ownership if stronger cancellation is needed. |
| Automatic TOML discovery and CLI path-map overrides | Those entry points belong to the Python setup/CLI layer. | Mapping behaviour is ported; configure `xdebugPathMappings` / `xdebugBaseDir` through Playwright or `PathMapper` through the standalone API. A TOML compatibility reader is feasible if existing consumers need one. |

As additional engine, runtime, configuration or coverage obstacles are discovered,
record the exact limitation and available alternative here. Ordinary missing APIs,
unported tests and setup work belong on the migration checklist instead.
