'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const {checkCanceled,pause,waitFor,waitForLoad,PAGE_LOAD_MS}=require('./browser-task.cjs');

const SEARCH_HOSTS=new Set(['research.ebsco.com','discovery.ebsco.com']);
const HUB_HOST='search.ebscohost.com';
const PROFILE=/^\/c\/[A-Za-z0-9_.~-]+(?=\/|$)/;
function refusal(step) {
  const error=new BrowserFailure('navigation','document_operation_failed');
  error.diagnostic.step=step;
  return error;
}

function httpsURL(value) {
  if(!publicClueURL(value))return null;
  const url=new URL(value);
  return url.protocol==='https:' && !url.port?url:null;
}

function profile(value) {
  const url=httpsURL(value);
  const match=url && SEARCH_HOSTS.has(url.hostname) && url.pathname.match(PROFILE);
  return match?{origin:url.origin,path:match[0]}:null;
}

function matchRecord(value,scope) {
  const url=httpsURL(value);
  const prefix=scope.path+'/search/details/';
  if(url?.origin!==scope.origin || !url.pathname.startsWith(prefix))return null;
  const record=url.pathname.slice(prefix.length);
  return /^[A-Za-z0-9_.~-]+$/.test(record)?{url,record}:null;
}

function isPdfRequest(details) {
  const file=details.method==='GET' && httpsURL(details.url);
  return file?.origin==='https://content.ebscohost.com' && file.pathname==='/cds/retrieve';
}

async function readReady(browser,tab,args,{signal,deadline,verify,retryDocumentRead=false},settled=()=>true) {
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  for(;;) {
    verify();
    try {
      const clue=await browser.readDocument(tab,'ebsco',{args,signal,deadline:limit});
      verify();
      if(clue.ready && settled(clue))return clue;
    } catch(error) {
      if(!retryDocumentRead || error.diagnostic?.code!=='document_changed')throw error;
      verify();
    }
    await waitFor(()=>pause(signal),signal,limit);
  }
}

function watchPdf(browser,tab,entry,{signal,deadline,verify}) {
  const owner=browser.operation,contents=tab.view.webContents;
  let resolve,first;
  const pending=new Promise(done=>{resolve=done;});
  const subscription=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId!==tab.id || !isPdfRequest(details) || !['xhr','subFrame','other'].includes(details.resourceType)
      || !browser.ownsPage(owner,tab.id)
      || signal?.aborted || Date.now()>=deadline)return;
    const top=httpsURL(contents.getURL());
    if(top?.origin!==entry.origin || top.pathname!==entry.pathname)return;
    const root=details.frame?.top;
    if(!root || !URL.canParse(details.frame.url) || new URL(details.frame.url).origin!==entry.origin
      || root.frameToken!==contents.mainFrame.frameToken || root.processId!==contents.mainFrame.processId)return;
    verify();
    const referer=Object.entries(details.requestHeaders || {}).find(([name])=>name.toLowerCase()==='referer')?.[1];
    const candidate={stage:'P4',rule_id:'R073',url:details.url,referer:httpsURL(referer)?.origin===entry.origin?referer:null};
    if(first?.generation===tab.documentGeneration && first.page===top.href) {
      first.ambiguous ||= first.candidate.url!==candidate.url || first.candidate.referer!==candidate.referer;
    } else {
      first={generation:tab.documentGeneration,page:top.href,frameToken:root.frameToken,processId:root.processId,
        candidate,ambiguous:false};
    }
    resolve();
  },{signal});
  return {pending,dispose:subscription.dispose,matching(doc) {
    if(!first || first.ambiguous || first.page!==doc.url || first.generation!==doc.navigationGeneration
      || first.frameToken!==doc.frameToken || first.processId!==doc.processId || !browser.documentCurrent(doc))return null;
    verify();
    return first.candidate;
  }};
}

