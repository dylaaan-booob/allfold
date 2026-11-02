'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),vm=require('node:vm');
const {execFileSync}=require('node:child_process');
const {prepareRuntime,validateRuntime,validateRepo,validateUpstream,LEGACY_RUNTIME_FILES,sha256,tracked}=require('../scripts/prepare-runtime.cjs');
const electron=path.resolve(__dirname,'..');
function temporary(t) {
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-runtime-build-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));return directory;
}
function generated(directory) {
  fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(path.join(directory,'owned.js'),'official');
  fs.writeFileSync(path.join(directory,'runtime-manifest.json'),JSON.stringify({format:1,files:[{path:'owned.js',sha256:sha256('official')}]}));
}
test('manifest ownership rejects edits, missing files, unknown files and unsafe paths',async t=>{
  for(const condition of ['modified','missing','unknown','escape','duplicate','symlink'])await t.test(condition,t=>{
    const dir=temporary(t);generated(dir);validateRuntime(dir);
    if(condition==='modified')fs.writeFileSync(path.join(dir,'owned.js'),'human');
    if(condition==='missing')fs.unlinkSync(path.join(dir,'owned.js'));
    if(condition==='unknown')fs.writeFileSync(path.join(dir,'user.txt'),'human');
    if(condition==='symlink'){fs.unlinkSync(path.join(dir,'owned.js'));fs.symlinkSync('elsewhere',path.join(dir,'owned.js'));}
    if(['escape','duplicate'].includes(condition)) {
      const file=path.join(dir,'runtime-manifest.json'),manifest=JSON.parse(fs.readFileSync(file));
      if(condition==='escape')manifest.files[0].path='../owned.js';else manifest.files.push(manifest.files[0]);
      fs.writeFileSync(file,JSON.stringify(manifest));
    }
    assert.throws(()=>validateRuntime(dir));
  });
});
test('source status checks include untracked files, and ignored files cannot be read as tracked input',t=>{
  const dir=temporary(t),repo=path.join(electron,'vendor/zotero-connectors/src/utilities');
  const checkout=path.join(dir,'source');
  execFileSync('git',['clone','--quiet','--shared',repo,checkout],{stdio:'pipe'});
  const revision=execFileSync('git',['-C',checkout,'rev-parse','HEAD'],{encoding:'utf8'}).trim();
  validateRepo(checkout,revision);
  fs.writeFileSync(path.join(checkout,'untracked.js'),'injected');assert.throws(()=>validateRepo(checkout,revision));
  fs.unlinkSync(path.join(checkout,'untracked.js'));
  fs.appendFileSync(path.join(checkout,'.git/info/exclude'),'\nignored.js\n');fs.writeFileSync(path.join(checkout,'ignored.js'),'injected');
  validateRepo(checkout,revision);assert.throws(()=>tracked(checkout,'ignored.js'));
  fs.appendFileSync(path.join(checkout,'date.js'),'\n// modified');assert.throws(()=>validateRepo(checkout,revision));
});
