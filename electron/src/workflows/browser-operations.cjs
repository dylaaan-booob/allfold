'use strict';
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('../browser/browser-errors.cjs');
const {checkCanceled,timeoutFailure,pause,waitFor,withTaskDeadline,waitForLoad}=require('../browser/browser-task.cjs');
const {institutionPageAction,resourcePageAction,detailPageAction,imagePageAction}=require('./page-actions.cjs');

async function pageAction(browser,tab,fn,args=[],signal,allowNavigation=false,deadline=Infinity) {
  checkCanceled(signal);
  if(signal)tab.taskSignal=signal;
  if(Number.isFinite(deadline))await waitForLoad(tab,signal,deadline);
  else while(tab.view.webContents.isLoadingMainFrame())await pause(signal);
  const doc=await waitFor(()=>browser.snapshot(tab),signal,deadline);
  checkCanceled(signal);
  if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  const result=await waitFor(()=>tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{
    code:'('+fn.toString()+')(...'+JSON.stringify(args)+')'}]),signal,deadline);
  checkCanceled(signal);
  if(!allowNavigation && !browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  return result;
}
async function newTaskPage(browser,signal,{managed=false,...association}={role:'auxiliary',service:false}) {
  await waitFor(()=>browser.ready,signal);
  const tab=browser.createTab({present:false,managed});
  browser.associatePage(tab,association);browser.beginPageLoad(tab,signal);
  return tab;
}
async function navigate(browser,tab,url,signal,progress,deadline) {
  return waitFor(()=>browser.navigate(url,{tab,signal,deadline,onWaiting:()=>progress({waiting_for_user:true})}),signal,deadline);
}
function official(url,path) {
  if(!url)return false;
  const u=new URL(url);
  return u.origin==='https://ds.carsi.edu.cn' && !u.username && !u.password && u.pathname===path;
}
const CARSI_SEARCH='https://ds.carsi.edu.cn/login/index.html';
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
async function loginCARSI(browser,tab,data,signal,progress,deadline) {
  checkCanceled(signal);
  const contents=tab.view.webContents;
  if(!tab.authContext?.active)browser.beginAuthentication(tab,signal);
  else tab.authContext.institution=true;
  let selectionDocument,issue,reportedIssue;
  if(data.use_shibboleth && data.login_url) {
    try {await navigate(browser,tab,data.login_url,signal,progress,deadline);}
    catch(error) {
      checkCanceled(signal);
      if(contents.isDestroyed() || error.diagnostic?.stage==='authentication' || error.diagnostic?.code==='timeout')throw error;
      await navigate(browser,tab,CARSI_SEARCH,signal,progress,deadline);
    }
  } else if(!official(contents.getURL(),'/login/index.html')) {
    await navigate(browser,tab,CARSI_SEARCH,signal,progress,deadline);
  }
  while(true) {
    checkCanceled(signal);
    await waitFor(()=>browser.checkAuthentication(tab),signal,deadline);
    if(contents.isLoadingMainFrame()){await waitForLoad(tab,signal,deadline);continue;}
    const portal=[...browser.tabs.values()].find(page=>page.authContext===tab.authContext
      && !page.view.webContents.isDestroyed() && !page.view.webContents.isLoadingMainFrame()
      && official(page.view.webContents.getURL(),'/resource/resource.php'));
    if(portal){browser.authenticationPortal(portal);progress({waiting_for_user:false});return portal;}
    const url=contents.getURL();
    if(official(url,'/wxds')){await navigate(browser,tab,CARSI_PORTAL,signal,progress,deadline);continue;}
    const selection=official(url,'/login/index.html');
    if(selection) {
      const doc=await waitFor(()=>browser.snapshot(tab),signal,deadline);
      const key=JSON.stringify([doc.pageId,doc.processId,doc.frameToken]);
      if(browser.documentCurrent(doc) && selectionDocument!==key) {
        // Reserve the native document before a selection can submit or destroy its context.
        selectionDocument=key;
        issue=data.institution_name?'institution_search_failed':'institution_name_required';
        if(data.institution_name) {
          try {await searchCARSIInstitution(browser,tab,data.institution_name,signal,progress,deadline);}
          catch(error) {
            checkCanceled(signal);
            if(contents.isDestroyed() || error.diagnostic?.stage==='authentication'
              || error.diagnostic?.code==='timeout' && Date.now()>=deadline)throw error;
            // A bounded selection miss stays manual; an unknown submission is never replayed.
          }
        }
        continue;
      }
    }
    const hint=selection && issue?issue:'';
    if(reportedIssue!==hint){reportedIssue=hint;progress({waiting_for_user:true,...(hint?{login_issue:hint}:{})});}
    await waitFor(()=>pause(signal),signal,deadline);
  }
}
async function searchCARSIResource(browser,tab,name,signal,requestDeadline) {
  const query=name.includes('&') ? name.slice(name.lastIndexOf('&')+1).trim() : name;
  const navigation=tab.navigation?.current,reloads=navigation?.reloads;
  let step='resource_ready',doc,operationDeadline=Math.min(requestDeadline,Date.now()+15000);
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
    const token=randomBytes(16).toString('hex'),deadline=Math.min(requestDeadline,Date.now()+15000);
    operationDeadline=deadline;
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
    const deadline=operationDeadline;
    await waitForLoad(tab,signal,deadline,()=>{checkCARSISession([tab],signal);checkNavigation();});
    doc=await waitFor(()=>browser.snapshot(tab),signal,deadline,'preparation',step);
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
    // Let B observe the existing recovery before classifying a stale document as a resource failure.
    if(navigation && tab.navigation.current===navigation && navigation.reloads>reloads)throw error;
    const failure=error instanceof BrowserFailure && error.diagnostic.stage==='preparation' ? error
      :fail(doc && !browser.documentCurrent(doc)?'document_changed':'controls_unavailable');
    if(['resource_filter','resource_search'].includes(step)
      && ['resource_request_failed','document_changed','controls_unavailable','refresh_unconfirmed'].includes(failure.diagnostic.code)) {
      // The site's AJAX error handler may navigate only after reporting its failure.
      const until=Math.min(operationDeadline,requestDeadline,Date.now()+1500);
      while(Date.now()<until) {
        checkCARSISession([tab],signal);
        await waitFor(()=>pause(signal,Math.min(350,until-Date.now())),signal,requestDeadline,'preparation','request');
      }
      checkCARSISession([tab],signal);
    }
    throw failure;
  }
}
async function loginInstitution(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'authentication',async(bounded,deadline)=>{
    if(data.login_url && !official(data.login_url,'/Shibboleth.sso/Login'))
      throw Error('Invalid CARSI entry');
    const entry=await newTaskPage(browser,bounded,{role:'carsi-portal',service:false,managed:true});
    const portal=await loginCARSI(browser,entry,data,bounded,progress,deadline);
    portal.managed=true;
    browser.associatePage(portal,{role:'carsi-portal',service:false});
    portal.institutionOrigins=new Set(portal.authContext?.origins || []);
    portal.carsiSessionReady=true;
    return {outcome:'Opened',portal_page_id:portal.id};
  });
}

