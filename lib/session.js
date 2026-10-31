// One test-owned PHP request. Reporting is injected by the Playwright fixture.
const { EventEmitter } = require('node:events');
const { fileURLToPath } = require('node:url');
const { ProtocolError, ConnectionClosed, XdebugError } = require('./dbgp');
const { bytes, text, parseProperty, plainValue, toValue, toPhp, toJSONSafe } = require('./values');
const {PathMapper} = require('./paths');
const records = require('./records');
const {EventQueue} = require('./events');
const {encodeBytes} = require('./encoding');
const CONTINUATIONS = new Set(['run','step_into','step_over','step_out','detach','stop']);
const EVALUATIONS = new Set(['eval','property_set']);
const COMMANDS = ('feature_get feature_set status run step_into step_over step_out stop detach breakpoint_set breakpoint_get '+
  'breakpoint_update breakpoint_remove breakpoint_list stack_depth stack_get context_names context_get '+
  'typemap_get property_get property_set property_value source stdout stderr eval').split(' ');
const FEATURES = ('language_name language_version encoding data_encoding supports_async supports_postmortem '+
  'breakpoint_types max_children max_data max_depth extended_properties notify_ok resolved_breakpoints breakpoint_details').split(' ');
const unsupportedFeature = error => error instanceof XdebugError && [3,4].includes(error.code);
const utf8 = value => /^utf-?8$/i.test(value);
const latin1 = value => /^(?:iso-?8859-?1|latin-?1)$/i.test(value);
const toPath = uri => {
  try { return uri?.startsWith('file:') ? fileURLToPath(uri) : uri; }
  catch { return uri; }
};
let counter = 0;
class Session extends EventEmitter {
  #execution;
  #busy = false;
  #release;
  #breakpoints = new Map();
  #types = new Map();
  #events;
  constructor(connection, init, {step = (_title,fn) => fn(), maxPages = 1024, maxDepth = 16, pathMappings = [], baseDir, maxEvents = 1024} = {}) {
    super();
    for (const [name,value] of Object.entries({maxPages,maxDepth})) {
      if (!Number.isSafeInteger(value) || value < 1) throw new TypeError(`${name} must be a positive integer`);
    }
    Object.assign(this,{connection,init,step,maxPages,maxDepth,id:++counter,state:'starting',request:{method:'',uri:''}});
    this.paths = pathMappings instanceof PathMapper ? pathMappings : new PathMapper(pathMappings,{baseDir});
    this.#events = new EventQueue(maxEvents);
    this.info = {...init,xml:init.rawXml,fileUri:init.fileuri,...this.paths.location(init.fileuri)};
    this.lastResult = {status:'starting'};
    connection.on('command', ({id,name}) => {
      if (this.#execution?.name === name && this.#execution.id === undefined) this.#execution.id = id;
    });
    connection.on('response', (response,transaction) => this.#response(response,transaction));
    connection.on('stream', node => this.#event('stream',{stream:node.type,data:bytes(node)}));
    connection.on('notify', node => {
      const point = node.breakpoint?.[0] ? records.breakpoint(node.breakpoint[0],this.paths) : undefined;
      if (point) this.#breakpoints.set(point.id,point);
      this.#event('notification',{...node,data:bytes(node),xml:node.rawXml,breakpoint:point,message:node.message ? {...node.message,...this.paths.location(node.message.filename)} : undefined});
    });
    connection.on('close', error => {
      this.state = 'stopped';
      this.#execution = undefined;
      this.#events.close(error);
      this.emit('close',error);
    });
  }
  get label() { return `#${this.id} ${this.request.method} ${this.request.uri}`; }
  #property(value) { return parseProperty(value,this.#types); }
  nextEvent(options) { return this.#events.next(options); }
  #event(type,data) {
    try { this.#events.push({type,data}); }
    catch (error) { this.connection.close(error); return; }
    this.emit(type,data);
  }
  get knownBreakpoints() { return Object.fromEntries([...this.#breakpoints].map(([id,point]) => [id,{...point,attributes:{...point.attributes}}])); }
  async prepare() {
    const encoding = await this.#optionalFeature('encoding');
    // Xdebug labels XML Latin-1 while embedding application bytes. Our parser
    // preserves those bytes without requiring Xdebug to change its XML label.
    const xdebugBytes = this.init.engine?.['#text']?.toLowerCase() === 'xdebug' && latin1(encoding.value);
    if (encoding.supported && !utf8(encoding.value) && !xdebugBytes) {
      await this.#requireEncoding('encoding','UTF-8');
    }
    const dataEncoding = await this.#optionalFeature('data_encoding');
    if (dataEncoding.supported && dataEncoding.value !== 'base64') {
      await this.#requireEncoding('data_encoding','base64');
    }
    for (const [n,v] of [['max_children',100],['max_data',0],['max_depth',1],['extended_properties',1],
      ['notify_ok',1],['resolved_breakpoints',1],['breakpoint_details',1]]) {
      try { await this.#send('feature_set',{n,v}); }
      catch (error) { if (!unsupportedFeature(error)) throw error; }
    }
    const property = await this.#evaluate(`($_SERVER['REQUEST_METHOD'] ?? 'CLI') . ' ' . ($_SERVER['REQUEST_URI'] ?? $_SERVER['SCRIPT_FILENAME'] ?? '')`);
    const value = toValue(property,this.#types);
    if (typeof value !== 'string' || !value.includes(' ')) throw new ProtocolError('Cannot read PHP request metadata');
    const separator = value.indexOf(' ');
    this.request = {method:value.slice(0,separator),uri:value.slice(separator+1)};
  }
  async #requireEncoding(name,value) {
    try {
      if (records.flag(await this.#send('feature_set',{n:name,v:value}),'success')) return;
    } catch (error) {
      if (!unsupportedFeature(error)) throw error;
    }
    throw new ProtocolError(`The engine must support ${value} ${name}`);
  }
  #send(name,args = {},...options) {
    if (name === 'feature_set') {
      if (args.n === 'encoding' && !utf8(String(args.v))) throw new TypeError('Session encoding must remain UTF-8');
      if (args.n === 'data_encoding' && args.v !== 'base64') throw new TypeError('Command data must remain base64');
    }
    return this.connection.send(name,args,...options);
  }
  #assertAvailable() {
    if (this.connection.closed) throw this.connection.error;
    if (this.#busy || this.#execution || !['starting','break','stopping'].includes(this.state)) {
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
    const point = response.breakpoint?.[0] ? records.breakpoint(response.breakpoint[0],this.paths) : undefined;
    return {status:response.status,reason:response.reason,file:toPath(response.message?.filename),
      fileUri:response.message?.filename,...this.paths.location(response.message?.filename),
      line:records.integer(response.message?.lineno,'execution line',{optional:true}),
      exception:response.message?.exception,message:response.message,breakpoint:point,responseReceived:true};
  }
  #metadata(response,{name,args = {},data,error}) {
    if (error) return;
    if (name === 'feature_get') records.feature(response);
    if (name === 'feature_set') records.flag(response,'success');
    if (name === 'property_set') records.flag(response,'success');
    if (name === 'typemap_get') this.#types = new Map(this.#decodeTypeMap(response).map(type => [type.name,type]));
    if (name === 'breakpoint_set') {
      if (!response.id) throw new ProtocolError('breakpoint_set requires an ID');
      this.#breakpoints.set(response.id,{id:response.id,type:args.t,fileUri:args.f,...this.paths.location(args.f),line:args.n,
        state:response.state ?? args.s ?? 'enabled',resolved:response.resolved,hitValue:args.h ?? 0,hitCondition:args.o,
        function:args.m,exception:args.x,temporary:args.r === 1,expression:data});
    }
    if (name === 'breakpoint_get' || name === 'breakpoint_list') {
      const points = (response.breakpoint ?? []).map(node => records.breakpoint(node,this.paths));
      if (name === 'breakpoint_get' && (points.length !== 1 || points[0].id !== args.d)) throw new ProtocolError('breakpoint_get returned a missing or different ID');
      if (new Set(points.map(point => point.id)).size !== points.length) throw new ProtocolError('breakpoint_list returned duplicate IDs');
      if (name === 'breakpoint_list') this.#breakpoints.clear();
      for (const point of points) this.#breakpoints.set(point.id,point);
    }
    if (name === 'breakpoint_update' && this.#breakpoints.has(args.d)) {
      const point = {...this.#breakpoints.get(args.d)};
      for (const [key,arg] of [['state','s'],['line','n'],['hitValue','h'],['hitCondition','o']]) if (args[arg] !== undefined) point[key] = args[arg];
      this.#breakpoints.set(args.d,point);
    }
    if (name === 'breakpoint_remove') this.#breakpoints.delete(args.d);
  }
  #response(response,transaction) {
    this.#metadata(response,transaction);
    const {id,name,error,abandoned} = transaction;
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
    if (this.state === 'break' && ((!error && CONTINUATIONS.has(name)) || (abandoned && EVALUATIONS.has(name)))) this.#event('stopped',this.lastResult);
    if (!error && ['stopping','stopped'].includes(this.state)) this.emit('finished',this.lastResult);
  }
  async #execute(name,args = {},data,timeout = 30000,signal) {
    if (this.#execution) throw new Error('PHP execution is already pending');
    if (['run','step_into','step_over','step_out'].includes(name) && !['starting','break'].includes(this.state)) throw new Error(`Cannot ${name} in state ${this.state}`);
    const execution = {name,previous:this.state};
    this.#execution = execution;
    this.state = 'running';
    try { return await this.#send(name,args,data,timeout,{signal}); }
    finally {
      // Encoding/validation failed before anything reached the engine.
      if (execution.id === undefined && this.#execution === execution) {
        this.state = execution.previous;
        this.#execution = undefined;
      }
    }
  }
  setBreakpoint(file,line,{condition,temporary = false,hitValue,hitCondition,state = 'enabled',kind = 'line',function:fn,exception} = {}) {
    return this.#operate(`break at ${file}:${line}`,async () => {
      if (condition !== undefined && kind === 'line') kind = 'conditional';
      if (!['line','conditional','call','return','exception','watch'].includes(kind)) throw new TypeError('Invalid breakpoint type');
      if (kind === 'line' && (!file || !Number.isSafeInteger(line) || line < 1)) throw new TypeError('Line breakpoint requires file and positive line');
      if (kind === 'conditional' && (!file || (line !== undefined && (!Number.isSafeInteger(line) || line < 1)))) throw new TypeError('Conditional breakpoint requires file and optional positive line');
      if (['conditional','watch'].includes(kind) && condition === undefined) throw new TypeError('Breakpoint requires a condition');
      if (['call','return'].includes(kind) && !fn) throw new TypeError('Breakpoint requires a function');
      if (kind === 'exception' && !exception) throw new TypeError('Breakpoint requires an exception');
      records.validateState(state); records.validateHit(hitValue,hitCondition);
      return (await this.#send('breakpoint_set',{
        t:kind,f:file === undefined ? undefined:this.paths.toRemote(file),n:line,r:temporary ? 1:0,h:hitValue,o:hitCondition,s:state,m:fn,x:exception,
      },condition)).id;
    });
  }
  setExceptionBreakpoint(exception = '*') {
    return this.setBreakpoint(undefined,undefined,{kind:'exception',exception});
  }
  removeBreakpoint(id) { return this.#operate(`remove breakpoint ${id}`,() => this.#send('breakpoint_remove',{d:id})); }
  getBreakpoint(id) {
    return this.#operate(`breakpoint ${id}`,async () => records.breakpoint((await this.#send('breakpoint_get',{d:id})).breakpoint?.[0],this.paths));
  }
  breakpoints() {
    return this.#operate('list breakpoints',async () => ((await this.#send('breakpoint_list')).breakpoint ?? []).map(point => records.breakpoint(point,this.paths)));
  }
  updateBreakpoint(id,{state,line,hitValue,hitCondition} = {}) {
    return this.#operate(`update breakpoint ${id}`,async () => {
      records.validateState(state,true); records.validateHit(hitValue,hitCondition);
      if (line !== undefined && (!Number.isSafeInteger(line) || line < 1)) throw new TypeError('Line must be positive');
      await this.#send('breakpoint_update',{d:id,s:state,n:line,h:hitValue,o:hitCondition});
    });
  }
  async #featureGet(name) { return records.feature(await this.#send('feature_get',{n:name})); }
  featureGet(name) { return this.#operate(`feature ${name}`,() => this.#featureGet(name)); }
  featureSet(name,value) {
    return this.#operate(`feature ${name} = ${value}`,async () => records.flag(await this.#send('feature_set',{n:name,v:value}),'success'));
  }
  async #optionalFeature(name) {
    try { return await this.#featureGet(name); }
    catch (error) {
      if (!unsupportedFeature(error)) throw error;
      return {supported:false,value:'',enabled:false};
    }
  }
  getCapabilities() {
    return this.#operate('get capabilities',async () => {
      const inventory = {};
      for (const name of [...FEATURES,...COMMANDS]) inventory[name] = await this.#optionalFeature(name);
      return inventory;
    });
  }
  status() {
    return this.#operate('status',async () => {
      const response = await this.#send('status');
      if (!['starting','running','break','stopping','stopped'].includes(response.status)) throw new ProtocolError('Invalid engine status');
      this.state = response.status;
      return this.#result(response);
    });
  }
  stackDepth() {
    return this.#operate('stack depth',async () => records.integer((await this.#send('stack_depth')).depth,'stack depth'));
  }
  contexts({frame = 0} = {}) {
    return this.#operate('contexts',async () => {
      records.validateFrame(frame);
      const contexts = (await this.#send('context_names',{d:frame})).context ?? [];
      return Object.fromEntries(contexts.map(context => [records.integer(context.id,'context ID'),context.name ?? '']));
    });
  }
  typeMap() {
    return this.#operate('type map',async () => this.#decodeTypeMap(await this.#send('typemap_get')));
  }
  #decodeTypeMap(response) {
    const maps = response.map ?? [];
    return (Array.isArray(maps) ? maps:[maps]).map(type => {
      if (!type.name || !type.type) throw new ProtocolError('Type mapping requires name and common type');
      return {name:type.name,type:type.type,schemaType:type['xsi:type'] ?? type.type,attributes:{...type}};
    });
  }
  source(file,{begin,end} = {}) {
    return this.#operate('source',async () => {
      for (const value of [begin,end]) if (value !== undefined && (!Number.isSafeInteger(value) || value < 1)) throw new TypeError('Source lines must be positive integers');
      const response = await this.#send('source',{f:file === undefined ? undefined:this.paths.toRemote(file),b:begin,e:end});
      if (response.success === '0') throw new ProtocolError('Engine could not retrieve source');
      return bytes(response);
    });
  }
  setOutput(stream = 'stdout',mode = 1) {
    return this.#operate(`output ${stream}`,async () => {
      if (!['stdout','stderr'].includes(stream) || ![0,1,2].includes(mode)) throw new TypeError('Choose stdout/stderr and mode 0, 1 or 2');
      return records.flag(await this.#send(stream,{c:mode}),'success');
    });
  }
  run(options) { return this.#continue('run',options); }
  stepInto(options) { return this.#continue('step_into',options); }
  stepOver(options) { return this.#continue('step_over',options); }
  stepOut(options) { return this.#continue('step_out',options); }
  #continue(name,{timeout = 30000,signal} = {}) {
    return this.#operate(name,async () => this.#result(await this.#execute(name,{},undefined,timeout,signal)));
  }
  runUntilBreak({timeout = 30000,signal} = {}) {
    return this.#operate('run until break',async () => {
      const result = this.#result(await this.#execute('run',{},undefined,timeout,signal));
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
      catch (error) { if (!(error instanceof ConnectionClosed) || !error.cleanEOF) throw error; return {status:'stopped',responseReceived:false}; }
      finally { this.connection.close(); }
    });
  }
  async #stack(frame) {
    if (frame !== undefined) records.validateFrame(frame);
    const decode = node => ({
      level:records.integer(node.level,'frame level'),where:node.where,file:toPath(node.filename),
      line:records.integer(node.lineno,'frame line',{optional:true}),fileUri:node.filename,...this.paths.location(node.filename),
      type:node.type,commandBegin:node.cmdbegin,commandEnd:node.cmdend,attributes:{...node},
      inputs:(node.input ? (Array.isArray(node.input) ? node.input:[node.input]):[]).map(decode),
    });
    return ((await this.#send('stack_get',{d:frame})).stack ?? []).map(decode);
  }
  stack({frame} = {}) { return this.#operate('stack',() => this.#stack(frame)); }
  locals({frame = 0,context = 0} = {}) {
    return this.#operate(`locals (frame ${frame})`,async () => {
      records.validateFrame(frame);
      const response = await this.#send('context_get',{d:frame,c:context});
      return Object.fromEntries((response.property ?? []).map(p => { const prop = this.#property(p); return [prop.name,plainValue(prop)]; }));
    });
  }
  getProperty(name,{frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate(`property ${name}`,async () => this.#property(await this.#fetch(name,frame,depth,context)));
  }
  getPropertyPage(name,{frame = 0,context = 0,page = 0,maxData,key,address} = {}) {
    return this.#operate(`property page ${name}`,async () => {
      records.validateFrame(frame); records.validateFrame(page);
      return this.#property((await this.#send('property_get',{n:name,d:frame,c:context,p:page,m:maxData,k:key,a:address})).property?.[0]);
    });
  }
  async #propertyValue(name,{frame = 0,context = 0,page,maxData = 0,key,address} = {}) {
    records.validateFrame(frame);
    if (page !== undefined) records.validateFrame(page);
    const response = await this.#send('property_value',{n:name,d:frame,c:context,p:page,m:maxData,k:key,a:address});
    const data = bytes(response);
    const size = response.size === undefined ? data.length:records.integer(response.size,'property value size');
    return {data,size,truncated:size > data.length,page:records.integer(response.page,'property value page',{optional:true}),key:response.key ?? key,address:response.address ?? address};
  }
  propertyValue(name,options) { return this.#operate(`value ${name}`,async () => (await this.#propertyValue(name,options)).data); }
  propertyValueInfo(name,options) { return this.#operate(`value metadata ${name}`,() => this.#propertyValue(name,options)); }
  getVariable(name,{frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate(`get ${name}`,async () => toValue(await this.#fetch(name,frame,depth,context),this.#types));
  }
  evaluate(expression,{timeout = 10000,frame = 0,page = 0,signal} = {}) {
    return this.#operate(`eval ${expression}`,async () => {
      records.validateFrame(frame); records.validateFrame(page);
      if (frame !== 0) throw new TypeError('Xdebug evaluates in the current frame; use property/context reads for other frames');
      return toValue(await this.#evaluate(expression,timeout,page,signal),this.#types);
    });
  }
  async #evaluate(expression,timeout,page = 0,signal) {
    const response = await this.#execute('eval',{d:0,p:page},expression,timeout,signal);
    return response.property?.[0] ?? {type:'null'};
  }
  setProperty(name,expression,{frame = 0,context = 0,type,address} = {}) {
    return this.#operate(`set property ${name}`,async () => {
      records.validateFrame(frame);
      if (typeof expression !== 'string' && !Buffer.isBuffer(expression)) throw new TypeError('Property assignment requires a PHP expression or Buffer');
      const data = Buffer.isBuffer(expression) ? expression:encodeBytes(expression);
      return records.flag(await this.#execute('property_set',{n:name,d:frame,c:context,t:type,a:address,l:data.length},data),'success');
    });
  }
  setVariable(name,value,{frame = 0,context = 0} = {}) {
    return this.#operate(`set ${name}`,async () => {
      records.validateFrame(frame);
      const expression = toPhp(value);
      const response = await this.#execute('property_set',{n:name,d:frame,c:context,l:Buffer.byteLength(expression)},expression);
      if (response.success !== '1') throw new Error(`Could not set ${name}`);
      // Declared but uninitialized locals cannot be read before assignment.
      // Conversely, a nonexistent local may report success but be discarded;
      // only the read after assignment distinguishes that engine behaviour.
      await this.#send('property_get',{n:name,d:frame,c:context}).catch(error => {
        throw new Error(`Could not set ${name}: it must be an existing variable in frame ${frame}`,{cause:error});
      });
    });
  }
  command(name,args,data,timeout) {
    return this.#operate(name,() => CONTINUATIONS.has(name) || EVALUATIONS.has(name)
      ? this.#execute(name,args,data,timeout) : this.#send(name,args,data,timeout));
  }
  snapshot({variables = [],expressions = [],frame = 0,depth = 1,context = 0} = {}) {
    return this.#operate('snapshot',async () => {
      records.validateFrame(frame);
      records.validateFrame(context);
      for (const [name,values] of Object.entries({variables,expressions})) {
        if (!Array.isArray(values) || values.some(value => typeof value !== 'string')) throw new TypeError(`Snapshot ${name} must be an array of strings`);
      }
      if (!Number.isSafeInteger(depth) || depth < 1 || depth > this.maxDepth) throw new TypeError(`Snapshot depth must be between 1 and ${this.maxDepth}`);
      if (expressions.length && frame !== 0) throw new TypeError('Xdebug evaluates expressions in the current frame only');
      const frames = await this.#stack();
      const execution = !this.lastResult.fileUri && frames.length ? {...this.lastResult,...this.paths.location(frames[0].fileUri),fileUri:frames[0].fileUri,file:frames[0].file,line:frames[0].line} : this.lastResult;
      const result = {sessionId:this.id,execution,frames,variables:{},expressions:{}};
      for (const name of variables) result.variables[name] = this.#property(await this.#fetch(name,frame,depth,context));
      for (const expression of expressions) result.expressions[expression] = this.#property(await this.#evaluate(expression));
      return toJSONSafe(result);
    });
  }
  async #fetch(fullname,frame,depth,context) {
    records.validateFrame(frame);
    if (!Number.isSafeInteger(depth) || depth < 1 || depth > this.maxDepth) throw new RangeError(`depth must be between 1 and ${this.maxDepth}`);
    const get = async page => {
      const wire = (await this.#send('property_get',{n:fullname,d:frame,c:context,p:page})).property?.[0];
      const parsed = this.#property(wire);
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
        const parsed = this.#property(child);
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
    let result = {status:'stopped',responseReceived:false};
    if (this.connection.closed) return result;
    try {
      if (!this.#execution && (!this.#busy || this.state === 'stopping')) {
        result = this.#result(await this.#send('detach',{},undefined,2000));
      }
    } catch (error) { result.releaseError = error.message; }
    finally { this.connection.close(); }
    return result;
  }
}
module.exports = {Session};
