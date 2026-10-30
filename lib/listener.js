const net = require('node:net');
const { EventEmitter } = require('node:events');
const { Connection, ProtocolError, ConnectionClosed } = require('./dbgp');
const { Session } = require('./session');
const {capture,actionOwner} = require('./capture');
class Listener extends EventEmitter {
  owners = new Map();
  #server;
  #connections = new Set();
  #preparations = new Set();
  #closing;
  #closed = false;
  #starting;
  #address;
  #diagnostics = [];
  constructor({handshakeTimeout = 5000,maxSessions = 256,connectionOptions = {}} = {}) {
    super();
    if (!Number.isFinite(handshakeTimeout) || handshakeTimeout <= 0) throw new TypeError('handshakeTimeout must be positive');
    if (!Number.isSafeInteger(maxSessions) || maxSessions < 1) throw new TypeError('maxSessions must be positive');
    Object.assign(this,{handshakeTimeout,maxSessions,connectionOptions});
  }
  get diagnostics() { return this.#diagnostics.map(error => ({name:error.name,message:error.message,code:error.code})); }
  #diagnostic(error) {
    this.#diagnostics.push(error); if (this.#diagnostics.length > 50) this.#diagnostics.shift();
    this.emit('diagnostic',error);
  }
  listen(port = 9003,host = '127.0.0.1') {
    if (this.#closed) return Promise.reject(new ConnectionClosed('Listener is closed'));
    const address = `${host}:${port}`;
    if (this.#starting) return address === this.#address ? this.#starting : Promise.reject(new Error('Listener is already starting on another address'));
    this.#address = address;
    this.#starting = this.#listen(port,host);
    return this.#starting;
  }
  async #listen(port,host) {
    this.#server = net.createServer(socket => this.#accept(socket));
    await new Promise((resolve,reject) => {
      const failed = error => reject(error.code === 'EADDRINUSE'
        ? new Error(`Port ${host}:${port} is in use. Run Xdebug specs with --workers=1 and close other debugger listeners.`,{cause:error}) : error);
      this.#server.once('error',failed);
      this.#server.listen(port,host,() => {
        this.#server.off('error',failed);
        this.#server.on('error',error => this.#diagnostic(error));
        if (this.#closed) return this.#server.close(() => reject(new ConnectionClosed('Listener closed during startup')));
        this.port = this.#server.address().port;
        this.host = host;
        resolve();
      });
    });
    return this;
  }
  register(owner) {
    if (this.#closed) throw new ConnectionClosed('Listener is closed');
    if (this.owners.has(owner.ideKey)) throw new Error(`Xdebug IDE key is already owned: ${owner.ideKey}`);
    if (owner.disposed) throw new ConnectionClosed('Xdebug owner is disposed');
    owner.listener = this;
    this.owners.set(owner.ideKey,owner);
    return owner;
  }
  unregister(owner) { if (this.owners.get(owner.ideKey) === owner) this.owners.delete(owner.ideKey); }
  close() {
    if (!this.#closing) this.#closing = this.#close();
    return this.#closing;
  }
  async #close() {
    this.#closed = true;
    await this.#starting?.catch(() => {});
    const closed = this.#server?.listening ? new Promise(resolve => this.#server.close(resolve)) : Promise.resolve();
    await Promise.all([...this.owners.values()].map(owner => owner.dispose()));
    // Includes connections that never initialized or are still preparing.
    for (const connection of this.#connections) connection.close();
    await Promise.allSettled([...this.#preparations]);
    this.owners.clear();
    await closed;
  }
  #accept(socket) {
    if (this.#closed || this.#connections.size >= this.maxSessions) {
      socket.destroy();
      this.#diagnostic(new Error('Xdebug listener is closed or at capacity'));
      return;
    }
    const connection = new Connection(socket,this.connectionOptions);
    this.#connections.add(connection);
    const timer = setTimeout(() => connection.close(new ProtocolError('Xdebug initialization timed out')),this.handshakeTimeout);
    connection.once('close',error => {
      clearTimeout(timer);
      this.#connections.delete(connection);
      if (error instanceof ProtocolError) this.#diagnostic(error);
    });
    connection.once('init',init => {
      clearTimeout(timer);
      const task = this.#prepare(connection,init);
      this.#preparations.add(task);
      task.finally(() => this.#preparations.delete(task));
    });
  }
  async #prepare(connection,init) {
    let owner;
    let session;
    try {
      if (init.language?.toLowerCase() !== 'php' || !['1','1.0'].includes(init.protocol_version) || !init.fileuri || !init.appid) {
        throw new ProtocolError('Invalid PHP DBGp initialization metadata');
      }
      owner = this.owners.get(init.idekey);
      session = new Session(connection,init,owner?.sessionOptions);
      if (!owner || owner.disposed || this.#closed) { await session.release(); return; }
      // Track before await so test teardown owns partially prepared requests.
      if (!owner.track(session)) return;
      await session.prepare();
      if (this.#closed || owner.disposed || this.owners.get(init.idekey) !== owner) await session.release();
      else owner.offer(session);
    } catch (error) {
      this.#diagnostic(error);
      owner?.reportError(error);
      if (session) await session.release();
      else connection.close(error);
    }
  }
}
class Xdebug {
  #context;
  #unclaimedTimeout;
  #sessions = new Set();
  #unclaimed = new Map();
  #waiters = [];
  #errors = [];
  #disposing;
  disposed = false;
  captures = new Set();
  captureOperations = new Set();
  capturePages = new Set();
  constructor(context,ideKey,unclaimedTimeout = 2000,{step = (_title,fn) => fn(),listener,...sessionOptions} = {}) {
    if (!Number.isFinite(unclaimedTimeout) || unclaimedTimeout < 0) throw new TypeError('unclaimedTimeout must be nonnegative');
    this.#context = context;
    this.ideKey = ideKey;
    this.#unclaimedTimeout = unclaimedTimeout;
    this.step = step;
    this.sessionOptions = {...sessionOptions,step};
    this.listener = listener;
  }
  createCaptureOwner(ideKey) { return new Xdebug(this.#context,ideKey,this.#unclaimedTimeout,{...this.sessionOptions,listener:this.listener}); }
  capture(page,action,options) { return capture(this,page,action,options); }
  goto(page,url,options = {}) {
    const target = new URL(url);
    if (!['http:','https:'].includes(target.protocol)) return Promise.reject(new TypeError('goto requires an absolute HTTP(S) URL'));
    target.hash = '';
    return this.capture(page,() => page.goto(url,{timeout:options.navigationTimeout ?? 0}),{...options,urlPattern:requestURL => requestURL.href === target.href});
  }
  async enableFor(url) {
    if (this.disposed) throw new ConnectionClosed('Xdebug owner is disposed');
    // Explicit root path covers every request on the enabled hostname.
    const parsed = new URL(url);
    await this.#context.addCookies([{name:'XDEBUG_TRIGGER',value:this.ideKey,url:parsed.origin+'/'}]);
  }
  track(session) {
    if (this.disposed) { void session.release(); return false; }
    this.#sessions.add(session);
    session.once('close',() => {
      this.#sessions.delete(session);
      clearTimeout(this.#unclaimed.get(session));
      this.#unclaimed.delete(session);
    });
    return true;
  }
  reportError(error) {
    if (this.disposed) return;
    if (this.#waiters.length) for (const waiter of [...this.#waiters]) waiter.fail(error);
    else { this.#errors.push(error); if (this.#errors.length > 50) this.#errors.shift(); }
  }
  waitForSession({url,method,timeout = 30000,signal} = {}) {
    return this.step(`xdebug: wait for session${url ? ` ${url}`:''}`,() => {
      if (this.disposed) throw new ConnectionClosed('Xdebug owner is disposed');
      if (!Number.isFinite(timeout) || timeout < 0) throw new TypeError('Timeout must be nonnegative');
      if (signal?.aborted) throw signal.reason;
      if (this.#errors.length) throw this.#errors.shift();
      const matches = session => {
        if (session.connection.closed || (method && session.request.method !== method.toUpperCase())) return false;
        if (url instanceof RegExp) {
          // Stateful /g and /y expressions must not depend on previous matches.
          return new RegExp(url.source,url.flags).test(session.request.uri);
        }
        return url === undefined || session.request.uri.split('?')[0] === url;
      };
      for (const [session,timer] of this.#unclaimed) {
        if (matches(session)) { clearTimeout(timer); this.#unclaimed.delete(session); return session; }
      }
      return new Promise((resolve,reject) => {
        let timer;
        const remove = () => {
          clearTimeout(timer);
          signal?.removeEventListener('abort',abort);
          const index = this.#waiters.indexOf(waiter);
          if (index >= 0) this.#waiters.splice(index,1);
        };
        const waiter = {matches,succeed:session => {remove();resolve(session);},fail:error => {remove();reject(error);}};
        const abort = () => waiter.fail(signal.reason);
        signal?.addEventListener('abort',abort,{once:true});
        if (timeout) timer = setTimeout(() => waiter.fail(new Error(`No Xdebug session${url ? ` for ${url}`:''} within ${timeout}ms. Check the trigger cookie and PHP's debugger connection settings.`)),timeout);
        this.#waiters.push(waiter);
      });
    });
  }
  offer(session) {
    if (this.disposed || session.connection.closed) { void session.release(); return; }
    if (!this.#sessions.has(session) && !this.track(session)) return;
    const waiter = this.#waiters.find(waiter => waiter.matches(session));
    if (waiter) return waiter.succeed(session);
    const timer = setTimeout(() => {
      this.#unclaimed.delete(session);
      void session.release();
    },this.#unclaimedTimeout);
    this.#unclaimed.set(session,timer);
  }
  dispose() {
    if (actionOwner.getStore() === this) return Promise.reject(new Error('Dispose the debugger outside its browser action'));
    if (!this.#disposing) {
      this.disposed = true;
      for (const operation of this.captureOperations) operation.controller.abort(new ConnectionClosed('Debugger disposed during capture'));
      for (const waiter of [...this.#waiters]) waiter.fail(new ConnectionClosed('Test finished while waiting for an Xdebug session'));
      for (const timer of this.#unclaimed.values()) clearTimeout(timer);
      this.#unclaimed.clear();
      this.#disposing = (async () => {
        await Promise.allSettled([...this.captureOperations].map(operation => operation.done));
        await Promise.all([...this.#sessions].map(session => session.release()));
        await Promise.all([...this.captures].map(paused => paused.close()));
        // A successfully completed capture is also in captures; failed setup
        // has already disposed its temporary owner before settling its job.
      })();
    }
    return this.#disposing;
  }
}
module.exports = {Listener,Xdebug};
