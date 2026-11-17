'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const runFixture=require('./fixture-process.cjs');
test('real controlled Document probes and internal article entry',{timeout:45000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-document-fixture-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await runFixture(t,require('electron'),[path.join(__dirname,'document-probes.fixture.cjs'),profile],
    {timeout:40000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/DOCUMENT PROBES PASS/);
});
