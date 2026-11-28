'use strict';
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('../browser/browser-errors.cjs');
const {checkCanceled,timeoutFailure,pause,waitFor,withTaskDeadline,waitForLoad}=require('../browser/browser-task.cjs');
const {ebscoEntry}=require('../browser/ebsco-source.cjs');
const {xmuLoginContext}=require('../auth/xmu-auth.cjs');
const {origin,reusableNavigationURL}=require('../browser/browser-recovery.cjs');
const {institutionPageAction,resourcePageAction,detailPageAction,imagePageAction}=require('./page-actions.cjs');

async function pageAction(browser,tab,fn,args=[],signal,allowNavigation=false,deadline=Infinity,beforeDispatch) {
  checkCanceled(signal);browser.checkTaskResources();
  if(signal)tab.taskSignal=signal;
  if(Number.isFinite(deadline))await waitForLoad(tab,signal,deadline);
  else while(tab.view.webContents.isLoadingMainFrame())await pause(signal);
  const doc=await waitFor(()=>browser.documentBinding(tab,{signal,deadline}),signal,deadline);
  checkCanceled(signal);
  if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  const result=await waitFor(()=>{
    beforeDispatch?.();
    return tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{
      code:'('+fn.toString()+')(...'+JSON.stringify(args)+')'}]);
  },signal,deadline);
  checkCanceled(signal);browser.checkTaskResources();
  if(!allowNavigation && !browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  return result;
}
async function newTaskPage(browser,signal,{managed=false,pageAttempt,deadline=Infinity,...association}={role:'auxiliary',service:false}) {
  await waitFor(()=>browser.ready,signal,deadline);
  const tab=await browser.newTaskPage({signal,deadline,managed,pageAttempt});
  browser.associatePage(tab,association);browser.beginPageLoad(tab,signal);
  return tab;
}
async function navigate(browser,tab,url,signal,progress,deadline) {
  return waitFor(()=>browser.navigate(url,{tab,signal,deadline,onWaiting:()=>progress({waiting_for_user:true})}),signal,deadline);
}
function official(url,path) {
  return origin(url)==='https://ds.carsi.edu.cn' && new URL(url).pathname===path;
}
const CARSI_PORTAL='https://ds.carsi.edu.cn/resource/resource.php';
function checkCARSISession(pages,signal) {
  checkCanceled(signal);
  for(const page of pages.filter(Boolean)) {
    const contents=page.view.webContents;
    if(!contents.isDestroyed() && official(contents.getURL(),'/login/index.html'))
      throw new BrowserFailure('authentication','carsi_session_expired');
  }
}
async function searchCARSIInstitution(browser,tab,name,signal,progress,requestDeadline) {
  const deadline=Math.min(requestDeadline,Date.now()+15000);
  const act=action=>pageAction(browser,tab,institutionPageAction,[action,name,deadline],signal,action==='select',deadline);
  let filled=false;
  while(Date.now()<deadline) {
    checkCanceled(signal);
    if(tab.view.webContents.isLoadingMainFrame())await waitForLoad(tab,signal,deadline);
    if(!official(tab.view.webContents.getURL(),'/login/index.html'))return;
    const state=await act('state');
    if(['manual','busy','pending'].includes(state.status)) {
      progress({waiting_for_user:state.status==='manual'});
      await waitFor(()=>pause(signal),signal,deadline);continue;
    }
    if(state.status!=='ready')return;
    if(!filled) {
      filled=true;
      if((await act('fill')).status!=='filled')return;
    } else {
      const result=await act('select');
      // Only a definite pre-dispatch miss permits another candidate observation.
      if(result.dispatched!==false || !['missing','pending'].includes(result.status))return;
    }
    await waitFor(()=>pause(signal),signal,deadline);
  }
}
async function openPortal(browser,tab,entry,signal,progress,deadline,first) {
  const url=entry.portal_login_url || CARSI_PORTAL;
  if(entry.portal_login_url && !official(url,'/Shibboleth.sso/Login'))throw Error('Invalid CARSI entry');
  await browser.navigate(url,{tab,signal,deadline,afterLoad:true,serviceEntry:first?'first':true});
  let selectionDocument,returnedFromLogin=false;
  while(true) {
    checkCanceled(signal);
    const pages=authenticationPages(browser,tab);
    const portal=pages.find(page=>official(page.view.webContents.getURL(),'/resource/resource.php'));
    if(portal) {
      const doc=await browser.waitForPage(portal,{signal,deadline,onWaiting:waiting=>progress({waiting_for_user:waiting})});
      if(official(doc.url,'/resource/resource.php'))return portal;
      continue;
    }
    const current=pages.at(-1);
    if(current) {
      browser.bindTaskPage(current,signal);
      const address=current.view.webContents.getURL();
      if(official(address,'/wxds') && !returnedFromLogin) {
        returnedFromLogin=true;
        await browser.navigate(CARSI_PORTAL,{tab:current,signal,deadline,afterLoad:true});
        continue;
      }
      if(official(address,'/login/index.html')) {
        const doc=await browser.documentBinding(current,{signal,deadline});
        if(selectionDocument!==doc.documentId) {
          selectionDocument=doc.documentId;
          if(entry.institution_name) {
            try {await searchCARSIInstitution(browser,current,entry.institution_name,signal,progress,deadline);}
            catch(error) {
              checkCanceled(signal);
              if(Date.now()>=deadline || error.diagnostic?.stage==='authentication' || current.view.webContents.isDestroyed())throw error;
              // The user can complete the same selector after a missed automatic match.
            }
          }
        }
      } else {
        await browser.inspectPage(current,{signal,deadline});
      }
    }
    progress({waiting_for_user:true});
    await waitFor(()=>pause(signal),signal,deadline,'authentication','request');
  }
}

