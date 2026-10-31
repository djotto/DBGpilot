const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Listener,Xdebug,CommandTimeout,ConnectionClosed} = require('../../core');
const {harness,parseCommand,property} = require('../support/peer');
const {waitFor} = require('../../lib/capture');
const tick = () => new Promise(resolve => setImmediate(resolve));
function deferred() {let resolve;const promise = new Promise(done => resolve = done);return {promise,resolve};}
function captureHarness(t,page = {route:async () => {},unroute:async () => {}}) {
  const listener = new Listener();
  const owner = listener.register(new Xdebug(undefined,'cleanup',1000));
  t.after(() => listener.close().catch(() => {}));
  const peer = harness(t);
  peer.socket.on('command',request => {
    const index = peer.socket.commands.indexOf(request);
    if (request.name === 'run') peer.socket.reply(index,'status="break"');
    if (request.name === 'stack_get') peer.socket.reply(index);
    if (request.name === 'detach') peer.socket.reply(index,'status="stopped"');
  });
  const action = async () => {
    const child = [...listener.owners.values()].filter(candidate => candidate !== owner).at(-1);
    child.offer(peer.session);return 'action complete';
  };
  return {...peer,listener,owner,page,action};
}

test('socket backpressure does not extend a command deadline or discard a late response',{timeout:1000},async t => {
  const {session,socket,connection} = harness(t);let callback;
  socket.write = (packet,done) => {socket.commands.push(parseCommand(packet));callback = done;return false;};
  await assert.rejects(session.run({timeout:10}),CommandTimeout);
  assert.equal(session.state,'running');assert.equal(connection.pendingCount,1);
  callback();assert.equal(session.state,'running');
  socket.reply(0,'status="break"');
  assert.equal(session.state,'break');assert.equal(connection.pendingCount,0);
});
test('a late write error closes the session and settles recovery waits',async t => {
  const {session,socket,connection} = harness(t);let callback;
  socket.write = (packet,done) => {socket.commands.push(parseCommand(packet));callback = done;return false;};
  await assert.rejects(session.run({timeout:5}),CommandTimeout);
  const pause = assert.rejects(session.waitForPause({timeout:500}),/Cannot write/);
  const event = session.nextEvent({timeout:500});
  callback(new Error('broken pipe'));await pause;
  assert.equal((await event).type,'closed');assert.equal(session.state,'stopped');assert.equal(connection.pendingCount,0);
});
for (const ending of ['end','error','close']) {
  test(`${ending} during execution settles the command, pause recovery and event waiter`,async t => {
    const {session,socket,connection} = harness(t);
    const run = assert.rejects(session.run({timeout:0}),ConnectionClosed);
    const pause = assert.rejects(session.waitForPause({timeout:0}),ConnectionClosed);
    const event = session.nextEvent({timeout:0});
    socket.emit(ending,...(ending === 'error' ? [new Error('disconnected')]:[]));
    await Promise.all([run,pause]);assert.equal((await event).type,'closed');
    assert.equal(connection.pendingCount,0);assert.equal(session.state,'stopped');
    assert.equal(session.listenerCount('stopped'),0);assert.equal(session.listenerCount('finished'),0);
  });
}
test('an earlier late run reply cannot clear execution started by its stop event',async t => {
  const {session,socket} = harness(t);
  await assert.rejects(session.run({timeout:5}),CommandTimeout);
  let following;
  session.once('stopped',() => {following = session.evaluate('$x');following.catch(() => {});});
  socket.reply(0,'status="break"');assert.equal(session.state,'running');
  await assert.rejects(session.locals(),/pending/);
  socket.reply(1,'',property('42',{type:'int'}));assert.equal(await following,42);assert.equal(session.state,'break');
});

