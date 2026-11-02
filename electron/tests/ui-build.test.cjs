'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
function fixture(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-ui-build-'));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const source=path.join(root,'frontend/ui'),output=path.join(root,'src/allfold/web/static/ui_next');
  fs.mkdirSync(source,{recursive:true});
  fs.writeFileSync(path.join(source,'kept.js'),"import './kept.css'; export const ready=true;");
  fs.writeFileSync(path.join(source,'kept.css'),'body { color: orange; }');
  fs.writeFileSync(path.join(source,'index.html'),'<script type="module" src="kept-app.js"></script>');
  fs.writeFileSync(path.join(source,'font.woff2'),'fixture-font-bytes');
  return {root,source,output};
}
test('UI delivery copies unchanged assets and rebuilds JS/CSS without changing source',async t=>{
  const {buildUI}=await import('../../tools/build-ui-next.mjs'),f=fixture(t);
  const original=fs.readFileSync(path.join(f.source,'kept.js'));
  await buildUI(f.root);
  assert.match(fs.readFileSync(path.join(f.output,'kept-app.js'),'utf8'),/ready/);
  assert.match(fs.readFileSync(path.join(f.output,'kept-app.css'),'utf8'),/orange/);
  assert.equal(fs.readFileSync(path.join(f.output,'font.woff2'),'utf8'),'fixture-font-bytes');
  assert.deepEqual(fs.readFileSync(path.join(f.source,'kept.js')),original);
  assert.ok(!fs.existsSync(path.join(f.output,'kept.js')));
});
test('UI build rejects existing and dangling output symlinks without touching their targets',async t=>{
  const {buildUI}=await import('../../tools/build-ui-next.mjs'),f=fixture(t),target=path.join(f.root,'user-data');
  fs.mkdirSync(path.dirname(f.output),{recursive:true});fs.mkdirSync(target);
  fs.writeFileSync(path.join(target,'paper.md'),'human content');
  fs.symlinkSync(target,f.output);
  await assert.rejects(buildUI(f.root),/symlink/);
  assert.equal(fs.readFileSync(path.join(target,'paper.md'),'utf8'),'human content');
  fs.unlinkSync(f.output);fs.symlinkSync(path.join(f.root,'missing'),f.output);
  await assert.rejects(buildUI(f.root),/symlink/);
});