async function readEbscoSource(browser,data,preparedURL,{signal,deadline,onWaiting,verify}) {
  const doi=validDOI(data.identity?.doi),title=data.target_title;
  const entry=httpsURL(preparedURL);
  let scope=profile(preparedURL);
  if(!doi || typeof title!=='string' || !title.trim() || title.length>4096 || !entry
    || !scope && entry.hostname!==HUB_HOST)throw refusal('prepared');
  checkCanceled(signal);
  const tab=await browser.newTaskPage({signal,deadline,managed:true});
  browser.bindTaskPage(tab,signal);
  browser.associatePage(tab,{role:'pdf-reader'});
  // Block automatic previews and unattributed GETs in this task page until
  // Chromium actually destroys it. Only the verified Viewer can supply a URL.
  const pdfGuard=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId===tab.id && isPdfRequest(details))return {cancel:true};
  });
  tab.view.webContents.once('destroyed',pdfGuard.dispose);
  const options={signal,deadline,verify};
  const visit=async (url,{documentOnly=false}={})=>{
    verify();
    const doc=await browser.navigate(url.href,{tab,signal,deadline,documentOnly,onWaiting:(diagnostic,current)=>{
      // An expired institutional login cannot consume the parent's budget.
      // The user can re-prepare this Service through the normal Login path.
      if(current?.markers.login || current?.markers.mfa)throw new BrowserFailure('navigation','content_access_blocked');
      onWaiting?.(diagnostic);
    }});
    browser.finishPageLoad(tab);
    verify();
    return doc;
  };

  const guard=browser.sessionEvents.subscribe('beforeRequest',details=>{
    if(details.webContentsId!==tab.id || !['mainFrame','subFrame'].includes(details.resourceType))return;
    verify();
    if(signal?.aborted || Date.now()>=deadline || !httpsURL(details.url))return {cancel:true};
  },{signal});
  try {
    if(!scope) {
      const hubURL=(await visit(entry)).url;
      scope=profile(hubURL);
      if(!scope) {
        if(httpsURL(hubURL)?.hostname!==HUB_HOST)throw refusal('resource_ready');
        const hub=await readReady(browser,tab,{mode:'profile'},options);
        const links=hub.urls.map(httpsURL).filter(url=>url && (profile(url.href) || url.hostname===HUB_HOST));
        if(links.length!==1)throw refusal('resource_ready');
        scope=profile((await visit(links[0])).url);
        if(!scope)throw refusal('resource_ready');
      }
    }
    const search=new URL(scope.path+'/search/results',scope.origin);
    search.searchParams.set('q',doi);
    // Once the authenticated results Document is readable, unrelated assets
    // need not finish before looking for the qualified record link.
    const searchDocument=await visit(search,{documentOnly:true});
    const contents=tab.view.webContents;
    const navigation=tab.navigation.current;
    const frame={pageId:searchDocument.pageId,processId:searchDocument.processId,frameToken:searchDocument.frameToken};
    const verifySearch=()=>{
      verify();
      const landing=httpsURL(contents.getURL());
      // The same document may add search filters to its query string.
      if(landing?.origin!==scope.origin || landing.pathname!==search.pathname
        || tab.navigation.current!==navigation || !navigation.documentReady
        || !browser.documentCurrent(frame))throw refusal('search');
    };
    const found=await readReady(browser,tab,{mode:'results',title},{...options,verify:verifySearch,retryDocumentRead:true},
      clue=>clue.urls.length>0 || !contents.isLoadingMainFrame());
    if(found.documentId!==searchDocument.documentId)throw refusal('search');
    const records=found.urls.map(url=>matchRecord(url,scope)).filter(Boolean);
    if(records.length!==1)throw refusal('result');
    if(contents.isLoadingMainFrame()) {
      contents.stop();
      await waitForLoad(tab,signal,deadline,verifySearch);
    }
    verifySearch();
    const record=records[0];
    const doc=await visit(record.url),detail=matchRecord(doc.url,scope);
    if(detail?.record!==record.record)throw refusal('contentReady');
    const matched=await readReady(browser,tab,{mode:'record',title,doi},options,clue=>!clue.doi || clue.urls.length>0);
    if(!matched.doi || !browser.documentCurrent(doc))throw refusal('contentReady');
    const links=matched.urls.map(httpsURL).filter(url=>url?.origin===scope.origin
      && url.pathname===scope.path+'/viewer/pdf/'+record.record);
    if(links.length!==1)throw refusal('contentReady');
    const reader=watchPdf(browser,tab,links[0],options);
    try {
      const viewer=await visit(links[0]);
      await waitFor(()=>reader.pending,signal,Math.min(deadline,Date.now()+PAGE_LOAD_MS));
      const candidate=reader.matching(viewer);
      if(!candidate)throw refusal('download');
      return {outcome:'retrieved',pdf_clues:{status:'complete',landing_url:detail.url.href,
        observed_at:new Date().toISOString(),platform:'ebsco',content_type:'journal-article',
        identifiers:[],candidates:[candidate],diagnostics:[]}};
    } finally {reader.dispose();}
  } finally {
    guard.dispose();
  }
}

module.exports={readEbscoSource};