async function prepareLoggedInService(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'preparation',async(bounded,deadline)=>{
    const entry=browser.tabs.get(data.portal_page_id);
    const source=browser.pageAssociation(data.portal_page_id);
    const matchesScope=['scope_id','config_revision','user_state_revision'].every(key=>
      data.service_scope?.[key] && data.service_scope[key]===source?.service_scope?.[key]);
    if(!entry?.carsiSessionReady || source?.role!=='carsi-portal' || source.workflow_id!==data.workflow_id
        || !matchesScope || !official(entry.view.webContents.getURL(),'/resource/resource.php'))
      throw new BrowserFailure('authentication','carsi_session_expired');
    const portal=await newTaskPage(browser,bounded,{role:'service-resource',source:entry,managed:true});
    portal.institutionOrigins=new Set(entry.institutionOrigins || []);
    await navigate(browser,portal,CARSI_PORTAL,bounded,progress,deadline);
    return visitCARSIResource(browser,portal,data,{signal:bounded,progress},deadline,{allowCredentials:false});
  });
}

async function visitManualService(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'preparation',async(bounded,deadline)=>{
    const tab=await newTaskPage(browser,bounded,{role:'service-target',managed:true});
    const document=await navigate(browser,tab,data.access_url,bounded,progress,deadline);
    if(!browser.documentCurrent(document))throw new BrowserFailure('navigation','document_changed');
    return {outcome:'Opened',reason:'target_opened',evidence:{visit_action_observed:true,
      navigation_observed:true,target_page_id:tab.id}};
  });
}

