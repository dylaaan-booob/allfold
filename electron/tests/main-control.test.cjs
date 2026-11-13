'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {AsyncLocalStorage}=require('node:async_hooks');
const {randomBytes}=require('node:crypto');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const source=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
const execute=source.slice(source.indexOf('const CONTROL_ACTIONS='),source.indexOf('async function startPython('));
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
function fixture(){
 const messages=[],logs=[],calls={end:0,save:0,translation:0};
 const taskContext=new AsyncLocalStorage();let pageId=0;
 const context=vm.createContext({operations:new Map(),exiting:false,bridgeReady:true,randomBytes,setTimeout,clearTimeout,
  ...require('../src/shared/logging.cjs'),...require('../src/shared/recovery-summary.cjs'),...require('../src/workflows/recovery-authority.cjs'),
  require:require('node:module').createRequire(require.resolve('../src/main.cjs')),
  operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
  log:(level,event,details)=>logs.push({level,event,...details}),AbortController,BrowserFailure,diagnosticFor,
  send:message=>{messages.push(JSON.parse(JSON.stringify(message)));context.onSend?.(message);},
  browser:{tabs:new Map(),documentCurrent:()=>true,publish(){},async invalidateAllAccess(){},stopAdmission(){},
   get operation(){return taskContext.getStore();},get taskTab(){return this.operation?.taskTab;},
   async runTask(signal,association,run){try{return await taskContext.run({signal,association,taskTab:{id:++pageId}},run);}finally{calls.end++;}},
   async navigate(){return {pageId:this.taskTab.id,url:'https://example.test/preparation'};}},
  prepareLoggedInService:async browser=>browser.navigate('https://example.test/preparation'),
 });
 vm.runInContext(execute,context);
 return {context,messages,logs,calls,run:(id='current')=>context.execute({id,action:'prepare_service',data:{workflow_id:'fixture'}})};
}
test('a stale cancel cannot abort another request or action', () => {
  const start = source.indexOf("else if(message.type === 'cancel') {") + "else if(message.type === 'cancel') {".length;
  const end = source.indexOf("else if(message.type === 'solve_cloudflare_result')", start);
  assert.ok(start>0 && end>start,'cancel branch boundaries must exist');
  const body = source.slice(start, end).replace(/}\s*$/, '');
  const controller=new AbortController(),other=new AbortController();
  const {context}=fixture();
  context.operations.set('current',{id:'current',action:'prepare_service',controller});
  context.operations.set('other',{id:'other',action:'prepare_service',controller:other});
  for (const message of [{id: 'old', action: 'prepare_service'}, {id: 'current', action: 'other'}]) {
    context.message = message;vm.runInContext(body, context);assert.equal(controller.signal.aborted, false);
  }
  context.message = {id: 'current', action: 'prepare_service'};vm.runInContext(body, context);
  assert.equal(controller.signal.aborted,true);assert.equal(other.signal.aborted,false);
});

test('native diagnostics reset bypasses browser task and document authority and refuses active work',async()=>{
  const f=fixture();let data;
  f.context.browser.runTask=()=>{throw Error('must not begin browser work');};
  f.context.diagnosticsReset=value=>{data=value;return {available:true,scope_id:value.scope_id,token:'preview'};};
  await f.context.execute({id:'reset_preview',action:'diagnostics_reset',data:{operation:'preview',scope_id:'a'.repeat(64)}});
  assert.equal(data.operation,'preview');assert.equal(f.calls.end,0);assert.equal(f.calls.save,0);assert.equal(f.logs.length,0);
  assert.equal(f.messages[0].data.token,'preview');
  f.context.operations.set('browser',{action:'prepare_service'});
  await assert.rejects(f.context.execute({id:'reset_busy',action:'diagnostics_reset',data:{operation:'preview'}}),/active/);
});

