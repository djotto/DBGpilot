const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {spawn,execFileSync} = require('node:child_process');
const {Listener,Xdebug} = require('../../core');
const reportFile = path.resolve(__dirname,'../../../test-results/compatibility-js.json');
fs.mkdirSync(path.dirname(reportFile),{recursive:true});
const results = [];
const targets = [
  ...['8.2','8.3','8.4','8.5'].map(php => ({php,xdebug:'3.5.3'})),
  {php:'8.2',xdebug:'3.3.2',historical:true},{php:'8.3',xdebug:'3.4.7',historical:true},
];
for (const target of targets) {
  test(`PHP ${target.php} / Xdebug ${target.xdebug}`,{timeout:20000},async t => {
    const executable = `/usr/bin/php${target.php}`;
    const args = target.historical ? ['-n','-d',`zend_extension=/mnt/ddev-global-cache/dbgpilot/runtimes/php${target.php}-xdebug${target.xdebug}.so`] : [];
    const record = {...target,status:'running'}; results.push(record);
    const listener = new Listener();
    const temp = fs.mkdtempSync(path.join(os.tmpdir(),'dbgpilot-js-matrix-'));
    let process;
    try {
      const [php,xdebugVersion] = JSON.parse(execFileSync(executable,[...args,'-d','xdebug.mode=off','-r',"echo json_encode([PHP_VERSION,phpversion('xdebug')]);"],{encoding:'utf8',timeout:5000}));
      record.php = php; assert(php.startsWith(target.php+'.')); assert.equal(xdebugVersion,target.xdebug);
      await listener.listen(0,'127.0.0.1');
      const source = fs.readFileSync(path.resolve(__dirname,'../fixtures/runtime.php'),'utf8');
      const file = path.join(temp,'compatibility é.php'); fs.writeFileSync(file,source);
      const line = source.split('\n').findIndex(text => text.includes('MATRIX_BREAK'))+1;
      const owner = listener.register(new Xdebug(undefined,'compatibility',2000,{pathMappings:[{local:'C:\\Matrix',remote:pathToFileURL(temp).href}]}));
      const waiting = owner.waitForSession({timeout:5000}); waiting.catch(() => {});
      process = spawn(executable,[...args,'-d','xdebug.mode=debug','-d','xdebug.start_with_request=yes','-d','xdebug.client_host=127.0.0.1','-d',`xdebug.client_port=${listener.port}`,'-d',`xdebug.idekey=${owner.ideKey}`,file],{stdio:['ignore','pipe','pipe']});
      let stdout = '', stderr = '';
      process.stdout.on('data',chunk => stdout += chunk); process.stderr.on('data',chunk => stderr += chunk);
      const done = new Promise((resolve,reject) => {process.once('error',reject);process.once('close',code => resolve(code));}); done.catch(() => {});
      const session = await waiting;
      assert.equal(session.init.engine.version,target.xdebug); assert.equal(session.request.method,'CLI');
      await session.setBreakpoint('C:\\Matrix\\compatibility é.php',line,{condition:'$discount === 10'});
      const stopped = await session.runUntilBreak(); assert.equal(stopped.localFile,'C:\\Matrix\\compatibility é.php');
      const snapshot = await session.snapshot({variables:['$discount','$binary','$bigint']});
      assert.equal(snapshot.variables.$discount.value,10); assert.equal(snapshot.variables.$binary.value.data,'/wA=');
      assert.equal(snapshot.variables.$bigint.value.value,'9223372036854775807');
      const data = await session.getProperty('$data'); assert.equal(data.children[0].name,'a\0b'); assert.equal(data.children[1].name,'é');
      assert.equal(await session.stackDepth(),2); assert.equal(await session.evaluate('$subtotal - $discount'),90);
      assert((await session.typeMap()).length > 0);
      assert.deepEqual(await session.getVariable('$many'),Array.from({length:250},(_,i) => i));
      const long = await session.propertyValueInfo('$long'); assert.equal(long.size,3072); assert.equal(long.data.toString(),'abc'.repeat(1024));
      await session.setVariable('$discount',15); await session.stepOver(); assert.equal(await session.evaluate('$total'),85);
      await session.detach(); assert.equal(await done,0,stderr); assert.equal(JSON.parse(stdout).total,85);
      record.status = 'passed';
    } catch (error) { record.status = 'failed'; record.error = error.message; throw error; }
    finally {
      await listener.close();
      if (process && process.exitCode === null) process.kill('SIGTERM');
      fs.rmSync(temp,{recursive:true,force:true});
      fs.writeFileSync(reportFile,JSON.stringify(results,null,2)+'\n');
    }
  });
}
