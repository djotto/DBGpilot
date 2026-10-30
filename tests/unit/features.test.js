const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,property} = require('../support/peer');
const {ProtocolError,XdebugError} = require('../../core');

// A negotiated engine, including independently controllable protocol errors.
function engine(t,{features = {},getErrors = {},settings = {},init} = {}) {
  const result = harness(t);
  if (init) Object.assign(result.session.init,init);
  const values = {encoding:'UTF-8',data_encoding:'base64',supports_async:'0',supports_postmortem:'0',
    breakpoint_types:'line conditional exception call return',...features};
  const replyError = (index,code) => result.socket.reply(index,'',`<error code="${code}"><message>Rejected</message></error>`);
  result.socket.on('command',request => {
    const index = result.socket.commands.length-1;
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

test('preparation negotiates commands, settings and notification support before reading PHP',async t => {
  const {session,socket} = engine(t);
  await session.prepare();
  assert.equal(session.supportsCommand('eval'),true);
  assert.equal(session.supportsCommand('feature_get'),true);
  assert.equal(session.supportsCommand('unknown'),false);
  assert.equal(session.supportsAsync,false);
  assert.deepEqual(session.request,{method:'GET',uri:'/checkout'});
  for (const name of ['max_children','max_data','max_depth','extended_properties','notify_ok','resolved_breakpoints','breakpoint_details']) {
    assert(socket.commands.some(command => command.name === 'feature_set' && command.args.n === name));
    assert.equal(session.capabilities[name].supported,true);
  }
  assert.equal(socket.commands.at(-1).name,'eval');
});

for (const outcome of [0,3,4]) {
  test(`optional settings rejected with ${outcome} retain the engine's original values`,async t => {
    const {session,connection} = engine(t,{features:{max_depth:'2',notify_ok:'0'},settings:{max_depth:outcome,notify_ok:outcome}});
    await session.prepare();
    assert.equal(connection.closed,false);
    assert.equal(session.capabilities.max_depth.value,'2');
    assert.equal(session.capabilities.notify_ok.enabled,false);
    assert.equal(session.supportsCommand('eval'),true);
  });
}

for (const code of [3,4]) {
  test(`unsupported feature queries (${code}) do not prevent preparation or refresh`,async t => {
    const getErrors = {source:code,supports_async:code,extended_properties:code};
    const {session,connection} = engine(t,{getErrors,settings:{extended_properties:code}});
    await session.prepare();
    assert.deepEqual(session.capabilities.source,{supported:false,value:'',enabled:false});
    assert.equal(session.supportsCommand('source'),false);
    assert.equal(session.supportsAsync,false);
    delete getErrors.source;
    await session.refreshCapabilities(['source']);
    assert.equal(session.supportsCommand('source'),true);
    assert.equal(connection.closed,false);
  });
}

test('unexpected negotiation errors remain visible',async t => {
  const {session} = engine(t,{getErrors:{source:5}});
  await assert.rejects(session.prepare(),error => error instanceof XdebugError && error.code === 5);
});
test('unexpected setting errors remain visible',async t => {
  const {session} = engine(t,{settings:{notify_ok:5}});
  await assert.rejects(session.prepare(),error => error instanceof XdebugError && error.code === 5);
});

test('a non-UTF-8 engine must accept UTF-8 before any PHP is evaluated',async t => {
  const {session,socket} = engine(t,{features:{encoding:'ASCII',data_encoding:'none'}});
  await session.prepare();
  assert.equal(session.capabilities.encoding.value,'UTF-8');
  assert.equal(session.capabilities.data_encoding.value,'base64');
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
  assert.equal(session.capabilities.encoding.value,'iso-8859-1');
  assert.equal(socket.commands.some(c => c.name === 'feature_set' && c.args.n === 'encoding'),false);
});
test('unknown optional encoding features use the protocol defaults',async t => {
  const {session} = engine(t,{features:{encoding:null,data_encoding:null}});
  await session.prepare();
  assert.equal(session.capabilities.encoding.supported,false);
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
test('boolean settings cache their wire value, and late capability replies update support',async t => {
  const {session,socket} = harness(t);
  const setting = session.featureSet('notify_ok',false);socket.reply(0,'success="1"');
  assert.equal(await setting,true);
  assert.deepEqual(session.capabilities.notify_ok,{supported:true,value:'0',enabled:false});
  const refresh = session.refreshCapabilities(['supports_async']);socket.reply(1,'supported="1"','1');await refresh;
  assert.equal(session.supportsAsync,true);
  const late = assert.rejects(session.command('feature_get',{n:'supports_async'},undefined,5),/timed out/);
  await late;socket.reply(2,'supported="1"','0');assert.equal(session.supportsAsync,false);
  const unsupported = assert.rejects(session.command('feature_get',{n:'eval'},undefined,5),/timed out/);
  await unsupported;socket.reply(3,'','<error code="4"><message>Unsupported</message></error>');
  assert.equal(session.supportsCommand('eval'),false);
  const lateSetting = assert.rejects(session.command('feature_set',{n:'supports_async',v:true},undefined,5),/timed out/);
  await lateSetting;socket.reply(4,'success="1"');assert.equal(session.supportsAsync,true);
});

const guarded = [
  ['eval',s => s.evaluate('$x')],['source',s => s.source()],['stdout',s => s.setOutput()],['stderr',s => s.setOutput('stderr')],
  ['run',s => s.run()],['step_into',s => s.stepInto()],['step_out',s => s.stepOut()],
  ['property_set',s => s.setVariable('$x',1)],['stack_get',s => s.stack()],
  ['property_get',s => s.setVariable('$x',1)],
  ['detach',s => s.detach()],['stop',s => s.stop()],
];
for (const [name,call] of guarded) {
  test(`advertised unavailable ${name} is rejected without changing or releasing PHP`,async t => {
    const {session,socket,connection} = harness(t);
    const refresh = session.refreshCapabilities([name]);socket.reply(0,'supported="1"','0');await refresh;
    await assert.rejects(call(session),new RegExp(`support for ${name}`));
    assert.equal(socket.commands.length,1);
    assert.equal(session.state,'starting');
    assert.equal(connection.closed,false);
  });
}
test('missing eval support prevents request metadata evaluation',async t => {
  const {session,socket} = engine(t,{features:{eval:null}});
  await assert.rejects(session.prepare(),/support for eval/);
  assert.equal(socket.commands.some(c => c.name === 'eval'),false);
});
test('owner cleanup still closes a connection whose engine cannot detach',async t => {
  const {session,socket,connection} = engine(t,{features:{detach:'0'}});
  await session.prepare();
  const before = socket.commands.length;
  const result = await session.release();
  assert.match(result.releaseError,/support for detach/);
  assert.equal(connection.closed,true);
  assert.equal(socket.commands.length,before);
});
