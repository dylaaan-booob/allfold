'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('actual isolated Document Date/Abstract extraction and lifetime',{timeout:90000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-extraction-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await promisify(execFile)(require('electron'),[path.join(__dirname,'document-extraction.fixture.cjs'),profile],
    {timeout:85000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}}).catch(error=>{throw Error((error.stderr || error.message).slice(-6000));});
  assert.match(stdout,/DOCUMENT EXTRACTION PASS/);
});
