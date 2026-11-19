'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const {checkCanceled,pause,waitFor,PAGE_LOAD_MS}=require('./browser-task.cjs');

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

async function readReady(browser,tab,args,{signal,deadline,verify},settled=()=>true) {
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  for(;;) {
    verify();
    const clue=await browser.readDocument(tab,'ebsco',{args,signal,deadline:limit});
    if(clue.ready && settled(clue))return clue;
    await waitFor(()=>pause(signal),signal,limit);
  }
}

function watchPdf(browser,tab,entry,{signal,deadline,verify}) {
  const owner=browser.operation,contents=tab.view.webContents;
  let resolve,first;
  const pending=new Promise(done=>{resolve=done;});
  const subscription=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId!==tab.id || details.method!=='GET' || !['xhr','subFrame','other'].includes(details.resourceType)
      || !browser.ownsPage(owner,tab.id)
      || signal?.aborted || Date.now()>=deadline)return;
    const top=httpsURL(contents.getURL());
    const file=httpsURL(details.url);
    if(top?.origin!==entry.origin || top.pathname!==entry.pathname
      || file?.origin!=='https://content.ebscohost.com' || file.pathname!=='/cds/retrieve')return;
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
    // The verified Paper stream, not the record preview, owns the first sent
    // PDF GET and the file. Search and metadata requests continue normally.
    return {cancel:true};
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
  const options={signal,deadline,verify};
  const visit=async url=>{
    verify();
    const doc=await browser.navigate(url.href,{tab,signal,deadline,onWaiting:(diagnostic,current)=>{
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
    const landing=httpsURL((await visit(search)).url);
    if(landing?.origin!==scope.origin || landing.pathname!==search.pathname)throw refusal('search');
    const found=await readReady(browser,tab,{mode:'results',title},options);
    const records=found.urls.map(url=>matchRecord(url,scope)).filter(Boolean);
    if(records.length!==1)throw refusal('result');
    const record=records[0];
    const preview=watchPdf(browser,tab,record.url,options);
    let detail,matched,candidate;
    try {
      const doc=await visit(record.url);
      detail=matchRecord(doc.url,scope);
      if(detail?.record!==record.record)throw refusal('contentReady');
      matched=await readReady(browser,tab,{mode:'record',title,doi},options,clue=>
        !clue.doi || clue.urls.length>0 || !!preview.matching(doc));
      if(!matched.doi || !browser.documentCurrent(doc))throw refusal('contentReady');
      candidate=preview.matching(doc);
    } finally {preview.dispose();}
    if(!candidate) {
      const links=matched.urls.map(httpsURL).filter(url=>url?.origin===scope.origin
        && url.pathname===scope.path+'/viewer/pdf/'+record.record);
      if(links.length!==1)throw refusal('contentReady');
      const reader=watchPdf(browser,tab,links[0],options);
      try {
        const doc=await visit(links[0]);
        await waitFor(()=>reader.pending,signal,Math.min(deadline,Date.now()+PAGE_LOAD_MS));
        candidate=reader.matching(doc);
        if(!candidate)throw refusal('download');
      } finally {reader.dispose();}
    }
    return {outcome:'retrieved',pdf_clues:{status:'complete',landing_url:detail.url.href,
      observed_at:new Date().toISOString(),platform:'ebsco',content_type:'journal-article',
      identifiers:[],candidates:[candidate],diagnostics:[]}};
  } finally {
    guard.dispose();
  }
}

module.exports={readEbscoSource};
