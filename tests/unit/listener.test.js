const {test} = require('node:test');
const assert = require('node:assert/strict');
const net = require('node:net');
const {once} = require('node:events');
const {Listener,Xdebug,Session,NAMESPACE} = require('../../core');
const {frame,response,parseCommand,harness} = require('../support/peer');
const tick = () => new Promise(resolve => setImmediate(resolve));

async function setup(t,options) {
  const listener = new Listener(options); await listener.listen(0,'127.0.0.1');
  t.after(() => listener.close()); return listener;
}
async function engine(t,listener,{idekey = 'test',method = 'GET',uri = '/checkout',holdEval = false,failFeature = false,disconnectAt} = {}) {
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
      if (request.name === disconnectAt) {socket.destroy();return;}
      if (request.name === 'feature_get') {
        const values = {encoding:failFeature ? 'ASCII':'UTF-8',data_encoding:'base64',supports_async:'0',supports_postmortem:'0',breakpoint_types:'line conditional exception call return'};
        socket.write(frame(response(request,'supported="1"',values[request.args.n] ?? '1')));
      }
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
test('encoding negotiation failures reach the waiter and the listener accepts the next engine',async t => {
  const listener = await setup(t); const xdebug = owner(t,listener);
  const waiting = assert.rejects(xdebug.waitForSession({timeout:1000}),/must support UTF-8/);
  const failed = await engine(t,listener,{failFeature:true});
  const closed = once(failed.socket,'close');
  await waiting;await closed;
  assert.equal(failed.commands.some(command => command.name === 'eval'),false);
  const next = xdebug.waitForSession({timeout:1000});
  await engine(t,listener);
  assert.equal((await next).supportsCommand('eval'),true);
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
for (const disconnectAt of ['feature_get','eval']) {
  test(`disconnect during ${disconnectAt} preparation reaches the waiter and permits the next request`,async t => {
    const listener = await setup(t),xdebug = owner(t,listener);
    const failed = assert.rejects(xdebug.waitForSession({timeout:1000}),/connection (?:ended|closed)/i);
    await engine(t,listener,{disconnectAt});await failed;
    const following = xdebug.waitForSession({timeout:1000});await engine(t,listener);
    assert.equal((await following).request.uri,'/checkout');
  });
}
test('listener shutdown closes idle sockets and waits for other owners after a cleanup failure',async t => {
  const listener = new Listener();await listener.listen(0);
  t.after(() => listener.close().catch(() => {}));
  let release;const gate = new Promise(resolve => release = resolve);
  listener.register({ideKey:'failed',dispose:async () => {throw new Error('owner cleanup failed');}});
  listener.register({ideKey:'delayed',dispose:async () => gate});
  const socket = net.connect(listener.port,listener.host);t.after(() => socket.destroy());await once(socket,'connect');await tick();
  const closed = once(socket,'close');let settled = false;
  const closing = listener.close().finally(() => {settled = true;});const rejected = assert.rejects(closing,AggregateError);
  await tick();const early = settled;release();await rejected;await closed;
  assert.equal(early,false);assert.equal(listener.owners.size,0);
  const replacement = new Listener();t.after(() => replacement.close());await replacement.listen(listener.port,listener.host);
});
test('failed preparation cleanup closes the socket, reports both failures and leaves the listener usable',async t => {
  const listener = await setup(t),xdebug = owner(t,listener),prepare = Session.prototype.prepare;
  const original = new Error('preparation failed'),cleanup = new Error('release failed');
  const diagnosed = new Promise(resolve => listener.on('diagnostic',error => {if (error === cleanup) resolve();}));
  Session.prototype.prepare = async function () {this.release = async () => {throw cleanup;};throw original;};
  try {
    const waiting = assert.rejects(xdebug.waitForSession({timeout:1000}),error => error === original);
    const peer = await engine(t,listener),closed = once(peer.socket,'close');
    await waiting;await diagnosed;await closed;
    assert(listener.diagnostics.some(error => error.message === original.message));
    assert(listener.diagnostics.some(error => error.message === cleanup.message));
  } finally {Session.prototype.prepare = prepare;}
  const following = xdebug.waitForSession({timeout:1000});await engine(t,listener);
  assert.equal((await following).request.uri,'/checkout');
});
test('an occupied port cannot attach to or close the existing listener',async t => {
  const existing = await setup(t),contender = new Listener();t.after(() => contender.close());
  await assert.rejects(contender.listen(existing.port,existing.host),/in use/);await contender.close();
  const xdebug = owner(t,existing),waiting = xdebug.waitForSession({timeout:1000});await engine(t,existing);
  assert.equal((await waiting).request.uri,'/checkout');
});
test('rejected-handshake diagnostics remain bounded and the next valid engine still connects',async t => {
  const listener = await setup(t),xdebug = owner(t,listener);
  for (let i=0;i<55;i++) {
    const socket = net.connect(listener.port,listener.host);await once(socket,'connect');
    const closed = once(socket,'close');socket.write(frame(`<response xmlns="${NAMESPACE}" command="status" transaction_id="1"/>`));await closed;
  }
  assert.equal(listener.diagnostics.length,50);
  const waiting = xdebug.waitForSession({timeout:1000});await engine(t,listener);assert.equal((await waiting).init.idekey,'test');
});
test('a timed-out session waiter does not claim the next PHP request',async t => {
  const listener = await setup(t),xdebug = owner(t,listener);
  await assert.rejects(xdebug.waitForSession({timeout:5}),/No Xdebug session/);
  const following = xdebug.waitForSession({timeout:1000});await engine(t,listener);
  assert.equal((await following).request.uri,'/checkout');
});
test('multiple waiters on the same owner claim distinct sessions',async t => {
  const listener = await setup(t),xdebug = owner(t,listener);
  const waiting = [xdebug.waitForSession({timeout:1000}),xdebug.waitForSession({timeout:1000})];
  await engine(t,listener);await engine(t,listener);
  const sessions = await Promise.all(waiting);assert.equal(new Set(sessions.map(session => session.id)).size,2);
});
