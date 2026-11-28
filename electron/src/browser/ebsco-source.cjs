'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const {checkCanceled,pause,waitFor,PAGE_LOAD_MS}=require('./browser-task.cjs');
const {reusableNavigationURL}=require('./browser-recovery.cjs');

const SEARCH_HOSTS=new Set(['research.ebsco.com','discovery.ebsco.com']);
const HUB_HOST='search.ebscohost.com';
const COMMUNITY_PATH=/^\/(?:webauth\/)?community\.aspx$/i;
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

function ebscoEntry(value) {
  const url=httpsURL(value);
  return url && (profile(value) || url.hostname===HUB_HOST && COMMUNITY_PATH.test(url.pathname))?url:null;
}

function matchRecord(value,scope) {
  const url=httpsURL(value);
  const prefix=scope.path+'/search/details/';
  if(url?.origin!==scope.origin || !url.pathname.startsWith(prefix))return null;
  const record=url.pathname.slice(prefix.length);
  return /^[A-Za-z0-9_.~-]+$/.test(record)?{url,record}:null;
}

async function readRecordJSON(browser,url,document,{signal,deadline,verify}) {
  const owner=browser.operation;
  const {response,requests}=await browser.sessionEvents.fetch(url.href,{
    method:'GET',credentials:'include',redirect:'error',
    headers:{Accept:'application/json',Referer:document.url},
  },{owner,attemptId:owner.association.request_id,document,signal,deadline,validate:verify});
  const carrier=requests.at(-1)?.responses.at(-1);
  if(carrier?.url!==url.href || carrier.statusCode!==response.status || !response.ok || !response.body) {
    await response.body?.cancel();
    return null;
  }
  const result=await response.json();
  verify();
  return result;
}

async function resolveDirectPdf(browser,scope,record,document,options) {
  const {verify,signal,deadline,doi,fromSearch}=options;
  const details=new URL('/api/viewer/v6/details/'+record.record,scope.origin);
  details.searchParams.set('opid',scope.path.slice(3));
  details.searchParams.set('includeHbrRestrictedLinks','true');
  try {
    // An optional lookup must leave the normal page route a chance to run.
    const lookup={...options,deadline:Math.min(deadline,Date.now()+PAGE_LOAD_MS)};
    const value=await readRecordJSON(browser,details,document,lookup);
    const rows=(Array.isArray(value)?value:[value]).map(row=>row?.result)
      .filter(result=>result && typeof result==='object');
    const identified=rows.filter(row=>row.recordId===record.record);
    const applicable=identified.length?identified:rows.filter(row=>row.recordId===undefined);
    if(applicable.some(row=>{
      const reported=validDOI(row.doi);
      return reported ? reported!==doi : fromSearch && !!row.links;
    }))return [];
    const pdfLinks=values=>Array.isArray(values)?values.flatMap(link=>{
      if(link?.type!=='pdf' || typeof link.url!=='string' || !URL.canParse(link.url,details))return [];
      const url=httpsURL(new URL(link.url,details).href);
      return url?[url.href]:[];
    }):[];
    const choices=applicable.filter(row=>row.links).map(row=>[...new Set([
      ...pdfLinks(row.links['v2-downloadLinks']),...pdfLinks(row.links.downloadLinks),
    ])]);
    if(!identified.length && new Set(choices.map(urls=>JSON.stringify([...urls].sort()))).size>1) {
      if(fromSearch)return [];
      throw refusal('result');
    }
    return [...new Set(choices.flat())];
  } catch(error) {
    checkCanceled(signal);
    verify();
    if(Date.now()>=deadline || error instanceof BrowserFailure && error.diagnostic.step==='result')throw error;
    // An unavailable optional direct entry leaves the regular Viewer usable.
    return [];
  }
}

