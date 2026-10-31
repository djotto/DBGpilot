// Archived Python integration scenarios, exercised against real PHP/Xdebug.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn,execFileSync} = require('node:child_process');
const {Listener,Xdebug,XdebugError} = require('../../core');
const targets = require('../support/runtimes');
const file = path.resolve(__dirname,'../fixtures/integration.php');
const source = fs.readFileSync(file,'utf8').split('\n');
function line(marker) {
  const matches = source.flatMap((text,index) => text.includes(`// ${marker}`) ? [index+1] : []);
  assert.equal(matches.length,1,`Expected exactly one ${marker} marker`);
  return matches[0];
}
function bounded(promise,timeout,message) {
  let timer;
  return Promise.race([promise,new Promise((_,reject) => {timer = setTimeout(() => reject(new Error(message)),timeout);})])
    .finally(() => clearTimeout(timer));
}
const output = Buffer.concat([Buffer.from('one\0'),Buffer.from([255]),Buffer.from('two é🙂')]);
const reportFile = path.resolve(__dirname,'../../test-results/integration-js.json');
fs.mkdirSync(path.dirname(reportFile),{recursive:true});
const records = [];

async function withPHP(target,scenario,body) {
  const listener = new Listener();
  let child,done;
  try {
    await listener.listen(0);
    const owner = listener.register(new Xdebug(undefined,'integration'));
    const attached = owner.waitForSession({timeout:5000});attached.catch(() => {});
    child = spawn(target.executable,[...target.args,'-d','xdebug.mode=debug','-d','xdebug.start_with_request=yes',
      '-d','xdebug.client_host=127.0.0.1','-d',`xdebug.client_port=${listener.port}`,'-d',`xdebug.idekey=${owner.ideKey}`,file,scenario],
    {stdio:['ignore','pipe','pipe']});
    const stdout = [],stderr = [];
    child.stdout.on('data',chunk => stdout.push(chunk));child.stderr.on('data',chunk => stderr.push(chunk));
    done = new Promise((resolve,reject) => {
      child.once('error',reject);
      child.once('close',(code,signal) => resolve({code,signal,stdout:Buffer.concat(stdout),stderr:Buffer.concat(stderr)}));
    });done.catch(() => {});
    const session = await attached;
    const finish = async expected => {
      await session.detach();
      const completed = await bounded(done,5000,'PHP did not exit after detach');
      assert.equal(completed.code,0,completed.stderr.toString());
      assert.equal(completed.signal,null);
      assert.equal(completed.stderr.length,0,completed.stderr.toString());
      assert.deepEqual(completed.stdout,Buffer.isBuffer(expected) ? expected:Buffer.from(expected));
    };
    await body(session,finish);
  } finally {
    try { await listener.close(); }
    finally {
      if (child && child.exitCode === null && child.signalCode === null) {
        child.kill('SIGTERM');
        const timer = setTimeout(() => child.kill('SIGKILL'),2000);
        try { await done.catch(() => {}); } finally {clearTimeout(timer);}
      }
    }
  }
}

