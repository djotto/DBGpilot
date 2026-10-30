const path = require('node:path');
const {defineConfig} = require('@playwright/test');
module.exports = defineConfig({
  testDir:path.join(__dirname,'tests/drupal'),workers:1,timeout:60000,
  outputDir:path.join(__dirname,'../test-results/playwright-drupal-js'),
  reporter:[['list'],['junit',{outputFile:path.join(__dirname,'../test-results/playwright-drupal-js.xml')}]],
  use:{
    baseURL:process.env.PW_DRUPAL_URL ?? 'https://dbgpilot-drupal11.ddev.site',
    ignoreHTTPSErrors:true,xdebugHost:'0.0.0.0',xdebugPort:9003,xdebugUnclaimedTimeout:50,
    trace:'retain-on-failure',
  },
});
