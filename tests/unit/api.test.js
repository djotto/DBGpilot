const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,property,frame} = require('../support/peer');
const {ProtocolError,NAMESPACE} = require('../../lib/dbgp');
const tick = () => new Promise(resolve => setImmediate(resolve));
test('mapped breakpoints retain inventory through get, update, list and remove',async t => {
  const {session,socket} = harness(t,{session:{pathMappings:[{local:'/local/project',remote:'file:///app'}]}});
  const create = session.setBreakpoint('/local/project/src/a b.php',8,{hitValue:2,hitCondition:'>=',temporary:true});
  assert.equal(socket.commands[0].args.f,'file:///app/src/a%20b.php');
  socket.reply(0,'id="b"'); assert.equal(await create,'b');
  assert.equal(session.knownBreakpoints.b.localFile,'/local/project/src/a b.php');
  const point = '<breakpoint id="b" type="line" state="enabled" filename="file:///app/src/a%20b.php" lineno="8" hit_count="1"/>';
  const get = session.getBreakpoint('b'); socket.reply(1,'',point); assert.equal((await get).hitCount,1);
  const update = session.updateBreakpoint('b',{state:'disabled',line:9,hitValue:3,hitCondition:'%'});
  socket.reply(2); await update; assert.equal(session.knownBreakpoints.b.line,9);
  const copy = session.knownBreakpoints; copy.b.line = 999; assert.equal(session.knownBreakpoints.b.line,9);
  const list = session.breakpoints(); socket.reply(3,'',point); assert.equal((await list).length,1);
  const remove = session.removeBreakpoint('b'); socket.reply(4); await remove; assert.deepEqual(session.knownBreakpoints,{});
});
for (const options of [{kind:'watch'}, {kind:'call'}, {kind:'exception'}, {state:'bad'}, {hitValue:-1}, {hitCondition:'bad'}]) {
  test(`invalid breakpoint options fail before sending ${JSON.stringify(options)}`,async t => {
    const {session,socket} = harness(t); await assert.rejects(session.setBreakpoint('/app/a.php',1,options)); assert.equal(socket.commands.length,0);
  });
}
test('unmapped outgoing source fails explicitly without touching PHP',async t => {
  const {session,socket} = harness(t,{session:{pathMappings:[{local:'/local',remote:'file:///app'}]}});
  await assert.rejects(session.setBreakpoint('/elsewhere/a.php',8),/no local root/);
  await assert.rejects(session.source('/elsewhere/a.php'),/no local root/); assert.equal(socket.commands.length,0);
});
test('conditional scope, call and exception options reach the engine',async t => {
  const {session,socket} = harness(t);
  for (const [file,line,options] of [['/app/a.php',undefined,{condition:'$x > 2'}],[undefined,undefined,{kind:'call',function:'Foo::bar'}],[undefined,undefined,{kind:'exception',exception:'RuntimeException'}]]) {
    const creating = session.setBreakpoint(file,line,options); const index = socket.commands.length-1;
    socket.reply(index,`id="b${index}" state="enabled"`); await creating;
  }
  assert.equal(socket.commands[0].args.t,'conditional'); assert.equal(socket.commands[0].args.n,undefined);
  assert.equal(socket.commands[1].args.m,'Foo::bar'); assert.equal(socket.commands[2].args.x,'RuntimeException');
});
test('breakpoint metadata mismatches close and reject pending operations',async t => {
  const {session,socket,connection} = harness(t); const pending = assert.rejects(session.getBreakpoint('b'),ProtocolError);
  socket.reply(0,'','<breakpoint id="wrong" type="line" state="enabled"/>'); await pending; assert.equal(connection.closed,true);
});
test('resolved notifications update mapped inventory and preserve original engine filename',async t => {
  const {session,socket} = harness(t,{session:{pathMappings:[{local:'/local',remote:'file:///app'}]}});
  let notification; session.on('notification',value => notification = value);
  socket.emit('data',frame(`<notify xmlns="${NAMESPACE}" name="breakpoint_resolved"><breakpoint id="b" type="line" state="temporary" filename="file:///app/a.php" lineno="9"/><message filename="file:///app/error.php" lineno="10"/></notify>`));
  assert.equal(session.knownBreakpoints.b.localFile,'/local/a.php');
  assert.equal(notification.message.filename,'file:///app/error.php'); assert.equal(notification.message.localFile,'/local/error.php');
});
test('features distinguish unsupported from supported zero and return setting acknowledgements',async t => {
  const {session,socket} = harness(t); const feature = session.featureGet('supports_async');
  socket.reply(0,'supported="1"','0'); assert.deepEqual(await feature,{supported:true,value:'0',enabled:false});
  const set = session.featureSet('max_data',1024); socket.reply(1,'success="0"'); assert.equal(await set,false);
  const unsupported = session.featureGet('nope'); socket.reply(2,'supported="0"','1'); assert.equal((await unsupported).enabled,false);
});
for (const invalid of [undefined,'','oops','1.5','-1']) {
  test(`malformed context ID is a protocol error ${String(invalid)}`,async t => {
    const {session,socket} = harness(t); const contexts = assert.rejects(session.contexts({frame:3}),ProtocolError);
    assert.equal(socket.commands[0].args.d,'3');
    socket.reply(0,'',`<context name="Broken"${invalid === undefined ? '':` id="${invalid}"`}/>`); await contexts;
  });
}
test('empty, named and unnamed contexts preserve valid IDs',async t => {
  const {session,socket} = harness(t); const contexts = session.contexts();
  socket.reply(0,'','<context id="7" name="Globals"/><context id="0" name="Locals"/><context id="2"/>');
  assert.deepEqual(await contexts,{7:'Globals',0:'Locals',2:''});
  const empty = session.contexts(); socket.reply(1); assert.deepEqual(await empty,{});
  await assert.rejects(session.contexts({frame:'oops'}),TypeError); assert.equal(socket.commands.length,2);
});
test('type maps preserve common type separately from schema attributes',async t => {
  const {session,socket} = harness(t); const map = session.typeMap();
  socket.reply(0,'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"','<map type="hash" name="array" xsi:type="xsd:array"/>');
  assert.deepEqual((await map)[0],{name:'array',type:'hash',schemaType:'xsd:array',attributes:{name:'array',type:'hash','xsi:type':'xsd:array'}});
});
test('mapped stack, nested inputs and snapshot fallback preserve engine URIs',async t => {
  const {session,socket} = harness(t,{session:{pathMappings:[{local:'C:\\Site',remote:'file:///app'}]}});
  const frames = session.stack({frame:2}); assert.equal(socket.commands[0].args.d,'2');
  const xml = '<stack level="2" where="checkout" filename="file:///app/a.php" lineno="9"><input level="3" filename="file:///app/input.php" lineno="2"/></stack>';
  socket.reply(0,'',xml); const first = (await frames)[0];
  assert.equal(first.localFile,'C:\\Site\\a.php'); assert.equal(first.inputs[0].localFile,'C:\\Site\\input.php');
  const snapshot = session.snapshot(); socket.reply(1,'',xml);
  assert.equal((await snapshot).execution.fileUri,'file:///app/a.php');
  const unmapped = session.stack(); socket.reply(2,'','<stack level="0" filename="file:///vendor/x.php" lineno="1"/><stack level="1" filename="dbgp:eval-42" lineno="1"/>');
  const missing = await unmapped; assert.match(missing[0].pathMappingError,/no remote root/); assert.equal(missing[1].pathMappingError,undefined);
});
test('source URI and line ranges preserve bytes and virtual source IDs',async t => {
  const {session,socket} = harness(t,{session:{pathMappings:[{local:'/local',remote:'file:///app'}]}});
  const source = session.source('/local/a.php',{begin:1,end:2}); assert.equal(socket.commands[0].args.f,'file:///app/a.php');
  socket.reply(0,'encoding="base64"',Buffer.from([255,0,60]).toString('base64')); assert.deepEqual(await source,Buffer.from([255,0,60]));
  const virtual = session.source('dbgp:eval-42'); assert.equal(socket.commands[1].args.f,'dbgp:eval-42'); socket.reply(1); assert.deepEqual(await virtual,Buffer.alloc(0));
});
test('property pages, full bytes and assignment options are frame and address aware',async t => {
  const {session,socket} = harness(t); const page = session.getPropertyPage('$x',{frame:2,context:1,page:3,maxData:64,key:'k',address:'a'});
  assert.deepEqual(socket.commands[0].args,{i:'1',n:'$x',d:'2',c:'1',p:'3',m:'64',k:'k',a:'a'});
  socket.reply(0,'',property('abc',{page:'3',size:'10'})); assert.equal((await page).valueTruncated,true);
  const value = session.propertyValueInfo('$x',{frame:2,page:3,address:'a'});
  socket.reply(1,'encoding="base64" size="3" page="3"',Buffer.from([255,0,120]).toString('base64'));
  const bytes = await value; assert.deepEqual(bytes.data,Buffer.from([255,0,120])); assert.equal(bytes.truncated,false); assert.equal(bytes.address,'a');
  const set = session.setProperty('$x',Buffer.from([255,0]),{frame:2,type:'string',address:'a'});
  assert.equal(socket.commands[2].args.l,'2'); socket.reply(2,'success="1"'); assert.equal(await set,true);
});
test('Xdebug eval depth is rejected, while explicit result page is sent',async t => {
  const {session,socket} = harness(t); await assert.rejects(session.evaluate('$x',{frame:1}),/current frame/); assert.equal(socket.commands.length,0);
  const evaluated = session.evaluate('$x',{page:3}); assert.equal(socket.commands[0].args.p,'3'); socket.reply(0,'',property('42',{type:'int'})); assert.equal(await evaluated,42);
});
test('status, depth and output use validated scalar responses',async t => {
  const {session,socket} = harness(t); const status = session.status(); socket.reply(0,'status="break" reason="ok"'); assert.equal((await status).status,'break');
  const depth = session.stackDepth(); socket.reply(1,'depth="3"'); assert.equal(await depth,3);
  const output = session.setOutput('stdout',1); socket.reply(2,'success="1"'); assert.equal(await output,true);
  await assert.rejects(session.setOutput('stdin',1),TypeError);
});
test('stop reports an acknowledgement separately from permitted clean EOF',async t => {
  const acknowledged = harness(t); const stopping = acknowledged.session.stop();
  acknowledged.socket.reply(0,'status="stopped" reason="ok"'); assert.equal((await stopping).responseReceived,true);
  const eof = harness(t); const terminating = eof.session.stop(); eof.socket.emit('end');
  assert.deepEqual(await terminating,{status:'stopped',responseReceived:false});
  const truncated = harness(t); const failed = assert.rejects(truncated.session.stop(),ProtocolError);
  truncated.socket.emit('data',Buffer.from('20\0abc')); truncated.socket.emit('end'); await failed;
});
test('detach reports acknowledgement and shares bounded release with teardown',async t => {
  const {session,socket,connection} = harness(t); const detaching = session.detach();
  socket.reply(0,'status="stopped" reason="ok"'); assert.equal((await detaching).responseReceived,true);
  assert.equal(connection.closed,true); assert.equal((await session.release()).responseReceived,true);
});
for (const name of ['feature_get','feature_set','property_set']) {
  test(`malformed ${name} acknowledgement fails as a protocol error`,async t => {
    const {session,socket} = harness(t);
    const pending = assert.rejects(session.command(name,name.startsWith('feature') ? {n:'x',v:1}:{n:'$x'},name === 'property_set' ? '1':undefined),ProtocolError);
    socket.reply(0,'supported="bad" success="bad"'); await pending;
  });
}