function authenticationPages(browser,tab) {
  const context=tab.authContext;
  return [...browser.tabs.values()].filter(page=>page.authContext===context
    && browser.ownsPage(context.owner,page.id) && !page.view.webContents.isLoadingMainFrame());
}

function isFederatedPage(entry,url) {
  if(!entry || !URL.canParse(url))return false;
  const current=new URL(url);
  if(xmuLoginContext(entry,url))return true;
  if(URL.canParse(entry.idp_entity_id)) {
    const idp=new URL(entry.idp_entity_id);
    if(current.origin===idp.origin && current.pathname.startsWith(idp.pathname.replace(/[^/]*$/,'')))return true;
  }
  return /^\/(?:idp\/profile\/|(?:authserver|cas)\/login(?:\/|$))/i.test(current.pathname);
}

function isCarsiSelection(url) {
  return official(url,'/login/index.html');
}

function assertServiceScope(browser,data) {
  browser.accessKey(data);
  const owner=browser.operation;
  if(owner.association.service_id!==data.service_id
    || owner.association.service_scope.scope_id!==data.service_scope.scope_id)
    throw new BrowserFailure('preparation','document_changed');
}

function retainService(browser,tab,data) {
  const retained=browser.retainAccessPage(tab,data);
  return {outcome:'Opened',reason:'target_opened',target_page_id:tab.id,...(retained.ebscoEntry && {pdf_source:'ebsco'})};
}

