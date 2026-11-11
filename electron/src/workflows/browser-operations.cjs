'use strict';
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('../browser/browser-errors.cjs');
const {checkCanceled,timeoutFailure,pause,waitFor,withTaskDeadline,waitForLoad}=require('../browser/browser-task.cjs');
const {PAGE_RECOVERY_MS,origin,reportRecovery,recoveryStop,pageRecoveryDetails}=require('../browser/browser-recovery.cjs');
const {institutionPageAction,resourcePageAction,detailPageAction,imagePageAction}=require('./page-actions.cjs');

async function pageAction(browser,tab,fn,args=[],signal,allowNavigation=false,deadline=Infinity,beforeDispatch) {
  checkCanceled(signal);
  if(signal)tab.taskSignal=signal;
  if(Number.isFinite(deadline))await waitForLoad(tab,signal,deadline);
  else while(tab.view.webContents.isLoadingMainFrame())await pause(signal);
  const doc=await waitFor(()=>browser.snapshot(tab),signal,deadline);
  checkCanceled(signal);
  if(!browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  const result=await waitFor(()=>{
    beforeDispatch?.();
    return tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{
      code:'('+fn.toString()+')(...'+JSON.stringify(args)+')'}]);
  },signal,deadline);
  checkCanceled(signal);
  if(!allowNavigation && !browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
  return result;
}
async function newTaskPage(browser,signal,{managed=false,pageAttempt,deadline=Infinity,...association}={role:'auxiliary',service:false}) {
  await waitFor(()=>browser.ready,signal,deadline);
  const tab=browser.createTab({present:false,managed,pageAttempt});
  browser.associatePage(tab,association);browser.beginPageLoad(tab,signal);
  return tab;
}
async function navigate(browser,tab,url,signal,progress,deadline) {
  return waitFor(()=>browser.navigate(url,{tab,signal,deadline,onWaiting:()=>progress({waiting_for_user:true})}),signal,deadline);
}
function official(url,path) {
  return origin(url)==='https://ds.carsi.edu.cn' && new URL(url).pathname===path;
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
  browser.beginAuthentication(tab,signal);
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

function requirePreparationKey(data) {
  if(!data.service_id || !data.service_scope?.scope_id || typeof data.preparation_key!=='string'
    || !/^[a-f0-9]{64}$/.test(data.preparation_key))
    throw new BrowserFailure('preparation','document_changed');
}

async function prepareLoggedInService(browser,data,{signal,progress}) {
  requirePreparationKey(data);
  const owner=browser.operation,association=owner.association;
  const {service_id,preparation_key,portal_page_id,workflow_id,task_id}=data;
  const scopeFields=['scope_id','config_revision','user_state_revision'];
  const scope=Object.fromEntries(scopeFields.map(key=>[key,data.service_scope[key]]));
  return withTaskDeadline(signal,'preparation',async(bounded,requestDeadline)=>{
    const entry=browser.tabs.get(portal_page_id);
    const frame=entry && !entry.view.webContents.isDestroyed()?entry.view.webContents.mainFrame:null;
    const binding=frame && {pageId:entry.id,processId:frame.processId,frameToken:frame.frameToken};
    const verifyPortal=()=>{
      checkCanceled(bounded);
      const source=browser.pageAssociation(portal_page_id);
      if(browser.operation!==owner || !browser.operations.has(owner) || owner.association!==association
        || association.service_id!==service_id || data.service_id!==service_id
        || association.workflow_id!==workflow_id || data.workflow_id!==workflow_id
        || association.task_id!==task_id || data.task_id!==task_id
        || data.preparation_key!==preparation_key || data.portal_page_id!==portal_page_id
        || !scopeFields.every(key=>scope[key] && scope[key]===association.service_scope?.[key]
          && scope[key]===data.service_scope?.[key]))
        throw new BrowserFailure('preparation','document_changed');
      if(!entry?.carsiSessionReady || source?.role!=='carsi-portal' || source.workflow_id!==workflow_id
        || !scopeFields.every(key=>scope[key]===source.service_scope?.[key])
        || !binding || !browser.documentFrame(binding,null) || entry.view.webContents.isLoadingMainFrame()
        || !official(entry.view.webContents.getURL(),'/resource/resource.php'))
        throw new BrowserFailure('authentication','carsi_session_expired');
    };
    const verifyRecovery=async(signal,deadline)=>{
      verifyPortal();
      await waitFor(()=>owner.validateRecovery?.({signal,deadline,stage:'preparation'}),signal,deadline,'preparation','request');
      verifyPortal();
    };
    let deadline=requestDeadline,firstFailure,sourcePageId,priorTargetOrigin,authentication;
    const record=(event,error,fields={})=>reportRecovery(owner.recordRecovery,event,pageRecoveryDetails(error,'resource_reentry',{
      stage:'preparation',source_page_id:sourcePageId,attempt:1,attempt_limit:1,...fields}));
    for(let index=0;index<2;index++) {
      const attempt=browser.pageAttempt(bounded);
      const {signal}=attempt;
      try {
        verifyPortal();
        if(index) {
          await browser.waitForCooldown([CARSI_PORTAL,priorTargetOrigin],{signal,deadline,validate:verifyPortal,stage:'preparation',
            step:'visit_target',pageId:sourcePageId,authorize:()=>verifyRecovery(signal,deadline)});
          verifyPortal();
        }
        const portal=await newTaskPage(browser,signal,{role:'service-resource',source:entry,managed:true,pageAttempt:attempt,deadline});
        portal.institutionOrigins=new Set(entry.institutionOrigins || []);
        const attemptProgress=value=>{
          if(value.waiting_for_user)attempt.manual=true;
          progress(value);
        };
        await navigate(browser,portal,CARSI_PORTAL,signal,attemptProgress,deadline);
        if(authentication)portal.authContext=authentication;
        else authentication=browser.beginAuthentication(portal,bounded,{institution:false});
        const result=await visitCARSIResource(browser,portal,data,{signal,progress:attemptProgress,attempt,priorTargetOrigin,
          verifyVisit:waited=>index || waited?verifyRecovery(signal,deadline):verifyPortal()},deadline);
        if(index) {
          const opened=result.outcome==='Opened';
          record(opened?'recovery_succeeded':'recovery_exhausted',opened?firstFailure:
            {diagnostic:result.diagnostic || {code:'unverified_official_page'}},
          {page_id:result.evidence?.target_page_id ?? browser.taskTab?.id,
            ...(opened?{dispatch_outcome:'confirmed'}:{recovery_stop:'failed'})});
        }
        return result;
      } catch(error) {
        const failed=browser.taskTab;
        if(index)record('recovery_exhausted',error,{page_id:failed?.id,recovery_stop:recoveryStop(error,bounded)});
        if(index || bounded.aborted || !browser.ownsPage(owner,failed?.id)
          || failed.pageAttempt!==attempt || attempt.visitStarted && !attempt.visitConfirmed
          || attempt.ambiguous || attempt.manual || authentication?.actionDispatched)throw error;
        // An exhausted target can start a new Visit through CARSI regardless of the failed request's method.
        const exhaustedTarget=attempt.visitConfirmed && browser.pageAssociation(failed.id)?.role==='service-target'
          && failed.navigation.exhaustedRefreshes(error);
        if(!exhaustedTarget && (!error.rebuildPage || failed.navigation.current?.chain.unsafeRequest))throw error;
        checkCARSISession([failed],bounded);
        verifyPortal();
        if(Date.now()>=deadline)throw timeoutFailure('preparation','request');
        deadline=Math.min(deadline,Date.now()+PAGE_RECOVERY_MS);
        firstFailure=error;sourcePageId=failed.id;priorTargetOrigin=attempt.targetOrigin;
        record('recovery_scheduled',error,{page_id:sourcePageId,dispatch_outcome:'not_dispatched'});
        browser.retirePageAttempt(attempt);
      }
    }
  });
}

async function visitManualService(browser,data,{signal,progress}) {
  requirePreparationKey(data);
  return withTaskDeadline(signal,'preparation',async(bounded,deadline)=>{
    const tab=await newTaskPage(browser,bounded,{role:'service-target',managed:true});
    const document=await navigate(browser,tab,data.access_url,bounded,progress,deadline);
    if(!browser.documentCurrent(document))throw new BrowserFailure('navigation','document_changed');
    tab.preparationKey=data.preparation_key;
    return {outcome:'Opened',reason:'target_opened',evidence:{visit_action_observed:true,
      navigation_observed:true,target_page_id:tab.id}};
  });
}

async function visitCARSIResource(browser,portal,data,{signal,progress,attempt,priorTargetOrigin,verifyVisit},requestDeadline) {
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
  const sourceDocument=await waitFor(()=>browser.snapshot(detail),signal,visitDeadline,'preparation','visit_target');
  const verifySource=()=>{
    checkCARSISession([portal,detail],signal);
    if(!browser.documentCurrent(sourceDocument) || wc.isLoadingMainFrame())
      throw new BrowserFailure('preparation','document_changed');
  };
  const targetOrigin=priorTargetOrigin || browser.carsiVisitOrigins.get(detailURL) || origin(data.access_url);
  await browser.waitForCooldown([targetOrigin,CARSI_PORTAL],{signal,deadline:requestDeadline,validate:verifySource,
    stage:'preparation',step:'visit_target',pageId:detail.id,authorize:verifyVisit});
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
        || attempt.ambiguous || attempt.manual)
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
    attempt.visitConfirmed=clickReturned;
    if(!clickReturned)target.navigation.blockReplay();
    settleClick(clickReturned);
    target.managed=true;
    browser.associatePage(target,{role:'service-target',source:target===detail?portal:detail});
    browser.bindTaskPage(target,signal);
    const doc=await browser.waitForPage(target,{signal,deadline:requestDeadline,
      onWaiting:waiting=>progress({waiting_for_user:waiting})});
    checkCARSISession([portal,detail,target],signal);
    if(attempt.ambiguous || !browser.documentCurrent(doc) || (target===detail && doc.url===sourceDocument.url))
      return {outcome:'Needs attention',reason:'unverified_official_page'};
    progress({waiting_for_user:false});
    target.carsiOwned=true;
    target.preparationKey=data.preparation_key;
    target.institutionOrigins=new Set(portal.authContext.origins);
    portal.institutionOrigins=new Set(portal.authContext.origins);
    return {outcome:'Opened',reason:'target_opened',evidence:{visit_action_observed:true,
      navigation_observed:true,source_page_id:detail.id,target_page_id:target.id}};
  } finally {
    settleClick(false);
    if(target)delete target.refreshGuard;
    browser.finishPageLoad(detail);
    if(attempt.visitConfirmed && !attempt.ambiguous) {
      const targetOrigin=origin(target?.navigation.current?.url);
      if(targetOrigin && targetOrigin!==origin(CARSI_PORTAL) && !portal.authContext.origins.has(targetOrigin)) {
        attempt.targetOrigin=targetOrigin;
        if(browser.carsiVisitOrigins.size>=128)browser.carsiVisitOrigins.delete(browser.carsiVisitOrigins.keys().next().value);
        browser.carsiVisitOrigins.set(detailURL,targetOrigin);
      }
    }
    wc.removeListener('did-start-navigation',ownNav);browser.events.removeListener('tab-created',popup);
    for(const [contents,listener] of popupListeners)contents.removeListener('did-start-navigation',listener);
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
module.exports={loginInstitution,prepareLoggedInService,visitManualService,searchJournalCover,newTaskPage,navigate,pageAction,pause,checkCanceled,
  waitFor,withTaskDeadline,timeoutFailure};
