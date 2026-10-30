// Same-process controls without importing the Playwright Test runner.
module.exports = {
  ...require('./lib/dbgp'),
  ...require('./lib/listener'),
  ...require('./lib/session'),
  PartialValue: require('./lib/values').PartialValue,
  toJSONSafe: require('./lib/values').toJSONSafe,
};
