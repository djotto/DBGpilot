# Getting started

[Documentation index](../README.md#documentation) · [Workflows](workflows.md) · [API](api.md)

## Requirements

Use Node 20 or newer, Playwright Test 1.50 or newer, a Playwright browser, and a
PHP runtime with Xdebug's step debugger enabled. The package contains JavaScript,
CommonJS/ESM entry points and TypeScript declarations; no compilation step,
Python service or pytest runner is needed.

The PHP application can run on another host or in a container. PHP must be able
to open a TCP connection to the Node process. DBGpilot does not install or
configure Xdebug in the application for you.

## Installation

The package name is `dbgpilot`. Registry publication is disabled in this source
tree. Use a GitHub release or one of the other sources below alongside
`@playwright/test`.

### GitHub release

The first JavaScript prerelease is
[`js-v0.1.0-testing.1`](https://github.com/djotto/DBGpilot/releases/tag/js-v0.1.0-testing.1).
Install its validated tarball directly:

```sh
npm install --save-dev https://github.com/djotto/DBGpilot/releases/download/js-v0.1.0-testing.1/dbgpilot-0.1.0.tgz @playwright/test
npx playwright install chromium
```

The release also provides `dbgpilot-0.1.0.tgz.sha256` for checksum verification.
This uses GitHub as the package source; it does not install DBGpilot from the
npm registry.

### Validated tarball

In the DBGpilot checkout:

```sh
npm ci
npm run check:package
```

In the consuming project:

```sh
npm install --save-dev /absolute/path/DBGpilot/dist/js-candidate/dbgpilot-0.1.0.tgz @playwright/test
npx playwright install chromium
```

The package check installs the actual tarball outside the checkout and validates
its CommonJS, ESM and TypeScript entry points. For browser system libraries on a
supported Linux host, Playwright also provides `npx playwright install --with-deps chromium`.

### Local checkout

```sh
npm install --save-dev /absolute/path/DBGpilot @playwright/test
```

A local source dependency can link to the checkout. Use a tarball when testing
what another project will actually receive.

### GitHub source

Once the desired commit is on GitHub:

```sh
npm install --save-dev dbgpilot@github:djotto/DBGpilot#main @playwright/test
```

Replace `main` with a reviewed commit SHA to select a specific revision. Commit
that project's lockfile. Changes that exist only locally require a local source
or tarball install. The JavaScript release tag above is another source pin;
there is no npm registry release. See [distribution](releasing.md).

## PHP and Xdebug configuration

Configure the **PHP runtime serving the website**, which may differ from the
`php` executable in your terminal:

```ini
xdebug.mode=debug
xdebug.start_with_request=trigger
xdebug.discover_client_host=0
xdebug.client_host=127.0.0.1
xdebug.client_port=9003
```

Restart the serving PHP runtime after changing its startup configuration. Check
its loaded Xdebug version, mode and destination. `php --ri xdebug` is useful for
CLI PHP, but does not prove that PHP-FPM or Apache uses the same settings.

Xdebug initiates the debugger connection. These addresses have different jobs:

| Setting | Meaning |
| --- | --- |
| Playwright `baseURL` | HTTP(S) address of the website, reached by the browser. |
| PHP `xdebug.client_host` | Address PHP uses to reach Node. |
| PHP `xdebug.client_port` | TCP port PHP connects to. |
| Fixture `xdebugHost` | Local interface on which Node listens. |
| Fixture `xdebugPort` | Local TCP port on which Node listens. |

For PHP and Node in the same container or host, `127.0.0.1:9003` works for both
ends. Across containers, use the Node container's reachable hostname as PHP's
`client_host`, and bind Node to `0.0.0.0`. PHP in a container connecting to a host
process needs that host's address as seen from the container. Do not use the
website's URL as a substitute for the debugger destination.

Use DBGpilot on a trusted development network: its listener is a debugger
endpoint, with access to PHP inspection and evaluation. Connection behavior and
trigger settings are described in [Xdebug's step-debugging guide](https://xdebug.org/docs/step_debug).

## Playwright configuration

For a consuming project, create `playwright.config.js`:

```js
const {defineConfig} = require('@playwright/test');

module.exports = defineConfig({
  testDir: './tests',
  workers: 1,
  timeout: 120_000,
  use: {
    baseURL: 'http://localhost:8080',
    xdebugHost: '127.0.0.1',
    xdebugPort: 9003,
  },
});
```

Replace the URL and networking values with those for your application. In specs,
import `test` and `expect` from `dbgpilot`. The fixture is still named `xdebug`.
Its operations appear as Playwright test steps, and it owns request cleanup.

The `require()` examples use CommonJS. If your consuming project sets
`"type": "module"`, use ESM imports in specs and either ESM configuration or a
`playwright.config.cjs` file for the CommonJS configuration above:

```js
import {test, expect} from 'dbgpilot';
```

For a typed configuration, use the exported option types:

```ts
import {defineConfig} from '@playwright/test';
import type {XdebugTestOptions, XdebugWorkerOptions} from 'dbgpilot';

export default defineConfig<XdebugTestOptions, XdebugWorkerOptions>({
  workers: 1,
  timeout: 120_000,
  use: {baseURL: 'http://localhost:8080', xdebugPort: 9003},
});
```

Run debugger tests with one worker. Multiple workers using the same listening
port conflict. Several PHP sessions can share one worker, provided the PHP server
has enough independent processes to serve them. See [concurrency](workflows.md#concurrency).

## First test in this repository

Set up the bundled development environment from the repository root:

```sh
ddev start
ddev test-setup
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npm run test:browser
```

DDEV serves the example at <https://xdebug.ddev.site/>. The browser test config
starts a separate PHP CLI server on port 19434, connecting to the debugger on
19433. Both use `tests/fixtures/checkout.php`.

Save this as `tests/browser/investigate.spec.js`. It locates the fixture's
breakpoint marker instead of depending on a hard-coded line number:

```js
const fs = require('node:fs');
const path = require('node:path');
const {test, expect} = require('dbgpilot');
const file = path.resolve('tests/fixtures/checkout.php');
const line = fs.readFileSync(file, 'utf8').split('\n')
  .findIndex(text => text.includes('BREAKPOINT:')) + 1;

test('change the discount for one response', async ({page, xdebug, baseURL}) => {
  const paused = await xdebug.goto(page, `${baseURL}/checkout.php?code=SAVE10`, {
    breakpoints: [{file, line}],
    variables: ['$discount'],
    expressions: ['$subtotal - $discount'],
  });
  try {
    expect(paused.snapshot.variables.$discount.value).toBe(10);
    expect(paused.snapshot.expressions['$subtotal - $discount'].value).toBe(90);
    await paused.session.setVariable('$discount', 15);
    await paused.session.detach();
    expect((await paused.finished()).status()).toBe(200);
    await expect(page.getByTestId('total')).toHaveText('85');
  } finally {
    await paused.close();
  }
});
```

Run it with the repository's existing config:

```sh
ddev exec env PLAYWRIGHT_BROWSERS_PATH=/mnt/ddev-global-cache/dbgpilot/playwright npx playwright test tests/browser/investigate.spec.js
```

The breakpoint pauses **before** the marked assignment. Changing `$discount`
therefore changes the total when PHP resumes. Changing a variable after its value
has already been consumed does not undo earlier calculations.

For another application, replace the URL, source path, line and assertion. If
Node and PHP see different source roots, add [path mappings](values-and-paths.md#source-paths).

## Restricted trigger values

The ordinary fixture uses a generated IDE key and enables an `XDEBUG_TRIGGER`
cookie for `baseURL`. If PHP restricts accepted triggers with
[`xdebug.trigger_value`](https://xdebug.org/docs/all_settings#trigger_value), set
`xdebugIdeKey` to an accepted value for cookie-based attachment.

`capture()` and `goto()` generate separate keys for their selected request. Their
`ideKey` option must be set explicitly when PHP restricts trigger values; it does
not inherit `xdebugIdeKey`. Use a different accepted key from the parent owner:

```js
test.use({xdebugIdeKey: 'accepted-background-key'});
// Inside a test; PHP must accept both values:
const paused = await xdebug.goto(page, absoluteURL, {
  ideKey: 'accepted-capture-key',
  breakpoints,
});
```

Keys registered with one listener must be unique. Reusing the parent key for a
capture, or using one capture key concurrently, is rejected. If your PHP setup
only permits one key, use the [manual attachment workflow](workflows.md#manual-attachment).