test('capture deadline bounds a route installation that never completes',{timeout:1000},async t => {
  let removed = 0,acted = false;
  const {owner,listener,page} = captureHarness(t,{route:() => new Promise(() => {}),unroute:async () => {removed++;}});
  await assert.rejects(owner.capture(page,async () => {acted = true;},{urlPattern:'**/*',timeout:10}),/capture timed out/);
  assert.equal(acted,false);assert.equal(removed,1);assert.equal(listener.owners.size,1);assert.equal(owner.captureOperations.size,0);
});
test('a route that finishes installing after capture failure is removed without affecting a retry',async t => {
  const installing = deferred(),removing = deferred(),routes = new Set();let first = true,lateHandler;
  const page = {route:async (_pattern,handler) => {if (first) {first = false;lateHandler = handler;await installing.promise;}routes.add(handler);},
    unroute:async (_pattern,handler) => {if (handler === lateHandler && routes.has(handler)) await removing.promise;routes.delete(handler);}};
  const {owner,action,listener} = captureHarness(t,page);
  await assert.rejects(owner.capture(page,action,{urlPattern:'**/*',timeout:10}),/capture timed out/);
  const retry = await owner.capture(page,action,{urlPattern:'**/*'});
  installing.resolve();await tick();await tick();
  let fallback = false;
  await lateHandler({fallback:async () => {fallback = true;},continue:() => assert.fail('expired route must not modify a request')});
  assert.equal(fallback,true);removing.resolve();await tick();await tick();
  assert.equal(routes.size,1,'only the successful retry may retain a route');
  await retry.close();assert.equal(routes.size,0);assert.equal(listener.owners.size,1);
});
test('route cleanup preserves an original action error and records the secondary failure',async t => {
  const original = new Error('original action failure'),cleanup = new Error('browser unavailable');
  const {owner,page} = captureHarness(t,{route:async () => {},unroute:async () => {throw cleanup;}});
  await assert.rejects(owner.capture(page,async () => {throw original;},{urlPattern:'**/*'}),error => error === original && error.cleanupError === cleanup);
});
for (const original of [undefined,null,0,'action failed',Object.freeze(new Error('frozen action failure'))]) {
  test(`cleanup cannot replace an original ${String(original)} rejection`,async t => {
    const {owner,page} = captureHarness(t,{route:async () => {},unroute:async () => {throw new Error('cleanup failed');}});
    let caught = false;
    try {await owner.capture(page,async () => {throw original;},{urlPattern:'**/*'});}
    catch (error) {caught = true;assert.equal(error,original);}
    assert.equal(caught,true);
  });
}
test('child-disposal failure preserves the action error and still removes routing',async t => {
  let removed = 0;const original = new Error('action failed'),cleanup = new Error('child disposal failed');
  const {owner,page,listener} = captureHarness(t,{route:async () => {},unroute:async () => {removed++;}});
  const create = owner.createCaptureOwner.bind(owner);
  owner.createCaptureOwner = key => {const child = create(key);const dispose = child.dispose.bind(child);
    child.dispose = async () => {await dispose();throw cleanup;};return child;};
  await assert.rejects(owner.capture(page,async () => {throw original;},{urlPattern:'**/*'}),error => error === original && error.cleanupError === cleanup);
  assert.equal(removed,1);assert.equal(listener.owners.size,1);
});
test('abandoning a close wait does not cancel shared cleanup or detach twice',async t => {
  const {owner,page,action,session,socket} = captureHarness(t);const paused = await owner.capture(page,action,{urlPattern:'**/*'});
  const released = deferred(),entered = deferred(),release = session.release.bind(session);
  session.release = async () => {entered.resolve();await released.promise;return release();};
  const closing = paused.close();await entered.promise;
  const controller = new AbortController();const abandoned = assert.rejects(waitFor(closing,{signal:controller.signal}),/abandoned/);
  controller.abort(new Error('abandoned close wait'));await abandoned;
  assert.equal(owner.captures.has(paused),true);assert.equal(session.connection.closed,false);
  assert.equal(paused.close(),closing);released.resolve();await Promise.all([closing,owner.dispose()]);
  assert.equal(owner.captures.size,0);assert.equal(session.connection.closed,true);
  assert.equal(socket.commands.filter(command => command.name === 'detach').length,1);
});
test('owner disposal waits for every capture even when one cleanup fails',async t => {
  const {owner,page,action} = captureHarness(t);const first = await owner.capture(page,action,{urlPattern:'**/*'});
  const second = await owner.capture({...page},action,{urlPattern:'**/*'});
  const entered = deferred(),released = deferred(),failure = new Error('first cleanup failed');
  first.removeRoute = async () => {throw failure;};
  second.removeRoute = async () => {entered.resolve();await released.promise;};
  let settled = false;
  const disposing = owner.dispose().then(() => {settled = true;},error => {settled = true;throw error;});
  const rejected = assert.rejects(disposing,AggregateError);
  await entered.promise;await tick();const early = settled;
  released.resolve();await rejected;assert.equal(early,false);assert.equal(owner.captures.size,0);
});
test('paused close reports both disposal and route failures after attempting all cleanup',async t => {
  const childError = new Error('child cleanup failed'),routeError = new Error('route cleanup failed');
  const {owner,page,action,listener,session} = captureHarness(t,{route:async () => {},unroute:async () => {throw routeError;}});
  const paused = await owner.capture(page,action,{urlPattern:'**/*'}),dispose = paused.child.dispose.bind(paused.child);
  paused.child.dispose = async () => {await dispose();throw childError;};
  await assert.rejects(paused.close(),error => error instanceof AggregateError && error.errors[0] === childError && error.errors[1] === routeError);
  assert.equal(session.connection.closed,true);assert.equal(listener.owners.size,1);assert.equal(owner.captures.size,0);
});
