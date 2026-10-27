# Python setup and optional pytest fixtures

`DebuggerSetup` connects ordinary async Python scripts to the persistent
DBGpilot API. It can explicitly launch `python -m dbgpilot serve`, using the
configured interpreter. It requires Python 3.12 or 3.13 and only the standard
library. Install Playwright and its browsers separately for browser scripts:

```sh
python -m pip install dist/dbgpilot-0.1.0-py3-none-any.whl playwright
python -m playwright install chromium
```

Build the wheel with `poetry build`, or substitute its actual download path.
DBGpilot has not yet been published as part of this implementation. It does not import
Playwright or pytest when importing the core library.

## Connection and ownership

```python
from dbgpilot import DebuggerSetup

# Reuse infrastructure started elsewhere. No ambient TOML discovery.
async with DebuggerSetup(url="http://127.0.0.1:9004") as setup:
    print(await setup.health())
    async with setup.debugger(page) as debugger:
        paused = await debugger.goto(url, breakpoints=breakpoints)
        # inspect, step, resume, or reconnect while this helper stays alive
```

`page` is an existing **async** Playwright page. The setup owns its HTTP client;
`setup.debugger(page)` returns the existing `PlaywrightDebugger`, whose context
owns its captures. It does not own the page, browser, or event loop.

To launch an owned server without DDEV:

```python
setup = DebuggerSetup(launch=True, port=0, xdebug_port=9003)
try:
    async with setup:
        print(setup.url, setup.pid, await setup.health())
        # Use setup.client, setup.debugger(page), or independent Client calls.
    # Exiting setup closes its client. The server remains running.
finally:
    # Deliberately release ALL sessions in this owned server and stop it.
    await setup.shutdown(release_sessions=True)
```

| Operation | Effect |
| --- | --- |
| Snapshot return or `Client.aclose()` | PHP remains paused in the server |
| Setup context exit or `setup.aclose()` | Closes this setup's client; server and PHP survive |
| Debugger context exit or `debugger.aclose()` | Releases that helper's captures and settles browser actions |
| `setup.shutdown(release_sessions=True)` | Stops only its own child and releases every session it owns |
| Shutdown on a reused server | Raises `SetupError`; no server is stopped |

Keep the setup handle until explicit shutdown. A launched process can survive
the creating event loop, but the browser and pending browser actions require
their original loop to stay alive. Destroying a browser can abort its HTTP
request even though the daemon remains. Server restart loses all session IDs.
Shutdown without `release_sessions=True` fails even when no sessions are
currently reported, avoiding a race with a newly arriving PHP request.

Startup uses the CLI's bounded readiness record, matching child PID and server
instance identity, and an authenticated `health` RPC with protocol `dbgpilot/1`.
There is no attach-on-bind-failure fallback. An occupied API **or debugger** port
fails that launch and cleans up only its child. Two independent launches can
use `port=0, xdebug_port=0` for independent listeners; retrieve the assigned
debugger port from `await setup.health()` and configure the PHP runtime to use
it. Repeated/concurrent `start()` calls on one handle start one child.

Cancellation, timeout, or failed startup reaps the launched child and removes
temporary files. Closing a successfully started setup preserves its child.
Cleanup allows five seconds for graceful termination before killing the owned
child; that bounded cleanup can follow an expired startup deadline.
`setup.health()` checks for unexpected child exit and identity changes. No
background supervisor restarts a failed process. Launching uses the current
interpreter by default; it must have DBGpilot installed. Authentication values
are excluded from config representations, launch arguments, readiness, and
setup error messages. Tokens are passed to children through their environment.

## Deliberate configuration

Use `DebuggerSetup(config="/project/dbgpilot.toml")`,
`DebuggerSetup(discover=True)`, or a preconstructed `SetupConfig`. With
`discover=True`, discovery walks upward from the caller's current directory.
The default library call reads no configuration file. `config=False` disables
discovery even if `discover=True` is supplied. Direct `Client` usage is unchanged.

```toml
[connection]
url = "http://127.0.0.1:9004"
timeout = 35
# Optional; the variable must be set when this file is loaded.
token_env = "PROJECT_DEBUG_TOKEN"

[startup]
launch = false
timeout = 10
# python = ".venv/bin/python"
# working_directory = "."

[listener]
host = "127.0.0.1"
port = 9004
xdebug_host = "127.0.0.1"
xdebug_port = 9003

[[path_mappings]]
local = "."
remote = "file:///var/www/html"
```