test('normal exit still settles captured resource cleanup without starting business work',{timeout:2000},async()=>{
  const f=fixture(),entered=deferred(),settled=deferred();
  f.context.exiting=true;
  f.context.browser.runTask=()=>{throw Error('exit must not create business work');};
  f.context.browser.invalidateAccess=async data=>{assert.equal(data.scope_id,'captured');entered.resolve();await settled.promise;return {closed:1};};
  const pending=f.context.execute({id:'cleanup',action:'invalidate_access',data:{scope_id:'captured'}});
  await entered.promise;
  assert.equal(f.messages.length,0);assert.equal(f.context.operations.size,1);
  await f.run('late-work');
  assert.equal(f.messages[0].data.diagnostic.code,'canceled');
  settled.resolve();await pending;
  assert.equal(f.messages[1].data.closed,1);assert.equal(f.context.operations.size,0);
  f.context.browser.releaseWorkflowPages=data=>({released:data.workflow_id==='old'});
  await f.context.execute({id:'release',action:'release_workflow_pages',data:{workflow_id:'old',task_id:'old'}});
  assert.equal(f.messages[2].data.released,true);
});

test('explicit credential writes settle through bridge ownership without browser dispatch or diagnostic payloads',{timeout:5000},async()=>{
  const f=fixture(),started=deferred(),settled=deferred();
  f.context.saveCASCredentials=async value=>{assert.equal(value.expected_revision,'missing');started.resolve();return settled.promise;};
  f.context.casErrorCode=error=>error.code;
  f.context.browser.runTask=()=>{throw Error('credentials must not enter Browser');};
  const pending=f.context.execute({id:'credentials',action:'cas_credentials',data:{operation:'save',expected_revision:'missing'}});
  await started.promise;
  assert.equal(f.context.operations.size,1);
  await assert.rejects(f.run(),/Concurrent/);
  settled.resolve({ok:true,revision:'new'});await pending;
  assert.equal(f.context.operations.size,0);assert.equal(f.calls.end,0);assert.equal(f.logs.length,0);
  assert.equal(f.messages[0].data.revision,'new');
});

