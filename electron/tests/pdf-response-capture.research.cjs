'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('Fetch response stream preserves bytes and Reader HTML but hides the original HTTP terminal',{timeout:30000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-response-capture-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'pdf-response-capture.fixture.cjs'),profile],
    {timeout:27000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/RESPONSE CAPTURE MECHANISM PASS/);assert.doesNotMatch(stderr,/Check failed/);
  t.diagnostic(stdout.trim());
});
