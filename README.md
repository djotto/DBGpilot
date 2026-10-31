# playwright-xdebug

JavaScript controls for PHP/Xdebug, with a Playwright Test fixture.
The fixture and standalone Node API share one debugger implementation.

From this repository:

```sh
npm ci
npm test
```

Install from GitHub in the target project alongside Playwright Test:

```sh
npm install --save-dev playwright-xdebug@github:djotto/DBGpilot#main @playwright/test
```

The lockfile records the installed commit. Pin a reviewed commit SHA instead of
`main` when you need an explicit version. No JS release tag or npm registry
release has been published yet. No Python or pytest is required.

The retired Python source is preserved on [archive/python](https://github.com/djotto/DBGpilot/tree/archive/python).
Its two testing releases have been unpublished; their Git tags remain historical.
See [development](docs/development.md) and [releasing](docs/releasing.md).

`npm run check:package` produces a validated, unpublished tarball at
`dist/js-candidate/playwright-xdebug-0.1.0.tgz`. Install that artifact in an
existing project with:

```sh
npm install /absolute/path/playwright-xdebug-0.1.0.tgz @playwright/test
```

TypeScript declarations and native ESM imports are included:

```js
import {test, expect} from 'playwright-xdebug';
import {Listener, PathMapper} from 'playwright-xdebug/core';
```

Run `npm run test:types` to check the public declarations against CommonJS and
ESM consumers. The package validator also checks them after a clean tarball
installation outside this repository.

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
Each paused request occupies a PHP worker; concurrent captures need enough
independent PHP processes to reach their breakpoints.

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

For one action, `goto()` / `capture()` install a unique per-request trigger,
configure breakpoints, and return a snapshot while PHP remains paused:

```js
const paused = await xdebug.goto(page, 'http://localhost/checkout?code=SAVE10', {
  breakpoints: [{file: '/var/www/html/src/Checkout.php', line: 42}],
  variables: ['$discount'],
});
expect(paused.snapshot.variables.$discount.value).toBe(10);
await paused.session.setVariable('$discount', 15);
await paused.session.detach();
await paused.finished();
await paused.close();
```

For POST or AJAX, use `xdebug.capture(page, () => action(), options)` with
`urlPattern` (a Playwright route glob/RegExp/URL predicate) and optional `method`.
The action can finish before PHP responds; capture still waits for the breakpoint.
Each page can have one capture setup in progress; different pages can capture
concurrently. The capture deadline ends when the paused handle returns.
`finished({timeout, signal})` waits for the action without resuming PHP.
`close()` releases its PHP session and routing, and is shared by repeated calls.
The fixture also closes all captures at teardown.

After selecting the first request, the route passes subsequent requests through.
Physical route removal happens when the capture closes: disabling Chromium
interception during a paused navigation can wait for PHP's response. Failed setup
releases PHP before removing routing. Cleanup is bounded and retains the original
action/setup error if cleanup also fails. Secondary failures are attached as
`error.cleanupError` when the original rejection can carry metadata; multiple
failures use an `AggregateError`. Primitive or frozen rejections are preserved.
Owner/listener shutdown attempts all cleanup and waits for the other captures
even when one fails, then reports collected failures. Expired routes pass requests
through; if installation completes after the capture deadline, that exact handler
is removed again without disturbing a retry. Helper waits can be aborted; an arbitrary user callback's
promise cannot be forcibly cancelled without taking ownership of its page.

Configure source roots through Playwright options when local and PHP paths differ:

```js
test.use({
  xdebugPathMappings: [{local: 'C:\\Site', remote: 'file:///var/www/html'}],
});
// session.setBreakpoint('C:\\Site\\src\\Checkout.php', 42)
```

Mappings are lexical, support Windows/UNC paths on Linux, and use the longest
matching directory root. Ambiguous mappings and unmapped outgoing local paths
fail explicitly. Explicit `file:` and `dbgp:` engine URIs bypass outbound mapping.
Results include `fileUri` (engine URI), `localFile`, and `pathMappingError`; `file`
remains a convenient server path for compatibility with the initial fixture.
`xdebugBaseDir` supplies the base for relative local paths, otherwise the process
working directory is used. Standalone callers can construct a `PathMapper` and
pass it as `pathMappings`. JS options replace Python TOML discovery.

| Method | Behaviour |
| --- | --- |
| `xdebug.waitForSession({url, method, timeout, signal})` | Claim a matching request. AbortSignal cancellation removes the waiter. |
| `session.setBreakpoint(file, line, {condition, temporary, hitValue, hitCondition, state})` | Returns an opaque breakpoint ID; use a PHP-server path or file URI. |
| `session.setExceptionBreakpoint(className = '*')` | Break on an exception. |
| `session.removeBreakpoint(id)` | Remove a breakpoint. |
| `session.getBreakpoint(id)`, `breakpoints()`, `updateBreakpoint(id, options)` | Mapped engine records, hit/state/line updates and a copied `knownBreakpoints` inventory. |
| `session.runUntilBreak({timeout})` | Return while PHP is paused; release and throw if execution finishes first. |
| `session.run()`, `stepInto()`, `stepOver()`, `stepOut()` | Wait for the next execution result. Options accept a timeout in milliseconds. |
| `session.waitForPause({timeout, signal})` | Recover the eventual pause after an earlier execution wait timed out, within this test. |
| `session.stack()` | Frames with level, function location, server file and line. |
| `session.stack({frame})`, `stackDepth()`, `contexts({frame})` | Selected frames, nested input locations and context discovery. |
| `session.status()`, `featureGet(name)`, `featureSet(name, value)`, `refreshCapabilities(names)`, `typeMap()` | Validated metadata, capability cache and engine type mappings. |
| `session.locals({frame, context})` | Convenient local/context values. |
| `session.getVariable(name, {frame, depth, context})` | Convenient values; follows direct-child pages and optionally descends. |
| `session.getProperty(name, options)` | Structured values, raw bytes, fullnames, metadata and truncation flags. |
| `session.getPropertyPage(name, {frame, context, page, maxData, key, address})` | One explicitly selected page, with complete targeting metadata. |
| `session.propertyValue(name, options)`, `propertyValueInfo(name, options)` | Full raw bytes and byte-size/truncation/target metadata. |
| `session.evaluate(php, {timeout})` | Evaluate PHP in the current frame. May have side effects. |
| `session.setVariable(name, value, {frame, context})` | Assign an existing variable/property. Scalars, Buffers, arrays and plain objects are supported. |
| `session.setProperty(name, expression, {frame, context, type, address})` | Explicit PHP expression/Buffer assignment, preserving payload byte length. |
| `session.source(file, {begin, end})`, `setOutput(stream, mode)` | Mapped/virtual/current source bytes and stdout/stderr off/copy/redirect modes. |
| `session.snapshot({variables, expressions, frame, depth, context})` | Independent JSON-safe copy of execution, stack and requested properties. Expressions may have side effects. |
| `session.detach()` / `session.stop()` | Let PHP finish / explicitly terminate a paused request. |
| `session.command(name, args, data, timeout)` | Raw DBGp command. Known execution commands use the same execution guards. |
| `session.nextEvent({timeout, signal})` | Retained in-process stream/notification/stop/closed events; cancellation does not consume a later event. |

All timeouts are milliseconds. A timeout abandons the caller's wait, not PHP
execution. The session stays busy until the actual reply; `waitForPause()` can
recover a late breakpoint. Inspection/mutation/evaluation fail immediately while
another operation owns the session. `detach()` explicitly releases it instead.
Streams and notifications are exposed as in-process `stream` and `notification`
events and through `nextEvent()`. The queue defaults to 1024 events; overflow
closes the debugger connection with an explicit protocol error. On-time evaluations
do not generate duplicate stops. Continuations and evaluations accept an
AbortSignal; aborting their wait preserves execution ownership until the real
reply. There is no daemon, cross-process reconnection or event replay service.

Before offering a PHP request, the fixture queries engine capabilities and
negotiates its settings. Unsupported optional settings retain the engine's defaults;
unexpected engine errors and malformed responses still fail setup. Session encoding
must remain UTF-8, with the existing lossless handling of Xdebug's Latin-1-labelled
application bytes. Command data must remain base64. Attempts to change those
assumptions through either `featureSet()` or `command('feature_set', ...)` fail
before reaching PHP. An engine advertising another encoding must accept the
required setting before request metadata is evaluated.

`session.supportsCommand('eval')` reports cached, advertised command support;
unknown commands return false. `session.supportsAsync` reports the cached async
capability, without adding an interrupt API. Fixture-created sessions have their
capabilities loaded during setup. Session operations reject commands advertised
as unavailable without resuming or closing PHP. `refreshCapabilities()` refreshes
the defaults, or accepts a list of feature/command names. Unsupported queries
reported with DBGp error 3 or 4 are retained as unavailable. Late feature replies
still update the cache after their original wait times out. `capabilities` returns
an independent copy of the cache. Cleanup always closes the connection, including
when the engine cannot detach.

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
ddev exec npm run test:compatibility
ddev exec npm run test:integration
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:stress
ddev exec npm run check:package
```

The PHP suite starts a temporary PHP server; the Drupal suite uses the pinned
fixture provisioned with `ddev drupal-setup`, including real render-only mutation,
saved Form API changes and author-autocomplete AJAX/database queries. The runtime
matrix and live integration suite require the cached historical Xdebug modules.
The integration suite checks stepping,
exact hit counts, binary stdout routing and evaluation-error recovery across the
same six runtimes. Its report is `test-results/integration-js.json`. The stress suite
uses three independent PHP servers for parallel browser requests and includes a
35-second pause.
Drupal caches may bypass application breakpoints; choose an executable line
that the selected request reaches. Browser action deadlines and Playwright's
whole-test deadline are separate from debugger deadlines and should allow the
intended pause. Keep the browser and event loop alive until PHP is released.

The standalone example takes `DBGPILOT_SCRIPT_URL`, `DBGPILOT_SCRIPT_FILE`, and
`DBGPILOT_SCRIPT_LINE`, with optional `DBGPILOT_SCRIPT_HOST`,
`DBGPILOT_SCRIPT_PORT` and `DBGPILOT_SCRIPT_IDEKEY`. These names are specific to
this example; `DEBUG_FILE` is reserved by Playwright for debug logging.
