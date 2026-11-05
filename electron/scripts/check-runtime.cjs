'use strict';
// Fresh CI inventory check after the real Setup; no alternate download/build path.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {execFileSync}=require('node:child_process');
const {prepareRuntime,validateUpstream}=require('./prepare-runtime.cjs');
const root=path.resolve(__dirname,'../..'),{source,translators}=validateUpstream(root),runtime=path.join(root,'electron/runtime');
for(const name of ['src/translate','src/utilities','src/zotero-schema'])assert.ok(fs.existsSync(path.join(source,name,'.git')));
for(const name of ['src/zotero','src/zotero-google-docs-integration','src/translate/modules/utilities','src/utilities/resource/schema/global'])
  assert.equal(fs.existsSync(path.join(source,name,'.git')),false,'Unexpected initialized child: '+name);
const code=execFileSync('git',['-C',translators,'ls-tree','-r','--name-only','-z','HEAD'],{encoding:'utf8'}).split('\0').filter(name=>/^[^/]+\.js$/.test(name));
const registry=JSON.parse(fs.readFileSync(path.join(runtime,'registry.json')));
assert.equal(code.length,752);assert.equal(registry.length,code.length);assert.equal(new Set(registry.map(item=>item.translatorID)).size,code.length);
for(const name of ['itemSaver.js','itemSaver_background.js','botBypass.js'])assert.equal(fs.existsSync(path.join(runtime,name)),false);
assert.doesNotMatch(fs.readFileSync(path.join(runtime,'offscreen.html'),'utf8'),/itemSaver|botBypass/);
const manifest=fs.readFileSync(path.join(runtime,'runtime-manifest.json'));prepareRuntime(root);
assert.deepEqual(fs.readFileSync(path.join(runtime,'runtime-manifest.json')),manifest);
console.log('Fresh selective sources and deterministic Runtime verified: '+registry.length+' Translators');
