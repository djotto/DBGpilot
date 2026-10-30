import type {TestType,PlaywrightTestArgs,PlaywrightTestOptions,PlaywrightWorkerArgs,PlaywrightWorkerOptions} from '@playwright/test';
import type {Xdebug,PathMapping} from './core';
export * from './core';
export {expect} from '@playwright/test';
export interface XdebugTestOptions {
  xdebugUnclaimedTimeout:number;xdebugIdeKey:string|undefined;xdebugPathMappings:PathMapping[];xdebugBaseDir:string|undefined;
}
export interface XdebugWorkerOptions {xdebugHost:string;xdebugPort:number}
export const test:TestType<PlaywrightTestArgs&PlaywrightTestOptions&XdebugTestOptions&{xdebug:Xdebug},PlaywrightWorkerArgs&PlaywrightWorkerOptions&XdebugWorkerOptions>;
