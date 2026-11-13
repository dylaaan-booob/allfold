'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),path=require('node:path'),fs=require('node:fs'),os=require('node:os'),{execFile}=require('node:child_process'),{promisify}=require('node:util');
const execute=promisify(execFile);
test('rendered ARRAY / Journals and extracted/provider abstracts retain text, selection and reading position',{timeout:90000},async t=>{
  const temp=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-reader-chain-')));
  t.after(()=>fs.rmSync(temp,{recursive:true,force:true}));
  const native=path.join(temp,'native.json'),workspace=path.join(temp,'workspace.json');
  const env={...process.env,ELECTRON_RUN_AS_NODE:''};
  const run=async(executable,args,options={})=>execute(executable,args,{timeout:55000,maxBuffer:1024*1024,env,...options})
    .catch(error=>{throw Error(`${error.message}\n${error.stdout || ''}\n${error.stderr || ''}`);});
  await run(require('electron'),[path.join(__dirname,'document-extraction.fixture.cjs'),path.join(temp,'profile'),native,'--sample-only']);
  const python=process.env.ALLFOLD_SOLVER_TEST_PYTHON || path.resolve(__dirname,'../../.venv/bin/python');
  const pipeline=await run(python,[path.join(__dirname,'../../tests/document_metadata_pipeline.py'),native,workspace],
    {env:{...env,PYTHONPATH:path.resolve(__dirname,'../../src')}});
  assert.match(pipeline.stdout,/METADATA PIPELINE PASS/);
  const {stdout:result}=await run(require('electron'),[path.join(__dirname,'workspace-layout-dom.fixture.cjs'),workspace]);
  assert.match(result,/LAYOUT DOM PASS/);
});
