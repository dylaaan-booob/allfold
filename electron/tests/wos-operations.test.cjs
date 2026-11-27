'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const vm=require('node:vm');
const hostRequire=require('node:module').createRequire(require.resolve('../src/workflows/wos-operations.cjs'));
const {EventEmitter}=require('node:events');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
const {attachBrowserMechanisms}=require('./browser-fixture.cjs');
const {BrowserFailure,checkPage}=require('../src/browser/browser-errors.cjs');
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
const preparedIdentity={service_id:'svc_'+'1'.repeat(32),service_scope:{
  scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)}};
const advanced='https://www.webofscience.com/wos/woscc/advanced-search';
function fixture(t,{attributable=true,hold=false,challenge=false,domError=null,query=false,verification=false,cancelVerification=false,deferExportMenu=false,dialogInitiallyClosed=false,batchLimit=1000,customFields=SELECTORS.customFields,overlayRouting=false,replaceAfterExport=false,otherResultsAfterExport=false}={}) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-wos-test-')));
  t.after(()=>fs.rmSync(root,{force:true,recursive:true}));
  const filename=path.join(root,'allfold-wos','a'.repeat(32),'b'.repeat(32)+'.txt');
  fs.mkdirSync(path.dirname(filename),{recursive:true});
  const partition=new EventEmitter(),controller=new AbortController(),ops=[],armedTokens=new Set();
  const doc={pageId:71,processId:1,frameToken:'native-frame',documentId:'native-document',navigationGeneration:0,url:'https://www.webofscience.com/wos/woscc/summary/test',status:200,};
  const authentication=query?exportAuthentication():null;
  if(query)doc.url='https://www.webofscience.com/wos/woscc/advanced-search';
  if(overlayRouting && !dialogInitiallyClosed)doc.url+='(overlay:export/exp)';
  let currentURL=doc.url,generation=0,documentId=doc.documentId;
  let settle,exported;
  const ready=new Promise(resolve=>exported=resolve);
  const item=new EventEmitter();item.setSavePath=value=>item.filename=value;
  item.getURLChain=()=>['https://www.webofscience.com/native-export'];
  item.cancel=()=>{item.cancelled=true;if(!hold)setImmediate(()=>item.emit('done',{},'cancelled'));};
  let challengeActive=challenge;
  let exportMenuReady=!deferExportMenu;
  let dialogOpen=!dialogInitiallyClosed;
  const wc={getURL:()=>currentURL,isLoadingMainFrame:()=>false,async executeJavaScript(code){
    const [op,args]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));ops.push(op);
    if(op==='search'){currentURL='https://www.webofscience.com/wos/woscc/summary/test';generation++;}
    if(op==='result')return {total:94};
    if(op==='controlReady' && args.control==='exportMenu') {
      if(!exportMenuReady){exportMenuReady=true;return {ready:false};}
      return {ready:true};
    }
    if(op==='exportMenu' && !exportMenuReady)return {error:'control_not_unique'};
    if(op==='plainText'){dialogOpen=true;authentication?.open(verification);if(overlayRouting){currentURL='https://www.webofscience.com/wos/woscc/summary/test(overlay:export/exp)';generation++;}}
    if(op==='verification')return {ready:!challengeActive};
    if(op==='arm'){if(armedTokens.size)return {error:'download_observer_busy'};armedTokens.add(args.token);}
    if(op==='cleanup')armedTokens.delete(args.token);
    if(op==='export' && domError)return {error:domError};
    if(op==='dialog')return {ready:dialogOpen,limit:batchLimit};
    if(op==='verifyCustom')return {verified:true,fields:customFields};
    if(op==='export') {
      if(overlayRouting || replaceAfterExport || otherResultsAfterExport) {
        currentURL='https://www.webofscience.com/wos/woscc/summary/'+(otherResultsAfterExport?'other':'test');generation++;
        if(replaceAfterExport)documentId='replacement-document';
      }
      ops.push({exportRange:args});
      partition.emit('will-download',{}, {cancel(){throw Error('unrelated download intercepted');}}, {});
      partition.emit('will-download',{},item,wc,{processId:doc.processId,frameToken:doc.frameToken});
      settle=()=>item.emit('done',{},'completed');exported();
      if(!hold)setImmediate(settle);
    }
    return op==='links'?{urls:attributable?item.getURLChain():['https://other.example/download']}:{ok:true};
  }};
  const tab={id:71,view:{webContents:wc},association:preparedIdentity,
    wosDocument:doc};
  const browser={tabs:new Map([[71,tab]]),partition,operation:{association:{workflow_id:'fixture',task_id:'fixture'}},sessionEvents:sharedSessionEvents(partition),
    liveToken:doc.frameToken,select(){},async checkAuthentication(){return authentication?.inspect().waiting || false;},async documentBinding(){return {...doc,url:wc.getURL(),navigationGeneration:generation,documentId};},
    documentCurrent(value){return this.liveToken===value.frameToken && value.documentId===documentId && value.navigationGeneration===generation && value.url===currentURL;},
    documentFrame(value){return this.documentCurrent(value)?wc:null;}};
  Object.defineProperty(tab,"documentGeneration",{get:()=>generation});
  attachBrowserMechanisms(browser);tab.wosWorkflowId='fixture';
  t.after(()=>browser.sessionEvents.dispose());
  browser.serviceContext=data=>{
    const candidate=browser.tabs.get(71);
    if(candidate && data.service_id===candidate.association.service_id
      && data.service_scope.scope_id===candidate.association.service_scope.scope_id)return {tab:candidate};
    return null;
  };
  browser.resumeServiceStep=(_data,_options,step)=>step();
  browser.observeServiceTarget=(_data,_url,options,observe)=>
    observe({...options,extraWaiting:()=>false,onWaiting:()=>{}});
  browser.waitForServiceTarget=async(_data,{tab:target})=>assert.equal(target,tab);
  browser.reserveTaskPages=async()=>{};
  browser.navigateServiceTarget=async(_data,url,{tab:target})=>{
    assert.equal(target,tab);assert.equal(url,advanced);
    currentURL=url;generation++;ops.push('navigate');
  };
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
        ...hostRequire(name),
        async newTaskPage(owner,_signal,{role,managed}) {
          assert.equal(owner,browser);assert.equal(role,'wos-query');assert.equal(managed,true);
          assert.equal(browser.tabs.size,0);
          browser.tabs.set(tab.id,tab);ops.push('new page');return tab;
        }}:
      hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/workflows/wos-operations.cjs'),'utf8'),context);
  return {browser,controller,item,ops,armedTokens,ready,settle:()=>settle(),
    replacePage(url) {currentURL=url;generation++;documentId='replacement-document';},
    runQuery:(data={})=>context.module.exports.wosQuery(browser,{...preparedIdentity,page_id:71,query:'fixture query',...data},
      {signal:controller.signal,progress:value=>progress.push(value)}),
    progress,run:(data={})=>context.module.exports.wosExport(browser,{...preparedIdentity,page_id:71,download_root:root,filename,first:1,last:1,...data},
      {signal:controller.signal,progress(value){progress.push(value);if(challenge && value.waiting_for_user) {
        challengeActive=false;setImmediate(()=>settle());
      }}}),filename};
}
test('a pre-export sign-in can resume the original verified results route exactly once',async t=>{
  const f=fixture(t),tab=f.browser.tabs.get(71);
  tab.wosResultTotal=94;
  const results=tab.wosDocument.url,login='https://idp.example/idp/profile/SAML2/Redirect/SSO';
  f.replacePage(login);
  f.browser.accessState=()=>({markers:{login:tab.view.webContents.getURL()===login}});
  f.browser.waitForPage=async(_tab,{onWaiting})=>{
    onWaiting(true,undefined,await f.browser.documentBinding());
    const returned='https://www.webofscience.com/wos/';
    f.replacePage(returned);
    return f.browser.documentBinding();
  };
  f.browser.navigateServiceTarget=async(_data,url)=>{
    assert.equal(url,results);
    f.ops.push('resume verified results');
    f.replacePage(url);
    return f.browser.documentBinding();
  };
  const output=await f.run({service_entry:{idp_entity_id:'https://idp.example/idp/shibboleth'}});
  assert.equal(output.page_id,tab.id);
  assert.equal(f.ops.filter(step=>step==='resume verified results').length,1);
  assert.equal(f.ops.filter(step=>step==='export').length,1);
  assert.ok(f.ops.indexOf('result')<f.ops.indexOf('export'));
});
test('WoS accepts only an observed native export URL into its issued file',async t=>{
  const f=fixture(t);assert.equal((await f.run()).filename,f.filename);
  assert.equal(f.controller.signal.aborted,false);
  assert.equal(f.browser.taskTab.taskSignal.aborted,true,'the completed bounded request releases its signal');
  assert.equal(f.item.filename,f.filename);assert.equal(f.ops.filter(op=>op==='export').length,1);
  assert.equal(f.browser.partition.listenerCount('will-download'),1);assert.equal(f.ops.at(-1),'cleanup');
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
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
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
  assert.equal(f.ops.length,before);
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
});