async function searchCARSIResource(browser,tab,name,signal,requestDeadline) {
  const query=name.includes('&') ? name.slice(name.lastIndexOf('&')+1).trim() : name;
  const navigation=tab.navigation?.current,reloads=navigation?.reloads;
  let step='resource_ready',doc;
  const fail=code=>{
    const error=new BrowserFailure('preparation',code);
    error.diagnostic.step=step;
    return error;
  };
  const checkNavigation=()=>{
    tab.navigation?.check();
    if(navigation && (tab.navigation.current!==navigation || navigation.reloads!==reloads
      || navigation.pendingStart || !navigation.loaded))throw fail('document_changed');
  };
  const act=async(action,token,deadline)=>{
    checkCARSISession([tab],signal);
    checkNavigation();
    const frame=doc && browser.documentFrame(doc);
    if(!frame || tab.view.webContents.isLoadingMainFrame())throw fail('document_changed');
    const result=await waitFor(()=>frame.executeJavaScript('('+resourcePageAction.toString()+')(...'
      +JSON.stringify([action,name,query,token,deadline])+')'),signal,deadline,'preparation',step);
    checkCARSISession([tab],signal);
    if(result.code==='carsi_session_expired')throw new BrowserFailure('authentication','carsi_session_expired');
    checkNavigation();
    if(!browser.documentCurrent(doc) || tab.view.webContents.isLoadingMainFrame())throw fail('document_changed');
    if(result.status==='failed')throw fail(result.code);
    return result;
  };
  const refresh=async action=>{
    step=action==='filter'?'resource_filter':'resource_search';
    const token=randomBytes(16).toString('hex'),deadline=requestDeadline;
    try {
      await act(action,token,deadline);
      while(Date.now()<deadline) {
        const result=await act('poll',token,deadline);
        if(result.status==='complete')return result.selection;
        await pause(signal);
      }
      throw fail('refresh_unconfirmed');
    } finally {
      // Cleanup bypasses the canceled action guard, but can only reach the original document.
      const frame=doc && browser.documentFrame(doc);
      if(frame) {
        const cleanup=frame.executeJavaScript('('+resourcePageAction.toString()+')(...'
          +JSON.stringify(['cleanup',name,query,token])+')').catch(()=>{});
        await waitFor(()=>cleanup,signal,deadline,'preparation',step).catch(()=>{});
      }
    }
  };
  try {
    const deadline=requestDeadline;
    await waitForLoad(tab,signal,deadline,()=>{checkCARSISession([tab],signal);checkNavigation();});
    doc=await waitFor(()=>browser.documentBinding(tab,{signal,deadline}),signal,deadline,'preparation',step);
    let state;
    while(Date.now()<deadline) {
      state=await act('ready',undefined,deadline);
      if(state.status==='ready')break;
      await pause(signal);
    }
    if(state?.status!=='ready')throw fail('timeout');
    if(state.checked)await refresh('filter');
    return await refresh('search');
  } catch(error) {
    checkCanceled(signal);
    if(Date.now()>=requestDeadline)throw timeoutFailure('preparation','request');
    if(error.diagnostic?.stage==='authentication' || ['canceled','timeout'].includes(error.diagnostic?.code))throw error;
    checkCARSISession([tab],signal);
    tab.navigation?.check();
    const failure=error instanceof BrowserFailure && error.diagnostic.stage==='preparation' ? error
      :fail(doc && !browser.documentCurrent(doc)?'document_changed':'controls_unavailable');
    if(['resource_filter','resource_search'].includes(step)
      && ['resource_request_failed','document_changed','controls_unavailable','refresh_unconfirmed'].includes(failure.diagnostic.code)) {
      // The site's AJAX error handler may navigate only after reporting its failure.
      const until=Math.min(requestDeadline,Date.now()+1500);
      while(Date.now()<until) {
        checkCARSISession([tab],signal);
        await waitFor(()=>pause(signal,Math.min(350,until-Date.now())),signal,requestDeadline,'preparation','request');
      }
      checkCARSISession([tab],signal);
    }
    throw failure;
  }
}
function serviceLanding(entry,value) {
  if(!reusableNavigationURL(value) || isFederatedPage(entry,value))return false;
  const url=new URL(value);
  if(url.origin===origin(CARSI_PORTAL) || url.hostname.startsWith('shibboleth.')
    || /\/(?:shibboleth\.sso|shibagent\.aspx|wayfless|(?:api|oauth2?)\/authorize|saml2?\/(?:sso|login)|(?:action\/)?ssostart|(?:login|signon)(?:\.aspx)?)(?:\/|$)/i.test(url.pathname))
    return false;
  if(entry.wayfless_url) {
    const initiator=new URL(entry.wayfless_url);
    if(initiator.origin===url.origin && initiator.pathname===url.pathname
      && [...url.searchParams.keys()].some(key=>/^(?:auth|eid|entity|entityid|idp|partneridpid|state|targeturl)$/i.test(key)))return false;
  }
  const host=url.hostname.replace(/^www\./,'');
  return entry.landing_hosts.some(expected=>expected.replace(/^www\./,'')===host)
    || entry.landing_hosts.includes('search.ebscohost.com') && !!ebscoEntry(value);
}

