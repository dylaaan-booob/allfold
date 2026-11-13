'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('actual composite and PDF-only Document clues preserve binding and cleanup',{timeout:60000},async t=>{
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-pdf-clues-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const aggregate=path.join(profile,'aggregate.json'),root=path.resolve(__dirname,'../..');
  const {stdout}=await promisify(execFile)(require('electron'),[path.join(__dirname,'pdf-clues.fixture.cjs'),profile,aggregate],
    {timeout:55000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}}).catch(error=>{throw Error((error.stderr || error.message).slice(-7000));});
  assert.match(stdout,/PDF CLUES PASS/);
  // The real native DTO must fit the later persistable-fact projection too;
  // nullable/default fields must not turn a bounded PDF partial into total loss.
  await promisify(execFile)('uv',['run','--locked','python','-c',
    'import json,sys; from allfold.application.document_metadata import validate_document_metadata; r=validate_document_metadata(json.load(open(sys.argv[1]))); assert r.delta.abstract == "A complete result." and r.partial and r.delta.discovery_facts[0].status == "partial"',aggregate],
    {cwd:root,timeout:10000,env:{...process.env,PYTHONPATH:path.join(root,'src')}});
});
