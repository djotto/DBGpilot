# Workflows

[Documentation index](../README.md#documentation) · [Setup](getting-started.md) · [API](api.md)

The examples below use the checkout from [getting started](getting-started.md#first-test-in-this-repository).
In snippets, `page`, `xdebug` and `baseURL` are Playwright fixtures, and
`breakpoints` is `[{file, line}]` at the checkout's `BREAKPOINT:` marker. Unless a
complete file is shown, place snippets inside a test imported from `dbgpilot`.

## One request's lifetime

1. Node starts its listener and registers a debugger owner.
2. The browser sends a triggered HTTP request; PHP connects to Node and waits.
3. DBGpilot prepares the session, sets the requested breakpoints, and runs PHP.
4. `goto()` or `capture()` returns a handle when PHP reaches a breakpoint.
5. Your code inspects, changes or steps PHP while the request stays open.
6. `detach()` lets PHP finish; then the browser can receive its response.
7. Close the capture, or let fixture teardown close it.

A returned snapshot is a copy. A session is a live connection. Keeping a snapshot
is safe after cleanup; a session ID is only a label within that process.

## Navigation

`goto()` takes an absolute HTTP(S) URL. It starts `page.goto()` and captures the
matching request, ignoring a fragment in matching. Its default navigation timeout
is zero; the capture deadline still applies while preparing and reaching the stop.

```js
const paused = await xdebug.goto(page, `${baseURL}/checkout.php?code=SAVE10`, {
  breakpoints,
  variables: ['$discount'],
});
try {
  await paused.session.setVariable('$discount', 15);
  await paused.session.stepOver();
  expect(await paused.session.evaluate('$total')).toBe(85);
  await paused.session.detach();
  const response = await paused.finished();
  expect(response.status()).toBe(200);
  await expect(page.getByTestId('total')).toHaveText('85');
} finally {
  await paused.close();
}
```

If PHP finishes without hitting a breakpoint, capture rejects and releases its
resources. An empty breakpoint list does not cause an automatic stop at entry.
Set a breakpoint in a reachable line, function or exception.

## Form submissions

Install the capture before invoking the action. Routing preserves the request
method and POST body, and adds trigger parameters to the selected URL.

```js
await page.goto('/checkout.php');
await page.getByRole('textbox').fill('SAVE10');
const paused = await xdebug.capture(
  page,
  () => page.getByRole('button', {name: 'Apply', exact: true}).click({timeout: 0}),
  {
    urlPattern: '**/checkout.php',
    method: 'POST',
    breakpoints,
    expressions: ["$_POST['code']"],
  },
);
try {
  expect(paused.snapshot.expressions["$_POST['code']"].value).toBe('SAVE10');
  await paused.session.setVariable('$discount', 20);
  await paused.session.detach();
  await paused.finished();
  await expect(page.getByTestId('total')).toHaveText('80');
} finally {
  await paused.close();
}
```

`urlPattern` uses Playwright routing: a glob, RegExp, or predicate receiving a
URL. A method filter is optional. The first matching request is selected; later
requests pass through that handler. Keep patterns narrow when actions cause
several requests. Redirects and later PHP requests are separate sessions.

## AJAX

A click that dispatches AJAX can resolve before the PHP request completes.
Capture still waits for its breakpoint. `finished()` waits for the supplied
**action**, so for AJAX it is not a network-completion guarantee.

```js
await page.goto('/checkout.php');
const paused = await xdebug.capture(
  page,
  () => page.getByRole('button', {name: 'AJAX', exact: true}).click(),
  {urlPattern: '**/checkout.php?json=1*', breakpoints},
);
try {
  await paused.finished(); // The click dispatched; PHP is still paused.
  expect(paused.session.state).toBe('break');
  await paused.session.setVariable('$discount', 25);
  await paused.session.detach();
  await expect(page.getByTestId('total')).toHaveText('75');
} finally {
  await paused.close();
}
```

Assert the final DOM or wait for a specific Playwright response after releasing
PHP when the outcome requires network completion.

## Manual attachment

Use `waitForSession()` when you want to select and control requests yourself.
The fixture enables a trigger cookie on the `baseURL` hostname; `enableFor(url)`
enables an additional hostname. Other triggered PHP requests can also connect.

```js
const waiting = xdebug.waitForSession({url: '/checkout.php', method: 'GET'});
const action = page.goto('/checkout.php?code=SAVE10', {timeout: 0});
action.catch(() => {}); // Handle rejection while PHP is paused.
try {
  const session = await waiting;
  await session.setBreakpoint(file, line, {condition: '$discount === 10'});
  await session.runUntilBreak();
  expect(await session.evaluate('$discount')).toBe(10);
  await session.detach();
  expect((await action).status()).toBe(200);
} finally {
  await xdebug.dispose();
  await action.catch(() => {});
}
```

A string `url` matches the request path without its query. A RegExp matches the
recorded URI including its query. Neither selector distinguishes origins: the
metadata contains method and URI, not a host. Match `method` when GET and POST
share a path. Unclaimed sessions detach after `xdebugUnclaimedTimeout` (2 s by
default), so create waiters before actions whenever possible.

`dispose()` ends this owner; subsequent operations require a new owner or test.
The Playwright fixture also disposes it at teardown, including failed tests.

## Stepping, exceptions and capabilities

Use `stepInto()`, `stepOver()` and `stepOut()` to obtain the next execution
result, then inspect the new frame. `stack()` shows frame levels; zero is the
current frame. Property and context reads can select another frame, while
Xdebug evaluation is limited to the current frame.

For exception debugging, set the exception breakpoint before resuming:

```js
await session.setExceptionBreakpoint('RuntimeException');
const stopped = await session.runUntilBreak();
console.log(stopped.exception, stopped.message, await session.stack());
```

Commands go to Xdebug when called. Unsupported commands throw `XdebugError` with
the command, numeric code and engine message. Query the inventory explicitly if
useful for an investigation:

```js
const inventory = await session.getCapabilities();
console.log(inventory.eval, inventory.breakpoint_types);
```

Every call queries all known features and commands afresh. It does not cache
results or change whether later commands are attempted. `supported` means that
the engine recognizes the name; `enabled` means its returned value is `1`. Read
`value` for names such as `breakpoint_types` or `max_children`.

## Timeouts and cancellation

There are separate clocks for the test runner, browser actions, capture setup,
DBGp commands and waiting for a browser action to finish. Extending one does not
extend the others. [Playwright's timeout guide](https://playwright.dev/docs/test-timeouts)
explains runner and browser settings.

| Operation | Default / behavior |
| --- | --- |
| Whole Playwright test | Configure with `timeout` or `test.setTimeout()`; Playwright defaults to 30 s. |
| `capture()` / `goto()` setup | 30 s, configurable up to 300 s; ends when the paused handle returns. |
| `goto()` browser navigation | Zero by default; override `navigationTimeout`. |
| Session continuation | 30 s; zero disables its waiting deadline. |
| Session `evaluate()` | 10 s; accepts timeout and signal. |
| `paused.finished()` | 30 s per call; accepts timeout and signal. |
| Most inspection commands | 10 s transport wait; use raw commands for an explicit command timeout. |

For a longer investigation, increase the test timeout before the pause and
allow enough time for `finished()` after resuming. Passing a signal cancels a
wait; it does not rewind PHP or forcibly cancel an arbitrary browser callback.
Capture setup rejects a timeout of zero. Other documented wait options accept
zero to wait without their own timer.

A continuation timeout does **not** prove PHP stopped. DBGpilot retains ownership
until the actual reply. Recover a late pause in the same test:

```js
try {
  await session.runUntilBreak({timeout: 100});
} catch (error) {
  if (!(error instanceof CommandTimeout)) throw error;
  await session.waitForPause({timeout: 10_000});
}
console.log(await session.stack());
```

Import `CommandTimeout` from `dbgpilot` or `dbgpilot/core`. Inspection rejects
while execution or another session operation is pending. If recovery is not
needed, close the capture or dispose the owner to release the request.

## Cleanup and concurrency

`detach()` lets PHP finish. `stop()` terminates the request before its remaining
code runs. Both end debugging; `stop()` is unsuitable for tests expecting the
normal completed HTTP response. Closing a capture releases its session and
removes its routing; it does not close the caller's page.

`finished()` does not resume PHP. For a navigation, calling it before detach or
another continuation completes the request can deadlock until a timeout.
`close()`, `dispose()` and listener shutdown share their ongoing cleanup work
across repeated calls. A failed detach is recorded as `releaseError` in the
returned result while the socket is closed. Other cleanup failures can reject;
setup/action errors retain the original failure, with `cleanupError` attached
where possible. Do not dispose an owner or close its capture from inside its
own capture action callback.

### Concurrency

One capture setup can be in progress per page; a returned paused handle no
longer occupies that setup slot. Different pages can prepare captures in
parallel. Sessions are independent, but operations **within one session** must
be sequential. A paused request occupies one PHP worker. Parallel captures need
several PHP workers or independent PHP servers, as in the stress suite. A single
PHP CLI server cannot serve another paused request while its first is stopped.

## Standalone Node scripts

Import `dbgpilot/core` to use the debugger without `test.step` or the Playwright
Test runner. The [complete example](../examples/standalone.js) creates a listener,
launches Chromium, registers an owner, captures a breakpoint and cleans up on
completion or interruption.

With the repository's DDEV demo started and test tooling installed, run from
the repository root. PHP-FPM already connects to port 9003 in that container:

```sh
ddev exec env \
  PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright \
  DBGPILOT_SCRIPT_URL=http://127.0.0.1/checkout.php?code=SAVE10 \
  DBGPILOT_SCRIPT_FILE=/var/www/html/tests/fixtures/checkout.php \
  DBGPILOT_SCRIPT_LINE=14 \
  node examples/standalone.js
```

For another application, run Node where PHP can reach its listener and change
the URL, PHP source path and executable line. Environment options:

| Name | Meaning / default |
| --- | --- |
| `DBGPILOT_SCRIPT_URL` | Required absolute HTTP(S) URL. |
| `DBGPILOT_SCRIPT_FILE` | Required source path as seen by PHP, or explicit engine URI. |
| `DBGPILOT_SCRIPT_LINE` | Required positive line number. |
| `DBGPILOT_SCRIPT_HOST` | Listener bind interface; default `127.0.0.1`. |
| `DBGPILOT_SCRIPT_PORT` | Listener port; default `9003`. |
| `DBGPILOT_SCRIPT_IDEKEY` | Parent owner's IDE key; generated UUID by default. |

The included example's captures use generated per-request keys. A restricted
trigger setup needs the explicit capture `ideKey` described in
[getting started](getting-started.md#restricted-trigger-values); the parent key
environment variable alone does not configure that child key. `DEBUG_FILE` is
reserved by Playwright for logging; do not use it as a source-file variable.

For your own script, construct `Listener`, call `listen()`, then register an
`Xdebug` owner with a browser context. Use `try/finally` to close the listener
and browser. For CLI PHP without a browser, register
`new Xdebug(undefined, ideKey)`, set PHP's IDE key to the same value, and attach
with `waitForSession()`. `enableFor()` and capture helpers require a browser
context/page. Listener shutdown disposes every registered owner.

The example's environment variables are a convenience of that script, not
package-wide configuration. Keep the process, browser and event loop alive while
debugging. Exiting ends its sessions; there is no reconnect from another script.
