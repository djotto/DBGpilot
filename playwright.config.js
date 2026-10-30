const path = require('node:path');
const {defineConfig} = require('@playwright/test');
const httpPort = Number(process.env.PW_PHP_PORT ?? 19434);
const debugPort = Number(process.env.PW_XDEBUG_PORT ?? 19433);
for (const port of [httpPort,debugPort]) {
  if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PHP and Xdebug ports must be between 1 and 65535');
}
module.exports = defineConfig({
  testDir:path.join(__dirname,'tests/browser'), workers:1, timeout:30000,
  outputDir:path.join(__dirname,'test-results/playwright-js'),
  reporter:[['list'],['junit',{outputFile:path.join(__dirname,'test-results/playwright-js.xml')}]],
  use:{baseURL:`http://127.0.0.1:${httpPort}`,xdebugPort:debugPort,trace:'retain-on-failure'},
  webServer:{
    command:`php -d xdebug.mode=debug -d xdebug.start_with_request=trigger -d xdebug.client_host=127.0.0.1 -d xdebug.client_port=${debugPort} -S 127.0.0.1:${httpPort} -t "${path.join(__dirname,'tests/fixtures')}"`,
    url:`http://127.0.0.1:${httpPort}/checkout.php`,reuseExistingServer:false,timeout:10000,
  },
});