test('a CARSI WoS query can acquire a new page and exports use its returned handle',async t=>{
  const f=fixture(t,{query:true});
  f.browser.tabs.clear();
  await assert.rejects(f.runQuery({page_id:null}),/document_changed/);
  assert.deepEqual(f.ops,[]);
  const query=await f.runQuery({service_entry:{resource_name:'Web of Science'}});
  assert.equal(query.page_id,71);
  assert.equal(f.ops[0],'new page');
  await assert.rejects(f.run({page_id:42}),/document_changed/);
  assert.equal((await f.run({page_id:query.page_id})).filename,f.filename);
  assert.equal(f.browser.taskTab.id,71);
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
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
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
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
});





test('a download completed after native document replacement cannot be accepted',async t=>{
  const f=fixture(t,{hold:true});const pending=f.run();await f.ready;
  f.browser.liveToken='replacement';f.settle();
  await assert.rejects(pending,/document_changed/);
  assert.equal(f.ops.includes('links'),false);assert.equal(f.ops.includes('cleanup'),false);
});


test('WoS Export expiry cancels native save but retains ownership until actual terminal',async t=>{
  t.mock.timers.enable({apis:['Date','setTimeout'],now:1000});
  const f=fixture(t,{hold:true});
  let settled=false;
  const pending=f.run().finally(()=>{settled=true;});
  const rejected=assert.rejects(pending,error=>error.diagnostic?.code==='timeout');
  await f.ready;
  t.mock.timers.tick(600000);
  assert.equal(f.item.cancelled,true);assert.equal(settled,false);
  f.settle();await rejected;
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
});

