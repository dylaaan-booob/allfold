'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const vm=require('node:vm');
const hostRequire=require('node:module').createRequire(require.resolve('../src/workflows/wos-operations.cjs'));
const {EventEmitter}=require('node:events');
const {attachBrowserMechanisms}=require('./browser-fixture.cjs');
const {ImportFailure,checkPage}=require('../src/workflows/import-errors.cjs');
const {pageStep,SELECTORS}=require('../src/workflows/page-actions.cjs');
const {institutionAuthPage}=require('../src/auth/institution-auth.cjs');
function exportAuthentication() {
  let dialog=false,otp=false;
  const input={type:'number',name:'markTo',id:'ending-range',disabled:true,autocomplete:'',labels:[],isConnected:true,
    getClientRects:()=>dialog?[{}]:[],closest:()=>null,
    getAttribute:key=>key==='aria-label'?'Input ending record range. A maximum of 1000 records can be exported at one time.':null};
  const context=vm.createContext({URL,location:{href:'https://www.webofscience.com/wos/woscc/summary/fixture(overlay:export/exp)'},
    getComputedStyle:()=>({visibility:'visible',display:'block'}),
    document:{title:'Export Records to Plain Text File',body:{innerText:''},getElementById:()=>null,
      querySelectorAll:selector=>selector==='input'?[input]:[]}});
  context.window=context;context.top=context;
  return {open(challenge){dialog=true;otp=challenge;input.autocomplete=otp?'one-time-code':'';},
    complete(){otp=false;input.autocomplete='';},get waitingForCode(){return otp;},
    inspect(){return vm.runInContext('('+institutionAuthPage.toString()+')()',context);}};
}
function domFixture(pathname,{challenge=false,hidden=false,emptyHost=false}={}) {
  const listeners=new Set();
  const widget={getClientRects:()=>hidden?[]:[{}]};
  const captchaHost={getClientRects:()=>[{}],innerText:''};
  const context=vm.createContext({Date,location:{pathname},
    getComputedStyle:()=>({visibility:'visible'}),HTMLAnchorElement:class {click(){}},
    document:{body:{innerText:''},querySelectorAll:selector=>emptyHost && selector.includes('app-captcha-details')?[captchaHost]:
        challenge && selector.startsWith('iframe[')?[widget]:[],
      addEventListener:(_name,listener)=>listeners.add(listener),
      removeEventListener:(_name,listener)=>listeners.delete(listener)}});
  const run=(op,args={})=>vm.runInContext('('+pageStep.toString()+')(...'+JSON.stringify([op,args,{},Date.now()+3000])+')',context);
  return {context,listeners,run};
}
const preparedIdentity={service_id:'svc_'+'1'.repeat(32),preparation_key:'e'.repeat(64),service_scope:{
  scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)}};
