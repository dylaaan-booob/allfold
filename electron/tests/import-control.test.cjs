'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {AsyncLocalStorage}=require('node:async_hooks');
const {randomBytes}=require('node:crypto');
const {ImportFailure, failedImport} = require('../src/workflows/import-errors.cjs');
const {BrowserFailure,diagnosticFor} = require('../src/browser/browser-errors.cjs');
const {ImportResources}=require('../src/zotero/import-resources.cjs');
const source = fs.readFileSync(path.join(__dirname, '../src/main.cjs'), 'utf8');
const limits={translator:2,pdf:2,writer:2};
const execute = source.slice(source.indexOf('const CONTROL_ACTIONS='), source.indexOf('async function startPython('));
const deferred = () => {let resolve;const promise = new Promise(r => {resolve = r;});return {promise, resolve};};
function fixture() {
  const messages = [], logs=[], calls = {translation: 0, save: 0, end: 0};
  const taskContext=new AsyncLocalStorage();
  let pageId=0;
  const context = vm.createContext({operations:new Map(),exiting:false,randomBytes,setTimeout,clearTimeout,
    ...require('../src/shared/logging.cjs'),
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    log:(level,event,details)=>logs.push({level,event,...details}),
    AbortController, ImportResources, ImportFailure, BrowserFailure, diagnosticFor, failedImport, normalizeDOI: value => value,
    send(message) {messages.push(JSON.parse(JSON.stringify(message)));},
    browser: {tabs:new Map(),
      async openPaperPage(data,doi,options){
        const tab={id:++pageId};
        taskContext.getStore().taskTab=tab;
        this.associatePage(tab,{role:options.role,doi});
        return this.navigate('https://doi.org/'+encodeURIComponent(doi),options);
      },
      async navigate() {return {pageId:this.taskTab.id,url:'https://example.org/article'};},
      documentCurrent:()=>true,
      get operation(){return taskContext.getStore();},get taskTab(){return this.operation?.taskTab;},
      async runTask(signal,association,run){try{return await taskContext.run({signal,association},run);}finally{calls.end++;}},
      associatePage(tab,data){tab.association={...this.operation.association,...data};},
      enterBusiness(){},publish(){}},
    translator: {setLimit(){},async translate(doc) {calls.translation++;return {item:{},sourceDocument:doc,metadataSource:'web'}; }},
    async saveOnce() {calls.save++;return {parent: {outcome: 'confirmed'}};}});
  vm.runInContext(execute, context);
  const run = (id='current') => context.execute({id, action: 'import_paper', data: {doi: '10.5555/test',workflow_id:'fixture',limits}});
  return {context, messages, logs, calls, run};
}


test('cancel during translation prevents a subsequent save', async () => {
  const f = fixture(), ready = deferred(), translated = deferred();
  f.context.translator.translate = () => {ready.resolve();return translated.promise;};
  const pending = f.run();await ready.promise;
  f.context.operations.get('current').controller.abort();translated.resolve({});await pending;
  assert.equal(f.calls.save, 0);
  assert.equal(f.messages.find(m => m.type === 'result').data.diagnostic.stage, 'translation');
});

test('cancel or quit during an escaped native save still waits for its actual result', async () => {
  const f = fixture(), saving = deferred(), saved = deferred();
  f.context.saveOnce = () => {saving.resolve();return saved.promise;};
  const pending = f.run();await saving.promise;
  let quitHandler, quitCalls = 0;
  Object.assign(f.context, {readyToExit: false, bridgeReady: false, python: null,
    exitApproved:false,exitCheck:null,window:null,
    app: {on(_name, handler) {quitHandler = handler;}, quit() {quitCalls++;}}});
  const quitSource = source.slice(source.indexOf("app.on('before-quit',event=>{"), source.indexOf("app.on('window-all-closed'"));
  vm.runInContext(quitSource, f.context);
  quitHandler({preventDefault() {}});
  assert.equal(f.context.operations.get('current').controller.signal.aborted, true);
  assert.equal(quitCalls, 0);assert.equal(f.calls.end, 0);
  saved.resolve({parent: {outcome: 'confirmed'}});await pending;await Promise.resolve();
  assert.equal(f.messages.find(m => m.type === 'result').data.parent.outcome, 'confirmed');
  assert.equal(f.calls.end, 1);assert.equal(quitCalls, 1);
});

