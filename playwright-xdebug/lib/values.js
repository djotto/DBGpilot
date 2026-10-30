const { isUtf8 } = require('node:buffer');
const { ProtocolError } = require('./dbgp');
const {encodeBytes} = require('./encoding');
function bytes(node) {
  const raw = typeof node === 'object' ? node?.['#text'] ?? '' : node ?? '';
  if (node?.encoding === 'base64') {
    const encoded = String(raw).replace(/\s/g,'');
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(encoded)) {
      throw new ProtocolError('Invalid base64 property data');
    }
    return Buffer.from(encoded,'base64');
  }
  if (node?.encoding && node.encoding !== 'none') throw new ProtocolError('Unsupported property encoding');
  return encodeBytes(String(raw));
}
function text(node) {
  const data = bytes(node);
  return isUtf8(data) ? data.toString('utf8') : data;
}
function integer(value,name,fallback) {
  if (value === undefined) return fallback;
  if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(Number(value))) throw new ProtocolError(`Invalid property ${name}`);
  return Number(value);
}
function parseProperty(property,typeMap = new Map()) {
  if (!property || typeof property !== 'object' || !property.type) throw new ProtocolError('Response contains no valid property');
  const commonType = typeMap.get(property.type)?.type ?? property.type;
  const children = (property.property ?? []).map(child => parseProperty(child,typeMap));
  const rawValue = ['array','hash','object','null','uninitialized'].includes(commonType) ? undefined : bytes(property.value ?? property);
  let value;
  const scalar = rawValue?.toString();
  switch (commonType) {
    case 'array':
    case 'hash':
    case 'object': value = null; break;
    case 'null': value = null; break;
    case 'uninitialized': value = undefined; break;
    case 'boolean':
    case 'bool':
      if (!['0','1'].includes(scalar)) throw new ProtocolError('Invalid boolean property');
      value = scalar === '1'; break;
    case 'integer':
    case 'int': {
      if (!/^[+-]?\d+$/.test(scalar)) throw new ProtocolError('Invalid integer property');
      const big = BigInt(scalar);
      value = big <= BigInt(Number.MAX_SAFE_INTEGER) && big >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(big) : big;
      break;
    }
    case 'double':
    case 'float':
      if (!['INF','-INF','NAN'].includes(scalar) && !/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(scalar)) throw new ProtocolError('Invalid float property');
      value = scalar === 'INF' ? Infinity : scalar === '-INF' ? -Infinity : scalar === 'NAN' ? NaN : Number(scalar);
      if (Number.isNaN(value) && scalar !== 'NAN') throw new ProtocolError('Invalid float property');
      break;
    default: if (rawValue !== undefined) value = isUtf8(rawValue) ? rawValue.toString() : rawValue;
  }
  const totalChildren = integer(property.numchildren,'numchildren',children.length);
  const size = integer(property.size,'size');
  const page = integer(property.page,'page',0);
  return {
    name:text(property.name), fullname:text(property.fullname), type:property.type,commonType,
    classname:property.classname === undefined ? undefined : text(property.classname),
    value, rawValue, children, totalChildren, size, page,
    pageSize:integer(property.pagesize,'pagesize'),
    hasChildren:property.children === '1' || totalChildren > 0,
    childrenTruncated:page > 0 || totalChildren > children.length,
    valueTruncated:rawValue !== undefined && size !== undefined && size > rawValue.length,
    facet:property.facet, facets:(property.facet ?? '').split(/\s+/).filter(Boolean),
    constant:property.constant === undefined ? undefined:property.constant === '1', key:property.key, address:property.address,
  };
}
// Typed partial values cannot be mistaken for PHP string placeholders.
class PartialValue {
  constructor(property) {
    this.type = property.type;
    this.classname = property.classname;
    this.totalChildren = property.totalChildren;
    this.children = property.children.map(child => ({name:child.name,value:plainValue(child)}));
    this.truncated = property.childrenTruncated || property.valueTruncated;
    if (property.rawValue !== undefined) this.rawValue = property.rawValue;
  }
}
function plainValue(property) {
  if (property.valueTruncated) return new PartialValue(property);
  if (!['array','hash','object'].includes(property.commonType)) return property.value;
  if (property.childrenTruncated || property.children.some(p => Buffer.isBuffer(p.name))) return new PartialValue(property);
  const entries = property.children.map(child => [child.name,plainValue(child)]);
  if (property.commonType === 'object') return {__class:property.classname,...Object.fromEntries(entries)};
  return entries.every(([key],i) => key === String(i)) ? entries.map(([,value]) => value) : Object.fromEntries(entries);
}
function toValue(property,typeMap) { return plainValue(parseProperty(property,typeMap)); }
function toPhp(value,seen = new Set()) {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'bigint') {
    if (value < -(2n ** 63n) || value >= 2n ** 63n) throw new RangeError('Integer exceeds signed 64-bit PHP range');
    return String(value);
  }
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || (Number.isInteger(value) && !Number.isSafeInteger(value))) {
      throw new RangeError('Use a BigInt for large integers and an explicit PHP expression for nonfinite numbers');
    }
    return String(value);
  }
  if (typeof value === 'string' || Buffer.isBuffer(value)) return `base64_decode('${(Buffer.isBuffer(value) ? value:encodeBytes(value)).toString('base64')}')`;
  if (!value || typeof value !== 'object' || (!Array.isArray(value) && Object.getPrototypeOf(value) !== Object.prototype)) {
    throw new TypeError('Assignments accept null, scalars, Buffers, arrays and plain objects');
  }
  if (seen.has(value)) throw new TypeError('Cannot assign a cyclic object');
  seen.add(value);
  try {
    const entries = Array.isArray(value) ? Array.from(value,child => toPhp(child,seen))
      : Object.entries(value).map(([key,child]) => `${toPhp(key,seen)} => ${toPhp(child,seen)}`);
    return `[${entries.join(', ')}]`;
  } finally { seen.delete(value); }
}
function toJSONSafe(value) {
  if (Buffer.isBuffer(value)) return {encoding:'base64',data:value.toString('base64')};
  if (typeof value === 'bigint') return {type:'bigint',value:String(value)};
  if (typeof value === 'number' && !Number.isFinite(value)) return {type:'float',value:String(value)};
  if (value === undefined) return {type:'uninitialized'};
  if (Array.isArray(value)) return value.map(toJSONSafe);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key,child]) => [key,toJSONSafe(child)]));
  return value;
}
module.exports = {bytes,text,parseProperty,plainValue,toValue,toPhp,toJSONSafe,PartialValue};
