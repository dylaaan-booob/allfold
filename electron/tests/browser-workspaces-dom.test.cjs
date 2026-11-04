'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');
test('shipped Kept and Run mount the production native task Browser at constrained sizes',{timeout:90000},async()=>{
  const output=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'browser-workspaces-dom.fixture.cjs')],
    {timeout:85000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}},(error,stdout,stderr)=>{
      if(error)reject(Error(`${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
    }));
  assert.match(output,/BROWSER WORKSPACES DOM PASS/);
});
