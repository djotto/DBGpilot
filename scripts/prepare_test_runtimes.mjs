// Build pinned historical Xdebug modules without changing serving PHP-FPM.
// Run with: ddev exec node scripts/prepare_test_runtimes.mjs
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';

if (!process.env.DDEV_SITENAME) throw new Error('Run this inside DDEV');
const cache = '/mnt/ddev-global-cache/dbgpilot/runtimes';
const sources = [
  ['8.2','3.3.2','15545b8311bedb5e7df08fd90d6653d9bf33629791e8119e70350475df932c55'],
  ['8.3','3.4.7','7592923501e3fdb9741ad35b90e08fc6b3c5dd31eadc4c83b7b3c9dda0627b24'],
];
fs.mkdirSync(cache,{recursive:true});
function run(command,args,options={}) {
  return execFileSync(command,args,{encoding:'utf8',timeout:600000,stdio:'inherit',...options});
}
if (sources.some(([php,version]) => !fs.existsSync(`${cache}/php${php}-xdebug${version}.so`))) {
  run('sudo',['env','DEBIAN_FRONTEND=noninteractive','apt-get','update','-qq']);
  run('sudo',['env','DEBIAN_FRONTEND=noninteractive','apt-get','install','-y','--no-install-recommends',
    'build-essential','autoconf','pkg-config','php8.2-dev','php8.3-dev']);
}
const results = [];
for (const [php,version,digest] of sources) {
  const module = `${cache}/php${php}-xdebug${version}.so`;
  if (!fs.existsSync(module)) {
    const url = `https://xdebug.org/files/xdebug-${version}.tgz`;
    const response = await fetch(url,{signal:AbortSignal.timeout(60000)});
    if (!response.ok) throw new Error(`Download failed: ${response.status} ${url}`);
    const payload = Buffer.from(await response.arrayBuffer());
    if (createHash('sha256').update(payload).digest('hex') !== digest) throw new Error(`Checksum mismatch: ${url}`);
    const temp = fs.mkdtempSync(path.join(os.tmpdir(),'dbgpilot-build-'));
    let log;
    try {
      const archive = path.join(temp,'source.tgz');fs.writeFileSync(archive,payload);
      run('tar',['-xzf',archive,'-C',temp,'--no-same-owner']);
      const cwd = path.join(temp,`xdebug-${version}`);
      log = fs.openSync(`${cache}/php${php}-xdebug${version}.build.log`,'w');
      const options = {cwd,stdio:['ignore',log,log]};
      console.log(`Building PHP ${php} / Xdebug ${version}`);
      run(`phpize${php}`,[],options);
      run('./configure',[`--with-php-config=/usr/bin/php-config${php}`,'--enable-xdebug'],options);
      run('make',['-j2'],options);
      fs.copyFileSync(path.join(cwd,'modules/xdebug.so'),module);
    } finally {
      if (log !== undefined) fs.closeSync(log);
      fs.rmSync(temp,{recursive:true,force:true});
    }
  }
  const args = [`/usr/bin/php${php}`,'-n','-d',`zend_extension=${module}`];
  const info = JSON.parse(run(args[0],[...args.slice(1),'-r',"echo json_encode([PHP_VERSION, phpversion('xdebug')]);"],{stdio:'pipe'}));
  if (!info[0].startsWith(php+'.') || info[1] !== version) throw new Error(`Unexpected runtime version: ${info}`);
  results.push({php:info[0],xdebug:info[1],args});
}
fs.writeFileSync(path.join(cache,'manifest.json'),JSON.stringify(results,null,2)+'\n');
console.log(JSON.stringify({event:'runtimes_ready',runtimes:results}));