function queryFixture(stages,{cancel=false,authError=false,advance=()=>{}}={}) {
  const controller=new AbortController(),events=[],progress=[],entryWindows=[];
  let index=0,current={...stages[0]};
  const wc={getURL:()=>current.url,isLoadingMainFrame:()=>!!current.loading,
    async executeJavaScript(code){
      const [op]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));events.push(op);
      entryWindows.push({op,eligible:tab.recoveryActive,reloads:tab.reloads});
      if(op==='verification')return domFixture(new URL(current.url).pathname,{challenge:current.challenge}).run(op);
      if(op==='result')return {total:0};
      if(op==='ready' && current.ready===false)return {ready:false};
      return {ready:true};
    }};
  const tab={id:71,view:{webContents:wc},association:preparedIdentity,
    preparationKey:preparedIdentity.preparation_key,recoveryActive:false,reloads:1};
  const browser={tabs:new Map([[71,tab]]),select(){},async checkAuthentication(){if(authError)throw new ImportFailure('authentication','institution_credentials_rejected');return false;},
    async snapshot(){return {pageId:71,url:current.url,status:200,title:'Fixture',html:'Fixture'};},
    documentCurrent:()=>true,documentFrame:()=>wc};
  attachBrowserMechanisms(browser);
  const checkCanceled=signal=>{if(signal.aborted)throw new ImportFailure('navigation','canceled');};
  const context=vm.createContext({module:{exports:{}},Date,URL,setTimeout,clearTimeout,
    require:name=>name==='./page-actions.cjs'?{pageStep:function(){},SELECTORS:{}}:
      name==='../browser/browser-task.cjs'?{...require('../src/browser/browser-task.cjs'),checkCanceled,
        async pause(signal){
          if(cancel)controller.abort();checkCanceled(signal);
          advance();
          if(index+1>=stages.length)throw Error('Unexpected additional wait');
          current={...stages[++index]};events.push('natural-navigation');
        }}:
      name==='./browser-operations.cjs'?{async navigate(_browser,target,url,signal){
          checkCanceled(signal);events.push('navigate');assert.equal(tab.recoveryActive,false);
          assert.equal(target,tab);
          assert.equal(index,stages.length-1,'must let the existing authentication finish');
          assert.equal(current.loading,undefined);assert.notEqual(current.challenge,true);
          current={url};
        }}:
      name==='./import-errors.cjs'?{ImportFailure,checkPage}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/workflows/wos-operations.cjs'),'utf8'),context);
  return {events,progress,controller,tab,entryWindows,
    run:()=>context.module.exports.wosQuery(browser,{...preparedIdentity,page_id:71,query:'fixture query'},
      {signal:controller.signal,progress:value=>progress.push(value)})};
}
const advanced='https://www.webofscience.com/wos/woscc/advanced-search';
function fixture(t,{attributable=true,hold=false,challenge=false,domError=null,query=false,verification=false,cancelVerification=false,deferExportMenu=false,dialogInitiallyClosed=false,batchLimit=1000,customFields=SELECTORS.customFields}={}) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-wos-test-')));
  t.after(()=>fs.rmSync(root,{force:true,recursive:true}));
  const filename=path.join(root,'allfold-wos','a'.repeat(32),'b'.repeat(32)+'.txt');
  fs.mkdirSync(path.dirname(filename),{recursive:true});
  const partition=new EventEmitter(),controller=new AbortController(),ops=[];
  const doc={pageId:71,processId:1,frameToken:'native-frame',url:'https://www.webofscience.com/wos/woscc/summary/test',status:200,title:'Results',html:'Results'};
  const authentication=query?exportAuthentication():null;
  if(query)doc.url='https://www.webofscience.com/wos/woscc/advanced-search';
  let settle,exported;
  const ready=new Promise(resolve=>exported=resolve);
  const item=new EventEmitter();item.setSavePath=value=>item.filename=value;
  item.getURLChain=()=>['https://www.webofscience.com/native-export'];
  item.cancel=()=>{item.cancelled=true;};
  let challengeActive=challenge;
  let exportMenuReady=!deferExportMenu;
  let dialogOpen=!dialogInitiallyClosed;
  const wc={getURL:()=>doc.url,isLoadingMainFrame:()=>false,async executeJavaScript(code){
    const [op,args]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));ops.push(op);
    if(op==='search')doc.url='https://www.webofscience.com/wos/woscc/summary/test';
    if(op==='result')return {total:94};
    if(op==='controlReady' && args.control==='exportMenu') {
      if(!exportMenuReady){exportMenuReady=true;return {ready:false};}
      return {ready:true};
    }
    if(op==='exportMenu' && !exportMenuReady)return {error:'control_not_unique'};
    if(op==='plainText'){dialogOpen=true;authentication?.open(verification);}
    if(op==='verification')return {ready:!challengeActive};
    if(op==='export' && domError)return {error:domError};
    if(op==='dialog')return {ready:dialogOpen,limit:batchLimit};
    if(op==='verifyCustom')return {verified:true,fields:customFields};
    if(op==='export') {
      ops.push({exportRange:args});
      partition.emit('will-download',{}, {cancel(){throw Error('unrelated download intercepted');}}, {});
      partition.emit('will-download',{},item,wc);
      settle=()=>item.emit('done',{},'completed');exported();
      if(!hold)setImmediate(settle);
    }
    return op==='links'?{urls:attributable?item.getURLChain():['https://other.example/download']}:{ok:true};
  }};
  const tab={id:71,view:{webContents:wc},association:preparedIdentity,
    preparationKey:preparedIdentity.preparation_key,wosServiceScope:preparedIdentity.service_scope,wosDocument:doc};
  const browser={tabs:new Map([[71,tab]]),partition,
    liveToken:doc.frameToken,select(){},async checkAuthentication(){return authentication?.inspect().waiting || false;},async snapshot(){return {...doc,url:wc.getURL()};},
    documentCurrent(value){return this.liveToken===value.frameToken;},
    documentFrame(value){return this.documentCurrent(value)?wc:null;}};
  attachBrowserMechanisms(browser);
  browser.servicePages=(scopeId,serviceId)=>[...browser.tabs.values()]
    .filter(candidate=>candidate.association?.service_scope?.scope_id===scopeId && candidate.association?.service_id===serviceId)
    .map(candidate=>({page_id:candidate.id}));
  browser.inspectAuthentication=async()=>authentication?.inspect() || {waiting:false};
  const progress=[];
  const context=vm.createContext({module:{exports:{}},Date,URL,AbortSignal,setTimeout,clearTimeout,
    require:name=>name==='./page-actions.cjs'?{pageStep:function(){},SELECTORS}:
      name==='../browser/browser-task.cjs'?{...require('../src/browser/browser-task.cjs'),async pause(){
        if(authentication && verification) {
          if(!authentication.waitingForCode)throw Error('Unexpected authentication wait on business dialog');
          if(cancelVerification)controller.abort();else authentication.complete();
        }
      },checkCanceled:signal=>{if(signal.aborted)throw Error('canceled');}}:
      name==='./browser-operations.cjs'?{
        async newTaskPage(owner,_signal,{role,managed}) {
          assert.equal(owner,browser);assert.equal(role,'wos-query');assert.equal(managed,true);
          assert.equal(browser.tabs.size,0);
          browser.tabs.set(tab.id,tab);ops.push('new page');return tab;
        },
        async navigate(_browser,target,url) {
          assert.equal(target,tab);assert.equal(url,advanced);
          doc.url=url;ops.push('navigate');
        }}:
      name==='./import-errors.cjs'?{ImportFailure,checkPage}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/workflows/wos-operations.cjs'),'utf8'),context);
  return {browser,controller,item,ops,ready,settle:()=>settle(),
    runQuery:(data={})=>context.module.exports.wosQuery(browser,{...preparedIdentity,page_id:71,query:'fixture query',...data},
      {signal:controller.signal,progress:value=>progress.push(value)}),
    progress,run:(data={})=>context.module.exports.wosExport(browser,{...preparedIdentity,page_id:71,download_root:root,filename,first:1,last:1,...data},
      {signal:controller.signal,progress(value){progress.push(value);if(challenge && value.waiting_for_user) {
        challengeActive=false;setImmediate(()=>settle());
      }}}),filename};
}
test('WoS accepts only an observed native export URL into its issued file',async t=>{
  const f=fixture(t);assert.equal((await f.run()).filename,f.filename);
  assert.equal(f.browser.taskTab.taskSignal,f.controller.signal);
  assert.equal(f.item.filename,f.filename);assert.equal(f.ops.filter(op=>op==='export').length,1);
  assert.equal(f.browser.partition.listenerCount('will-download'),0);assert.equal(f.ops.at(-1),'cleanup');
});
test('WoS reopens and verifies every persisted Custom field before arming a download',async t=>{
  const f=fixture(t);await f.run();
  assert.equal(f.ops.filter(op=>op==='saveCustom').length,2);
  assert.ok(f.ops.indexOf('configureCustom')<f.ops.indexOf('verifyCustom'));
  assert.ok(f.ops.indexOf('verifyCustom')<f.ops.indexOf('arm'));
  assert.equal(f.ops.find(op=>op?.exportRange).exportRange.customVerified,true);
});
test('a wrong persisted Custom field set refuses export before installing a download observer',async t=>{
  const f=fixture(t,{customFields:[...SELECTORS.customFields.slice(1),'citedRefUse_HOT_PAPER']});
  await assert.rejects(f.run(),/export_content_unverified/);
  assert.equal(f.ops.includes('arm'),false);
  assert.equal(f.ops.includes('export'),false);
  assert.equal(f.browser.partition.listenerCount('will-download'),0);
});
test('the current Custom range limit governs every batch without a hardcoded 1000 ceiling',async t=>{
  const small=fixture(t,{batchLimit:1});
  await assert.rejects(small.run({first:1,last:2}),/export_range_exceeds_limit/);
  assert.equal(small.ops.includes('export'),false);
  const large=fixture(t,{batchLimit:1500});
  await large.run({first:1,last:1200});
  assert.equal(large.ops.filter(op=>op==='export').length,1);
});
test('WoS query and consecutive exports keep the prepared page/document while another tab is visible',async t=>{
  const f=fixture(t,{query:true}),tab=f.browser.tabs.get(71);
  const identity={...preparedIdentity,service_scope:{...preparedIdentity.service_scope,
    config_revision:'f'.repeat(64),user_state_revision:'0'.repeat(64)}};
  tab.association={...preparedIdentity,source_page_id:55};
  f.browser.selected={id:99};
  f.browser.select=()=>{throw Error('Task must not change presentation');};
  await assert.rejects(f.runQuery({...identity,preparation_key:'1'.repeat(64)}),/document_changed/);
  assert.equal(f.ops.length,0);
  const query=await f.runQuery(identity);
  assert.equal(query.page_id,71);assert.equal(query.total,94);
  const document=f.browser.tabs.get(71).wosDocument;
  await f.run(identity);
  f.browser.taskTab=null;
  await f.run({...identity,first:2,last:2});
  assert.equal(f.browser.taskTab,tab);
  assert.equal(f.browser.tabs.get(71).wosDocument,document);
  assert.equal(f.browser.selected.id,99);
  assert.deepEqual(f.ops.filter(op=>op?.exportRange).map(op=>op.exportRange),[
    {first:1,last:1,customVerified:true},{first:2,last:2,customVerified:true}]);
  const before=f.ops.length;
  await assert.rejects(f.run({...identity,service_scope:{...identity.service_scope,scope_id:'d'.repeat(64)}}),/document_changed/);
  await assert.rejects(f.run(preparedIdentity),/document_changed/);
  assert.equal(f.ops.length,before);
  assert.equal(f.browser.partition.listenerCount('will-download'),0);
});

test('manual confirmation opens a WoS query page and keeps that page for export',async t=>{
  const f=fixture(t,{query:true});
  f.browser.tabs.clear();
  await assert.rejects(f.runQuery({page_id:null}),/wos_target_lost/);
  assert.deepEqual(f.ops,[]);

  const query=await f.runQuery({page_id:42,manually_confirmed:true});
  assert.equal(query.page_id,71);
  assert.deepEqual(f.ops.slice(0,2),['new page','navigate']);
  const tab=f.browser.tabs.get(query.page_id);
  assert.equal(tab.preparationKey,preparedIdentity.preparation_key);
  assert.equal((await f.run({page_id:query.page_id})).filename,f.filename);
  assert.equal(f.browser.taskTab,tab);
  assert.equal((await f.runQuery({page_id:null,manually_confirmed:true})).page_id,tab.id);
  assert.equal(f.ops.filter(op=>op==='new page').length,1);
});
test('WoS waits for a result toolbar that mounts after the result count, then opens export once',async t=>{
  const f=fixture(t,{query:true,deferExportMenu:true});
  const result=await f.runQuery();
  assert.equal(result.total,94);
  assert.equal(result.page_id,71);
  assert.equal(f.ops.filter(op=>op==='exportMenu').length,1);
});
test('a later export waits for the toolbar before reopening its closed dialog',async t=>{
  const f=fixture(t,{deferExportMenu:true,dialogInitiallyClosed:true});
  assert.equal((await f.run()).filename,f.filename);
  assert.equal(f.ops.filter(op=>op==='exportMenu').length,1);
  assert.equal(f.ops.filter(op=>op==='export').length,1);
  assert.equal(f.browser.partition.listenerCount('will-download'),0);
});
test('WoS refuses an unattributable completed download and a replaced document',async t=>{
  const f=fixture(t,{attributable:false});await assert.rejects(f.run(),/download_not_attributable/);
  f.browser.liveToken='replacement';
  const clicks=f.ops.filter(op=>op==='export').length;
  await assert.rejects(f.run(),/document_changed/);
  assert.equal(f.ops.filter(op=>op==='export').length,clicks);
});
test('WoS cancellation waits for the active native download terminal event',async t=>{
  const f=fixture(t,{hold:true});let finished=false;
  const pending=f.run().finally(()=>{finished=true;});await f.ready;
  f.controller.abort();await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.item.cancelled,true);assert.equal(finished,false);
  f.settle();await assert.rejects(pending,/canceled/);
  assert.equal(f.browser.partition.listenerCount('will-download'),0);
});





test('a download completed after native document replacement cannot be accepted',async t=>{
  const f=fixture(t,{hold:true});const pending=f.run();await f.ready;
  f.browser.liveToken='replacement';f.settle();
  await assert.rejects(pending,/document_changed/);
  assert.equal(f.ops.includes('links'),false);assert.equal(f.ops.includes('cleanup'),false);
});