async function prepareService(browser,data,{signal,progress}) {
  return withTaskDeadline(signal,'preparation',(bounded,deadline)=>
    prepareServiceWithinDeadline(browser,data,{signal:bounded,progress},deadline));
}
async function prepareServiceWithinDeadline(browser,data,{signal,progress},requestDeadline) {
  if(!data.institution_name && !(data.use_shibboleth && data.login_url))
    return {outcome:'Needs attention',reason:'manual_action_required'};
  // Python constructs this URL exclusively from the saved, validated Institution.
  if(data.login_url && !official(data.login_url,'/Shibboleth.sso/Login'))throw Error('Invalid CARSI entry');
  const portal=await ensureCARSIPortal(browser,data,{signal,progress},requestDeadline);
  return visitCARSIResource(browser,portal,data,{signal,progress},requestDeadline);
}
// A runs once per task. The existing cache also prevents re-login after a failed attempt.
async function ensureCARSIPortal(browser,data,{signal,progress},deadline) {
  if(browser.carsiPortal?.task===data.task_id) {
    const portal=browser.tabs.get(browser.carsiPortal.id);
    if(!portal || portal.view.webContents.isDestroyed())throw new BrowserFailure('navigation','page_closed');
    browser.associatePage(portal,{role:'carsi-portal',service:false});
    checkCARSISession([portal],signal);
    return portal;
  }
  browser.carsiPortal={task:data.task_id,id:null};
  let portal=await newTaskPage(browser,signal,{role:'carsi-portal',service:false});
  browser.carsiPortal={task:data.task_id,id:portal.id};
  try {portal=await loginCARSI(browser,portal,data,signal,progress,deadline);}
  catch(error) {browser.carsiPortal={task:data.task_id,id:null};throw error;}
  browser.carsiPortal={task:data.task_id,id:portal.id};
  browser.associatePage(portal,{role:'carsi-portal',service:false});
  portal.institutionOrigins=new Set(portal.authContext?.origins || []);
  return portal;
}
// B performs one Service operation without re-entering institution initialization.
async function visitCARSIResource(browser,portal,data,{signal,progress},requestDeadline,{allowCredentials=true}={}) {
  if(!portal.authContext?.active || portal.authContext.signal!==signal)
    browser.beginAuthentication(portal,signal,{institution:false,allowCredentials});
  portal.taskSignal=signal;
  browser.bindTaskPage(portal,signal);
  let detail,visitDeadline;
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
    try {
      while(true) {
        const navigation=portal.navigation?.current;
        if(navigation && (navigation.reloads>0 || !navigation.loaded || portal.view.webContents.isLoadingMainFrame())) {
          await waitForLoad(portal,signal,requestDeadline,()=>{
            checkCARSISession([portal],signal);portal.navigation.check();
          });
          checkCARSISession([portal],signal);
          if(!official(portal.view.webContents.getURL(),'/resource/resource.php'))
            throw new BrowserFailure('preparation','document_changed');
          await browser.waitForPage(portal,{signal,deadline:requestDeadline,finish:false,
            onWaiting:waiting=>{
              checkCARSISession([portal],signal);
              if(!official(portal.view.webContents.getURL(),'/resource/resource.php'))
                throw new BrowserFailure('preparation','document_changed');
              progress({waiting_for_user:waiting});
            }});
          checkCARSISession([portal],signal);
          portal.navigation.check();
          if(portal.navigation.current!==navigation || navigation.signal!==signal
            || !official(portal.view.webContents.getURL(),'/resource/resource.php'))
            throw new BrowserFailure('preparation','document_changed');
        }
        const generation=navigation?.generation,reloads=navigation?.reloads,owner=navigation?.owner;
        try {
          selected=await searchCARSIResource(browser,portal,data.name,signal,requestDeadline);
          checkCARSISession([portal],signal);
          portal.navigation?.check();
          if(navigation && (portal.navigation.current!==navigation || navigation.reloads!==reloads)
            || !official(portal.view.webContents.getURL(),'/resource/resource.php')) {
            const failure=new BrowserFailure('preparation','document_changed');
            failure.diagnostic.step='resource_search';throw failure;
          }
          break;
        } catch(error) {
          checkCanceled(signal);
          if(Date.now()>=requestDeadline)throw timeoutFailure('preparation','request');
          if(error.diagnostic?.stage==='authentication')throw error;
          checkCARSISession([portal],signal);
          portal.navigation?.check();
          const current=portal.navigation?.current;
          if(!navigation || current!==navigation || current.generation!==generation
            || current.owner!==owner || current.signal!==signal || !current.active || !current.automatic || !current.enabled
            || current.reloads<=reloads)throw error;
          // Only a confirmed native recovery permits a new read-only query in the replacement document.
        }
      }
    } finally {browser.finishPageLoad(portal);}
    checkCARSISession([portal,detail],signal);
    if(selected.status==='missing')return {outcome:'Needs attention',reason:'resource_not_found',
      diagnostic:{stage:'preparation',step:'resource_search',code:'resource_not_found'}};
    if(selected.status==='ambiguous')return {outcome:'Needs attention',reason:'ambiguous_resource',
      diagnostic:{stage:'preparation',step:'resource_search',code:'ambiguous_resource'}};
    if(selected.status!=='selected')throw new BrowserFailure('preparation','unverified_official_page');
    if(!official(selected.url,'/resource/resourceDetail.php'))throw Error('Invalid CARSI resource');
    detail=await newTaskPage(browser,signal,{role:'service-resource',source:portal,managed:portal.managed});
    detail.authContext=portal.authContext;
    await navigate(browser,detail,selected.url,signal,progress,requestDeadline);
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
  // Bind the native click and its first attributable main-frame navigation.
  const wc=detail.view.webContents,owner=browser.operation;
  let target=null,ambiguous=false;
  const observe=tab=>{
    if(signal.aborted || !browser.ownsPage(owner,tab.id))return;
    if(target) {
      if(target!==tab){ambiguous=true;browser.finishPageLoad(target);}
      return;
    }
    browser.runInOperation(owner,()=>browser.beginPageLoad(tab,signal,requestDeadline));
    target=tab;
  };
  const observesTarget=(tab,event,inPlace,main)=>{
    if((event.isMainFrame ?? main) && !(event.isSameDocument ?? inPlace))observe(tab);
  };
  const ownNav=(event,_url,inPlace,main)=>observesTarget(detail,event,inPlace,main);
  const popupListeners=[];
  const popup=(_event,tab)=>{
    if(tab.opener!==detail)return;
    const listener=(event,_url,inPlace,main)=>observesTarget(tab,event,inPlace,main);
    tab.view.webContents.on('did-start-navigation',listener);popupListeners.push([tab.view.webContents,listener]);
  };
  wc.on('did-start-navigation',ownNav);browser.events.on('tab-created',popup);
  try {
    browser.beginPageLoad(detail,signal,requestDeadline,{fresh:true});
    const sourceDocument=await waitFor(()=>browser.snapshot(detail),signal,visitDeadline,'preparation','visit_target');
    try {
      const clicked=await pageAction(browser,detail,detailPageAction,['visit',visitDeadline],signal,true,visitDeadline);
      if(clicked?.status!=='visited_click')return {outcome:'Needs attention',reason:'unverified_official_page'};
    } catch(error) {
      checkCanceled(signal);
      if(error.diagnostic?.code==='timeout' || !target || ambiguous || browser.documentCurrent(sourceDocument))throw error;
      // The one click may destroy its execution context after navigation was already observed.
    }
    while(!target)await waitFor(()=>pause(signal),signal,visitDeadline,'preparation','visit_target');
    if(ambiguous)return {outcome:'Needs attention',reason:'unverified_official_page'};
    target.managed=true;
    browser.associatePage(target,{role:'service-target',source:target===detail?portal:detail});
    browser.bindTaskPage(target,signal);
    await browser.waitForPage(target,{signal,deadline:requestDeadline,
      onWaiting:waiting=>progress({waiting_for_user:waiting})});
    if(ambiguous)return {outcome:'Needs attention',reason:'unverified_official_page'};
    progress({waiting_for_user:false});
    target.carsiOwned=true;
    target.institutionOrigins=new Set(portal.authContext.origins);
    portal.institutionOrigins=new Set(portal.authContext.origins);
    return {outcome:'Opened',reason:'target_opened',evidence:{visit_action_observed:true,
      navigation_observed:true,source_page_id:detail.id,target_page_id:target.id}};
  } finally {
    wc.removeListener('did-start-navigation',ownNav);browser.events.removeListener('tab-created',popup);
    for(const [contents,listener] of popupListeners)if(!contents.isDestroyed())contents.removeListener('did-start-navigation',listener);
  }
}

