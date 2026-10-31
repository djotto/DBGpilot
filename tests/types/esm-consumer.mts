import {test,expect} from 'dbgpilot';
import {PathMapper,Listener} from 'dbgpilot/core';
test('ESM types resolve',async ({xdebug}) => {expect(typeof xdebug.waitForSession).toBe('function');});
const paths = new PathMapper();
void paths.toRemote('/app/a.php');
void new Listener();
