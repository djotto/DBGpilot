import {test,expect,PathMapper,Session,toJSONSafe} from 'playwright-xdebug';
import {Listener,Xdebug,PartialValue} from 'playwright-xdebug/core';
test.use({xdebugPort:9003,xdebugPathMappings:[{local:'C:\\Site',remote:'file:///app'}]});
test('typed fixture',async ({page,xdebug}) => {
  const paused = await xdebug.goto(page,'http://localhost/',{breakpoints:[{file:'C:\\Site\\index.php',line:10}],variables:['$x']});
  expect(paused.snapshot.variables.$x.value).toBe(10);
  await paused.session.setVariable('$x',42n);await paused.session.detach();await paused.finished();
});
async function standalone(session:Session) {
  // @ts-expect-error sessions are supplied by the debugger, not constructed from raw connections
  new Session(null as never,{});
  // @ts-expect-error raw transport is not part of the public session contract
  void session.connection;
  const capabilities = await session.getCapabilities();
  const canEvaluate:boolean = capabilities.eval.enabled;
  const canInterrupt:boolean = capabilities.supports_async.enabled;
  void canEvaluate;void canInterrupt;
  // @ts-expect-error capability queries always return the full inventory
  await session.getCapabilities(['eval']);
  // @ts-expect-error capability inventories are not cached on sessions
  void session.capabilities;
  // @ts-expect-error replaced by getCapabilities()
  await session.refreshCapabilities();
  const value = await session.getVariable('$x');
  if (value instanceof PartialValue) console.log(value.totalChildren);
  const paths = new PathMapper([{local:'/work',remote:'file:///app'}]);
  const listener = new Listener();listener.register(new Xdebug(undefined,'cli',2000));
  console.log(paths.toRemote('/work/x.php'),toJSONSafe(value));
  // @ts-expect-error typed assignments must not silently accept Date objects
  await session.setVariable('$x',new Date());
  // @ts-expect-error invalid fixture option
  test.use({xdebugPort:'wrong'});
}
void standalone;
