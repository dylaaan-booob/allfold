'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {initializeConfig,prepareSources}=require('../scripts/setup.cjs');
function fixture(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-setup-safety-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  fs.writeFileSync(path.join(root,'config.template.yaml'),'name: Example\n');
  return root;
}
test('first setup creates the local config without copying credentials',t=>{
  const root=fixture(t);initializeConfig(root);
  assert.equal(fs.readFileSync(path.join(root,'config.example.yaml'),'utf8'),'name: Example\n');
  assert.deepEqual(fs.readdirSync(root).sort(),['config.example.yaml','config.template.yaml']);
});
test('repeated setup preserves existing configuration, credentials and symlink targets',t=>{
  const root=fixture(t),target=path.join(root,'config.example.yaml'),secret=path.join(root,'config.example.openalex-secrets.json');
  fs.writeFileSync(target,'user settings');fs.writeFileSync(secret,'fixture credential');
  initializeConfig(root);
  assert.equal(fs.readFileSync(target,'utf8'),'user settings');assert.equal(fs.readFileSync(secret,'utf8'),'fixture credential');
  fs.unlinkSync(target);fs.symlinkSync(secret,target);initializeConfig(root);
  assert.ok(fs.lstatSync(target).isSymbolicLink());assert.equal(fs.readFileSync(secret,'utf8'),'fixture credential');
});
test('an existing invalid source is rejected without replacing its contents',t=>{
  const root=fixture(t),source=path.join(root,'electron/vendor/zotero-connectors');fs.mkdirSync(source,{recursive:true});
  const marker=path.join(source,'user.txt');fs.writeFileSync(marker,'keep');
  fs.writeFileSync(path.join(root,'electron/upstream.lock'),'upstream https://github.com/zotero/zotero-connectors.git '+'0'.repeat(40)+'\n');
  assert.throws(()=>prepareSources(root));assert.equal(fs.readFileSync(marker,'utf8'),'keep');
});
const {sourceFixture}=require('./runtime-sources.fixture.cjs');
const {execFileSync}=require('node:child_process');
function nativeLocalSources(t,root) {
  const rows=[
    ['protocol.file.allow','always'],
    ...['translate','utilities','zotero-schema'].map(name=>['url.'+path.join(root,'electron/vendor/zotero-connectors/src',name)+'.insteadOf','https://github.com/zotero/'+name+(name==='zotero-schema'?'':'.git')]),
  ];
  const saved={...process.env};
  process.env.GIT_CONFIG_COUNT=String(rows.length);
  rows.forEach(([key,value],index)=>{process.env['GIT_CONFIG_KEY_'+index]=key;process.env['GIT_CONFIG_VALUE_'+index]=value;});
  t.after(()=>{for(const key of Object.keys(process.env))if(!(key in saved))delete process.env[key];Object.assign(process.env,saved);});
}
test('native source preparation initializes only missing named children and repeats without touching existing sources',t=>{
  const provider=sourceFixture(t),root=sourceFixture(t),source=path.join(root,'electron/vendor/zotero-connectors');
  nativeLocalSources(t,provider);
  for(const name of ['translate','zotero-schema'])fs.rmSync(path.join(source,'src',name),{recursive:true});
  const existing=fs.readFileSync(path.join(source,'src/utilities/.git/HEAD'));
  prepareSources(root);prepareSources(root);
  assert.deepEqual(fs.readFileSync(path.join(source,'src/utilities/.git/HEAD')),existing);
  for(const name of ['translate','utilities','zotero-schema'])assert.ok(fs.existsSync(path.join(source,'src',name,'.git')));
  for(const name of ['zotero','zotero-google-docs-integration','translate/modules/utilities','utilities/resource/schema/global'])
    assert.equal(fs.existsSync(path.join(source,'src',name,'.git')),false);
});
test('invalid existing required child is rejected before Git can overwrite it',t=>{
  const root=sourceFixture(t),child=path.join(root,'electron/vendor/zotero-connectors/src/utilities');
  const target=path.join(child,'date.js');execFileSync('git',['-C',child,'update-index','--assume-unchanged','date.js']);
  fs.writeFileSync(target,'keep hidden user edit');
  assert.throws(()=>prepareSources(root));assert.equal(fs.readFileSync(target,'utf8'),'keep hidden user edit');
});