`connection.timeout` is the client transport timeout; `startup.timeout` bounds
the entire launch/readiness/compatibility check. Both are finite positive
seconds. They do not replace the helper's capture timeout or Playwright action
deadlines. Listener ports accept 0 through 65535, with zero selecting an
available port. The defaults above also apply when no file is loaded, except
that no token environment variable is read by the library by default.

Explicit setup keyword arguments override loaded settings, which override
defaults. API names are `request_timeout`, `startup_timeout`, `launch`, `url`,
`token`, `python`, `working_directory`, `host`, `port`, `xdebug_host`,
`xdebug_port`, and `path_mapper`. `url` is for reuse; an owned launch uses the
listener settings and its readiness URL. Reused servers retain their existing
listener and mappings; loading a client-side file does not reconfigure them.

`dbgpilot serve` and `dbgpilot call` deliberately discover `dbgpilot.toml` unless
`--no-config` is passed. Both accept `--config FILE`. Explicit CLI options
override the file. For CLI authentication, `--token` overrides `DBGPILOT_TOKEN`,
which overrides the file's `connection.token_env`. `serve` starts the server
regardless of `startup.launch`; `call` connects without launching one. Startup
timeout/interpreter/working-directory settings belong to the Python helper.
`call --timeout` overrides `connection.timeout` for its HTTP transport.
Repeatable `serve --path-map LOCAL REMOTE` overrides individual configured roots.
An overridden `connection.token_env` need not be set. Without a token override,
the configured variable remains required. An explicit API `token=None` disables
the file's token setting.

Relative mapping roots, startup working directories, and interpreter paths
containing a slash are resolved against the config file's directory on the
machine reading it. A bare interpreter name uses PATH. Explicit API path
overrides use the caller's current directory. Owned launches pass resolved
mappings to the CLI and disable unrelated child-directory discovery. Mapping
paths are lexical and do not require the source files to exist on the server.
See [path mapping](path-mapping.md) for Windows, URI, and conflict handling.

## Standalone and pytest examples

[checkout_debug.py](../examples/checkout_debug.py) runs against the repository's
checkout PHP fixture. It captures `$discount`, closes the first client,
reconnects by ID, inspects and mutates PHP, steps, detaches, and asserts `£85` in
the actual DOM. Line 11 is the `$total` assignment in this pinned fixture.

```sh
# Inside the prepared parent DDEV container, with no other daemon on port 9003:
ddev poetry run python examples/checkout_debug.py --launch --port 0 \
  --source /var/www/html/src/checkout.php --line 11
# Reuse an independently running server instead:
ddev poetry run python examples/checkout_debug.py --url http://127.0.0.1:9004 \
  --source /var/www/html/src/checkout.php --line 11
```

The [pytest example](../examples/pytest/) runs the same investigation using the
opt-in fixtures. Install `pytest>=8.3,<10` and `pytest-asyncio>=1,<2` separately.
In a consuming suite's top-level `conftest.py`, enable the plugin explicitly:

```python
import pytest

pytest_plugins = ["dbgpilot.pytest_plugin"]

@pytest.fixture
def dbgpilot_options():
    return {"url": "http://127.0.0.1:9004"}  # reused; never shut down

@pytest.fixture
def dbgpilot_page(my_async_page):
    return my_async_page  # supplied and owned by your existing suite
```

The default `dbgpilot_page` uses a fixture named `page`; it must be an **async**
page, rather than the synchronous Playwright pytest fixture. The provided
example creates its own async page; ordinary consuming suites can reuse theirs.
`dbgpilot_setup` and `dbgpilot_debugger` are function-scoped async fixtures with
function-scoped loops. The debugger releases its captures first; setup then
closes its client and explicitly shuts down an owned child. Reused daemons and
other clients' sessions remain under their existing owners. Using `launch=True`
in fixture options opts into teardown that releases that child's sessions.

Tests use `@pytest.mark.asyncio`, or configure `asyncio_mode = auto`. Keep
`asyncio_default_fixture_loop_scope = function`. For longer-lived shared
infrastructure, start a daemon separately and keep these clients function scoped.
If replacing async fixture scopes, align all dependent fixture/test loop scopes
and browser lifetimes; a page must stay on the loop that created it.

