'use strict';
const {app, WebContentsView, session, webFrameMain, Menu, clipboard} = require('electron');
const {BrowserPresentation}=require('./browser-presentation.cjs');
const {BrowserFailure,checkPage}=require('./browser-errors.cjs');
const {configureBrowserIdentity} = require('./browser-identity.cjs');
const {validDOI,articleURL,articleIdentity}=require('./article-identity.cjs');
const {DocumentRuntime}=require('./document-runtime.cjs');
const {qualifyReader,publicClueURL}=require('./pdf-clues.cjs');
const {EventEmitter}=require('node:events');
const {AsyncLocalStorage}=require('node:async_hooks');
const {randomBytes}=require('node:crypto');
const {log,withLogContext,associationLogContext}=require('../shared/logging.cjs');
const {institutionAuthPage}=require('../auth/institution-auth.cjs');
const {casErrorCode}=require('../auth/cas-credentials.cjs');
const {waitFor,pause,checkCanceled,timeoutFailure,TASK_DEADLINE_MS}=require('./browser-task.cjs');
const {NavigationRecovery,inspectPage,waitForPage}=require('./browser-navigation.cjs');
const {PAGE_RECOVERY_MS,reportRecovery,recoveryStop,pageRecoveryDetails,origin,loadFailure}=require('./browser-recovery.cjs');
const {sharedSessionEvents}=require('./session-events.cjs');
const {operationAssociation}=require('./page-association.cjs');
const {PageBudget}=require('./page-budget.cjs');

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
    this.partition = configureBrowserSession(session.fromPartition('allfold'));
    this.sessionEvents=sharedSessionEvents(this.partition,{timing:recoveryTiming});
    this.cooldown=this.sessionEvents.cooldown;
    this.sessionEvents.subscribe('beforeRequest',details=>{
      const tab=this.tabs.get(details.webContentsId);
      if(details.resourceType==='mainFrame')tab?.navigation.observeRequestStart(details);
      if(tab?.taskOwner && !tab.pageAttempt?.retired) {
        const frame=details.frame;
        this.sessionEvents.associateRequest(details.id,{...tab.taskOwner.association,
          page_id:tab.id,attempt_id:tab.pageAttempt?.id ?? tab.taskOwner.association.request_id,process_id:frame?.processId,frame_token:frame?.frameToken,
          document_id:frame?tab.documentIds.get(frame.frameToken):undefined,navigation_generation:tab.documentGeneration});
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
    this.failedCreations=new Set();
    this.carsiVisitOrigins=new Map();
    this.documents=new DocumentRuntime(this);
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
    if (!this.identity || this.destroying) throw Error('Browser identity is not ready');
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
      taskOwner:owner || null,taskSignal:inheriting?opener.taskSignal:owner?.signal || null,
      authContext:inheriting?opener.authContext:undefined,loadOwner:inheriting?opener.loadOwner:null,
      loadAllowed:inheriting?opener.loadAllowed:false};
    this.tabs.set(tab.id, tab);
    if(owner)this.trackTaskDownloads(tab,owner);
    contents.setWindowOpenHandler(({url}) => {
      if(tab.pageAttempt?.retired || contents.isDestroyed() || tab.closing)return {action:'deny'};
      const popupOwner=tab.taskOwner;
      if(popupOwner && !this.ownsPage(popupOwner,tab.id) || !popupOwner && tab.resourceOwner.kind!=='user')return {action:'deny'};
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
          return this.createTab({...options,present:false,user:!popupOwner,pageTicket:popupTicket},tab).view.webContents;
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
      tab.navigation.finish();
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
        publishLoading();
      }
    });
    contents.on('did-start-loading',publishLoading);
    contents.on('did-stop-loading',publishLoading);
    for (const name of ['page-title-updated', 'did-navigate-in-page'])
      contents.on(name, () => this.publish());
    contents.on('destroyed', () => {
      this.reportPage('info','page_closed',tab,{reason:this.destroying?'app_exit':tab.closeReason});
      tab.association=null;tab.associationOwner=null;
      tab.downloadScope?.dispose();
      this.tabs.delete(tab.id);
      const access=tab.resourceOwner?.kind==='access'?tab.resourceOwner:null;
      if(access){access.valid=false;if(this.accessContexts.get(access.key)===access)this.accessContexts.delete(access.key);this.events.emit('access-pages-closed',[tab.id]);}
      tab.destroyedCleanup=this.sessionEvents.waitForDownloads(contents).then(()=>resource.release());
      if(this.paperPages.get(tab.paperKey)===tab)this.paperPages.delete(tab.paperKey);
      if (tab.taskOwner?.taskTab === tab)tab.taskOwner.taskTab=null;
      for(const page of this.tabs.values()) {
        if(page.opener===tab)page.opener=null;
        if(page.association?.source_page_id===tab.id)
          page.association=Object.freeze({...page.association,source_page_id:null});
      }
      if (this.destroying) return;
      if (this.selected === tab) {
        this.select([...this.tabs.values()].filter(page=>!page.pageAttempt?.retired).at(-1));
      }
      this.publish();
    });
    if(opener?.association) {
      tab.association=Object.freeze({...opener.association,role:'popup',source_page_id:opener.id});
      tab.associationOwner=inheriting?owner:null;
    }
    this.reportPage('info','page_created',tab);
    if(opener?.association)this.reportPage('info','page_associated',tab);
    if(options.present!==false)this.select(tab);
    else this.publish();
    this.events.emit('tab-created',null,tab);
    return tab;
  }
  beginAuthentication(tab,signal,{institution=true}={}) {
    // Only CARSI entry and its attributable WoS handoff call this, never generic navigate().
    const owner=this.claimPage(tab,signal);
    const context={owner,signal,active:true,institution,allowCredentials:institution,origins:new Set(tab.institutionOrigins || []),
      loginSubmitted:false,failure:null};
    context.fatal=new Promise((_,reject)=>{context.reject=reject;});
    context.fatal.catch(()=>{});
    tab.authContext=context;tab.taskSignal=signal;
    return context;
  }
  authenticationFailure(tab) {
    const context=tab?.authContext;
    if(context?.active && !context.signal.aborted && context.failure)
      throw new BrowserFailure('authentication','institution_credentials_rejected');
  }
  async inspectAuthentication(tab) {
    const wc=tab.view.webContents;
    if(wc.isDestroyed())throw new BrowserFailure('navigation','page_closed');
    if(wc.isLoadingMainFrame())return {step:'loading',waiting:true};
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
    const mode=context?.active && !context.signal.aborted && !context.failure
      && (context.institution || context.origins.has(url.origin))?'institution':'page';
    try {state=carsiPage?{step:'none',waiting:false}:await frame.executeJavaScript('('+institutionAuthPage.toString()+')(...'
      +JSON.stringify(['inspect',null,null,mode])+')');}
    catch (_) {state={step:'manual',waiting:true,code:'auth_execution_failed'};}
    if(!this.documentCurrent(binding) || wc.isLoadingMainFrame())return {step:'loading',waiting:true};
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
      const origin=new URL(wc.getURL()).origin;
      // After Portal return, only the IdP origins observed in this CARSI flow may autofill.
      const permitted=context.institution || context.origins.has(origin);
      if(context.institution && origin!=='https://ds.carsi.edu.cn')context.origins.add(origin);
      tab.authState={...state,waiting:state.waiting || context.origins.has(origin)};
      if(!permitted)return;
      if(state.code==='institution_credentials_rejected') {
        context.failure=true;
        context.reject(new BrowserFailure('authentication','institution_credentials_rejected'));
        this.reportPage('info','institution_auth_failed',tab,{code:state.code});
        return;
      }
      if(!['account','login','terms','release'].includes(state.step))return;
      context.origins.add(origin);
      if(!tab.authDocument || tab.authDocument.context!==context || tab.authDocument.processId!==state.binding.processId
        || tab.authDocument.frameToken!==state.binding.frameToken || tab.authDocument.documentId!==state.binding.documentId
        || tab.authDocument.navigationGeneration!==state.binding.navigationGeneration)
        tab.authDocument={...state.binding,context,attempted:new Set()};
      const attempted=tab.authDocument.attempted;
      if(attempted.has(state.step) || state.step===context.lastAction
        || (state.step==='login' && context.loginSubmitted))return;
      let credentials=null;
      if(state.step==='login') {
        if(!context.allowCredentials || !this.readCASCredentials)return;
        try {credentials=await this.readCASCredentials();}
        catch(error) {this.reportPage('info','institution_auth_skipped',tab,{code:casErrorCode(error)});return;}
        if(!credentials || !current())return;
      }
      if(!current())return;
      // Reserve before execution: duplicate events cannot replay an action, even if navigation interrupts JS.
      attempted.add(state.step);context.lastAction=state.step;context.actionDispatched=true;
      tab.navigation.blockReplay();
      if(state.step==='login')context.loginSubmitted=true;
      const releaseUnsent=()=>{
        attempted.delete(state.step);
        if(context.lastAction===state.step)context.lastAction=null;
        if(state.step==='login')context.loginSubmitted=false;
      };
      const frame=this.documentFrame(state.binding);
      let result;
      try {result=await frame.executeJavaScript('('+institutionAuthPage.toString()+')(...'
        +JSON.stringify(['act',credentials,state.step,'institution'])+')');}
      catch (_) {this.reportPage('info','institution_auth_skipped',tab,{code:'auth_execution_failed'});return;}
      if(result?.acted===false && current())releaseUnsent();
      if(['terms','release'].includes(state.step) && result?.submission) {
        if(!current())return;
        let dispatched=false;
        try {
          const {url,body,referrer}=result.submission;
          const destination=browserURL(url),source=new URL(wc.getURL());
          if(new URL(destination).origin!==source.origin || referrer!==source.href || typeof body!=='string')
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
        context.failure=true;context.reject(new BrowserFailure('authentication','institution_credentials_rejected'));
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
    if(!context?.active || context.signal.aborted)return false;
    this.authenticationFailure(tab);
    let waiting=false;
    for(const page of this.tabs.values()) {
      if(page.authContext!==context)continue;
      await this.handleAuthentication(page);
      this.authenticationFailure(tab);
      waiting ||= page.authState?.waiting===true;
    }
    return waiting;
  }
  authenticationPortal(tab) {
    const context=tab.authContext;
    if(context) {
      context.institution=false;context.allowCredentials=false;context.lastAction=null;
      for(const page of this.tabs.values())if(page!==tab && page.authContext===context)page.authContext=null;
    }
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
        busy:this.pageBusy(tab),managed:tab.managed,
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
    return this.cooldown.wait(url,{report:this.operation?.recordRecovery,...options});
  }
  reportPage(level,event,tab,details={}) {
    const snapshot=associationLogContext(tab.association,tab.id,tab.navigation?.generation);
    // Native callbacks can run in an old async context: the saved page association is authoritative for diagnostics.
    withLogContext({},()=>log(level,event,{...snapshot,...details}));
  }
  get operation() {return this.operationContext.getStore();}
  get taskTab() {return this.operation?.taskTab ?? null;}
  get taskActive() {return !!this.operation?.taskTab;}
  async runTask(signal,data,run) {
    if(this.destroying)throw new BrowserFailure('navigation','canceled');
    const owner={signal,phase:'loading',solverDocuments:new Map(),association:operationAssociation(data),
      taskTab:null,navigationAbort:null};
    this.operations.add(owner);
    try {const result=await this.runInOperation(owner,run);if(owner.resourceFailure)throw owner.resourceFailure;return result;}
    finally {await this.releaseOperation(owner);}
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
  async inspectPage(tab,{signal,deadline=Infinity,stage='navigation',step='verification',extraWaiting,onWaiting,automaticDeadline=deadline,solveCloudflare=this.solveCloudflare,
    solverDocuments=this.operation?.solverDocuments || new Map(),navigationChain}={}) {
    checkCanceled(signal);this.checkTaskResources();
    if(navigationChain && tab.navigation.current?.chain!==navigationChain)throw new BrowserFailure('navigation','document_changed');
    tab.navigation.check();
    if(tab.view.webContents.isLoadingMainFrame() || (tab.navigation.current?.active && !tab.navigation.current.loaded))
      return {doc:null,waiting:false,loading:true};
    try {return await inspectPage({signal,deadline,automaticDeadline,stage,step,solverDocuments,onWaiting,
      authentication:()=>this.checkAuthentication(tab),inspectAuthentication:()=>this.inspectAuthentication(tab),
      probe:()=>this.accessState(tab,{signal,deadline}),current:doc=>{
        tab.navigation.check();
        if(navigationChain && tab.navigation.current?.chain!==navigationChain)throw new BrowserFailure('navigation','document_changed');
        return this.documentCurrent(doc) && !tab.view.webContents.isLoadingMainFrame()
          && !(tab.navigation.current?.active && !tab.navigation.current.loaded);
      },
      extraWaiting:doc=>!!extraWaiting?.(doc) || !!(tab.authContext?.active && tab.authContext.institution
        && new URL(doc.url).origin!=='https://ds.carsi.edu.cn'),
      solveCloudflare:this.taskActive && this.ownsPage(this.operation,tab.id)?solveCloudflare:undefined,
      onSolverFailure:()=>this.reportPage('warn','cloudflare_solver_failed',tab,{code:'solver_failed'})}).then(result=>{
        if(result.waiting && !result.loading && (result.recheck || result.diagnostic || Number.isInteger(result.doc?.status)))
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
    const solverDocuments=this.operation?.solverDocuments || new Map();
    const chain=options.navigationChain || tab.navigation.current?.chain;
    try {
      const doc=await waitForPage(()=>this.inspectPage(tab,{signal,deadline,extraWaiting,onWaiting,solverDocuments,...options,navigationChain:chain}),
        {signal,deadline,onWaiting,...options});
      if(finish && tab.navigation.current?.chain===chain)this.finishPageLoad(tab);
      return doc;
    } catch(error){if(tab.navigation.current?.chain===chain)this.finishPageLoad(tab);throw error;}
  }

  async openPaperPage(data,identity,{role,signal,onWaiting,deadline=Date.now()+TASK_DEADLINE_MS}={}) {
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
    if(paperIdentity.doi && !doi || !doi && !established)throw new BrowserFailure('navigation','article_identity_unconfirmed');
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
        const matches=doc=>this.documentCurrent(doc) && contents.getURL()===doc.url && !contents.isLoadingMainFrame();
        const previous=tab.paperDocument;
        if(previous?.identityKey===identityKey && matches(previous.doc) && !tab.navigation.current?.failure) {
          const doc=await this.waitForPage(tab,{signal:attempt.signal,deadline,
            onWaiting:(waiting,diagnostic)=>{if(waiting)onWaiting?.(diagnostic);}});
          if(tab.paperDocument===previous && matches(previous.doc) && doc.url===previous.doc.url)
            return this.confirmArticlePage(paperIdentity,doc,{signal:attempt.signal,deadline});
        }
        tab.paperDocument=null;
        const doc=await this.navigate(target,{tab,signal:attempt.signal,deadline,onWaiting});
        if(!matches(doc) || this.paperPages.get(key)!==tab)throw new BrowserFailure('navigation','document_changed');
        this.finishPageLoad(tab);
        const confirmed=await this.confirmArticlePage(paperIdentity,doc,{signal:attempt.signal,deadline});
        tab.paperDocument={identityKey,doc:confirmed};
        if(index)record('recovery_succeeded',firstFailure,{page_id:tab.id,dispatch_outcome:'confirmed'});
        return confirmed;
      } catch(error) {
        if(index)record('recovery_exhausted',error,{page_id:tab?.id,recovery_stop:recoveryStop(error,signal)});
        if(index || !error.rebuildPage || signal?.aborted || owner.phase!=='loading'
          || !this.ownsPage(owner,tab?.id) || this.paperPages.get(key)!==tab)throw error;
        if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
        deadline=Math.min(deadline,Date.now()+PAGE_RECOVERY_MS);
        firstFailure=error;sourcePageId=tab.id;previousOrigin=origin(tab.navigation.current?.url);
        record('recovery_scheduled',error,{page_id:tab.id,dispatch_outcome:'not_dispatched'});
        await this.retirePageAttempt(attempt);
        tab=null;
      }
    }
  }

  async navigate(url,{tab=this.taskTab,signal=this.operation?.signal,deadline=Infinity,onWaiting,solveCloudflare=this.solveCloudflare}={}) {
    const owner=this.operation;
    if(!this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
    await waitFor(()=>this.ready,signal,deadline);
    checkCanceled(signal);
    if(this.destroying || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');
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
      const loading=tab.navigation.dispatch(()=>tab.view.webContents.loadURL(target),
        {...this.navigationOptions(tab,{signal:bounded,deadline}),replayable:true,initialURL:target});
      chain=tab.navigation.current.chain;
      const navigation=await (tab.authContext?.active
        ?Promise.race([loading,tab.authContext.fatal]):loading);
      const doc=await this.waitForPage(tab,{signal:bounded,deadline,finish:false,navigationChain:navigation.chain,solveCloudflare,
        onWaiting:(waiting,diagnostic)=>{if(waiting)onWaiting?.(diagnostic);}});
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
    tab.navigation.check();
    const frame=tab.view.webContents.mainFrame;
    if(frame.url.length>4096)throw new BrowserFailure('navigation','page_probe_unconfirmed');
    const binding={pageId:tab.id,processId:frame.processId,frameToken:frame.frameToken,
      url:frame.url,navigationGeneration:tab.documentGeneration};
    const known=tab.documentIds.get(frame.frameToken);
    if(known)binding.documentId=known;
    const result=await this.documents.call(binding,action,options.args || {},options);
    checkCanceled(options.signal);
    tab.navigation.check();
    if(!this.documentCurrent(binding))throw new BrowserFailure('navigation','document_changed');
    tab.documentIds.set(frame.frameToken,result.documentId);
    return {...binding,...result,status:tab.status};
  }
  documentBinding(tab=this.taskTab,options={}) {return this.readDocument(tab,'binding',options);}
  accessState(tab=this.taskTab,options={}) {return this.readDocument(tab,'access',options);}
  async confirmArticlePage(target,doc,{signal,deadline=Infinity}={}) {
    checkCanceled(signal);
    const tab=this.tabs.get(doc.pageId);
    if(!this.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
    // No cached DOI or earlier navigation authorizes this use boundary.
    const access=await this.waitForPage(tab,{signal,deadline});
    if(!this.documentCurrent(doc) || access.documentId!==doc.documentId)throw new BrowserFailure('navigation','document_changed');
    const evidence=await this.readDocument(tab,'article',{signal,deadline});
    if(!this.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
    checkPage(evidence.status,evidence.access);
    if(evidence.access.markers.login)throw new BrowserFailure('navigation','article_identity_unconfirmed');
    const identity=articleIdentity(target,evidence,evidence.article);
    if(identity.outcome!=='confirmed') {
      const error=new BrowserFailure('navigation',identity.outcome==='conflict'?'article_identity_conflict':'article_identity_unconfirmed');
      error.identity=identity;throw error;
    }
    checkCanceled(signal);
    return {...evidence,identity};
  }
  async extractPaperMetadata(data,options={}) {
    if(typeof data?.wantAbstract!=='boolean')throw new BrowserFailure('navigation','document_operation_failed');
    return this.extractPaperDocument(data,{...options,metadata:true});
  }
  extractPaperPdfClues(data,options={}) {
    if(Object.hasOwn(data,'wantAbstract') || Object.hasOwn(data,'reader_access_only') && data.reader_access_only!==true)throw new BrowserFailure('navigation','document_operation_failed');
    if(data.reader_access_only) {
      if(data.reader || !/^[a-f0-9]{64}$/.test(data.workspace_identity)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.paper_id)
        || !Number.isSafeInteger(data.deadline_ms))throw new BrowserFailure('navigation','document_operation_failed');
      checkCanceled(options.signal);if(Date.now()>=data.deadline_ms)throw timeoutFailure('navigation','document_operation');
      this.pinPreparedPaperAccess(data)();
      const context=data.service_id && Number.isSafeInteger(data.target_page_id)?this.accessContexts.get(this.accessKey(data)):null;
      const oce=!!context && new URL(context.tab.view.webContents.getURL()).hostname==='oce.ovid.com';
      return {outcome:'retrieved',reader_access:{oce}};
    }
    return this.extractPaperDocument(data,{...options,metadata:false});
  }
  async extractPaperDocument(data,{signal,deadline=Date.now()+TASK_DEADLINE_MS,onWaiting,metadata}={}) {
    if(metadata && (data.reader || Object.hasOwn(data,'reader_access_only')))throw new BrowserFailure('navigation','document_operation_failed');
    const readerKind=data.reader?qualifyReader(data.reader,data.identity):null;
    const verifyAccess=this.pinPreparedPaperAccess(data,readerKind==='oce'?'oce.ovid.com':null),owner=this.operation,validateRecovery=owner.validateRecovery;
    owner.validateRecovery=async options=>{verifyAccess();await validateRecovery?.(options);verifyAccess();};
    let requestGuard,readerFailure;
    try {
      let doc;
      if(readerKind) {
        if(!/^[a-f0-9]{64}$/.test(data.workspace_identity)||!/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(data.paper_id))throw new BrowserFailure('navigation','document_operation_failed');
        const tab=await this.newTaskPage({signal,deadline,managed:true});this.bindTaskPage(tab,signal);this.associatePage(tab,{role:'pdf-reader'});
        requestGuard=this.sessionEvents.subscribe('beforeRequest',details=>{
          if(details.webContentsId!==tab.id || !['mainFrame','subFrame'].includes(details.resourceType))return;
          if(readerKind==='sciencedirect' && details.resourceType==='mainFrame'
            && new URL(details.url).hostname==='pdf.sciencedirectassets.com') {
            try {qualifyReader({...data.reader,url:details.url},data.identity);}
            catch {readerFailure=new BrowserFailure('navigation','pdf_target_refused');return {cancel:true};}
          }
          // A native inline PDF creates Chromium's internal viewer child. Keep
          // that non-HTTP child blocked without revoking its qualified public
          // main Document, which can supply the actual PDF source URL.
          const current=new URL(tab.view.webContents.getURL() || 'about:blank');
          if(readerKind==='sciencedirect' && details.resourceType==='subFrame'
            && details.url==='chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/index.html'
            && current.hostname==='pdf.sciencedirectassets.com'
            && current.protocol===new URL(data.reader.source_url).protocol
            && current.pathname.endsWith('/1-s2.0-'+data.reader.identifier+'/main.pdf'))return {cancel:true};
          if(signal?.aborted || Date.now()>=deadline || !publicClueURL(details.url)) {
            readerFailure=new BrowserFailure('navigation',signal?.aborted?'canceled':'pdf_target_refused');return {cancel:true};
          }
        });
        doc=await this.navigate(data.reader.url,{tab,signal,deadline,onWaiting});this.finishPageLoad(tab);
        // A redirect may preserve the source chain only inside this fixed reader's qualification.
        qualifyReader({...data.reader,url:doc.url},data.identity);
        const bound=await this.readDocument(tab,'article',{signal,deadline});
        checkPage(bound.status,bound.access);if(bound.access.markers.login)throw new BrowserFailure('navigation','article_identity_unconfirmed');
        doc={...bound};
      } else doc=await this.openPaperPage(data,data.identity,{role:'article',signal,deadline,onWaiting});
      const tab=this.tabs.get(doc.pageId),subject=doc.article.subject;
      if(!subject)throw new BrowserFailure('navigation','page_probe_unconfirmed');
      let result=null,metadata_status='complete';
      if(metadata)try {result=await this.readDocument(tab,'extract',{signal,deadline,args:{wantAbstract:data.wantAbstract}});
        if(result.diagnostics.some(code=>['abstract_candidate_failed','abstract_budget_exceeded'].includes(code)))metadata_status='partial';}
      catch(error){if(error.diagnostic?.code!=='document_operation_failed')throw error;metadata_status='failed';}
      let pdf;
      try {
        pdf=await this.readDocument(tab,'pdf',{signal,deadline,args:{readerKind}});
        // ScienceDirect hydrates its current-article toolbar after the first
        // usable Document. Give that fixed read a short window within the
        // original task deadline; do not navigate or renew identity/authority.
        const hydrationEnd=Math.min(deadline,Date.now()+2000);
        while(!metadata && !readerKind && pdf.clues.platform==='sciencedirect'
          && pdf.clues.status==='complete' && !pdf.clues.candidates.length && Date.now()<hydrationEnd) {
          if(!this.documentCurrent(doc)||pdf.documentId!==doc.documentId||pdf.subject!==subject)
            throw new BrowserFailure('navigation','document_changed');
          await waitFor(()=>pause(signal,Math.min(200,hydrationEnd-Date.now())),signal,deadline,'navigation','document_operation');
          pdf=await this.readDocument(tab,'pdf',{signal,deadline,args:{readerKind}});
        }
      }
      catch(error) {
        if(error.diagnostic?.code!=='document_operation_failed')throw error;
        // A local PDF scanner/DTO failure does not discard independent content.
        // The original live Document, subject and identity are still checked
        // below; this empty failure envelope cannot authorize a changed page.
        pdf={documentId:doc.documentId,subject,clues:{status:'failed',landing_url:doc.url,
          observed_at:new Date().toISOString(),platform:readerKind || 'generic',content_type:'unknown',
          identifiers:[],candidates:[],diagnostics:['pdf_parse_failed']}};
      }
      checkCanceled(signal);
      if(!this.documentCurrent(doc)||pdf.documentId!==doc.documentId||pdf.subject!==subject
        ||result&&(result.documentId!==doc.documentId||result.subject!==subject))throw new BrowserFailure('navigation','document_changed');
      // Revalidate the exact live subject after both independent reads, before normal cleanup.
      const verified=readerKind?await this.readDocument(tab,'article',{signal,deadline}):await this.confirmArticlePage(data.identity,doc,{signal,deadline});
      if(readerKind){checkPage(verified.status,verified.access);if(verified.access.markers.login)throw new BrowserFailure('navigation','article_identity_unconfirmed');qualifyReader({...data.reader,url:verified.url},data.identity);}
      if(!this.documentCurrent(doc)||verified.documentId!==doc.documentId||verified.article.subject!==subject)throw new BrowserFailure('navigation','document_changed');
      checkCanceled(signal);verifyAccess();
      if(Date.now()>=deadline)throw timeoutFailure('navigation','document_operation');
      return {outcome:'retrieved',...(metadata?{metadata:result?.metadata || null,metadata_status,
          extraction_diagnostics:result?.diagnostics || ['metadata_extraction_failed']} : {}),pdf_clues:readerKind?{...pdf.clues,candidates:pdf.clues.candidates.map(candidate=>({...candidate,stage:data.reader.stage,rule_id:data.reader.rule_id}))}:pdf.clues,
        document:{pageId:doc.pageId,processId:doc.processId,frameToken:doc.frameToken,
          documentId:doc.documentId,navigationGeneration:doc.navigationGeneration}};
    } catch(error){throw readerFailure || error;}
    finally {requestGuard?.dispose();owner.validateRecovery=validateRecovery;}
  }
  pinPreparedPaperAccess(data,requiredHost=null) {
    const owner=this.operation;
    if(!data.service_id){if(requiredHost)throw new BrowserFailure('preparation','document_changed');return ()=>{};}
    const key=this.accessKey(data),preparation=data.preparation_key,scope=data.service_scope.scope_id,
      service=data.service_id,page=data.target_page_id,manual=data.manually_confirmed;
    const context=page==null?null:this.accessContexts.get(key);
    const verify=()=>{
      checkCanceled(owner.signal);
      if(!this.operations.has(owner) || owner.association.service_id!==service || owner.association.service_scope?.scope_id!==scope
        || data.service_id!==service || data.service_scope.scope_id!==scope || data.preparation_key!==preparation || data.target_page_id!==page)
        throw new BrowserFailure('preparation','document_changed');
      if(page==null) {
        // This explicit host-captured manual policy has no retained target to pin;
        // its saved authority is still checked by the task and recovery callback.
        if(manual!==true || data.manually_confirmed!==true)throw new BrowserFailure('preparation','document_changed');
      } else if(!Number.isSafeInteger(page) || !context?.valid || context.accessKind!=='target'
        || this.accessContexts.get(key)!==context || context.preparationKey!==preparation
        || context.tab.id!==page || this.tabs.get(page)!==context.tab || context.tab.closing || context.tab.view.webContents.isDestroyed())
        throw new BrowserFailure('preparation','document_changed');
      if(requiredHost && (!context || new URL(context.tab.view.webContents.getURL()).hostname!==requiredHost))throw new BrowserFailure('preparation','document_changed');
    };
    verify();
    if(context){context.pins.add(owner);context.lastUsed=Date.now();}
    // releaseOperation retains this pin through actual temporary-page destruction.
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
  accessKey(data,kind='target') {
    const scope=data.service_scope?.scope_id;
    const identity=kind==='portal'?data.authentication_key:data.preparation_key;
    if(!scope || typeof identity!=='string' || !/^[a-f0-9]{64}$/.test(identity)
      || kind!=='portal' && !data.service_id)throw new BrowserFailure('preparation','document_changed');
    return scope+':'+(kind==='portal'?'portal':data.service_id);
  }
  async replaceAccess(data,kind='target') {
    const key=this.accessKey(data,kind);
    const contexts=[...this.accessContexts.values()].filter(context=>kind==='portal'?context.scopeId===data.service_scope.scope_id:context.key===key);
    if(contexts.some(context=>context.pins.size || context.loan || this.pageBusy(context.tab)))throw new BrowserFailure('navigation','navigation_active');
    await Promise.all(contexts.map(context=>{context.valid=false;return this.closePage(context.tab,'access_replaced');}));
  }
  pinAccessPage(tab,data) {
    const context=tab?.resourceOwner,owner=this.operation;
    if(context?.kind!=='access' || !context.valid || context.accessKind!=='portal'
      || context.scopeId!==data.service_scope?.scope_id || data.authentication_key && context.authenticationKey!==data.authentication_key)
      throw new BrowserFailure('authentication','carsi_session_expired');
    context.pins.add(owner);return context;
  }
  async evictFor(owner,count) {
    const bucket=this.pageBucket(owner);
    while(!this.destroying) {
      const used=this.pageBudget.usage(bucket);
      if(used.total+count<=this.pageBudget.limits.global_limit && used.scoped+count<=this.pageBudget.limits.service_limit)return;
      const scoped=used.scoped+count>this.pageBudget.limits.service_limit;
      const context=[...this.accessContexts.values()].filter(context=>context.valid && !context.pins.size && !context.loan
        && !this.pageBusy(context.tab) && !context.tab.closing && (!scoped || context.tab.resource.bucket===bucket))
        .sort((a,b)=>(a.accessKind==='portal')-(b.accessKind==='portal') || a.lastUsed-b.lastUsed)[0];
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
  retainAccessPage(tab,data,kind='target') {
    const owner=this.operation,key=this.accessKey(data,kind);
    if(!this.ownsPage(owner,tab.id) || tab.resourceOwner!==owner || this.accessContexts.has(key)
      || data.service_scope.scope_id!==owner.association.service_scope?.scope_id
      || kind!=='portal' && data.service_id!==owner.association.service_id)
      throw new BrowserFailure('navigation','navigation_active');
    const context={kind:'access',key,accessKind:kind,tab,scopeId:data.service_scope.scope_id,serviceId:data.service_id || null,
      preparationKey:data.preparation_key,authenticationKey:data.authentication_key,valid:true,pins:new Set(),loan:null,lastUsed:Date.now()};
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
    const hash=value=>typeof value==='string' && /^[a-f0-9]{64}$/.test(value);
    if(!data || !hash(data.scope_id) || !data.preparation_keys || typeof data.preparation_keys!=='object'
      || Array.isArray(data.preparation_keys) || Object.entries(data.preparation_keys).some(([id,key])=>!/^svc_[a-f0-9]{32}$/.test(id) || !hash(key))
      || data.authentication_key!==null && !hash(data.authentication_key))throw Error('Invalid access invalidation');
    const contexts=[...this.accessContexts.values()].filter(context=>context.scopeId===data.scope_id
      && (data.authentication_key && context.authenticationKey===data.authentication_key
        || context.serviceId && context.preparationKey===data.preparation_keys[context.serviceId]));
    if(contexts.some(context=>context.pins.size || context.loan || this.pageBusy(context.tab)))throw new BrowserFailure('navigation','navigation_active');
    await Promise.all(contexts.map(context=>{context.valid=false;return this.closePage(context.tab,'access_invalidated');}));
    return {closed:contexts.length};
  }
  async invalidateAllAccess() {
    const contexts=[...this.accessContexts.values()];
    if(contexts.some(context=>context.pins.size || context.loan || this.pageBusy(context.tab)))throw new BrowserFailure('navigation','navigation_active');
    await Promise.all(contexts.map(context=>{context.valid=false;if(context.tab.authContext)context.tab.authContext.active=false;return this.closePage(context.tab,'credentials_changed');}));
  }
  updatePageLimits(limits) {return this.pageBudget.update(limits);}
  pageBucket(owner) {
    const association=owner?.association;
    return (association?.service_scope?.scope_id || 'session')+':'+(association?.service_id || 'public');
  }
  async newTaskPage({signal=this.operation?.signal,deadline=Infinity,...options}={}) {
    const owner=this.operation;
    const validate=()=>{checkCanceled(signal);if(this.destroying || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');};
    await waitFor(()=>this.ready,signal,deadline);validate();
    if(!this.reservedTicket(owner))await this.evictFor(owner,1);
    const ticket=this.reservedTicket(owner) || await this.pageBudget.acquire(owner,this.pageBucket(owner),{signal,deadline,validate});
    try {validate();const tab=this.createTab({...options,present:false,pageTicket:ticket});this.bindTaskPage(tab,signal);return tab;}
    finally {if(!owner.pageTickets?.has(ticket))ticket.release();}
  }
  reservedTicket(owner) {return owner && [...(owner.pageTickets || [])].find(ticket=>!ticket.revoked && ticket.remaining>0);}
  async reserveTaskPages(count,{signal=this.operation?.signal,deadline=Infinity}={}) {
    const owner=this.operation;
    const validate=()=>{checkCanceled(signal);if(this.destroying || !this.operations.has(owner))throw new BrowserFailure('navigation','canceled');};
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
    tab.closing=(async()=>{
      await this.sessionEvents.waitForDownloads(contents);
      if(contents.isDestroyed())return;
      const destroyed=new Promise(resolve=>contents.once('destroyed',resolve));
      tab.closeReason=reason;this.reportPage('info','page_close_requested',tab,{reason});
      contents.close({waitForBeforeUnload:false});await destroyed;await tab.destroyedCleanup;
    })();
    return tab.closing;
  }
  releaseOperation(owner) {
    if(owner.cleanup)return owner.cleanup;
    this.operations.delete(owner);owner.navigationAbort?.abort();this.pageBudget.releaseUnused(owner);
    owner.cleanup=(async()=>{
      const temporary=[];
      for(const tab of this.tabs.values()) {
        if(tab.navigation.current?.owner===owner)tab.navigation.finish();
        if(tab.authContext?.owner===owner)tab.authContext.active=false;
        if(tab.associationOwner===owner) {this.reportPage('info','page_association_released',tab);tab.associationOwner=null;}
        const unsafeSource=tab.taskOwner===owner && this.sessionEvents.downloadSourceUnsafe(tab.view.webContents);
        if(tab.resourceOwner===owner || unsafeSource) {
          if(unsafeSource && tab.resourceOwner?.kind==='access'){tab.resourceOwner.valid=false;tab.resourceOwner.loan=null;}
          temporary.push(tab);
        }
        else if(tab.taskOwner===owner){tab.downloadScope?.dispose();tab.downloadScope=null;tab.downloadScopeOwner=null;tab.taskOwner=null;tab.taskSignal=null;}
        if(tab.loadOwner===owner){tab.loadOwner=null;tab.loadAllowed=false;}
      }
      await Promise.all([...temporary.map(tab=>this.closePage(tab)),...(owner.creationCleanup || [])]);
      for(const context of this.accessContexts.values())context.pins.delete(owner);
      this.reconsiderAdmission();this.publish();
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
  stopAdmission() {this.destroying=true;this.pageBudget.stop();}
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
      this.documents.dispose();this.identity?.dispose();this.identity=null;
      this.sessionEvents.dispose();this.closed=true;
    })();
    return this.closing;
  }
}
module.exports={BrowserRuntime,chromiumUserAgent,configureBrowserSession};
