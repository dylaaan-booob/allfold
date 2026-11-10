'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');
test('real task Browser keeps its Page through Focus, overlays, resize, zoom and mouse / keyboard input',{timeout:90000},async()=>{
  const output=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'browser-presentation-dom.fixture.cjs')],
    {timeout:85000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}},(error,stdout,stderr)=>{
      if(error)reject(Error(`${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
    }));
  assert.match(output,/BROWSER PRESENTATION DOM PASS/);
});
