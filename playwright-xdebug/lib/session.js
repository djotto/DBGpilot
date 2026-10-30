// One test-owned PHP request. Reporting is injected by the Playwright fixture.
const { EventEmitter } = require('node:events');
const { pathToFileURL, fileURLToPath } = require('node:url');
const { ProtocolError, ConnectionClosed } = require('./dbgp');
const { bytes, parseProperty, plainValue, toValue, toPhp, toJSONSafe } = require('./values');
const CONTINUATIONS = new Set(['run','step_into','step_over','step_out','detach','stop']);
const EVALUATIONS = new Set(['eval','property_set']);
const toUri = file => /^(file|dbgp):/.test(file) ? file : pathToFileURL(file).href;
const toPath = uri => uri?.startsWith('file:') ? fileURLToPath(uri) : uri;
let counter = 0;
class Session extends EventEmitter {
  #execution;
  #busy = false;
  #release;
  constructor(connection, init, {step = (_title,fn) => fn(), maxPages = 1024, maxDepth = 16} = {}) {
    super();
    for (const [name,value] of Object.entries({maxPages,maxDepth})) {
      if (!Number.isSafeInteger(value) || value < 1) throw new TypeError(`${name} must be a positive integer`);
    }
    Object.assign(this,{connection,init,step,maxPages,maxDepth,id:++counter,state:'starting',request:{method:'',uri:''}});
    this.lastResult = {status:'starting'};
    connection.on('command', ({id,name}) => {
      if (this.#execution?.name === name && this.#execution.id === undefined) this.#execution.id = id;
    });
    connection.on('response', (response,transaction) => this.#response(response,transaction));
    connection.on('stream', node => this.emit('stream',{stream:node.type,data:bytes(node)}));
    connection.on('notify', node => this.emit('notification',node));
    connection.on('close', error => {
      this.state = 'stopped';
      this.#execution = undefined;
      this.emit('close',error);
    });
  }
  get label() { return `#${this.id} ${this.request.method} ${this.request.uri}`; }
  async prepare() {
    for (const [n,v] of [['max_children',100],['max_data',0],['max_depth',1],['extended_properties',1]]) {
      const response = await this.connection.send('feature_set',{n,v});
      if (response.success !== '1') throw new ProtocolError(`Xdebug did not accept feature ${n}`);
    }
    const property = await this.#evaluate(`$_SERVER['REQUEST_METHOD'] . ' ' . $_SERVER['REQUEST_URI']`);
    const value = toValue(property);
    if (typeof value !== 'string' || !value.includes(' ')) throw new ProtocolError('Cannot read PHP request metadata');
    const separator = value.indexOf(' ');
    this.request = {method:value.slice(0,separator),uri:value.slice(separator+1)};
  }
  #assertAvailable() {
    if (this.connection.closed) throw this.connection.error;
    if (this.#busy || this.#execution || !['starting','break'].includes(this.state)) {
      throw new Error(`${this.label} is ${this.state} or has an operation pending`);
    }
  }
  #operate(title,fn) {
    return this.step(`xdebug: ${title}`,async () => {
      this.#assertAvailable();
      this.#busy = true;
      try { return await fn(); } finally { this.#busy = false; }
    });
  }
  #result(response) {
    return {status:response.status,reason:response.reason,file:toPath(response.message?.filename),
      line:Number(response.message?.lineno) || undefined,message:response.message};
  }
  #response(response,{id,name,error,abandoned}) {
    if (this.#execution?.id !== id) return;
    const execution = this.#execution;
    if (error || (EVALUATIONS.has(name) && response.status === undefined)) {
      this.state = execution.previous;
    } else {
      if (!['break','stopping','stopped'].includes(response.status)) throw new ProtocolError(`${name} returned an invalid execution status`);
      this.state = response.status;
    }
    this.#execution = undefined;
    if (CONTINUATIONS.has(name) && !error) this.lastResult = this.#result(response);
    if (this.state === 'break' && !error && (CONTINUATIONS.has(name) || abandoned)) this.emit('stopped',this.lastResult);
    if (!error && ['stopping','stopped'].includes(this.state)) this.emit('finished',this.lastResult);
  }
  async #execute(name,args = {},data,timeout = 30000) {
    if (this.#execution) throw new Error('PHP execution is already pending');
    const execution = {name,previous:this.state};
    this.#execution = execution;
    this.state = 'running';
    try { return await this.connection.send(name,args,data,timeout); }
    finally {
      // Encoding/validation failed before anything reached the engine.
      if (execution.id === undefined && this.#execution === execution) {
        this.state = execution.previous;
        this.#execution = undefined;
      }
    }
  }
  setBreakpoint(file,line,{condition,temporary,hitValue,hitCondition,state} = {}) {
    return this.#operate(`break at ${file}:${line}`,async () => (await this.connection.send('breakpoint_set',{
      t:condition ? 'conditional':'line',f:toUri(file),n:line,r:temporary ? 1:undefined,
      h:hitValue,o:hitCondition,s:state,
    },condition)).id);
  }
  setExceptionBreakpoint(exception = '*') {
    return this.#operate(`break on exception ${exception}`,async () =>
      (await this.connection.send('breakpoint_set',{t:'exception',x:exception})).id);
  }
  removeBreakpoint(id) { return this.#operate(`remove breakpoint ${id}`,() => this.connection.send('breakpoint_remove',{d:id})); }
  run(options) { return this.#continue('run',options); }
  stepInto(options) { return this.#continue('step_into',options); }
  stepOver(options) { return this.#continue('step_over',options); }
  stepOut(options) { return this.#continue('step_out',options); }
  #continue(name,{timeout = 30000} = {}) {
    return this.#operate(name,async () => this.#result(await this.#execute(name,{},undefined,timeout)));
  }
  runUntilBreak({timeout = 30000} = {}) {
    return this.#operate('run until break',async () => {
      const result = this.#result(await this.#execute('run',{},undefined,timeout));
      if (result.status !== 'break') {
        await this.release();
        throw new Error(`${this.label} finished without hitting a breakpoint`);
      }
      return result;
    });
  }
  // Recovery after a continuation's caller timed out, within the same test.
  waitForPause({timeout = 30000, signal} = {}) {
    if (!Number.isFinite(timeout) || timeout < 0) return Promise.reject(new TypeError('Invalid timeout'));
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (this.state === 'break' && !this.#execution) return Promise.resolve(this.lastResult);
    if (this.connection.closed) return Promise.reject(this.connection.error);
    if (['stopping','stopped'].includes(this.state)) return Promise.reject(new Error('PHP finished without pausing'));
    return new Promise((resolve,reject) => {
      let timer;
      const cleanup = () => { clearTimeout(timer); this.off('stopped',stopped); this.off('finished',finished); this.off('close',closed); signal?.removeEventListener('abort',abort); };
      const stopped = result => { cleanup(); resolve(result); };
      const closed = error => { cleanup(); reject(error); };
      const finished = () => { cleanup(); reject(new Error('PHP finished without pausing')); };
      const abort = () => { cleanup(); reject(signal.reason); };
      this.on('stopped',stopped); this.on('finished',finished); this.on('close',closed); signal?.addEventListener('abort',abort,{once:true});
      if (timeout) timer = setTimeout(() => { cleanup(); reject(new Error('Timed out waiting for PHP to pause')); },timeout);
    });
  }
  detach() { return this.step('xdebug: detach',() => this.release()); }
  stop() {
    return this.#operate('stop',async () => {
      try { return this.#result(await this.#execute('stop')); }
      catch (error) { if (!(error instanceof ConnectionClosed)) throw error; return {status:'stopped',responseReceived:false}; }
      finally { this.connection.close(); }
    });
  }
  async #stack() {
    return ((await this.connection.send('stack_get')).stack ?? []).map(frame => ({
      level:Number(frame.level),where:frame.where,file:toPath(frame.filename),line:Number(frame.lineno),
    }));
  }
  stack() { return this.#operate('stack',() => this.#stack()); }
  locals({frame = 0,context = 0} = {}) {
    return this.#operate(`locals (frame ${frame})`,async () => {
      const response = await this.connection.send('context_get',{d:frame,c:context});
      return Object.fromEntries((response.property ?? []).map(p => { const prop = parseProperty(p); return [prop.name,plainValue(prop)]; }));
    });
  }
  getProperty(name,{frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate(`property ${name}`,async () => parseProperty(await this.#fetch(name,frame,depth,context)));
  }
  getVariable(name,{frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate(`get ${name}`,async () => toValue(await this.#fetch(name,frame,depth,context)));
  }
  evaluate(expression,{timeout = 10000} = {}) {
    return this.#operate(`eval ${expression}`,async () => toValue(await this.#evaluate(expression,timeout)));
  }
  async #evaluate(expression,timeout) {
    const response = await this.#execute('eval',{},expression,timeout);
    return response.property?.[0] ?? {type:'null'};
  }
  setVariable(name,value,{frame = 0,context = 0} = {}) {
    return this.#operate(`set ${name}`,async () => {
      const expression = toPhp(value);
      const response = await this.#execute('property_set',{n:name,d:frame,c:context,l:Buffer.byteLength(expression)},expression);
      if (response.success !== '1') throw new Error(`Could not set ${name}`);
      // Declared but uninitialized locals cannot be read before assignment.
      // Conversely, a nonexistent local may report success but be discarded;
      // only the read after assignment distinguishes that engine behaviour.
      await this.connection.send('property_get',{n:name,d:frame,c:context}).catch(error => {
        throw new Error(`Could not set ${name}: it must be an existing variable in frame ${frame}`,{cause:error});
      });
    });
  }
  command(name,args,data,timeout) {
    return this.#operate(name,() => CONTINUATIONS.has(name) || EVALUATIONS.has(name)
      ? this.#execute(name,args,data,timeout) : this.connection.send(name,args,data,timeout));
  }
  snapshot({variables = [],expressions = [],frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate('snapshot',async () => {
      const result = {sessionId:this.id,execution:this.lastResult,frames:await this.#stack(),variables:{},expressions:{}};
      for (const name of variables) result.variables[name] = parseProperty(await this.#fetch(name,frame,depth,context));
      for (const expression of expressions) result.expressions[expression] = parseProperty(await this.#evaluate(expression));
      return toJSONSafe(result);
    });
  }
  async #fetch(fullname,frame,depth,context) {
    if (!Number.isSafeInteger(depth) || depth < 1 || depth > this.maxDepth) throw new RangeError(`depth must be between 1 and ${this.maxDepth}`);
    const get = async page => {
      const wire = (await this.connection.send('property_get',{n:fullname,d:frame,c:context,p:page})).property?.[0];
      const parsed = parseProperty(wire);
      if (parsed.page !== page) throw new ProtocolError('Engine returned the wrong property page');
      return {wire,parsed};
    };
    const {wire:property,parsed:first} = await get(0);
    let children = property.property ?? [];
    for (let page = 1; children.length < first.totalChildren; page++) {
      if (page >= this.maxPages) throw new ProtocolError('Property pagination exceeded maxPages');
      const {wire,parsed} = await get(page);
      if (parsed.totalChildren !== first.totalChildren) throw new ProtocolError('Property child count changed during pagination');
      const more = wire.property ?? [];
      if (!more.length) throw new ProtocolError('Property pagination made no progress');
      children = children.concat(more);
    }
    if (depth > 1) {
      const fetched = [];
      // Bound request fan-out when descending large Drupal object graphs.
      for (const child of children) {
        const parsed = parseProperty(child);
        fetched.push(parsed.totalChildren > 0
          ? {...await this.#fetch(parsed.fullname,frame,depth-1,context),name:child.name} : child);
      }
      children = fetched;
    }
    return {...property,property:children};
  }
  release() {
    if (!this.#release) this.#release = this.#releaseConnection();
    return this.#release;
  }
  async #releaseConnection() {
    if (this.connection.closed) return;
    try {
      if (!this.#execution && !this.#busy) await this.connection.send('detach',{},undefined,2000);
      // An operation that has reached stopping may release itself safely.
      else if (!this.#execution && this.state === 'stopping') await this.connection.send('detach',{},undefined,2000);
    } catch { /* Explicit release still closes an unreachable transport. */ }
    finally { this.connection.close(); }
  }
}
module.exports = {Session};
