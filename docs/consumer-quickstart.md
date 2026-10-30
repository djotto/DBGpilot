# Add DBGpilot to a pytest / Playwright project

Use Python **3.12 or 3.13** and an **async Playwright page**. Install a supplied
DBGpilot wheel; a public package index is not required. Your PHP application
needs Xdebug. DBGpilot, PHP, and the browser can run on different machines or
in different containers if their connections are configured accordingly.

## Find an artifact

Published testing builds are shared through
[GitHub Releases](https://github.com/djotto/DBGpilot/releases). Open a release's
**Assets** list and download the wheel, source archive and `SHA256SUMS`, or use
the exact pip install command in its release notes. The source archive contains
this guide and the starter files. A download is available only after that
release is published; no release is created by committing source alone.

## Install in your test environment

Activate your project's existing virtual environment, then install the downloaded
wheel. Retain compatible test dependencies already supplied by your project:

```sh
python -m pip install /absolute/path/dbgpilot-0.1.1-py3-none-any.whl
python -m pip install 'pytest>=8.3,<10' 'pytest-asyncio>=1,<2' 'playwright>=1.64,<2'
python -m playwright install chromium
dbgpilot --version
```

Linux browsers may need additional system libraries; see Playwright's
[browser installation instructions](https://playwright.dev/python/docs/browsers#install-system-dependencies).
DBGpilot's core has no runtime dependencies; pytest and Playwright are optional
tools. Poetry, DDEV and this repository's PHP/Drupal fixtures are not needed.

## Connect PHP to a daemon

For PHP and DBGpilot running on the same machine, enable these settings in the
PHP runtime that serves your application:

```ini
xdebug.mode=debug
xdebug.start_with_request=trigger
xdebug.client_host=127.0.0.1
xdebug.client_port=9003
```

Restart that PHP runtime after changing its configuration. The helper adds the
request trigger automatically; its generated trigger values must be permitted
by your Xdebug configuration. If `xdebug.trigger_value` is restricted, see
[trigger configuration](playwright.md).

In a separate terminal, using an environment with DBGpilot installed, start:

```sh
dbgpilot serve --no-config
```

Leave it running. The test connects to the HTTP API on **9004**; PHP/Xdebug
connects back to the debugger listener on **9003**. Check the API with:

```sh
dbgpilot call health --no-config
```

For containers, set `xdebug.client_host` to the address reachable **from PHP**.
If PHP connects from another container, bind the debugger listener with
`--xdebug-host 0.0.0.0`. Reach the HTTP API independently through a suitable
address; non-loopback API binding requires authentication. See
[installation/networking](installation.md#debug-an-existing-application) and
[server configuration](server.md). The local example above needs no token.

Set breakpoints using engine paths, such as `file:///var/www/html/src/order.php`.
To use your local source paths when they differ from PHP's paths, configure the
**daemon** at startup, for example:

```sh
dbgpilot serve --no-config --path-map /home/me/app /var/www/html
```

Choose either startup command before starting the daemon. Changing client
settings does not reconfigure a running daemon's mappings. See
[path mapping](path-mapping.md) for multiple roots and Windows paths.

## Copy the minimal pytest starter

The source archive supplied alongside the wheel contains
[`examples/consumer/`](../examples/consumer/). Unpack it to obtain the example:

```sh
tar -xzf /absolute/path/dbgpilot-0.1.1.tar.gz
cp -R dbgpilot-0.1.1/examples/consumer ./dbgpilot-smoke
```

Run this from your consuming project's directory. The test imports the installed
wheel; it needs no imports from the DBGpilot checkout. The starter contains:

- `conftest.py`: explicitly enables `dbgpilot.pytest_plugin`, reuses the daemon,
  and supplies a function-scoped async Chromium page named `dbgpilot_page`.
- `pytest.ini`: keeps async fixtures and tests on function-scoped event loops.
- `test_debug.py`: captures a breakpoint, closes its first client, reconnects to
  the paused session, detaches, and checks that the browser gets a successful
  HTTP response.

Point it at an application URL and an executable PHP line that request reaches:

```sh
export DBGPILOT_URL=http://127.0.0.1:9004
export DBGPILOT_TEST_URL=http://localhost:8080/orders
export DBGPILOT_TEST_FILE=file:///var/www/html/src/order.php
export DBGPILOT_TEST_LINE=42
python -m pytest -c dbgpilot-smoke/pytest.ini dbgpilot-smoke/test_debug.py -q
```

Replace the application URL, file and line with your own values. The selected
request must return a successful HTTP status after detach. If the API requires
a token, set `DBGPILOT_TOKEN` in your environment. The starter reads it without
writing it into source or command arguments.

To integrate into your existing suite, merge `pytest_plugins` and
`dbgpilot_options` into its root `conftest.py`. Append to any existing
`pytest_plugins` list. If you already own an async page fixture, replace the
starter's browser fixture with:

```python
@pytest.fixture
def dbgpilot_page(my_async_page):
    return my_async_page
```

Use your fixture's actual name and align its event loop with the test. The
standard synchronous Playwright `page` fixture cannot be passed to DBGpilot;
the starter uses a separate fixture name so existing synchronous tests can
keep their page fixture. Merge the pytest settings rather than replacing your
project's configuration.

Add your application assertions in `test_debug.py`. For values at the breakpoint,
pass `variables=["$your_variable"]` to `goto()` and inspect
`paused.snapshot["variables"]`. The
[larger example](../examples/pytest/test_checkout.py) demonstrates variable
inspection/mutation, stepping and final DOM assertions. See
[the helper guide](playwright.md) for form and AJAX captures.

## Pause ownership and cleanup

Returning a snapshot or closing a client leaves PHP paused. Keep the browser,
page and original event loop alive while you reconnect. Session IDs last only
for the daemon process; they do not survive restart.

The helper's 30-second capture deadline ends when the paused handle returns.
Browser navigation uses a separate deadline, disabled by default during capture.
`paused.finished(timeout=30)` waits for navigation after you resume/detach; it
does not resume PHP itself. Set browser action deadlines deliberately for form
or AJAX captures.

The pytest debugger fixture releases its captures on teardown, including after
an assertion fails. This starter reuses a separately started daemon, so teardown
leaves that daemon running. Stop your daemon manually when finished. If cleanup
cannot reach the API, reconnect and explicitly release the affected session;
see [ownership and recovery](python-setup.md#connection-and-ownership).
