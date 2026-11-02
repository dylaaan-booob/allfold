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
  'proxy.js','schema.js','utilities.js','http.js','inject/http.js','translateWeb.js','botBypass.js',
];
// One-time ownership list for the pre-manifest Runtime. Never discover ownership by globbing.
const LEGACY_RUNTIME_FILES=[
  "COPYING",
  "dateFormats.json",
  "http.js",
  "offscreenSandbox.html",
  "proxy.js",
  "registry.json",
  "schema.js",
  "translate/debug.js",
  "translate/http.js",
  "translate/promise.js",
  "translate/rdf/identity.js",
  "translate/rdf/init.js",
  "translate/rdf/n3parser.js",
  "translate/rdf/rdfparser.js",
  "translate/rdf/serialize.js",
  "translate/rdf/term.js",
  "translate/rdf/uri.js",
  "translate/tlds.js",
  "translate/translation/sandboxManager.js",
  "translate/translation/translate.js",
  "translate/translation/translate_item.js",
  "translate/translator.js",
  "translate/translators.js",
  "translate/utilities_translate.js",
  "utilities.js",
  "utilities/cachedTypes.js",
  "utilities/date.js",
  "utilities/openurl.js",
  "utilities/resource/zoteroTypeSchemaData.js",
  "utilities/schema.js",
  "utilities/utilities.js",
  "utilities/utilities_item.js",
  "utilities/xregexp-all.js",
  "utilities/xregexp-unicode-zotero.js",
  "zotero.js",
  "zotero_config.js"
];
const MANIFEST='runtime-manifest.json';
const sha256=bytes=>createHash('sha256').update(bytes).digest('hex');
const git=(repo,args)=>execFileSync('git',['-C',repo,...args],{encoding:'utf8'}).trim();
function validateRepo(repo,revision) {
  if(git(repo,['rev-parse','HEAD'])!==revision || git(repo,['status','--porcelain=v1','--untracked-files=all']))
    throw Error('Pinned source missing or modified: '+repo);
}
function tracked(repo,name) {
  if(git(repo,['ls-files','--error-unmatch','--',name])!==name)throw Error('Untracked build input');
  const file=path.join(repo,name);
  if(!fs.lstatSync(file).isFile())throw Error('Build input must be a regular file');
  return fs.readFileSync(file);
}
function validateUpstream(root) {
  const source=path.join(root,'electron/vendor/zotero-connectors'),translators=path.join(root,'electron/vendor/translators');
  const entries=fs.readFileSync(path.join(root,'electron/upstream.lock'),'utf8').split(/\r?\n/)
    .filter(line=>line.trim() && !line.startsWith('#')).map(line=>line.trim().split(/\s+/));
  const expected=['upstream','submodule:src/translate','submodule:src/utilities','submodule:src/zotero',
    'submodule:src/zotero-google-docs-integration','submodule:src/zotero-schema','translators'];
  const seen=new Set();
  for(const [kind,name,sha,...extra] of entries) {
    const key=kind==='submodule'?kind+':'+name:kind;
    if(!expected.includes(key) || seen.has(key) || extra.length || !/^[a-f0-9]{40}$/.test(sha))throw Error('Invalid upstream lock');
    seen.add(key);
    const repo=kind==='upstream'?source:kind==='translators'?translators:path.join(source,name);
    validateRepo(repo,sha);
    if(kind==='submodule' && git(source,['ls-tree','HEAD','--',name]).split(/\s+/)[2]!==sha)
      throw Error('Submodule differs from Connector gitlink: '+name);
  }
  if(seen.size!==expected.length)throw Error('Incomplete upstream lock');
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
function validateRuntime(directory) {
  try {fs.lstatSync(directory);}catch(error){if(error.code==='ENOENT')return {files:[],dirs:[]};throw error;}
  const actual=listFiles(directory),manifestFile=path.join(directory,MANIFEST);
  let owned=LEGACY_RUNTIME_FILES;
  if(fs.existsSync(manifestFile)) {
    const manifest=JSON.parse(fs.readFileSync(manifestFile,'utf8'));
    if(manifest.format!==1 || !Array.isArray(manifest.files))throw Error('Invalid Runtime manifest');
    const seen=new Set();
    for(const item of manifest.files) {
      const name=item.path;
      if(typeof name!=='string' || !name || name.includes('\\') || path.posix.normalize(name)!==name
        || path.posix.isAbsolute(name) || name.split('/').some(part=>part==='..' || part==='.')
        || name===MANIFEST || seen.has(name) || !/^[a-f0-9]{64}$/.test(item.sha256))throw Error('Unsafe Runtime manifest path');
      seen.add(name);
      if(!actual.files.includes(name) || sha256(fs.readFileSync(path.join(directory,name)))!==item.sha256)
        throw Error('Runtime file missing or modified: '+name);
    }
    owned=[...seen,MANIFEST];
  }
  const allowed=new Set(owned),allowedDirs=new Set();
  for(const name of owned)for(let dir=path.posix.dirname(name);dir!=='.';dir=path.posix.dirname(dir))allowedDirs.add(dir);
  if(actual.files.some(name=>!allowed.has(name)) || actual.dirs.some(name=>!allowedDirs.has(name)))throw Error('Unknown Runtime entry');
  return actual;
}
function removeRuntime(directory) {
  const {files,dirs}=validateRuntime(directory);
  for(const name of files)fs.unlinkSync(path.join(directory,name));
  for(const dir of dirs.sort((a,b)=>b.length-a.length))fs.rmdirSync(path.join(directory,dir));
  fs.rmdirSync(directory);
}
function prepareRuntime(root=path.resolve(__dirname,'../..')) {
  const {source,translators}=validateUpstream(root),electron=path.join(root,'electron'),output=path.join(electron,'runtime');
  validateRuntime(output);
  const stage=fs.mkdtempSync(path.join(electron,'.runtime-build-'));
  let previous;
  try {
    const write=(name,bytes)=>{const target=path.join(stage,name);fs.mkdirSync(path.dirname(target),{recursive:true});fs.writeFileSync(target,bytes);};
    for(const name of [...SCRIPTS,'itemSaver.js','itemSaver_background.js']) {
      let repo=source,relative='src/common/'+name;
      if(name.startsWith('translate/')){repo=path.join(source,'src/translate');relative='src/'+name.slice(10);}
      else if(name.startsWith('utilities/')){repo=path.join(source,'src/utilities');relative=name.slice(10);}
      let content=tracked(repo,relative);
      if(name==='schema.js')content=content.toString().replace('/*ZOTERO_SCHEMA*/',
        JSON.stringify(JSON.parse(tracked(path.join(source,'src/zotero-schema'),'schema.json'))));
      write(name,content);
    }
    const registry=[],ids=new Set();let translatorBytes=0;
    for(const file of git(translators,['ls-files','-z']).split('\0').filter(name=>/^[^/]+\.js$/.test(name))) {
      const code=tracked(translators,file),header=code.toString().match(/^\s*(\{[\s\S]*?\n\})/);
      if(!header)throw Error('Invalid Translator metadata: '+file);
      const metadata=JSON.parse(header[1]),id=metadata.translatorID;
      if(typeof id!=='string' || !/^[a-z0-9 -]+$/i.test(id) || ids.has(id))throw Error('Unsafe or duplicate Translator ID');
      ids.add(id);registry.push(metadata);write('translators/'+id+'.js',code);translatorBytes+=code.length;
    }
    write('document-compat.js',fs.readFileSync(path.join(electron,'src/zotero/document-compat.js')));
    write('registry.json',JSON.stringify(registry));
    write('dateFormats.json',tracked(path.join(source,'src/utilities'),'resource/dateFormats.json'));
    write('COPYING',tracked(source,'COPYING'));
    const html='<!doctype html><html><head><meta charset="UTF-8">'
      +'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'self\' \'unsafe-eval\'; connect-src \'self\'; form-action \'none\'">'
      +'</head><body>'+SCRIPTS.map(name=>'<script src="/'+name+'"></script>').join('')
      +'<script src="/document-compat.js"></script><script src="/sandbox-adapter.js"></script></body></html>';
    write('offscreen.html',html);
    const files=listFiles(stage).files.sort().map(name=>({path:name,sha256:sha256(fs.readFileSync(path.join(stage,name)))}));
    write(MANIFEST,JSON.stringify({format:1,files},null,2)+'\n');validateRuntime(stage);
    // Revalidate ownership immediately before replacing the old generated tree.
    validateRuntime(output);
    if(fs.existsSync(output)) {
      previous=fs.mkdtempSync(path.join(electron,'.runtime-before-'));fs.rmdirSync(previous);
      fs.renameSync(output,previous);
    }
    try {fs.renameSync(stage,output);} catch(error) {if(previous)fs.renameSync(previous,output);previous=null;throw error;}
    if(previous)removeRuntime(previous);
    const generated=listFiles(output).files;
    return {translator_count:registry.length,translator_bytes:translatorBytes,runtime_file_count:generated.length,
      runtime_bytes:generated.reduce((sum,name)=>sum+fs.statSync(path.join(output,name)).size,0),
      registry_bytes:fs.statSync(path.join(output,'registry.json')).size};
  } finally {if(fs.existsSync(stage))fs.rmSync(stage,{recursive:true,force:true});}
}
if(require.main===module)console.log(JSON.stringify(prepareRuntime()));
module.exports={prepareRuntime,validateRepo,validateUpstream,validateRuntime,LEGACY_RUNTIME_FILES,sha256,tracked};