function clickCommunityEntry(documentId,source,destination,deadline) {
  if(globalThis[Symbol.for('allfold.ebsco.document')]!==documentId
    || location.href!==source || Date.now()>=deadline)return false;
  const links=[...document.querySelectorAll(destination?'a[href]':'form[method="post" i] a[href]')].filter(link=>{
    const baseTarget=document.querySelector('base[target]')?.target || '';
    if(!['','_self'].includes((link.target || baseTarget).toLowerCase()) || link.hasAttribute('download')
      || !link.checkVisibility({checkVisibilityCSS:true}))return false;
    if(destination)return link.href===destination;
    const form=link.closest('form'),action=new URL(form.action);
    return /^javascript:\s*WebForm_DoPostBackWithOptions\(/.test(link.getAttribute('href'))
      && action.origin===location.origin && /^\/(?:webauth\/)?community\.aspx$/i.test(action.pathname)
      && ['', '_self'].includes((form.target || baseTarget).toLowerCase());
  });
  const actions=[...new Map(links.map(link=>[link.href,link])).values()];
  // A Community WebForm can hide several distinct profile destinations behind
  // the same POST endpoint. Use the journal-search label only to disambiguate
  // already qualified native controls when their actual targets are opaque.
  const choices=destination || actions.length<=1?actions:actions.filter(link=>
    /^EBSCO(?:host)?\s*(?:一站式检索|Research Databases|Search Databases)$/i.test(link.textContent.trim()));
  if(choices.length!==1)return false;
  choices[0].click();
  return true;
}

async function openCommunityEntry(browser,tab,hub,destination,{signal,deadline,verify,onWaiting}) {
  const contents=tab.view.webContents,owner=browser.operation;
  const source=httpsURL(hub.url);
  if(source?.hostname!==HUB_HOST || !COMMUNITY_PATH.test(source.pathname))throw refusal('resource_ready');
  const validate=()=>{
    verify();
    if(!browser.ownsPage(owner,tab.id))throw refusal('resource_ready');
  };
  await browser.waitForCooldown(hub.url,{signal,deadline,validate,pageId:tab.id,step:'page_load',
    authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal,deadline,stage:'navigation'}):undefined});
  validate();
  let submitted=null;
  const requestGuard=browser.sessionEvents.subscribe('beforeRequest',details=>{
    if(details.webContentsId!==tab.id)return;
    if(details.resourceType==='subFrame' && details.method!=='GET')return {cancel:true};
    if(details.resourceType!=='mainFrame')return;
    if(signal?.aborted || Date.now()>=deadline || !browser.ownsPage(owner,tab.id))return {cancel:true};
    verify();
    const target=httpsURL(details.url);
    const selected=destination?details.method==='GET' && target?.href===destination
      :details.method==='POST' && target?.origin===source.origin && COMMUNITY_PATH.test(target.pathname);
    if(submitted===null && selected) {
      submitted=details.id;
      return;
    }
    if(submitted===null || details.id!==submitted || details.method!=='GET' || !target)return {cancel:true};
  });
  const releaseGuard=()=>{requestGuard.dispose();contents.removeListener('destroyed',releaseGuard);};
  contents.once('destroyed',releaseGuard);
  try {
    browser.beginPageLoad(tab,signal,deadline,{fresh:true});
    const args=[hub.documentId,hub.url,destination,deadline];
    let clicked;
    try {
      clicked=await waitFor(()=>contents.executeJavaScriptInIsolatedWorld(999,[{
        code:'('+clickCommunityEntry.toString()+')(...'+JSON.stringify(args)+')',
      }]),signal,deadline);
    } catch(error) {
      checkCanceled(signal);
      if(submitted===null)throw error;
      // The qualified POST can replace the world before the click replies.
      clicked=true;
    }
    if(clicked!==true && submitted===null)return null;
    const doc=await browser.waitForPage(tab,{signal,deadline,documentOnly:true,onWaiting});
    verify();
    const scope=submitted===null?null:profile(doc.url);
    // A replacement Community selector cannot renew an observed form POST.
    if(!scope && !destination && submitted!==null)throw refusal('resource_ready');
    return scope;
  } finally {
    browser.finishPageLoad(tab);
    releaseGuard();
  }
}

function clickRecordLink(documentId,source,destination,deadline) {
  if(globalThis[Symbol.for('allfold.ebsco.document')]!==documentId
    || location.href!==source || Date.now()>=deadline)return false;
  const main=document.querySelector('main,[role="main"]') || document.body;
  const link=[...main.querySelectorAll('a[href]')].find(link=>
    link.href===destination && link.closest('h2,.result-item-title,[class*="result-item-title"]')
    && link.checkVisibility({checkVisibilityCSS:true}) && !link.hasAttribute('download')
    && ['', '_self'].includes((link.target || document.querySelector('base[target]')?.target || '').toLowerCase()));
  if(!link)return false;
  link.click();
  return true;
}

