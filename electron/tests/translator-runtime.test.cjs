'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');
test('official Translators support Web, DOI fallback and document-bound Enrich in the native Runtime',{timeout:80000},async()=>{
  const output=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'translator-runtime.fixture.cjs')],
    {timeout:75000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}},(error,stdout,stderr)=>{
      if(error)reject(Error(`${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
    }));
  assert.match(output,/OFFICIAL TRANSLATOR RUNTIME PASS/);
});
