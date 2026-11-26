'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
const runFixture=require('./fixture-process.cjs');
async function runClues(t,mode) {
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-pdf-clues-'+mode+'-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const aggregate=path.join(profile,'aggregate.json');
  const {stdout}=await runFixture(t,require('electron'),[path.join(__dirname,'pdf-clues.fixture.cjs'),profile,aggregate,mode],
    {timeout:55000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}}).catch(error=>{
      throw Error([error.message,error.stderr].filter(Boolean).join('\n').slice(-7000));
    });
  assert.match(stdout,new RegExp(mode+' PDF CLUES PASS'));
  return aggregate;
}
test('actual composite and PDF-only Document clues preserve snapshot facts and cleanup',{timeout:60000},async t=>{
  const aggregate=await runClues(t,'document'),root=path.resolve(__dirname,'../..');
  // The real native DTO must fit the later persistable-fact projection too;
  // nullable/default fields must not turn a bounded PDF partial into total loss.
  await promisify(execFile)('uv',['run','--locked','python','-c',
    'import json,sys; from allfold.application.document_metadata import validate_document_metadata; r=validate_document_metadata(json.load(open(sys.argv[1]))); assert r.delta.abstract == "A complete result." and r.partial and r.delta.discovery_facts[0].status == "partial"',aggregate],
    {cwd:root,timeout:10000,env:{...process.env,PYTHONPATH:path.join(root,'src')}});
});
test('actual EBSCO Documents keep the selected record and Viewer access',{timeout:60000},async t=>{
  await runClues(t,'ebsco');
});