async function waitForServiceLanding(browser,tab,entry,{signal,progress,deadline}) {
  while(true) {
    checkCanceled(signal);
    const context=tab.authContext;
    const pages=[...browser.tabs.values()].filter(page=>{
      if(page.authContext!==context || !browser.ownsPage(context.owner,page.id))return false;
      for(let opener=page;opener;opener=opener.opener)if(opener===tab)return true;
      return false;
    });
    for(const page of pages.reverse()) {
      browser.bindTaskPage(page,signal);
      const observed=await browser.inspectPage(page,{signal,deadline});
      if(observed.loading)continue;
      const doc=observed.doc;
      if(!observed.waiting && doc.status>=200 && doc.status<300) {
        if(isFederatedPage(entry,doc.url))continue;
        if(serviceLanding(entry,doc.url))return page;
        if(pages.length===1 && origin(doc.url))throw new BrowserFailure('preparation','service_entry_unavailable');
      }
    }
    progress({waiting_for_user:true});
    await waitFor(()=>pause(signal),signal,deadline,'preparation','request');
  }
}

async function prepareServiceWithinDeadline(browser,data,{signal,progress,first=false,deadline}) {
  assertServiceScope(browser,data);
  const entry=data.service_entry;
  if(!entry || entry.unavailable_reason)throw new BrowserFailure('preparation','service_unavailable');
  await browser.replaceAccess(data);
  const open=async (wayfless,firstEntry)=>{
    const attempt=browser.pageAttempt(signal);
    const options={signal:attempt.signal,progress,deadline};
    const closeTemporary=keep=>Promise.all([...browser.tabs.values()]
      .filter(page=>page!==keep && page.pageAttempt===attempt && page.resourceOwner===attempt.owner)
      .map(page=>browser.closePage(page)));
    let tab,context;
    try {
      await browser.reserveTaskPages(3,options);
      tab=await newTaskPage(browser,attempt.signal,{role:'service-resource',managed:true,pageAttempt:attempt,deadline});
      context=browser.beginAuthentication(tab,attempt.signal,entry,{preparing:true});
      options.signal=context.signal;
      if(wayfless) {
        await browser.navigate(entry.wayfless_url,{tab,signal:options.signal,deadline,afterLoad:true,serviceEntry:firstEntry?'first':true});
        tab=await waitForServiceLanding(browser,tab,entry,options);
        browser.associatePage(tab,{role:'service-target'});
        progress({waiting_for_user:false});
        browser.finishPageLoad(tab);
        return retainService(browser,tab,data);
      }
      const portal=await openPortal(browser,tab,entry,options.signal,progress,deadline,firstEntry);
      await closeTemporary(portal);
      const result=await visitCARSIResource(browser,portal,{name:entry.resource_name,access_url:entry.access_url},
        {...options,attempt},deadline);
      if(result.outcome==='Opened')return retainService(browser,browser.tabs.get(result.target_page_id),data);
      return result;
    } catch(error) {
      // Only an explicit entry refusal or an observed wrong landing can fall back.
      // A fresh Portal entry never reloads a callback or reuses form data.
      const diagnostic=error.diagnostic;
      if(wayfless && !options.signal.aborted && (diagnostic?.code==='service_entry_unavailable'
        || !context?.actionDispatched && diagnostic?.code==='http_error' && [404,410].includes(diagnostic.status)
          && tab && origin(tab.view.webContents.getURL())===origin(entry.wayfless_url))) {
        await browser.retirePageAttempt(attempt);
        browser.pageBudget.releaseUnused(browser.operation);
        return null;
      }
      throw error;
    } finally {
      browser.endAuthentication(context);
      await closeTemporary();
      browser.pageBudget.releaseUnused(attempt.owner);
    }
  };
  if(entry.wayfless_url) {
    const result=await open(true,first);
    if(result)return result;
    first=false;
  }
  return open(false,first);
}

