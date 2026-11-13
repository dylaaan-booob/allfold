'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {initializeConfig}=require('../scripts/setup.cjs');
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
