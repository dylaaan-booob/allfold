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
