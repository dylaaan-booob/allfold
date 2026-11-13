'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('Electron 45 preserves original responses through the shared Session download router',{timeout:65000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-session-downloads-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'session-downloads.fixture.cjs'),profile],
    {timeout:60000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/SESSION DOWNLOADS PASS/);
  assert.doesNotMatch(stderr,/Check failed/);
  t.diagnostic(stdout.trim());
});
