// Byte-oriented DBGp transport. A timed-out wait does not cancel PHP execution.
const { EventEmitter } = require('node:events');
const { XMLParser, XMLValidator } = require('fast-xml-parser');
const {encodeBytes,decodeBytes} = require('./encoding');
const NAMESPACE = 'urn:debugger_protocol_v1';
const parser = new XMLParser({
  ignoreAttributes: false, attributeNamePrefix: '@_', trimValues: false,
  parseTagValue: false, parseAttributeValue: false,
  isArray: name => ['property', 'stack', 'breakpoint', 'context'].includes(name.split(':').at(-1)),
});
class ProtocolError extends Error { name = 'ProtocolError'; }
class ConnectionClosed extends Error {
  name = 'ConnectionClosed';
  constructor(message = 'Xdebug connection closed',{cleanEOF = false} = {}) {
    super(message); this.cleanEOF = cleanEOF;
  }
}
class CommandTimeout extends Error {
  name = 'CommandTimeout';
  constructor(command, timeout) {
    super(`Xdebug ${command} timed out after ${timeout}ms; PHP may still be executing`);
    this.command = command;
  }
}
class XdebugError extends Error {
  name = 'XdebugError';
  constructor(command, code, message, {attributes,xml,response} = {}) {
    super(`Xdebug ${command} failed (${code}): ${message}`);
    this.command = command;
    this.code = Number(code);
    this.attributes = attributes; this.xml = xml; this.response = response;
  }
}
function quote(value) {
  if (!['string','number','bigint','boolean'].includes(typeof value) && !Buffer.isBuffer(value)) {
    throw new TypeError('DBGp arguments must be text, bytes, numbers or booleans');
  }
  const raw = Buffer.isBuffer(value) ? value : encodeBytes(String(typeof value === 'boolean' ? Number(value) : value));
  if (raw.length && !/[\s\\"\0]/u.test(raw.toString())) return raw;
  const bytes = [34];
  for (const byte of raw) {
    if (byte === 0) bytes.push(92, 48);
    else if (byte === 34 || byte === 92) bytes.push(92, byte);
    else bytes.push(byte);
  }
  bytes.push(34);
  return Buffer.from(bytes);
}
function encodeCommand(name, id, args = {}, data) {
  if (!/^[A-Za-z_][A-Za-z_0-9]*$/.test(name)) throw new TypeError('Invalid DBGp command name');
  if (!Number.isSafeInteger(id) || id < 1) throw new TypeError('Invalid transaction ID');
  if (!args || typeof args !== 'object' || Array.isArray(args)) throw new TypeError('Invalid DBGp arguments');
  const parts = [Buffer.from(name), Buffer.from('-i'), Buffer.from(String(id))];
  for (const [key, value] of Object.entries(args)) {
    if (!/^[A-Za-z]$/.test(key) || key === 'i') throw new TypeError(`Invalid or reserved argument: ${key}`);
    if (value !== undefined && value !== null) parts.push(Buffer.from(`-${key}`), quote(value));
  }
  if (data !== undefined) {
    if (typeof data !== 'string' && !Buffer.isBuffer(data)) throw new TypeError('DBGp data must be text or a Buffer');
    parts.push(Buffer.from('--'), Buffer.from((Buffer.isBuffer(data) ? data:encodeBytes(data)).toString('base64')));
  }
  return Buffer.concat(parts.flatMap((part, i) => i ? [Buffer.from(' '), part] : [part]).concat(Buffer.from([0])));
}
function stripPrefixes(value) {
  if (Array.isArray(value)) return value.map(stripPrefixes);
  if (!value || typeof value !== 'object') return value;
  // Child expression/name/value elements take precedence over attributes with
  // the same local name, as required by the extended-property format.
  return Object.fromEntries(Object.entries(value).sort(([a],[b]) => Number(b.startsWith('@_'))-Number(a.startsWith('@_'))).map(([key, child]) => [
    key.startsWith('@_') ? key.slice(2) : key.split(':').at(-1), stripPrefixes(child),
  ]));
}
function parsePacket(body) {
  if (body.includes(0) || /<!DOCTYPE|<!ENTITY/i.test(body.toString('latin1'))) {
    throw new ProtocolError('NUL, DTD and entity declarations are not supported in DBGp XML');
  }
  // Xdebug labels XML Latin-1 but embeds raw application bytes. Values and
  // extended property names are base64; ordinary names use application UTF-8.
  const xml = decodeBytes(body);
  const valid = XMLValidator.validate(xml);
  if (valid !== true) throw new ProtocolError(`Invalid DBGp XML: ${valid.err.msg}`);
  const roots = Object.entries(parser.parse(xml)).filter(([key]) => !key.startsWith('?'));
  if (roots.length !== 1) throw new ProtocolError('Expected one DBGp root element');
  const [tag, root] = roots[0];
  const namespace = tag.includes(':') ? root[`@_xmlns:${tag.split(':')[0]}`] : root['@_xmlns'];
  if (namespace !== NAMESPACE) throw new ProtocolError('Missing or invalid DBGp namespace');
  const kind = tag.split(':').at(-1);
  if (!['init','response','stream','notify'].includes(kind)) throw new ProtocolError(`Unexpected DBGp packet: ${kind}`);
  const node = stripPrefixes(root);
  Object.defineProperty(node,'rawXml',{value:xml});
  return {kind,node};
}
class Connection extends EventEmitter {
  #buffer = Buffer.alloc(0);
  #nextId = 1;
  #pending = new Map();
  #initialized = false;
  constructor(socket, {maxPacketSize = 16 * 1024 * 1024, maxPendingCommands = 1024} = {}) {
    super();
    for (const [name, value] of Object.entries({maxPacketSize,maxPendingCommands})) {
      if (!Number.isSafeInteger(value) || value < 1) throw new TypeError(`${name} must be a positive integer`);
    }
    Object.assign(this, {socket,maxPacketSize,maxPendingCommands,closed:false});
    socket.on('data', chunk => {
      if (this.closed) return;
      try { this.#receive(chunk); } catch (error) { this.close(error); }
    });
    socket.on('error', error => this.close(new ConnectionClosed(`Xdebug socket error: ${error.message}`)));
    socket.on('end', () => this.close(this.#buffer.length
      ? new ProtocolError('Peer disconnected during a DBGp packet') : new ConnectionClosed('Xdebug connection ended',{cleanEOF:true})));
    socket.on('close', () => this.close());
  }
  get pendingCount() { return this.#pending.size; }
  send(name, args = {}, data, timeout = 10000, {signal} = {}) {
    if (this.closed) return Promise.reject(this.error);
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (!Number.isFinite(timeout) || timeout < 0) throw new TypeError('Timeout must be a nonnegative finite number');
    if (this.#pending.size >= this.maxPendingCommands) throw new Error('Outstanding DBGp command limit reached');
    const id = this.#nextId;
    const packet = encodeCommand(name,id,args,data);
    this.#nextId++;
    return new Promise((resolve,reject) => {
      const entry = {id,name,args:{...args},data,resolve,reject,abandoned:false};
      const abandon = error => {
        clearTimeout(entry.timer); entry.removeAbort();
        entry.abandoned = true;
        reject(error);
      };
      const abort = () => abandon(signal.reason);
      entry.removeAbort = () => signal?.removeEventListener('abort',abort);
      signal?.addEventListener('abort',abort,{once:true});
      entry.timer = timeout ? setTimeout(() => abandon(new CommandTimeout(name,timeout)),timeout) : undefined;
      this.#pending.set(id,entry);
      this.emit('command',{id,name,args:entry.args,data});
      try {
        this.socket.write(packet,error => {
          if (error) this.close(new ConnectionClosed(`Cannot write DBGp command: ${error.message}`));
        });
      } catch (error) { this.close(new ConnectionClosed(`Cannot write DBGp command: ${error.message}`)); }
    });
  }
  close(error = new ConnectionClosed('Xdebug connection closed')) {
    if (this.closed) return;
    this.closed = true;
    this.error = error;
    for (const pending of this.#pending.values()) {
      clearTimeout(pending.timer);
      pending.removeAbort();
      pending.reject(error);
    }
    this.#pending.clear();
    this.#buffer = Buffer.alloc(0);
    this.socket.destroy();
    this.emit('close',error);
  }
  #receive(chunk) {
    this.#buffer = Buffer.concat([this.#buffer,chunk]);
    while (!this.closed && this.#buffer.length) {
      const nul = this.#buffer.indexOf(0);
      const header = this.#buffer.subarray(0,nul < 0 ? undefined : nul).toString('latin1');
      if (header.length > 10 || !/^\d*$/.test(header)) throw new ProtocolError('Invalid DBGp packet length');
      if (nul < 0) return;
      const length = Number(header);
      if (!length || length > this.maxPacketSize) throw new ProtocolError('DBGp packet length is zero or exceeds the limit');
      const end = nul + 1 + length;
      if (this.#buffer.length <= end) return;
      if (this.#buffer[end] !== 0) throw new ProtocolError('Missing DBGp packet terminator');
      const body = this.#buffer.subarray(nul+1,end);
      this.#buffer = this.#buffer.subarray(end+1);
      this.#packet(parsePacket(body));
    }
  }
  #packet({kind,node}) {
    if (kind === 'init') {
      if (this.#initialized) throw new ProtocolError('Duplicate DBGp initialization');
      this.#initialized = true;
    }
    if (kind !== 'response') return this.emit(kind,node);
    if (!/^[1-9]\d*$/.test(node.transaction_id ?? '')) throw new ProtocolError('Invalid response transaction ID');
    const id = Number(node.transaction_id);
    const pending = this.#pending.get(id);
    if (!pending) throw new ProtocolError(`Unknown DBGp transaction: ${id}`);
    if (node.command !== pending.name) throw new ProtocolError('DBGp response command does not match its transaction');
    if (node.error && (!/^\d+$/.test(node.error.code ?? '') || !Number.isSafeInteger(Number(node.error.code)))) throw new ProtocolError('Invalid engine error code');
    const error = node.error ? new XdebugError(pending.name,node.error.code,node.error.message?.['#text'] ?? node.error.message ?? '',{attributes:{...node.error},xml:node.rawXml,response:node}) : undefined;
    // Listeners validate and update execution before the waiter returns. Leave
    // the transaction registered until then so a protocol error rejects it too.
    this.emit('response',node,{id,name:pending.name,args:pending.args,data:pending.data,abandoned:pending.abandoned,error});
    this.#pending.delete(id);
    clearTimeout(pending.timer);
    pending.removeAbort();
    if (error) pending.reject(error);
    else pending.resolve(node);
  }
}
module.exports = {Connection,XdebugError,ProtocolError,ConnectionClosed,CommandTimeout,encodeCommand,parsePacket,NAMESPACE};
