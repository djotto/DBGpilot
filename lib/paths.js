// Lexical path namespaces: Windows paths work even when Node runs in Linux.
const path = require('node:path');
const {encodeBytes,decodeBytes} = require('./encoding');
class PathMappingError extends Error {
  name = 'PathMappingError';
  constructor(value,direction,reason) {
    super(`${direction}: ${value}: ${reason}`);
    this.path = value; this.direction = direction; this.reason = reason;
  }
}
function input(value) {
  if (typeof value !== 'string' || !value || value.includes('\0')) throw new TypeError('Paths must be nonempty text without NUL');
  return value;
}
function decodePath(value) {
  if (/%(?![0-9a-f]{2})/i.test(value)) throw new TypeError('File URI contains an invalid percent escape');
  const parts = value.split(/(%[0-9a-f]{2})/i).filter(Boolean).map(part => /^%/.test(part) ? Buffer.from([parseInt(part.slice(1),16)]) : encodeBytes(part));
  return decodeBytes(Buffer.concat(parts));
}
function escapePath(value) {
  return [...encodeBytes(value)].map(byte => /[A-Za-z0-9_.~:/-]/.test(String.fromCharCode(byte))
    ? String.fromCharCode(byte) : `%${byte.toString(16).toUpperCase().padStart(2,'0')}`).join('');
}
function local(value,base) {
  input(value);
  const windows = /^[A-Za-z]:/.test(value) || value.startsWith('\\\\');
  const api = windows ? path.win32 : path.posix;
  if (windows && !api.isAbsolute(value)) throw new TypeError('Windows paths require an absolute drive or UNC share');
  const normalized = windows ? api.normalize(value) : api.resolve(base,value);
  const root = api.parse(normalized).root;
  const parts = [root,...normalized.slice(root.length).split(windows ? /[\\/]/ : '/').filter(Boolean)];
  const name = parts.length === 1 ? root : api.join(root,...parts.slice(1));
  return {windows,parts,path:name};
}
function remote(value) {
  input(value);
  const match = /^file:\/\/([^/?#]*)(\/[^?#]*)$/.exec(value);
  if (!match || match[1].includes('@') || (match[1].includes(':') && !/^\[[0-9a-f:.]+\]$/i.test(match[1]))) {
    throw new TypeError('Remote roots must be absolute file:// URIs without query, fragment, userinfo or port');
  }
  let host = match[1].toLowerCase();
  if (host === 'localhost') host = '';
  if (host) { try { new URL(`file://${host}/`); } catch { throw new TypeError('Invalid file URI authority'); } }
  const decoded = decodePath(match[2]);
  if (decoded.includes('\0')) throw new TypeError('File URI contains NUL');
  const windows = /^\/[A-Za-z]:(?:[/\\]|$)/.test(decoded);
  const parts = windows
    ? path.win32.normalize(decoded.slice(1)).split(/[\\/]/).filter(Boolean)
    : path.posix.normalize('/'+decoded.replace(/^\/+/, '')).split('/').filter(Boolean);
  return {host,windows,parts};
}
function uri(remotePath) {
  return `file://${remotePath.host}${escapePath('/'+remotePath.parts.join('/'))}${remotePath.windows && remotePath.parts.length === 1 ? '/':''}`;
}
function prefix(parts,root,caseSensitive = true) {
  return parts.length >= root.length && root.every((part,i) => caseSensitive ? part === parts[i] : part.toLowerCase() === parts[i].toLowerCase());
}
function sameLocal(a,b) { return a.windows === b.windows && a.parts.length === b.parts.length && prefix(a.parts,b.parts,!a.windows); }
class PathMapper {
  #rules;
  constructor(mappings = [],{baseDir = process.cwd()} = {}) {
    this.baseDir = path.resolve(baseDir);
    this.#rules = [];
    if (!Array.isArray(mappings)) throw new TypeError('Path mappings must be an array');
    for (const mapping of mappings) {
      if (!mapping || typeof mapping !== 'object' || Object.keys(mapping).some(key => !['local','remote','remoteCaseSensitive'].includes(key))) throw new TypeError('Invalid path mapping');
      if (mapping.remoteCaseSensitive !== undefined && typeof mapping.remoteCaseSensitive !== 'boolean') throw new TypeError('remoteCaseSensitive must be boolean');
      const localRoot = local(mapping.local,this.baseDir), remoteRoot = remote(mapping.remote);
      const caseSensitive = mapping.remoteCaseSensitive ?? !remoteRoot.windows;
      for (const other of this.#rules) {
        if (sameLocal(localRoot,other.local)) throw new TypeError('Duplicate local mapping root');
        if (remoteRoot.host === other.remote.host && remoteRoot.windows === other.remote.windows) {
          const overlap = prefix(remoteRoot.parts,other.remote.parts,false) || prefix(other.remote.parts,remoteRoot.parts,false);
          if (overlap && caseSensitive !== other.caseSensitive) throw new TypeError('Overlapping remote roots require the same case policy');
          if (remoteRoot.parts.length === other.remote.parts.length && prefix(remoteRoot.parts,other.remote.parts,caseSensitive)) throw new TypeError('Duplicate remote mapping root');
        }
      }
      this.#rules.push({local:localRoot,remote:remoteRoot,caseSensitive,mapping:{local:localRoot.path,remote:uri(remoteRoot),...(mapping.remoteCaseSensitive === undefined ? {} : {remoteCaseSensitive:mapping.remoteCaseSensitive})}});
    }
  }
  get mappings() { return this.#rules.map(rule => ({...rule.mapping})); }
  withOverrides(mappings,{baseDir = process.cwd()} = {}) {
    const overrides = new PathMapper(mappings,{baseDir});
    const retained = this.#rules.filter(rule => !overrides.#rules.some(other => sameLocal(rule.local,other.local))).map(rule => rule.mapping);
    return new PathMapper([...retained,...overrides.mappings],{baseDir:this.baseDir});
  }
  #outbound(value) {
    const rule = this.#rules.filter(rule => rule.local.windows === value.windows && prefix(value.parts,rule.local.parts,!value.windows)).sort((a,b) => b.local.parts.length-a.local.parts.length)[0];
    if (!rule) throw new PathMappingError(value.path,'toRemote','no local root matches; use an explicit engine URI');
    const suffix = value.parts.slice(rule.local.parts.length);
    if (rule.remote.windows && suffix.some(part => /[\\:]/.test(part))) throw new PathMappingError(value.path,'toRemote','component cannot be represented on remote Windows');
    return {remote:{...rule.remote,parts:[...rule.remote.parts,...suffix]},rule};
  }
  #inbound(value) {
    const rule = this.#rules.filter(rule => rule.remote.host === value.host && rule.remote.windows === value.windows && prefix(value.parts,rule.remote.parts,rule.caseSensitive)).sort((a,b) => b.remote.parts.length-a.remote.parts.length)[0];
    if (!rule) throw new PathMappingError(uri(value),'toLocal','no remote root matches');
    const suffix = value.parts.slice(rule.remote.parts.length);
    if (rule.local.windows && suffix.some(part => /[\\:]/.test(part))) throw new PathMappingError(uri(value),'toLocal','component cannot be represented on local Windows');
    const api = rule.local.windows ? path.win32 : path.posix;
    return local(api.join(rule.local.path,...suffix),this.baseDir);
  }
  toRemote(value) {
    input(value);
    if (/^(file|dbgp):/.test(value)) return value;
    const source = local(value,this.baseDir);
    if (!this.#rules.length) {
      if (source.windows && source.parts[0].startsWith('\\\\')) {
        const [host,share] = source.parts[0].split(/[\\/]/).filter(Boolean);
        return uri({host:host.toLowerCase(),windows:false,parts:[share,...source.parts.slice(1)]});
      }
      return uri({host:'',windows:source.windows,parts:source.windows ? [source.parts[0].slice(0,2),...source.parts.slice(1)] : source.parts.slice(1)});
    }
    const result = this.#outbound(source).remote;
    if (!sameLocal(this.#inbound(result),source)) throw new PathMappingError(value,'toRemote','overlapping mappings do not round-trip');
    return uri(result);
  }
  toLocal(value) {
    let target;
    try { target = remote(value); } catch (error) { throw new PathMappingError(value,'toLocal',error.message); }
    const result = this.#inbound(target);
    const forward = this.#outbound(result);
    if (forward.remote.host !== target.host || forward.remote.parts.length !== target.parts.length || !prefix(forward.remote.parts,target.parts,forward.rule.caseSensitive)) throw new PathMappingError(value,'toLocal','overlapping mappings do not round-trip');
    return result.path;
  }
  location(value) {
    if (!this.#rules.length || !value?.startsWith('file:')) return {localFile:undefined,pathMappingError:undefined};
    try { return {localFile:this.toLocal(value),pathMappingError:undefined}; }
    catch (error) { return {localFile:undefined,pathMappingError:error.message}; }
  }
}
module.exports = {PathMapper,PathMappingError};
