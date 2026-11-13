'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function fixture(){
  const requests=[];
  const node={addEventListener(){}};
  const context={window:{},document:{getElementById:()=>node},fetch:()=>new Promise(resolve=>requests.push(data=>resolve({ok:true,json:async()=>data}))),URL,Error};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/api.js'),'utf8'),context);
  context.uiNext=context.window.uiNext;
  return {api:context.uiNext,requests};
}
test('a late snapshot cannot replace a newer persisted Paper action',async()=>{
  const {api,requests}=fixture();
  const first=api.workspace();requests.shift()({workspace_id:'library-a',revision:3,csrf_token:'csrf'});await first;
  const old=api.workspace(),action=api.request('/api/ui-next/papers/paper/reject',{});
  requests[1]({workspace_id:'library-a',revision:4,paper:{id:'paper',status:'trash'}});await action;
  requests[0]({workspace_id:'library-a',revision:3,subjects:['old']});
  await assert.rejects(old,error=>error.stale===true);
  assert.equal(api.data.revision,3);
  assert.equal(api.isCurrentEnvelope(api.data),false);
});
test('response ordering rejects same-revision older replies and previous Workspace replies',async()=>{
  const {api,requests}=fixture();
  const first=api.workspace(),second=api.workspace();requests[1]({workspace_id:'library-a',revision:5});await second;
  requests[0]({workspace_id:'library-a',revision:5});await assert.rejects(first,error=>error.stale===true);
  const old=api.workspace();api.resetWorkspace();const next=api.workspace();
  requests[3]({workspace_id:'library-b',revision:0});await next;
  requests[2]({workspace_id:'library-a',revision:99});await assert.rejects(old,error=>error.stale===true);
  assert.equal(api.data.workspace_id,'library-b');
});
for(const [name,path,payload] of [
  ['Preprint status','/api/papers/paper/preprint-lookup/state',{revision:4,phase:'Cancelling'}],
  ['field read','/api/papers/paper/fields',{revision:'field-digest',snapshot_revision:4,abstract:'Saved'}],
])test(`a later ${name} response cannot supersede the persisted Reject projection`,async()=>{
  const {api,requests}=fixture();
  const initial=api.workspace();requests.shift()({workspace_id:'library-a',revision:3});await initial;
  const action=api.request('/api/ui-next/papers/paper/reject',{}),read=api.request(path);
  requests[1]({workspace_id:'library-a',...payload});await read;
  requests[0]({workspace_id:'library-a',revision:4,paper:{id:'paper',status:'trash'}});
  const rejected=await action;
  assert.equal(api.isCurrentEnvelope(rejected),true);
  assert.equal(rejected.paper.status,'trash');
});
test('status polling after Reject preserves its projection and cannot admit an older snapshot',async()=>{
  const {api,requests}=fixture();
  const initial=api.workspace();requests.shift()({workspace_id:'library-a',revision:3});await initial;
  const old=api.workspace(),action=api.request('/api/ui-next/papers/paper/reject',{}),poll=api.request('/api/papers/paper/preprint-lookup/state');
  requests[1]({workspace_id:'library-a',revision:4,paper:{id:'paper',status:'trash'}});const rejected=await action;
  requests[2]({workspace_id:'library-a',revision:4,phase:'Cancelling'});await poll;
  assert.equal(api.isCurrentEnvelope(rejected),true);
  requests[0]({workspace_id:'library-a',revision:3});await assert.rejects(old,error=>error.stale===true);
});
for(const revision of [4,5])test(`an applied revision ${revision} snapshot still supersedes an older Reject response`,async()=>{
  const {api,requests}=fixture();
  const initial=api.workspace();requests.shift()({workspace_id:'library-a',revision:3});await initial;
  const action=api.request('/api/ui-next/papers/paper/reject',{}),snapshot=api.workspace();
  requests[1]({workspace_id:'library-a',revision});await snapshot;
  requests[0]({workspace_id:'library-a',revision:4,paper:{id:'paper',status:'trash'}});
  await assert.rejects(action,error=>error.stale===true);
  assert.equal(api.data.revision,revision);
});
