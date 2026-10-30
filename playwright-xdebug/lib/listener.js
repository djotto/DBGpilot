const net = require('node:net');
const { EventEmitter } = require('node:events');
const { Connection, ProtocolError, ConnectionClosed } = require('./dbgp');
const { Session } = require('./session');
class Listener extends EventEmitter {
  owners = new Map();
  #server;
  #connections = new Set();
  #preparations = new Set();
  #closing;
  #closed = false;
  constructor({handshakeTimeout = 5000,maxSessions = 256,connectionOptions = {}} = {}) {
    super();
    if (!Number.isFinite(handshakeTimeout) || handshakeTimeout <= 0) throw new TypeError('handshakeTimeout must be positive');
    if (!Number.isSafeInteger(maxSessions) || maxSessions < 1) throw new TypeError('maxSessions must be positive');
    Object.assign(this,{handshakeTimeout,maxSessions,connectionOptions});
  }
  async listen(port = 9003,host = '127.0.0.1') {
    if (this.#server || this.#closed) throw new Error('Listener has already started or closed');
    this.#server = net.createServer(socket => this.#accept(socket));
    await new Promise((resolve,reject) => {
      const failed = error => reject(error.code === 'EADDRINUSE'
        ? new Error(`Port ${host}:${port} is in use. Run Xdebug specs with --workers=1 and close other debugger listeners.`,{cause:error}) : error);
      this.#server.once('error',failed);
      this.#server.listen(port,host,() => {
        this.#server.off('error',failed);
        this.#server.on('error',error => this.emit('diagnostic',error));
        this.port = this.#server.address().port;
        this.host = host;
        resolve();
      });
    });
    return this;
  }
  close() {
    if (!this.#closing) this.#closing = this.#close();
    return this.#closing;
  }
  async #close() {
    this.#closed = true;
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
      this.emit('diagnostic',new Error('Xdebug listener is closed or at capacity'));
      return;
    }
    const connection = new Connection(socket,this.connectionOptions);
    this.#connections.add(connection);
    const timer = setTimeout(() => connection.close(new ProtocolError('Xdebug initialization timed out')),this.handshakeTimeout);
    connection.once('close',error => {
      clearTimeout(timer);
      this.#connections.delete(connection);
      if (error instanceof ProtocolError) this.emit('diagnostic',error);
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
      this.emit('diagnostic',error);
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
  constructor(context,ideKey,unclaimedTimeout = 2000,{step = (_title,fn) => fn(),...sessionOptions} = {}) {
    if (!Number.isFinite(unclaimedTimeout) || unclaimedTimeout < 0) throw new TypeError('unclaimedTimeout must be nonnegative');
    this.#context = context;
    this.ideKey = ideKey;
    this.#unclaimedTimeout = unclaimedTimeout;
    this.step = step;
    this.sessionOptions = {...sessionOptions,step};
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
    if (!this.#disposing) {
      this.disposed = true;
      for (const waiter of [...this.#waiters]) waiter.fail(new ConnectionClosed('Test finished while waiting for an Xdebug session'));
      for (const timer of this.#unclaimed.values()) clearTimeout(timer);
      this.#unclaimed.clear();
      this.#disposing = Promise.all([...this.#sessions].map(session => session.release())).then(() => {});
    }
    return this.#disposing;
  }
}
module.exports = {Listener,Xdebug};
