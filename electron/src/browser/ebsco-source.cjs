'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const {checkCanceled,pause,waitFor,waitForLoad,PAGE_LOAD_MS}=require('./browser-task.cjs');

const SEARCH_HOSTS=new Set(['research.ebsco.com','discovery.ebsco.com']);
const HUB_HOST='search.ebscohost.com';
const COMMUNITY_PATH=/^\/(?:webauth\/)?community\.aspx$/i;
const PROFILE=/^\/c\/[A-Za-z0-9_.~-]+(?=\/|$)/;
const JSON_BUDGET=1024*1024;
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

function deliveryURL(value) {
  const file=httpsURL(value);
  return file?.origin==='https://content.ebscohost.com' && file.pathname==='/cds/retrieve'?file:null;
}

function isPdfRequest(details) {
  return details.method==='GET' && deliveryURL(details.url)!==null;
}

async function readRecordJSON(browser,url,document,{signal,deadline,verify}) {
  const owner=browser.operation;
  const {response,requests}=await browser.sessionEvents.fetch(url.href,{
    method:'GET',credentials:'include',redirect:'error',
    headers:{Accept:'application/json',Referer:document.url},
  },{owner,attemptId:owner.association.request_id,document,signal,deadline,validate:verify});
  const carrier=requests.at(-1)?.responses.at(-1);
  const media=response.headers.get('content-type')?.split(';',1)[0];
  if(carrier?.url!==url.href || carrier.statusCode!==response.status
    || !response.ok || !media?.toLowerCase().includes('json') || !response.body) {
    await response.body?.cancel();
    return null;
  }
  const chunks=[];
  let bytes=0;
  for await(const chunk of response.body) {
    bytes+=chunk.byteLength;
    if(bytes>JSON_BUDGET)return null;
    chunks.push(chunk);
  }
  verify();
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

async function resolveDirectPdf(browser,scope,record,document,options) {
  const {verify,signal,deadline}=options;
  const verifyRecord=()=>{
    verify();
    if(!browser.documentCurrent(document))throw refusal('contentReady');
  };
  const readOptions={signal,deadline:Math.min(deadline,Date.now()+PAGE_LOAD_MS),verify:verifyRecord};
  const details=new URL('/api/viewer/v6/details/'+record.record,scope.origin);
  details.searchParams.set('opid',scope.path.slice(3));
  details.searchParams.set('includeHbrRestrictedLinks','true');
  try {
    const rows=await readRecordJSON(browser,details,document,readOptions);
    const links=Array.isArray(rows) && rows.length===1?rows[0]?.result?.links:null;
    const pdfLinks=values=>Array.isArray(values)?[...new Set(values.flatMap(link=>
      link?.type==='pdf' && typeof link.url==='string'?[link.url]:[]))]:[];
    const preferred=pdfLinks(links?.['v2-downloadLinks']);
    const choices=preferred.length?preferred:pdfLinks(links?.downloadLinks);
    if(choices.length!==1 || !URL.canParse(choices[0],details))return null;
    const link=httpsURL(new URL(choices[0],details).href);
    if(deliveryURL(link?.href))return link;
    if(link?.origin!==scope.origin || !link.pathname.startsWith('/api/'))return null;
    const entry=await readRecordJSON(browser,link,document,readOptions);
    return typeof entry?.url==='string' && URL.canParse(entry.url,link)?deliveryURL(new URL(entry.url,link).href):null;
  } catch(error) {
    checkCanceled(signal);
    verifyRecord();
    if(Date.now()>=deadline)throw error;
    // An unavailable optional direct entry leaves the regular Viewer usable.
    return null;
  }
}

function clickProfilePostback(documentId,source,deadline) {
  if(globalThis[Symbol.for('allfold.ebsco.document')]!==documentId
    || location.href!==source || Date.now()>=deadline)return false;
  const links=[...document.querySelectorAll('form[method="post" i] a[href]')].filter(link=>{
    const form=link.closest('form');
    const action=new URL(form.action);
    const baseTarget=document.querySelector('base[target]')?.target || '';
    return /^(?:EBSCO\s*一站式检索|EBSCOhost Research Databases)$/i.test(link.textContent.trim())
      && /^javascript:\s*WebForm_DoPostBackWithOptions\(/.test(link.getAttribute('href'))
      && action.origin===location.origin && /^\/(?:webauth\/)?community\.aspx$/i.test(action.pathname)
      && ['', '_self'].includes((form.target || baseTarget).toLowerCase())
      && ['', '_self'].includes((link.target || baseTarget).toLowerCase())
      && !link.hasAttribute('download') && link.checkVisibility({checkVisibilityCSS:true});
  });
  if(links.length!==1)return false;
  links[0].click();
  return true;
}

async function openProfilePostback(browser,tab,hub,{signal,deadline,verify,onWaiting}) {
  const contents=tab.view.webContents,owner=browser.operation;
  const source=httpsURL(hub.url);
  if(source?.hostname!==HUB_HOST || !COMMUNITY_PATH.test(source.pathname))throw refusal('resource_ready');
  const validate=()=>{
    verify();
    if(!browser.documentCurrent(hub))throw refusal('resource_ready');
  };
  await browser.waitForCooldown(hub.url,{signal,deadline,validate,pageId:tab.id,step:'page_load',
    authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal,deadline,stage:'navigation'}):undefined});
  validate();
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  let submitted=null,scope=null;
  const requestGuard=browser.sessionEvents.subscribe('beforeRequest',details=>{
    if(details.webContentsId!==tab.id)return;
    if(details.resourceType==='subFrame' && details.method!=='GET')return {cancel:true};
    if(details.resourceType!=='mainFrame')return;
    if(signal?.aborted || Date.now()>=limit || !browser.ownsPage(owner,tab.id))return {cancel:true};
    verify();
    const target=httpsURL(details.url);
    if(submitted===null && details.method==='POST' && target?.origin===source.origin && COMMUNITY_PATH.test(target.pathname)) {
      submitted=details.id;
      return;
    }
    if(submitted===null || details.id!==submitted || details.method!=='GET' || !target)return {cancel:true};
  });
  const releaseGuard=()=>{requestGuard.dispose();contents.removeListener('destroyed',releaseGuard);};
  contents.once('destroyed',releaseGuard);
  try {
    browser.beginPageLoad(tab,signal,limit,{fresh:true});
    const args=[hub.documentId,hub.url,limit];
    let clicked;
    try {
      clicked=await waitFor(()=>contents.executeJavaScriptInIsolatedWorld(999,[{
        code:'('+clickProfilePostback.toString()+')(...'+JSON.stringify(args)+')',
      }]),signal,limit);
    } catch(error) {
      checkCanceled(signal);
      if(submitted===null || browser.documentCurrent(hub))throw error;
      // The qualified POST can replace the world before the click replies.
      clicked=true;
    }
    if(clicked!==true)throw refusal('resource_ready');
    const doc=await browser.waitForPage(tab,{signal,deadline:limit,documentOnly:true,onWaiting});
    verify();
    scope=submitted===null?null:profile(doc.url);
    return scope;
  } finally {
    browser.finishPageLoad(tab);
    if(scope)releaseGuard();
  }
}

