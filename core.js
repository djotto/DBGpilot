// Same-process controls without importing the Playwright Test runner.
const {XdebugError,ProtocolError,ConnectionClosed,CommandTimeout} = require('./lib/dbgp');
const {Listener,Xdebug} = require('./lib/listener');
const {Session} = require('./lib/session');
const {PathMapper,PathMappingError} = require('./lib/paths');
const {PausedBrowser} = require('./lib/capture');
const {PartialValue,toJSONSafe} = require('./lib/values');
module.exports = {
  XdebugError,ProtocolError,ConnectionClosed,CommandTimeout,
  Listener,Xdebug,Session,PathMapper,PathMappingError,PausedBrowser,PartialValue,toJSONSafe,
};