async function prepareService(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'preparation',(bounded,deadline)=>
    prepareServiceWithinDeadline(browser,data,{signal:bounded,progress,deadline,first:data.first_entry===true}));
}

async function visitManualService(browser,data,{signal,progress}) {
  assertServiceScope(browser,data);
  return withTaskDeadline(signal,'preparation',async(bounded,deadline)=>{
    await browser.replaceAccess(data);
    await browser.reserveTaskPages(3,{signal:bounded,deadline});
    const tab=await newTaskPage(browser,bounded,{role:'service-target',managed:true,deadline});
    const document=await navigate(browser,tab,data.access_url,bounded,progress,deadline);
    if(!browser.documentCurrent(document))throw new BrowserFailure('navigation','document_changed');
    return retainService(browser,tab,data);
  });
}

async function recoverService(browser,data,{signal,deadline,progress},previous) {
  const entry=data.service_entry,owner=browser.operation;
  if(!entry || entry.unavailable_reason)throw new BrowserFailure('preparation','service_unavailable');
  assertServiceScope(browser,data);
  const key=browser.accessKey(data);
  while(true) {
    checkCanceled(signal);
    if(Date.now()>=deadline)throw timeoutFailure('authentication','request');
    const pending=browser.serviceRecoveries.get(key);
    if(pending) {
      try {return await waitFor(()=>pending.settlement,signal,deadline,'authentication','request');}
      catch(error) {
        checkCanceled(signal);
        const parentEnded=pending.signal.aborted || Date.now()>=pending.deadline;
        if(!parentEnded || !['canceled','timeout'].includes(error.diagnostic?.code))throw error;
        continue;
      }
    }
    const current=browser.serviceContext(data);
    if(current && current!==previous)return current;
    const recovery={signal,deadline,settlement:(async()=>{
      await owner.validateRecovery?.({signal,deadline,stage:'authentication'});
      while(browser.serviceContext(data)?.pins.size)
        await waitFor(()=>pause(signal),signal,deadline,'authentication','request');
      const result=await prepareServiceWithinDeadline(browser,data,{signal,deadline,progress});
      if(result.outcome!=='Opened')throw new BrowserFailure('authentication','service_authentication_required');
      return browser.serviceContext(data);
    })()};
    browser.serviceRecoveries.set(key,recovery);
    // Keep the shared result through actual Prepare settlement.
    try {return await recovery.settlement;}
    finally {browser.serviceRecoveries.delete(key);}
  }
}

