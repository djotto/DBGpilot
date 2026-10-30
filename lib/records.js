const {ProtocolError} = require('./dbgp');
const {text} = require('./values');
function integer(value,name,{optional = false,min = 0} = {}) {
  if (value === undefined && optional) return undefined;
  if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(Number(value)) || Number(value) < min) throw new ProtocolError(`Missing or invalid ${name}`);
  return Number(value);
}
function flag(response,name) {
  if (!['0','1'].includes(response[name])) throw new ProtocolError(`Invalid ${name} flag`);
  return response[name] === '1';
}
function feature(response) {
  const supported = flag(response,'supported');
  const value = (response['#text'] ?? '').trim();
  return {supported,value,enabled:supported && value === '1'};
}
function breakpoint(node,paths) {
  if (!node?.id || node.state === '') throw new ProtocolError('Breakpoint requires ID and nonempty state');
  return {
    id:node.id,type:node.type ?? 'line',state:node.state ?? 'enabled',fileUri:node.filename,...paths.location(node.filename),
    line:integer(node.lineno,'breakpoint line',{optional:true}),resolved:node.resolved,
    hitCount:integer(node.hit_count,'hit count',{optional:true}) ?? 0,
    hitValue:integer(node.hit_value,'hit value',{optional:true}) ?? 0,hitCondition:node.hit_condition,
    expression:node.expression === undefined ? undefined : text(node.expression),
    function:node.function,exception:node.exception,temporary:node.temporary === '1',attributes:{...node},
  };
}
function validateFrame(frame) {
  if (!Number.isSafeInteger(frame) || frame < 0) throw new TypeError('Frame must be a nonnegative integer');
}
function validateHit(hitValue,hitCondition) {
  if (hitValue !== undefined && (!Number.isSafeInteger(hitValue) || hitValue < 0)) throw new TypeError('Invalid breakpoint hit value');
  if (hitCondition !== undefined && !['>=','==','%'].includes(hitCondition)) throw new TypeError('Invalid breakpoint hit condition');
}
function validateState(state,optional = false) {
  if (!(optional && state === undefined) && !['enabled','disabled'].includes(state)) throw new TypeError('Invalid breakpoint state');
}
module.exports = {integer,flag,feature,breakpoint,validateFrame,validateHit,validateState};
