const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawn} = require('node:child_process');
const {Listener,Xdebug} = require('../../core');
const file = path.resolve(__dirname,'../fixtures/runtime.php');
const line = fs.readFileSync(file,'utf8').split('\n').findIndex(line => line.includes('MATRIX_BREAK'))+1;
function launch(t,listener,key) {
  const owner = listener.register(new Xdebug(undefined,key));
  const attached = owner.waitForSession({timeout:5000}); attached.catch(() => {});
  const child = spawn('/usr/bin/php8.4',['-d','xdebug.mode=debug','-d','xdebug.start_with_request=yes','-d','xdebug.client_host=127.0.0.1','-d',`xdebug.client_port=${listener.port}`,'-d',`xdebug.idekey=${key}`,file],{stdio:['ignore','pipe','pipe']});
  let stdout = '',stderr = '';
  child.stdout.on('data',chunk => stdout += chunk); child.stderr.on('data',chunk => stderr += chunk);
  const done = new Promise((resolve,reject) => {child.once('error',reject); child.once('close',code => resolve({code,stdout,stderr}));}); done.catch(() => {});
  t.after(async () => {if (child.exitCode === null) child.kill('SIGTERM');await done;});
  return {attached,done};
}
test('four real PHP sessions remain independent and produce their own mutated outputs',{timeout:15000},async t => {
  const listener = new Listener(); await listener.listen(0); t.after(() => listener.close());
  const children = Array.from({length:4},(_,i) => launch(t,listener,`parallel-${i}`));
  const sessions = await Promise.all(children.map(child => child.attached));
  assert.equal(new Set(sessions.map(session => session.id)).size,4);
  await Promise.all(sessions.map(async session => {await session.setBreakpoint(file,line);await session.runUntilBreak();}));
  for (const session of sessions) assert.equal(await session.evaluate('$discount'),10);
  await sessions[0].setVariable('$discount',11); await sessions[0].detach();
  assert.equal(JSON.parse((await children[0].done).stdout).total,89);
  for (let i=1;i<4;i++) {
    assert.equal(sessions[i].state,'break'); assert.equal(await sessions[i].evaluate('$discount'),10);
    await sessions[i].setVariable('$discount',11+i); await sessions[i].stepOver();
    assert.equal(await sessions[i].evaluate('$total'),89-i); await sessions[i].detach();
  }
  const completed = await Promise.all(children.map(child => child.done));
  assert(completed.every(result => result.code === 0));
});
test('closing the owner releases several paused requests and settles each PHP process',{timeout:15000},async t => {
  const listener = new Listener(); await listener.listen(0); t.after(() => listener.close());
  const children = Array.from({length:3},(_,i) => launch(t,listener,`release-${i}`));
  const sessions = await Promise.all(children.map(child => child.attached));
  await Promise.all(sessions.map(async session => {await session.setBreakpoint(file,line);await session.runUntilBreak();}));
  await listener.close();
  for (const child of children) {const result = await child.done;assert.equal(result.code,0,result.stderr);assert.equal(JSON.parse(result.stdout).total,90);}
});
test('explicit stop terminates PHP before the remaining output executes',{timeout:15000},async t => {
  const listener = new Listener(); await listener.listen(0); t.after(() => listener.close());
  const child = launch(t,listener,'stop'); const session = await child.attached;
  await session.setBreakpoint(file,line); await session.runUntilBreak();
  assert.equal((await session.stop()).status,'stopped');
  const completed = await child.done; assert.equal(completed.stdout,'');
});
