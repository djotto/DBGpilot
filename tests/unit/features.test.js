const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,property} = require('../support/peer');
const {ProtocolError,XdebugError} = require('../../core');

// A negotiated engine, including independently controllable protocol errors.
function engine(t,{features = {},getErrors = {},settings = {},commandErrors = {},init} = {}) {
  const result = harness(t);
  if (init) Object.assign(result.session.init,init);
  const values = {encoding:'UTF-8',data_encoding:'base64',supports_async:'0',supports_postmortem:'0',
    breakpoint_types:'line conditional exception call return',...features};
  const replyError = (index,code) => result.socket.reply(index,'',`<error code="${code}"><message>Rejected</message></error>`);
  result.socket.on('command',request => {
    const index = result.socket.commands.length-1;
    if (commandErrors[request.name]) return replyError(index,commandErrors[request.name]);
    if (request.name === 'feature_get') {
      if (getErrors[request.args.n]) return replyError(index,getErrors[request.args.n]);
      const value = Object.hasOwn(values,request.args.n) ? values[request.args.n] : '1';
      result.socket.reply(index,`supported="${value === null ? 0:1}"`,value ?? '');
    } else if (request.name === 'feature_set') {
      const outcome = settings[request.args.n] ?? 1;
      if (outcome > 1) return replyError(index,outcome);
      if (outcome) values[request.args.n] = request.args.v;
      result.socket.reply(index,`success="${outcome}"`);
    } else if (request.name === 'eval') result.socket.reply(index,'',property('GET /checkout'));
    else if (request.name === 'detach') result.socket.reply(index,'status="stopped"');
  });
  return {...result,values};
}

test('preparation only queries encodings, applies settings and reads request metadata',async t => {
  const {session,socket} = engine(t);
  await session.prepare();
  assert.deepEqual(socket.commands.filter(command => command.name === 'feature_get').map(command => command.args.n),['encoding','data_encoding']);
  assert.equal(socket.commands.length,10);
  assert.deepEqual(session.request,{method:'GET',uri:'/checkout'});
  for (const name of ['max_children','max_data','max_depth','extended_properties','notify_ok','resolved_breakpoints','breakpoint_details']) {
    assert(socket.commands.some(command => command.name === 'feature_set' && command.args.n === name));
  }
  assert.equal(socket.commands.at(-1).name,'eval');
});

for (const outcome of [0,3,4]) {
  test(`optional settings rejected with ${outcome} retain the engine's original values`,async t => {
    const {session,connection} = engine(t,{features:{max_depth:'2',notify_ok:'0'},settings:{max_depth:outcome,notify_ok:outcome}});
    await session.prepare();
    assert.equal(connection.closed,false);
    assert.equal((await session.featureGet('max_depth')).value,'2');
    assert.equal((await session.featureGet('notify_ok')).enabled,false);
  });
}

for (const code of [3,4]) {
  test(`the full inventory reports unsupported feature queries (${code}) without failing`,async t => {
    const getErrors = {source:code,supports_async:code,extended_properties:code};
    const {session,connection} = engine(t,{getErrors,settings:{extended_properties:code}});
    await session.prepare();
    const inventory = await session.getCapabilities();
    for (const name of Object.keys(getErrors)) assert.deepEqual(inventory[name],{supported:false,value:'',enabled:false});
    delete getErrors.source;
    assert.equal((await session.getCapabilities()).source.enabled,true);
    assert.equal(connection.closed,false);
  });
}

test('unexpected inventory errors are reported only when the inventory is requested',async t => {
  const {session} = engine(t,{getErrors:{source:5}});
  await session.prepare();
  await assert.rejects(session.getCapabilities(),error => error instanceof XdebugError && error.code === 5);
  assert.equal(await session.evaluate('1'),'GET /checkout');
});
test('unexpected essential encoding query errors fail preparation',async t => {
  const {session} = engine(t,{getErrors:{encoding:5}});
  await assert.rejects(session.prepare(),error => error instanceof XdebugError && error.code === 5);
});
test('unexpected setting errors remain visible',async t => {
  const {session} = engine(t,{settings:{notify_ok:5}});
  await assert.rejects(session.prepare(),error => error instanceof XdebugError && error.code === 5);
});