test('quit confirmation occurs before aborting an active task and cancelling leaves the task running',async()=>{
  const f=fixture(),confirmation=deferred();let quitHandler,quitCalls=0;
  const controller=new AbortController();
  f.context.operations.set('active',{controller});
  Object.assign(f.context,{readyToExit:false,exitApproved:false,exitCheck:null,
    window:{isDestroyed:()=>false},dialog:{},confirmConfigurationExit:()=>confirmation.promise,
    app:{on(_event,handler){quitHandler=handler;},quit(){quitCalls++;}}});
  vm.runInContext(source.slice(source.indexOf("app.on('before-quit',event=>{"),source.indexOf("app.on('window-all-closed'")),f.context);
  let prevented=false;quitHandler({preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(controller.signal.aborted,false);
  confirmation.resolve(false);await Promise.resolve();
  assert.equal(controller.signal.aborted,false);assert.equal(quitCalls,0);
});

for(const sameDocument of [false,true])test(`same-URL challenges ignore stale replies after ${sameDocument?'same-document':'full'} navigation`,{timeout:5000},async()=>{
  const {EventEmitter}=require('node:events');
  const f=fixture(),sent=deferred(),results=new Map();
  class Socket extends EventEmitter {
    constructor(){super();Socket.instance=this;}
    addEventListener(...args){this.on(...args);}
    close(){throw Error('unexpected bridge close');}
  }
  let challengeCount=0;
  f.context.onSend=message=>{
    if(message.type==='solve_cloudflare' && ++challengeCount===2)sent.resolve();
  };
  Object.assign(f.context,{WebSocket:Socket,bridgeReady:false,base:'http://127.0.0.1:18767',token:'fixture'});
  vm.runInContext(source.slice(source.indexOf('async function connect('),source.indexOf('async function main(')),f.context);
  const connected=f.context.connect();
  const reply=message=>Socket.instance.emit('message',{data:JSON.stringify(message)});
  reply({type:'ready',log_level:'warn'});
  await connected;

  f.context.browser.ownsPage=(owner,pageId)=>owner.taskTab.id===pageId;
  f.context.browser.navigate=async function(url) {
    const pageId=this.taskTab.id;
    const contents=new EventEmitter();
    Object.assign(contents,{getURL:()=>url,isLoadingMainFrame:()=>false,getOrCreateDevToolsTargetId:()=>String(pageId).repeat(32)});
    this.tabs.set(pageId,{view:{webContents:contents}});
    const doc={pageId,url,frameToken:'document_'+pageId,processId:42};
    results.set(pageId,await f.context.solveCloudflare(doc,{signal:this.operation.signal}));
    return doc;
  };
  const first=f.run('first'),second=f.run('second');
  await sent.promise;
  const [a,b]=f.messages.filter(message=>message.type==='solve_cloudflare');
  assert.equal(a.data.url,b.data.url);
  assert.notEqual(a.data.target_id,b.data.target_id);
  const response=message=>({...message,type:'solve_cloudflare_result',data:{outcome:'clicked',reason:'checkbox_clicked'}});
  reply(response({...b,id:a.id}));
  await Promise.resolve();
  assert.equal(results.size,0);
  f.context.browser.tabs.get(1).view.webContents.emit('did-start-navigation',{isMainFrame:true,isSameDocument:sameDocument});
  reply(response(a));reply(response(b));
  await Promise.all([first,second]);
  assert.equal(results.get(1).reason,'canceled');
  assert.equal(results.get(2).outcome,'clicked');
  assert.ok(f.messages.some(message=>message.type==='cancel_cloudflare' && message.id===a.id));
  assert.ok(!f.messages.some(message=>message.type==='cancel_cloudflare' && message.id===b.id));
});

test('retired Paper Import Enrich and Local API actions cannot enter native Browser work',async()=>{
 const f=fixture();
 for(const action of ['import_paper','enrich_paper','zotero_local'])await f.context.execute({id:action,action,data:{}});
 assert.equal(f.calls.end,0);assert.equal(f.context.operations.size,0);
 assert.deepEqual(f.messages.map(item=>item.data.diagnostic.code),['unsupported_operation','unsupported_operation','unsupported_operation']);
});
test('shutdown revokes native operations and drains their real settlement before stopping Python',async()=>{
 const f=fixture(),started=deferred(),settled=deferred();let quitHandler,quitCalls=0;
 f.context.prepareLoggedInService=async()=>{started.resolve();return settled.promise;};
 const pending=f.run();await started.promise;
 Object.assign(f.context,{readyToExit:false,exitApproved:false,exitCheck:null,window:null,bridgeReady:false,python:null,
  app:{on(_name,handler){quitHandler=handler;},quit(){quitCalls++;}}});
 vm.runInContext(source.slice(source.indexOf("app.on('before-quit',event=>{"),source.indexOf("app.on('window-all-closed'")),f.context);
 quitHandler({preventDefault(){}});
 assert.equal(f.context.operations.get('current').controller.signal.aborted,true);assert.equal(quitCalls,0);
 await f.run('late');assert.equal(f.messages.find(item=>item.id==='late').data.diagnostic.code,'canceled');
 settled.resolve({outcome:'Opened'});await pending;await Promise.resolve();
 assert.equal(f.context.operations.size,0);assert.equal(quitCalls,1);
});

test('scoped access cleanup and old workflow release dispatch without creating a Browser task',async()=>{
  const f=fixture(),calls=[];
  f.context.browser.invalidateAccess=async data=>{calls.push(['invalidate',data.scope_id]);return {closed:1};};
  f.context.browser.releaseWorkflowPages=data=>{calls.push(['release',data.workflow_id,data.task_id]);return {released:false};};
  await f.context.execute({id:'invalidate',action:'invalidate_access',data:{scope_id:'a'.repeat(64),preparation_keys:{},authentication_key:'b'.repeat(64)}});
  await f.context.execute({id:'release',action:'release_workflow_pages',data:{workflow_id:'old',task_id:'old'}});
  assert.deepEqual(calls,[['invalidate','a'.repeat(64)],['release','old','old']]);assert.equal(f.calls.end,0);
  assert.equal(f.messages[0].data.closed,1);assert.equal(f.messages[1].data.released,false);
});


test('successful credential replacement waits retained access destruction before returning success',async()=>{
  const f=fixture(),cleaned=deferred();let started=false;
  f.context.saveCASCredentials=async()=>({ok:true,revision:'new'});
  f.context.browser.invalidateAllAccess=()=>{started=true;return cleaned.promise;};
  const result=f.context.execute({id:'credentials',action:'cas_credentials',data:{operation:'save'}});
  await new Promise(setImmediate);assert.equal(started,true);assert.equal(f.messages.length,0);assert.equal(f.context.operations.size,1);
  cleaned.resolve();await result;assert.equal(f.messages[0].data.ok,true);assert.equal(f.context.operations.size,0);
});
