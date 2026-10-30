const fs = require('node:fs');
const path = require('node:path');
const {test,expect} = require('../..');
const file = path.resolve(__dirname,'../fixtures/checkout.php');
const line = fs.readFileSync(file,'utf8').split('\n').findIndex(text => text.includes('BREAKPOINT:'))+1;
const breakpoints = [{file,line}];
test.use({xdebugUnclaimedTimeout:25});
test('goto returns a copied snapshot while PHP and browser navigation stay paused',async ({page,xdebug,baseURL}) => {
  const paused = await xdebug.goto(page,baseURL+'/checkout.php?code=SAVE10#total',{breakpoints,variables:['$discount']});
  expect(paused.snapshot.variables.$discount.value).toBe(10);
  await paused.session.setVariable('$discount',15); await paused.session.stepOver();
  expect(await paused.session.evaluate('$total')).toBe(85);
  expect(paused.snapshot.variables.$discount.value).toBe(10);
  await expect(paused.finished({timeout:20})).rejects.toThrow('timed out');
  expect(paused.session.state).toBe('break');
  await paused.session.detach(); expect((await paused.finished()).status()).toBe(200);
  await expect(page.getByTestId('total')).toHaveText('85');
  await paused.close(); expect(xdebug.captures.size).toBe(0);
});
test('capture preserves POST body and method while correlating one form submission',async ({page,xdebug}) => {
  await page.goto('/checkout.php'); await page.getByRole('textbox').fill('SAVE10');
  const paused = await xdebug.capture(page,() => page.getByRole('button',{name:'Apply',exact:true}).click({timeout:0}),{
    urlPattern:'**/checkout.php',method:'POST',breakpoints,expressions:["$_POST['code']"],
  });
  expect(paused.snapshot.expressions["$_POST['code']"].value).toBe('SAVE10');
  expect(paused.session.request.method).toBe('POST');
  await paused.session.setVariable('$discount',20); await paused.session.detach(); await paused.finished();
  await expect(page.getByTestId('total')).toHaveText('80');
});
test('successful AJAX action completion does not end breakpoint capture or resume PHP',async ({page,xdebug}) => {
  await page.goto('/checkout.php');
  const paused = await xdebug.capture(page,() => page.getByRole('button',{name:'AJAX',exact:true}).click(),{
    urlPattern:'**/checkout.php?json=1*',breakpoints,variables:['$discount'],
  });
  await paused.finished(); expect(paused.session.state).toBe('break');
  await expect(page.getByTestId('total')).toHaveText('100');
  await paused.session.setVariable('$discount',25); await paused.session.detach();
  await expect(page.getByTestId('total')).toHaveText('75');
});
test('action errors and capture deadlines clean routes and temporary owners for retry',async ({page,xdebug,baseURL,_xdebugListener}) => {
  await expect(xdebug.capture(page,async () => {throw new Error('action failed');},{urlPattern:'**/*',breakpoints})).rejects.toThrow('action failed');
  expect(_xdebugListener.owners.size).toBe(1);
  await expect(xdebug.capture(page,async () => {},{urlPattern:'**/*',breakpoints,timeout:25})).rejects.toThrow('capture timed out');
  expect(_xdebugListener.owners.size).toBe(1);
  const paused = await xdebug.goto(page,baseURL+'/checkout.php',{breakpoints});
  await paused.close(); expect((await paused.finished()).status()).toBe(200);
});
test('setup failure after attachment releases PHP and permits a subsequent capture',async ({page,xdebug,baseURL}) => {
  await expect(xdebug.goto(page,baseURL+'/checkout.php',{breakpoints:[{file,line:0}]})).rejects.toThrow('positive line');
  const next = await xdebug.goto(page,baseURL+'/checkout.php',{breakpoints});
  await next.close(); expect((await next.finished()).status()).toBe(200);
});
test('dispose cancels pending capture setup and cannot deadlock inside a browser action',async ({page,xdebug}) => {
  await expect(xdebug.capture(page,() => xdebug.dispose(),{urlPattern:'**/*',breakpoints})).rejects.toThrow('outside its browser action');
  const abort = new AbortController();
  const waiting = xdebug.capture(page,async () => {},{urlPattern:'**/*',breakpoints,signal:abort.signal});
  abort.abort(new Error('cancelled capture'));
  await expect(waiting).rejects.toThrow('cancelled capture');
  const pending = xdebug.capture(page,async () => {},{urlPattern:'**/*',breakpoints});
  const rejected = expect(pending).rejects.toThrow('disposed during capture');
  await xdebug.dispose(); await rejected;
});
