# playwright-xdebug

JavaScript controls for PHP/Xdebug, with a Playwright Test fixture. This is the
replacement being developed on `migration/playwright`; see
[the migration plan](../MIGRATION.md) for completed work and remaining coverage.
The fixture and the same-process standalone API share one debugger implementation.

From this repository:

```sh
npm ci
npm test
```

The root npm workspace supplies `require('playwright-xdebug')`. In another local
project, install this folder as a file dependency alongside `@playwright/test`.
No Python or pytest is required by the JavaScript implementation.

```js
const {test, expect} = require('playwright-xdebug');

test('discount applied', async ({page, xdebug}) => {
  const waiting = xdebug.waitForSession({url: '/checkout', method: 'POST'});
  const submission = page.getByRole('button', {name: 'Apply'}).click({timeout: 0});
  submission.catch(() => {}); // Handle rejection while debugger waits are pending.
  const session = await waiting;
  await session.setBreakpoint('/var/www/html/src/Checkout.php', 42);
  await session.runUntilBreak();
  expect(await session.evaluate('$discount')).toBe(10);
  await session.setVariable('$discount', 15);
  await session.detach();
  await submission;
  await expect(page.getByTestId('total')).toHaveText('85');
});
```

Configure `baseURL` in Playwright's `use` settings. PHP must connect **to the
machine/container running the fixture**, on the fixture's listener address/port:

```ini
xdebug.mode=debug
xdebug.start_with_request=trigger
xdebug.client_host=127.0.0.1
xdebug.client_port=9003
```

Use the address reachable from PHP when running across containers. Restart the
actual serving PHP runtime after changing its configuration. `xdebugHost` is
where the fixture binds; it can differ from PHP's destination hostname. Use
`0.0.0.0` when accepting connections from another container, on an appropriate
trusted development network.

Run debugger specs with one worker. Every worker would otherwise try to bind
the same Xdebug port; an IDE listener can also conflict. Separate PHP runtimes
and ports are needed for independently configured concurrent debug workers.
The listener can hold multiple PHP sessions within one test.

The fixture sets a unique `XDEBUG_TRIGGER` cookie for the baseURL hostname.
`xdebug.enableFor(url)` enables another hostname. An explicit `xdebugIdeKey`
option supports an allowed trigger value configured by the application;
otherwise PHP must accept the generated random trigger values. `xdebugPort`
(default 9003), `xdebugHost` (127.0.0.1) and `xdebugUnclaimedTimeout` (2000 ms)
are configurable fixture options.

Matching PHP requests throughout that browser context connect and pause,
including AJAX and redirects. Unclaimed requests are released after the
unclaimed timeout. Call `waitForSession()` before the action when possible.
A string `url` matches the path, ignoring the query; a RegExp matches path and
query, and `method` optionally filters GET/POST/etc. Unknown IDE keys detach.
Setup/preparation errors reach the waiting test. Test teardown releases every
tracked session, including requests still preparing, after success or failure.

| Method | Behaviour |
| --- | --- |
| `xdebug.waitForSession({url, method, timeout, signal})` | Claim a matching request. AbortSignal cancellation removes the waiter. |
| `session.setBreakpoint(file, line, {condition, temporary, hitValue, hitCondition, state})` | Returns an opaque breakpoint ID; use a PHP-server path or file URI. |
| `session.setExceptionBreakpoint(className = '*')` | Break on an exception. |
| `session.removeBreakpoint(id)` | Remove a breakpoint. |
| `session.runUntilBreak({timeout})` | Return while PHP is paused; release and throw if execution finishes first. |
| `session.run()`, `stepInto()`, `stepOver()`, `stepOut()` | Wait for the next execution result. Options accept a timeout in milliseconds. |
| `session.waitForPause({timeout, signal})` | Recover the eventual pause after an earlier execution wait timed out, within this test. |
| `session.stack()` | Frames with level, function location, server file and line. |
| `session.locals({frame, context})` | Convenient local/context values. |
| `session.getVariable(name, {frame, depth, context})` | Convenient values; follows direct-child pages and optionally descends. |
| `session.getProperty(name, options)` | Structured values, raw bytes, fullnames, metadata and truncation flags. |
| `session.evaluate(php, {timeout})` | Evaluate PHP in the current frame. May have side effects. |
| `session.setVariable(name, value, {frame, context})` | Assign an existing variable/property. Scalars, Buffers, arrays and plain objects are supported. |
| `session.snapshot({variables, expressions, frame, depth, context})` | Independent JSON-safe copy of execution, stack and requested properties. Expressions may have side effects. |
| `session.detach()` / `session.stop()` | Let PHP finish / explicitly terminate a paused request. |
| `session.command(name, args, data, timeout)` | Raw DBGp command. Known execution commands use the same execution guards. |

All timeouts are milliseconds. A timeout abandons the caller's wait, not PHP
execution. The session stays busy until the actual reply; `waitForPause()` can
recover a late breakpoint. Inspection/mutation/evaluation fail immediately while
another operation owns the session. `detach()` explicitly releases it instead.
Streams and notifications are exposed as in-process `stream` and `notification`
events. There is no daemon, cross-process reconnection or event replay service.

UTF-8 PHP strings become JS strings; invalid UTF-8 becomes a lossless `Buffer`.
Safe integers become numbers; larger PHP integers become `BigInt`. `INF`, `-INF`
and `NAN` retain their numeric meaning. `toJSONSafe(value)` (also used by snapshots)
encodes bytes, BigInt, nonfinite and uninitialized values explicitly for JSON.
Nonfinite or already-unsafe JS numbers are rejected on assignment; use a BigInt
or an explicit PHP expression instead.

List arrays become JS arrays, associative arrays become objects, and PHP objects
include a convenient `__class` field. Use `getProperty` for unambiguous metadata.
Incomplete containers return `PartialValue` instances with fetched children and
the total count, rather than placeholder strings. Binary array keys also use
that entry-based representation. Default depth is one; recursive reads are
sequential, with a depth limit of 16 and at most 1024 pages per property.
Packets default to a 16 MiB maximum. These are bounds, not a promise that reading
a large object graph is inexpensive.

The independent core is available without importing Playwright Test:

```js
const {Listener, Xdebug, toJSONSafe} = require('playwright-xdebug/core');
```

A standalone script owns its listener, browser context, debugger owner and
cleanup explicitly. See [the standalone example](examples/standalone.js).
Closing that script ends its debugging sessions. Cross-script retention is
outside this package's target scope.

The maintained PHP/browser and Drupal smoke suites have runnable configurations:

```sh
ddev exec npm ci
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:browser
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:drupal
```

The PHP suite starts a temporary PHP server; the Drupal suite uses the pinned
fixture provisioned with `ddev drupal-setup`. See the migration plan for the
remaining PHP/Xdebug version matrix and Drupal persistence/AJAX migration.
Drupal caches may bypass application breakpoints; choose an executable line
that the selected request reaches. Browser action deadlines and Playwright's
whole-test deadline are separate from debugger deadlines and should allow the
intended pause. Keep the browser and event loop alive until PHP is released.
