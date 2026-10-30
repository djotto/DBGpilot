const fs = require('node:fs');
const path = require('node:path');
const {test,expect,PartialValue} = require('../..');
const file = path.resolve(__dirname,'../fixtures/checkout.php');
const line = fs.readFileSync(file,'utf8').split('\n').findIndex(text => text.includes('BREAKPOINT:'))+1;
test.use({xdebugUnclaimedTimeout:25});
function navigate(page,url) {
  const action = page.goto(url,{timeout:0});
  // Keep rejection handled while the test is inspecting a paused PHP request.
  action.catch(() => {}); return action;
}
test('navigation, snapshot, mutation, stepping, detach and final DOM',async ({page,xdebug}) => {
  const action = navigate(page,'/checkout.php?code=SAVE10');
  const session = await xdebug.waitForSession({url:'/checkout.php',method:'GET'});
  await session.setBreakpoint(file,line,{condition:'$discount === 10',temporary:true});
  expect(await session.runUntilBreak()).toMatchObject({status:'break',file,line});
  const snapshot = await session.snapshot({variables:['$discount','$bigint']});
  expect(snapshot.variables.$discount.value).toBe(10);
  expect(snapshot.variables.$bigint.value.value).toBe('9223372036854775807');
  await session.setVariable('$discount',15); await session.stepOver();
  expect(await session.evaluate('$total')).toBe(85);
  expect(snapshot.variables.$discount.value).toBe(10);
  await session.detach(); expect((await action).status()).toBe(200);
  await expect(page.getByTestId('total')).toHaveText('85');
});
test('binary, large integers, extended names, pagination and nested assignment',async ({page,xdebug}) => {
  const action = navigate(page,'/checkout.php'); const session = await xdebug.waitForSession();
  await session.setBreakpoint(file,line); await session.runUntilBreak();
  expect(await session.getVariable('$binary')).toEqual(Buffer.from([255,0,120]));
  expect(await session.getVariable('$bigint')).toBe(9223372036854775807n);
  expect(await session.getVariable('$spaced')).toBe('  é🙂  ');
  expect(await session.evaluate('INF')).toBe(Infinity);
  expect(await session.getVariable('$big')).toHaveLength(250);
  const binaryKeys = await session.getProperty('$binaryKeys');
  expect(binaryKeys.children[0].name).toEqual(Buffer.from([98,97,100,0,255]));
  expect(await session.getVariable('$binaryKeys')).toBeInstanceOf(PartialValue);
  await session.setVariable('$nested',{list:[1,2.5,'three'],binary:Buffer.from([255,0]),big:9223372036854775807n});
  expect(await session.getVariable('$nested',{depth:2})).toEqual({list:[1,2.5,'three'],binary:Buffer.from([255,0]),big:9223372036854775807n});
  await expect(session.setVariable('$notALocal',1)).rejects.toThrow('existing variable');
  await session.detach(); expect((await action).status()).toBe(200);
});
test('POST form request can be debugged and changed',async ({page,xdebug}) => {
  await page.goto('/checkout.php'); await page.getByRole('textbox').fill('SAVE10');
  const waiting = xdebug.waitForSession({url:'/checkout.php',method:'POST'});
  const action = page.getByRole('button',{name:'Apply',exact:true}).click({timeout:0}); action.catch(() => {});
  const session = await waiting; await session.setBreakpoint(file,line); await session.runUntilBreak();
  expect(await session.evaluate("$_POST['code']")).toBe('SAVE10');
  await session.setVariable('$discount',20); await session.detach(); await action;
  await expect(page.getByTestId('total')).toHaveText('80');
});
test('AJAX dispatch may finish while PHP remains paused',async ({page,xdebug}) => {
  await page.goto('/checkout.php');
  const waiting = xdebug.waitForSession({url:/checkout\.php\?json=1/,method:'GET'});
  await page.getByRole('button',{name:'AJAX',exact:true}).click();
  const session = await waiting; await session.setBreakpoint(file,line); await session.runUntilBreak();
  await expect(page.getByTestId('total')).toHaveText('100');
  await session.setVariable('$discount',25); await session.detach();
  await expect(page.getByTestId('total')).toHaveText('75');
});
test('late breakpoint response recovers within the same test',async ({page,xdebug}) => {
  const action = navigate(page,'/checkout.php?slow=1'); const session = await xdebug.waitForSession();
  await session.setBreakpoint(file,line);
  await expect(session.runUntilBreak({timeout:10})).rejects.toThrow('timed out');
  expect((await session.waitForPause()).status).toBe('break');
  expect(await session.evaluate('$subtotal')).toBe(100);
  await session.detach(); expect((await action).status()).toBe(200);
});
test('exceptions and missed breakpoints do not hang requests',async ({page,xdebug}) => {
  const action = navigate(page,'/checkout.php?exception=1'); const session = await xdebug.waitForSession();
  await session.setExceptionBreakpoint('RuntimeException'); await session.runUntilBreak();
  expect((await session.stack())[0].where).toBe('checkout');
  await session.detach(); expect((await action).status()).toBe(500);
  const next = navigate(page,'/checkout.php'); const second = await xdebug.waitForSession();
  await expect(second.runUntilBreak()).rejects.toThrow('finished without hitting');
  expect((await next).status()).toBe(200);
});
test('intentional assertion failure releases paused PHP at teardown',async ({page,xdebug}) => {
  navigate(page,'/checkout.php'); const session = await xdebug.waitForSession();
  await session.setBreakpoint(file,line); await session.runUntilBreak();
  test.fail(); expect(false).toBe(true);
});
test('next request completes after failed-test teardown and unclaimed release',async ({page,xdebug}) => {
  expect((await page.goto('/checkout.php')).status()).toBe(200);
});
