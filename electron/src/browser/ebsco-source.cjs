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

async function readReady(browser,tab,args,{signal,deadline,verify}) {
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  for(;;) {
    verify();
    const clue=await browser.readDocument(tab,'ebsco',{args,signal,deadline:limit});
    if(clue.ready)return clue;
    await waitFor(()=>pause(signal),signal,limit);
  }
}

async function locatePdf(browser,tab,viewer,{signal,deadline,onWaiting,verify}) {
  const owner=browser.operation,contents=tab.view.webContents;
  let resolve;
  const pending=new Promise(done=>{resolve=done;});
  const subscription=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId!==tab.id || details.method!=='GET' || !['xhr','subFrame','other'].includes(details.resourceType)
      || !browser.ownsPage(owner,tab.id)
      || signal?.aborted || Date.now()>=deadline)return;
    const top=httpsURL(contents.getURL());
    const file=httpsURL(details.url);
    if(top?.origin!==viewer.origin || top.pathname!==viewer.pathname
      || file?.origin!=='https://content.ebscohost.com' || file.pathname!=='/cds/retrieve')return;
    if(details.frame && (!URL.canParse(details.frame.url) || new URL(details.frame.url).origin!==viewer.origin
      || details.frame.top?.frameToken!==contents.mainFrame.frameToken))return;
    verify();
    const referer=Object.entries(details.requestHeaders || {}).find(([name])=>name.toLowerCase()==='referer')?.[1];
    resolve({stage:'P4',rule_id:'R073',url:details.url,referer:httpsURL(referer)?.origin===viewer.origin?referer:null});
    // The current viewer has issued a qualified GET. Let the normal Download
    // stream own that request and the file; do not transfer it in the viewer too.
    return {cancel:true};
  },{signal});
  try {
    const doc=await browser.navigate(viewer.href,{tab,signal,deadline,onWaiting});
    const candidate=await waitFor(()=>pending,signal,Math.min(deadline,Date.now()+PAGE_LOAD_MS));
    if(!browser.documentCurrent(doc))throw refusal('download');
    verify();
    return candidate;
  } finally {
    subscription.dispose();
  }
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
  const options={signal,deadline,onWaiting,verify};
  const visit=async url=>{
    verify();
    const doc=await browser.navigate(url.href,{tab,signal,deadline,onWaiting});
    browser.finishPageLoad(tab);
    verify();
    return doc.url;
  };

  if(!scope) {
    const hubURL=await visit(entry);
    scope=profile(hubURL);
    if(!scope) {
      if(httpsURL(hubURL)?.hostname!==HUB_HOST)throw refusal('resource_ready');
      const hub=await readReady(browser,tab,{mode:'profile'},options);
      const links=hub.urls.map(httpsURL).filter(url=>url && (profile(url.href) || url.hostname===HUB_HOST));
      if(links.length!==1)throw refusal('resource_ready');
      scope=profile(await visit(links[0]));
      if(!scope)throw refusal('resource_ready');
    }
  }
  const search=new URL(scope.path+'/search/results',scope.origin);
  search.searchParams.set('q',doi);
  const landing=httpsURL(await visit(search));
  if(landing?.origin!==scope.origin || landing.pathname!==search.pathname)throw refusal('search');
  const found=await readReady(browser,tab,{mode:'results',title},options);
  const records=found.urls.map(url=>matchRecord(url,scope)).filter(Boolean);
  if(records.length!==1)throw refusal('result');
  const record=records[0];
  const detail=matchRecord(await visit(record.url),scope);
  if(detail?.record!==record.record)throw refusal('contentReady');
  const matched=await readReady(browser,tab,{mode:'record',title,doi},options);
  if(!matched.doi || !matched.pdf)throw refusal('contentReady');
  const viewer=new URL(scope.path+'/viewer/pdf/'+record.record,scope.origin);
  const candidate=await locatePdf(browser,tab,viewer,options);
  return {outcome:'retrieved',pdf_clues:{status:'complete',landing_url:detail.url.href,
    observed_at:new Date().toISOString(),platform:'ebsco',content_type:'journal-article',
    identifiers:[],candidates:[candidate],diagnostics:[]}};
}

module.exports={readEbscoSource};