test('a non-UTF-8 engine must accept UTF-8 before any PHP is evaluated',async t => {
  const {session,socket} = engine(t,{features:{encoding:'ASCII',data_encoding:'none'}});
  await session.prepare();
  assert.equal((await session.featureGet('encoding')).value,'UTF-8');
  assert.equal((await session.featureGet('data_encoding')).value,'base64');
  for (const name of ['encoding','data_encoding']) {
    assert(socket.commands.findIndex(c => c.name === 'feature_set' && c.args.n === name) < socket.commands.findIndex(c => c.name === 'eval'));
  }
});
for (const name of ['encoding','data_encoding']) for (const outcome of [0,3,4]) {
  test(`required ${name} rejected with ${outcome} prevents evaluation`,async t => {
    const features = name === 'encoding' ? {encoding:'ASCII'} : {data_encoding:'none'};
    const {session,socket} = engine(t,{features,settings:{[name]:outcome}});
    await assert.rejects(session.prepare(),ProtocolError);
    assert.equal(socket.commands.some(c => c.name === 'eval'),false);
  });
}
test('Xdebug Latin-1 labels retain the lossless byte parser without forcing UTF-8',async t => {
  const {session,socket} = engine(t,{features:{encoding:'iso-8859-1'},init:{engine:{'#text':'Xdebug'}}});
  await session.prepare();
  assert.equal((await session.featureGet('encoding')).value,'iso-8859-1');
  assert.equal(socket.commands.some(c => c.name === 'feature_set' && c.args.n === 'encoding'),false);
});
test('unknown optional encoding features use the protocol defaults',async t => {
  const {session} = engine(t,{features:{encoding:null,data_encoding:null}});
  await session.prepare();
  assert.equal((await session.featureGet('encoding')).supported,false);
  assert.equal(session.request.method,'GET');
});

test('typed and raw feature setters cannot change encoding assumptions',async t => {
  const {session,socket} = engine(t);
  for (const [name,value] of [['encoding','ISO-8859-1'],['data_encoding','none']]) {
    await assert.rejects(session.featureSet(name,value),TypeError);
    await assert.rejects(session.command('feature_set',{n:name,v:value}),TypeError);
  }
  assert.equal(socket.commands.length,0);
  assert.equal(await session.featureSet('encoding','utf8'),true);
  assert.equal(await session.featureSet('data_encoding','base64'),true);
});
test('getCapabilities returns the full inventory afresh without retaining a cache',async t => {
  const {session,socket,values} = engine(t);
  const first = await session.getCapabilities();
  assert.equal(Object.keys(first).length,40);
  for (const name of ['language_name','encoding','supports_async','supports_postmortem','breakpoint_types',
    'max_data','breakpoint_details','feature_get','run','eval','property_get','property_set','source','detach','stop']) {
    assert(Object.hasOwn(first,name),name);
  }
  assert.equal(socket.commands.length,40);
  assert(socket.commands.every(command => command.name === 'feature_get'));
  assert.deepEqual(first.supports_async,{supported:true,value:'0',enabled:false});
  first.supports_async.value = 'changed by caller';
  values.supports_async = '1';
  await session.featureSet('notify_ok',false);
  const before = socket.commands.length;
  const second = await session.getCapabilities();
  assert.equal(socket.commands.length-before,40);
  assert.deepEqual(second.supports_async,{supported:true,value:'1',enabled:true});
  assert.deepEqual(second.notify_ok,{supported:true,value:'0',enabled:false});
  assert.equal(first.notify_ok.value,'1');
  assert.notEqual(first,second);
  for (const name of ['capabilities','refreshCapabilities','supportsAsync','supportsCommand']) assert.equal(name in session,false);
});