test('a stale cancel cannot abort another request or action', () => {
  const start = source.indexOf("else if(message.type === 'cancel') {") + "else if(message.type === 'cancel') {".length;
  const end = source.indexOf("else if(message.type === 'solve_cloudflare_result')", start);
  assert.ok(start>0 && end>start,'cancel branch boundaries must exist');
  const body = source.slice(start, end).replace(/}\s*$/, '');
  const controller=new AbortController(),other=new AbortController();
  const {context}=fixture();
  context.operations.set('current',{id:'current',action:'import_paper',controller});
  context.operations.set('other',{id:'other',action:'import_paper',controller:other});
  for (const message of [{id: 'old', action: 'import_paper'}, {id: 'current', action: 'other'}]) {
    context.message = message;vm.runInContext(body, context);assert.equal(controller.signal.aborted, false);
  }
  context.message = {id: 'current', action: 'import_paper'};vm.runInContext(body, context);
  assert.equal(controller.signal.aborted,true);assert.equal(other.signal.aborted,false);
});

test('Enrich runs the official read-only Translator and never dispatches ItemSaver', async () => {
  const f=fixture();let enrichment;
  f.context.translator.translate=async (_doc,_doi,options)=>{enrichment=options.forEnrichment;return {item:{DOI:'10.5555/test'},sourceDocument:_doc,metadataSource:'web'};};
  await f.context.execute({id:'enrich',action:'enrich_paper',data:{doi:'10.5555/test'}});
  assert.equal(enrichment,true);assert.equal(f.calls.save,0);assert.equal(f.calls.end,1);
  assert.equal(f.messages.find(m=>m.type==='result').data.item.DOI,'10.5555/test');
});

test('Enrich reports the Imperva denial fields without handing the page to Zotero', async () => {
  const f=fixture(),{checkPage}=require('../src/browser/browser-errors.cjs');
  f.context.browser.navigate=async()=>checkPage(200,'','<body><iframe src="/_Incapsula_Resource?edet=16&amp;private=fixture">'
    +'Request unsuccessful. Incapsula incident ID: 123-456</iframe></body>');
  await f.context.execute({id:'enrich',action:'enrich_paper',data:{doi:'10.5555/test'}});
  assert.equal(f.calls.translation,0);
  const diagnostic=f.messages.find(m=>m.type==='result').data.diagnostic;
  assert.deepEqual(diagnostic,{stage:'navigation',code:'site_restricted',status:200,imperva_edet:16,imperva_incident_id:'123-456'});
  const event=f.logs.find(e=>e.event==='task_finished');
  assert.equal(event.imperva_edet,16);
  assert.equal(event.imperva_incident_id,'123-456');
});

test('Enrich reports Imperva verification as a wait and translates after the page is ready', async () => {
  const f=fixture(), waiting=deferred(), verified=deferred();
  f.context.browser.navigate=async (_url,{onWaiting})=>{
    onWaiting({stage:'navigation',code:'verification_page',status:200,imperva_edet:12,imperva_incident_id:'123-456'});
    waiting.resolve();
    await verified.promise;
    return {pageId:1,url:'https://example.org/article'};
  };
  const task=f.context.execute({id:'enrich',action:'enrich_paper',data:{doi:'10.5555/test'}});
  await waiting.promise;
  assert.equal(f.calls.translation,0);
  assert.ok(f.messages.some(m=>m.type==='progress' && m.id==='enrich' && m.data.waiting_for_user));
  assert.equal(f.messages.some(m=>m.type==='result'),false);
  const event=f.logs.find(e=>e.event==='manual_wait' && e.waiting);
  assert.equal(event.imperva_edet,12);
  assert.equal(event.imperva_incident_id,'123-456');
  verified.resolve();
  await task;
  assert.equal(f.calls.translation,1);
  assert.ok(f.messages.some(m=>m.type==='result' && m.id==='enrich' && m.data.metadata_source==='web'));
});

test('Import binds an independent page and Paper/Service context for each request',async()=>{
  const f=fixture();
  const scope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
  const records=[];
  f.context.browser.navigate=async function(url){
    records.push({page:this.taskTab.id,url,association:JSON.parse(JSON.stringify(this.taskTab.association))});
    return {pageId:this.taskTab.id,url};
  };
  for(const [index,service] of ['svc_'+'1'.repeat(32),'svc_'+'2'.repeat(32),null].entries()) {
    await f.context.execute({id:'request'+index,action:'import_paper',data:{doi:'10.5555/'+index,
      workflow_id:'batch',task_id:'batch',limits,paper_id:'paper'+index,service_scope:scope,service_id:service}});
  }
  assert.deepEqual(records.map(value=>value.page),[1,2,3]);
  assert.deepEqual(records.map(value=>value.association.service_id),['svc_'+'1'.repeat(32),'svc_'+'2'.repeat(32),null]);
  assert.deepEqual(records.map(value=>value.association.paper_id),['paper0','paper1','paper2']);
  assert.deepEqual(records.map(value=>value.association.doi),['10.5555/0','10.5555/1','10.5555/2']);
});




