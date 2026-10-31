// Validate the actual npm artifact and a consumer outside this checkout.
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
const root = fileURLToPath(new URL('../',import.meta.url));
const packageRoot = root;
const packageJSON = JSON.parse(fs.readFileSync(path.join(packageRoot,'package.json'),'utf8'));
const lock = JSON.parse(fs.readFileSync(path.join(root,'package-lock.json'),'utf8'));
function lockedVersion(name) {
  const entry = lock.packages[`node_modules/${name}`];
  assert(entry?.version,`Missing locked dependency: ${name}`);
  return entry.version;
}
const temp = fs.mkdtempSync(path.join(os.tmpdir(),'dbgpilot-js-package-'));
const reportPath = path.join(root,'test-results/js-package-validation.json');
fs.mkdirSync(path.dirname(reportPath),{recursive:true});
const report = {status:'running',node:process.version,package:packageJSON.name,version:packageJSON.version};
function run(command,args,cwd = root) {
  return execFileSync(command,args,{cwd,encoding:'utf8',timeout:120000,maxBuffer:16*1024*1024});
}
try {
  const pack = JSON.parse(run('npm',['pack','--ignore-scripts','--json','--pack-destination',temp,'--cache',path.join(temp,'cache')]))[0];
  const expected = ['package.json','index.js','index.mjs','index.d.ts','core.js','core.mjs','core.d.ts','LICENSE','NOTICE.md','README.md','examples/standalone.js',
    ...fs.readdirSync(path.join(packageRoot,'lib')).filter(name => name.endsWith('.js')).map(name => 'lib/'+name)].sort();
  assert.deepEqual(pack.files.map(file => file.path).sort(),expected,'Unexpected npm package payload');
  const consumer = path.join(temp,'consumer');fs.mkdirSync(consumer);
  fs.writeFileSync(path.join(consumer,'package.json'),JSON.stringify({name:'dbgpilot-installed-consumer',private:true,dependencies:{
    'dbgpilot':'file:'+path.join(temp,pack.filename),
    '@playwright/test':lockedVersion('@playwright/test'),
    typescript:lockedVersion('typescript'),
    '@types/node':lockedVersion('@types/node'),
  }},null,2));
  run('npm',['install','--ignore-scripts','--no-audit','--no-fund','--cache',path.join(temp,'cache')],consumer);
  const installed = path.join(consumer,'node_modules/dbgpilot');
  for (const name of expected) assert.deepEqual(fs.readFileSync(path.join(installed,name)),fs.readFileSync(path.join(packageRoot,name)),`Installed file differs: ${name}`);
  run(process.execPath,['--input-type=commonjs','-e',String.raw`
    const assert=require('node:assert/strict');
    const core=require('dbgpilot/core');
    assert.equal(typeof core.Listener,'function');
    assert.equal(Object.keys(require.cache).some(p=>/node_modules\/(?:@playwright\/test|playwright|playwright-core)\//.test(p)),false);
    assert.equal(core.toJSONSafe({x:9223372036854775807n}).x.value,'9223372036854775807');
    const {test,expect}=require('dbgpilot');
    assert.equal(typeof test,'function');assert.equal(typeof expect,'function');
    for (const api of [core,require('dbgpilot')]) {
      for (const name of ['Connection','encodeCommand','parsePacket','NAMESPACE']) assert.equal(Object.hasOwn(api,name),false,name+' must remain internal');
    }
    assert.throws(()=>require('dbgpilot/lib/dbgp'),{code:'ERR_PACKAGE_PATH_NOT_EXPORTED'});
  `],consumer);
  run(process.execPath,['--input-type=module','-e',String.raw`
    import assert from 'node:assert/strict';
    import {Listener,PathMapper} from 'dbgpilot/core';
    import {test,expect} from 'dbgpilot';
    import * as core from 'dbgpilot/core';
    import * as fixture from 'dbgpilot';
    assert.equal(typeof Listener,'function');assert.equal(typeof test,'function');assert.equal(typeof expect,'function');
    assert.equal(new PathMapper([{local:'/work',remote:'file:///app'}]).toRemote('/work/a.php'),'file:///app/a.php');
    for (const api of [core,fixture]) for (const name of ['Connection','encodeCommand','parsePacket','NAMESPACE']) assert.equal(Object.hasOwn(api,name),false);
  `],consumer);
  const typed = String.raw`
    import {test,expect} from 'dbgpilot';
    import {PathMapper,Session} from 'dbgpilot/core';
    // @ts-expect-error raw connections are internal
    import {Connection} from 'dbgpilot/core';
    // @ts-expect-error packet encoders are internal
    import {encodeCommand} from 'dbgpilot/core';
    // @ts-expect-error packet parsers are internal
    import {parsePacket} from 'dbgpilot/core';
    // @ts-expect-error protocol constants are internal
    import {NAMESPACE} from 'dbgpilot/core';
    // @ts-expect-error fixture exports also hide raw connections
    import {Connection as FixtureConnection} from 'dbgpilot';
    // @ts-expect-error fixture exports also hide packet encoders
    import {encodeCommand as fixtureEncoder} from 'dbgpilot';
    // @ts-expect-error fixture exports also hide packet parsers
    import {parsePacket as fixtureParser} from 'dbgpilot';
    // @ts-expect-error fixture exports also hide protocol constants
    import {NAMESPACE as fixtureNamespace} from 'dbgpilot';
    test.use({xdebugPort:9003,xdebugPathMappings:[{local:'/work',remote:'file:///app'}]});
    test('typed consumer',async({page,xdebug})=>{
      const paused=await xdebug.goto(page,'http://localhost/',{variables:['$x']});
      const capabilities=await paused.session.getCapabilities();
      const canEvaluate:boolean=capabilities.eval.enabled;
      const canInterrupt:boolean=capabilities.supports_async.enabled;void canEvaluate;void canInterrupt;
      await paused.session.setVariable('$x',42n);await paused.session.detach();
      const response=await paused.finished();if(response) expect(response.status()).toBe(200);
    });
    // @ts-expect-error a bad fixture option must be rejected by installed types
    test.use({xdebugPort:'wrong'});
    const mapper=new PathMapper();void mapper.toRemote('/app/a.php');
  `;
  fs.writeFileSync(path.join(consumer,'consumer.ts'),typed);fs.writeFileSync(path.join(consumer,'consumer.mts'),typed);
  fs.writeFileSync(path.join(consumer,'tsconfig.json'),JSON.stringify({compilerOptions:{strict:true,noEmit:true,target:'ES2022',module:'NodeNext',moduleResolution:'NodeNext',types:['node']},include:['*.ts','*.mts']}));
  run(process.execPath,[path.join(consumer,'node_modules/typescript/bin/tsc'),'--project',path.join(consumer,'tsconfig.json')],consumer);
  const artifact = path.join(root,'dist/js-candidate',pack.filename);fs.mkdirSync(path.dirname(artifact),{recursive:true});
  fs.copyFileSync(path.join(temp,pack.filename),artifact);
  Object.assign(report,{status:'passed',files:expected,artifact:path.relative(root,artifact),sha256:createHash('sha256').update(fs.readFileSync(artifact)).digest('hex'),checks:['exact package payload','fresh install outside checkout','installed file bytes','CommonJS exports','ESM exports','test-independent core import','installed CJS/ESM TypeScript consumers'],published:false});
  console.log(`Package validation passed: ${expected.length} files; fresh CommonJS/ESM/TypeScript consumers.`);
} catch (error) {
  report.status='failed';report.error=error.message;
  if (error.stderr) console.error(String(error.stderr));
  throw error;
} finally {
  fs.writeFileSync(reportPath,JSON.stringify(report,null,2)+'\n');
  fs.rmSync(temp,{recursive:true,force:true});
}
