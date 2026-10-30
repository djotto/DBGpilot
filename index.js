// Playwright Test with an `xdebug` fixture. Use in place of @playwright/test:
//   const { test, expect } = require('playwright-xdebug');

const { test: base, expect } = require('@playwright/test');
const { randomBytes } = require('crypto');
const { Listener, Xdebug } = require('./lib/listener');
const { XdebugError } = require('./lib/dbgp');
const core = require('./core');

const test = base.extend({
  // Must match xdebug.client_host / xdebug.client_port.
  xdebugHost: ['127.0.0.1', { scope: 'worker', option: true }],
  xdebugPort: [9003, { scope: 'worker', option: true }],
  // How long a request nobody is waiting for stays paused before release.
  xdebugUnclaimedTimeout: [2_000, { option: true }],
  xdebugIdeKey: [undefined, { option: true }],
  xdebugPathMappings: [[], { option: true }],
  xdebugBaseDir: [undefined, { option: true }],

  _xdebugListener: [async ({ xdebugHost, xdebugPort }, use) => {
    const listener = new Listener();
    await listener.listen(xdebugPort, xdebugHost);
    try { await use(listener); } finally { await listener.close(); }
  }, { scope: 'worker' }],

  xdebug: async ({ context, baseURL, _xdebugListener, xdebugUnclaimedTimeout, xdebugIdeKey, xdebugPathMappings, xdebugBaseDir }, use, testInfo) => {
    const ideKey = xdebugIdeKey ?? `pw${testInfo.workerIndex}-${randomBytes(8).toString('hex')}`;
    const xdebug = new Xdebug(context, ideKey, xdebugUnclaimedTimeout, {
      step: (title, body) => base.step(title, body, { box: true }),
      pathMappings: xdebugPathMappings, baseDir: xdebugBaseDir,
    });
    _xdebugListener.register(xdebug);
    try {
      if (baseURL) await xdebug.enableFor(baseURL);
      await use(xdebug);
    } finally {
      _xdebugListener.unregister(xdebug);
      await xdebug.dispose();
    }
  },
});

module.exports = { ...core, test, expect, XdebugError };
