'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),{randomUUID}=require('node:crypto');
const {NativeOutput}=require('../src/workflows/native-output.cjs');
const identity=file=>{const info=fs.lstatSync(file);return [info.dev,info.ino];};
function capability(t) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-native-output-'))),paper=randomUUID();
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const documents=path.join(root,'Documents'),staging=path.join(documents,'.downloads'),disposal=path.join(staging,'.cleanup');
  fs.mkdirSync(disposal,{recursive:true,mode:0o700});
  const directory=path.join(staging,paper+'.1.native');fs.mkdirSync(directory,{mode:0o700});
  const temporary=`Documents/.downloads/${paper}.1.native/body.part`;
  return {root,filename:path.join(root,temporary),output:new NativeOutput({workspace_root:root,paper_id:paper,attempt:1,deadline_ms:Date.now()+10000,
    output:{temporary,target:`Documents/${paper}.pdf`,file:null,workspace:identity(root),documents:identity(documents),
      staging:identity(staging),disposal:identity(disposal),native_directory:identity(directory)}})};
}
test('unlinked empty reservations never qualify final or already owned output',t=>{
  const {root,filename,output}=capability(t),reservation=path.join(root,'reservation');
  fs.writeFileSync(reservation,'');const fd=fs.openSync(reservation,'r');fs.unlinkSync(reservation);
  let unlinked;try{unlinked=fs.fstatSync(fd);}finally{fs.closeSync(fd);}
  assert.equal(unlinked.nlink,0);assert.equal(unlinked.size,0);
  const lstat=fs.lstatSync;
  const observe=()=>t.mock.method(fs,'lstatSync',(file,...options)=>file===filename?unlinked:lstat(file,...options));
  let mocked=observe();
  assert.equal(output.capture({missing:true}),null);
  assert.throws(()=>output.capture(),error=>error.bodyLocal===true);
  mocked.mock.restore();
  fs.writeFileSync(filename,'completed output');
  assert.deepEqual(output.capture(),{file:identity(filename),size:16});
  mocked=observe();
  assert.throws(()=>output.capture({missing:true}),error=>error.bodyLocal===true);
  mocked.mock.restore();
});
test('empty linked and symlinked destinations remain refused',t=>{
  for(const kind of ['hardlink','symlink']) {
    const {root,filename,output}=capability(t),foreign=path.join(root,'foreign');fs.writeFileSync(foreign,'');
    if(kind==='hardlink')fs.linkSync(foreign,filename);else fs.symlinkSync(foreign,filename);
    assert.throws(()=>output.capture({missing:true}),error=>error.bodyLocal===true,kind);
    assert.throws(()=>output.capture(),error=>error.bodyLocal===true,kind);
    assert.equal(fs.readFileSync(foreign,'utf8'),'');
  }
});
test('a replacement cannot borrow a captured native output inode',t=>{
  const {root,filename,output}=capability(t);fs.writeFileSync(filename,'original');
  const captured=output.capture();assert.deepEqual(captured,{file:identity(filename),size:8});
  fs.renameSync(filename,path.join(root,'original'));fs.writeFileSync(filename,'replacement');
  assert.throws(()=>output.capture({missing:true}),error=>error.bodyLocal===true);
  assert.throws(()=>output.capture(),error=>error.bodyLocal===true);
  assert.equal(fs.readFileSync(filename,'utf8'),'replacement');
});
