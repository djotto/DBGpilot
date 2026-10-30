const {AsyncLocalStorage} = require('node:async_hooks');
const {randomUUID} = require('node:crypto');
const actionOwner = new AsyncLocalStorage();
function waitFor(promise,{timeout = 0,signal} = {}) {
  if (!Number.isFinite(timeout) || timeout < 0) return Promise.reject(new TypeError('Invalid wait timeout'));
  // Attach handlers even when already aborted: work already started may reject.
  return new Promise((resolve,reject) => {
    let timer;
    const cleanup = () => { clearTimeout(timer); signal?.removeEventListener('abort',abort); };
    const done = fn => value => {cleanup();fn(value);};
    const abort = () => done(reject)(signal.reason);
    Promise.resolve(promise).then(done(resolve),done(reject));
    if (signal?.aborted) return abort();
    signal?.addEventListener('abort',abort,{once:true});
    if (timeout) timer = setTimeout(() => done(reject)(new Error(`Wait timed out after ${timeout}ms`)),timeout);
  });
}
async function settleAction(action) {
  if (!action) return;
  await waitFor(action.catch(() => {}),{timeout:1000}).catch(() => {});
}
class PausedBrowser {
  #close;
  constructor({session,snapshot,action,owner,child,page,removeRoute}) {
    Object.assign(this,{session,snapshot,action,owner,child,page,removeRoute});
  }
  finished(options = {}) { return waitFor(this.action,{timeout:30000,...options}); }
  close() {
    if (actionOwner.getStore() === this.owner) return Promise.reject(new Error('Close the capture outside its browser action'));
    if (!this.#close) this.#close = (async () => {
      try { await this.child.dispose(); }
      finally {
        this.owner.listener.unregister(this.child);
        try { await settleAction(this.action); await this.removeRoute(); }
        finally { this.owner.captures.delete(this); }
      }
    })();
    return this.#close;
  }
}
async function capture(owner,page,action,{
  urlPattern,method,breakpoints = [],variables = [],expressions = [],timeout = 30000,ideKey,signal,
} = {}) {
  if (owner.disposed) throw new Error('Xdebug owner is disposed');
  if (!owner.listener) throw new Error('Register the debugger with a Listener before capturing');
  if (!urlPattern || typeof action !== 'function') throw new TypeError('capture requires urlPattern and an action function');
  if (!Number.isFinite(timeout) || timeout <= 0 || timeout > 300000) throw new TypeError('Capture timeout must be greater than zero and at most 300000ms');
  if (owner.capturePages.has(page)) throw new Error('A capture is already active on this page');
  if (!Array.isArray(breakpoints) || breakpoints.some(point => !point || typeof point !== 'object')) throw new TypeError('Breakpoints must be specification objects');
  const controller = new AbortController();
  const operation = {controller};
  const abort = () => controller.abort(signal.reason);
  if (signal?.aborted) abort();
  signal?.addEventListener('abort',abort,{once:true});
  const timer = setTimeout(() => controller.abort(new Error(`Breakpoint capture timed out after ${timeout}ms`)),timeout);
  owner.capturePages.add(page);
  owner.captureOperations.add(operation);
  operation.done = perform();
  try { return await operation.done; }
  finally {
    clearTimeout(timer); signal?.removeEventListener('abort',abort);
    owner.capturePages.delete(page); owner.captureOperations.delete(operation);
  }
  async function perform() {
    // Independent per-action IDE keys prevent unrelated requests/pages from
    // claiming this capture. Explicit keys must be allowed by PHP and unique.
    const child = owner.createCaptureOwner(ideKey ?? `capture-${randomUUID()}`);
    let routed = false, selected = false, browser, failure;
    const route = async intercepted => {
      if (selected || (method && intercepted.request().method() !== method.toUpperCase())) return intercepted.fallback();
      selected = true;
      const url = new URL(intercepted.request().url());
      url.searchParams.set('XDEBUG_SESSION',child.ideKey);
      url.searchParams.set('XDEBUG_TRIGGER',child.ideKey);
      await intercepted.continue({url:url.href});
    };
    const bounded = promise => waitFor(promise,{signal:controller.signal});
    try {
      owner.listener.register(child);
      routed = true;
      await bounded(page.route(urlPattern,route));
      const waiting = child.waitForSession({timeout:0,signal:controller.signal});
      browser = Promise.resolve().then(() => actionOwner.run(owner,action));
      // Success can mean an AJAX click only dispatched the request. Only action
      // failures race attachment/configuration/snapshot capture.
      const actionFailure = browser.then(() => new Promise(() => {}));
      actionFailure.catch(() => {});
      const race = promise => bounded(Promise.race([promise,actionFailure]));
      const session = await race(waiting);
      for (const point of breakpoints) {
        const {file,line,...options} = point;
        await race(session.setBreakpoint(file,line,options));
      }
      await race(session.runUntilBreak({timeout:0}));
      const snapshot = await race(session.snapshot({variables,expressions}));
      // Chromium Fetch.disable can wait for a paused navigation's response.
      // Keep this logically one-shot handler (selected=true => fallback), and
      // remove it after PHP is released rather than deadlocking capture return.
      const removeRoute = () => waitFor(page.unroute(urlPattern,route),{timeout:2000});
      const paused = new PausedBrowser({session,snapshot,action:browser,owner,child,page,removeRoute});
      owner.captures.add(paused);
      routed = false; // The returned handle now owns physical route cleanup.
      return paused;
    } catch (error) {
      failure = error;
      controller.abort(error);
      owner.listener.unregister(child);
      await child.dispose();
      await settleAction(browser);
      throw error;
    } finally {
      if (routed) {
        try { await waitFor(page.unroute(urlPattern,route),{timeout:2000}); }
        catch (error) { if (failure) failure.cleanupError = error; else throw error; }
      }
    }
  }
}
module.exports = {capture,PausedBrowser,actionOwner,waitFor};
