const fs = require('node:fs');
const path = require('node:path');
const {test,expect} = require('../..');
const file = path.resolve(__dirname,'../fixtures/checkout.php');
const line = fs.readFileSync(file,'utf8').split('\n').findIndex(text => text.includes('BREAKPOINT:'))+1;
const breakpoints = [{file,line}];
test('navigation stays alive for a 35-second interactive PHP pause',async ({page,xdebug,baseURL}) => {
  const paused = await xdebug.goto(page,baseURL+'/checkout.php?code=SAVE10',{breakpoints,timeout:5000});
  await new Promise(resolve => setTimeout(resolve,35000));
  expect(paused.session.state).toBe('break'); expect(await paused.session.evaluate('$discount')).toBe(10);
  await paused.session.setVariable('$discount',15); await paused.session.detach();
  expect((await paused.finished()).status()).toBe(200); await expect(page.getByTestId('total')).toHaveText('85');
});
test('three browser captures pause independently and releasing one leaves the others paused',async ({context,xdebug,baseURL}) => {
  const pages = await Promise.all([context.newPage(),context.newPage(),context.newPage()]);
  const captures = await Promise.all(pages.map((page,index) => xdebug.goto(page,`${baseURL}/checkout.php?request=${index}`,{breakpoints})));
  expect(new Set(captures.map(paused => paused.session.id)).size).toBe(3);
  for (let index=0;index<captures.length;index++) {
    const paused = captures[index]; await paused.session.setVariable('$discount',10+index); await paused.session.detach();
    expect((await paused.finished()).status()).toBe(200); await expect(pages[index].getByTestId('total')).toHaveText(String(90-index));
    for (const other of captures.slice(index+1)) expect(other.session.state).toBe('break');
  }
});