For parallel pytest workers, a shared independently started server with separate
pages and generated capture IDE keys is the normal configuration. Do not reuse
an explicit fixed `idekey` across simultaneous captures. Worker-owned daemons
need isolated API **and** debugger ports, plus PHP routing to the correct
listener; `port=0, xdebug_port=0` isolates sockets but does not configure Xdebug.
The fixed-port DDEV acceptance harness runs sequentially. No fixture can shut
down a server it merely reused.

```sh
ddev exec env DBGPILOT_EXAMPLE_LAUNCH=1 \
  DBGPILOT_EXAMPLE_SOURCE=/var/www/html/src/checkout.php \
  /mnt/ddev_config/commands/web/poetry run pytest examples/pytest -q
```

To verify the **installed wheel** outside the source tree, including both real
examples after installing the development tooling:

```sh
ddev poetry build
ddev poetry run python scripts/check_setup_examples.py --live
```

`./scripts/check.sh` also builds the wheel and runs this installed-example check
after the required full suite.

The checker creates a fresh environment, installs the wheel without dependencies,
verifies core imports without pytest or Playwright, then exposes only the
development environment's optional dependencies. It copies examples into a
temporary directory and asserts the imported DBGpilot comes from the wheel.
Without `--live`, it validates imports, standalone CLI help and pytest collection
only. A successful collection is not evidence of PHP/browser acceptance.

## DDEV and Drupal

Local startup does not require DDEV and cannot implicitly start a container.
If PHP runs inside a container, it initiates the debugger connection; configure
its `xdebug.client_host` and port to reach the actual listener. The browser URL,
HTTP API URL, and debugger listener address can belong to different networks.
Starting a host daemon does not make container loopback reach that host.

For the provided Drupal fixture, either reuse a daemon started separately:

```sh
ddev poetry run dbgpilot serve --xdebug-host 0.0.0.0 \
  --config fixtures/drupal11/dbgpilot.toml
```

or run Python inside the parent DDEV container with:

```python
setup = DebuggerSetup(config="fixtures/drupal11/dbgpilot.toml", launch=True,
                      port=0, xdebug_host="0.0.0.0")
```

The Drupal container connects to `ddev-xdebug-web:9003`. The browser uses
`http://ddev-dbgpilot-drupal11-web`; the API stays on parent-container loopback.
Use `setup.debugger(page)` and a breakpoint in the actual Drupal source with
this setup. `tests/test_drupal.py::test_drupal_owned_setup_configuration_and_reconnect`
is a runnable core-rendering example: capture the entity label, close the first
client, reconnect, mutate its in-memory title, detach, and verify the page.
It runs via `ddev drupal-test` after `ddev drupal-setup` and `ddev test-setup`.
See the [Drupal guide](drupal.md) for database seeding and complete form/AJAX
investigations. For scripts outside the container, publish/configure reachable
API and debugger addresses separately and map the script's source namespace;
the fixture does not publish those ports to the host automatically.

## Failure diagnostics

`SetupError` distinguishes incompatible API versions, authentication failure,
startup deadline, occupied listeners, missing launch prerequisites, identity
mismatch, and unexpected child exit. Existing `Client` calls retain their
structured RPC errors. Capture `TimeoutError` includes troubleshooting notes:

- Verify a normal browser request works and the route pattern matches the PHP
  request, including POST or AJAX. Block service workers if they intercept it.
- Check Xdebug debug mode, trigger support, allowed trigger values, and outbound
  connectivity to `health()["xdebug_host"]`/`xdebug_port`. A wildcard listener
  needs a concrete reachable address in PHP configuration.
- Verify `await setup.client.to_remote(source_path)` and breakpoint line
  executability. Local/server path mapping never changes network routing.
- A capture timeout covers attaching and reaching the breakpoint, ending once
  the paused handle returns. A browser navigation/click deadline is separate;
  use `navigation_timeout=0` or action `timeout=0` for deliberately long pauses.
- A completed AJAX click can precede PHP completion. Resume/detach explicitly
  and assert the resulting DOM. Keep the helper, browser, and loop alive during
  reconnection. Closing the helper releases its captures.

Cleanup after client closure uses a fresh client. If the server is unreachable,
remote cleanup can fail and is reported; reconnect to the same daemon and
explicitly close the session when connectivity returns. Restarting the daemon
releases its sessions and invalidates their IDs.