async function visitCARSIResource(browser,portal,data,{signal,progress,attempt},requestDeadline) {
  portal.taskSignal=signal;
  browser.bindTaskPage(portal,signal);
  let detail,detailURL,visitDeadline;
  checkCARSISession([portal],signal);
  browser.beginPageLoad(portal,signal,requestDeadline);
  await waitForLoad(portal,signal,requestDeadline,()=>{checkCARSISession([portal],signal);portal.navigation?.check();});
  await waitFor(()=>browser.checkAuthentication(portal),signal,requestDeadline);
  checkCARSISession([portal],signal);
  if(!official(portal.view.webContents.getURL(),'/resource/resource.php')) {
    const error=new BrowserFailure('preparation','controls_unavailable');
    error.diagnostic.step='resource_ready';throw error;
  }
  progress({waiting_for_user:false});
  try {
    let selected;
    try {selected=await searchCARSIResource(browser,portal,data.name,signal,requestDeadline);}
    finally {browser.finishPageLoad(portal);}
    checkCARSISession([portal,detail],signal);
    if(selected.status==='missing')return {outcome:'Needs attention',reason:'resource_not_found',
      diagnostic:{stage:'preparation',step:'resource_search',code:'resource_not_found'}};
    if(selected.status==='ambiguous')return {outcome:'Needs attention',reason:'ambiguous_resource',
      diagnostic:{stage:'preparation',step:'resource_search',code:'ambiguous_resource'}};
    if(selected.status!=='selected')throw new BrowserFailure('preparation','unverified_official_page');
    if(!official(selected.url,'/resource/resourceDetail.php'))throw Error('Invalid CARSI resource');
    detailURL=selected.url;
    detail=await newTaskPage(browser,signal,{role:'service-resource',source:portal,managed:portal.managed,pageAttempt:attempt,deadline:requestDeadline});
    detail.authContext=portal.authContext;
    await navigate(browser,detail,detailURL,signal,progress,requestDeadline);
    checkCARSISession([portal,detail],signal);
    visitDeadline=Math.min(requestDeadline,Date.now()+10000);
    while(true) {
      checkCARSISession([portal,detail],signal);
      const state=await pageAction(browser,detail,detailPageAction,['check',visitDeadline],signal,false,visitDeadline);
      if(state.status==='ready')break;
      if(state.status!=='pending')throw new BrowserFailure('preparation','unverified_official_page');
      await waitFor(()=>pause(signal),signal,visitDeadline,'preparation','visit_target');
    }
    checkCARSISession([portal,detail],signal);
  } catch(error) {
    if(['canceled','timeout'].includes(error.diagnostic?.code) || error.diagnostic?.stage==='authentication')throw error;
    checkCARSISession([portal,detail],signal);
    if(error.diagnostic?.stage==='preparation' && error.diagnostic.step) {
      // A failed observed operation must not enter login recovery and replay its click.
      const reason={refresh_unconfirmed:'timeout',controls_unavailable:'unverified_official_page',
        resource_request_failed:'navigation_failed',document_changed:'navigation_failed'}[error.diagnostic.code]
        || error.diagnostic.code;
      return {outcome:'Needs attention',reason,diagnostic:error.diagnostic};
    }
    if(error.diagnostic?.stage==='preparation')
      return {outcome:'Needs attention',reason:error.diagnostic.code,diagnostic:error.diagnostic};
    throw error;
  }
  // Bind the click to its exact detail document and to one main-frame target.
  const wc=detail.view.webContents,owner=browser.operation;
  const sourceDocument=await waitFor(()=>browser.documentBinding(detail,{signal,deadline:visitDeadline}),signal,visitDeadline,'preparation','visit_target');
  const verifySource=()=>{
    checkCARSISession([portal,detail],signal);
    if(!browser.documentCurrent(sourceDocument) || wc.isLoadingMainFrame())
      throw new BrowserFailure('preparation','document_changed');
  };
  const targetOrigin=browser.carsiVisitOrigins.get(detailURL) || origin(data.access_url);
  await browser.waitForCooldown([targetOrigin,CARSI_PORTAL],{signal,deadline:requestDeadline,validate:verifySource,
    stage:'preparation',step:'visit_target',pageId:detail.id});
  verifySource();
  await browser.reserveChildPage({signal,deadline:Math.min(requestDeadline,Date.now()+10000)});
  verifySource();
  visitDeadline=Math.min(requestDeadline,Date.now()+10000);
  let target=null,settleClick;
  const confirmed=new Promise(resolve=>{settleClick=resolve;});
  const popupListeners=new Map();
  const ambiguous=()=>{
    attempt.ambiguous=true;
    target?.navigation.blockReplay();
    settleClick(false);
  };
  const observe=(tab,url)=>{
    if(!attempt.visitStarted || signal.aborted || !browser.ownsPage(owner,tab.id) || !origin(url))return;
    if(tab===detail && popupListeners.size || target && target!==tab) {
      ambiguous();return;
    }
    if(target || attempt.ambiguous)return;
    target=tab;
    target.refreshGuard=async options=>{
      if(!await waitFor(()=>confirmed,options.signal,options.deadline,'preparation','visit_target')
        || attempt.ambiguous)
        throw new BrowserFailure('preparation','unverified_official_page');
    };
    browser.runInOperation(owner,()=>browser.beginPageLoad(tab,signal,requestDeadline,{
      replayable:true,replayFollowingGets:true,
    }));
  };
  const observesTarget=(tab,event,url,inPlace,main)=>{
    if((event.isMainFrame ?? main) && !(event.isSameDocument ?? inPlace))observe(tab,event.url ?? url);
  };
  const ownNav=(event,url,inPlace,main)=>observesTarget(detail,event,url,inPlace,main);
  const popup=(_event,tab)=>{
    if(!attempt.visitStarted || signal.aborted || tab.opener!==detail || !browser.ownsPage(owner,tab.id))return;
    if(target===detail || popupListeners.size)ambiguous();
    const listener=(event,url,inPlace,main)=>observesTarget(tab,event,url,inPlace,main);
    tab.view.webContents.on('did-start-navigation',listener);
    popupListeners.set(tab.view.webContents,listener);
  };
  wc.on('did-start-navigation',ownNav);browser.events.on('tab-created',popup);
  try {
    browser.beginPageLoad(detail,signal,requestDeadline,{fresh:true});
    let clickReturned=false;
    try {
      const clicked=await pageAction(browser,detail,detailPageAction,['visit',visitDeadline],signal,true,visitDeadline,()=>{
        verifySource();
        attempt.visitStarted=true;
      });
      if(clicked?.status!=='visited_click')return {outcome:'Needs attention',reason:'unverified_official_page'};
      clickReturned=true;
    } catch(error) {
      checkCanceled(signal);
      if(error.diagnostic?.code==='timeout' || !target || attempt.ambiguous || browser.documentCurrent(sourceDocument))throw error;
      // A lost click acknowledgement can use already observed success, without replay.
    }
    while(!target && !attempt.ambiguous)await waitFor(()=>pause(signal),signal,visitDeadline,'preparation','visit_target');
    if(attempt.ambiguous)return {outcome:'Needs attention',reason:'unverified_official_page'};
    if(!clickReturned)target.navigation.blockReplay();
    settleClick(clickReturned);
    target.managed=true;
    browser.associatePage(target,{role:'service-target',source:target===detail?portal:detail});
    browser.bindTaskPage(target,signal);
    let landed;
    try {
      landed=await waitForServiceLanding(browser,target,portal.authContext.entry,{signal,deadline:requestDeadline,progress});
    } catch(error) {
      if(error.diagnostic?.code==='service_entry_unavailable')
        return {outcome:'Needs attention',reason:'unverified_official_page'};
      throw error;
    }
    if(attempt.ambiguous || (landed===detail && landed.view.webContents.getURL()===sourceDocument.url))
      return {outcome:'Needs attention',reason:'unverified_official_page'};
    browser.associatePage(landed,{role:'service-target',source:target===detail?portal:detail});
    browser.finishPageLoad(landed);
    progress({waiting_for_user:false});
    if(browser.carsiVisitOrigins.size>=128)browser.carsiVisitOrigins.delete(browser.carsiVisitOrigins.keys().next().value);
    browser.carsiVisitOrigins.set(detailURL,origin(landed.view.webContents.getURL()));
    return {outcome:'Opened',target_page_id:landed.id};
  } finally {
    settleClick(false);
    if(target)delete target.refreshGuard;
    browser.finishPageLoad(detail);
    wc.removeListener('did-start-navigation',ownNav);browser.events.removeListener('tab-created',popup);
    for(const [contents,listener] of popupListeners)contents.removeListener('did-start-navigation',listener);
  }
}