async function openRecord(browser,tab,searchDocument,scope,record,{signal,deadline,verify,onWaiting}) {
  const contents=tab.view.webContents,owner=browser.operation;
  await browser.waitForCooldown(record.url.href,{signal,deadline,validate:verify,pageId:tab.id,step:'page_load',
    authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal,deadline,stage:'navigation'}):undefined});
  verify();
  const landed=url=>matchRecord(url,scope)?.record===record.record;
  const inPage=(event,url,main)=>{
    if((event.isMainFrame ?? main) && landed(event.url ?? url))browser.finishPageLoad(tab);
  };
  contents.on('did-navigate-in-page',inPage);
  browser.beginPageLoad(tab,signal,deadline,{fresh:true});
  try {
    const args=[searchDocument.documentId,searchDocument.url,record.url.href,deadline];
    try {
      // A real click retains the site's client-side search and record state.
      const clicked=await waitFor(()=>contents.executeJavaScriptInIsolatedWorld(999,[{
        code:'('+clickRecordLink.toString()+')(...'+JSON.stringify(args)+')',
      }]),signal,deadline);
      if(!clicked)return null;
    } catch(error) {
      checkCanceled(signal);
      if(!landed(contents.getURL()) && !landed(tab.navigation.current?.url))return null;
    }
    const doc=await browser.waitForPage(tab,{signal,deadline,documentOnly:true,onWaiting});
    if(!landed(doc.url))throw refusal('contentReady');
    verify();
    return doc;
  } finally {
    contents.removeListener('did-navigate-in-page',inPage);
    browser.finishPageLoad(tab);
  }
}

async function readReady(browser,tab,args,{signal,deadline,verify},settled=()=>true) {
  for(;;) {
    verify();
    try {
      const clue=await browser.readDocument(tab,'ebsco',{args,signal,deadline});
      verify();
      if(clue.ready && settled(clue))return clue;
    } catch(error) {
      if(error.diagnostic?.code!=='document_changed')throw error;
    }
    await waitFor(()=>pause(signal),signal,deadline);
  }
}

function viewerLinks(values,scope,record) {
  return values.map(httpsURL).filter(url=>url?.origin===scope.origin
    && url.pathname.startsWith(scope.path+'/viewer/') && url.pathname.split('/').at(-1)===record.record);
}

function findRecord(found,scope,verifiedRecord) {
  const scoped=values=>{
    const records=new Map();
    for(const value of values) {
      const record=matchRecord(value,scope);
      if(record && !records.has(record.record))records.set(record.record,record);
    }
    return records;
  };
  const records=scoped(found.urls);
  if(verifiedRecord) {
    const record=records.get(verifiedRecord);
    if(!record)throw refusal('result');
    return {record,confirmed:true};
  }
  const confirmed=scoped(found.exact),titles=scoped(found.titled);
  const choices=confirmed.size?confirmed:titles.size?titles:records;
  if(choices.size!==1)throw refusal('result');
  return {record:choices.values().next().value,confirmed:confirmed.size===1};
}

function watchPdf(browser,tab,viewer,{signal,deadline,verify}) {
  const owner=browser.operation,contents=tab.view.webContents;
  let resolve;
  const pending=new Promise(done=>{resolve=done;}),requests=new Map();
  const headers=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId!==tab.id || details.method!=='GET'
      || !['xhr','subFrame','other','mainFrame'].includes(details.resourceType) || !httpsURL(details.url)
      || !browser.ownsPage(owner,tab.id) || signal?.aborted || Date.now()>=deadline)return;
    const top=httpsURL(contents.getURL()),root=details.frame?.top;
    if(top?.origin!==viewer.origin || top.pathname!==viewer.pathname || !root
      || (details.initiatorOrigin || new URL(details.frame.url).origin)!==viewer.origin
      || root.frameToken!==contents.mainFrame.frameToken || root.processId!==contents.mainFrame.processId)return;
    verify();
    const referer=Object.entries(details.requestHeaders || {}).find(([name])=>name.toLowerCase()==='referer')?.[1];
    requests.set(details.id,{stage:'P4',rule_id:'R073',url:details.url,referer:httpsURL(referer)?.href ?? null});
  },{signal});
  const response=browser.sessionEvents.subscribe('headersReceived',details=>{
    const request=requests.get(details.id);
    requests.delete(details.id);
    if(details.webContentsId!==tab.id || request?.url!==details.url || details.statusCode<200
      || details.statusCode>=300 || !browser.ownsPage(owner,tab.id) || signal?.aborted || Date.now()>=deadline)return;
    verify();
    const fields=Object.entries(details.responseHeaders || {});
    const header=name=>fields.find(([key])=>key.toLowerCase()===name)?.[1]?.[0] ?? '';
    const mime=header('content-type').split(';',1)[0].trim().toLowerCase();
    const attached=/^attachment[; ]/i.test(header('content-disposition'));
    if(mime!=='application/pdf' && !(attached && mime==='application/octet-stream'))return;
    resolve(request);
    return {cancel:true};
  },{signal});
  const terminal=['completed','errorOccurred'].map(event=>browser.sessionEvents.subscribe(event,
    details=>{requests.delete(details.id);},{signal}));
  return {pending,dispose:()=>{for(const listener of [headers,response,...terminal])listener.dispose();}};
}

