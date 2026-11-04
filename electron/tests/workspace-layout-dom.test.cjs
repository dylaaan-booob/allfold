'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');
test('rendered ARRAY / Journals keep business DOM through rails, flyouts, sidebar and constrained containers',{timeout:60000},async()=>{
  const result=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'workspace-layout-dom.fixture.cjs')],
    {timeout:55000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}},(error,stdout,stderr)=>{
      if(error)reject(new Error(`${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
    }));
  assert.match(result,/LAYOUT DOM PASS/);
});
