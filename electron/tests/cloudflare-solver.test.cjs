'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('the native Solver clicks only the selected same-URL tab and its owned challenge frame',{timeout:12000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-cdp-fixture-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await promisify(execFile)(require('electron'),[path.join(__dirname,'cloudflare-solver.fixture.cjs'),profile],
    {timeout:10000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/CLOUDFLARE TARGET ISOLATION PASS/);
});
