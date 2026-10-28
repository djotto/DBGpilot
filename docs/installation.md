# Install and reach a first breakpoint

DBGpilot 0.1.0 is available as a **GitHub testing prerelease**. Download its
verified wheel or source archive from
[v0.1.0-testing.1](https://github.com/djotto/DBGpilot/releases/tag/v0.1.0-testing.1).
Package-index publication remains pending. The core supports async Python 3.12
and 3.13 and has no third-party runtime dependencies. PHP/Xdebug and browser
tools are installed separately.

For a copyable example in another project's test suite, use the
[pytest / Playwright consumer quickstart](consumer-quickstart.md).

## Install an artifact

Create an environment using either supported Python version:

```sh
python3.12 -m venv .venv-dbgpilot
. .venv-dbgpilot/bin/activate
python -m pip install /absolute/path/dbgpilot-0.1.0-py3-none-any.whl
dbgpilot --version
python -c 'import dbgpilot; print(dbgpilot.__version__)'
```

Both version commands print 0.1.0. On Windows, use the environment's
`Scripts/python.exe`/activation command instead of POSIX activation. The tested
live harness is Linux/DDEV; the release report records each validation platform
and interpreter rather than claiming every OS is tested.

Source installation uses the same core API:

```sh
python -m pip install /absolute/path/dbgpilot-0.1.0.tar.gz
```

Building from source temporarily needs the pinned `poetry-core==2.1.1` backend;
pip installs it into an isolated build environment. It is not a runtime
dependency. For an offline install, obtain that wheel beforehand and use
`--no-index --find-links /path/to/build-tools`. The release validator verifies
the backend wheel's pinned SHA-256 before using it. Wheel installs need no build
backend. A Python library consumer does not need Poetry, DDEV, pytest or
Playwright.

The source archive includes the Python package, docs, examples, configuration
example and validation scripts. Development PHP/Drupal fixtures, generated
vendor code, reference projects and local test results are excluded. Full
development checks need the development checkout; package validation itself
can run from the unpacked source archive.

## First breakpoint without a browser

This walkthrough needs a **local PHP CLI with Xdebug loaded**. Check the actual
executable before running it:

```sh
php --version
php --ri xdebug
```

Unpack the source archive to obtain its maintained example, keeping the wheel
installed in the environment above:

```sh
tar -xzf /absolute/path/dbgpilot-0.1.0.tar.gz
python dbgpilot-0.1.0/examples/first_breakpoint.py --launch --php php
```

The example writes a temporary six-line PHP calculation, explicitly launches
an owned DBGpilot process on available local ports, and starts PHP with
per-process Xdebug settings. It sets a breakpoint before `$total` is calculated,
returns a snapshot with `$discount == 10`, closes that client while PHP stays
paused, reconnects by session ID, inspects/mutates the discount to 15, steps,
detaches and asserts actual PHP output `85`. It prints `paused` and `complete`
JSON events. Finally it shuts down its own daemon and removes temporary files.
It changes no PHP ini file, application source or database. This command needs
no browser, pytest, DDEV or import from the development checkout.

Inside the prepared development container, the same example runs with:

```sh
ddev poetry run python examples/first_breakpoint.py --launch
```

## Debug an existing application

Start a persistent server where the PHP runtime can reach it:

```sh
dbgpilot serve --no-config
# Or load deliberate project settings:
dbgpilot serve --config /project/dbgpilot.toml
```

Keep that process alive. From another terminal in the installed environment:

```sh
dbgpilot call health --no-config
```

Health/readiness report package `version`, protocol `dbgpilot/1`, and the
debugger listening address. The API and debugger ports serve different clients:

| Connection | Direction and default |
| --- | --- |
| Script → DBGpilot API | HTTP/JSON, `127.0.0.1:9004` |
| PHP/Xdebug → debugger listener | DBGp TCP, `127.0.0.1:9003` |
| Browser → PHP application | The application's ordinary HTTP(S) URL |

Enable Xdebug's debug mode and trigger support in the **PHP runtime serving the
request**, not merely a different CLI installation:

```ini
xdebug.mode=debug
xdebug.start_with_request=trigger
xdebug.client_host=127.0.0.1
xdebug.client_port=9003
```

That host is resolved from PHP's network namespace. PHP initiates the connection
to DBGpilot. For PHP in a container and DBGpilot on the host, use the actual
reachable host address (the provided DDEV setup uses `host.docker.internal` for
this arrangement). For two containers, use a reachable container/service name
and bind the debugger listener accordingly. API access from another namespace
also needs deliberate routing; publishing an API port does not publish the
debugger port. Non-loopback API binding requires a bearer token.

The included checkout site normally runs PHP and DBGpilot in the same parent
container, so localhost is correct there. The Drupal fixture uses a separate
container and connects to `ddev-xdebug-web:9003`. See [Drupal](drupal.md) for its
actual addresses and setup, and [server](server.md) for authentication/lifetimes.

Pass an appropriate `XDEBUG_TRIGGER`/`XDEBUG_SESSION` to the application's
request; the Python Playwright helper generates matching unique values. If
`xdebug.trigger_value` is restricted, configure permitted values deliberately.
Breakpoints use engine file URIs or local paths translated by configured roots.
[Path mappings](path-mapping.md) translate source locations, not networks or
mounts. `dbgpilot.example.toml` shows the shared configuration; library loading
is explicit, while CLI discovery can be disabled with `--no-config`.

## Optional browser and pytest use

Install browser tooling only when needed:

```sh
python -m pip install 'playwright>=1.64,<2'
python -m playwright install chromium
# For the opt-in pytest integration:
python -m pip install 'pytest>=8.3,<10' 'pytest-asyncio>=1,<2'
```

Linux Chromium may also require Playwright's documented system libraries;
the development harness prepares them with `ddev test-setup`. These packages
are optional tools, not DBGpilot runtime requirements; no package extras are
declared. Existing async Playwright pages can be reused. See
[Python setup](python-setup.md) for ownership, function-scoped pytest fixtures,
reconnection and runnable installed-package examples, and
[Playwright](playwright.md) for navigation, form and AJAX captures.

## Diagnose setup failures

- CLI missing or import fails: activate the environment where the artifact was
  installed; compare `python --version` and `python -m pip show dbgpilot`.
- First walkthrough cannot attach: its selected PHP executable must load
  Xdebug. `XDEBUG_MODE` is set only for that child; the generated per-process
  settings route to its temporary listener. An ordinary application must instead
  use its own actual runtime, trigger and reachable daemon address.
- Port occupied: stop the process you intentionally own, or change the API port.
  Changing the debugger port also requires changing PHP's target. The local
  first-breakpoint example selects available ports automatically.
- Health works but PHP does not attach: check the direction of the Xdebug
  connection and PHP's namespace/configuration, allowed trigger values and the
  actual PHP request selected by browser routing.
- PHP attaches but misses the line: check executable line numbers and
  `Client.to_remote(source_path)` against engine URIs. A host path and container
  path may refer to the same source through different namespaces.
- Browser stalls during a deliberate pause: keep its page and event loop alive;
  capture and browser-action deadlines are separate. Closing a client preserves
  PHP; closing the helper releases its captures. Resume/detach deliberately.
- Reconnect fails after restart: session IDs are scoped to the old process and
  cannot be migrated. Follow the [upgrade policy](release-policy.md).
