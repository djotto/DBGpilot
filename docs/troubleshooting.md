# Troubleshooting

[Documentation index](../README.md#documentation) · [Setup](getting-started.md) · [Workflows](workflows.md)

## No Xdebug session arrives

Check the PHP-to-Node connection before changing breakpoint code:

1. Verify Xdebug is loaded in the serving PHP runtime and `xdebug.mode` includes
   `debug`. CLI and web PHP can load different configurations.
2. Verify `xdebug.start_with_request=trigger` and that the request carries a
   trigger. The fixture enables a cookie for `baseURL`; `enableFor()` covers
   another hostname. Capture adds query triggers to its selected request.
3. Check PHP's `xdebug.client_host` and port from PHP's network namespace. They
   identify the Node listener, not the website. Across containers, bind Node to
   a reachable interface such as `0.0.0.0` and use its container hostname in PHP.
4. Check accepted trigger values and IDE keys. Capture keys are separate from
   the parent fixture key; see [restricted triggers](getting-started.md#restricted-trigger-values).
5. Confirm the request really reaches PHP. Browser/service-worker caches and
   reverse-proxy caches can avoid application execution altogether.

For PHP-side diagnostics, temporarily configure a writable Xdebug log:

```ini
xdebug.log=/tmp/dbgpilot-xdebug.log
xdebug.log_level=7
```

Restart the actual serving runtime when required and reproduce one request.
Inspect connection attempts, destination and trigger behavior. See
[Xdebug's logging settings](https://xdebug.org/docs/step_debug#log). Restore the
previous logging configuration after diagnosis if you do not need the logs.

In a core script, also attach `listener.on('diagnostic', error => console.error(error))`
and inspect `listener.diagnostics`. Invalid initialization and preparation errors
are reported; fixture waiters receive preparation failures instead of only a
silent generic timeout.

## Port already in use

Use one Playwright worker for a shared debugger port. Close another IDE/debugger
listener, another DBGpilot run, or configure a different port at both ends.
An alternate Node port without matching PHP configuration will not attach.
A previous process left alive can retain the port until it closes its listener.

## PHP connects but the breakpoint is missed

Confirm the source path **as PHP sees it**, and that the line contains executable
code reached by that request. Use [path mappings](values-and-paths.md#source-paths)
when filesystem roots differ. Check `getBreakpoint(id)`, `breakpoints()` and
resolved notifications when the engine supplies them.

Breakpoints pause before the marked statement runs. Comments, blank lines,
unexecuted branches and an outdated source copy can mislead line selection.
In Drupal, cached render output or a cached response may bypass application
code. Choose a line in the actual request path or invalidate the relevant cache
in your test setup. An exception breakpoint only helps if that exception occurs.

A capture with no reachable breakpoint rejects with a finished-without-breakpoint
error and releases PHP. It does not automatically pause at the first statement.

## Browser navigation or click hangs

A paused PHP request cannot finish its HTTP response. Inspect and change PHP,
then call `detach()` before awaiting a navigation's completion. `finished()`
waits for the action; it does not resume the request.

A click dispatching AJAX can complete while PHP is still paused. In that case,
assert the final DOM or wait for a response after detach. Waiting for the click
alone proves only that the action completed.

If no debugger session exists, check whether an unrelated request is holding the
only PHP worker. Cookie-triggered background requests can also pause; unclaimed
ones detach after the configured delay. Several simultaneous paused requests
need enough independent PHP workers. The test harness uses independent CLI
servers for this reason.

## The test times out during an intentional pause

Increase the Playwright test timeout and any relevant browser/action wait. The
capture timeout only covers setup until the paused handle returns. Its expiry
is separate from continuation/evaluation and `finished()` timeouts. See the
[timeout table](workflows.md#timeouts-and-cancellation).

A CommandTimeout means the caller stopped waiting, not that PHP stopped.
Use `waitForPause()` for a late continuation response. Do not issue inspection
commands while the session still owns a pending operation. To abandon the
investigation, close the capture or dispose its owner.

## Xdebug says a command is unsupported

Catch `XdebugError` and inspect `command`, `code`, `message` and the preserved
engine response. `getCapabilities()` provides a fresh inventory for diagnosis;
it is not a prerequisite for every command. `featureGet(name)` queries one
feature or command. A `supported` feature whose `value` is `0` differs from an
unrecognized feature. For numeric/list features, read the value instead of
interpreting `enabled` as universal availability.

DBGpilot does not simulate unsupported DBGp commands. Watch breakpoints,
optional stream operations and vendor-specific extensions depend on the engine.
A raw command sends the request; it does not supply missing engine behavior.

## Values look incomplete or JSON serialization fails

Use `getProperty()` to inspect types, children and truncation flags. Increase
read depth deliberately, or use page/value reads for targeted data. A
`PartialValue` preserves incomplete containers and binary keys; it is not an
application string. Container contents in snapshots are structured `children`,
not a plain object in `value`.

Use `toJSONSafe()` before serializing Buffers, BigInts or uninitialized/nonfinite
values. Pass a BigInt when assigning large integers; an already-rounded JS
number cannot recover the original integer. See [value handling](values-and-paths.md#php-values).

## Cleanup also fails

A capture's setup/action failure stays primary. Inspect its `cleanupError` when
present, or AggregateError members from multi-resource shutdown. A detach failure
is recorded in the release result's `releaseError`, with the socket still closed.
Closing debugging does not undo application or database changes; tests must
clean up their own persisted data.

Do not call an owner's `dispose()` or capture's `close()` from inside the capture
action callback. Finish or reject the callback, then clean up from its caller.
Keep the Node process and browser alive while debugging; cross-script retention
is outside this package's scope.

## DDEV tests cannot launch Chromium

After DDEV recreates its container, the cached browser executable can remain
while operating-system libraries disappear. From the repository root, rerun
`ddev test-setup` to install browser dependencies and prepare runtimes. For only
browser tooling:

```sh
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npx playwright install --with-deps chromium
```

Use the same `PLAYWRIGHT_BROWSERS_PATH` when running browser suites. Missing
historical PHP/Xdebug runtimes require the full setup command. Run these commands
in the repository's parent DDEV project, not the separate Drupal fixture.
