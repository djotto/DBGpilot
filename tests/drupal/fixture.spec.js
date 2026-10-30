// Proof that the fixture can pause, inspect, change and release real Drupal
// requests. Breakpoints are in code that runs on every request, cached or
// not. Run with --workers=1: only one process can listen on port 9003.

const path = require('path');
const fs = require('fs');
const { test, expect, PartialValue } = require('../..');

const docroot = path.resolve(__dirname, '../..', 'fixtures/drupal11/web');
const serverRoot = process.env.PW_DRUPAL_ROOT ?? '/var/www/html/web';
const INDEX = path.posix.join(serverRoot, 'index.php');
const KERNEL = path.posix.join(serverRoot, 'core/lib/Drupal/Core/DrupalKernel.php');
function lineIn(relative, statement) {
  const lines = fs.readFileSync(path.join(docroot, relative), 'utf8').split('\n');
  const matches = lines.flatMap((line,index) => line.includes(statement) ? [index+1] : []);
  if (matches.length !== 1) throw new Error(`Expected one ${statement} in ${relative}`);
  return matches[0];
}
const INDEX_LINE = lineIn('index.php', 'return new DrupalKernel');
// DrupalKernel::handle(): `$response = $this->getHttpKernel()->handle(...)`
// and `$response->prepare($request)`. Re-check if core is updated.
const KERNEL_HANDLE = lineIn('core/lib/Drupal/Core/DrupalKernel.php', '$response = $this->getHttpKernel()->handle');
const KERNEL_PREPARE = lineIn('core/lib/Drupal/Core/DrupalKernel.php', '$response->prepare($request)');

test('pauses a page request at a breakpoint and lets it finish', async ({ page, xdebug }) => {
  const navigation = page.goto('/?probe=1', {timeout: 0}); navigation.catch(() => {});
  const session = await xdebug.waitForSession({ url: '/' });
  expect(session.request).toEqual({ method: 'GET', uri: '/?probe=1' });

  await session.setBreakpoint(INDEX, INDEX_LINE);
  expect(await session.runUntilBreak()).toMatchObject({ status: 'break', file: INDEX, line: INDEX_LINE });
  expect((await session.stack())[0]).toMatchObject({ file: INDEX, line: INDEX_LINE });
  expect(await session.evaluate(`$_GET['probe']`)).toBe('1');

  await session.detach();
  expect((await navigation).status()).toBe(200);
});

test('inspects and changes state inside Drupal core', async ({ page, xdebug }) => {
  const navigation = page.goto('/', {timeout: 0}); navigation.catch(() => {});
  const session = await xdebug.waitForSession({ url: '/' });
  await session.setBreakpoint(KERNEL, KERNEL_HANDLE);
  await session.runUntilBreak();

  const locals = await session.locals();
  expect(locals.$request.__class).toBe('Symfony\\Component\\HttpFoundation\\Request');
  expect(locals.$request.headers).toBeInstanceOf(PartialValue);
  expect(locals.$request.headers.classname).toBe('Symfony\\Component\\HttpFoundation\\HeaderBag');
  expect(locals.$catch).toBe(true);
  const request = await session.getVariable('$request', { depth: 2 });
  expect(request.headers.__class).toBe('Symfony\\Component\\HttpFoundation\\HeaderBag');
  expect(await session.evaluate('$request->getMethod()')).toBe('GET');

  // JS -> PHP -> JS round trip, nested two levels deep. $response is unset
  // here and overwritten by the next line PHP runs, so this is harmless.
  await session.setVariable('$response', { list: [1, 2.5, 'three'], flag: false, none: null });
  expect(await session.getVariable('$response', { depth: 2 }))
    .toEqual({ list: [1, 2.5, 'three'], flag: false, none: null });
  await expect(session.setVariable('$notALocal', 1)).rejects.toThrow('must be an existing variable');

  // Step past the HTTP kernel, then change the response PHP sends.
  await session.setBreakpoint(KERNEL, KERNEL_PREPARE);
  expect(await session.run()).toMatchObject({ status: 'break', line: KERNEL_PREPARE });
  expect(await session.evaluate('$response->getStatusCode()')).toBe(200);
  await session.evaluate(`$response->headers->set('X-Xdebug-Probe', 'changed')`);

  await session.detach();
  expect((await navigation).headers()['x-xdebug-probe']).toBe('changed');
});

test('breaks on an exception', async ({ page, xdebug }) => {
  const navigation = page.goto('/this-page-does-not-exist-xdebug', {timeout: 0}); navigation.catch(() => {});
  const session = await xdebug.waitForSession();
  await session.setExceptionBreakpoint('Symfony\\Component\\HttpKernel\\Exception\\NotFoundHttpException');
  await session.runUntilBreak();
  expect((await session.stack())[0].where).toContain('->');

  await session.detach();
  expect((await navigation).status()).toBe(404);
});

test('releases requests nobody waits for, so pages still load', async ({ page, xdebug }) => {
  expect((await page.goto('/')).status()).toBe(200);
});

test('runUntilBreak fails, without hanging the page, if no breakpoint is hit', async ({ page, xdebug }) => {
  const navigation = page.goto('/', {timeout: 0}); navigation.catch(() => {});
  const session = await xdebug.waitForSession();
  await session.setBreakpoint(INDEX, 1); // Not executable: never hit.
  await expect(session.runUntilBreak()).rejects.toThrow('finished without hitting a breakpoint');
  expect((await navigation).status()).toBe(200);
});
