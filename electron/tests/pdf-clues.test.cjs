'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('actual composite and PDF-only Document clues preserve binding and cleanup',{timeout:60000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-pdf-clues-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout}=await promisify(execFile)(require('electron'),[path.join(__dirname,'pdf-clues.fixture.cjs'),profile],
    {timeout:55000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}}).catch(error=>{throw Error((error.stderr || error.message).slice(-7000));});
  assert.match(stdout,/PDF CLUES PASS/);
});
