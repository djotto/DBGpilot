const {test} = require('node:test');
const assert = require('node:assert/strict');
const {PathMapper,PathMappingError} = require('../../lib/paths');
const mapper = (...rules) => new PathMapper(rules.map(([local,remote]) => ({local,remote})));
test('no mappings preserve explicit engine URIs and use an explicit base for relative paths',() => {
  const paths = new PathMapper([],{baseDir:'/work'});
  assert.equal(paths.toRemote('src/a b.php'),'file:///work/src/a%20b.php');
  for (const uri of ['file:///elsewhere/a.php','dbgp:eval-42']) assert.equal(paths.toRemote(uri),uri);
  assert.equal(paths.location('file:///app/x.php').localFile,undefined);
  assert.throws(() => paths.toLocal('file:///app/x.php'),/no remote root/);
});
for (const [suffix,encoded] of [['/index.php','/index.php'],['',''],['/',''],['/café #?%.php','/caf%C3%A9%20%23%3F%25.php'],['/src/../index.php','/index.php'],['/binary-\udcff.php','/binary-%FF.php']]) {
  test(`lexical URI round trip ${JSON.stringify(suffix)}`,() => {
    const paths = mapper(['/work/project/','file:///var/www/html/']);
    assert.equal(paths.toRemote('/work/project'+suffix),'file:///var/www/html'+encoded);
    assert.equal(paths.toLocal(paths.toRemote('/work/project'+suffix)),'/work/project'+suffix.replace('/src/..','').replace(/\/$/,''));
  });
}
test('longest component prefix wins without matching adjacent directory names',() => {
  const paths = mapper(['/work','file:///app'],['/work/vendor','file:///shared/vendor']);
  assert.equal(paths.toRemote('/work/vendor/lib/a.php'),'file:///shared/vendor/lib/a.php');
  assert.equal(paths.toLocal('file:///shared/vendor/lib/a.php'),'/work/vendor/lib/a.php');
  assert.equal(paths.toRemote('/work/vendor-other/a.php'),'file:///app/vendor-other/a.php');
  assert.throws(() => paths.toRemote('/workspace/file.php'),PathMappingError);
});
test('nested mappings must round-trip in both directions',() => {
  assert.throws(() => mapper(['/work','file:///app'],['/elsewhere','file:///app/vendor']).toRemote('/work/vendor/lib.php'),/round-trip/);
  const paths = mapper(['/work','file:///app'],['/work/vendor','file:///vendor']);
  assert.throws(() => paths.toLocal('file:///app/vendor/lib.php'),/round-trip/);
  assert.match(paths.location('file:///app/vendor/lib.php').pathMappingError,/round-trip/);
});
for (const rules of [[['/work','file:///a'],['/work/','file:///b']],[['/a','file:///app'],['/b','file:///app/']],[['C:\\Work','file:///a'],['c:\\work','file:///b']],[['/a','file://localhost/app'],['/b','file:///app']]]) {
  test(`duplicate roots rejected ${JSON.stringify(rules)}`,() => assert.throws(() => mapper(...rules),/Duplicate/));
}
test('Windows drive, UNC and remote drive namespaces are host independent',() => {
  const paths = mapper(['C:\\Users\\Alice\\Site','file:///var/www/html']);
  assert.equal(paths.toRemote('c:\\users\\ALICE\\site\\src\\café.php'),'file:///var/www/html/src/caf%C3%A9.php');
  assert.equal(paths.toLocal('file:///var/www/html/src/a.php'),'C:\\Users\\Alice\\Site\\src\\a.php');
  assert.throws(() => paths.toLocal('file:///VAR/www/html/a.php'),PathMappingError);
  const unc = mapper(['\\\\SERVER\\share\\Site','file:///app']);
  assert.equal(unc.toRemote('\\\\server\\SHARE\\site\\a.php'),'file:///app/a.php');
  assert.equal(unc.toLocal('file:///app/a.php'),'\\\\SERVER\\share\\Site\\a.php');
  const remote = mapper(['/work','file:///C:/App']);
  assert.equal(remote.toLocal('file:///c:/APP/src/a.php'),'/work/src/a.php');
  assert.equal(mapper(['/work','file:///C:/']).toRemote('/work'),'file:///C:/');
});
test('explicit remote case policy and IPv6 authority do not require network access',() => {
  const paths = new PathMapper([{local:'/work',remote:'file://SERVER/share/Site',remoteCaseSensitive:false}]);
  assert.equal(paths.toLocal('file://server/SHARE/site/a.php'),'/work/a.php');
  assert.equal(paths.toRemote('/work/a.php'),'file://server/share/Site/a.php');
  const ipv6 = mapper(['/work','file://[::1]/app']);
  assert.equal(ipv6.toRemote('/work/a.php'),'file://[::1]/app/a.php');
});
for (const uri of ['file:///app/../outside/a.php','file:///app/%2e%2e/outside/a.php','file:///app/%2F../outside/a.php','file:///application/a.php','file://other/app/a.php']) {
  test(`reject traversal or unrelated engine path ${uri}`,() => assert.throws(() => mapper(['/work','file:///app']).toLocal(uri),PathMappingError));
}
for (const uri of ['/app','dbgp:eval','https://example.com/app','file:relative','file:///app?query','file:///app#fragment','file://user@host/app','file:///app/%00','file:///app/%GG','file://host:/app','file://host:1/app']) {
  test(`reject invalid remote root ${uri}`,() => assert.throws(() => mapper(['/work',uri]),TypeError));
}
test('invalid inputs and Windows-incompatible components report errors',() => {
  assert.throws(() => mapper(['C:relative','file:///app']),TypeError);
  assert.throws(() => new PathMapper([{local:'/work',remtoe:'file:///app'}]),TypeError);
  assert.throws(() => new PathMapper([{local:'/work',remote:'file:///app',remoteCaseSensitive:'no'}]),TypeError);
  assert.throws(() => mapper(['C:\\Work','file:///app']).toLocal('file:///app/a%5Cb.php'),/Windows/);
  assert.throws(() => mapper(['/work','file:///C:/App']).toRemote('/work/a\\b.php'),/Windows/);
  assert.throws(() => mapper(['/work','file:///app']).toRemote(123),TypeError);
});
test('overlapping remote roots cannot mix case policies',() => assert.throws(() => new PathMapper([
  {local:'/work',remote:'file:///App'}, {local:'/vendor',remote:'file:///app/vendor',remoteCaseSensitive:false},
]),/case policy/));
test('configuration and overrides are copies, with the original local-root replacement contract',() => {
  const original = new PathMapper([{local:'.',remote:'file:///app'}],{baseDir:'/work'});
  const override = original.withOverrides([{local:'/work',remote:'file:///different'}]);
  assert.equal(override.toRemote('/work/a.php'),'file:///different/a.php');
  assert.equal(original.toRemote('a.php'),'file:///app/a.php');
  const copy = original.mappings; copy[0].remote = 'changed'; assert.equal(original.mappings[0].remote,'file:///app');
  assert.throws(() => original.withOverrides([{local:'/other',remote:'file:///app'}]),/Duplicate remote/);
});
test('generated Unicode and punctuation suffixes round-trip across lexical roots',() => {
  const paths = mapper(['/work','file:///app']);
  const components = ['café','abc XYZ','?query','#hash','%percent','🙂','binary-\udcfe','a._-'];
  for (let i=0;i<100;i++) {
    const suffix = [components[i%8],components[(i*3+1)%8],String(i)].join('/');
    assert.equal(paths.toLocal(paths.toRemote('/work/'+suffix)),'/work/'+suffix);
  }
});
