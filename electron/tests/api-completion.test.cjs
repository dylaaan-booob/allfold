'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(state){
  const listeners=new Map(),nodes=new Map(),timers=[];
  let refreshes=0;
  const document={getElementById(id){
    if(!nodes.has(id))nodes.set(id,{textContent:'',hidden:false,disabled:false,children:[],
      addEventListener(){},replaceChildren(...children){this.children=children;},querySelector(){return null;},querySelectorAll(){return [];}});
    return nodes.get(id);
  }};
  const requests=[];
  const window={addEventListener:(event,callback)=>listeners.set(event,callback),
    allfoldCompletionPapers:()=>({papers:[]}),allfoldRefreshWorkspace:async()=>{refreshes++;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/api-completion.js'),'utf8'),{
    window,document,uiNext:{request:async url=>{requests.push(url);return state.value;}},
    setTimeout:callback=>{timers.push(callback);return timers.length;},clearTimeout(){},
  });
  return {window,requests,timers,restore:()=>listeners.get('workspace-data-changed')(),get refreshes(){return refreshes;}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

test('restoring an already terminal API task does not refresh the startup Workspace or disrupt another workflow',async()=>{
  const f=fixture({value:{phase:'Completed',request_id:'old-task',total:0,processed:0,results:[]}});
  f.restore();await settle();
  assert.equal(f.refreshes,0);
  assert.deepEqual(f.requests,['/api/papers/api-completion/state']);
});

test('an API task observed running refreshes once when it settles without starting another operation',async()=>{
  const state={value:{phase:'Running',request_id:'active-task',total:0,processed:0,results:[]}},f=fixture(state);
  f.restore();await settle();assert.equal(f.refreshes,0);assert.equal(f.window.allfoldApiCompletion.active(),true);
  state.value={...state.value,phase:'Completed'};
  f.timers.shift()();await settle();
  assert.equal(f.refreshes,1);
  assert.equal(f.window.allfoldApiCompletion.active(),false);
  assert.deepEqual(f.requests,['/api/papers/api-completion/state','/api/papers/api-completion/state']);
});
