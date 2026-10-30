const path = require('node:path');
const {defineConfig} = require('@playwright/test');
const base = require('./playwright.config');
module.exports = defineConfig({
  ...base,testDir:path.join(__dirname,'tests/stress'),timeout:60000,
  outputDir:path.join(__dirname,'../test-results/playwright-stress-js'),
  reporter:[['list'],['junit',{outputFile:path.join(__dirname,'../test-results/playwright-stress-js.xml')}]],
  webServer:{...base.webServer,env:{PHP_CLI_SERVER_WORKERS:'4'}},
});
