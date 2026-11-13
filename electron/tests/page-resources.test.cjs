'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('real physical pages share admission and retained popup/download lifetimes',{timeout:45000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-page-resources-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await promisify(execFile)(require('electron'),[path.join(__dirname,'page-resources.fixture.cjs'),profile],
    {timeout:40000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/PAGE RESOURCES PASS/);
});
