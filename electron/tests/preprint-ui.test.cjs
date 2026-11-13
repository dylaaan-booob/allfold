'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
test('Preprint keeps cleanup ownership after a terminal response and refreshes when the worker truly ends',async()=>{
 let reads=0;
 const f=await taskUI('preprint-lookup.js',{request:async url=>url.endsWith('/state')?{phase:'Idle'}:url.endsWith('/start')?
  {request_id:'lookup',phase:'Running',workspace_id:'library-fixture',revision:2}:
  {request_id:'lookup',phase:'Cancelled',workspace_id:'library-fixture',revision:3,cleaning_up:++reads===1,saved_fields:[]}});
 f.window.allfoldRefreshWorkspace=f.window.uiWorkspace.refresh;
 f.window.allfoldPreprintLookup.select({id:'paper-1',metadata_present:true,excluded:false,preprint_lookup_available:true});
 await f.get('preprint-lookup-start').emit('click');
 assert.equal(f.get('preprint-lookup-start').disabled,true);assert.equal(f.stats().refreshes,0);
 await f.tick();assert.equal(f.get('preprint-lookup-start').disabled,false);assert.equal(f.stats().refreshes,1);
});
test('identity-only and excluded Papers have no Preprint action',async()=>{
 const f=await taskUI('preprint-lookup.js',{request:async()=>({phase:'Idle'})});
 for(const paper of [{id:'identity',metadata_present:false},{id:'trash',metadata_present:true,excluded:true}]){
  f.window.allfoldPreprintLookup.select(paper);assert.equal(f.get('paper-preprint-lookup').hidden,true);
 }
 assert.equal(f.calls.length,0);
});
