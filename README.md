# DBGpilot

Drive PHP/Xdebug from JavaScript while Playwright operates the browser. Pause a
request, inspect or change PHP variables, step through execution, then let the
browser finish and assert on the response.

DBGpilot provides a Playwright Test fixture and a standalone Node API, sharing
one debugger implementation. It requires Node 20+ and PHP with Xdebug step
debugging enabled. No Python or pytest is required.

## Documentation

| Guide | Contents |
| --- | --- |
| [Getting started](docs/getting-started.md) | Installation, PHP configuration, container networking and a runnable first test. |
| [Workflows](docs/workflows.md) | Navigation, forms, AJAX, manual attachment, timeouts and standalone scripts. |
| [API reference](docs/api.md) | Fixture options, capture handles, sessions, breakpoints, events, errors and limits. |
| [Values and paths](docs/values-and-paths.md) | PHP value conversion, binary data, snapshots, source mappings and Windows paths. |
| [Troubleshooting](docs/troubleshooting.md) | Attachment failures, missed breakpoints, blocked browser actions and cleanup. |
| [Development](docs/development.md) | Repository layout, DDEV, test commands, runtime matrix and package verification. |
| [Distribution](docs/releasing.md) | Local installs, GitHub pins, release candidates and the Python archive. |

## Install

The package is named `dbgpilot` and is distributed through
[GitHub releases](https://github.com/djotto/DBGpilot/releases/tag/js-v0.1.0-testing.1).
Install the validated release tarball in the project that will use it:

```sh
npm install --save-dev https://github.com/djotto/DBGpilot/releases/download/js-v0.1.0-testing.1/dbgpilot-0.1.0.tgz @playwright/test
npx playwright install chromium
```

The release includes a SHA-256 checksum. npm registry publication is disabled.
See [installation alternatives](docs/getting-started.md#installation) for local
builds, source installs and GitHub commits. Commit the consumer's lockfile.

## Use the fixture

Import DBGpilot's extended `test` instead of the base Playwright Test object:

```js
const {test, expect} = require('dbgpilot');

test('inspect a discount', async ({page, xdebug, baseURL}) => {
  const paused = await xdebug.goto(page, new URL('/checkout', baseURL).href, {
    breakpoints: [{file: '/var/www/html/src/Checkout.php', line: 42}],
    variables: ['$discount'],
  });
  try {
    expect(paused.snapshot.variables.$discount.value).toBe(10);
    await paused.session.setVariable('$discount', 15);
    await paused.session.detach();
    await paused.finished();
    await expect(page.getByTestId('total')).toHaveText('85');
  } finally {
    await paused.close();
  }
});
```

This example assumes an application with that checkout URL, executable PHP line
and output element. [Getting started](docs/getting-started.md#first-test-in-this-repository)
provides an example using the included checkout application.

Configure `baseURL`, one test worker, and PHP's connection **to** the debugger
listener before running it. The browser talks HTTP to the website; PHP makes a
separate DBGp connection to Node. A paused request keeps its PHP worker occupied.
See [PHP and networking](docs/getting-started.md#php-and-xdebug-configuration).

ESM and TypeScript are supported:

```js
import {test, expect} from 'dbgpilot';
import {Listener, Xdebug, toJSONSafe} from 'dbgpilot/core';
```

The `dbgpilot/core` entry point works without a Playwright Test execution context.
See [standalone scripts](docs/workflows.md#standalone-node-scripts) and the
[complete example](examples/standalone.js).

## Lifetime and scope

A session belongs to its test or script. `goto()` and `capture()` return while
PHP is paused. Inspect it, then `detach()` to let the request finish; `stop()`
terminates PHP instead. Awaiting browser completion does not resume PHP.
Teardown releases owned requests on success or failure.

Commands are attempted when called, and Xdebug errors reach the caller. Use
`await session.getCapabilities()` for a fresh inventory when you need one.
There is no capability cache, daemon, cross-script reconnection, or debugger
proxy workflow. Unsupported engine extensions remain engine errors.

## Develop and verify

```sh
npm run check:fast
```

For the full PHP, Chromium and Drupal suite, follow
[development setup](docs/development.md#full-environment). The maintained matrix
covers PHP 8.2–8.5 and Xdebug 3.3.2, 3.4.7 and 3.5.3 in the combinations listed
there. These are tested combinations, not a promise that every extension is
available on every engine.

DBGpilot is MIT licensed; see [LICENSE](LICENSE) and [provenance](NOTICE.md).
The retired Python implementation remains on
[archive/python](https://github.com/djotto/DBGpilot/tree/archive/python).
