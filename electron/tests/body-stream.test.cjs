'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('internal body service streams selected Electron Session to durable Workspace',{timeout:65000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-body-stream-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-stream.fixture.cjs'),profile],
    {timeout:60000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY STREAM PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