function clickRecordLink(documentId,source,destination,title,deadline) {
  if(globalThis[Symbol.for('allfold.ebsco.document')]!==documentId
    || location.href!==source || Date.now()>=deadline)return false;
  const titleKey=value=>value.normalize('NFKC').replace(/[^\p{L}\p{N}]/gu,'').toLowerCase();
  const links=[...document.querySelectorAll('a[href]')].filter(link=>
    link.href===destination && titleKey(link.textContent || '')===titleKey(title)
    && link.closest('h2,.result-item-title,[class*="result-item-title"]')
    && link.checkVisibility({checkVisibilityCSS:true}) && !link.hasAttribute('download')
    && ['', '_self'].includes((link.target || document.querySelector('base[target]')?.target || '').toLowerCase()));
  if(links.length!==1)return false;
  links[0].click();
  return true;
}

async function openRecord(browser,tab,searchDocument,scope,record,title,{signal,deadline,verify,onWaiting}) {
  const contents=tab.view.webContents,owner=browser.operation;
  const validate=()=>{
    verify();
    if(!browser.documentCurrent(searchDocument))throw refusal('search');
  };
  await browser.waitForCooldown(record.url.href,{signal,deadline,validate,pageId:tab.id,step:'page_load',
    authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal,deadline,stage:'navigation'}):undefined});
  validate();
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  const landed=url=>matchRecord(url,scope)?.record===record.record;
  const inPage=(event,url,main)=>{
    if((event.isMainFrame ?? main) && landed(event.url ?? url))browser.finishPageLoad(tab);
  };
  contents.on('did-navigate-in-page',inPage);
  try {
    browser.beginPageLoad(tab,signal,limit,{fresh:true});
    const args=[searchDocument.documentId,searchDocument.url,record.url.href,title,limit];
    try {
      // Follow the site's actual link so its in-page search context can open
      // the record. A static link still performs a normal Browser navigation.
      const clicked=await waitFor(()=>contents.executeJavaScriptInIsolatedWorld(999,[{
        code:'('+clickRecordLink.toString()+')(...'+JSON.stringify(args)+')',
      }]),signal,limit);
      if(!clicked)throw refusal('result');
    } catch(error) {
      checkCanceled(signal);
      // A new Document can retire the click's execution world before replying.
      if(!landed(contents.getURL()) && !landed(tab.navigation.current?.url))throw error;
    }
    const doc=await browser.waitForPage(tab,{signal,deadline:limit,documentOnly:true,onWaiting});
    if(!landed(doc.url))throw refusal('contentReady');
    verify();
    return doc;
  } finally {
    contents.removeListener('did-navigate-in-page',inPage);
    browser.finishPageLoad(tab);
  }
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
  const viewerOnly=data.prepared_source==='ebsco-viewer';
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
  const onAccessWaiting=(waiting,diagnostic,current)=>{
    if(!waiting)return;
    // An expired institutional login cannot consume the parent's budget.
    // The user can re-prepare this Service through the normal Login path.
    if(current?.markers.login || current?.markers.mfa)throw new BrowserFailure('navigation','content_access_blocked');
    onWaiting?.(diagnostic);
  };
  const options={signal,deadline,verify};
  const visit=async (url,{documentOnly=false}={})=>{
    verify();
    const doc=await browser.navigate(url.href,{tab,signal,deadline,documentOnly,
      onWaiting:(diagnostic,current)=>onAccessWaiting(true,diagnostic,current)});
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
        if(links.length>1)throw refusal('resource_ready');
        scope=links.length ? profile((await visit(links[0])).url)
          : await openProfilePostback(browser,tab,hub,{...options,onWaiting:onAccessWaiting});
        if(!scope)throw refusal('resource_ready');
      }
    }
    const expectedRecord=viewerOnly?matchRecord(data.prepared_record,scope):null;
    if(viewerOnly && !expectedRecord)throw refusal('prepared');
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
    if(expectedRecord && record.record!==expectedRecord.record)throw refusal('result');
    const doc=await openRecord(browser,tab,found,scope,record,title,{...options,onWaiting:onAccessWaiting});
    const recordArgs={mode:'record',title,doi};
    const matchViewer=clue=>!clue.doi || clue.urls.length>0;
    let matched=await readReady(browser,tab,recordArgs,options,viewerOnly?matchViewer:undefined);
    if(!matched.doi || !browser.documentCurrent(doc))throw refusal('contentReady');
    const retrieved=candidate=>({outcome:'retrieved',pdf_clues:{status:'complete',landing_url:doc.url,
      observed_at:new Date().toISOString(),platform:'ebsco',content_type:'journal-article',
      identifiers:[],candidates:[candidate],diagnostics:[]}});
    if(!viewerOnly) {
      const direct=await resolveDirectPdf(browser,scope,record,doc,options);
      if(direct) {
        browser.reportPage('info','ebsco_direct_pdf_entry',tab);
        return retrieved({stage:'P4',rule_id:'R073',field:'ebsco_download_link',url:direct.href,referer:doc.url});
      }
      if(!matched.urls.length)matched=await readReady(browser,tab,recordArgs,options,matchViewer);
      if(!matched.doi || !browser.documentCurrent(doc))throw refusal('contentReady');
    }
    const links=matched.urls.map(httpsURL).filter(url=>url?.origin===scope.origin
      && url.pathname===scope.path+'/viewer/pdf/'+record.record);
    if(links.length!==1)throw refusal('contentReady');
    const reader=watchPdf(browser,tab,links[0],options);
    try {
      // The Viewer provides its body request once its main Document is ready.
      // Unrelated assets can still be loading when that request is observed.
      const viewer=await visit(links[0],{documentOnly:true});
      await waitFor(()=>reader.pending,signal,Math.min(deadline,Date.now()+PAGE_LOAD_MS));
      const candidate=reader.matching(viewer);
      if(!candidate)throw refusal('download');
      return retrieved(candidate);
    } finally {reader.dispose();}
  } finally {
    guard.dispose();
  }
}

module.exports={readEbscoSource};
