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
