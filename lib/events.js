const {ProtocolError} = require('./dbgp');
class EventQueue {
  #items = [];
  #waiters = [];
  #terminal;
  constructor(limit = 1024) {
    if (!Number.isSafeInteger(limit) || limit < 1) throw new TypeError('maxEvents must be positive');
    this.limit = limit;
  }
  push(event) {
    if (this.#terminal) return;
    if (this.#waiters.length) return this.#waiters[0].succeed(event);
    if (this.#items.length >= this.limit) throw new ProtocolError('Debugger event queue overflow');
    this.#items.push(event);
  }
  close(error) {
    this.#terminal = {type:'closed',error:{name:error.name,message:error.message}};
    for (const waiter of [...this.#waiters]) waiter.succeed(this.#terminal);
  }
  next({timeout = 30000,signal} = {}) {
    if (!Number.isFinite(timeout) || timeout < 0) return Promise.reject(new TypeError('Invalid event timeout'));
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (this.#items.length) return Promise.resolve(this.#items.shift());
    if (this.#terminal) return Promise.resolve({...this.#terminal,error:{...this.#terminal.error}});
    return new Promise((resolve,reject) => {
      let timer;
      const remove = () => {
        clearTimeout(timer); signal?.removeEventListener('abort',abort);
        const index = this.#waiters.indexOf(waiter); if (index >= 0) this.#waiters.splice(index,1);
      };
      const waiter = {succeed:event => {remove();resolve(event);},fail:error => {remove();reject(error);}};
      const abort = () => waiter.fail(signal.reason);
      signal?.addEventListener('abort',abort,{once:true});
      if (timeout) timer = setTimeout(() => waiter.fail(new Error('Debugger event wait timed out')),timeout);
      this.#waiters.push(waiter);
    });
  }
}
module.exports = {EventQueue};
