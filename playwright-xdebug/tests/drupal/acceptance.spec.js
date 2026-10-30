const fs = require('node:fs');
const path = require('node:path');
const {randomUUID} = require('node:crypto');
const {test,expect} = require('../..');
const fixture = path.resolve(__dirname,'../../../fixtures/drupal11');
const state = JSON.parse(fs.readFileSync(path.join(fixture,'fixture-state.json'),'utf8'));
const web = path.join(fixture,'web');
test.use({baseURL:state.test_url,xdebugPathMappings:[{local:web,remote:'file:///var/www/html/web'}]});
function point(relative,statement) {
  const file = path.join(web,relative);
  const matches = fs.readFileSync(file,'utf8').split('\n').flatMap((line,index) => line.includes(statement) ? [index+1]:[]);
  if (matches.length !== 1) throw new Error(`Expected one ${statement} in ${file}`);
  return {file,line:matches[0]};
}
async function login(page) {
  await page.goto('/user/login');
  await page.locator('input[name="name"]').fill('admin');
  await page.locator('input[name="pass"]').fill('dbgpilot-admin');
  await page.getByRole('button',{name:'Log in',exact:true}).click();
  expect((await page.goto('/node/add/page')).status()).toBe(200);
  await expect(page.locator('input[name="title[0][value]"]')).toBeVisible();
}
async function record(name,snapshot,details) {
  await test.info().attach(`${name}.json`,{body:JSON.stringify({runtime:state,snapshot,...details},null,2),contentType:'application/json'});
}
test('core render mutation affects this response without changing the database',async ({page,xdebug,baseURL}) => {
  const breakpoint = point('core/lib/Drupal/Core/Entity/Controller/EntityViewController.php','$page = $this->entityTypeManager');
  const paused = await xdebug.goto(page,baseURL+state.node_path,{breakpoints:[breakpoint],variables:['$_entity','$view_mode'],expressions:['$_entity->id()','$_entity->label()']});
  expect(paused.snapshot.expressions['$_entity->label()'].value).toBe(state.node_title);
  expect(String(paused.snapshot.expressions['$_entity->id()'].value)).toBe(String(state.node_id));
  expect(paused.snapshot.execution.localFile).toBe(breakpoint.file);
  expect(paused.snapshot.frames.some(frame => frame.where?.includes('{fiber:'))).toBe(true);
  expect(paused.snapshot.frames.some(frame => frame.fileUri?.includes('/Render/Renderer.php'))).toBe(true);
  const changed = 'DBGpilot JS changed this request';
  await paused.session.evaluate(`$_entity->setTitle(${JSON.stringify(changed)})`);
  await paused.session.stepOver(); await paused.session.detach();
  expect((await paused.finished()).status()).toBe(200);
  await expect(page.getByRole('heading',{level:1})).toHaveText(changed);
  await paused.close(); await page.goto(state.node_path);
  await expect(page.getByRole('heading',{level:1})).toHaveText(state.node_title);
  await record('core-render',paused.snapshot,{renderedTitle:changed,persistedTitle:state.node_title});
});
test('Form API save persists a PHP mutation and a fresh request reads it',async ({page,xdebug}) => {
  await login(page);
  const proposed = `DBGpilot JS page ${randomUUID().slice(0,8)}`;
  const persisted = proposed+' changed in PHP';
  await page.locator('input[name="title[0][value]"]').fill(proposed);
  const breakpoint = point('core/modules/node/src/Form/NodeForm.php','$node->save();');
  let createdPath,paused;
  try {
    paused = await xdebug.capture(page,() => page.getByRole('button',{name:'Save',exact:true}).click({timeout:0}),{
      urlPattern:url => url.pathname.includes('/node/add/page'),method:'POST',breakpoints:[breakpoint],
      variables:['$node','$insert'],expressions:['$node->label()','$node->isNew()'],
    });
    expect(paused.snapshot.expressions['$node->label()'].value).toBe(proposed);
    expect(paused.snapshot.expressions['$node->isNew()'].value).toBe(true);
    expect(paused.snapshot.frames.some(frame => frame.fileUri?.includes('/Form/FormSubmitter.php'))).toBe(true);
    await paused.session.evaluate(`$node->setTitle(${JSON.stringify(persisted)})`);
    await paused.session.stepOver(); createdPath = '/node/'+String(await paused.session.evaluate('$node->id()'));
    await paused.session.detach(); await paused.finished(); await paused.close();
    await page.waitForURL('**'+createdPath);
    await expect(page.getByRole('heading',{level:1})).toHaveText(persisted);
    await page.goto(createdPath); await expect(page.getByRole('heading',{level:1})).toHaveText(persisted);
    expect(paused.snapshot.expressions['$node->label()'].value).toBe(proposed);
    await record('form-save',paused.snapshot,{proposedTitle:proposed,persistedTitle:persisted,nodePath:createdPath});
  } finally {
    await paused?.close();
    if (createdPath) {
      await page.goto(createdPath+'/delete'); await page.getByRole('button',{name:'Delete',exact:true}).click();
    }
  }
});
test('author autocomplete AJAX pauses before the database query and returns the mutated search',async ({page,xdebug}) => {
  await login(page);
  const author = page.locator('input[name="uid[0][target_id]"]');
  await author.evaluate(element => {
    for (let parent = element.parentElement;parent;parent = parent.parentElement) if (parent.tagName === 'DETAILS') parent.open = true;
  });
  await author.fill('');
  const breakpoint = point('core/modules/system/src/Controller/EntityAutocompleteController.php','$matches = $this->matcher->getMatches');
  const paused = await xdebug.capture(page,() => author.fill('adm'),{
    urlPattern:url => url.pathname.includes('/entity_reference_autocomplete/user/'),breakpoints:[breakpoint],variables:['$target_type','$typed_string'],
  });
  expect(paused.snapshot.variables.$target_type.value).toBe('user');
  expect(paused.snapshot.variables.$typed_string.value).toBe('adm');
  await paused.finished(); expect(paused.session.state).toBe('break');
  await paused.session.setVariable('$typed_string','admin'); await paused.session.stepOver();
  const count = await paused.session.evaluate('count($matches)'); expect(count).toBeGreaterThanOrEqual(1);
  await paused.session.detach();
  await expect(page.locator('.ui-autocomplete .ui-menu-item').filter({hasText:'admin'}).first()).toBeVisible();
  await record('author-autocomplete',paused.snapshot,{query:'admin',resultCount:count});
});
