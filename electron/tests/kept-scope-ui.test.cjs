'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
const idle={phase:'idle',active:false,can_cancel:false};
const queue={import_token:'all-token',services:[
  {id:'all',name:'All Services',kept:2,eligible:2},
  {id:'svc_a',name:'Service A',kept:1,eligible:1},
  {id:'svc_b',name:'Service B',kept:1,eligible:1},
  {id:'unassigned',name:'Unassigned',kept:0,eligible:0},
  {id:'ambiguous',name:'Ambiguous',kept:0,eligible:0}],papers:[]};
const active={workflow_id:'fixed-a',generation:7,service_id:'svc_a',service_name:'Service A',phase:'importing',
  active:true,can_cancel:true,message:'Importing Service A'};

test('Last Import shows only Item PDF Fallback indicators, deduplicates Papers and keeps query failures unknown',async()=>{
 const results=[{paper_id:'saved',service_id:'svc_a',outcome:'exported',parent_outcome:'confirmed',item_exists:true,pdf_attached:true,pdf_source:'openalex',fallback_used:true,reason:'Registered fallback PDF'},
 {paper_id:'unknown',service_id:'svc_b',outcome:'exported',parent_outcome:'confirmed',item_exists:true,pdf_attached:null,fallback_used:null,query_diagnostic:{code:'connection_lost'},reason:'Parent saved'}];
 const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?queue:{...idle,workflow_id:'last',import_started:true,batch:{total:2,results:[...results,results[0]]}}});
 assert.equal(f.get('kept-record-items').children.length,2);
 const text=f.get('kept-record-items').textContent;
 assert.match(text,/Item Yes.*PDF Yes.*Fallback Yes/s);assert.match(text,/PDF 无法核验.*Fallback 无法核验/s);
 assert.match(text,/查询：connection_lost/);
 assert.ok(!text.includes('PDF unverified'));
 await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_b').emit('click');
 assert.equal(f.get('kept-record-items').children.length,1);
 assert.match(f.get('kept-record-items').textContent,/Paper: unknown/);
 assert.doesNotMatch(f.get('kept-record-items').textContent,/Paper: saved/);
});

test('Kept captures its next saved Service before autosave and display changes cannot retarget it',async()=>{
  const starts=[];let current=idle;
  const f=await taskUI('kept.js',{page:'kept',request:async(url,body)=>{
    if(url.includes('/queue'))return {...queue,import_token:url.includes('svc_a')?'a-token':'all-token'};
    if(url.endsWith('/start')){starts.push(body);current=active;return active;}
    return current;
  }});
  let release;
  f.window.allfoldAutosave={flush:()=>new Promise(resolve=>{release=resolve;})};
  await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_a').emit('click');
  const started=f.get('kept-start').emit('click');await f.settle();
  assert.equal(starts.length,0);
  await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_b').emit('click');
  release(true);await started;
  assert.equal(starts.length,1);
  assert.equal(starts[0].service_id,'svc_a');assert.equal(starts[0].import_token,'a-token');
  assert.match(f.get('kept-scope-status').textContent,/Service A/);
  assert.match(f.get('kept-progress').textContent,/Service A/);
  assert.equal(f.get('kept-start').disabled,true);
});

test('Unassigned and Ambiguous are display groups with no single Service execution',async()=>{
  const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?queue:idle});
  for(const id of ['unassigned','ambiguous']){
    await f.get('kept-service-list').children.find(row=>row.dataset.serviceId===id).emit('click');
    assert.equal(f.get('kept-start').disabled,true);
    await f.get('kept-start').emit('click');
  }
  assert.equal(f.calls.some(call=>call[0].endsWith('/start')),false);
});

test('Import lists unprepared Services and starts only on explicit confirmation of the exact saved scope',async()=>{
  const missing=[{id:'svc_a',name:'Service A'}],starts=[];
  const f=await taskUI('kept.js',{page:'kept',request:async(url,body)=>{
    if(url.includes('/queue'))return {...queue,unprepared_services:missing};
    if(url.endsWith('/start')){starts.push(body);return active;}
    return idle;
  }});
  await f.get('kept-start').emit('click');
  assert.equal(f.get('kept-confirm').open,true);assert.equal(starts.length,0);
  assert.equal(f.get('kept-confirm-services').textContent,'Service A');
  await f.get('kept-confirm-login').emit('click');
  assert.equal(f.page(),'login');assert.equal(starts.length,0);
  f.setPage('kept');await f.get('kept-start').emit('click');await f.get('kept-continue').emit('click');
  assert.deepEqual(JSON.parse(JSON.stringify(starts)),[{service_id:null,import_token:'all-token',skip_unprepared:['svc_a']}]);
  assert.equal(f.calls.some(([url])=>url.endsWith('/continue')),false);
});

test('Import result details retain skipped Paper reasons and recorded Service attribution',async()=>{
  const results=[{paper_id:'paper-a',service_id:'svc_a',outcome:'skipped',parent_outcome:'not_saved',
    reason:'Unprepared Service skipped',diagnostic:{stage:'import',step:'plan',code:'service_not_prepared'}}];
  const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?
    {...queue,papers:[{paper_id:'paper-a',service_id:'svc_b'}]}:
    {...idle,phase:'completed',workflow_id:'fixed',batch:{total:1,results}}});
  const record=f.get('kept-record-items').textContent;
  assert.match(record,/Paper: paper-a/);
  assert.match(record,/Service: svc_a/);
  assert.match(record,/Unprepared Service skipped/);
  assert.match(record,/service_not_prepared/);
  assert.match(f.get('kept-progress').textContent,/已跳过 1/);
});

test('failed autosave prevents Kept task dispatch and preserves the selected scope',async()=>{
  const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?queue:idle});
  f.window.allfoldAutosave={flush:async()=>false};
  await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_a').emit('click');
  await f.get('kept-start').emit('click');
  assert.equal(f.calls.some(call=>call[0].endsWith('/start')),false);
  assert.match(f.get('kept-scope-status').textContent,/Service A/);
});
test('Browser task summary retains original batch counts when the display Service changes',async()=>{
  const state={...active,planned_total:3,batch:{total:3,results:[
    {paper_id:'first',outcome:'exported',parent_outcome:'confirmed',pdf_outcome:'unverified',reason:'Parent confirmed'},
    {paper_id:'second',outcome:'uncertain',parent_outcome:'uncertain',reason:'Inspect before retry'}]}};
  const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?queue:state});
  await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_b').emit('click');
  assert.match(f.get('kept-scope-status').textContent,/Service B/);
  assert.match(f.get('kept-progress').textContent,/Service A.*已处理 2 \/ 3.*已确认 1/);
});