async function readEbscoSource(browser,data,context,{signal,deadline,onWaiting,verify,withAccess}) {
  const doi=validDOI(data.identity?.doi),title=data.target_title;
  const viewerOnly=data.prepared_source==='ebsco-viewer';
  const entry=context.ebscoEntry;
  if(!doi || typeof title!=='string' || !entry)throw refusal('prepared');
  checkCanceled(signal);
  const openTab=async()=>{
    const page=await browser.newTaskPage({signal,deadline,managed:true});
    browser.associatePage(page,{role:'pdf-reader'});
    const guard=browser.sessionEvents.subscribe('beforeRequest',details=>{
      if(details.webContentsId!==page.id || !['mainFrame','subFrame'].includes(details.resourceType))return;
      verify();
      if(signal?.aborted || Date.now()>=deadline || !httpsURL(details.url))return {cancel:true};
    });
    page.view.webContents.once('destroyed',guard.dispose);
    return page;
  };
  let tab=await openTab();
  const onAccessWaiting=(waiting,diagnostic,current)=>{
    if(!waiting)return;
    if(!data.service_entry && (current?.markers.login || current?.markers.mfa))throw new BrowserFailure('navigation','content_access_blocked');
    onWaiting?.(diagnostic);
  };
  const options={signal,deadline,verify,onWaiting:onAccessWaiting,doi};
  const navigate=async (url,{referer,watch}={})=>{
    verify();
    if(browser.tabs.get(tab.id)!==tab)tab=await openTab();
    const observation=watch?.(tab);
    try {
      const doc=await browser.navigateServiceTarget(data,url.href,{tab,signal,deadline,documentOnly:true,
        httpReferrer:referer?{url:referer,policy:'strict-origin-when-cross-origin'}:undefined,
        onWaiting:(diagnostic,current)=>onAccessWaiting(true,diagnostic,current)});
      browser.finishPageLoad(tab);
      verify();
      return observation ? await observation.read(doc) : doc;
    } finally {observation?.dispose();}
  };
  const visit=(url,settings)=>reusableNavigationURL(url.href)
    ? withAccess(current=>{context=current;return navigate(url,settings);})
    : navigate(url,settings);
  let scope=profile(context.tab.view.webContents.getURL()) || context.ebscoProfile || profile(entry.href);
  async function enterProfile() {
    const hubURL=(await visit(entry)).url;
    const landed=profile(hubURL);
    if(landed)return landed;
    if(httpsURL(hubURL)?.hostname!==HUB_HOST)throw refusal('resource_ready');
    for(;;) {
      const hub=await readReady(browser,tab,{mode:'profile'},options);
      const profiles=new Map();
      for(const url of hub.urls) {
        const link=profile(url);
        if(link && !profiles.has(link.origin+link.path))profiles.set(link.origin+link.path,url);
      }
      if(profiles.size>1)throw refusal('resource_ready');
      const chosen=await openCommunityEntry(browser,tab,hub,profiles.values().next().value ?? null,options);
      if(chosen)return chosen;
      const current=tab.view.webContents.getURL();
      if(current===hub.url && tab.documentGeneration===hub.navigationGeneration)throw refusal('resource_ready');
    }
  }
  const remembered=!!scope;
  if(!scope)scope=await enterProfile();
  if(!scope)throw refusal('resource_ready');
  let record=viewerOnly?matchRecord(data.prepared_record,scope):null;
  if(viewerOnly && !record)throw refusal('prepared');
  const directResult=(recordURL,referer,links,viewer)=>{
    browser.reportPage('info','ebsco_direct_pdf_entry',tab);
    return retrieved(recordURL,links.map(url=>({stage:'P4',rule_id:'R073',field:'ebsco_download_link',url,referer})),viewer);
  };
  const readRecord=async (confirmed,settled)=>{
    const clue=await readReady(browser,tab,{mode:'record',title,doi,confirmed},options,settled);
    if(!clue.doi || matchRecord(clue.url,scope)?.record!==record.record)throw refusal('contentReady');
    return clue;
  };

  if(viewerOnly) {
    const viewer=viewerLinks([data.prepared_viewer],scope,record)[0];
    if(viewer) {
      browser.reportPage('info','ebsco_viewer_reused',tab);
      return await fromViewer(viewer,record.url.href);
    }
    // A Viewer that was not observed may require the site's results navigation.
  }

  const expected=record;
  const search=()=>{const url=new URL(scope.path+'/search/results',scope.origin);url.searchParams.set('q',doi);return url;};
  let searchURL=search();
  browser.reportPage('info',remembered?'ebsco_profile_reused':'ebsco_profile_ready',tab);
  try {await visit(searchURL);}
  catch(error) {
    checkCanceled(signal);
    verify();
    if(!remembered || !['content_access_blocked','http_error'].includes(error.diagnostic?.code)
      || profile(entry.href))throw error;
    context.ebscoProfile=null;
    scope=await enterProfile();
    if(!scope)throw refusal('resource_ready');
    browser.reportPage('info','ebsco_profile_ready',tab);
    searchURL=search();await visit(searchURL);
  }
  const verifiedRecord=expected && matchRecord(expected.url.href,scope);
  const args={mode:'results',title,doi};
  let doc,confirmed;
  for(;;) {
    const found=await readReady(browser,tab,args,options);
    const location=httpsURL(found.url);
    if(location?.origin!==scope.origin || location.pathname!==searchURL.pathname
      || location.searchParams.get('q')!==doi)throw refusal('search');
    const lookupFromSearch=!record;
    ({record,confirmed}=findRecord(found,scope,verifiedRecord?.record));
    if(expected && record.record!==expected.record)throw refusal('result');
    if(lookupFromSearch) {
      // The selected record's licensed details can confirm the Paper directly
      // from the search page. A missing match or link leaves page access usable.
      const direct=await resolveDirectPdf(browser,scope,record,found,{...options,fromSearch:true});
      if(direct.length) {
        context.ebscoProfile=scope;
        browser.reportPage('info','ebsco_record_ready',tab);
        return directResult(record.url.href,found.url,direct);
      }
    }
    doc=await openRecord(browser,tab,found,scope,record,options);
    if(doc)break;
    await waitFor(()=>pause(signal),signal,deadline);
  }
  const matched=await readRecord(confirmed);
  context.ebscoProfile=scope;
  browser.reportPage('info','ebsco_record_ready',tab);
  const recordURL=matched.url;
  const viewer=viewerLinks(matched.urls,scope,record)[0];
  if(!viewerOnly) {
    const direct=await resolveDirectPdf(browser,scope,record,{...doc,url:recordURL},options);
    if(direct.length)return directResult(recordURL,recordURL,direct,viewer);
  }
  const accessSettled=clue=>!clue.doi || clue.urls.length>0 || clue.accessEmpty;
  const currentViewer=viewer || viewerLinks((await readRecord(true,accessSettled)).urls,scope,record)[0];
  if(!currentViewer)return retrieved(recordURL,[]);
  return await fromViewer(currentViewer,recordURL);

  async function fromViewer(viewer,recordURL) {
    return visit(viewer,{referer:recordURL,watch:page=>{
      const reader=watchPdf(browser,page,viewer,options);
      return {dispose:reader.dispose,async read(landed) {
        const url=httpsURL(landed.url);
        if(url?.origin!==viewer.origin || url.pathname!==viewer.pathname)throw refusal('contentReady');
        // A refused request can be followed by another eligible Viewer response.
        const candidate=await waitFor(()=>reader.pending,signal,Math.min(deadline,Date.now()+PAGE_LOAD_MS));
        return retrieved(recordURL,[candidate]);
      }};
    }});
  }
}

function retrieved(landing,candidates,viewer) {
  return {outcome:'retrieved',...(viewer && {ebsco_viewer_url:viewer.href}),pdf_clues:{status:'complete',landing_url:landing,
    observed_at:new Date().toISOString(),platform:'ebsco',content_type:'journal-article',identifiers:[],candidates,diagnostics:[]}};
}

module.exports={readEbscoSource,ebscoEntry};