test('late feature replies do not determine whether subsequent commands are attempted',async t => {
  const {session,socket} = harness(t);
  await assert.rejects(session.command('feature_get',{n:'eval'},undefined,5),/timed out/);
  socket.reply(0,'supported="1"','0');
  const evaluated = session.evaluate('42');
  socket.reply(1,'',property('42',{type:'int'}));
  assert.equal(await evaluated,42);
});

const commands = [
  ['eval',s => s.evaluate('$x')],['source',s => s.source()],['stdout',s => s.setOutput()],['stderr',s => s.setOutput('stderr')],
  ['run',s => s.run()],['step_into',s => s.stepInto()],['step_over',s => s.stepOver()],['step_out',s => s.stepOut()],
  ['property_set',s => s.setVariable('$x',1)],['stack_get',s => s.stack()],
  ['property_get',s => s.getVariable('$x')],
];
for (const [name,call] of commands) {
  test('unavailable '+name+' reaches Xdebug and returns its error without releasing PHP',async t => {
    const {session,socket,connection} = engine(t,{features:{[name]:'0'},commandErrors:{[name]:4}});
    assert.equal((await session.getCapabilities())[name].enabled,false);
    const before = socket.commands.length;
    await assert.rejects(call(session),error => error instanceof XdebugError && error.code === 4 && error.command === name);
    assert.equal(socket.commands.length,before+1);
    assert.equal(socket.commands.at(-1).name,name);
    assert.equal(session.state,'starting');
    assert.equal(connection.closed,false);
    assert.equal((await session.featureGet('encoding')).value,'UTF-8');
  });
}

test('assignment attempts verification and reports its failure as the cause',async t => {
  const {session,socket} = harness(t);
  const setting = assert.rejects(session.setVariable('$x',1),error => error.cause instanceof XdebugError && error.cause.code === 4);
  socket.reply(0,'success="1"');
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(socket.commands[1].name,'property_get');
  socket.reply(1,'','<error code="4"><message>Unsupported</message></error>');
  await setting;
});

test('unsupported request metadata evaluation fails preparation with the engine error',async t => {
  const {session,socket} = engine(t,{commandErrors:{eval:4}});
  await assert.rejects(session.prepare(),error => error instanceof XdebugError && error.code === 4);
  assert.equal(socket.commands.at(-1).name,'eval');
});
test('breakpoint type advertisements do not pre-empt the actual breakpoint request',async t => {
  const {session,socket} = engine(t);
  assert.equal((await session.getCapabilities()).breakpoint_types.value.includes('watch'),false);
  const creating = session.setBreakpoint(undefined,undefined,{kind:'watch',condition:'$x'});
  assert.equal(socket.commands.at(-1).args.t,'watch');
  socket.reply(socket.commands.length-1,'','<error code="201"><message>Unsupported breakpoint type</message></error>');
  await assert.rejects(creating,error => error instanceof XdebugError && error.code === 201);
});
for (const method of ['detach','release']) {
  test(method+' attempts detach and reports its failure while closing the connection',async t => {
    const {session,socket,connection} = engine(t,{features:{detach:'0'},commandErrors:{detach:4}});
    await session.prepare();
    const before = socket.commands.length;
    const result = await session[method]();
    assert.match(result.releaseError,/Rejected/);
    assert.equal(connection.closed,true);
    assert.equal(socket.commands.length,before+1);
    assert.equal(socket.commands.at(-1).name,'detach');
  });
}
test('unsupported stop returns the engine error and still closes the connection',async t => {
  const {session,socket,connection} = engine(t,{commandErrors:{stop:4}});
  await assert.rejects(session.stop(),error => error instanceof XdebugError && error.code === 4);
  assert.equal(socket.commands[0].name,'stop');
  assert.equal(connection.closed,true);
});
