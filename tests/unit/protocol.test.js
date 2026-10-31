const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Connection,ProtocolError,CommandTimeout,encodeCommand,parsePacket,NAMESPACE} = require('../../lib/dbgp');
const {Socket,frame,response,property} = require('../support/peer');

test('fragmented/coalesced packets preserve binary payload and byte framing',async t => {
  const socket = new Socket(); const connection = new Connection(socket);
  t.after(() => connection.close());
  const first = connection.send('eval',{},Buffer.from([255,0,120]));
  const second = connection.send('status');
  const data = Buffer.from(Array.from({length:256},(_,i) => i));
  const packet = Buffer.concat([
    frame(response(socket.commands[0],'',property(data))),
    frame(response(socket.commands[1],'status="break"')),
  ]);
  for (const byte of packet) socket.emit('data',Buffer.from([byte]));
  assert.deepEqual(Buffer.from((await first).property[0]['#text'],'base64'),data);
  assert.equal((await second).status,'break');
  assert.deepEqual(socket.commands[0].data,Buffer.from([255,0,120]));
});

for (const header of ['', '0','-1','abc','99999999999','99999','1.5']) {
  test(`reject invalid/oversize length ${JSON.stringify(header)}`,async t => {
    const socket = new Socket(); const connection = new Connection(socket,{maxPacketSize:1024});
    t.after(() => connection.close());
    const result = assert.rejects(connection.send('status'),ProtocolError);
    socket.emit('data',Buffer.from(`${header}\0`));
    await result; assert.equal(connection.closed,true);
  });
}
for (const xml of ['<broken','<response/>','<response xmlns="wrong"/>','<!DOCTYPE x [<!ENTITY y "hello">]><x/>']) {
  test(`reject malformed XML or namespace: ${xml}`,() => assert.throws(() => parsePacket(Buffer.from(xml)),ProtocolError));
}
test('prefixes and whitespace survive XML decoding',() => {
  const packet = parsePacket(Buffer.from(`<d:response xmlns:d="${NAMESPACE}" command="eval" transaction_id="1"><d:property type="string">  é🙂  </d:property></d:response>`));
  assert.equal(packet.node.property[0]['#text'],'  é🙂  ');
});
test('duplicate initialization closes the transport',() => {
  const socket = new Socket(); const connection = new Connection(socket);
  const init = frame(`<init xmlns="${NAMESPACE}"/>`);
  socket.emit('data',Buffer.concat([init,init]));
  assert.equal(connection.closed,true); assert.match(connection.error.message,/Duplicate/);
});
for (const mutation of ['terminator','command','transaction']) {
  test(`reject response ${mutation} mismatch`,async t => {
    const socket = new Socket(); const connection = new Connection(socket); t.after(() => connection.close());
    const pending = assert.rejects(connection.send('status'),ProtocolError);
    let xml = response(socket.commands[0]);
    if (mutation === 'command') xml = xml.replace('command="status"','command="eval"');
    if (mutation === 'transaction') xml = xml.replace('transaction_id="1"','transaction_id="99"');
    socket.emit('data',frame(xml,mutation === 'terminator' ? 88 : 0));
    await pending;
  });
}
test('truncated frame EOF rejects pending commands',async () => {
  const socket = new Socket(); const connection = new Connection(socket);
  const pending = assert.rejects(connection.send('status'),ProtocolError);
  socket.emit('data',Buffer.from('20\0abc')); socket.emit('end'); await pending;
});
test('timed-out transactions remain bounded and late replies are published',async t => {
  const socket = new Socket(); const connection = new Connection(socket,{maxPendingCommands:1}); t.after(() => connection.close());
  await assert.rejects(connection.send('run',{},undefined,10),CommandTimeout);
  assert.equal(connection.pendingCount,1);
  assert.throws(() => connection.send('status'),/limit/);
  let late; connection.on('response',(_node,meta) => late = meta);
  socket.reply(0,'status="break"');
  assert.equal(late.abandoned,true); assert.equal(connection.pendingCount,0);
});
for (const [name,args] of [['bad name',{}],['status',{i:9}],['status',{long:1}]]) {
  test(`reject command injection ${name} ${JSON.stringify(args)}`,() => assert.throws(() => encodeCommand(name,1,args),TypeError));
}
test('argument escaping preserves Unicode, binary bytes and empty data',() => {
  assert.equal(encodeCommand('property_get',1,{n:'$a["a\\b\0 é"]'}).toString(),
    'property_get -i 1 -n "$a[\\"a\\\\b\\0 é\\"]"\0');
  const encoded = encodeCommand('eval',2,{},Buffer.alloc(0));
  assert.equal(encoded.toString(),'eval -i 2 -- \0');
  assert(encodeCommand('property_get',1,{n:Buffer.from([255,32,0])}).includes(Buffer.from([255])));
});
test('stream and notification packets do not settle an unrelated command',async t => {
  const socket = new Socket(); const connection = new Connection(socket); t.after(() => connection.close());
  const pending = connection.send('status'); const events = [];
  connection.on('stream',node => events.push(node.type)); connection.on('notify',node => events.push(node.name));
  socket.emit('data',Buffer.concat([frame(`<stream xmlns="${NAMESPACE}" type="stdout">x</stream>`),frame(`<notify xmlns="${NAMESPACE}" name="error"/>`)]));
  assert.equal(connection.pendingCount,1); socket.reply(0,'status="break"'); await pending;
  assert.deepEqual(events,['stdout','error']);
});