const cases = [
  ['step into a function, inspect its locals and step out to its caller','stepping',async (session,finish) => {
    const point = await session.setBreakpoint(file,line('STEP_CALL'));
    assert.equal((await session.runUntilBreak({timeout:3000})).line,line('STEP_CALL'));
    await session.removeBreakpoint(point);
    const entered = await session.stepInto({timeout:3000});
    assert.equal(entered.line,line('STEP_BODY'));
    assert.equal((await session.stack())[0].where,'double_number');
    assert.equal(await session.stackDepth(),2);
    assert.equal(await session.getVariable('$number'),3);
    await session.stepOver({timeout:3000});
    assert.equal(await session.getVariable('$doubled'),6);
    const returned = await session.stepOut({timeout:3000});
    assert.equal(returned.line,line('STEP_AFTER'));
    assert.equal((await session.stack())[0].where,'{main}');
    assert.equal(await session.stackDepth(),1);
    assert.equal(await session.getVariable('$result'),6);
    await finish('6');
  }],
  ['exact third-hit breakpoint followed by a temporary breakpoint on the next iteration','hits',async (session,finish) => {
    const point = await session.setBreakpoint(file,line('HIT_CALL'),{hitValue:3,hitCondition:'=='});
    await session.runUntilBreak({timeout:3000});
    assert.equal(await session.getVariable('$i'),2);
    const record = await session.getBreakpoint(point);
    assert.equal(record.hitCount,3);assert.equal(record.hitValue,3);assert.equal(record.hitCondition,'==');
    await session.removeBreakpoint(point);
    await session.stepOver({timeout:3000});
    assert.equal(await session.getVariable('$result'),4);
    const temporary = await session.setBreakpoint(file,line('HIT_CALL'),{temporary:true});
    assert.equal((await session.runUntilBreak({timeout:3000})).line,line('HIT_CALL'));
    assert.equal(await session.getVariable('$i'),3);
    assert.equal((await session.getBreakpoint(temporary)).state,'disabled');
    await finish('6');
  }],
  ...[0,1,2].map(mode => [`stdout mode ${mode} preserves binary stream bytes and routes process output correctly`,'output',async (session,finish) => {
    const point = await session.setBreakpoint(file,line('OUTPUT_READY'));
    await session.runUntilBreak({timeout:3000});await session.removeBreakpoint(point);
    const observed = [];
    session.on('stream',event => {assert.equal(event.stream,'stdout');observed.push(event.data);});
    assert.equal(await session.setOutput('stdout',mode),true);
    assert.equal((await session.run({timeout:3000})).status,'stopping');
    const expected = mode === 0 ? Buffer.alloc(0):output;
    assert.deepEqual(Buffer.concat(observed),expected);
    // Breakpoint notifications/stops can precede output. Each emitted stream
    // must also be retained by nextEvent(), without assuming packet chunking.
    const retained = [];
    while (retained.length < observed.length) {
      const event = await session.nextEvent({timeout:1000});
      if (event.type === 'stream') {assert.equal(event.data.stream,'stdout');retained.push(event.data.data);}
    }
    assert.deepEqual(Buffer.concat(retained),expected);
    await finish(mode === 2 ? Buffer.alloc(0):output);
  }]),
  ['invalid PHP evaluation preserves the exception pause and allows inspection, mutation and detach','evaluation',async (session,finish) => {
    await session.setExceptionBreakpoint('RuntimeException');
    const stopped = await session.runUntilBreak({timeout:3000});
    assert.equal(stopped.exception,'RuntimeException');
    assert.equal(stopped.line,line('EVAL_EXCEPTION'));
    const before = (await session.stack())[0];
    await assert.rejects(session.evaluate('this is not valid PHP!'),error => {
      assert(error instanceof XdebugError);assert.equal(error.command,'eval');assert(Number.isInteger(error.code));return true;
    });
    assert.equal(session.connection.closed,false);assert.equal(session.state,'break');
    assert.equal((await session.status()).status,'break');
    const after = (await session.stack())[0];
    assert.deepEqual([after.fileUri,after.line,after.where],[before.fileUri,before.line,before.where]);
    assert.equal(await session.getVariable('$answer'),40);
    assert.equal(await session.evaluate('$answer + 2'),42);
    await session.setVariable('$answer',41);
    await finish('caught:41');
  }],
];

for (const target of targets) {
  test(`live scenarios: PHP ${target.php} / Xdebug ${target.xdebug}`,{timeout:45000},async t => {
    const record = {...target,status:'running',cases:[]};records.push(record);
    try {
      const executable = `/usr/bin/php${target.php}`;
      const args = target.historical ? ['-n','-d',`zend_extension=/mnt/ddev-global-cache/dbgpilot/runtimes/php${target.php}-xdebug${target.xdebug}.so`]:[];
      const [php,xdebug] = JSON.parse(execFileSync(executable,[...args,'-d','xdebug.mode=off','-r',"echo json_encode([PHP_VERSION,phpversion('xdebug')]);"],{encoding:'utf8',timeout:5000}));
      assert(php.startsWith(target.php+'.'));assert.equal(xdebug,target.xdebug);
      record.php = php;
      for (const [name,scenario,body] of cases) {
        await t.test(name,{timeout:15000},async () => {
          const result = {name,status:'running'};record.cases.push(result);
          try {await withPHP({executable,args},scenario,body);result.status = 'passed';}
          catch (error) {result.status = 'failed';result.error = error.message;throw error;}
        });
      }
      record.status = record.cases.every(result => result.status === 'passed') ? 'passed':'failed';
    } catch (error) {record.status = 'failed';record.error = error.message;throw error;}
    finally {fs.writeFileSync(reportFile,JSON.stringify({node:process.version,runtimes:records},null,2)+'\n');}
  });
}
