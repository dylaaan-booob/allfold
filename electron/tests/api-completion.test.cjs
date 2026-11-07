'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function fixture(state){
  const listeners=new Map(),nodes=new Map(),timers=[];
  let refreshes=0;
  const element=()=>({textContent:'',hidden:false,disabled:false,children:[],
    addEventListener(){},append(...children){this.children.push(...children);},replaceChildren(...children){this.children=children;},querySelector(){return null;},querySelectorAll(){return [];}});
  const document={createElement:element,createTextNode:text=>({textContent:text}),getElementById(id){
    if(!nodes.has(id))nodes.set(id,element());
    return nodes.get(id);
  }};
  const requests=[];
  const window={addEventListener:(event,callback)=>listeners.set(event,callback),
    allfoldCompletionPapers:()=>({papers:[]}),allfoldRefreshWorkspace:async()=>{refreshes++;}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/api-completion.js'),'utf8'),{
    window,document,uiNext:{request:async url=>{requests.push(url);return state.value;}},
    setTimeout:callback=>{timers.push(callback);return timers.length;},clearTimeout(){},
  });
  return {window,requests,timers,nodes,restore:()=>listeners.get('workspace-data-changed')(),get refreshes(){return refreshes;}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));

for(const [first_public_status,label] of Object.entries({recorded:'首版日期已记录',no_association:'尚无预印本关联',known_unresolved:'已知预印本首版尚未确定',conflict:'首版日期证据冲突',failed:'首版日期查询失败',cancelled:'首版日期查询已取消'}))test('Partial explains source problems and '+first_public_status+' first-public date',async()=>{
  const state={value:{phase:'Partial',total:1,processed:1,results:[{paper_id:'paper-1',status:'updated',first_public_status,
    lookups:[{provider:'crossref',status:'failed'}],issues:[{provider:'crossref',message:'Request failed'}]}]}},f=fixture(state);
  f.restore();await settle();
  assert.match(f.nodes.get('api-completion-status').textContent,/部分来源查询异常/);
  const heading=f.nodes.get('api-completion-results').children[0].children[0].children[0].textContent;
  assert.match(heading,new RegExp(label));
});

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
