'use strict';
const {app, WebContentsView, webFrameMain, Menu, clipboard, ipcMain} = require('electron');
const {BrowserPresentation}=require('./browser-presentation.cjs');
const {BrowserFailure}=require('./browser-errors.cjs');
const {configureBrowserIdentity} = require('./browser-identity.cjs');
const {validDOI,articleURL}=require('./article-identity.cjs');
const {DocumentRuntime}=require('./document-runtime.cjs');
const {BodyActionRuntime}=require('./body-action-runtime.cjs');
const {qualifyReader,publicClueURL,matchingScienceDirectAssetGet}=require('./pdf-clues.cjs');
const {readEbscoSource,ebscoEntry}=require('./ebsco-source.cjs');
const {EventEmitter}=require('node:events');
const {AsyncLocalStorage}=require('node:async_hooks');
const {randomBytes}=require('node:crypto');
const {log,withLogContext,associationLogContext}=require('../shared/logging.cjs');
const {institutionAuthPage}=require('../auth/institution-auth.cjs');
const {xmuLoginContext}=require('../auth/xmu-auth.cjs');
const {ServiceEntryStarts}=require('./service-entry-starts.cjs');
const {casErrorCode}=require('../auth/cas-credentials.cjs');
const {waitFor,pause,checkCanceled,timeoutFailure,TASK_DEADLINE_MS}=require('./browser-task.cjs');
const {NavigationRecovery,inspectPage,waitForPage}=require('./browser-navigation.cjs');
const {reportRecovery,recoveryStop,pageRecoveryDetails,origin,loadFailure,reusableNavigationURL}=require('./browser-recovery.cjs');
const {sharedSessionEvents}=require('./session-events.cjs');
const {sharedBrowserSession}=require('./browser-session.cjs');
const {operationAssociation}=require('./page-association.cjs');
const {PageBudget}=require('./page-budget.cjs');
const {recoverService,isFederatedPage,isCarsiSelection}=require('../workflows/browser-operations.cjs');
const {PageChallenge}=require('./page-challenge.cjs');

