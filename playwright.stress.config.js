const path = require('node:path');
const {defineConfig} = require('@playwright/test');
const base = require('./playwright.config');
const httpPort = Number(new URL(base.use.baseURL).port || 80);
const ports = Array.from({length:3},(_,index) => httpPort+index);
if (ports.some(port => port > 65535 || port === base.use.xdebugPort)) {
  throw new Error('Stress tests need three consecutive PHP HTTP ports, separate from the Xdebug port');
}
module.exports = defineConfig({
  ...base,testDir:path.join(__dirname,'tests/stress'),timeout:60000,
  outputDir:path.join(__dirname,'test-results/playwright-stress-js'),
  reporter:[['list'],['junit',{outputFile:path.join(__dirname,'test-results/playwright-stress-js.xml')}]],
  // A prefork CLI worker can accept two connections before serving either.
  // Pausing its first request then prevents its second from reaching Xdebug.
  // Independent servers guarantee one PHP process for each paused browser.
  webServer:ports.map(port => ({...base.webServer,
    command:base.webServer.command.replace(`-S 127.0.0.1:${httpPort}`,`-S 127.0.0.1:${port}`),
    url:`http://127.0.0.1:${port}/checkout.php`,
  })),
});
