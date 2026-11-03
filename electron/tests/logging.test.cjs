'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {createLogger,attachmentCounts}=require('../src/shared/logging.cjs');
function fixture(t,options={}) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-logs-test-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const output=[];
  return {root,output,logger:createLogger({root,runtimeId:'runtime_test',scopeId:'a'.repeat(64),stderr:line=>output.push(JSON.parse(line)),...options})};
}
test('persistent events strictly validate safe fields and retain important states at every detail level',t=>{
  const {logger,output}=fixture(t,{level:'error'});
  logger.log('info','task_finished',{request_id:'request_1',action:'import_paper',workflow_id:'workflow_1',stage:'attachment',code:'http_error',status:403,parent:'uncertain',pdf:'unverified',
    host:'secret.example',reason:'password=SECRET',translator:'SECRET',translator_id:'SECRET',first_doi:'10.5555/SECRET',body:'SECRET',headers:{Authorization:'SECRET'},net_error:'ERR_FAILED SECRET'});
  const events=logger.readEvents();assert.equal(events.length,1);assert.equal(output.length,1);
  assert.equal(events[0].schema_version,1);assert.equal(events[0].source,'electron');assert.equal(events[0].scope_id,'a'.repeat(64));
  assert.equal(events[0].parent,'uncertain');assert.equal(events[0].stage,'attachment');assert.equal(events[0].workflow_id,'workflow_1');
  assert.doesNotMatch(JSON.stringify(events),/SECRET|secret.example|Authorization|first_doi|translator/);
  assert.equal(attachmentCounts([{attachments:[{mimeType:'application/pdf'},{mimeType:'text/html'}]}]).pdf_attachment_count,1);
});
test('async request contexts stay distinct and strict event schemas drop unsupported events',async t=>{
  const {logger}=fixture(t);const {withLogContext}=require('../src/shared/logging.cjs');
  await Promise.all(['alpha','beta'].map(id=>withLogContext({request_id:id,workflow_id:'workflow_'+id,action:'import_paper'},async()=>{
    await new Promise(resolve=>setTimeout(resolve,id==='alpha'?5:0));logger.log('info','task_finished',{outcome:'uncertain'});
  })));
  logger.log('error','SECRET',{code:'failed'});
  assert.deepEqual(logger.readEvents().map(e=>[e.request_id,e.workflow_id]),[['beta','workflow_beta'],['alpha','workflow_alpha']]);
});
test('bounded rotation persists incompleteness across restart and files are private',t=>{
  const {logger,root}=fixture(t,{maxBytes:512,maxFiles:2});
  for(let i=0;i<12;i++)logger.log('info','manual_wait',{request_id:'request_'+i,waiting:!!(i%2)});
  const directory=path.join(root,'scopes','a'.repeat(64),'electron');
  const events=fs.readdirSync(directory).filter(name=>name.endsWith('.jsonl'));
  assert.equal(events.length,2);for(const name of events){const stat=fs.statSync(path.join(directory,name));assert.ok(stat.size<=512);assert.equal(stat.mode&0o777,0o600);}
  assert.equal(fs.statSync(directory).mode&0o777,0o700);assert.ok(logger.status().rotations>0);assert.equal(logger.status().incomplete,true);
  const reopened=createLogger({root,runtimeId:'restart',scopeId:'a'.repeat(64),stderr(){},maxBytes:512,maxFiles:2});
  assert.ok(reopened.status().rotations>0);assert.equal(reopened.readEvents().at(-1).request_id,'request_11');
});
test('reset is one use and writer records new events after deleting its verified files',t=>{
  const {logger}=fixture(t);const scope_id='a'.repeat(64);
  logger.log('info','manual_wait',{waiting:true});
  const expected=logger.reset({operation:'preview',scope_id});assert.equal(expected.available,true);
  const result=logger.reset({operation:'reset',scope_id,expected});assert.equal(result.success,true);
  assert.equal(logger.reset({operation:'reset',scope_id,expected}).success,false);
  logger.log('info','manual_wait',{waiting:false});assert.equal(logger.readEvents().length,1);assert.equal(logger.readEvents()[0].waiting,false);
});
test('reset refuses changed files and symlink/replaced directories never receive subsequent writes',t=>{
  const {logger,root,output}=fixture(t),scope_id='a'.repeat(64),directory=path.join(root,'scopes',scope_id,'electron');
  logger.log('info','manual_wait',{waiting:true});const expected=logger.reset({operation:'preview',scope_id});
  logger.log('info','manual_wait',{waiting:false});assert.equal(logger.reset({operation:'reset',scope_id,expected}).success,false);
  const moved=path.join(root,'detached');fs.renameSync(directory,moved);fs.mkdirSync(directory,{mode:0o700});
  const old=fs.readFileSync(path.join(moved,'events.0.jsonl'),'utf8');logger.log('error','bridge_disconnected');
  assert.equal(fs.readFileSync(path.join(moved,'events.0.jsonl'),'utf8'),old);assert.deepEqual(fs.readdirSync(directory),[]);
  assert.equal(logger.status().available,false);assert.equal(logger.status().incomplete,true);assert.equal(output.at(-1).event,'diagnostic_write_failed');
  fs.rmSync(directory,{recursive:true});fs.symlinkSync(moved,directory);
  const rejected=createLogger({root,runtimeId:'restart',scopeId:scope_id,stderr(){}});assert.equal(rejected.status().available,false);
});
test('disk exhaustion falls back to stderr, reports incompleteness and never throws into a caller',t=>{
  const {logger,output}=fixture(t);
  t.mock.method(fs,'writeFileSync',()=>{throw Object.assign(Error('secret path'),{code:'ENOSPC'});});
  assert.doesNotThrow(()=>logger.log('error','bridge_disconnected'));
  assert.equal(logger.status().write_failures,1);assert.equal(logger.status().incomplete,true);
  assert.equal(output[0].event,'bridge_disconnected');assert.equal(output[1].event,'diagnostic_write_failed');
  assert.doesNotMatch(JSON.stringify(output),/secret path|ENOSPC/);
});
test('partial reset reports retained files and a restart does not claim complete retention',t=>{
  const {logger,root}=fixture(t),scope_id='a'.repeat(64);logger.log('info','manual_wait',{waiting:true});
  const expected=logger.reset({operation:'preview',scope_id}),unlink=fs.unlinkSync;
  const mocked=t.mock.method(fs,'unlinkSync',function(file){if(file.endsWith('events.0.jsonl'))throw Object.assign(Error('blocked'),{code:'EACCES'});return unlink.call(fs,file);});
  const result=logger.reset({operation:'reset',scope_id,expected});mocked.mock.restore();
  assert.equal(result.success,false);assert.equal(result.partial,true);assert.equal(result.deleted,1);assert.equal(result.failed,1);
  const reopened=createLogger({root,runtimeId:'restart',scopeId:scope_id,stderr(){}});
  assert.equal(reopened.status().incomplete,true);assert.equal(reopened.readEvents().length,1);
});
test('saved Python level vocabulary controls optional details without dropping native final results',t=>{
  const {logger}=fixture(t);logger.setLevel('WARNING');
  logger.log('info','task_progress',{request_id:'one',stage:'navigation'});
  logger.log('info','task_finished',{request_id:'one',action:'import_paper',outcome:'uncertain'});
  assert.equal(logger.readEvents().length,1);assert.equal(logger.readEvents()[0].event,'task_finished');assert.equal(logger.status().incomplete,false);
});