test('DOM translation cycles share one ten-minute deadline and dispose the active observer',async t=>{
  t.mock.timers.enable({apis:['Date','setTimeout'],now:1000});
  const {TranslatorSandbox}=require('../src/zotero/translator.cjs');
  const sandbox=new TranslatorSandbox(),observations=[],deadlines=[];
  const doc={pageId:1,processId:2,frameToken:'current',type:'text/html',url:'https://fixture/',html:'<div></div>'};
  sandbox.run=async()=>({ok:true,candidateCount:0,candidates:[],observers:[{selector:null,options:{childList:true}}]});
  sandbox.browser={documentCurrent:()=>true,tabs:new Map(),translationDocuments:async()=>[doc],
    observeDOM:async(_doc,_configs,{signal,deadline})=>{
      deadlines.push(deadline);const change=deferred(),observation={changed:require('../src/browser/browser-task.cjs').waitFor(()=>change.promise,signal,deadline,'translation','dom_observer'),resolve:change.resolve,disposed:false,
        async dispose(){this.disposed=true;}};observations.push(observation);return observation;
    }};
  const pending=sandbox.translate(doc,'10.5555/test');
  const rejected=assert.rejects(pending,error=>error.diagnostic?.code==='timeout');
  await new Promise(setImmediate);assert.equal(observations.length,1);
  t.mock.timers.tick(300000);observations[0].resolve();await new Promise(setImmediate);
  assert.equal(observations.length,2);assert.equal(observations[0].disposed,true);
  t.mock.timers.tick(300000);await rejected;
  assert.deepEqual(deadlines,[601000,601000]);assert.equal(observations[1].disposed,true);
});
test('native diagnostics reset bypasses browser task and document authority and refuses active work',async()=>{
  const f=fixture();let data;
  f.context.browser.runTask=()=>{throw Error('must not begin browser work');};
  f.context.diagnosticsReset=value=>{data=value;return {available:true,scope_id:value.scope_id,token:'preview'};};
  await f.context.execute({id:'reset_preview',action:'diagnostics_reset',data:{operation:'preview',scope_id:'a'.repeat(64)}});
  assert.equal(data.operation,'preview');assert.equal(f.calls.end,0);assert.equal(f.calls.save,0);assert.equal(f.logs.length,0);
  assert.equal(f.messages[0].data.token,'preview');
  f.context.operations.set('browser',{action:'import_paper'});
  await assert.rejects(f.context.execute({id:'reset_busy',action:'diagnostics_reset',data:{operation:'preview'}}),/active/);
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
test('native final diagnostic keeps stable attachment code separate from its network error',async()=>{
  const f=fixture();f.context.saveOnce=async()=>({parent:{outcome:'confirmed'},pdf:{outcome:'unverified'},diagnostic:{stage:'attachment',code:'http_error',net_error:'ERR_CONNECTION_RESET',status:403}});
  await f.run();const final=f.logs.find(event=>event.event==='task_finished');
  assert.equal(final.stage,'attachment');assert.equal(final.code,'http_error');assert.equal(final.net_error,'ERR_CONNECTION_RESET');
  assert.equal(f.messages.find(m=>m.type==='result').data.parent.outcome,'confirmed');
});
test('Local API discovery and authorization settle outside browser authority without secret diagnostic payloads',async()=>{
 const f=fixture();let prompts=0;
 f.context.zoteroLocal={targets:async()=>({ok:true,server_id:'SERVERFIXTUR',authorized:false,libraries:[]}),authorize:async()=>{prompts++;return {ok:true,server_id:'SERVERFIXTUR',authorized:true};},validate:async()=>{}};
 for(const operation of ['targets','authorize','validate'])await f.context.execute({id:operation,action:'zotero_local',data:{operation,target:{}}});
 assert.equal(prompts,1);assert.equal(f.calls.translation,0);assert.equal(f.calls.save,0);assert.equal(f.calls.end,0);assert.equal(f.logs.length,0);
 assert.equal(f.messages.length,3);assert.equal(f.messages[2].data.ok,true);assert.ok(!JSON.stringify(f.messages).includes('api_key'));
});

test('quit cancels a waiting authorization without waiting for a human approval timeout',async()=>{
 const f=fixture(),ready=deferred();let quitHandler,signal;
 f.context.zoteroLocal={authorize:options=>{signal=options?.signal;ready.resolve();return new Promise((resolve,reject)=>signal?.addEventListener('abort',()=>reject(Object.assign(Error(),{code:'canceled'})),{once:true}));}};
 const pending=f.context.execute({id:'authorize',action:'zotero_local',data:{operation:'authorize'}});
 await ready.promise;
 Object.assign(f.context,{readyToExit:false,bridgeReady:false,python:null,exitApproved:false,exitCheck:null,window:null,
  app:{on(_name,handler){quitHandler=handler;},quit(){}}});
 vm.runInContext(source.slice(source.indexOf("app.on('before-quit',event=>{"),source.indexOf("app.on('window-all-closed'")),f.context);
 quitHandler({preventDefault(){}});
 assert.equal(signal?.aborted,true);await pending;
 assert.equal(f.context.operations.size,0);
 assert.equal(f.messages[0].data.error,'canceled');assert.equal(f.calls.save,0);
});

test('shutdown stops new dispatch and waits for every escaped save to settle',async()=>{
  const f=fixture(),started=deferred(),first=deferred(),second=deferred();
  f.context.saveOnce=({doc})=>{
    if(doc.pageId===2)started.resolve();
    return doc.pageId===1?first.promise:second.promise;
  };
  const a=f.run('first'),b=f.run('second');
  await started.promise;
  let quitHandler,quitCalls=0;
  Object.assign(f.context,{readyToExit:false,bridgeReady:false,python:null,exitApproved:false,exitCheck:null,window:null,
    app:{on(_event,handler){quitHandler=handler;},quit(){quitCalls++;}}});
  vm.runInContext(source.slice(source.indexOf("app.on('before-quit',event=>{"),source.indexOf("app.on('window-all-closed'")),f.context);
  quitHandler({preventDefault(){}});
  assert.equal([...f.context.operations.values()].every(op=>op.controller.signal.aborted),true);
  await f.run('late');
  assert.equal(f.messages.find(m=>m.type==='result' && m.id==='late').data.diagnostic.code,'canceled');
  second.resolve({parent:{outcome:'confirmed',accepted_id:'SECOND01'}});await b;
  assert.equal(quitCalls,0);assert.equal(f.calls.end,1);
  first.resolve({parent:{outcome:'uncertain',requested_id:'FIRST001'}});await a;await Promise.resolve();
  assert.equal(f.messages.find(m=>m.type==='result' && m.id==='first').data.parent.requested_id,'FIRST001');
  assert.equal(f.messages.find(m=>m.type==='result' && m.id==='second').data.parent.accepted_id,'SECOND01');
  assert.equal(quitCalls,1);assert.equal(f.calls.end,2);
});

test('same-URL challenges use their own CDP target and ignore stale replies after navigation',{timeout:5000},async()=>{
  const {EventEmitter}=require('node:events');
  const f=fixture(),sent=deferred(),results=new Map();
  class Socket extends EventEmitter {
    constructor(){super();Socket.instance=this;}
    addEventListener(...args){this.on(...args);}
    close(){throw Error('unexpected bridge close');}
  }
  let challengeCount=0;
  const send=f.context.send;
  f.context.send=message=>{
    send(message);
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
  f.context.browser.tabs.get(1).view.webContents.emit('did-start-navigation',{isMainFrame:true,isSameDocument:false});
  reply(response(a));reply(response(b));
  await Promise.all([first,second]);
  assert.equal(results.get(1).reason,'canceled');
  assert.equal(results.get(2).outcome,'clicked');
  assert.ok(f.messages.some(message=>message.type==='cancel_cloudflare' && message.id===a.id));
  assert.ok(!f.messages.some(message=>message.type==='cancel_cloudflare' && message.id===b.id));
});

test('a lost bridge during orderly quit still drains native saves before stopping Python',{timeout:5000},async()=>{
  const {EventEmitter}=require('node:events');
  const f=fixture(),saving=deferred(),settle=deferred(),terminated=deferred();
  class Socket extends EventEmitter {
    constructor(){super();Socket.instance=this;}
    addEventListener(...args){this.on(...args);}
    close(){this.emit('close');}
  }
  let quitHandler;
  Object.assign(f.context,{WebSocket:Socket,bridgeReady:false,base:'http://127.0.0.1:18767',token:'fixture',
    readyToExit:false,exitApproved:false,exitCheck:null,window:null,
    python:{exitCode:null,signalCode:null,kill(signal){terminated.resolve(signal);}},
    app:{on(_name,handler){quitHandler=handler;},quit(){}}});
  vm.runInContext(source.slice(source.indexOf('async function connect('),source.indexOf('async function main(')),f.context);
  vm.runInContext(source.slice(source.indexOf("app.on('before-quit',event=>{"),source.indexOf("app.on('window-all-closed'")),f.context);
  const connecting=f.context.connect();
  Socket.instance.emit('message',{data:JSON.stringify({type:'ready',log_level:'info'})});
  await connecting;
  f.context.saveOnce=()=>{saving.resolve();return settle.promise;};
  const active=f.run();await saving.promise;
  quitHandler({preventDefault(){}});
  assert.equal(f.messages.some(message=>message.type==='shutdown'),true);
  Socket.instance.close();
  let stopped=false;void terminated.promise.then(()=>{stopped=true;});
  await Promise.resolve();assert.equal(stopped,false);
  settle.resolve({parent:{outcome:'confirmed'}});await active;
  assert.equal(await terminated.promise,'SIGTERM');
});
