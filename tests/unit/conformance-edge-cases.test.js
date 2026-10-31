// Protocol, PHP value and validation edge cases.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,Socket,frame,parseCommand,property} = require('../support/peer');
const {PathMapper,PathMappingError,ProtocolError,XdebugError,CommandTimeout,toJSONSafe} = require('../../core');
const {Connection,NAMESPACE,encodeCommand,parsePacket} = require('../../lib/dbgp');
const {Session} = require('../../lib/session');
const {bytes,parseProperty,toValue} = require('../../lib/values');
const {encodeBytes,decodeBytes} = require('../../lib/encoding');
function random(seed) {
  return () => {seed ^= seed << 13;seed ^= seed >>> 17;seed ^= seed << 5;return seed >>> 0;};
}
test('seeded binary streams survive arbitrary packet fragmentation and coalescing',t => {
  const next = random(0xdb6031);
  for (let sample=0;sample<50;sample++) {
    const socket = new Socket(),connection = new Connection(socket);t.after(() => connection.close());
    const payload = Buffer.from(Array.from({length:sample === 0 ? 0:next()%4097},() => next()&255));
    const command = encodeCommand('eval',1,{},payload);
    assert.deepEqual(parseCommand(command).data,payload);
    assert(!command.includes(10) && !command.includes(13),'base64 command data cannot contain wrapped lines');
    const received = [];connection.on('stream',node => received.push(bytes(node)));
    const stream = frame(`<stream xmlns="${NAMESPACE}" type="stdout" encoding="base64">${payload.toString('base64')}</stream>`);
    const combined = Buffer.concat([stream,stream]);
    for (let offset=0;offset<combined.length;) {
      const end = Math.min(combined.length,offset+1+next()%97);
      socket.emit('data',combined.subarray(offset,end));offset = end;
    }
    assert.equal(connection.closed,false,`sample ${sample}`);assert.deepEqual(received,[payload,payload],`sample ${sample}`);
  }
});
test('seeded PHP strings and very large integers preserve bytes and JSON fidelity',() => {
  const next = random(0xb17e);
  for (let sample=0;sample<80;sample++) {
    const data = sample%4 === 0 ? Buffer.from(`  café🙂\0${sample}  `):Buffer.from(Array.from({length:next()%4097},() => next()&255));
    const parsed = parseProperty({type:'string',encoding:'base64',size:String(data.length),'#text':data.toString('base64')});
    assert.deepEqual(parsed.rawValue,data);assert.equal(parsed.valueTruncated,false);
    assert.deepEqual(Buffer.isBuffer(parsed.value) ? parsed.value:Buffer.from(parsed.value),data);
    assert.doesNotThrow(() => JSON.stringify(toJSONSafe(parsed)));
    const big = BigInt('0x'+Buffer.from(Array.from({length:64},() => next()&255)).toString('hex'))*(sample%2 ? -1n:1n);
    const value = toValue({type:'int','#text':String(big)});assert.equal(BigInt(value),big);
    assert.equal(typeof value === 'bigint' ? toJSONSafe(value).value:String(value),String(big));
  }
  for (const big of [0n,2n**512n,-(2n**512n)]) assert.equal(BigInt(toValue({type:'int','#text':String(big)})),big);
});
test('UTF-8 split inside multibyte characters survives byte framing and adjacent packets',t => {
  const {socket,connection} = harness(t),received = [];
  connection.on('notify',node => received.push(node['#text']));connection.on('stream',node => received.push(bytes(node).toString()));
  const data = Buffer.concat([frame(`<notify xmlns="${NAMESPACE}" name="example">é£🙂</notify>`),frame(`<stream xmlns="${NAMESPACE}" type="stdout">café🙂</stream>`)]);
  for (const byte of data) socket.emit('data',Buffer.from([byte]));
  assert.deepEqual(received,['é£🙂','café🙂']);
});
test('filesystem symlinks remain lexical and their targets require an explicit mapping',t => {
  const fs = require('node:fs'),os = require('node:os'),path = require('node:path');
  const temp = fs.mkdtempSync(path.join(os.tmpdir(),'dbgpilot-audit-paths-'));t.after(() => fs.rmSync(temp,{recursive:true,force:true}));
  const work = path.join(temp,'work'),real = path.join(temp,'real');fs.mkdirSync(work);fs.mkdirSync(real);fs.symlinkSync(real,path.join(work,'link'),'dir');
  const mapper = new PathMapper([{local:work,remote:'file:///app'}]);
  assert.equal(mapper.toRemote(path.join(work,'link','file.php')),'file:///app/link/file.php');
  assert.throws(() => mapper.toRemote(path.join(real,'file.php')),PathMappingError);
  assert.equal(mapper.withOverrides([{local:real,remote:'file:///real'}]).toRemote(path.join(real,'file.php')),'file:///real/file.php');
});
for (const extended of [false,true]) for (const mapped of [false,true]) {
  test(`empty and nested containers preserve scalar distinctions (extended=${extended}, typemap=${mapped})`,() => {
    const name = extended ? {encoding:'base64','#text':Buffer.from('$value').toString('base64')}:'$value';
    const array = {name,fullname:name,type:'array',children:'0',numchildren:'0'};
    const string = {name,fullname:name,type:'string',size:'0',...(extended ? {value:{encoding:'base64','#text':''}}:{encoding:'base64','#text':''})};
    const types = mapped ? new Map([['array',{type:'hash'}],['string',{type:'string'}]]):undefined;
    const a = parseProperty(array,types),s = parseProperty(string,types);
    assert.equal(a.name,'$value');assert.equal(a.fullname,'$value');assert.equal(a.value,null);assert.equal(a.rawValue,undefined);
    assert.deepEqual(a.children,[]);assert.equal(a.hasChildren,false);assert.equal(a.childrenTruncated,false);assert.deepEqual(toValue(array,types),[]);
    assert.equal(s.name,'$value');assert.equal(s.value,'');assert.deepEqual(s.rawValue,Buffer.alloc(0));
    const nested = parseProperty({type:'array',numchildren:'2',property:[array,string]},types);
    assert.equal(nested.value,null);assert.equal(nested.children[0].value,null);assert.equal(nested.children[1].value,'');
  });
}
for (const [type,input,expected] of [['bool','0',false],['bool','1',true],['null','',null],['uninitialized','',undefined],['float','1.25',1.25]]) {
  test(`scalar ${type} ${input} retains its JS and JSON representation`,() => {
    assert.equal(toValue({type,'#text':input}),expected);assert.doesNotThrow(() => JSON.stringify(toJSONSafe(expected)));
  });
}
for (const attribute of ['size','numchildren','page','pagesize']) {
  test(`negative ${attribute} metadata is rejected`,() => assert.throws(() => parseProperty({type:'string','#text':'value',[attribute]:'-1'}),ProtocolError));
}
test('extended class, child names, facets, paging and binary values retain structured metadata',() => {
  const encoded = value => ({encoding:'base64','#text':Buffer.from(value).toString('base64')});
  const p = parseProperty({type:'object',classname:encoded('Example'),numchildren:'50',page:'1',pagesize:'10',
    property:[{name:encoded('a\0b'),fullname:encoded('$obj["a\\0b"]'),type:'string',value:encoded(Buffer.from([255,0])),size:'2',facet:'private static',constant:'1',key:'opaque',address:'0x123'}]});
  assert.equal(p.classname,'Example');assert.equal(p.childrenTruncated,true);assert.equal(p.page,1);assert.equal(p.pageSize,10);
  const child = p.children[0];assert.equal(child.name,'a\0b');assert.deepEqual(child.value,Buffer.from([255,0]));
  assert.deepEqual(child.facets,['private','static']);assert.equal(child.constant,true);assert.equal(child.key,'opaque');assert.equal(child.address,'0x123');
  assert.equal(toJSONSafe(p).children[0].value.data,'/wA=');
});
test('evaluation interleaves events while rejecting overlapping inspection and execution',async t => {
  const {session,socket} = harness(t);session.state = 'break';
  const evaluation = session.evaluate('$x');
  for (const call of [() => session.run(),() => session.stack(),() => session.locals()]) await assert.rejects(call(),/pending/);
  socket.emit('data',Buffer.concat([frame(`<stream xmlns="${NAMESPACE}" type="stdout" encoding="base64">/wA=</stream>`),frame(`<notify xmlns="${NAMESPACE}" name="example"/>`)]));
  assert.equal((await session.nextEvent()).type,'stream');assert.equal((await session.nextEvent()).type,'notification');
  assert.equal(session.state,'running');socket.reply(0,'',property('7',{type:'int'}));assert.equal(await evaluation,7);assert.equal(session.state,'break');
});
for (const raw of [Buffer.from("'hello'"),Buffer.from("'café'"),Buffer.from([39,255,0,128,39])]) for (const asText of [false,true]) {
  test(`binary eval and assignment preserve bytes (${raw.toString('hex')}, text=${asText})`,async t => {
    const {session,socket} = harness(t);session.state = 'break';const input = asText ? decodeBytes(raw):raw;
    assert.deepEqual(encodeBytes(decodeBytes(raw)),raw);
    const evaluating = session.evaluate(input,{page:3});assert.deepEqual(socket.commands[0].data,raw);assert.equal(socket.commands[0].args.p,'3');
    socket.reply(0,'',property('ok'));assert.equal(await evaluating,'ok');
    const setting = session.setProperty('$x',input,{frame:2,context:1,type:'string',address:'0xabc'});
    assert.deepEqual(socket.commands[1].data,raw);assert.deepEqual(socket.commands[1].args,{i:'2',n:'$x',d:'2',c:'1',t:'string',a:'0xabc',l:String(raw.length)});
    socket.reply(1,'success="1"');assert.equal(await setting,true);assert.equal(session.state,'break');
  });
}
test('raw engine errors preserve a paused session for subsequent commands',async t => {
  const {session,socket,connection} = harness(t);session.state = 'break';
  const bad = assert.rejects(session.command('unknown'),error => error instanceof XdebugError && error.command === 'unknown' && error.code === 4);
  socket.reply(0,'','<error code="4"><message>not implemented</message></error>');await bad;
  assert.equal(connection.closed,false);const next = session.status();socket.reply(1,'status="break"');assert.equal((await next).status,'break');
});
for (const ending of ['partial_header','partial_body','malformed','error']) {
  test(`stop rejects ${ending} instead of claiming successful termination`,async t => {
    const {session,socket,connection} = harness(t);const failed = assert.rejects(session.stop(),ending === 'error' ? XdebugError:ProtocolError);
    if (ending === 'error') socket.reply(0,'','<error code="5"><message>unavailable</message></error>');
    else {
      socket.emit('data',ending === 'partial_header' ? Buffer.from('12'):ending === 'partial_body' ? Buffer.from('12\0<res'):Buffer.from('1\0<\0'));
      socket.emit('end');
    }
    await failed;assert.equal(connection.closed,true);
  });
}
for (const command of ['breakpoint_update','breakpoint_remove']) {
  test(`late ${command} acknowledgements update the inventory`,async t => {
    const {session,socket} = harness(t);const create = session.setBreakpoint('/a.php',3);socket.reply(0,'id="point"');await create;
    await assert.rejects(session.command(command,{d:'point',s:'disabled',n:5},undefined,5),CommandTimeout);
    socket.reply(1);
    if (command === 'breakpoint_update') {assert.equal(session.knownBreakpoints.point.state,'disabled');assert.equal(session.knownBreakpoints.point.line,5);}
    else assert.equal(session.knownBreakpoints.point,undefined);
  });
}
test('init vendor/relationship metadata and continuation breakpoint details remain JSON safe',async t => {
  const init = parsePacket(Buffer.from(`<init xmlns="${NAMESPACE}" xmlns:v="urn:vendor" language="PHP" protocol_version="1.0" appid="123" idekey="test" fileuri="file:///app.php" session="cookie" thread="t" parent="p" proxied="192.0.2.1" extra="kept"><engine version="3.5.3">Xdebug</engine><v:custom secret="kept"/></init>`)).node;
  const socket = new Socket(),connection = new Connection(socket),session = new Session(connection,init);t.after(() => connection.close());
  for (const key of ['session','thread','parent','proxied','extra']) assert.equal(session.info[key],init[key]);
  assert.equal(session.info.engine['#text'],'Xdebug');assert.equal(session.info.engine.version,'3.5.3');assert(session.info.xml.includes('secret="kept"'));
  const run = session.run();socket.reply(0,'status="break"','<breakpoint id="opaque" type="call" function="work" hit_count="2"/>');
  const result = await run;assert.equal(result.breakpoint.id,'opaque');assert.equal(result.breakpoint.hitCount,2);assert.doesNotThrow(() => JSON.stringify(toJSONSafe(result)));
});
for (const params of [{variables:'$x'},{variables:[1]},{expressions:[1]},{depth:true},{depth:0},{context:-1}]) {
  test(`invalid snapshot options fail before reaching PHP: ${JSON.stringify(params)}`,async t => {
    const {session,socket} = harness(t);
    socket.on('command',() => socket.emit('end'));
    await assert.rejects(session.snapshot(params),TypeError);assert.equal(socket.commands.length,0);
  });
}
for (const depth of [undefined,'-1','oops','1.5']) {
  test(`invalid engine stack depth is rejected: ${depth}`,async t => {
    const {session,socket} = harness(t);const checked = assert.rejects(session.stackDepth(),ProtocolError);
    socket.reply(0,depth === undefined ? '':`depth="${depth}"`);await checked;
  });
}
test('missing status and type-map fields fail explicitly',async t => {
  const first = harness(t),second = harness(t);
  const status = assert.rejects(first.session.status(),ProtocolError);first.socket.reply(0);await status;
  const types = assert.rejects(second.session.typeMap(),ProtocolError);second.socket.reply(0,'','<map name="broken"/>');await types;
});
for (const kind of ['line','conditional','call','return','exception','watch']) {
  test(`${kind} breakpoint creation preserves disabled state and targeting options`,async t => {
    const {session,socket} = harness(t);
    const creating = session.setBreakpoint('/app.php',5,{kind,condition:['conditional','watch'].includes(kind) ? Buffer.from('$x > 1'):undefined,function:'work',exception:'Example',
      state:'disabled',temporary:true,hitValue:3,hitCondition:'=='});
    const request = socket.commands[0];assert.equal(request.args.t,kind);assert.equal(request.args.s,'disabled');
    assert.equal(request.args.m,'work');assert.equal(request.args.x,'Example');assert.equal(request.args.h,'3');assert.equal(request.args.o,'==');
    socket.reply(0,'id="opaque" state="disabled"');assert.equal(await creating,'opaque');assert.equal(session.knownBreakpoints.opaque.temporary,true);
  });
}
for (const state of ['unresolved','vendor-state']) {
  test(`engine-specific breakpoint state ${state} is preserved`,async t => {
    const {session,socket} = harness(t);const reading = session.getBreakpoint('p');socket.reply(0,'',`<breakpoint id="p" state="${state}"/>`);
    assert.equal((await reading).state,state);
  });
}
test('an empty breakpoint ID never commits a partially valid replacement inventory',async t => {
  const {session,socket} = harness(t);const creating = session.setBreakpoint('/app.php',1);socket.reply(0,'id="old"');await creating;
  const listing = assert.rejects(session.breakpoints(),ProtocolError);socket.reply(1,'','<breakpoint id="valid"/><breakpoint id=""/>');await listing;
  assert.equal(session.knownBreakpoints.old.id,'old');assert.equal(session.knownBreakpoints.valid,undefined);
});
for (const supported of [false,true]) for (const method of ['source','contexts','typeMap']) {
  test(`postmortem ${method} reports the engine response (support=${supported})`,async t => {
    const {session,socket} = harness(t);const feature = session.featureGet('supports_postmortem');socket.reply(0,'supported="1"',supported ? '1':'0');await feature;
    const running = session.run();socket.reply(1,'status="stopping"');await running;
    if (!supported) {
      const pending = assert.rejects(session[method](),error => error instanceof XdebugError && error.code === 5);
      socket.reply(2,'','<error code="5"><message>Command unavailable in this state</message></error>');await pending;
      assert.equal(socket.commands.length,3);assert.equal(session.state,'stopping');assert.equal(session.connection.closed,false);
    }
    else {const pending = session[method]();socket.reply(2);await pending;}
  });
}
test('snapshot expressions do not publish another stop or overflow event retention',async t => {
  const {session,socket} = harness(t,{session:{maxEvents:1}});session.state = 'break';let stops = 0;session.on('stopped',() => stops++);
  socket.on('command',request => socket.reply(socket.commands.indexOf(request),'',request.name === 'eval' ? property('1',{type:'int'}):''));
  for (let i=0;i<5;i++) assert.equal((await session.snapshot({expressions:['1']})).expressions['1'].value,1);
  assert.equal(stops,0);assert.equal(session.connection.closed,false);
});
for (const cancel of [false,true]) {
  test(`an abandoned read reply leaves following commands usable (abort=${cancel})`,async t => {
    const {session,socket,connection} = harness(t),controller = new AbortController();
    const abandoned = assert.rejects(connection.send('status',{},undefined,cancel ? 0:5,{signal:controller.signal}),cancel ? /abandoned/:CommandTimeout);
    if (cancel) controller.abort(new Error('abandoned read'));
    await abandoned;socket.reply(0,'status="starting"');
    const depth = session.stackDepth();socket.reply(1,'depth="2"');assert.equal(await depth,2);assert.equal(connection.closed,false);
  });
}
test('execution in one session does not block inspection in another',async t => {
  const first = harness(t),second = harness(t),running = first.session.run();
  const status = second.session.status();second.socket.reply(0,'status="starting"');assert.equal((await status).status,'starting');
  assert.equal(first.session.state,'running');first.socket.reply(0,'status="break"');await running;
});
