'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
const idle={phase:'idle',active:false,can_continue:false,can_cancel:false};
const queue={import_token:'all-token',services:[
  {id:'all',name:'All Services',kept:2,eligible:2},
  {id:'svc_a',name:'Service A',kept:1,eligible:1},
  {id:'svc_b',name:'Service B',kept:1,eligible:1},
  {id:'unassigned',name:'Unassigned',kept:0,eligible:0},
  {id:'ambiguous',name:'Ambiguous',kept:0,eligible:0}],papers:[]};
const active={workflow_id:'fixed-a',generation:7,service_id:'svc_a',service_name:'Service A',phase:'waiting_for_user',
  active:true,can_continue:true,can_cancel:true,settings:{},message:'Review Service A',preparation:{manual_services:[],results:[]}};

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
  await f.get('kept-start').emit('click');
  assert.equal(starts.length,0);
  await f.get('kept-service-list').children.find(row=>row.dataset.serviceId==='svc_b').emit('click');
  release(true);await f.settle();
  assert.equal(starts.length,1);
  assert.equal(starts[0].service_id,'svc_a');assert.equal(starts[0].import_token,'a-token');
  assert.match(f.get('kept-scope-status').textContent,/当前批次：Service A.*下一批：Service B/);
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
  const summary=f.get('kept-scope-status').textContent;
  assert.match(summary,/当前批次：Service A/);
  assert.match(summary,/计划 3.*已处理 2.*父条目确认 1.*待处理 1/);
  assert.match(summary,/等待 Continue/);
});
test('polling preserves the keyboard reachable batch counter and its reading position',async()=>{
  const f=await taskUI('kept.js',{page:'kept',request:async url=>url.includes('/queue')?queue:{...active,planned_total:3}});
  const counter=f.get('kept-scope-status').children[1];counter.scrollLeft=42;
  await f.tick();
  assert.equal(f.get('kept-scope-status').children[1],counter);
  assert.equal(counter.scrollLeft,42);assert.equal(counter.tabIndex,0);
});