async function searchJournalCover(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'navigation',(bounded,deadline)=>searchJournalCoverWithinDeadline(browser,data,{signal:bounded,progress},deadline));
}
async function searchJournalCoverWithinDeadline(browser,data,{signal,progress},requestDeadline) {
  if(typeof data.name!=='string' || !data.name.trim())throw Error('Saved Journal name required');
  const tab=await newTaskPage(browser,signal,{role:'auxiliary',service:false,deadline:requestDeadline});
  await navigate(browser,tab,'https://www.google.com/search?udm=2&q='+encodeURIComponent(data.name+' journal'),signal,progress,requestDeadline);
  let deadline=Date.now()+30000;
  while(true) {
    checkCanceled(signal);
    const observed=await browser.inspectPage(tab,{signal,deadline:requestDeadline,onWaiting:waiting=>progress({waiting_for_user:waiting}),extraWaiting:doc=>new URL(doc.url).pathname.startsWith('/sorry')});
    if(observed.loading){await waitFor(()=>pause(signal),signal,requestDeadline);continue;}
    const doc=observed.doc,url=new URL(doc.url);
    if(!/^(?:[a-z0-9-]+\.)*google\.(?:[a-z]{2,3}|(?:com|co)\.[a-z]{2})$/.test(url.hostname))
      throw Error('Cover search left Google');
    const waiting=observed.waiting;
    if(waiting) {
      progress({waiting_for_user:true});deadline=Math.min(requestDeadline,Date.now()+30000);await waitFor(()=>pause(signal),signal,requestDeadline);continue;
    }
    progress({waiting_for_user:false});
    if(url.pathname!=='/search' && url.pathname!=='/imgres')throw Error('Unverified image search');
    browser.enterBusiness();
    const result=await pageAction(browser,tab,imagePageAction,[],signal,false,Math.min(deadline,requestDeadline));
    if(result.ready) {
      if(!result.source_url)return {source_url:null};
      const source=new URL(result.source_url);
      if(!['http:','https:'].includes(source.protocol) || source.username || source.password
        || /^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|\[)/i.test(source.hostname)
        || /\.(local|localhost)$/i.test(source.hostname))throw Error('Unsafe image target');
      // Reuse Chromium and its identity; public cover downloads omit credentials as before.
      const {response}=await browser.sessionEvents.fetch(source.href,{redirect:'follow',credentials:'omit'},
        {owner:browser.operation,attemptId:randomBytes(16).toString('hex'),document:doc,signal,
          deadline:Math.min(requestDeadline,Date.now()+20000),validate:()=>{
            if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
          }});
      if(!response.ok)throw Error('Image download failed');
      checkCanceled(signal);
      const reader=response.body.getReader();let size=0;const chunks=[];
      try {while(true){const {done,value}=await reader.read();checkCanceled(signal);if(done)break;size+=value.length;
        if(size>5*1024*1024)throw Error('Image too large');chunks.push(value);}}
      finally {await reader.cancel();}
      return {source_url:source.href,image_base64:Buffer.concat(chunks).toString('base64')};
    }
    if(Date.now()>=Math.min(deadline,requestDeadline))throw new BrowserFailure('navigation','timeout');
    await pause(signal);
  }
}
module.exports={prepareService,recoverService,isFederatedPage,isCarsiSelection,visitManualService,searchJournalCover,newTaskPage,navigate,pageAction,pause,checkCanceled,
  waitFor,withTaskDeadline,timeoutFailure};
