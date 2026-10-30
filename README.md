Important note: This project is completely vibe-coded, even the docs. I haven't
even opened most of the files here, and if you use it it's completely at your
own risk. All the "tests" are LLM-written, too. They mean nothing.

The goal is to extend pytest with xdebug controls, so it can use Playwright and
xdebug simultaneously. There are other potential uses (eg a command-line tool
to allow LLMs to interact with xdebug), but controlling Playwright and xdebug
from the same Python script was my main goal.

# DBGpilot

An asynchronous Python controller for Xdebug's DBGp protocol. Python 3.12/3.13,
MIT licensed, with no runtime dependencies outside the standard library.

Current version: **0.1.1, testing prerelease**. Download the wheel/source from
[GitHub Release v0.1.1-testing.1](https://github.com/djotto/DBGpilot/releases/tag/v0.1.1-testing.1)
and follow the [first-breakpoint guide](docs/installation.md).
For an existing pytest / async Playwright project, start with the
[consumer quickstart](docs/consumer-quickstart.md) and copyable minimal example.
See [release policy](docs/release-policy.md), [changelog](CHANGELOG.md), and
[candidate validation/rehearsal](docs/releasing.md) for compatibility and status.

DBGpilot listens for PHP debugging connections. Each request gets an independent
session that stays alive between inspection and execution commands. A breakpoint
snapshot is a copied, JSON-safe value; returning it does not resume PHP.

```python
import json
from dbgpilot import Controller

async def investigate():
    async with Controller(host="127.0.0.1", port=9003) as pilot:
        # Trigger the PHP request concurrently, through a browser or HTTP client.
        session = await pilot.wait_for_session(timeout=30)
        await session.set_breakpoint("/var/www/html/src/checkout.php", 11)
        stopped = await session.run_until_break(timeout=30)
        snapshot = await session.snapshot(["$subtotal", "$discount"])
        print(json.dumps(snapshot.to_dict()))

        # PHP remains paused: the application can choose what to do next.
        calculated = await session.evaluate("$subtotal - $discount")
        await session.step_over()
        await session.detach()  # Let PHP finish its HTTP response.
```

The listener and sessions live in the owning Python process. Use the persistent
server when scripts or later tool calls need to reconnect to the same session.

## Persistent server

Run inside the DDEV container alongside PHP:

```sh
ddev poetry install
ddev poetry run dbgpilot serve
```

The JSON API listens on `127.0.0.1:9004`; Xdebug connects separately on port
9003. Keep this process running. In another terminal:

```sh
ddev poetry run dbgpilot call health
ddev poetry run python scripts/check_server_harness.py
```

The example returns a breakpoint snapshot, closes its first client, reconnects
with the session ID, changes the discount, and finishes the HTTP response.
Closing a client leaves PHP paused. Explicitly call `detach()`, `stop()`, or
`close()` to finish debugging. Sessions and their IDs last for the server process.

```python
from dbgpilot import Client

async with Client() as pilot:
    # Start the browser action concurrently: PHP may wait for debugging.
    session = await pilot.wait_for_session(timeout=30)
    await session.set_breakpoint("/var/www/html/src/checkout.php", 11)
    snapshot = await session.break_and_return(["$subtotal", "$discount"])
    session_id = session.id
    # snapshot is JSON-safe; PHP stays paused after this client closes.

async with Client() as later:
    session = later.session(session_id)
    value = await session.evaluate("$subtotal - $discount")
    await session.detach()
```

The API supports concurrent clients and replayable event cursors. Python
Playwright scripts can use `PlaywrightDebugger` to coordinate navigation,
form submission, and AJAX with breakpoint snapshots; JavaScript scripts can
call `/rpc` directly. `Client.request()` exposes explicit remote cancellation.
See the [server guide](docs/server.md) for the wire protocol, Playwright example,
session selection, deadlines, event history, and cleanup behaviour.

Prepare the real browser and additional PHP/Xdebug test runtimes:

```sh
ddev test-setup
ddev poetry run pytest
```

With the server running, the actual browser example is:

```sh
ddev poetry run python scripts/check_playwright_harness.py
```

See [the Playwright helper guide](docs/playwright.md) and
[compatibility results](docs/compatibility.md).

Ordinary async scripts can use `DebuggerSetup` to reuse a server or explicitly
launch the installed CLI. Its context closes only its client; an owned daemon
is stopped with `shutdown(release_sessions=True)`. The opt-in pytest plugin
reuses existing async pages. See [Python setup](docs/python-setup.md) for shared
TOML settings, ownership, worker isolation, and standalone/pytest examples.

## Features

- Concurrent PHP sessions; independent command/response matching per connection.
- Line, conditional, exception, call/return, temporary, and hit-count breakpoint
  requests, with get/list/update/remove operations.
- Run, step into/over/out, detach, and explicit execution termination.
- Stack frames, contexts, frame-aware property reads, direct-child pagination,
  full string retrieval, PHP evaluation, scalar assignment, and source retrieval.
- Status, stack depth, type maps, capability discovery, and postmortem inspection
  where advertised by the engine.
- Standard and extended properties; typed scalars and binary-safe strings.
- Separate stream, notification, stopped, and connection-closed events.
- Structured breakpoint/error notifications and retained protocol metadata.
- DBGp proxy registration, unregister, and structured proxy errors.
- Standard input and interactive shells where advertised by the engine.
- Optional expression/code execution and spawnpoint management with capability
  checks; see [optional commands](docs/optional-commands.md).
- Configurable local/remote path mappings, including Windows paths on Linux
  servers, project configuration, and local locations in snapshots/events.
- Bounded incoming packets/events, command timeouts, cancellation, and cleanup.
- Persistent HTTP/JSON server, async client, CLI, session IDs, and replayable
  stream/notification/stop events.

See [the API guide](docs/api.md) for state/lifetime rules and Xdebug limitations.

## Install and test

Prepare a local artifact for testing or manual sharing with
`./scripts/release.sh`. It wraps the distribution validator, builds wheel/source
artifacts and checks fresh installs without running the full test suite or
uploading anything. See [manual handoff and upload](docs/releasing.md#manual-upload)
for the next step. Run the broader tests separately when you choose.

To share a candidate on GitHub, use
`poetry run python scripts/github_release.py CANDIDATE --tag TAG`.
It uploads the checked files to a draft prerelease with consumer install notes;
`--dry-run` previews it and `--publish` publishes immediately. See the
[GitHub release steps](docs/releasing.md#github-release-command) for committing,
tagging and making the download available to consumers.

An artifact installation needs neither Poetry nor the development fixtures:

```sh
python -m pip install /absolute/path/dbgpilot-0.1.1-py3-none-any.whl
dbgpilot --version
```

The [installation guide](docs/installation.md) also covers source installs,
optional browser/pytest tools, PHP/Xdebug routing, and a standalone local PHP
walkthrough that reconnects after closing its first client. For development:

```sh
poetry install
poetry run pytest -m "not integration"
poetry build
```

The development dependencies are pytest, pytest-asyncio, Hypothesis, Playwright,
and pylint. Browser installation is separate (`ddev test-setup`).

## DDEV integration harness

The included PHP 8.4 site has Xdebug enabled and Python 3.13/Poetry available.

```sh
ddev start
ddev test-setup
ddev poetry run pytest -m integration
# Run every test, including the TCP peer tests, inside DDEV:
ddev poetry run pytest
# Runnable HTTP debugging example, with breakpoint and completion JSON events:
ddev poetry run python scripts/check_harness.py
```

The site is at https://xdebug.ddev.site. Use `SAVE10` in the form to subtract £10
from a £100 order. `/health.php` reports the PHP-FPM runtime;
`/?code=SAVE10&format=json` returns the calculation.

Xdebug points to **127.0.0.1:9003 inside the web container**. Start DBGpilot before
triggering a request with `XDEBUG_TRIGGER=1` as a query parameter or cookie.
The Playwright helper routes the first matching request with a unique trigger
and IDE key, leaving subsequent requests unmodified.
The project directory is `/var/www/html` in the container.

To listen from the host, change `xdebug.client_host` in `.ddev/php/xdebug.ini` to
`host.docker.internal` and restart DDEV. Pass server-side file URIs to breakpoint
operations. Configure directory roots in `dbgpilot.toml` or with
`--path-map LOCAL REMOTE` to use local source paths. Results retain engine URIs
and include mapped local paths. See [path mappings](docs/path-mapping.md) for
configuration and diagnostics, and [proxies and optional shells](docs/proxies-and-shells.md) for proxy
registration, stdin, and interactive command APIs.

The host uses `.venv/`. `ddev poetry` uses a separate environment in DDEV's
persistent cache, so macOS and Linux packages do not mix. Live integration tests
skip outside DDEV. TCP peer tests need permission to bind local listening sockets.

Architecture, test strategy, and source references: [development notes](docs/development.md).
Spec audit and implementation checklist: [TODO.md](TODO.md).

## Drupal 11 target

A separate pinned Drupal 11.4.11 site exercises actual core rendering, Form API
database saves, and author-autocomplete AJAX through Chromium and Xdebug:

```sh
ddev drupal-setup
ddev test-setup
ddev drupal-test
```

Open https://dbgpilot-drupal11.ddev.site; fixture login is
`admin` / `dbgpilot-admin`. Its own database is separate from the checkout site.
See [the Drupal guide](docs/drupal.md) for setup, manual debugging, path mappings,
recorded results, and the observed render-Fiber stack behaviour.

## References and provenance

While building DBGpilot, we consulted the
[DBGp specification](https://xdebug.org/docs/dbgp),
[Xdebug's implementation](https://github.com/xdebug/xdebug), and these debugger
projects as design and interoperability references:

- [Komodo Python DBGp](https://github.com/agroszer/komodo-python3-dbgp)
- [Vdebug](https://github.com/vim-vdebug/vdebug)
- [Pugdebug](https://github.com/Mte90/pugdebug)

The three debugger projects were initially included as development references.
Their dependencies, associated Qt packages, and vendored snapshots have since
been removed. DBGpilot is an original implementation that runs and is tested
independently; no implementation code from those projects is copied, imported,
or bundled.

See [NOTICE.md](NOTICE.md) for provenance and the
[development notes](docs/development.md#design-references-and-provenance) for the
specific revisions and topics consulted.
