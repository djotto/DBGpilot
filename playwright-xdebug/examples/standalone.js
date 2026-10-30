// DEBUG_URL=http://localhost/checkout DEBUG_FILE=/var/www/html/src/Checkout.php
// DEBUG_LINE=42 node playwright-xdebug/examples/standalone.js
const {randomUUID} = require('node:crypto');
const {chromium} = require('playwright');
const {Listener,Xdebug,toJSONSafe} = require('playwright-xdebug/core');

async function main() {
  const url = process.env.DEBUG_URL;
  const file = process.env.DEBUG_FILE;
  const line = Number(process.env.DEBUG_LINE);
  if (!url || !file || !Number.isSafeInteger(line) || line < 1) {
    throw new Error('Set DEBUG_URL, DEBUG_FILE (PHP server path), and DEBUG_LINE');
  }
  const listener = new Listener();
  let browser;
  let action;
  let xdebug;
  try {
    await listener.listen(Number(process.env.DEBUG_PORT ?? 9003),process.env.DEBUG_HOST ?? '127.0.0.1');
    browser = await chromium.launch();
    const context = await browser.newContext();
    xdebug = new Xdebug(context,process.env.DEBUG_IDEKEY ?? randomUUID());
    listener.owners.set(xdebug.ideKey,xdebug);
    await xdebug.enableFor(url);
    const page = await context.newPage();
    const waiting = xdebug.waitForSession({url:new URL(url).pathname});
    action = page.goto(url,{timeout:0});
    action.catch(() => {});
    const session = await waiting;
    await session.setBreakpoint(file,line);
    await session.runUntilBreak();
    console.log(JSON.stringify(toJSONSafe(await session.snapshot()),null,2));
    // Add further inspection, mutation and assertions here, in this process.
    await session.detach();
    console.log('HTTP status:',(await action).status());
  } finally {
    try { await listener.close(); }
    finally {
      try { await browser?.close(); }
      finally { await action?.catch(() => {}); }
    }
  }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