function chromiumUserAgent(userAgent, productName) {
  return userAgent.split(' ').filter(token => !token.startsWith('Electron/')
    && !token.startsWith(productName + '/')).join(' ');
}
function configureBrowserSession(partition) {
  partition.setUserAgent(chromiumUserAgent(partition.getUserAgent(), app.getName())
    .replace(/Chrome\/(\d+)(?:\.\d+)*/, 'Chrome/$1.0.0.0'));
  partition.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  partition.setPermissionCheckHandler(() => false);
  return partition;
}
function browserURL(value) {
  const url = new URL(value);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password)
    throw Error('Browser requires an HTTP(S) URL without credentials');
  return url.href;
}
class BrowserRuntime {
  constructor({hostWindow,solveCloudflare,readCASCredentials,isTaskRunning=()=>false,recoveryTiming={},pageLimits} = {}) {
    this.solveCloudflare=solveCloudflare;
    this.readCASCredentials=readCASCredentials;
    this.isTaskRunning=isTaskRunning;
    this.recoveryTiming=recoveryTiming;
    this.pageBudget=new PageBudget(pageLimits);
    this.pageBudget.onBlocked=()=>{if(this.pageBudget.queue.length)this.reconsiderAdmission();};
    this.partition = configureBrowserSession(sharedBrowserSession());
    this.sessionEvents=sharedSessionEvents(this.partition,{timing:recoveryTiming});
    this.cooldown=this.sessionEvents.cooldown;
    this.sessionEvents.subscribe('beforeRequest',details=>{
      const tab=this.tabs.get(details.webContentsId);
      if(details.resourceType==='mainFrame' && tab){tab.mainRequest=details.id;tab.navigation.observeRequestStart(details);}
      if(tab?.taskOwner && !tab.pageAttempt?.retired) {
        const frame=details.frame;
        this.sessionEvents.associateRequest(details.id,{...tab.taskOwner.association,
          page_id:tab.id,attempt_id:tab.pageAttempt?.id ?? tab.taskOwner.association.request_id,process_id:frame?.processId,frame_token:frame?.frameToken,
          document_id:frame?tab.documentIds.get(frame.frameToken):undefined,navigation_generation:tab.documentGeneration});
      }
    });
    this.sessionEvents.subscribe('headersReceived',details=>{
      const tab=this.tabs.get(details.webContentsId);
      if(tab && details.resourceType==='mainFrame' && tab.mainRequest===details.id) {
        const values=Object.entries(details.responseHeaders || {}).filter(([key])=>key.toLowerCase()==='cf-mitigated').flatMap(([,value])=>value);
        tab.cfMitigated=values.length===1 && values[0].trim().toLowerCase()==='challenge';
      }
    });
    this.sessionEvents.subscribe('errorOccurred',details=>{
      const tab=this.tabs.get(details.webContentsId);
      if(details.resourceType==='mainFrame'){tab?.navigation.observeRequestFailure(details);return;}
      const netError=String(details.error || '').match(/^(?:net::)?(ERR_[A-Z0-9_]{1,80})$/)?.[1];
      if(tab)this.reportPage('debug','page_request_failed',tab,{resource_type:details.resourceType,net_error:netError,
        net_code:loadFailure(netError,details.errorCode).diagnostic.net_code});
    });
    this.tabs = new Map();
    this.paperPages=new Map();
    this.accessContexts=new Map();
    this.serviceEntryStarts=new ServiceEntryStarts(recoveryTiming);
    this.serviceRecoveries=new Map();
    this.authenticationRevision=0;
    this.schoolSubmission=null;
    this.failedCreations=new Set();
    this.carsiVisitOrigins=new Map();
    this.documents=new DocumentRuntime(this);
    this.bodyActions=new BodyActionRuntime(this,{ipc:ipcMain});
    this.events = new EventEmitter();
    this.selected = null;
    this.operationContext=new AsyncLocalStorage();
    this.operations=new Set();
    this.presentation=new BrowserPresentation(hostWindow);
    this.destroying = false;
    this.ready = configureBrowserIdentity(this.partition, app.getPath('sessionData'),{sessionEvents:this.sessionEvents}).then(identity => {
      this.identity = identity;
      if (this.destroying) {identity.dispose();throw Error('Browser closed during identity initialization');}
      return identity;
    });
  }
  createTab(options = {}, opener = null) {
    if (!this.identity || this.destroying || this.resetting) throw Error('Browser identity is not ready');
    if(options.webContents && this.tabs.has(options.webContents.id))throw new BrowserFailure('navigation','navigation_active');
    const execution=options.user===true?null:opener?.taskOwner || this.operation;
    if(execution && !this.operations.has(execution))throw new BrowserFailure('navigation','canceled');
    const bucket=this.pageBucket(execution);
    const ticket=options.pageTicket || this.reservedTicket(execution) || this.pageBudget.tryAcquire(execution,bucket,1,!execution);
    if(!ticket)throw new BrowserFailure('navigation','page_capacity');
    const resource=ticket.take();
    let view;
    try {view = new WebContentsView({...(options.webContents ? {webContents:options.webContents} : {}),
      webPreferences:{...options.webPreferences, session:this.partition, sandbox:true,
      contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true, webSecurity:true}});}
    catch(error){
      if(options.webContents && !options.webContents.isDestroyed())this.retireFailedCreation(options.webContents,resource,execution);
      else resource.release();
      throw error;
    }
    const contents = view.webContents;
    view.setVisible(false);
    this.presentation.initializeView(view);
    // The Session already owns the synchronous identity preload and HTTPS headers.
    contents.setUserAgent(this.partition.getUserAgent());
    const owner=execution;
    const inheriting=opener && owner && this.ownsPage(owner,opener.id);
    const tab = {id:contents.id, view, resource,resourceOwner:execution || {kind:'user'},status:null, error:null, opener,managed:options.managed===true,
      pageAttempt:inheriting?opener.pageAttempt:options.pageAttempt,documentGeneration:0,documentIds:new Map(),
      taskOwner:owner || null,taskSignal:inheriting?opener.taskSignal:owner?.signal || null,popupFrameName:options.popupFrameName,
      authContext:inheriting?opener.authContext:undefined,loadOwner:inheriting?opener.loadOwner:null,
      loadAllowed:inheriting?opener.loadAllowed:false};
    this.tabs.set(tab.id, tab);
    if(owner)this.trackTaskDownloads(tab,owner);
    contents.setWindowOpenHandler(({url,frameName}) => {
      if(this.resetting || tab.pageAttempt?.retired || contents.isDestroyed() || tab.closing)return {action:'deny'};
      if(tab.bodyAction && !tab.bodyAction.acceptPopup(url,frameName))return {action:'deny'};
      const popupOwner=tab.taskOwner;
      if(popupOwner && !this.ownsPage(popupOwner,tab.id) || !popupOwner && tab.resourceOwner.kind!=='user' && !(tab.resourceOwner.kind==='access' && tab.resourceOwner.valid))return {action:'deny'};
      if (url !== 'about:blank') {
        try {browserURL(url);} catch (_) {return {action:'deny'};}
      }
      const reserved=popupOwner?this.reservedTicket(popupOwner):null;
      const popupTicket=popupOwner?reserved?.split():this.pageBudget.tryAcquire(null,'user',1,true);
      if(!popupTicket){if(popupOwner)popupOwner.resourceFailure=new BrowserFailure('navigation','page_capacity');return {action:'deny'};}
      return {action:'allow',outlivesOpener:!!popupOwner, overrideBrowserWindowOptions:{webPreferences:{session:this.partition,
        sandbox:true, contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true}},
        createWindow:options => {
          if(popupOwner && !this.ownsPage(popupOwner,tab.id) || tab.closing || contents.isDestroyed())throw new BrowserFailure('navigation','canceled');
          return this.createTab({...options,present:false,user:!popupOwner,pageTicket:popupTicket,popupFrameName:frameName},tab).view.webContents;
        }};
    });
    const guard = (event, url) => {
      url=event.url ?? url;
      if (url === 'about:blank') return;
      try {browserURL(url);} catch (_) {event.preventDefault();}
    };
    contents.on('will-navigate', guard);
    contents.on('will-redirect', guard);
    tab.navigation=new NavigationRecovery(tab,{...this.recoveryTiming,options:()=>this.navigationOptions(tab),
      changed:()=>this.publish(),report:(level,event,details)=>this.reportPage(level,event,tab,details)});
    contents.on('render-process-gone', (_event, details) => {
      if(this.destroying || tab.pageAttempt?.retired)return;
      if(tab.navigation.current)tab.navigation.current.failure=new BrowserFailure('navigation','renderer_gone');
      tab.challenge?.cancel();tab.navigation.finish();
      tab.status=null;tab.paperDocument=null;tab.documentGeneration++;tab.documentIds.clear();
      tab.error={kind:'renderer',reason:details.reason,exitCode:details.exitCode};
      this.reportPage('warn','page_renderer_gone',tab,{reason:details.reason,exit_code:details.exitCode});
      tab.association=null;tab.associationOwner=null;
      this.publish();
    });
    contents.on('context-menu', (_event, params) => {
      const template=[
        {label:'后退',enabled:!tab.managed && contents.navigationHistory.canGoBack(),click:()=>{void this.command({action:'back',id:tab.id}).catch(()=>{});}},
        {label:'前进',enabled:!tab.managed && contents.navigationHistory.canGoForward(),click:()=>{void this.command({action:'forward',id:tab.id}).catch(()=>{});}},
        {label:'刷新',enabled:!tab.managed || !this.pageBusy(tab),click:()=>{void this.command({action:'reload',id:tab.id}).catch(()=>{});}},
      ];
      if(params.isEditable) {
        const flags=params.editFlags;
        template.push({type:'separator'},
          {label:'撤销',enabled:flags.canUndo,click:()=>contents.undo()},
          {label:'重做',enabled:flags.canRedo,click:()=>contents.redo()},
          {label:'剪切',enabled:flags.canCut,click:()=>contents.cut()},
          {label:'复制',enabled:flags.canCopy,click:()=>contents.copy()},
          {label:'粘贴',enabled:flags.canPaste,click:()=>contents.paste()},
          {label:'全选',enabled:flags.canSelectAll,click:()=>contents.selectAll()});
      } else if(params.selectionText)template.push({type:'separator'},{label:'复制',click:()=>contents.copy()});
      if(params.linkURL)template.push({label:'复制链接地址',click:()=>clipboard.writeText(params.linkURL)});
      template.push({type:'separator'},{label:'检查元素',click:()=>{
        contents.openDevTools({mode:'detach'});
        contents.inspectElement(params.x,params.y);
      }});
      Menu.buildFromTemplate(template).popup({window:this.presentation.host});
    });
    // Coalesce page events while a handler is running; no event consumes a login budget.
    let authPending=false,authRunning=false;
    const handleAuth=async()=>{
      authPending=true;
      if(authRunning)return;
      authRunning=true;
      try {
        while(authPending && !contents.isDestroyed()) {
          authPending=false;
          await this.handleAuthentication(tab);
        }
      } catch (_) {this.reportPage('warn','institution_auth_skipped',tab,{code:'auth_execution_failed'});}
      finally {authRunning=false;}
    };
    contents.on('did-stop-loading',()=>{void handleAuth();});
    contents.on('did-navigate-in-page',(_event,_url,main)=>{if(main)void handleAuth();});
    let mainFrameLoading=false;
    const publishLoading=()=>{
      const loading=contents.isLoadingMainFrame();
      if(loading===mainFrameLoading)return;
      mainFrameLoading=loading;this.publish();
    };
    contents.on('did-start-navigation',(event,url,inPlace,main)=>{
      if(event.isMainFrame ?? main) {
        tab.documentGeneration++;tab.documentIds.clear();tab.paperDocument=null;
        if(!(event.isSameDocument ?? inPlace)){tab.cfMitigated=false;tab.mainRequest=null;tab.challenge?.navigating();}
        publishLoading();
      }
    });
    contents.on('did-start-loading',publishLoading);
    contents.on('did-stop-loading',publishLoading);
    for (const name of ['page-title-updated', 'did-navigate-in-page'])
      contents.on(name, () => this.publish());
    contents.on('destroyed', () => {
      this.cleanupStep(()=>this.reportPage('info','page_closed',tab,{reason:this.destroying?'app_exit':tab.closeReason}),tab.taskOwner);
      tab.association=null;tab.associationOwner=null;
      this.cleanupStep(()=>tab.downloadScope?.dispose(),tab.taskOwner);
      this.tabs.delete(tab.id);
      const access=tab.resourceOwner?.kind==='access'?tab.resourceOwner:null;
      if(access){access.valid=false;if(this.accessContexts.get(access.key)===access)this.accessContexts.delete(access.key);
        this.cleanupStep(()=>this.events.emit('access-pages-closed',[tab.id]),tab.taskOwner);}
      tab.destroyedCleanup=Promise.all([this.sessionEvents.waitForDownloads(contents),tab.challenge?.close()]).then(()=>resource.release());
      if(this.paperPages.get(tab.paperKey)===tab)this.paperPages.delete(tab.paperKey);
      if (tab.taskOwner?.taskTab === tab)tab.taskOwner.taskTab=null;
      for(const page of this.tabs.values()) {
        if(page.opener===tab)page.opener=null;
        if(page.association?.source_page_id===tab.id)
          page.association=Object.freeze({...page.association,source_page_id:null});
      }
      if (this.destroying) return;
      if (this.selected === tab) {
        this.cleanupStep(()=>this.select([...this.tabs.values()].filter(page=>!page.pageAttempt?.retired).at(-1)),tab.taskOwner);
      }
      this.cleanupStep(()=>this.publish(),tab.taskOwner);
    });
    if(opener?.association) {
      tab.association=Object.freeze({...opener.association,role:'popup',source_page_id:opener.id});
      tab.associationOwner=inheriting?owner:null;
    }
    this.reportPage('info','page_created',tab);
    if(opener?.association)this.reportPage('info','page_associated',tab);
    if(options.present!==false)this.select(tab);
    else this.publish();
    tab.challenge=this.runInOperation(null,()=>new PageChallenge({tab,owner,probe:signal=>this.accessState(tab,{signal,independent:true}),
      solve:options=>this.solveCloudflare?.(tab,options),changed:()=>{
        this.publish();
        if(tab.challenge?.state)this.reportPage('info','page_access',tab,{access_state:tab.challenge.state,challenge_type:tab.challenge.kind || 'unknown'});
      },
      report:()=>this.reportPage('warn','cloudflare_solver_failed',tab,{code:'solver_failed'})}));
    this.events.emit('tab-created',null,tab);
    opener?.bodyAction?.addPopup(tab);
    return tab;
  }
  beginAuthentication(tab,signal,entry,{preparing=false}={}) {
    const owner=this.claimPage(tab,signal);
    const controller=new AbortController();
    signal=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
    if(preparing && (this.authenticationPaused || owner.authenticationRevision!==this.authenticationRevision))
      throw new BrowserFailure('authentication','configuration_changed');
        const context={owner,signal,controller,entry,active:true,preparing,revision:owner.authenticationRevision,
      loginSubmitted:false,failure:null};
    context.fatal=new Promise((_,reject)=>{context.reject=reject;});
    context.fatal.catch(()=>{});
    owner.authContext=tab.authContext=context;
    return context;
  }
  endAuthentication(context) {
    if(!context)return;
    context.active=false;
    if(this.schoolSubmission===context)this.schoolSubmission=null;
    if(context.owner.authContext===context)context.owner.authContext=null;
  }
  authenticationFailure(tab) {
    const context=tab?.authContext;
    if(context?.active && context.failure)throw context.failure;
  }
  async revokeAuthentication() {
    this.authenticationRevision++;
    const active=[...this.operations].map(owner=>owner.authContext).filter(context=>context?.active);
    for(const context of active)if(context.preparing || context.engaged) {
      context.failure=new BrowserFailure('authentication','configuration_changed');
      context.reject(context.failure);context.controller.abort(context.failure);
    }
    await Promise.allSettled([...this.tabs.values()].map(tab=>tab.authHandling).filter(Boolean));
  }
  async inspectAuthentication(tab,{documentOnly=false}={}) {
    const wc=tab.view.webContents;
    if(wc.isDestroyed())throw new BrowserFailure('navigation','page_closed');
    const loading=()=>wc.isLoadingMainFrame() && !(documentOnly && tab.navigation.current?.documentReady);
    if(loading())return {step:'loading',waiting:true};
    let binding;
    try {binding=await this.documentBinding(tab,{signal:tab.taskSignal,deadline:tab.navigation.current?.deadline});}
    catch(error) {
      checkCanceled(tab.taskSignal);
      const context=tab.authContext;
      if(error.diagnostic?.code==='document_changed' && context?.active && !context.failure && this.operation===context.owner
        && this.ownsPage(context.owner,tab.id) && !wc.isDestroyed() && !wc.isCrashed() && !tab.navigation.current?.failure)
        return {step:'loading',waiting:true};
      throw error;
    }
    const frame=this.documentFrame(binding);
    if(!frame)return {step:'loading',waiting:true};
    let state;
    const url=new URL(binding.url);
    const carsiPage=url.origin==='https://ds.carsi.edu.cn' && ['/login/index.html','/wxds',
      '/resource/resource.php','/resource/resourceDetail.php'].includes(url.pathname);
    const context=tab.authContext;
    const mode=context?.active && xmuLoginContext(context.entry,binding.url)?'institution':'page';
    try {state=carsiPage?{step:'none',waiting:false}:await frame.executeJavaScript('('+institutionAuthPage.toString()+')(...'
      +JSON.stringify(['inspect',null,null,mode])+')');}
    catch (_) {state={step:'manual',waiting:true,code:'auth_execution_failed'};}
    if(!this.documentCurrent(binding) || loading())return {step:'loading',waiting:true};
    return {...state,binding};
  }
  async handleAuthentication(tab) {
    if(tab.authHandling)return tab.authHandling;
    const context=tab.authContext,wc=tab.view.webContents;
    if(!context?.active || !this.ownsPage(context.owner,tab.id) || context.signal.aborted || context.failure || this.destroying || wc.isDestroyed())return;
    const operation=this.runInOperation(context.owner,async()=>{
      const state=await this.inspectAuthentication(tab);
      const current=()=>context.active && !context.signal.aborted && !context.failure
        && tab.authContext===context && this.ownsPage(context.owner,tab.id) && !this.destroying && this.documentCurrent(state.binding)
        && !wc.isLoadingMainFrame();
      if(!state.binding || !current())return;
      const school=xmuLoginContext(context.entry,state.binding.url);
      const confirmation=['terms','release'].includes(state.step);
      tab.authState=state;
      if(state.waiting && (school || confirmation))context.engaged=true;
      if(school && state.code==='institution_credentials_rejected') {
        context.failure=new BrowserFailure('authentication','institution_credentials_rejected');
        context.reject(context.failure);
        this.reportPage('info','institution_auth_failed',tab,{code:state.code});
        return;
      }
      if(!confirmation && (!school || !['account','login'].includes(state.step)))return;
      if(!tab.authDocument || tab.authDocument.context!==context
        || tab.authDocument.documentId!==state.binding.documentId
        || tab.authDocument.frameToken!==state.binding.frameToken)
        tab.authDocument={...state.binding,context,attempted:new Set()};
      const attempted=tab.authDocument.attempted;
      if(attempted.has(state.step) || state.step==='login' && context.loginSubmitted)return;
      const authorized=()=>current() && context.revision===this.authenticationRevision && !this.authenticationPaused;
      if(!authorized())return;
      let credentials=null;
      if(!confirmation) {
        if(state.step==='login') {
          if(this.schoolSubmission && this.schoolSubmission!==context)return;
          this.schoolSubmission=context;
        }
        try {
          await context.owner.validateRecovery?.({signal:context.signal,
            deadline:tab.navigation.current?.deadline ?? Infinity,stage:'authentication'});
          if(state.step==='login' && this.readCASCredentials && authorized())credentials=await this.readCASCredentials();
        } catch(error) {
          if(!authorized())return;
          if(error instanceof BrowserFailure)throw error;
          this.reportPage('info','institution_auth_skipped',tab,{code:casErrorCode(error)});return;
        } finally {
          if(!context.active && this.schoolSubmission===context)this.schoolSubmission=null;
        }
        if(state.step==='login' && !credentials) {
          if(this.schoolSubmission===context)this.schoolSubmission=null;
          return;
        }
      }
      if(!authorized())return;
      // A form action belongs to this document and is never replayed after dispatch.
      attempted.add(state.step);context.actionDispatched=true;
      tab.navigation.blockReplay();
      if(state.step==='login')context.loginSubmitted=true;
      const releaseUnsent=()=>{
        attempted.delete(state.step);
        if(state.step==='login')context.loginSubmitted=false;
        if(!confirmation && this.schoolSubmission===context)this.schoolSubmission=null;
      };
      const frame=this.documentFrame(state.binding);
      let result;
      try {result=await frame.executeJavaScript('('+institutionAuthPage.toString()+')(...'
        +JSON.stringify(['act',credentials,state.step,confirmation?'confirmation':'institution'])+')');}
      catch (_) {this.reportPage('info','institution_auth_skipped',tab,{code:'auth_execution_failed'});return;}
      if(result?.acted===false && authorized())releaseUnsent();
      if(['terms','release'].includes(state.step) && result?.submission) {
        if(!authorized())return;
        let dispatched=false;
        try {
          const {url,body,referrer}=result.submission;
          const destination=browserURL(url),source=new URL(wc.getURL());
          if(source.protocol!=='https:' || new URL(destination).origin!==source.origin || referrer!==source.href || typeof body!=='string')
            throw Error('Invalid consent submission');
          // Navigation events observe the response; holding authHandling until load completion stalls that observer.
          tab.navigation.track(()=>{
            dispatched=true;
            return wc.loadURL(destination,{postData:[{type:'rawData',bytes:Buffer.from(body,'utf8')}],
              extraHeaders:'Content-Type: application/x-www-form-urlencoded',httpReferrer:referrer});
          });
          result.acted=true;
        } catch (_) {
          if(!dispatched && current())releaseUnsent();
          this.reportPage('info','institution_auth_skipped',tab,{code:'auth_execution_failed'});return;
        }
      }
      if(result?.code==='institution_credentials_rejected' && context.active && !context.signal.aborted
        && tab.authContext===context) {
        context.failure=new BrowserFailure('authentication','institution_credentials_rejected');context.reject(context.failure);
      }
      this.reportPage('info','institution_auth_action',tab,{step:state.step,
        code:result?.acted?'auth_action_dispatched':'auth_action_unconfirmed'});
    });
    tab.authHandling=operation;
    try {await operation;} finally {if(tab.authHandling===operation)tab.authHandling=null;}
  }
  checkTaskResources() {if(this.operation?.resourceFailure)throw this.operation.resourceFailure;}
  async checkAuthentication(tab) {
    this.checkTaskResources();
    tab?.navigation.check();
    const context=tab?.authContext;
    this.authenticationFailure(tab);
    if(!context?.active || context.signal.aborted)return false;
    let waiting=false;
    for(const page of this.tabs.values()) {
      if(page.authContext!==context)continue;
      await this.handleAuthentication(page);
      this.authenticationFailure(tab);
      waiting ||= page===tab && page.authState?.waiting===true;
    }
    return waiting;
  }
  select(tab,{focus=false}={}) {
    this.selected = tab || null;
    this.presentation.select(this.selected,{focus});this.publish();
  }
  setPresentation(value){return this.presentation.update(value);}
  pageBusy(tab) {return !!tab?.taskOwner && this.operations.has(tab.taskOwner);}
  state() {
    const taskPageIds=[...this.operations].map(owner=>owner.taskTab?.id).filter(id=>id!=null);
    return {selected:this.selected?.id || null,taskPageId:taskPageIds.at(-1) ?? null,taskPageIds,
      taskRunning:this.operations.size>0 || this.isTaskRunning(),
      tabs:[...this.tabs.values()].filter(tab=>!tab.pageAttempt?.retired).map(tab => {
      const wc=tab.view.webContents;
      return {id:tab.id,title:wc.getTitle() || 'New tab',url:wc.getURL(),loading:wc.isLoadingMainFrame(),
        busy:this.pageBusy(tab),managed:tab.managed,challenge:tab.challenge?.state || null,challengeKind:tab.challenge?.kind || null,
        association:this.pageAssociation(tab.id),openerId:tab.opener?.id || null,
        error:tab.error?{kind:tab.error.kind,code:tab.error.code,reason:tab.error.reason}:null,
        back:wc.navigationHistory.canGoBack(),forward:wc.navigationHistory.canGoForward()};
    })};
  }
  publish() {
    this.presentation.send('browser:state',this.state());
  }
  async show() {
    await this.ready;
    if (!this.tabs.size) this.createTab({user:true});
    if(!this.selected)this.select(this.tabs.values().next().value);
    this.presentation.show();
    return this.state();
  }
  async openURL(value) {
    const url=browserURL(value);
    await this.ready;
    const tab=this.createTab({present:false,user:true});this.select(tab,{focus:true});
    this.presentation.show();
    await this.waitForCooldown(url,{pageId:tab.id});
    if(this.tabs.get(tab.id)!==tab)throw new BrowserFailure('navigation','page_closed');
    await tab.navigation.dispatch(()=>tab.view.webContents.loadURL(url),{});
    return tab;
  }
  async command(command) {
    await this.ready;
    const actions=['state','new','select','close','navigate','back','forward','reload'];
    const fields=['action','id','url'];
    if (!command || typeof command!=='object' || Array.isArray(command)
      || Object.keys(command).some(key=>!fields.includes(key))
      || !actions.includes(command.action)
      || (command.id!==undefined && (!Number.isSafeInteger(command.id) || command.id<=0))
      || (command.action==='select' && command.id===undefined)
      || (command.action==='navigate' && (typeof command.url!=='string' || command.url.length>8192))
      || (command.url!==undefined && command.action!=='navigate')) throw Error('Invalid Browser command');
    if(this.resetting && command.action!=='state')throw new BrowserFailure('navigation','canceled');
    const tab = command.id == null ? this.selected : this.tabs.get(command.id);
    if (command.id != null && !tab && !['state','new'].includes(command.action)) throw Error('Unknown tab');
    if(tab?.managed && ['close','navigate','back','forward'].includes(command.action))
      throw Error('This managed page is locked');
    if(tab?.managed && command.action==='reload' && this.pageBusy(tab))
      throw Error('The active task page cannot be refreshed');
    switch (command.action) {
      case 'state': break;
      case 'new': this.select(this.createTab({present:false,user:true}),{focus:true});break;
      case 'select': if (!this.tabs.has(command.id)) throw Error('Unknown tab');this.select(tab,{focus:true});break;
      case 'close':
        if (this.pageBusy(tab)) throw Error('The active task page cannot be closed');
        if(tab){tab.closeReason='user';this.reportPage('info','page_close_requested',tab,{reason:'user'});tab.view.webContents.close();}break;
      case 'navigate': {
        if(!tab)throw Error('No Browser tab');
        const url=browserURL(command.url);
        await this.waitForCooldown(url,{pageId:tab.id,validate:()=>this.checkCommandPage(tab,command.action)});
        this.checkCommandPage(tab,command.action);
        tab.authContext=null;
        await tab.navigation.dispatch(()=>tab.view.webContents.loadURL(url),this.navigationOptions(tab));break;
      }
      case 'back':
      case 'forward': {
        const history=tab?.view.webContents.navigationHistory,back=command.action==='back';
        if(!(back?history?.canGoBack():history?.canGoForward()))break;
        const index=history.getActiveIndex()+(back?-1:1),url=history.getEntryAtIndex(index)?.url;
        await this.waitForCooldown(url,{pageId:tab.id,validate:()=>this.checkCommandPage(tab,command.action)});
        this.checkCommandPage(tab,command.action);
        if(history.getActiveIndex()+(back?-1:1)!==index || history.getEntryAtIndex(index)?.url!==url)
          throw new BrowserFailure('navigation','document_changed');
        tab.navigation.history(()=>back?history.goBack():history.goForward(),this.navigationOptions(tab));
        break;
      }
      case 'reload': {
        if(!tab)break;
        const wc=tab.view.webContents,url=wc.getURL(),generation=tab.navigation.generation;
        await this.waitForCooldown(url,{pageId:tab.id,validate:()=>this.checkCommandPage(tab,command.action)});
        this.checkCommandPage(tab,command.action);
        if(wc.getURL()!==url || tab.navigation.generation!==generation)
          throw new BrowserFailure('navigation','document_changed');
        tab.navigation.begin(this.navigationOptions(tab));tab.navigation.track(()=>wc.reload());break;
      }
      default: throw Error('Unknown Browser command');
    }
    return this.state();
  }
  checkCommandPage(tab,action) {
    if(this.tabs.get(tab.id)!==tab || tab.pageAttempt?.retired || tab.view.webContents.isDestroyed())
      throw new BrowserFailure('navigation','page_closed');
    if(tab.managed && (action!=='reload' || this.pageBusy(tab)))
      throw new BrowserFailure('navigation','navigation_active');
  }
  waitForCooldown(url,options={}) {
    const contents=this.tabs.get(options.pageId)?.view.webContents;
    if(!contents)return this.cooldown.wait(url,{report:this.operation?.recordRecovery,...options});
    const closed=new AbortController(),stop=()=>closed.abort(new BrowserFailure('navigation','page_closed'));
    contents.once('destroyed',stop);
    if(contents.isDestroyed())stop();
    return this.cooldown.wait(url,{report:this.operation?.recordRecovery,...options,
      signal:AbortSignal.any([options.signal,closed.signal].filter(Boolean))})
      .finally(()=>contents.removeListener('destroyed',stop));
  }
  reportPage(level,event,tab,details={}) {
    const snapshot=associationLogContext(tab.association,tab.id,tab.navigation?.generation);
    // Native callbacks can run in an old async context: the saved page association is authoritative for diagnostics.
    withLogContext({},()=>log(level,event,{...snapshot,...details}));
  }
  cleanupStep(run,owner) {
    try{return run();}catch(_) {
      // Only auxiliary synchronous release/notification work uses this path.
      // Physical DownloadItem/page settlement is still awaited by its owner.
      try{log('warn','task_cleanup_failed',{...associationLogContext(owner?.association),step:'release',code:'document_operation_failed'});}catch(_){}
    }
  }
  get operation() {return this.operationContext.getStore();}
  get taskTab() {return this.operation?.taskTab ?? null;}
  get taskActive() {return !!this.operation?.taskTab;}
  async runTask(signal,data,run) {
    if(this.destroying || this.resetting)throw new BrowserFailure('navigation','canceled');
    const owner={signal,phase:'loading',authenticationRevision:this.authenticationRevision,association:operationAssociation(data),
      taskTab:null,navigationAbort:null};
    this.operations.add(owner);
    try {
      const result=await this.runInOperation(owner,run);
      const completedBody=result?.kind==='pdf'&&result.pdf_type===true&&result.transfer_complete===true;
      if(owner.resourceFailure&&!completedBody)throw owner.resourceFailure;
      return result;
    }
    finally {
      try{await this.releaseOperation(owner);}catch(error){error.resource_closed=false;throw error;}
    }
  }
  runInOperation(owner,run) {
    return this.operationContext.run(owner,run);
  }
  ownsPage(owner,id) {
    return !!owner && this.operations.has(owner) && !owner.signal?.aborted
      && this.tabs.get(id)?.taskOwner===owner && !this.tabs.get(id).pageAttempt?.retired;
  }
  claimPage(tab,signal) {
    checkCanceled(signal);
    if(this.destroying || this.tabs.get(tab?.id)!==tab || tab.pageAttempt?.retired || tab.view.webContents.isDestroyed())
      throw new BrowserFailure('navigation','page_closed');
    const owner=this.operation;
    if(!this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
    checkCanceled(owner.signal);if(owner.resourceFailure)throw owner.resourceFailure;
    const access=tab.resourceOwner?.kind==='access'?tab.resourceOwner:null;
    if(access?.loan && (access.loan.workflow_id!==owner.association.workflow_id || access.loan.task_id!==owner.association.task_id))
      throw new BrowserFailure('navigation','navigation_active');
    if(access && !access.valid)throw new BrowserFailure('navigation','document_changed');
    if(tab.taskOwner && tab.taskOwner!==owner)throw new BrowserFailure('navigation','navigation_active');
    tab.taskOwner=owner;
    this.trackTaskDownloads(tab,owner);
    return owner;
  }
  trackTaskDownloads(tab,owner) {
    if(tab.downloadScopeOwner===owner)return;
    tab.downloadScope?.dispose();tab.downloadScopeOwner=owner;
    tab.downloadScope=this.sessionEvents.registerTaskPage({owner,contents:tab.view.webContents,
      validate:()=>tab.taskOwner===owner && this.tabs.get(tab.id)===tab});
  }
  associatePage(tab,{role,source=null,service=true,doi=null}={}) {
    if(this.tabs.get(tab?.id)!==tab || tab.view.webContents.isDestroyed())
      throw new BrowserFailure('navigation','page_closed');
    const owner=this.claimPage(tab,this.operation?.signal);
    const association=owner.association;
    if(tab.association)this.reportPage('info','page_association_replaced',tab);
    tab.association=Object.freeze({...association,service_id:service?association.service_id:null,
      role,doi,source_page_id:source && source!==tab && this.tabs.get(source.id)===source?source.id:null});
    tab.associationOwner=owner;
    this.reportPage('info','page_associated',tab);
    this.publish();
  }
  pageAssociation(id) {
    const tab=this.tabs.get(id);
    if(!tab?.association || tab.pageAttempt?.retired || tab.view.webContents.isDestroyed())return null;
    return Object.freeze({page_id:id,...tab.association,
      active:!!tab.associationOwner?.taskTab && this.ownsPage(tab.associationOwner,id)});
  }
  servicePages(scopeId,serviceId) {
    return [...this.tabs.values()].filter(tab=>tab.association?.service_scope?.scope_id===scopeId
      && tab.association?.service_id===serviceId).map(tab=>this.pageAssociation(tab.id)).filter(Boolean);
  }
  pageAttempt(signal) {
    const owner=this.operation;
    if(!this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
    const controller=new AbortController();
    return {id:randomBytes(16).toString('hex'),owner,controller,signal:AbortSignal.any([controller.signal,...(signal?[signal]:[])])};
  }
  async retirePageAttempt(attempt) {
    const owner=this.operation;
    if(attempt.owner!==owner || !this.operations.has(owner) || owner.phase!=='loading')
      throw new BrowserFailure('navigation','document_changed');
    const pages=[...this.tabs.values()].filter(tab=>tab.pageAttempt===attempt && this.ownsPage(owner,tab.id));
    attempt.retired=true;
    for(const tab of pages) {
      tab.navigation.dispose();
      tab.authContext=null;
      tab.paperDocument=null;
      if(this.paperPages.get(tab.paperKey)===tab)this.paperPages.delete(tab.paperKey);
      if(owner.taskTab===tab)owner.taskTab=null;
    }
    attempt.controller.abort(new BrowserFailure('navigation','document_changed'));
    await Promise.all(pages.map(tab=>this.closePage(tab,'attempt_retired')));
  }
  bindTaskPage(tab,signal=this.operation?.signal) {
    const owner=this.claimPage(tab,signal);
    owner.taskTab=tab;tab.taskSignal=signal;
  }
  navigationOptions(tab,{signal,deadline}={}) {
    const owner=tab.taskOwner;
    const automatic=this.ownsPage(owner,tab.id) && (owner.taskTab===tab || tab.loadOwner===owner || (!!tab.opener && tab.opener===owner.taskTab));
    return {automatic,owner:automatic?owner:null,
      ...(owner?.association.paper_id && {pageLoadLimit:null}),
      signal:automatic?(signal || tab.taskSignal || owner?.signal):undefined,
      deadline:automatic?(deadline ?? tab.navigation?.current?.deadline ?? Infinity):Infinity,
      enabled:automatic && !this.destroying && owner.phase!=='business' && tab.loadAllowed!==false,
      valid:()=>this.ownsPage(owner,tab.id) && owner.phase==='loading' && !tab.authContext?.actionDispatched,
      beforeRefresh:(url,options)=>this.runInOperation(owner,async()=>{
        await tab.refreshGuard?.(options);
        await this.waitForCooldown(url,{...options,pageId:tab.id,step:'page_load',
          authorize:owner.validateRecovery?()=>owner.validateRecovery({...options,stage:'navigation'}):undefined});
      }),recoveryReport:owner?.recordRecovery};
  }
  beginPageLoad(tab,signal,deadline=Infinity,{fresh=false,replayable,replayFollowingGets}={}) {
    this.bindTaskPage(tab,signal);tab.loadOwner=this.operation;tab.loadAllowed=true;
    const options={...this.navigationOptions(tab,{signal,deadline}),replayable,replayFollowingGets};
    return fresh?tab.navigation.begin(options):tab.navigation.adopt(options);
  }
  finishPageLoad(tab=this.taskTab) {if(tab){tab.loadAllowed=false;tab.navigation.finish();}}
  enterBusiness() {
    const owner=this.operation;
    if(!owner)return;
    owner.phase='business';
    for(const tab of this.tabs.values())if(tab.navigation.current?.owner===owner)tab.navigation.finish();
  }
  async inspectPage(tab,{signal,deadline=Infinity,stage='navigation',step='verification',extraWaiting,onWaiting,automaticDeadline=deadline,navigationChain,documentOnly=false}={}) {
    checkCanceled(signal);this.checkTaskResources();
    if(navigationChain && tab.navigation.current?.chain!==navigationChain)throw new BrowserFailure('navigation','document_changed');
    tab.navigation.check();
    if(tab.navigation.isLoading(documentOnly))
      return {doc:null,waiting:false,loading:true};
    try {return await inspectPage({signal,deadline,automaticDeadline,stage,step,onWaiting,
      authentication:()=>this.checkAuthentication(tab),inspectAuthentication:()=>this.inspectAuthentication(tab,{documentOnly}),
      probe:()=>this.accessState(tab,{signal,deadline}),current:doc=>{
        tab.navigation.check();
        if(navigationChain && tab.navigation.current?.chain!==navigationChain)throw new BrowserFailure('navigation','document_changed');
        return this.documentCurrent(doc) && !tab.navigation.isLoading(documentOnly);
      },
      extraWaiting,
      }).then(result=>{
        if(result.waiting && !result.loading && (result.diagnostic || Number.isInteger(result.doc?.status)))
          tab.navigation.blockReplay();
        return result;
      });
    }catch(error) {
      // A document replaced within the same navigation chain is still loading.
      if(error.diagnostic?.code==='document_changed' && navigationChain && tab.navigation.current?.chain===navigationChain && !signal?.aborted)
        return {doc:null,waiting:false,loading:true};
      throw error;
    }
  }
  async waitForPage(tab,{signal,deadline=Infinity,onWaiting,extraWaiting,finish=true,...options}={}) {
    const chain=options.navigationChain || tab.navigation.current?.chain;
    try {
      const doc=await waitForPage(()=>this.inspectPage(tab,{signal,deadline,extraWaiting,onWaiting,...options,navigationChain:chain}),
        {signal,deadline,onWaiting,...options});
      if(finish && tab.navigation.current?.chain===chain)this.finishPageLoad(tab);
      return doc;
    } catch(error){if(tab.navigation.current?.chain===chain)this.finishPageLoad(tab);throw error;}
  }

  navigateServiceTarget(data,target,options) {
    return this.observeServiceTarget(data,target,options,value=>this.navigate(target,value));
  }
  waitForServiceTarget(data,options) {
    const {tab}=options;
    return this.observeServiceTarget(data,tab.view.webContents.getURL(),options,value=>this.waitForPage(tab,{
      ...value,onWaiting:(waiting,diagnostic,doc)=>{if(waiting)value.onWaiting?.(diagnostic,doc);},
    }));
  }
  async observeServiceTarget(data,target,options,observe) {
    const {tab,signal,onWaiting}=options,entry=data.service_entry;
    if(!entry)return observe(options);
    if(entry.unavailable_reason)throw new BrowserFailure('preparation','service_unavailable');
    const context=this.beginAuthentication(tab,signal,entry);
    try {
      return await observe({...options,signal:context.signal,
        extraWaiting:doc=>isCarsiSelection(doc.url) || isFederatedPage(entry,doc.url) || options.extraWaiting?.(doc),
        onWaiting:(diagnostic,doc)=>{
          const url=doc?.url;
          // Preserve the current IdP/consent chain. A recognized login barrier
          // outside it can use the saved entry once. A bare 403 never gets here.
          if(url && reusableNavigationURL(target) && (isCarsiSelection(url)
            || !diagnostic && doc.markers.login && !doc.markers.mfa && !isFederatedPage(entry,url) && !context.engaged))
            throw new BrowserFailure('authentication','service_authentication_required');
          if(doc?.markers.login || doc?.markers.mfa || isFederatedPage(entry,url)) {
            context.engaged=true;
            if(context.revision!==this.authenticationRevision)
              throw new BrowserFailure('authentication','configuration_changed');
          }
          onWaiting?.(diagnostic,doc);
        }});
    } finally {
      this.endAuthentication(context);
    }
  }
  async resumeServiceStep(data,{signal,deadline,onWaiting,closeBlockedPage=false},step) {
    const previous=this.serviceContext(data);
    try {return await step();}
    catch(error) {
      if(!data.service_entry || error.diagnostic?.stage!=='authentication'
        || !['service_authentication_required','service_page_required'].includes(error.diagnostic.code))throw error;
      const owner=this.operation,tab=owner.taskTab;
      if(tab && this.ownsPage(owner,tab.id) && (tab.resourceOwner===owner || closeBlockedPage
        && tab.resourceOwner===previous && !previous.pins.size && !previous.loan))await this.closePage(tab,'service_recovery');
      this.pageBudget.releaseUnused(owner);
      await recoverService(this,data,{signal,deadline,
        progress:value=>{if(value.waiting_for_user)onWaiting?.(undefined,undefined);}},previous);
      checkCanceled(signal);
      return step();
    }
  }

  async openPaperPage(data,identity,{role,signal,onWaiting,deadline=Date.now()+TASK_DEADLINE_MS,documentOnly=false}={}) {
    const options={role,signal,onWaiting,deadline,documentOnly};
    return this.resumeServiceStep(data,options,()=>this.openArticle(data,identity,options));
  }
  async openArticle(data,identity,{role,signal,onWaiting,deadline,documentOnly}) {
    const {workspace_identity:workspace,paper_id:paper}=data;
    if(typeof workspace!=='string' || !/^[a-f0-9]{64}$/.test(workspace)
      || typeof paper!=='string' || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(paper))
      throw Error('Invalid managed Paper identity');
    await waitFor(()=>this.ready,signal,deadline);
    checkCanceled(signal);
    const owner=this.operation,key=workspace+':'+paper.toLowerCase();
    let tab=this.paperPages.get(key),firstFailure,sourcePageId,previousOrigin;
    const paperIdentity=typeof identity==='string'?{doi:identity}:{doi:identity?.doi,confirmed_article_url:identity?.confirmed_article_url};
    const doi=validDOI(paperIdentity.doi),established=articleURL(paperIdentity.confirmed_article_url);
    if(paperIdentity.doi && !doi || !doi && !established)throw new BrowserFailure('navigation','document_operation_failed');
    const target=doi?'https://doi.org/'+encodeURIComponent(doi):established.href;
    const identityKey=JSON.stringify([doi,established?.href]);
    const record=(event,error,fields={})=>reportRecovery(owner.recordRecovery,event,pageRecoveryDetails(error,'paper_reopen',{
      stage:'navigation',source_page_id:sourcePageId,attempt:1,attempt_limit:1,...fields}));
    for(let index=0;index<2;index++) {
      const attempt=this.pageAttempt(signal);
      try {
        if(index) {
          const validate=()=>{
            if(this.paperPages.has(key) || !this.operations.has(owner) || owner.phase!=='loading'
              || data.workspace_identity!==workspace || data.paper_id!==paper)
              throw new BrowserFailure('navigation','document_changed');
            if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
          };
          await this.waitForCooldown([target,previousOrigin],{signal:attempt.signal,deadline,validate,
            pageId:sourcePageId,step:'page_load',authorize:()=>waitFor(()=>owner.validateRecovery?.({
              signal:attempt.signal,deadline,stage:'navigation'}),attempt.signal,deadline)});
          validate();
        }
        if(!tab) {
          tab=await this.newTaskPage({signal:attempt.signal,deadline,managed:true,pageAttempt:attempt});
          tab.paperKey=key;
          this.paperPages.set(key,tab);
        }
        this.bindTaskPage(tab,attempt.signal);
        tab.pageAttempt=attempt;
        this.associatePage(tab,{role,doi});
        const contents=tab.view.webContents;
        const matches=doc=>this.documentCurrent(doc) && contents.getURL()===doc.url
          && (documentOnly || !contents.isLoadingMainFrame());
        const previous=tab.paperDocument;
        if(previous?.identityKey===identityKey && matches(previous.doc) && !tab.navigation.current?.failure) {
          const doc=await this.waitForPage(tab,{signal:attempt.signal,deadline,documentOnly,
            onWaiting:(waiting,diagnostic)=>{if(waiting)onWaiting?.(diagnostic);}});
          if(tab.paperDocument===previous && matches(previous.doc) && doc.url===previous.doc.url)
            return {...doc,identity:paperIdentity};
        }
        tab.paperDocument=null;
        const doc=await this.navigateServiceTarget(data,target,{tab,signal:attempt.signal,deadline,onWaiting,documentOnly});
        if(!matches(doc) || this.paperPages.get(key)!==tab)throw new BrowserFailure('navigation','document_changed');
        this.finishPageLoad(tab);
        const confirmed={...doc,identity:paperIdentity};
        tab.paperDocument={identityKey,doc:confirmed};
        if(index)record('recovery_succeeded',firstFailure,{page_id:tab.id,dispatch_outcome:'confirmed'});
        return confirmed;
      } catch(error) {
        if(index)record('recovery_exhausted',error,{page_id:tab?.id,recovery_stop:recoveryStop(error,signal)});
        if(index || !error.rebuildPage || signal?.aborted || owner.phase!=='loading'
          || !this.ownsPage(owner,tab?.id) || this.paperPages.get(key)!==tab)throw error;
        if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
        firstFailure=error;sourcePageId=tab.id;previousOrigin=origin(tab.navigation.current?.url);
        record('recovery_scheduled',error,{page_id:tab.id,dispatch_outcome:'not_dispatched'});
        await this.retirePageAttempt(attempt);
        tab=null;
      }
    }
  }

  async navigate(url,{tab=this.taskTab,signal=this.operation?.signal,deadline=Infinity,onWaiting,httpReferrer,documentOnly=false,serviceEntry,afterLoad=false,extraWaiting}={}) {
    const owner=this.operation;
    if(!this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
    await waitFor(()=>this.ready,signal,deadline);
    checkCanceled(signal);
    if(this.destroying || this.resetting || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
    if(owner.navigationAbort)throw new BrowserFailure('navigation','navigation_active');
    if(!tab)throw new BrowserFailure('navigation','page_closed');
    const target=browserURL(url);
    this.bindTaskPage(tab,signal);
    const controller=new AbortController(),bounded=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
    owner.navigationAbort=controller;
    tab.taskSignal=bounded;tab.loadOwner=owner;tab.loadAllowed=true;
    let chain;
    try {
      const validate=()=>{
        if(!this.ownsPage(owner,tab.id))throw new BrowserFailure('navigation','document_changed');
      };
      await this.waitForCooldown(target,{signal:bounded,deadline,validate,pageId:tab.id,step:'page_load',
        authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal:bounded,deadline,stage:'navigation'}):undefined});
      checkCanceled(bounded);
      validate();
      if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
      let loading;
      const start=()=>{
        loading=tab.navigation.dispatch(()=>tab.view.webContents.loadURL(target,{httpReferrer}),
          {...this.navigationOptions(tab,{signal:bounded,deadline}),replayable:true,initialURL:target,httpReferrer,documentOnly});
        loading.catch(()=>{});
        chain=tab.navigation.current?.chain;
      };
      if(serviceEntry) {
        let first=serviceEntry==='first';
        while(!loading) {
          await this.serviceEntryStarts.dispatch(()=>{
            if((this.cooldown.origins.get(origin(target))?.until ?? 0)<=this.cooldown.now())start();
          },{signal:bounded,deadline,validate,first});
          if(!loading)await this.waitForCooldown(target,{signal:bounded,deadline,validate,pageId:tab.id,step:'page_load'});
          first=false;
        }
      } else start();
      const navigation=await (tab.authContext?.active
        ?Promise.race([loading,tab.authContext.fatal]):loading);
      if(afterLoad)return navigation;
      const doc=await this.waitForPage(tab,{signal:bounded,deadline,finish:false,navigationChain:navigation.chain,documentOnly,extraWaiting,
        onWaiting:(waiting,diagnostic,document)=>{if(waiting)onWaiting?.(diagnostic,document);}});
      this.reportPage('info','navigation_ready',tab,{stage:'navigation',code:'page_ready',status:doc.status});
      return doc;
    } catch(error) {
      if(chain && tab.navigation.current?.chain===chain) {
        tab.navigation.current.failure ||= error;
        this.finishPageLoad(tab);
        if(!tab.view.webContents.isDestroyed() && tab.view.webContents.isLoadingMainFrame())tab.view.webContents.stop();
      }
      throw error;
    } finally {
      if(owner.navigationAbort===controller)owner.navigationAbort=null;
    }
  }
  async readDocument(tab=this.taskTab,action='binding',options={}) {
    checkCanceled(options.signal);
    if(!tab || !this.tabs.has(tab.id))throw new BrowserFailure('navigation','page_closed');
    if(!options.independent)tab.navigation.check();
    const frame=tab.view.webContents.mainFrame;
    const binding={pageId:tab.id,processId:frame.processId,frameToken:frame.frameToken,
      url:frame.url,navigationGeneration:tab.documentGeneration,...(options.identity?{identity:options.identity}:{})};
    const known=tab.documentIds.get(frame.frameToken);
    if(known)binding.documentId=known;
    const result=await this.documents.call(binding,action,options.args || {},options);
    if(action==='extract'||action==='pdf')return result;
    if(action==='ebsco')return {...binding,...result,status:tab.status};
    checkCanceled(options.signal);
    if(!options.independent)tab.navigation.check();
    if(!this.documentCurrent(binding))throw new BrowserFailure('navigation','document_changed');
    tab.documentIds.set(frame.frameToken,result.documentId);
    return {...binding,...result,status:tab.status};
  }
  documentBinding(tab=this.taskTab,options={}) {return this.readDocument(tab,'binding',options);}
  async accessState(tab=this.taskTab,options={}) {
    const doc=await this.readDocument(tab,'access',options);
    // Native frame ancestry includes Turnstile inside a closed shadow root.
    // This is evidence for an already detected challenge, never a challenge by itself.
    const frame=this.documentFrame(doc);
    const cloudflareFrame=(frame?.framesInSubtree || []).some(child=>{
      if(child===frame || !URL.canParse(child.url))return false;
      const url=new URL(child.url);
      return url.origin==='https://challenges.cloudflare.com' && url.pathname.startsWith('/cdn-cgi/challenge-platform/');
    });
    const access={...doc,cloudflareFrame,cfMitigated:tab.cfMitigated===true};
    if(!options.independent)tab.challenge?.observe(access);
    return access;
  }
  async extractPaperMetadata(data,options={}) {
    if(typeof data?.wantAbstract!=='boolean')throw new BrowserFailure('navigation','document_operation_failed');
    return this.extractPaperDocument(data,{...options,metadata:true});
  }
  extractPaperPdfClues(data,options={}) {
    if(Object.hasOwn(data,'wantAbstract') || Object.hasOwn(data,'reader_access_only') && data.reader_access_only!==true)throw new BrowserFailure('navigation','document_operation_failed');
    if(Object.hasOwn(data,'prepared_source'))return this.extractEbscoSource(data,options);
    if(data.reader_access_only) {
      if(data.reader || !/^[a-f0-9]{64}$/.test(data.workspace_identity)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.paper_id)
        || !Number.isSafeInteger(data.deadline_ms))throw new BrowserFailure('navigation','document_operation_failed');
      checkCanceled(options.signal);if(Date.now()>=data.deadline_ms)throw timeoutFailure('navigation','document_operation');
      this.pinPreparedPaperAccess(data)();
      const context=this.serviceContext(data);
      const oce=!!context && new URL(context.tab.view.webContents.getURL()).hostname==='oce.ovid.com';
      return {outcome:'retrieved',reader_access:{oce}};
    }
    return this.extractPaperDocument(data,{...options,metadata:false});
  }
  async extractEbscoSource(data,options) {
    if(!['ebsco','ebsco-viewer'].includes(data.prepared_source) || data.reader || data.reader_access_only || !data.service_id
      || !Number.isSafeInteger(data.deadline_ms)
      || !/^[a-f0-9]{64}$/.test(data.workspace_identity)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.paper_id))
      throw new BrowserFailure('navigation','document_operation_failed');
    return this.resumeServiceStep(data,options,async()=>{
      const context=this.serviceContext(data);
      if(!context?.ebscoEntry)throw new BrowserFailure('authentication','service_page_required');
      const verify=this.pinPreparedPaperAccess(data,'ebsco');
      try {
        return await readEbscoSource(this,data,context,{...options,verify});
      } finally {
        context.pins.delete(this.operation);
      }
    });
  }
  async extractPaperDocument(data,options={}) {
    const bounded={...options,deadline:options.deadline ?? Date.now()+TASK_DEADLINE_MS};
    if(data.reader)return this.resumeServiceStep(data,bounded,()=>this.readPaperDocument(data,bounded));
    return this.readPaperDocument(data,bounded);
  }
  async readPaperDocument(data,{signal,deadline,onWaiting,metadata,observeReaderNavigation}) {
    if(metadata && (data.reader || Object.hasOwn(data,'reader_access_only') || Object.hasOwn(data,'prepared_source')))throw new BrowserFailure('navigation','document_operation_failed');
    const readerKind=data.reader?qualifyReader(data.reader,data.identity):null;
    const verifyAccess=this.pinPreparedPaperAccess(data,readerKind==='oce'?'oce.ovid.com':null),owner=this.operation,validateRecovery=owner.validateRecovery;
    owner.validateRecovery=async options=>{verifyAccess();await validateRecovery?.(options);verifyAccess();};
    let requestGuard,headerGuard,readerFailure,readerRequest,priorCookies,lastReaderGet;
    try {
      let doc;
      if(readerKind) {
        if(!/^[a-f0-9]{64}$/.test(data.workspace_identity)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.paper_id))throw new BrowserFailure('navigation','document_operation_failed');
        const tab=await this.newTaskPage({signal,deadline,managed:true});this.bindTaskPage(tab,signal);this.associatePage(tab,{role:'pdf-reader'});
        priorCookies=await waitFor(()=>this.sessionEvents.cookieContext(data.reader.url),signal,deadline);
        requestGuard=this.sessionEvents.subscribe('beforeRequest',details=>{
          if(details.webContentsId!==tab.id || !['mainFrame','subFrame'].includes(details.resourceType))return;
          if(signal?.aborted || Date.now()>=deadline || !publicClueURL(details.url)) {
            readerFailure=new BrowserFailure('navigation',signal?.aborted?'canceled':'pdf_target_refused');return {cancel:true};
          }
          if(details.resourceType==='mainFrame') {
            readerRequest={id:details.id,url:details.url,method:details.method,referer:null};
            if(readerKind==='sciencedirect' && details.method==='GET')lastReaderGet=readerRequest;
          }
        });
        headerGuard=this.sessionEvents.subscribe('beforeSendHeaders',details=>{
          if(details.webContentsId===tab.id && details.id===readerRequest?.id)
            readerRequest.referer=Object.entries(details.requestHeaders||{}).find(([name])=>name.toLowerCase()==='referer')?.[1] || null;
        });
        doc=await this.navigateServiceTarget(data,data.reader.url,{tab,signal,deadline,onWaiting});this.finishPageLoad(tab);
      } else doc=await this.openPaperPage(data,data.identity,{role:'article',signal,deadline,onWaiting,documentOnly:!metadata});
      const tab=this.tabs.get(doc.pageId);
      const result=await this.readDocument(tab,metadata?'extract':'pdf',{signal,deadline,identity:data.identity,
        args:metadata?{wantAbstract:data.wantAbstract}:{readerKind}});
      let pdf=result.clues;
      // Only a missing, delayed toolbar needs another snapshot. An optional
      // observation cannot erase content already captured by the original read.
      let toolbarPending=result.toolbarPending && pdf.status!=='failed';
      while(!metadata && !readerKind && !pdf.candidates.length && toolbarPending) {
        try {
          await waitFor(()=>pause(signal,200),signal,deadline,'navigation','document_operation');
          const next=await this.readDocument(tab,'pdf',{signal,deadline,identity:data.identity,args:{readerKind:null}});
          toolbarPending=next.toolbarPending && next.clues.status!=='failed';
          if(next.clues.candidates.length || next.clues.status!=='failed')pdf=next.clues;
        }catch(error){checkCanceled(signal);if(error.diagnostic?.code!=='document_changed')throw error;}
      }
      checkCanceled(signal);verifyAccess();
      if(readerKind==='sciencedirect')try {
        observeReaderNavigation?.({method:readerRequest?.method,lastGetURL:lastReaderGet?.url});
      }catch(_) {}
      const metadata_status=!result.metadata?'failed':result.diagnostics?.some(code=>
        ['date_scan_failed','abstract_candidate_failed','abstract_budget_exceeded'].includes(code))?'partial':'complete';
      // A verification POST can finish at the exact PDF that Chromium already
      // requested by GET. Preserve that observed GET and its Referer.
      const lastRequest=readerRequest;
      const retainedGet=readerKind==='sciencedirect' && lastRequest?.method==='POST' && doc.status===200 && !pdf.candidates.length
        ?matchingScienceDirectAssetGet(data.reader.identifier,lastReaderGet,pdf.landing_url):null;
      const readerCookies=readerKind && (lastRequest?.method==='GET' || retainedGet)
        ?await waitFor(()=>this.sessionEvents.cookieContext(data.reader.url),signal,deadline):null;
      let handoff=readerRequest?.method==='GET'?readerRequest:null;
      if(retainedGet)handoff=readerRequest===lastRequest && this.documentCurrent(doc)?retainedGet:null;
      return {outcome:'retrieved',...(metadata?{metadata:result.metadata,metadata_status,
          extraction_diagnostics:result.diagnostics} : {}),
        ...(readerKind && handoff?{reader_result:{url:handoff.url,referer:handoff.referer,
          context_changed:priorCookies!==readerCookies,context_key:readerCookies}}:{}),
        pdf_clues:readerKind?{...pdf,candidates:pdf.candidates.map(candidate=>({...candidate,stage:data.reader.stage,rule_id:data.reader.rule_id}))}:pdf};
    } catch(error){throw readerFailure || error;}
    finally {requestGuard?.dispose();headerGuard?.dispose();owner.validateRecovery=validateRecovery;}
  }
  serviceContext(data) {
    if(!data.service_id)return null;
    const context=this.accessContexts.get(this.accessKey(data));
    return context?.valid && !context.tab.closing && this.tabs.get(context.tab.id)===context.tab
      && !context.tab.view.webContents.isDestroyed() ? context : null;
  }
  pinPreparedPaperAccess(data,requiredHost=null) {
    const owner=this.operation;
    const scope=owner.association.service_scope?.scope_id, service=owner.association.service_id;
    const context=requiredHost?this.serviceContext(data):null;
    const verify=()=>{
      checkCanceled(owner.signal);
      if(!this.operations.has(owner) || (data.service_id ?? null)!==service || data.service_scope?.scope_id!==scope)
        throw new BrowserFailure('preparation','document_changed');
      if(data.service_entry?.unavailable_reason)throw new BrowserFailure('preparation','service_unavailable');
      if(requiredHost && (!context || this.serviceContext(data)!==context
        || requiredHost==='ebsco' && !context.ebscoEntry
        || requiredHost!=='ebsco' && new URL(context.tab.view.webContents.getURL()).hostname!==requiredHost))
        throw new BrowserFailure('preparation','document_changed');
    };
    verify();
    if(context){context.pins.add(owner);context.lastUsed=Date.now();}
    return verify;
  }
  documentFrame(doc,owner=this.operationContext.getStore()) {
    if(owner && !this.ownsPage(owner,doc.pageId))return null;
    const tab=this.tabs.get(doc.pageId);
    if (!tab || tab.pageAttempt?.retired || tab.view.webContents.isDestroyed() || tab.view.webContents.isCrashed()) return null;
    if(doc.navigationGeneration!==undefined && doc.navigationGeneration!==tab.documentGeneration)return null;
    if(doc.documentId && tab.documentIds.get(doc.frameToken)!==doc.documentId)return null;
    const frame=webFrameMain.fromFrameToken(doc.processId,doc.frameToken);
    if (!frame || frame.isDestroyed() || frame.detached) return null;
    if(doc.url!==undefined && frame.url!==doc.url)return null;
    const current=tab.view.webContents.mainFrame;
    if(doc.rootFrameToken) {
      if(current.processId!==doc.rootProcessId || current.frameToken!==doc.rootFrameToken)return null;
      const top=frame.top;
      return top?.processId===current.processId && top.frameToken===current.frameToken?frame:null;
    }
    return current.processId===doc.processId && current.frameToken===doc.frameToken?frame:null;
  }
  documentCurrent(doc) {return !!this.documentFrame(doc);}
  accessKey(data) {
    const scope=data.service_scope?.scope_id;
    if(!/^[a-f0-9]{64}$/.test(scope) || !/^svc_[a-f0-9]{32}$/.test(data.service_id))
      throw new BrowserFailure('preparation','document_changed');
    return scope+':'+data.service_id;
  }
  async replaceAccess(data) {
    const context=this.serviceContext(data);
    if(!context)return;
    if(context.pins.size || context.loan || this.pageBusy(context.tab))
      throw new BrowserFailure('navigation','navigation_active');
    context.valid=false;
    await this.closePage(context.tab,'access_replaced');
  }
  async evictFor(owner,count) {
    const bucket=this.pageBucket(owner);
    while(!this.destroying) {
      const used=this.pageBudget.usage(bucket);
      if(used.total+count<=this.pageBudget.limits.global_limit && used.scoped+count<=this.pageBudget.limits.service_limit)return;
      const scoped=used.scoped+count>this.pageBudget.limits.service_limit;
      const context=[...this.accessContexts.values()].filter(context=>context.valid && !context.pins.size && !context.loan
        && !this.pageBusy(context.tab) && !context.tab.closing && (!scoped || context.tab.resource.bucket===bucket))
        .sort((a,b)=>a.lastUsed-b.lastUsed)[0];
      if(!context)return;
      context.valid=false;await this.closePage(context.tab,'access_evicted');
    }
  }
  reconsiderAdmission() {
    if(this.destroying)return;
    if(this.capacityWork){this.capacityDirty=true;return;}
    this.capacityWork=(async()=>{
      do {
        this.capacityDirty=false;
        for(const entry of [...this.pageBudget.queue]) {
          if(!this.pageBudget.queue.includes(entry))continue;
          try {await this.evictFor(entry.owner,entry.count);this.pageBudget.drain();}
          catch(error){if(this.pageBudget.queue.includes(entry))entry.finish(error);}
        }
      }while(this.capacityDirty && !this.destroying);
    })().finally(()=>{this.capacityWork=null;});
  }
  retainAccessPage(tab,data) {
    const owner=this.operation,key=this.accessKey(data);
    if(!this.ownsPage(owner,tab.id) || tab.resourceOwner!==owner || this.accessContexts.has(key)
      || data.service_scope.scope_id!==owner.association.service_scope?.scope_id
      || data.service_id!==owner.association.service_id)
      throw new BrowserFailure('navigation','navigation_active');
    const context={kind:'access',key,tab,scopeId:data.service_scope.scope_id,serviceId:data.service_id,
      valid:true,pins:new Set(),loan:null,lastUsed:Date.now(),ebscoEntry:ebscoEntry(tab.view.webContents.getURL())};
    tab.resourceOwner=context;tab.resource.owner=context;this.accessContexts.set(key,context);
    return context;
  }
  loanWorkflowPage(tab,document) {
    const context=tab?.resourceOwner,owner=this.operation;
    if(context?.kind!=='access' || !context.valid || !this.ownsPage(owner,tab.id) || !this.documentCurrent(document))
      throw new BrowserFailure('navigation','document_changed');
    context.loan={workflow_id:owner.association.workflow_id,task_id:owner.association.task_id,
      page_id:tab.id,documentId:document.documentId,processId:document.processId,frameToken:document.frameToken};
  }
  releaseWorkflowPages(data) {
    if(!data || !['workflow_id','task_id'].every(key=>typeof data[key]==='string' && /^[a-zA-Z0-9_-]{1,128}$/.test(data[key])))
      throw Error('Invalid workflow page release');
    let released=false;
    for(const context of this.accessContexts.values())if(context.loan?.workflow_id===data.workflow_id && context.loan.task_id===data.task_id) {
      context.loan=null;context.lastUsed=Date.now();released=true;
    }
    this.pageBudget.drain();this.reconsiderAdmission();return {released};
  }
  async invalidateAccess(data) {
    if(!/^[a-f0-9]{64}$/.test(data?.scope_id) || !Array.isArray(data.service_ids)
      || data.service_ids.some(id=>!/^svc_[a-f0-9]{32}$/.test(id)))throw Error('Invalid access invalidation');
    const contexts=[...this.accessContexts.values()].filter(context=>context.scopeId===data.scope_id
      && data.service_ids.includes(context.serviceId));
    if(contexts.some(context=>context.pins.size || context.loan || this.pageBusy(context.tab)))
      throw new BrowserFailure('navigation','navigation_active');
    await Promise.all(contexts.map(context=>{context.valid=false;return this.closePage(context.tab,'access_invalidated');}));
    return {closed:contexts.length};
  }
  async resetSession() {
    this.resetting=true;
    try {
      if(this.operations.size)throw new BrowserFailure('navigation','navigation_active');
      await Promise.all([...this.tabs.values()].map(tab=>this.closePage(tab,'session_reset')));
      await Promise.all(this.failedCreations);
      await this.sessionEvents.waitForDownloads();
      await this.partition.closeAllConnections();
      await this.partition.clearData();
      await this.partition.clearAuthCache();
      this.carsiVisitOrigins.clear();
      return {ok:true};
    } finally {
      this.resetting=false;
    }
  }
  updatePageLimits(limits) {return this.pageBudget.update(limits);}
  pageBucket(owner) {
    const association=owner?.association;
    return (association?.service_scope?.scope_id || 'session')+':'+(association?.service_id || 'public');
  }
  async newTaskPage({signal=this.operation?.signal,deadline=Infinity,...options}={}) {
    const owner=this.operation;
    const validate=()=>{checkCanceled(signal);if(this.destroying || this.resetting || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');};
    await waitFor(()=>this.ready,signal,deadline);validate();
    if(!this.reservedTicket(owner))await this.evictFor(owner,1);
    const ticket=this.reservedTicket(owner) || await this.pageBudget.acquire(owner,this.pageBucket(owner),{signal,deadline,validate});
    try {validate();const tab=this.createTab({...options,present:false,pageTicket:ticket});this.bindTaskPage(tab,signal);return tab;}
    finally {if(!owner.pageTickets?.has(ticket))ticket.release();}
  }
  reservedTicket(owner) {return owner && [...(owner.pageTickets || [])].find(ticket=>!ticket.revoked && ticket.remaining>0);}
  async reserveTaskPages(count,{signal=this.operation?.signal,deadline=Infinity}={}) {
    const owner=this.operation;
    const validate=()=>{checkCanceled(signal);if(this.destroying || this.resetting || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');};
    validate();
    await this.evictFor(owner,count);validate();
    const ticket=await this.pageBudget.acquire(owner,this.pageBucket(owner),{count,signal,deadline,validate});
    owner.pageTickets ??= new Set();owner.pageTickets.add(ticket);return ticket;
  }
  async reserveChildPage({signal=this.operation?.signal,deadline=Infinity}={}) {
    if(!this.reservedTicket(this.operation))await this.reserveTaskPages(1,{signal,deadline});
    checkCanceled(signal);if(this.operation?.resourceFailure)throw this.operation.resourceFailure;
  }
  async closePage(tab,reason='task_complete') {
    if(tab.closing)return tab.closing;
    const contents=tab.view.webContents;
    const challengeCleanup=tab.challenge?.close();
    tab.closing=(async()=>{
      await Promise.all([this.sessionEvents.waitForDownloads(contents),challengeCleanup]);
      if(contents.isDestroyed()){await tab.destroyedCleanup;return;}
      const destroyed=new Promise(resolve=>contents.once('destroyed',resolve));
      tab.closeReason=reason;this.cleanupStep(()=>this.reportPage('info','page_close_requested',tab,{reason}),tab.taskOwner);
      contents.close({waitForBeforeUnload:false});await destroyed;await tab.destroyedCleanup;
    })();
    return tab.closing;
  }
  releaseOperation(owner) {
    if(owner.cleanup)return owner.cleanup;
    this.cleanupStep(()=>owner.navigationAbort?.abort(),owner);
    this.cleanupStep(()=>this.pageBudget.releaseUnused(owner),owner);
    owner.cleanup=(async()=>{
      this.endAuthentication(owner.authContext);
      const temporary=[];
      for(const tab of this.tabs.values()) {
        if(tab.navigation.current?.owner===owner)this.cleanupStep(()=>tab.navigation.finish(),owner);
        if(tab.authContext?.owner===owner)tab.authContext=null;
        if(tab.associationOwner===owner) {this.cleanupStep(()=>this.reportPage('info','page_association_released',tab),owner);tab.associationOwner=null;}
        const unsafeSource=tab.taskOwner===owner && this.sessionEvents.downloadSourceUnsafe(tab.view.webContents);
        if(tab.resourceOwner===owner || unsafeSource) {
          if(unsafeSource && tab.resourceOwner?.kind==='access'){tab.resourceOwner.valid=false;tab.resourceOwner.loan=null;}
          temporary.push(tab);
        }
        else if(tab.taskOwner===owner){this.cleanupStep(()=>tab.downloadScope?.dispose(),owner);tab.downloadScope=null;tab.downloadScopeOwner=null;tab.taskOwner=null;tab.taskSignal=null;}
        if(tab.loadOwner===owner){tab.loadOwner=null;tab.loadAllowed=false;}
      }
      const settled=await Promise.allSettled([...temporary.map(tab=>this.closePage(tab)),...(owner.creationCleanup || [])]);
      for(const context of this.accessContexts.values())context.pins.delete(owner);
      this.cleanupStep(()=>this.reconsiderAdmission(),owner);
      this.cleanupStep(()=>this.publish(),owner);
      const rejected=settled.find(value=>value.status==='rejected');
      if(rejected && (temporary.some(tab=>!tab.view.webContents.isDestroyed()) || owner.creationCleanup?.size))
        throw rejected.reason;
      this.operations.delete(owner);
      if(rejected)this.cleanupStep(()=>{throw rejected.reason;},owner);
    })();
    return owner.cleanup;
  }
  retireFailedCreation(contents,resource,owner) {
    const cleanup=(async()=>{
      await this.sessionEvents.waitForDownloads(contents);
      if(!contents.isDestroyed()) {
        const destroyed=new Promise(resolve=>contents.once('destroyed',resolve));
        contents.close({waitForBeforeUnload:false});await destroyed;
      }
      resource.release();
    })();
    this.failedCreations.add(cleanup);owner && (owner.creationCleanup ??= new Set()).add(cleanup);
    cleanup.then(()=>{this.failedCreations.delete(cleanup);owner?.creationCleanup?.delete(cleanup);},()=>{});
  }
  stopChallenges() {for(const tab of this.tabs.values())void tab.challenge?.close();}
  stopAdmission() {this.destroying=true;this.pageBudget.stop();this.stopChallenges();}
  close() {
    if(this.closing)return this.closing;
    this.stopAdmission();
    this.closing=(async()=>{
      await Promise.all([...this.operations].map(owner=>this.releaseOperation(owner)));
      for(const context of this.accessContexts.values()){context.valid=false;context.loan=null;context.pins.clear();}
      await Promise.all([...this.tabs.values()].map(tab=>this.closePage(tab,'app_exit')));
      await Promise.all(this.failedCreations);
      await this.sessionEvents.waitForDownloads();
      await this.ready.catch(()=>{});
      this.presentation.dispose();this.selected=null;
      this.documents.dispose();this.bodyActions.dispose();this.identity?.dispose();this.identity=null;
      this.sessionEvents.dispose();this.closed=true;
    })();
    return this.closing;
  }
}
module.exports={BrowserRuntime,chromiumUserAgent,configureBrowserSession};
