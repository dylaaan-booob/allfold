'use strict';
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const {executeLocalBody}=require('../src/workflows/local-body.cjs');

function fixture(t){
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-local-body-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  fs.mkdirSync(path.join(root,'Documents/nested'),{recursive:true});
  const file=path.join(root,'Documents/nested/retained.pdf');fs.writeFileSync(file,'normal transfer bytes');
  const identity=name=>{const stat=fs.lstatSync(name);return [stat.dev,stat.ino];};
  const data={workspace_root:root,workspace_id:'12345678-1234-4234-8234-123456789012',paper_id:'12345678-1234-4234-8234-123456789013',body_generation:2,
    action:'open',body:{relative_path:'Documents/nested/retained.pdf',workspace:identity(root),
      directories:[identity(path.join(root,'Documents')),identity(path.join(root,'Documents/nested'))],file:identity(file)}};
  return {root,file,data};
}

test('current nested body opens with a controlled shell after current authority verification',async t=>{
  const {file,data}=fixture(t),calls=[];
  const result=await executeLocalBody(data,{verifyAuthority:async()=>calls.push('verified'),
    shell:{openPath:async target=>{assert.equal(target,file);calls.push('opened');return '';}}});
  assert.deepEqual(calls,['verified','opened']);assert.equal(result.outcome,'opened');assert.equal(result.resource_closed,true);
});

test('openPath nonempty error is finite failure and locate only reports its request',async t=>{
  const {file,data}=fixture(t);
  const failed=await executeLocalBody(data,{verifyAuthority:async()=>{},shell:{openPath:async()=>`private error ${file}`}});
  assert.equal(failed.outcome,'local_failure');assert.ok(!JSON.stringify(failed).includes(file));
  const located=await executeLocalBody({...data,action:'locate'},{verifyAuthority:async()=>{},shell:{showItemInFolder:target=>assert.equal(target,file)}});
  assert.equal(located.outcome,'locate_requested');assert.notEqual(located.outcome,'opened');
});

for(const replacement of ['file','directory','symlink','hardlink','workspace'])test(`a ${replacement} replacement during authority confirmation never reaches shell`,async t=>{
  const {root,file,data}=fixture(t);let opened=false;
  const result=await executeLocalBody(data,{verifyAuthority:async()=>{
    if(replacement==='workspace'){
      fs.renameSync(root,root+'-old');fs.mkdirSync(root);
      t.after(()=>fs.rmSync(root+'-old',{recursive:true,force:true}));
    }else if(replacement==='directory'){
      fs.renameSync(path.dirname(file),path.dirname(file)+'-old');fs.mkdirSync(path.dirname(file));
      fs.writeFileSync(file,'unknown');
    }else if(replacement==='hardlink')fs.linkSync(file,file+'.link');
    else {fs.renameSync(file,file+'.old');if(replacement==='symlink')fs.symlinkSync(file+'.old',file);else fs.writeFileSync(file,'unknown');}
  },shell:{openPath:async()=>{opened=true;return '';}}});
  assert.equal(opened,false);assert.equal(result.outcome,'local_failure');assert.equal(result.resource_closed,true);
});

test('confirmed missing leaf differs from unsafe parent and shell failures',async t=>{
  const {data,file}=fixture(t);let opened=false;
  fs.unlinkSync(file);
  const missing=await executeLocalBody(data,{verifyAuthority:async()=>{},shell:{openPath:async()=>{opened=true;return '';}}});
  assert.equal(missing.outcome,'missing');assert.equal(opened,false);
  fs.rmdirSync(path.dirname(file));
  const unsafe=await executeLocalBody(data,{verifyAuthority:async()=>{},shell:{}});
  assert.equal(unsafe.outcome,'local_failure');
});
