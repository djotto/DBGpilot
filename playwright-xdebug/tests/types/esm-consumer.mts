import {test,expect} from 'playwright-xdebug';
import {PathMapper,Listener} from 'playwright-xdebug/core';
test('ESM types resolve',async ({xdebug}) => {expect(typeof xdebug.waitForSession).toBe('function');});
const paths = new PathMapper();
void paths.toRemote('/app/a.php');
void new Listener();
