'use strict';
const fs=require('node:fs'),path=require('node:path');
const {createHash}=require('node:crypto');
const {execFileSync}=require('node:child_process');
const SCRIPTS=[
  'zotero_config.js','zotero.js',
  'utilities/openurl.js','utilities/date.js','utilities/xregexp-all.js','utilities/xregexp-unicode-zotero.js',
  'utilities/utilities.js','utilities/utilities_item.js','utilities/schema.js',
  'utilities/resource/zoteroTypeSchemaData.js','utilities/cachedTypes.js',
  'translate/promise.js','translate/utilities_translate.js','translate/debug.js','translate/http.js',
  'translate/translator.js','translate/translators.js','translate/translation/translate.js',
  'translate/translation/sandboxManager.js','translate/translation/translate_item.js','translate/tlds.js',
  'translate/rdf/init.js','translate/rdf/uri.js','translate/rdf/term.js','translate/rdf/identity.js',
  'translate/rdf/n3parser.js','translate/rdf/rdfparser.js','translate/rdf/serialize.js',
  'proxy.js','schema.js','utilities.js','http.js','inject/http.js','translateWeb.js',
];
const MANIFEST='runtime-manifest.json';
const REQUIRED_SUBMODULES=['src/translate','src/utilities','src/zotero-schema'];
const UNUSED_SUBMODULES=['src/zotero','src/zotero-google-docs-integration'];
const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
const git=(repo,args)=>execFileSync('git',['-C',repo,...args],{encoding:'utf8',stdio:'pipe'}).trimEnd();
function safePath(root,name='') {
  let current=root;
  if(!fs.lstatSync(current).isDirectory())throw Error('Unsafe source root: '+root);
  const parts=name.split('/').filter(Boolean);
  for(const [index,part] of parts.entries()) {
    if(part==='.' || part==='..' || part.includes('\\'))throw Error('Unsafe source path');
    current=path.join(current,part);
    const stat=fs.lstatSync(current);
    if(stat.isSymbolicLink() || (index<parts.length-1 && !stat.isDirectory()))throw Error('Unsafe source path: '+current);
  }
  return current;
}
function regularInput(root,name) {
  const file=safePath(root,name);if(!fs.lstatSync(file).isFile())throw Error('Build input must be a regular file: '+name);return fs.readFileSync(file);
}
function readLock(root) {
  const rows=regularInput(root,'electron/upstream.lock').toString('utf8').split(/\r?\n/)
    .filter(line=>line.trim() && !line.trim().startsWith('#')).map(line=>line.trim().split(/\s+/));
  const expected=['upstream',...REQUIRED_SUBMODULES.map(name=>'submodule:'+name),'translators'],seen=new Set();
  for(const [kind,name,sha,...extra] of rows) {
    const key=kind==='submodule'?kind+':'+name:kind;
    if(!expected.includes(key) || seen.has(key) || extra.length || !/^[a-f0-9]{40}$/.test(sha))throw Error('Invalid upstream lock');
    if(kind!=='submodule' && name!=='https://github.com/zotero/'+(kind==='upstream'?'zotero-connectors':'translators')+'.git')
      throw Error('Unexpected upstream repository');
    seen.add(key);
  }
  if(seen.size!==expected.length)throw Error('Incomplete upstream lock');
  return rows;
}
function validateRepo(repo,revision,{connector=false,allowMissingSubmodules=false}={}) {
  safePath(repo);
  const changes=git(repo,['status','--porcelain=v1','--untracked-files=all','--ignore-submodules=none','--','.',
    ...(connector?UNUSED_SUBMODULES.map(name=>':(exclude)'+name):[])]).split('\n').filter(Boolean);
  const modified=changes.some(line=>!(allowMissingSubmodules && REQUIRED_SUBMODULES.some(name=>line===' D '+name && !fs.existsSync(path.join(repo,name)))));
  if(!fs.existsSync(path.join(repo,'.git')) || fs.realpathSync(git(repo,['rev-parse','--show-toplevel']))!==fs.realpathSync(repo)
    || git(repo,['rev-parse','HEAD'])!==revision
    || modified)
    throw Error('Pinned source missing or modified: '+repo);
  const entries=inventory(repo);
  for(const [name,item] of entries.head)if(item.type==='blob' && ['100644','100755'].includes(item.mode))readTracked(repo,name,entries);
}
function inventory(repo) {
  const head=new Map(git(repo,['ls-tree','-r','-z','HEAD']).split('\0').filter(Boolean).map(line=>{
    const [,mode,type,hash,name]=line.match(/^(\d+) (\S+) ([a-f0-9]+)\t([\s\S]+)$/) || [];
    if(!name)throw Error('Invalid source inventory');return [name,{mode,type,hash}];
  }));
  const index=new Map(git(repo,['ls-files','--stage','-z']).split('\0').filter(Boolean).map(line=>{
    const [,mode,hash,stage,name]=line.match(/^(\d+) ([a-f0-9]+) (\d+)\t([\s\S]+)$/) || [];
    if(!name || stage!=='0')throw Error('Invalid source index');return [name,{mode,hash}];
  }));
  return {head,index};
}
function readTracked(repo,name,entries) {
  const expected=entries.head.get(name),indexed=entries.index.get(name);
  if(!expected || expected.type!=='blob' || !['100644','100755'].includes(expected.mode)
    || indexed?.mode!==expected.mode || indexed.hash!==expected.hash)throw Error('Untracked or modified build input: '+name);
  const file=safePath(repo,name);
  if(!fs.lstatSync(file).isFile())throw Error('Build input must be a regular file: '+name);
  const bytes=fs.readFileSync(file);
  // Compare the actual bytes to the pinned Git blob, even for assume-unchanged/skip-worktree entries.
  const hash=createHash('sha1').update('blob '+bytes.length+'\0').update(bytes).digest('hex');
  if(hash!==expected.hash)throw Error('Build input differs from pinned blob: '+name);
  return bytes;
}
function tracked(repo,name){return readTracked(repo,name,inventory(repo));}
function validateGitlink(source,name,sha) {
  const {head,index}=inventory(source),expected=head.get(name),indexed=index.get(name);
  if(expected?.mode!=='160000' || expected.type!=='commit' || expected.hash!==sha
    || indexed?.mode!=='160000' || indexed.hash!==sha)throw Error('Submodule differs from Connector gitlink: '+name);
}
function validateUpstream(root) {
  const rows=readLock(root),source=safePath(root,'electron/vendor/zotero-connectors'),translators=safePath(root,'electron/vendor/translators');
  for(const [kind,name,sha] of rows) {
    const repo=kind==='upstream'?source:kind==='translators'?translators:safePath(source,name);
    if(kind==='submodule')validateGitlink(source,name,sha);
    validateRepo(repo,sha,{connector:kind==='upstream'});
  }
  return {source,translators};
}
function listFiles(directory) {
  if(!fs.lstatSync(directory).isDirectory() || fs.lstatSync(directory).isSymbolicLink())throw Error('Unsafe Runtime root');
  const files=[],dirs=[];
  function walk(relative) {
    for(const item of fs.readdirSync(path.join(directory,relative),{withFileTypes:true})) {
      const name=relative?relative+'/'+item.name:item.name;
      if(item.isSymbolicLink())throw Error('Runtime symlink rejected');
      if(item.isDirectory()){dirs.push(name);walk(name);}
      else if(item.isFile())files.push(name);
      else throw Error('Unknown Runtime entry');
    }
  }
  walk('');return {files,dirs};
}
function validateRuntime(directory,profiles=[]) {
  try {fs.lstatSync(directory);}catch(error){if(error.code==='ENOENT')return {files:[],dirs:[]};throw error;}
  const actual=listFiles(directory);
  if(!actual.files.includes(MANIFEST))throw Error('Runtime has no verifiable ownership manifest');
  const manifest=JSON.parse(fs.readFileSync(path.join(directory,MANIFEST),'utf8'));
  if(manifest.format!==1 || !Array.isArray(manifest.files) || Object.keys(manifest).sort().join(',')!=='files,format')throw Error('Invalid Runtime manifest');
  const declared=new Map();
  for(const item of manifest.files) {
    const name=item?.path;
    if(typeof name!=='string' || !name || name.includes('\\') || path.posix.normalize(name)!==name
      || path.posix.isAbsolute(name) || name.split('/').some(part=>part==='..' || part==='.')
      || name===MANIFEST || declared.has(name) || !/^[a-f0-9]{64}$/.test(item.sha256)
      || Object.keys(item).sort().join(',')!=='path,sha256')throw Error('Unsafe Runtime manifest path');
    declared.set(name,item.sha256);
  }
  const expected=profiles.find(profile=>profile.size===declared.size && [...profile].every(([name,hash])=>declared.get(name)===hash));
  if(!expected)throw Error('Runtime manifest does not match a trusted generated profile');
  const allowedDirs=new Set();
  for(const name of expected.keys())for(let dir=path.posix.dirname(name);dir!=='.';dir=path.posix.dirname(dir))allowedDirs.add(dir);
  if(actual.files.length!==expected.size+1 || actual.files.some(name=>name!==MANIFEST&&!expected.has(name))
    || actual.dirs.some(name=>!allowedDirs.has(name)))throw Error('Unknown Runtime entry');
  for(const [name,hash] of expected)if(!actual.files.includes(name) || sha256(fs.readFileSync(path.join(directory,name)))!==hash)
    throw Error('Runtime file missing or modified: '+name);
  return actual;
}
function removeRuntime(directory,profiles) {
  const {files,dirs}=validateRuntime(directory,profiles);
  for(const name of files)fs.unlinkSync(path.join(directory,name));
  for(const dir of dirs.sort((a,b)=>b.length-a.length))fs.rmdirSync(path.join(directory,dir));
  fs.rmdirSync(directory);
}
function offscreenHTML(scripts) {
  return '<!doctype html><html><head><meta charset="UTF-8">'
    +'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'self\' \'unsafe-eval\'; connect-src \'self\'; form-action \'none\'">'
    +'</head><body>'+scripts.map(name=>'<script src="/'+name+'"></script>').join('')
    +'<script src="/document-compat.js"></script><script src="/sandbox-adapter.js"></script></body></html>';
}
function prepareRuntime(root=path.resolve(__dirname,'../..')) {
  const {source,translators}=validateUpstream(root),electron=path.join(root,'electron'),output=path.join(electron,'runtime');
  const stage=fs.mkdtempSync(path.join(electron,'.runtime-build-'));
  let previous;
  try {
    const inventories=new Map(),read=(repo,name)=>{
      if(!inventories.has(repo))inventories.set(repo,inventory(repo));return readTracked(repo,name,inventories.get(repo));
    };
    const write=(name,bytes)=>{const target=path.join(stage,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,bytes);};
    for(const name of SCRIPTS) {
      let repo=source,relative='src/common/'+name;
      if(name.startsWith('translate/')){repo=path.join(source,'src/translate');relative='src/'+name.slice(10);}
      else if(name.startsWith('utilities/')){repo=path.join(source,'src/utilities');relative=name.slice(10);}
      let content=read(repo,relative);
      if(name==='schema.js')content=content.toString().replace('/*ZOTERO_SCHEMA*/',
        JSON.stringify(JSON.parse(read(path.join(source,'src/zotero-schema'),'schema.json'))));
      write(name,content);
    }
    const registry=[],ids=new Set();let translatorBytes=0;
    for(const file of [...inventory(translators).head.keys()].filter(name=>/^[^/]+\.js$/.test(name))) {
      const code=read(translators,file),header=code.toString().match(/^\s*(\{[\s\S]*?\n\})/);
      if(!header)throw Error('Invalid Translator metadata: '+file);
      const metadata=JSON.parse(header[1]),id=metadata.translatorID;
      if(typeof id!=='string' || !/^[a-z0-9 -]+$/i.test(id) || ids.has(id))throw Error('Unsafe or duplicate Translator ID');
      ids.add(id);registry.push(metadata);write('translators/'+id+'.js',code);translatorBytes+=code.length;
    }
    write('document-compat.js',regularInput(root,'electron/src/zotero/document-compat.js'));
    write('registry.json',JSON.stringify(registry));
    write('dateFormats.json',read(path.join(source,'src/utilities'),'resource/dateFormats.json'));
    write('COPYING',read(source,'COPYING'));
    write('offscreen.html',offscreenHTML(SCRIPTS));
    const files=listFiles(stage).files.sort().map(name=>({path:name,sha256:sha256(fs.readFileSync(path.join(stage,name)))}));
    const current=new Map(files.map(item=>[item.path,item.sha256]));
    // Explicit PR #26 format-1 migration: same pinned translations, retired common writer and old entry HTML.
    // This bounded profile authorizes only the exact old generated bytes, never hashes supplied by the old manifest.
    const prior=new Map(current);
    for(const [name,hash] of Object.entries({
      'itemSaver.js':'6bafbb0145415f76ad0458cbdd85a1bde68b681d8725c83413527a886de14ee0',
      'itemSaver_background.js':'e6e048fafce80ea8f761aaa7853a06d40f49d28ffb0f1e0016814378cff31b2f',
      'botBypass.js':'4ae92ffc736d125c88916bf838aeac6c517852e8cf0ccb90a53d7f917ca0d652',
    }))prior.set(name,hash);
    prior.set('offscreen.html',sha256(offscreenHTML([...SCRIPTS,'botBypass.js'])));
    prior.set('document-compat.js','d094e208ddad7b9b61aa70496455a8adafc5629d9c15514148f4976fd6054b99');
    const profiles=[current,prior];
    write(MANIFEST,JSON.stringify({format:1,files},null,2)+'\n');validateRuntime(stage,[current]);
    // Revalidate ownership immediately before replacing and again before deleting the renamed old tree.
    validateRuntime(output,profiles);
    if(fs.existsSync(output)) {
      previous=fs.mkdtempSync(path.join(electron,'.runtime-before-'));fs.rmdirSync(previous);fs.renameSync(output,previous);
    }
    try {fs.renameSync(stage,output);} catch(error) {if(previous)fs.renameSync(previous,output);previous=null;throw error;}
    if(previous)removeRuntime(previous,profiles);
    const generated=listFiles(output).files;
    return {translator_count:registry.length,translator_bytes:translatorBytes,runtime_file_count:generated.length,
      runtime_bytes:generated.reduce((sum,name)=>sum+fs.statSync(path.join(output,name)).size,0),
      registry_bytes:fs.statSync(path.join(output,'registry.json')).size};
  } finally {if(fs.existsSync(stage))fs.rmSync(stage,{recursive:true,force:true});}
}
if(require.main===module)console.log(JSON.stringify(prepareRuntime()));
module.exports={prepareRuntime,validateRepo,validateUpstream,validateRuntime,readLock,validateGitlink,safePath,REQUIRED_SUBMODULES,sha256,tracked};
