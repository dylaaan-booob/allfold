'use strict';
const fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {validateRepo,validateUpstream}=require('./prepare-runtime.cjs');

const ROOT=path.resolve(__dirname,'../..');
function run(command,args,cwd=ROOT) {
  execFileSync(command,args,{cwd,stdio:'inherit',env:{...process.env,GIT_TERMINAL_PROMPT:'0'}});
}
function initializeConfig(root=ROOT) {
  const target=path.join(root,'config.example.yaml');
  try {fs.copyFileSync(path.join(root,'config.template.yaml'),target,fs.constants.COPYFILE_EXCL);}
  catch(error) {if(error.code!=='EEXIST')throw error;}
}
function prepareSources(root=ROOT) {
  const entries=fs.readFileSync(path.join(root,'electron/upstream.lock'),'utf8').split(/\r?\n/)
    .filter(line=>line.trim() && !line.startsWith('#')).map(line=>line.trim().split(/\s+/));
  for(const kind of ['upstream','translators']) {
    const rows=entries.filter(row=>row[0]===kind);
    if(rows.length!==1 || rows[0].length!==3 || !/^[a-f0-9]{40}$/.test(rows[0][2]))throw Error('Invalid upstream lock');
    const [,url,revision]=rows[0],name=kind==='upstream'?'zotero-connectors':'translators';
    if(url!=='https://github.com/zotero/'+name+'.git')throw Error('Unexpected upstream repository');
    const destination=path.join(root,'electron/vendor',name);
    if(fs.existsSync(destination)) {validateRepo(destination,revision);continue;}
    fs.mkdirSync(path.dirname(destination),{recursive:true});
    run('git',['init','--quiet',destination],root);
    run('git',['-C',destination,'remote','add','origin',url],root);
    run('git',['-C',destination,'fetch','--depth=1','origin',revision],root);
    run('git',['-C',destination,'checkout','--quiet','--detach','FETCH_HEAD'],root);
    if(kind==='upstream')run('git',['-C',destination,'submodule','update','--init','--depth=1'],root);
  }
  validateUpstream(root);
}
function setup() {
  if(Number(process.versions.node.split('.')[0])!==24)throw Error('Node.js 24 is required');
  run('git',['--version']);run('uv',['--version']);
  run('uv',['python','find','3.12']);
  initializeConfig();
  run('uv',['sync','--locked','--group','dev']);
  run('npm',['ci','--prefix','electron']);
  // Electron's official on-demand installer completes before parallel Node tests can import it.
  run(process.execPath,[path.join(ROOT,'electron/node_modules/electron/install.js')]);
  const installed=path.join(ROOT,'electron/node_modules/electron');
  const version=JSON.parse(fs.readFileSync(path.join(installed,'package.json'),'utf8')).version;
  if(fs.readFileSync(path.join(installed,'dist/version'),'utf8').trim().replace(/^v/,'')!==version)
    throw Error('Electron binary version mismatch');
  const binary=path.join(installed,'dist',fs.readFileSync(path.join(installed,'path.txt'),'utf8').trim());
  if(!fs.statSync(binary).isFile())throw Error('Electron binary missing');
  run('npm',['ci','--prefix','tools']);
  prepareSources();
  run(process.execPath,['tools/build-ui-next.mjs']);
  run('npm',['--prefix','electron','run','prepare-runtime']);
  console.log('Setup complete. Start with: npm --prefix electron start');
}
if(require.main===module) {
  try {setup();}catch(error) {console.error('Setup failed:',error.message);process.exitCode=1;}
}
module.exports={initializeConfig,prepareSources};
