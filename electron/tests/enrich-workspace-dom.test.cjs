'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),{execFile}=require('node:child_process');

test('shipped Enrich retains its task and Reader through its independent native Browser handoff',{timeout:100000},async()=>{
  for(const scrollbar of ['WhenScrolling','Always']){
    const output=await new Promise((resolve,reject)=>execFile(require('electron'),[path.join(__dirname,'enrich-workspace-dom.fixture.cjs'),'-AppleShowScrollBars',scrollbar],
      {timeout:45000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:'',
        ...(process.env.ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS?{ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS:path.join(process.env.ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS,scrollbar)}:{})}},(error,stdout,stderr)=>{
        if(error)reject(Error(`${scrollbar}: ${error.message}\n${stdout}\n${stderr}`));else resolve(stdout+stderr);
      }));
    assert.match(output,/ENRICH WORKSPACE DOM PASS/);
  }
});
