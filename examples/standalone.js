// DBGPILOT_SCRIPT_URL=http://localhost/checkout DBGPILOT_SCRIPT_FILE=/var/www/html/src/Checkout.php
// DBGPILOT_SCRIPT_LINE=42 node examples/standalone.js
const {randomUUID} = require('node:crypto');
const {chromium} = require('playwright');
const {Listener,Xdebug} = require('dbgpilot/core');

async function main() {
  const url = process.env.DBGPILOT_SCRIPT_URL;
  const file = process.env.DBGPILOT_SCRIPT_FILE;
  const line = Number(process.env.DBGPILOT_SCRIPT_LINE);
  if (!url || !file || !Number.isSafeInteger(line) || line < 1) {
    throw new Error('Set DBGPILOT_SCRIPT_URL, DBGPILOT_SCRIPT_FILE (PHP server path), and DBGPILOT_SCRIPT_LINE');
  }
  const controller = new AbortController();
  const interrupted = () => controller.abort(new Error('Investigation interrupted'));
  process.once('SIGTERM',interrupted);process.once('SIGINT',interrupted);
  const listener = new Listener();
  let browser,action;
  try {
    await listener.listen(Number(process.env.DBGPILOT_SCRIPT_PORT ?? 9003),process.env.DBGPILOT_SCRIPT_HOST ?? '127.0.0.1');
    browser = await chromium.launch();
    const context = await browser.newContext();
    const xdebug = listener.register(new Xdebug(context,process.env.DBGPILOT_SCRIPT_IDEKEY ?? randomUUID()));
    const page = await context.newPage();
    const paused = await xdebug.goto(page,url,{breakpoints:[{file,line}],signal:controller.signal});
    action = paused.action;
    console.log(JSON.stringify(paused.snapshot,null,2));
    // Add further inspection, mutation and assertions here, in this process.
    await paused.session.detach();
    console.log(`HTTP status: ${(await paused.finished()).status()}`);
    await paused.close();
  } finally {
    try { await listener.close(); }
    finally {
      try { await browser?.close(); }
      finally {
        await action?.catch(() => {});
        process.off('SIGTERM',interrupted);process.off('SIGINT',interrupted);
      }
    }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
