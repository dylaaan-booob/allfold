'use strict';
const fs=require('node:fs'),path=require('node:path');
const {execFileSync}=require('node:child_process');
const {validateRepo,validateUpstream,readLock,validateGitlink,safePath}=require('./prepare-runtime.cjs');

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
  const entries=readLock(root); // Validate the complete lock before touching any checkout.
  for(const kind of ['upstream','translators']) {
    const [,url,revision]=entries.find(row=>row[0]===kind),name=kind==='upstream'?'zotero-connectors':'translators';
    const destination=path.join(root,'electron/vendor',name);
    let existing=true;
    try {safePath(root,'electron/vendor/'+name);}catch(error){if(error.code!=='ENOENT')throw error;existing=false;}
    if(existing)validateRepo(destination,revision,{connector:kind==='upstream',allowMissingSubmodules:kind==='upstream'});
    else {
      fs.mkdirSync(path.dirname(destination),{recursive:true});
      run('git',['init','--quiet',destination],root);
      run('git',['-C',destination,'remote','add','origin',url],root);
      run('git',['-C',destination,'fetch','--depth=1','origin',revision],root);
      run('git',['-C',destination,'checkout','--quiet','--detach','FETCH_HEAD'],root);
    }
    if(kind==='upstream') {
      const missing=[];
      for(const [,child,sha] of entries.filter(row=>row[0]==='submodule')) {
        validateGitlink(destination,child,sha);
        let absent=false;
        try {
          const directory=safePath(destination,child);
          if(!fs.lstatSync(directory).isDirectory())throw Error('Unsafe submodule path: '+child);
          if(fs.readdirSync(directory).length===0)absent=true;
          else validateRepo(directory,sha);
        }catch(error){if(error.code!=='ENOENT')throw error;absent=true;}
        if(absent)missing.push(child);
      }
      if(missing.length)run('git',['-C',destination,'submodule','update','--init','--checkout','--depth=1','--',...missing],root);
    }
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
