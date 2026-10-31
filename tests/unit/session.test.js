const {test} = require('node:test');
const assert = require('node:assert/strict');
const {harness,property} = require('../support/peer');
const {CommandTimeout,ProtocolError} = require('../../core');
test('late run reply restores pause and allows subsequent stepping',async t => {
  const {session,socket} = harness(t);
  await assert.rejects(session.run({timeout:10}),CommandTimeout);
  assert.equal(session.state,'running');
  await assert.rejects(session.stepOver(),/pending/);
  const recovered = session.waitForPause({timeout:1000});
  socket.reply(0,'status="break" reason="ok"','<message filename="file:///app/a.php" lineno="7"/>');
  assert.equal((await recovered).line,7); assert.equal(session.state,'break');
  const step = session.stepOver(); socket.reply(1,'status="break"'); await step;
});
test('rejected continuation restores previous state',async t => {
  const {session,socket} = harness(t); const run = assert.rejects(session.run(),/failed/);
  socket.reply(0,'','<error code="5"><message>unavailable</message></error>'); await run;
  assert.equal(session.state,'starting');
});
test('late execution completion rejects pause recovery promptly',async t => {
  const {session,socket} = harness(t);
  await assert.rejects(session.run({timeout:10}),CommandTimeout);
  const waiting = assert.rejects(session.waitForPause(),/finished without pausing/);
  socket.reply(0,'status="stopping"'); await waiting;
  await assert.rejects(session.waitForPause(),/finished without pausing/);
});
test('aborted pause recovery leaves PHP owned and removes listeners',async t => {
  const {session,socket} = harness(t); const running = session.run();
  const abort = new AbortController();
  const waiting = assert.rejects(session.waitForPause({signal:abort.signal}),/cancelled/);
  abort.abort(new Error('cancelled')); await waiting;
  assert.equal(session.state,'running'); assert.equal(session.listenerCount('stopped'),0);
  socket.reply(0,'status="break"'); await running;
});
for (const method of ['locals','stack','getVariable','evaluate','setVariable']) {
  test(`reject ${method} during execution without sending it`,async t => {
    const {session,socket} = harness(t); const run = session.run();
    await assert.rejects(session[method]('$x',1),/pending/);
    assert.equal(socket.commands.length,1); socket.reply(0,'status="break"'); await run;
  });
}
test('evaluations own execution until their late response, preserving one stop',async t => {
  const {session,socket} = harness(t); session.state = 'break'; let stops = 0;
  session.on('stopped',() => stops++);
  await assert.rejects(session.evaluate('slow()',{timeout:10}),CommandTimeout);
  await assert.rejects(session.run(),/pending/);
  socket.reply(0,'',property('42',{type:'int'}));
  assert.equal(session.state,'break'); assert.equal(stops,1);
  const evaluation = session.evaluate('42'); socket.reply(1,'',property('42',{type:'int'}));
  assert.equal(await evaluation,42); assert.equal(stops,1);
});
test('raw continuation commands update the same state machine',async t => {
  const {session,socket} = harness(t); const run = session.command('run');
  assert.equal(session.state,'running'); socket.reply(0,'status="break"'); await run;
  assert.equal(session.state,'break');
});
test('invalid continuation status closes and rejects the current operation',async t => {
  const {session,socket,connection} = harness(t); const pending = assert.rejects(session.run(),ProtocolError);
  socket.reply(0,'status="banana"'); await pending; assert.equal(connection.closed,true);
});
test('failed validation restores state without sending a command',async t => {
  const {session,socket} = harness(t); await assert.rejects(session.run({timeout:-1}),/Timeout/);
  assert.equal(session.state,'starting'); assert.equal(socket.commands.length,0);
});
test('ordinary standalone controls do not import or require test.step',async t => {
  const {session,socket} = harness(t); const evaluating = session.evaluate('42');
  socket.reply(0,'',property('42',{type:'int'})); assert.equal(await evaluating,42);
  assert.equal(Object.keys(require.cache).some(path => /node_modules.*playwright/.test(path)),false);
});
test('property paging follows direct children and retains their names',async t => {
  const {session,socket} = harness(t);
  socket.on('command',request => {
    const page = Number(request.args.p);
    queueMicrotask(() => socket.reply(socket.commands.indexOf(request),'',`<property type="array" numchildren="3" page="${page}">${[page*2,page*2+1].filter(i => i<3).map(i => property(String(i+1),{name:String(i),type:'int'})).join('')}</property>`));
  });
  assert.deepEqual(await session.getVariable('$a'),[1,2,3]); assert.equal(socket.commands.length,2);
});
for (const problem of ['empty','wrong page','page bound']) {
  test(`pagination rejects ${problem}`,async t => {
    const {session,socket} = harness(t,{session:{maxPages:2}});
    socket.on('command',request => {
      const page = Number(request.args.p);
      const reported = problem === 'wrong page' && page > 0 ? 0 : page;
      const children = problem === 'empty' && page > 0 ? '' : property('1',{name:String(page),type:'int'});
      queueMicrotask(() => socket.reply(socket.commands.indexOf(request),'',`<property type="array" numchildren="3" page="${reported}">${children}</property>`));
    });
    await assert.rejects(session.getVariable('$a'),/progress|wrong.*page|maxPages/);
    assert(socket.commands.length <= 2);
  });
}
test('setVariable preserves frame and byte length, guards its PHP execution',async t => {
  const {session,socket} = harness(t);
  const assigning = session.setVariable('$x',Buffer.from([255,0]),{frame:2});
  assert.equal(socket.commands[0].args.d,'2');
  assert.equal(socket.commands[0].name,'property_set'); assert.equal(session.state,'running');
  assert.equal(Number(socket.commands[0].args.l),socket.commands[0].data.length);
  await assert.rejects(session.evaluate('1'),/pending/);
  socket.reply(0,'success="1"'); await new Promise(resolve => setImmediate(resolve));
  socket.reply(1,'',property(Buffer.from([255,0]))); await assigning;
  assert.equal(session.state,'starting');
});
test('release is shared and can close an outstanding operation',async t => {
  const {session,connection} = harness(t); const run = assert.rejects(session.run(),/closed/);
  const first = session.release(); assert.equal(first,session.release()); await first; await run;
  assert.equal(connection.closed,true);
});
test('snapshot stays JSON safe and independent after PHP changes',async t => {
  const {session,socket} = harness(t); session.state = 'break';
  socket.on('command',request => queueMicrotask(() => {
    if (request.name === 'stack_get') socket.reply(socket.commands.indexOf(request),'','<stack level="0" where="checkout" filename="file:///app/a.php" lineno="7"/>');
    else socket.reply(socket.commands.indexOf(request),'',property('9223372036854775807',{type:'int'}));
  }));
  const snapshot = await session.snapshot({variables:['$x']});
  assert.equal(JSON.parse(JSON.stringify(snapshot)).variables.$x.value.value,'9223372036854775807');
  assert.equal(Object.hasOwn(snapshot.execution,'localFile'),false);
  assert.equal(Object.hasOwn(snapshot.execution,'pathMappingError'),false);
  assert.equal(snapshot.execution.localFile ?? snapshot.execution.file,'/app/a.php');
  session.lastResult.status = 'changed'; assert.equal(snapshot.execution.status,'starting');
  assert.equal(session.state,'break');
});
for (const mapping of ['none','matched','unmatched']) {
  test(`snapshot omits absent metadata and preserves PHP values with ${mapping} path mappings`,async t => {
    const pathMappings = mapping === 'none' ? [] : [{local:'/work',remote:mapping === 'matched' ? 'file:///app':'file:///other'}];
    const {session,socket} = harness(t,{session:{pathMappings}});
    socket.on('command',request => queueMicrotask(() => {
      const index = socket.commands.indexOf(request);
      if (request.name === 'run') socket.reply(index,'status="break" reason="ok"',
        '<message filename="file:///app/a.php" lineno="7"/><breakpoint id="bp1" filename="file:///app/a.php" lineno="7"/>');
      else if (request.name === 'stack_get') socket.reply(index,'',
        '<stack level="0" where="checkout" filename="file:///app/a.php" lineno="7"><input level="1" filename="file:///app/a.php"/></stack>');
      else if (request.name === 'property_get') socket.reply(index,'',
        '<property name="$x" fullname="$x" type="array" numchildren="1"><property name="0" fullname="$x[0]" type="uninitialized"/></property>');
      else socket.reply(index,'',property('',{type:'uninitialized'}));
    }));
    await session.run();
    const snapshot = await session.snapshot({variables:['$x'],expressions:['$unset']});
    const records = [snapshot.execution,snapshot.execution.breakpoint,snapshot.frames[0],snapshot.frames[0].inputs[0]];
    for (const record of records) {
      assert.equal(Object.hasOwn(record,'localFile'),mapping === 'matched');
      assert.equal(Object.hasOwn(record,'pathMappingError'),mapping === 'unmatched');
      assert.equal(record.localFile ?? record.fileUri,mapping === 'matched' ? '/work/a.php':'file:///app/a.php');
      if (mapping === 'unmatched') assert.match(record.pathMappingError,/no remote root/);
    }
    assert.equal(Object.hasOwn(snapshot.execution,'exception'),false);
    for (const key of ['hitCondition','function','exception','expression']) assert.equal(Object.hasOwn(snapshot.execution.breakpoint,key),false);
    assert.equal(Object.hasOwn(snapshot.frames[0],'commandBegin'),false);
    assert.deepEqual(snapshot.variables.$x.children[0].value,{type:'uninitialized'});
    assert.deepEqual(snapshot.expressions.$unset.value,{type:'uninitialized'});
    assert.deepEqual(JSON.parse(JSON.stringify(snapshot)),snapshot);
  });
}
