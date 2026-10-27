# Playwright breakpoint helper

`PlaywrightDebugger` coordinates an async Playwright page with a DBGpilot server.
It uses the existing `Client` and does not import Playwright at runtime. The
development environment installs Playwright and Chromium for real acceptance
tests; your application may supply its own async Playwright page.

For reusable connection setup, explicitly owned CLI processes, configuration,
optional pytest fixtures, and installed-package examples, see
[Python setup](python-setup.md). `DebuggerSetup` does not own your page or browser;
its context exit closes its client while preserving the server. A debugger
context still releases its captures on exit.

```sh
ddev test-setup
# Keep this running in another terminal:
ddev poetry run dbgpilot serve
# Actual Chromium -> PHP-FPM -> Xdebug -> server -> reconnect -> page check:
ddev poetry run python scripts/check_playwright_harness.py
```

## Navigate and return a paused snapshot

```python
from dbgpilot import BreakpointSpec, Client, PlaywrightDebugger

async with Client() as first, PlaywrightDebugger(page, first) as debugger:
    paused = await debugger.goto(
        "http://127.0.0.1/?code=SAVE10",
        breakpoints=[BreakpointSpec("/var/www/html/src/checkout.php", 11)],
        variables=["$subtotal", "$discount"],
        expressions=["$subtotal - $discount"],
        timeout=30,
    )
    assert paused.snapshot["variables"]["$discount"]["value"] == 10
    assert not paused.action.done()
    print(paused.session_id, paused.snapshot)

    await first.aclose()
    async with Client() as later:
        session = paused.session(later)
        assert await session.set_value("$discount", 15)
        await session.step_over()
        assert (await session.property_get("$total"))["value"] == 85
        await session.detach()

    await paused.finished()
    assert await page.get_by_test_id("total").inner_text() == "£85"
```

`goto()` takes an absolute HTTP(S) URL. `BreakpointSpec(file, line, options={})`
forwards options such as `condition`, `kind`, `function`, `exception`,
`temporary`, and hit settings to the controller. Multiple specifications are
installed before running PHP.

The capture deadline (`timeout`, seconds, greater than zero and at most 300)
covers attachment, breakpoint installation, and snapshot capture. It ends once
the paused handle returns. Navigation has a separate `navigation_timeout` in
seconds, default zero (disabled), so a long PHP pause does not expire the browser
action. `paused.finished(timeout=30)` waits for that action after you explicitly
advance/detach PHP; it does not advance PHP itself and does not cancel the action
if that wait times out.

Route installation/removal are included in the capture deadline too. Removal
during failure cleanup has a separate four-second bound. A route-cleanup error
is attached as a note to an existing action/setup error, preserving that original
failure.

Each `goto()` uses a distinct trigger URL for the actual browser navigation,
so retries after failed setup are not tied to a previous navigation. After a
successful load it removes its generated trigger parameters with
`history.replaceState`, without sending another HTTP request. Redirect paths and
other query parameters are retained.

## Clicks, forms, and AJAX

```python
paused = await debugger.capture(
    lambda: page.get_by_role("button", name="Apply").click(timeout=0),
    url_pattern="http://127.0.0.1/**",
    breakpoints=[BreakpointSpec("/var/www/html/src/checkout.php", 11)],
    variables=["$discount"],
)
```

`capture(action, url_pattern=..., ...)` accepts a no-argument async action and a
Playwright page route pattern/predicate. The first matching request receives
debug parameters; the route is then removed. Select the PHP request you intend
to debug, rather than a broad pattern that could match an unrelated request.
This works for page navigation and for POST or XHR/fetch requests; method/body
are preserved when the route's URL is updated. Successful click completion does
not imply PHP completion: a button may have only dispatched an AJAX request.
Action errors fail quickly and cancel the attachment wait.

For a click that waits for navigation, pass `timeout=0` to the Playwright action
if the PHP pause can outlast its normal timeout. DBGpilot owns the debugger, not
Playwright's general action timeout settings. Routing is page-scoped; use
separate pages for concurrent captures. Requests served by service workers may
bypass Playwright page routing; create the browser context with
`service_workers="block"` if your application uses them.

## Correlation and cleanup

Each capture generates a unique IDE key and sends the same value in
`XDEBUG_SESSION` and `XDEBUG_TRIGGER`, replacing existing versions of those query
parameters. Other query parameters are retained. Xdebug can use the trigger
value as the IDE key, so these values must agree. This isolates simultaneous
requests/pages without relying on shared browser cookies. The included harness
accepts arbitrary trigger values.

If the application restricts `xdebug.trigger_value`, either allow the generated
values in your test setup or pass an allowed `idekey` to the helper constructor.
An explicit key must match your Xdebug configuration; reused explicit keys do
not distinguish concurrent captures. The helper does not alter PHP/Xdebug ini
settings or automatically map local/server file paths.

The returned `PausedBrowser` contains `session_id`, a copied JSON snapshot, and
the `action` task. `session(client=None)` reconnects with the chosen client.
`events(client=None, timeout=30)` polls and updates its stored event cursor.
`close()` explicitly releases debugging and settles/cancels the browser action.
Concurrent calls to that handle's `close()` share one cleanup task. Cancelling
a caller waiting for close leaves cleanup running and tracked by the helper
until it finishes; later handle/helper close calls await the same task.

Use the helper as an async context manager to release its captures on exit.
Closing also cancels captures still installing routes, waiting for PHP, or
configuring a breakpoint, and releases any attached session. Concurrent close
calls await the same cleanup; cancelling a close waiter does not abandon the
owned cleanup task. Call `aclose()` from the task managing the helper, outside
the browser action passed to `capture()`; closing from that action is rejected
to prevent a task cycle. A capture's `close()` must also be called outside its
own browser action.
Closing a `Client` alone leaves PHP paused. To retain a paused capture beyond a
helper scope, keep the helper alive and close it explicitly after the
investigation. Keep the owning browser and event loop alive too: neither a
session ID nor the server preserves a browser process that has exited.

On failed setup, action errors, or capture deadlines, the helper cancels its
pending RPCs, closes an attached debugging session, removes routing, and settles
the action. Cleanup uses a fresh client, so it still works after the original
client closes. A server/network failure can prevent remote cleanup; server-side
metadata and explicit session close remain the recovery mechanisms.

## Local source paths

Configure [path mappings](path-mapping.md) on the server to pass local files in
`BreakpointSpec`, including Windows paths when the server runs in Linux/DDEV.
Snapshots keep the engine `file` URI and add `local_file` and
`path_mapping_error` on execution/frame records. An unmapped local breakpoint
fails explicitly; helper cleanup releases the captured session as with other
setup failures. Map the path namespace used by the script, even when those local
files do not exist inside the server container.

## Acceptance coverage

The real Chromium tests cover navigation, form submission, successful early
AJAX clicks, variable mutation followed by page assertions, first-client closure,
reconnection, action/setup failures, and route cleanup. Stress tests also hold a
navigation for 35 seconds, pause four browser requests independently, and restart
the server while a request is paused. A mapping test uses Windows source paths
through a Linux server, reconnects, mutates PHP, and asserts the resulting DOM.
See [compatibility and stress coverage](compatibility.md).
