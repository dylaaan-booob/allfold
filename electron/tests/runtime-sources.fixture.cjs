'use strict';
// Real pinned Git repositories, copied only into disposable test projects.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {execFileSync}=require('node:child_process');
const {after}=require('node:test');
const project=path.resolve(__dirname,'../..');let base;
after(()=>{if(base)fs.rmSync(base,{recursive:true,force:true});});
function clone(provider,target,sha){
  fs.mkdirSync(target,{recursive:true});
  for(const args of [['init','--quiet',target],['-C',target,'fetch','--quiet','--depth=1',provider,sha],['-C',target,'checkout','--quiet','--detach','FETCH_HEAD']])
    execFileSync('git',args,{stdio:'pipe',env:{...process.env,GIT_NO_LAZY_FETCH:'1'}});
}
function sourceFixture(t){
  if(!base){
    base=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-pinned-sources-'));
    const provider=process.env.ALLFOLD_TEST_SOURCE_ROOT || project;
    fs.mkdirSync(path.join(base,'electron/src/zotero'),{recursive:true});
    for(const relative of ['electron/upstream.lock','electron/src/zotero/document-compat.js'])fs.copyFileSync(path.join(project,relative),path.join(base,relative));
    const rows=fs.readFileSync(path.join(base,'electron/upstream.lock'),'utf8').split(/\r?\n/).filter(line=>line.trim()&&!line.startsWith('#')).map(line=>line.split(/\s+/));
    for(const [kind,name,sha] of rows){
      if(kind==='submodule'&&!['src/translate','src/utilities','src/zotero-schema'].includes(name))continue;
      const relative=kind==='submodule'?'zotero-connectors/'+name:kind==='upstream'?'zotero-connectors':'translators';
      clone(path.join(provider,'electron/vendor',relative),path.join(base,'electron/vendor',relative),sha);
    }
  }
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-source-test-'));
  fs.cpSync(base,root,{recursive:true,verbatimSymlinks:true});t.after(()=>fs.rmSync(root,{recursive:true,force:true}));return root;
}
module.exports={sourceFixture,clone};
