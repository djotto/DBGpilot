const path = require('node:path');
const fs = require('node:fs');
const {spawn,execFile} = require('node:child_process');
const {promisify} = require('node:util');
const {test,expect} = require('../..');
test('standalone Node example uses Playwright and the debugger without the test fixture',async () => {
  const root = path.resolve(__dirname,'../fixtures');
  const file = path.join(root,'checkout.php');
  const line = fs.readFileSync(file,'utf8').split('\n').findIndex(text => text.includes('BREAKPOINT:'))+1;
  const original = fs.readFileSync(file);
  const server = spawn('php',['-d','xdebug.mode=debug','-d','xdebug.start_with_request=trigger','-d','xdebug.client_host=127.0.0.1','-d','xdebug.client_port=19533','-S','127.0.0.1:19534','-t',root],{stdio:['ignore','ignore','pipe']});
  let diagnostic = '';server.stderr.on('data',chunk => diagnostic += chunk);server.on('error',error => diagnostic += error.message);
  try {
    let ready = false;
    for (let i=0;i<40;i++) {
      try {const reply = await fetch('http://127.0.0.1:19534/checkout.php',{signal:AbortSignal.timeout(500)});await reply.text();ready = true;break;}
      catch {await new Promise(resolve => setTimeout(resolve,50));}
    }
    expect(ready,diagnostic).toBe(true);
    const result = await promisify(execFile)(process.execPath,[path.resolve(__dirname,'../../examples/standalone.js')],{
      timeout:15000,env:{...process.env,DBGPILOT_SCRIPT_URL:'http://127.0.0.1:19534/checkout.php?code=SAVE10',DBGPILOT_SCRIPT_PORT:'19533',DBGPILOT_SCRIPT_FILE:file,DBGPILOT_SCRIPT_LINE:String(line)},
    });
    expect(result.stdout).toContain('HTTP status: 200');
    const snapshot = JSON.parse(result.stdout.slice(0,result.stdout.indexOf('HTTP status:')).trim());
    expect(snapshot.execution.status).toBe('break');expect(snapshot.frames[0].where).toBe('checkout');
    expect(fs.readFileSync(file)).toEqual(original);
  } finally {server.kill('SIGTERM');}
});
