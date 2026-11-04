'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');
test('shipped Kept and Run mount the production native task Browser at constrained sizes',{timeout:180000},async()=>{
  for(const scrollbar of ['WhenScrolling','Always']){
    // Cocoa's argument-domain preference changes only this fixture process.
    const output=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'browser-workspaces-dom.fixture.cjs'),'-AppleShowScrollBars',scrollbar],
      {timeout:85000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:'',
        ...(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS?{ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS:path.join(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS,scrollbar)}:{})}},(error,stdout,stderr)=>{
        if(error)reject(Error(`${scrollbar}: ${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
      }));
    assert.match(output,/BROWSER WORKSPACES DOM PASS/);
  }
});
