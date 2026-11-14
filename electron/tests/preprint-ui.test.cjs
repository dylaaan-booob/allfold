'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
test('Preprint keeps cleanup ownership after a terminal response and refreshes when the worker truly ends',async()=>{
 let reads=0;
 const f=await taskUI('preprint-lookup.js',{request:async url=>url.endsWith('/state?workspace_id=library-fixture')?{phase:'Idle',workspace_id:'library-fixture'}:url.endsWith('/start')?
  {request_id:'lookup',phase:'Running',workspace_id:'library-fixture',revision:2}:
  {request_id:'lookup',phase:'Cancelled',workspace_id:'library-fixture',revision:3,cleaning_up:++reads===1,saved_fields:[]}});
 f.window.allfoldRefreshWorkspace=f.window.uiWorkspace.refresh;
 f.window.allfoldPreprintLookup.select({id:'paper-1',metadata_present:true,excluded:false,preprint_lookup_available:true});
 await f.get('preprint-lookup-start').emit('click');
 assert.equal(f.get('preprint-lookup-start').disabled,true);assert.equal(f.stats().refreshes,0);
 await f.tick();assert.equal(f.get('preprint-lookup-start').disabled,false);assert.equal(f.stats().refreshes,1);
});
test('manual queries are per Workspace/Paper and navigation leaves each exact request alive',async()=>{
 const f=await taskUI('preprint-lookup.js',{request:async(url,body)=>url.includes('/state?')?
  {phase:'Running',workspace_id:'library-fixture',request_id:url.includes('paper-1')?'one':'two'}:
  {phase:'Running',workspace_id:body.workspace_id,request_id:url.includes('paper-1')?'one':'two'}});
 f.window.allfoldRefreshWorkspace=f.window.uiWorkspace.refresh;
 const paper=id=>({id,metadata_present:true,excluded:false,preprint_lookup_available:true});
 f.window.allfoldPreprintLookup.select(paper('paper-1'));await f.settle();
 f.window.allfoldPreprintLookup.select(paper('paper-2'));await f.settle();
 assert.equal(f.calls.some(([url])=>url.includes('/cancel')),false);
 await f.tick();
 assert.equal(f.calls.some(([url])=>url.includes('paper-1/preprint-lookup/state?workspace_id=library-fixture&request_id=one')),true);
 assert.equal(f.calls.some(([url])=>url.includes('paper-2/preprint-lookup/state?workspace_id=library-fixture&request_id=two')),true);
});
test('identity-only and excluded Papers have no Preprint action',async()=>{
 const f=await taskUI('preprint-lookup.js',{request:async()=>({phase:'Idle'})});
 for(const paper of [{id:'identity',metadata_present:false},{id:'trash',metadata_present:true,excluded:true}]){
  f.window.allfoldPreprintLookup.select(paper);assert.equal(f.get('paper-preprint-lookup').hidden,true);
 }
 assert.equal(f.calls.length,0);
});
test('a pending old Workspace query cannot revive after reset or disable the new Paper',async()=>{
 let deliver;
 const f=await taskUI('preprint-lookup.js',{request:async(url,body)=>url.includes('/state?')?{phase:'Idle',workspace_id:body?.workspace_id}:
  new Promise(resolve=>{deliver=resolve;})});
 const paper={id:'paper-1',metadata_present:true,excluded:false,preprint_lookup_available:true};
 f.window.allfoldPreprintLookup.select(paper);const starting=f.get('preprint-lookup-start').emit('click');await f.settle();
 f.window.uiNext.workspaceEpoch++;f.window.uiNext.libraryIdentity='new-library';
 f.window.dispatchEvent({type:'workspace-reset'});f.window.allfoldPreprintLookup.select(paper);
 deliver({phase:'Running',request_id:'old',workspace_id:'library-fixture',message:'OLD WORKSPACE'});await starting;await f.settle();
 assert.equal(f.get('preprint-lookup-start').disabled,false);
 assert.notEqual(f.get('preprint-lookup-status').textContent,'OLD WORKSPACE');
 await f.tick();assert.equal(f.calls.some(([url])=>url.includes('request_id=old')),false);
});
test('an unknown exact request after server recovery releases only its old UI state',async()=>{
 const f=await taskUI('preprint-lookup.js',{request:async(url,body)=>url.endsWith('/start')?
  {phase:'Running',workspace_id:body.workspace_id,request_id:'old-request'}:
  {phase:'Idle',workspace_id:'library-fixture',request_id:null}});
 f.window.allfoldRefreshWorkspace=f.window.uiWorkspace.refresh;
 f.window.allfoldPreprintLookup.select({id:'paper-1',metadata_present:true,excluded:false,preprint_lookup_available:true});
 await f.get('preprint-lookup-start').emit('click');
 assert.equal(f.get('preprint-lookup-start').disabled,false);
 assert.equal(f.get('preprint-lookup-cancel').hidden,true);
 assert.equal(f.stats().refreshes,1);
});
