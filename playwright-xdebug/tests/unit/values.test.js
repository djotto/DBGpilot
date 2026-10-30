const {test} = require('node:test');
const assert = require('node:assert/strict');
const {toValue,toPhp,parseProperty,toJSONSafe,PartialValue} = require('../../lib/values');
const scalar = (type,value) => ({type,encoding:'base64','#text':Buffer.from(value).toString('base64')});
test('binary values retain every byte and UTF-8 strings remain strings',() => {
  const data = Buffer.from([255,0,120]); assert.deepEqual(toValue(scalar('string',data)),data);
  assert.equal(toValue(scalar('string','  é🙂\0  ')),'  é🙂\0  ');
});
for (const [wire,value] of [['42',42],['9007199254740991',Number.MAX_SAFE_INTEGER],['9223372036854775807',9223372036854775807n],['-9223372036854775808',-9223372036854775808n]]) {
  test(`integer fidelity ${wire}`,() => assert.equal(toValue(scalar('int',wire)),value));
}
test('nonfinite floats retain their meaning and serialize explicitly',() => {
  assert.equal(toValue(scalar('float','INF')),Infinity); assert.equal(toValue(scalar('float','-INF')),-Infinity);
  assert(Number.isNaN(toValue(scalar('float','NAN'))));
  const safe = toJSONSafe({integer:9223372036854775807n,binary:Buffer.from([255]),inf:Infinity,unset:undefined});
  assert.equal(JSON.parse(JSON.stringify(safe)).integer.value,'9223372036854775807');
  assert.equal(safe.binary.data,'/w=='); assert.equal(safe.inf.value,'Infinity');
});
test('partial containers retain fetched children and cannot masquerade as PHP strings',() => {
  const value = toValue({type:'array',numchildren:'2',property:[{name:'0',...scalar('int','7')}]});
  assert(value instanceof PartialValue); assert.deepEqual(value.children,[{name:'0',value:7}]); assert.equal(value.totalChildren,2);
  assert.deepEqual(toValue({type:'array',numchildren:'0'}),[]);
});
test('extended properties preserve binary names, fullname and raw values',() => {
  const prop = parseProperty({type:'string',name:{encoding:'base64','#text':'/wA='},fullname:{encoding:'base64','#text':'JHg='},value:{encoding:'base64','#text':'/wA='},size:'2',facet:'private',address:'123'});
  assert.deepEqual(prop.name,Buffer.from([255,0])); assert.equal(prop.fullname,'$x'); assert.equal(prop.facet,'private');
  assert.deepEqual(prop.rawValue,Buffer.from([255,0]));
});
test('truncated strings are explicit and retain their received prefix',() => {
  const prop = {...scalar('string','abc'),size:'10'};
  assert.equal(parseProperty(prop).valueTruncated,true); assert.deepEqual(toValue(prop).rawValue,Buffer.from('abc'));
});
for (const wire of [{type:'int','#text':'no'}, {type:'bool','#text':'2'}, {type:'string',encoding:'base64','#text':'!!'}, {type:'array',page:'-1'}]) {
  test(`reject malformed property ${JSON.stringify(wire)}`,() => assert.throws(() => parseProperty(wire)));
}
test('assignment encoding preserves binary, BigInt and nested values',() => {
  assert.equal(toPhp(Buffer.from([255,0])),"base64_decode('/wA=')");
  assert.equal(toPhp(9223372036854775807n),'9223372036854775807');
  assert.match(toPhp({list:[1,2.5,'three'],flag:false,none:null}),/false/);
});
for (const value of [Infinity,NaN,Number.MAX_SAFE_INTEGER+1,2n**63n,undefined,new Date()]) {
  test(`reject lossy/unsupported assignment ${String(value)}`,() => assert.throws(() => toPhp(value)));
}
test('cyclic assignments fail before sending PHP code',() => {
  const cycle = {}; cycle.self = cycle; assert.throws(() => toPhp(cycle),/cyclic/);
});
