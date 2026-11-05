'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {execFileSync}=require('node:child_process');
const {prepareRuntime,tracked}=require('../scripts/prepare-runtime.cjs');
const {sourceFixture}=require('./runtime-sources.fixture.cjs');
function git(repo,args){return execFileSync('git',['-C',repo,...args],{encoding:'utf8',stdio:'pipe'}).trim();}
function file(root,name){return path.join(root,'electron/runtime',name);}
function snapshot(root){return fs.readFileSync(file(root,'runtime-manifest.json'),'utf8');}
test('complete pinned translation inputs build reproducibly without the retired save runtime',t=>{
  const root=sourceFixture(t),first=prepareRuntime(root),manifest=snapshot(root);
  assert.equal(first.translator_count,752);
  assert.equal(new Set(JSON.parse(fs.readFileSync(file(root,'registry.json'))).map(row=>row.translatorID)).size,752);
  for(const name of ['itemSaver.js','itemSaver_background.js','botBypass.js'])assert.equal(fs.existsSync(file(root,name)),false);
  assert.doesNotMatch(fs.readFileSync(file(root,'offscreen.html'),'utf8'),/itemSaver|botBypass/);
  prepareRuntime(root);assert.equal(snapshot(root),manifest);
});
test('Runtime refuses self-authorized or incomplete ownership and preserves original contents',async t=>{
  const base=sourceFixture(t);prepareRuntime(base);
  for(const condition of ['self-authorized','edited-known-hash','empty','subset','duplicate','unsafe','manifest-symlink','file-symlink','directory-symlink','unknown-directory','premanifest'])await t.test(condition,t=>{
    const root=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-runtime-refusal-'));t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
    fs.cpSync(base,root,{recursive:true,verbatimSymlinks:true});
    const manifest=JSON.parse(snapshot(root));
    if(condition==='self-authorized'){fs.writeFileSync(file(root,'user.txt'),'keep');manifest.files.push({path:'user.txt',sha256:require('node:crypto').createHash('sha256').update('keep').digest('hex')});}
    if(condition==='edited-known-hash'){fs.writeFileSync(file(root,'http.js'),'keep');manifest.files.find(row=>row.path==='http.js').sha256=require('node:crypto').createHash('sha256').update('keep').digest('hex');}
    if(condition==='empty')manifest.files=[];
    if(condition==='subset')manifest.files.pop();
    if(condition==='duplicate')manifest.files.push(manifest.files[0]);
    if(condition==='unsafe')manifest.files[0].path='../outside';
    fs.writeFileSync(file(root,'runtime-manifest.json'),JSON.stringify(manifest));
    if(condition==='manifest-symlink'){fs.renameSync(file(root,'runtime-manifest.json'),path.join(root,'outside'));fs.symlinkSync(path.join(root,'outside'),file(root,'runtime-manifest.json'));}
    if(condition==='file-symlink'){fs.unlinkSync(file(root,'http.js'));fs.symlinkSync(path.join(root,'outside'),file(root,'http.js'));}
    if(condition==='directory-symlink'){fs.renameSync(file(root,'translate'),path.join(root,'outside'));fs.symlinkSync(path.join(root,'outside'),file(root,'translate'));}
    if(condition==='unknown-directory')fs.mkdirSync(file(root,'user-empty'));
    if(condition==='premanifest')fs.unlinkSync(file(root,'runtime-manifest.json'));
    const before=fs.readdirSync(path.join(root,'electron/runtime')).sort();
    assert.throws(()=>prepareRuntime(root));assert.deepEqual(fs.readdirSync(path.join(root,'electron/runtime')).sort(),before);
    if(condition==='self-authorized')assert.equal(fs.readFileSync(file(root,'user.txt'),'utf8'),'keep');
  });
});
test('mandatory source bytes, index, paths and pinned gitlinks must match trusted HEAD',async t=>{
  for(const condition of ['missing','wrong-head','wrong-index','hidden-edit','symlink-file','symlink-ancestor','untracked','ignored'])await t.test(condition,t=>{
    const root=sourceFixture(t),source=path.join(root,'electron/vendor/zotero-connectors'),utilities=path.join(source,'src/utilities');
    if(condition==='missing')fs.unlinkSync(path.join(utilities,'date.js'));
    if(condition==='wrong-head')fs.writeFileSync(path.join(utilities,'.git/HEAD'),'ref: refs/heads/missing\n');
    if(condition==='wrong-index')git(source,['update-index','--cacheinfo','160000,bea5b9afc1cc424f066c38e77a42ddbef152070f,src/utilities']);
    if(condition==='hidden-edit'){git(utilities,['update-index','--assume-unchanged','date.js']);fs.writeFileSync(path.join(utilities,'date.js'),'keep');}
    if(condition==='symlink-file'){fs.unlinkSync(path.join(utilities,'date.js'));fs.symlinkSync('utilities.js',path.join(utilities,'date.js'));}
    if(condition==='symlink-ancestor'){fs.renameSync(utilities,path.join(root,'outside'));fs.symlinkSync(path.join(root,'outside'),utilities);}
    if(['untracked','ignored'].includes(condition)){
      fs.writeFileSync(path.join(utilities,'injected.js'),'keep');
      if(condition==='ignored')fs.appendFileSync(path.join(utilities,'.git/info/exclude'),'\ninjected.js\n');
      assert.throws(()=>tracked(utilities,'injected.js'));
      if(condition==='ignored')return;
    }
    assert.throws(()=>prepareRuntime(root));assert.equal(fs.existsSync(path.join(root,'electron/runtime')),false);
  });
});
test('verified PR26 generated Runtime migrates while unused legacy checkouts and user files stay intact',t=>{
  const root=sourceFixture(t),source=path.join(root,'electron/vendor/zotero-connectors');prepareRuntime(root);
  for(const name of ['itemSaver.js','itemSaver_background.js','botBypass.js'])fs.writeFileSync(file(root,name),tracked(source,'src/common/'+name));
  fs.copyFileSync(path.join(__dirname,'runtime-pr26-offscreen.fixture.html'),file(root,'offscreen.html'));
  const manifest=JSON.parse(snapshot(root));
  for(const name of ['itemSaver.js','itemSaver_background.js','botBypass.js','offscreen.html']){
    const hash=require('node:crypto').createHash('sha256').update(fs.readFileSync(file(root,name))).digest('hex');
    const row=manifest.files.find(item=>item.path===name);if(row)row.sha256=hash;else manifest.files.push({path:name,sha256:hash});
  }
  fs.writeFileSync(file(root,'runtime-manifest.json'),JSON.stringify(manifest));
  // Extra historical submodules can even be at another revision and contain user work.
  for(const name of ['src/zotero','src/zotero-google-docs-integration']){
    const destination=path.join(source,name);fs.cpSync(path.join(source,'src/utilities'),destination,{recursive:true,verbatimSymlinks:true});
    fs.writeFileSync(path.join(destination,'user.txt'),'keep');fs.appendFileSync(path.join(destination,'date.js'),'\n// old user edit\n');
  }
  const marker=path.join(source,'src/zotero/date.js'),before=fs.readFileSync(marker);
  require('../scripts/setup.cjs').prepareSources(root);prepareRuntime(root);
  assert.deepEqual(fs.readFileSync(marker),before);assert.equal(fs.readFileSync(path.join(source,'src/zotero/user.txt'),'utf8'),'keep');
  assert.equal(fs.existsSync(file(root,'itemSaver.js')),false);assert.doesNotMatch(fs.readFileSync(file(root,'offscreen.html'),'utf8'),/botBypass/);
});
