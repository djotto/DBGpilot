const {test} = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const {once} = require('node:events');
const {Listener,Xdebug,NAMESPACE} = require('../../core');
const {frame,response,parseCommand,harness} = require('../support/peer');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(t,options) {
  const listener = new Listener(options); await listener.listen(0,'127.0.0.1');
  t.after(() => listener.close()); return listener;
}
async function engine(t,listener,{idekey = 'test',method = 'GET',uri = '/checkout',holdEval = false,failFeature = false} = {}) {
  const socket = net.connect(listener.port,listener.host); t.after(() => socket.destroy());
  socket.on('error',() => {}); await once(socket,'connect');
  const commands = []; let buffer = Buffer.alloc(0); let seenEval;
  const evaluated = new Promise(resolve => seenEval = resolve);
  socket.on('data',chunk => {
    buffer = Buffer.concat([buffer,chunk]);
    for (;;) {
      const end = buffer.indexOf(0); if (end < 0) break;
      const request = parseCommand(buffer.subarray(0,end+1)); buffer = buffer.subarray(end+1);
      commands.push(request);
      if (request.name === 'feature_get') socket.write(frame(response(request,'supported="1"',request.args.n === 'breakpoint_types' ? 'line conditional exception call return':'0')));
      else if (request.name === 'feature_set') socket.write(frame(response(request,`success="${failFeature ? 0:1}"`)));
      else if (request.name === 'eval') {
        seenEval(request);
        if (!holdEval) socket.write(frame(response(request,'',`<property type="string" encoding="base64">${Buffer.from(method+' '+uri).toString('base64')}</property>`)));
      } else if (request.name === 'detach') socket.end(frame(response(request,'status="stopped"')));
    }
  });
  socket.write(frame(`<init xmlns="${NAMESPACE}" language="PHP" protocol_version="1.0" appid="123" fileuri="file:///app/index.php" idekey="${idekey}"/>`));
  return {socket,commands,evaluated};
}
function owner(t,listener,key = 'test',timeout = 1000) {
  const result = new Xdebug({addCookies:async () => {}},key,timeout);
  listener.owners.set(key,result); t.after(() => result.dispose()); return result;
}
test('shutdown closes a socket that has not initialized',async t => {
  const listener = await setup(t); const socket = net.connect(listener.port,listener.host);
  t.after(() => socket.destroy()); await once(socket,'connect'); await tick();
  const ended = once(socket,'close'); await listener.close(); await ended;
});
test('initialization deadline closes an idle peer and reports its error',async t => {
  const listener = await setup(t,{handshakeTimeout:20});
  const diagnostic = once(listener,'diagnostic'); const socket = net.connect(listener.port,listener.host);
  t.after(() => socket.destroy()); await once(socket,'connect'); const ended = once(socket,'close');
  assert.match((await diagnostic)[0].message,/initialization timed out/); await ended;
});
test('dispose owns preparation before its eval finishes',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const peer = await engine(t,listener,{holdEval:true}); await peer.evaluated;
  const ended = once(peer.socket,'close'); await xdebug.dispose(); await ended;
  assert.equal(xdebug.disposed,true);
  await assert.rejects(Promise.resolve().then(() => xdebug.waitForSession()),/disposed/);
});
test('session selection distinguishes method and ignores stateful RegExp cursors',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const post = xdebug.waitForSession({url:/checkout/g,method:'POST',timeout:1000});
  await engine(t,listener,{method:'GET'}); await engine(t,listener,{method:'POST'});
  const session = await post; assert.equal(session.request.method,'POST');
  const get = await xdebug.waitForSession({url:/checkout/g}); assert.equal(get.request.method,'GET');
});
test('unknown IDE keys detach without consuming an owner waiter',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const unknown = await engine(t,listener,{idekey:'unknown'}); await once(unknown.socket,'close');
  const waiting = xdebug.waitForSession({timeout:1000}); await engine(t,listener);
  assert.equal((await waiting).init.idekey,'test');
});
test('preparation failures reach the waiting test immediately',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const waiting = assert.rejects(xdebug.waitForSession({timeout:1000}),/did not accept feature/);
  await engine(t,listener,{failFeature:true}); await waiting;
});
test('aborted wait does not claim the next matching session',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener); const abort = new AbortController();
  const cancelled = assert.rejects(xdebug.waitForSession({signal:abort.signal}),/cancelled/);
  abort.abort(new Error('cancelled')); await cancelled;
  const next = xdebug.waitForSession({timeout:1000}); await engine(t,listener);
  assert.equal((await next).request.uri,'/checkout');
});
test('closed queued sessions are pruned',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const {session,connection} = harness(t); session.request.uri = '/closed';
  xdebug.offer(session); connection.close();
  await assert.rejects(xdebug.waitForSession({url:'/closed',timeout:10}),/No Xdebug session/);
});
test('all unclaimed requests are released and disposal is idempotent',async t => {
  const listener = await setup(t); owner(t,listener,'test',10);
  const peer = await engine(t,listener); await once(peer.socket,'close');
  assert(peer.commands.some(command => command.name === 'detach'));
  assert.equal(listener.close(),listener.close());
});
test('concurrent listener startup shares one bind and shutdown during bind leaves none',async t => {
  const listener = new Listener();t.after(() => listener.close());
  const first = listener.listen(0);assert.equal(first,listener.listen(0));await first;
  assert.equal(await listener.listen(0),listener);
  const closing = new Listener();const starting = closing.listen(0);const rejected = assert.rejects(starting,/closed during startup/);
  await closing.close();await rejected;await assert.rejects(closing.listen(0),/closed/);
});
test('connection admission rejects only new sockets and retains diagnostics',async t => {
  const listener = await setup(t,{maxSessions:1});
  const first = net.connect(listener.port,listener.host);t.after(() => first.destroy());await once(first,'connect');await tick();
  const diagnostic = once(listener,'diagnostic');const second = net.connect(listener.port,listener.host);t.after(() => second.destroy());
  await once(second,'connect');await once(second,'close');assert.match((await diagnostic)[0].message,/capacity/);
  assert.equal(first.destroyed,false);assert.match(listener.diagnostics[0].message,/capacity/);
});
