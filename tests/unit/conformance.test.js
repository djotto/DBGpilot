const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,frame,property,Socket,response} = require('../support/peer');
const {parsePacket,Connection,ProtocolError,encodeCommand,NAMESPACE} = require('../../core');
const {toValue} = require('../../lib/values');
test('mixed notification body excludes child metadata and preserves raw XML',async t => {
  const {session,socket} = harness(t); const encoded = Buffer.from('before\0after').toString('base64');
  socket.emit('data',frame(`<notify xmlns="${NAMESPACE}" xmlns:v="urn:vendor" name="error" encoding="base64">${encoded.slice(0,4)}<v:message filename="file:///a.php" lineno="9" v:extra="keep">child metadata</v:message>${encoded.slice(4)}</notify>`));
  const event = (await session.nextEvent()).data;
  assert.deepEqual(event.data,Buffer.from('before\0after')); assert.equal(event.message['v:extra'],'keep');
  assert(event.xml.includes('child metadata'));
});
test('abandoned eval errors restore the pause and retain vendor diagnostics',async t => {
  const {session,socket} = harness(t); session.state = 'break'; const abort = new AbortController();
  const evaluated = assert.rejects(session.evaluate('bad()',{signal:abort.signal}),/cancelled/);
  abort.abort(new Error('cancelled')); await evaluated;
  socket.reply(0,'xmlns:v="urn:vendor"','<error code="206" v:detail="keep"><v:message>invalid code</v:message><v:extra>extended details</v:extra></error>');
  assert.equal(session.state,'break'); assert.equal((await session.nextEvent()).type,'stopped');
  const failure = session.evaluate('bad()');
  const checked = assert.rejects(failure,error => error.code === 206 && error.attributes['v:detail'] === 'keep' && error.xml.includes('extended details'));
  socket.reply(1,'xmlns:v="urn:vendor"','<error code="206" v:detail="keep"><v:message>invalid code</v:message><v:extra>extended details</v:extra></error>');
  await checked; assert.equal(session.state,'break');
});
test('raw Xdebug byte-container XML names and command data do not transcode bytes',() => {
  const body = Buffer.concat([Buffer.from(`<?xml version="1.0" encoding="iso-8859-1"?><response xmlns="${NAMESPACE}" command="property_get" transaction_id="1"><property name="`),Buffer.from([255]),Buffer.from('" fullname="$x" type="string" encoding="base64">/wA=</property></response>')]);
  const node = parsePacket(body).node.property[0];
  assert.deepEqual(require('../../lib/values').parseProperty(node).name,Buffer.from([255]));
  assert.deepEqual(toValue(node),Buffer.from([255,0]));
  assert.equal(encodeCommand('eval',1,{},'raw-\udcff').toString(),'eval -i 1 -- cmF3Lf8=\0');
});
for (const type of ['int','float','bool']) {
  for (const value of ['', 'oops','0x12']) test(`reject malformed ${type} scalar ${JSON.stringify(value)}`,() => assert.throws(() => toValue({type,'#text':value}),ProtocolError));
}
test('non-ASCII XML encodings cannot bypass DTD rejection',() => {
  const xml = '<!DOCTYPE x [<!ENTITY y "hello">]><x/>';
  assert.throws(() => parsePacket(Buffer.from(xml,'utf16le')),ProtocolError);
});
test('late raw breakpoint replies still update the retained inventory',async t => {
  const {session,socket} = harness(t);
  await assert.rejects(session.command('breakpoint_set',{t:'line',f:'file:///app/a.php',n:1},undefined,10),/timed out/);
  socket.reply(0,'id="b"'); assert.equal(session.knownBreakpoints.b.line,1);
});
test('invalid breakpoint list does not commit a partial new inventory',async t => {
  const {session,socket} = harness(t); const create = session.setBreakpoint('/app/a.php',1);socket.reply(0,'id="old"');await create;
  const pending = assert.rejects(session.breakpoints(),ProtocolError);
  socket.reply(1,'','<breakpoint id="a" type="line" state="enabled"/><breakpoint id="a" type="line" state="enabled"/>');await pending;
  assert.equal(session.knownBreakpoints.old.id,'old'); assert.equal(session.knownBreakpoints.a,undefined);
});
test('supported postmortem inspection does not permit another continuation',async t => {
  const {session,socket} = harness(t);const feature = session.featureGet('supports_postmortem');socket.reply(0,'supported="1"','1');await feature;
  const run = session.run();socket.reply(1,'status="stopping"');await run;
  const get = session.getVariable('$x');socket.reply(2,'',property('42',{type:'int'}));assert.equal(await get,42);
  await assert.rejects(session.run(),/Cannot run/);assert.equal(socket.commands.length,3);
});
test('out-of-order nonexecuting transport replies remain independently correlated',async t => {
  const socket = new Socket();const connection = new Connection(socket);t.after(() => connection.close());
  const first = connection.send('stack_depth'), second = connection.send('status');
  socket.reply(1,'status="starting"');socket.reply(0,'depth="3"');
  assert.equal((await first).depth,'3');assert.equal((await second).status,'starting');
});
test('empty arrays remain arrays after an engine hash type map is loaded',async t => {
  const {session,socket} = harness(t);const mapping = session.typeMap();socket.reply(0,'','<map name="array" type="hash"/>');await mapping;
  const array = session.getVariable('$a');socket.reply(1,'','<property name="$a" fullname="$a" type="array" numchildren="0"/>');assert.deepEqual(await array,[]);
  const string = session.getVariable('$s');socket.reply(2,'',property(''));assert.equal(await string,'');
});
test('child expressions override attribute expressions and optional breakpoint metadata defaults',async t => {
  const {session,socket} = harness(t);const pending = session.getBreakpoint('b');
  socket.reply(0,'','<breakpoint id="b" expression="old"><expression encoding="base64">bmV3</expression></breakpoint>');
  const point = await pending;assert.equal(point.expression,'new');assert.equal(point.type,'line');assert.equal(point.state,'enabled');
});
