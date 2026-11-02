'use strict';
const fs=require('node:fs');
const path=require('node:path');
const {randomBytes}=require('node:crypto');
const {pageStep,SELECTORS}=require('./page-actions.cjs');
const {navigate}=require('./browser-operations.cjs');
const {pause,checkCanceled,waitFor,withTaskDeadline,timeoutFailure}=require('../browser/browser-task.cjs');
const {BrowserFailure,checkPage}=require('../browser/browser-errors.cjs');

function taskPage(browser,data,signal) {
  const tab=browser.tabs.get(data.page_id);
  if(!tab)throw Error('wos_target_lost');
  if(tab.carsiOwned && !tab.authContext?.active)browser.beginAuthentication(tab,signal,{institution:false});
  tab.taskSignal=signal;
  browser.taskTab=tab;browser.taskActive=true;browser.select(tab);
  return tab;
}
async function page(browser,doc,op,args,signal,deadline=Infinity) {
  const frame=browser.documentFrame(doc);
  if(!frame)throw new BrowserFailure('navigation','document_changed');
  const code='('+pageStep.toString()+')(...'+JSON.stringify([op,args,SELECTORS,Math.min(deadline,Date.now()+3000)])+')';
  // Execute against the captured native frame, never a replacement WebContents document.
  const result=await waitFor(()=>frame.executeJavaScript(code),signal,deadline,'wos_dom',op);
  if(op!=='search' && !browser.documentCurrent(doc))
    throw new BrowserFailure('navigation','document_changed');
  if(result.error==='server_unexpected_error')
    throw new BrowserFailure('wos_dom','server_unexpected_error');
  return result;
}
async function step(browser,tab,op,args,signal,progress,timeout=10000,requestDeadline=Date.now()+600000) {
  let remaining=timeout;
  while(true) {
    checkCanceled(signal);
    const started=Date.now(),deadline=Math.min(requestDeadline,started+remaining);
    if(started>=requestDeadline)throw timeoutFailure('wos_dom',op);
    const observed=await browser.inspectPage(tab,{signal,deadline:requestDeadline,automaticDeadline:deadline,
      stage:'wos_dom',step:op,onWaiting:waiting=>progress({waiting_for_user:waiting}),extraWaiting:doc=>op==='verification' && !new URL(doc.url).pathname.startsWith('/wos/')});
    if(browser.wosDocument && !browser.documentCurrent(browser.wosDocument))
      throw new BrowserFailure('navigation','document_changed');
    if(observed.loading) {
      await waitFor(()=>pause(signal),signal,deadline,'wos_dom',op);
      remaining-=Date.now()-started;continue;
    }
    const doc=observed.doc,url=new URL(doc.url);
    checkCanceled(signal);
    if(browser.wosDocument && (url.origin!=='https://www.webofscience.com'
      || !url.pathname.startsWith('/wos/woscc/summary/')))
      throw new BrowserFailure('navigation','unverified_results_page');
    let waiting=observed.waiting;
    if(!waiting && url.origin==='https://www.webofscience.com' && !tab.view.webContents.isLoadingMainFrame()) {
      const value=await page(browser,doc,op,args,signal,deadline);
      checkCanceled(signal);
      if(browser.wosDocument && !browser.documentCurrent(browser.wosDocument))
        throw new BrowserFailure('navigation','document_changed');
      if(value.error==='verification_required' || (op==='verification' && value.ready===false))waiting=true;
      else if(value.error) {
        const codes=new Set(['control_not_unique','control_disabled','input_value_mismatch',
          'core_collection_unverified','stale_search_results','export_range_unverified',
          'download_observer_busy','action_expired','export_content_unverified','unknown_dom_step','dom_step_failed']);
        const error=new BrowserFailure('wos_dom',codes.has(value.error)?value.error:'dom_step_failed');
        error.diagnostic.step=op;
        throw error;
      }
      else if(value.ready!==false)return value;
    } else if(!waiting && url.origin!=='https://www.webofscience.com')waiting=true;
    if(waiting) {
      progress({waiting_for_user:true});
      await waitFor(()=>pause(signal),signal,requestDeadline,'wos_dom',op);
    } else {
      progress({waiting_for_user:false});
      await waitFor(()=>pause(signal),signal,deadline,'wos_dom',op);
      remaining-=Date.now()-started;
    }
  }
}
async function wosQuery(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'wos_dom',(bounded,deadline)=>
    wosQueryWithinDeadline(browser,data,{signal:bounded,progress},deadline));
}
async function wosQueryWithinDeadline(browser,data,{signal,progress},deadline) {
  const tab=taskPage(browser,data,signal);
  browser.beginPageLoad(tab,signal,deadline);
  browser.wosDocument=null;
  const run=(op,args={},timeout=10000)=>step(browser,tab,op,args,signal,progress,timeout,deadline);
  // Let CARSI/SSO finish in the existing page before starting another navigation.
  await run('verification',{},85000);
  browser.finishPageLoad(tab);
  progress({waiting_for_user:false});
  if(new URL(tab.view.webContents.getURL()).pathname!=='/wos/woscc/advanced-search')
    await navigate(browser,tab,'https://www.webofscience.com/wos/woscc/advanced-search',signal,progress,deadline);
  await run('ready',{},85000);
  browser.enterBusiness();
  await run('search',{query:data.query});
  const result=await run('result',{},85000);
  if(!Number.isSafeInteger(result.total) || result.total<0)throw Error('invalid_result_count');
  let batchLimit=1000;
  if(result.total) {
    await run('exportMenu');
    await run('controlReady',{control:'plainText'});
    await run('plainText');
    batchLimit=(await run('dialog')).limit;
  }
  browser.wosDocument=await waitFor(()=>browser.snapshot(tab),signal,deadline,'wos_dom','result');
  if(!browser.documentCurrent(browser.wosDocument))throw new BrowserFailure('navigation','document_changed');
  return {total:result.total,batch_limit:batchLimit,page_id:tab.id};
}
async function wosExport(browser,data,{signal,progress}) {
  const tab=taskPage(browser,data,signal),doc=browser.wosDocument;
  browser.enterBusiness();
  if(!doc || doc.pageId!==data.page_id || !browser.documentCurrent(doc))
    throw new BrowserFailure('navigation','document_changed');
  if(!Number.isInteger(data.first) || !Number.isInteger(data.last) || data.first<1
    || data.last<data.first || data.last-data.first>=1000)throw Error('invalid_export_range');
  const root=path.resolve(data.download_root),filename=path.resolve(data.filename);
  const relative=path.relative(root,filename);
  if(path.isAbsolute(relative) || relative.startsWith('..') || !/^allfold-wos\/[a-f0-9]+\/[a-f0-9]+\.txt$/.test(relative))
    throw Error('invalid_export_path');
  for(let current=path.dirname(filename);;current=path.dirname(current)) {
    const info=fs.lstatSync(current);if(!info.isDirectory() || info.isSymbolicLink())throw Error('unsafe_export_path');
    if(current===root)break;
  }
  if(fs.existsSync(filename))throw Error('export_already_exists');
  while(tab.view.webContents.isLoadingMainFrame())await pause(signal);
  checkCanceled(signal);
  let dialog=await page(browser,doc,'dialog',{});
  if(!dialog.ready) {
    await step(browser,tab,'exportMenu',{},signal,progress);
    await step(browser,tab,'controlReady',{control:'plainText'},signal,progress);
    await step(browser,tab,'plainText',{},signal,progress);
    dialog=await step(browser,tab,'dialog',{},signal,progress);
  }
  if(data.last-data.first+1>dialog.limit)throw Error('export_range_exceeds_limit');
  await step(browser,tab,'configure',{first:data.first,last:data.last},signal,progress);
  await step(browser,tab,'contentReady',{},signal,progress);
  await step(browser,tab,'selectContent',{},signal,progress);
  const token=randomBytes(16).toString('hex');
  await step(browser,tab,'arm',{token},signal,progress);
  let item=null,terminal=null,ambiguous=false,finished=false;
  const done=new Promise(resolve=>terminal=resolve);
  const listener=(_event,download,source)=>{
    if(source!==tab.view.webContents)return;
    if(item){ambiguous=true;download.cancel();item.cancel();return;}
    item=download;
    // Untrusted native filenames are ignored. The file is only staging until URL attribution succeeds.
    item.setSavePath(filename);
    item.once('done',(_e,state)=>{finished=true;terminal(state);});
    if(signal.aborted)item.cancel();
  };
  const cancel=()=>item?.cancel();
  browser.partition.on('will-download',listener);signal.addEventListener('abort',cancel,{once:true});
  let timer;
  try {
    await step(browser,tab,'export',{first:data.first,last:data.last},signal,progress);
    let state,waiting=false;
    while(true) {
      // Without a DownloadItem, cancellation ends the wait immediately.
      if(!item)checkCanceled(signal);
      await browser.checkAuthentication(tab);
      state=await Promise.race([done,new Promise(resolve=>{timer=setTimeout(()=>resolve('poll'),500);})]);
      clearTimeout(timer);
      if(state!=='poll')break;
      let needsHuman=false;
      if(!signal.aborted && !tab.view.webContents.isLoadingMainFrame()) {
        if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
        const current=await browser.snapshot(tab);
        try {checkPage(current.status,current.title,current.html);}
        catch(error){if(error.diagnostic?.code!=='verification_page')throw error;needsHuman=true;}
        if(!needsHuman && !tab.view.webContents.isLoadingMainFrame())
          needsHuman=(await page(browser,doc,'verification',{})).ready===false;
      }
      if(needsHuman!==waiting){waiting=needsHuman;progress({waiting_for_user:waiting});}
    }
    checkCanceled(signal);
    if(state!=='completed') {
      const code={interrupted:'download_interrupted',cancelled:'download_cancelled'}[state] || 'download_failed';
      throw new BrowserFailure('wos_download',code);
    }
    if(ambiguous)throw new BrowserFailure('wos_download','download_ambiguous');
    if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
    const observed=await step(browser,tab,'links',{token},signal,progress);
    if(!item.getURLChain().some(url=>observed.urls.includes(url)))throw new BrowserFailure('wos_download','download_not_attributable');
    return {filename};
  } finally {
    clearTimeout(timer);signal.removeEventListener('abort',cancel);browser.partition.removeListener('will-download',listener);
    if(item && !finished){item.cancel();await done;}
    // Cleanup is scoped to the same document; never mutate a replacement page.
    if(browser.documentCurrent(doc) && !tab.view.webContents.isLoadingMainFrame())
      await page(browser,doc,'cleanup',{token}).catch(()=>{});
  }
}
module.exports={wosQuery,wosExport};
