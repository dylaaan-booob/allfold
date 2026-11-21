'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const runFixture=require('./fixture-process.cjs');
test('tab-owned Solver handles independent, retained and popup pages with exact target isolation',{timeout:60000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-cdp-fixture-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await runFixture(t,require('electron'),[path.join(__dirname,'cloudflare-solver.fixture.cjs'),profile],
    {timeout:55000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/CLOUDFLARE TARGET ISOLATION PASS/);
});