async function searchJournalCover(browser,data,{signal,progress}) {
  if(typeof data.name!=='string' || !data.name.trim())throw Error('Saved Journal name required');
  const tab=await newTaskPage(browser,signal);
  await navigate(browser,tab,'https://www.google.com/search?udm=2&q='+encodeURIComponent(data.name+' journal'),signal,progress);
  let deadline=Date.now()+30000;
  while(true) {
    checkCanceled(signal);
    const observed=await browser.inspectPage(tab,{signal,onWaiting:waiting=>progress({waiting_for_user:waiting}),extraWaiting:doc=>new URL(doc.url).pathname.startsWith('/sorry')});
    if(observed.loading){await pause(signal);continue;}
    const doc=observed.doc,url=new URL(doc.url);
    if(!/^(?:[a-z0-9-]+\.)*google\.(?:[a-z]{2,3}|(?:com|co)\.[a-z]{2})$/.test(url.hostname))
      throw Error('Cover search left Google');
    const waiting=observed.waiting;
    if(waiting) {
      progress({waiting_for_user:true});deadline=Date.now()+30000;await pause(signal);continue;
    }
    progress({waiting_for_user:false});
    if(url.pathname!=='/search' && url.pathname!=='/imgres')throw Error('Unverified image search');
    browser.enterBusiness();
    const result=await pageAction(browser,tab,imagePageAction,[],signal);
    if(result.ready) {
      if(!result.source_url)return {source_url:null};
      const source=new URL(result.source_url);
      if(!['http:','https:'].includes(source.protocol) || source.username || source.password
        || /^(localhost|127\.|0\.|10\.|192\.168\.|169\.254\.|\[)/i.test(source.hostname)
        || /\.(local|localhost)$/i.test(source.hostname))throw Error('Unsafe image target');
      // Reuse Chromium and its identity; public cover downloads omit credentials as before.
      const response=await browser.partition.fetch(source.href,{redirect:'follow',credentials:'omit',
        signal:AbortSignal.any([signal,AbortSignal.timeout(20000)])});
      if(!response.ok)throw Error('Image download failed');
      checkCanceled(signal);
      const reader=response.body.getReader();let size=0;const chunks=[];
      try {while(true){const {done,value}=await reader.read();checkCanceled(signal);if(done)break;size+=value.length;
        if(size>5*1024*1024)throw Error('Image too large');chunks.push(value);}}
      finally {await reader.cancel();}
      return {source_url:source.href,image_base64:Buffer.concat(chunks).toString('base64')};
    }
    if(Date.now()>deadline)throw new BrowserFailure('navigation','timeout');
    await pause(signal);
  }
}
module.exports={loginInstitution,prepareLoggedInService,visitManualService,prepareService,searchJournalCover,newTaskPage,navigate,pageAction,pause,checkCanceled,
  waitFor,withTaskDeadline,timeoutFailure};
