// Same-process controls without importing the Playwright Test runner.
module.exports = {
  ...require('./lib/dbgp'),
  ...require('./lib/listener'),
  ...require('./lib/session'),
  ...require('./lib/paths'),
  PausedBrowser: require('./lib/capture').PausedBrowser,
  PartialValue: require('./lib/values').PartialValue,
  toJSONSafe: require('./lib/values').toJSONSafe,
};
