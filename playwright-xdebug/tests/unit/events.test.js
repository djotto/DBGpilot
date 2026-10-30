const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,frame,property} = require('../support/peer');
const {ProtocolError,NAMESPACE} = require('../../core');
test('cancelled execution retains PHP ownership and publishes the real later stop',async t => {
  const {session,socket} = harness(t); const abort = new AbortController();
  const running = assert.rejects(session.run({signal:abort.signal}),/cancelled/);
  abort.abort(new Error('cancelled')); await running; assert.equal(session.state,'running');
  await assert.rejects(session.evaluate('1'),/pending/);
  socket.reply(0,'status="break"'); assert.equal(session.state,'break');
  assert.equal((await session.nextEvent()).type,'stopped');
  const read = session.getVariable('$x'); socket.reply(1,'',property('42',{type:'int'})); assert.equal(await read,42);
});
test('cancel before sending does not change engine state or write a command',async t => {
  const {session,socket} = harness(t); const abort = new AbortController(); abort.abort(new Error('cancelled'));
  await assert.rejects(session.run({signal:abort.signal}),/cancelled/); assert.equal(session.state,'starting'); assert.equal(socket.commands.length,0);
});
test('cancelled and timed-out event waits do not consume future events',async t => {
  const {session,socket} = harness(t); const abort = new AbortController();
  const waiting = assert.rejects(session.nextEvent({signal:abort.signal}),/cancelled/); abort.abort(new Error('cancelled')); await waiting;
  await assert.rejects(session.nextEvent({timeout:10}),/timed out/);
  socket.emit('data',frame(`<notify xmlns="${NAMESPACE}" name="later"/>`));
  assert.equal((await session.nextEvent()).data.name,'later');
});
test('on-time evals do not duplicate stop events or overflow a small queue',async t => {
  const {session,socket} = harness(t,{session:{maxEvents:1}}); session.state = 'break';
  for (let i=0;i<20;i++) {
    const evaluated = session.evaluate('1'); socket.reply(i,'',property('1',{type:'int'})); await evaluated;
  }
  assert.equal(session.connection.closed,false); await assert.rejects(session.nextEvent({timeout:10}),/timed out/);
});
test('event overflow closes the connection and reports its terminal error',async t => {
  const {session,socket} = harness(t,{session:{maxEvents:1}}); const pending = assert.rejects(session.run(),ProtocolError);
  for (const name of ['one','two']) socket.emit('data',frame(`<notify xmlns="${NAMESPACE}" name="${name}"/>`));
  await pending; assert.equal((await session.nextEvent()).data.name,'one');
  const terminal = await session.nextEvent(); assert.equal(terminal.type,'closed'); assert.match(terminal.error.message,/overflow/);
});
test('binary stream events remain independent of command responses',async t => {
  const {session,socket} = harness(t); const running = session.run();
  socket.emit('data',frame(`<stream xmlns="${NAMESPACE}" type="stdout" encoding="base64">/wA=</stream>`));
  const event = await session.nextEvent(); assert.equal(event.type,'stream'); assert.deepEqual(event.data.data,Buffer.from([255,0]));
  assert.equal(session.state,'running'); socket.reply(0,'status="break"'); await running;
});