for(const dialogInitiallyClosed of [false,true])test(`WoS export retains the native results Document through known overlay routing (${dialogInitiallyClosed?'reopened':'already open'})`,async t=>{
  const f=fixture(t,{overlayRouting:true,dialogInitiallyClosed});
  assert.equal((await f.run()).filename,f.filename);
  assert.equal(f.ops.filter(op=>op==='export').length,1);
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
});
for(const change of ['replaceAfterExport','otherResultsAfterExport'])test(`WoS export still rejects ${change} after its own click`,async t=>{
  const f=fixture(t,{overlayRouting:true,[change]:true});
  await assert.rejects(f.run(),/document_changed/);
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
});

test('a failed export after opening its overlay cleans its own armed observer',async t=>{
  const f=fixture(t,{overlayRouting:true,dialogInitiallyClosed:true,domError:'control_disabled'});
  await assert.rejects(f.run(),/control_disabled/);
  assert.equal(f.ops.includes('arm'),true);
  assert.equal(f.armedTokens.size,0);
  assert.equal(f.browser.partition.listenerCount('will-download'),1);
  await assert.rejects(f.run(),/control_disabled/,'retry reaches the control, not a leaked download observer');
  assert.equal(f.armedTokens.size,0);
});

test('an unresolved prior download refuses a new export before arming or clicking its source',async t=>{
  const f=fixture(t),tab=f.browser.tabs.get(71),doc=tab.wosDocument;
  const prior=f.browser.sessionEvents.registerDownload({owner:f.browser.operation,attemptId:'unresolved',
    contents:tab.view.webContents,frame:doc,document:doc,filename:'/tmp/unused',deadline:Date.now()+1000,validate:()=>true});
  prior.dispose({dispatched:true});
  await assert.rejects(f.run(),error=>error.diagnostic?.code==='download_not_attributable');
  assert.deepEqual(f.ops,[]);assert.equal(f.armedTokens.size,0);
});
