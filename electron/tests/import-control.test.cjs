'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {ImportFailure, failedImport} = require('../src/workflows/import-errors.cjs');
const {BrowserFailure,diagnosticFor} = require('../src/browser/browser-errors.cjs');
const source = fs.readFileSync(path.join(__dirname, '../src/main.cjs'), 'utf8');
const execute = source.slice(source.indexOf('async function execute('), source.indexOf('async function startPython('));
const deferred = () => {let resolve;const promise = new Promise(r => {resolve = r;});return {promise, resolve};};
function fixture() {
  const messages = [], logs=[], calls = {translation: 0, save: 0, end: 0};
  const context = vm.createContext({activeRequest: null, activeOperation: null, exiting: false,
    ...require('../src/shared/logging.cjs'),
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    log:(level,event,details)=>logs.push({level,event,...details}),
    AbortController, ImportFailure, BrowserFailure, diagnosticFor, failedImport, normalizeDOI: value => value,
    newTaskPage:async()=>({id:1}),
    send(message) {messages.push(JSON.parse(JSON.stringify(message)));},
    browser: {tabs:new Map([[1,{}]]),async navigate() {return {pageId:1,url: 'https://example.org/article'};}, documentCurrent: () => true,
      beginOperation(_signal,data) {this.operation={association:data};},
      associatePage(tab,data){tab.association={...this.operation.association,...data};},
      bindTaskPage(tab){this.taskTab=tab;},
      enterBusiness() {},publish() {},endTask() {calls.end++;}},
    translator: {async translate(doc) {calls.translation++;return {item:{},sourceDocument:doc,metadataSource:'web'}; }},
    async saveOnce() {calls.save++;return {parent: {outcome: 'confirmed'}};}});
  vm.runInContext(execute, context);
  const run = () => context.execute({id: 'current', action: 'import_paper', data: {doi: '10.5555/test'}});
  return {context, messages, logs, calls, run};
}


test('cancel during translation prevents a subsequent save', async () => {
  const f = fixture(), ready = deferred(), translated = deferred();
  f.context.translator.translate = () => {ready.resolve();return translated.promise;};
  const pending = f.run();await ready.promise;
  f.context.activeOperation.controller.abort();translated.resolve({});await pending;
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
  assert.equal(f.context.activeOperation.controller.signal.aborted, true);
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
  const controller = new AbortController(), context = vm.createContext({activeOperation: {id: 'current', action: 'import_paper', controller}});
  for (const message of [{id: 'old', action: 'import_paper'}, {id: 'current', action: 'other'}]) {
    context.message = message;vm.runInContext(body, context);assert.equal(controller.signal.aborted, false);
  }
  context.message = {id: 'current', action: 'import_paper'};vm.runInContext(body, context);
  assert.equal(controller.signal.aborted, true);
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

test('Import reuses one page and replaces Paper/Service context, including an unmatched Paper',async()=>{
  const f=fixture();let created=0;
  f.context.newTaskPage=async()=>{created++;return {id:1};};
  const scope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
  const records=[];
  f.context.browser.navigate=async function(url){
    records.push({page:this.taskTab.id,url,association:JSON.parse(JSON.stringify(this.taskTab.association))});
    return {pageId:this.taskTab.id,url};
  };
  for(const [index,service] of ['svc_'+'1'.repeat(32),'svc_'+'2'.repeat(32),null].entries()) {
    await f.context.execute({id:'request'+index,action:'import_paper',data:{doi:'10.5555/'+index,
      task_id:'batch',paper_id:'paper'+index,service_scope:scope,service_id:service}});
  }
  assert.equal(created,1);
  assert.deepEqual(records.map(value=>value.page),[1,1,1]);
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
  f.context.browser.beginOperation=()=>{throw Error('must not begin browser work');};
  f.context.diagnosticsReset=value=>{data=value;return {available:true,scope_id:value.scope_id,token:'preview'};};
  await f.context.execute({id:'reset_preview',action:'diagnostics_reset',data:{operation:'preview',scope_id:'a'.repeat(64)}});
  assert.equal(data.operation,'preview');assert.equal(f.calls.end,0);assert.equal(f.calls.save,0);assert.equal(f.logs.length,0);
  assert.equal(f.messages[0].data.token,'preview');
  f.context.activeRequest=Promise.resolve();
  await assert.rejects(f.context.execute({id:'reset_busy',action:'diagnostics_reset',data:{operation:'preview'}}),/active/);
});
test('explicit credential writes settle through bridge ownership without browser dispatch or diagnostic payloads',{timeout:5000},async()=>{
  const f=fixture(),started=deferred(),settled=deferred();
  f.context.saveCASCredentials=async value=>{assert.equal(value.expected_revision,'missing');started.resolve();return settled.promise;};
  f.context.casErrorCode=error=>error.code;
  f.context.browser.beginOperation=()=>{throw Error('credentials must not enter Browser');};
  const pending=f.context.execute({id:'credentials',action:'cas_credentials',data:{operation:'save',expected_revision:'missing'}});
  await started.promise;
  assert.ok(f.context.activeRequest);
  await assert.rejects(f.run(),/Concurrent/);
  settled.resolve({ok:true,revision:'new'});await pending;
  assert.equal(f.context.activeRequest,null);assert.equal(f.calls.end,0);assert.equal(f.logs.length,0);
  assert.equal(f.messages[0].data.revision,'new');
});
test('quit confirmation occurs before aborting an active task and cancelling leaves the task running',async()=>{
  const f=fixture(),confirmation=deferred();let quitHandler,quitCalls=0;
  const controller=new AbortController();
  Object.assign(f.context,{activeOperation:{controller},readyToExit:false,exitApproved:false,exitCheck:null,
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
 assert.equal(f.context.activeRequest,null);assert.equal(f.context.activeOperation,null);
 assert.equal(f.messages[0].data.error,'canceled');assert.equal(f.calls.save,0);
});
