'use strict';
const {app, WebContentsView, session, webFrameMain, Menu, clipboard} = require('electron');
const {BrowserPresentation}=require('./browser-presentation.cjs');
const {BrowserFailure}=require('./browser-errors.cjs');
const {configureBrowserIdentity} = require('./browser-identity.cjs');
const {DocumentRuntime}=require('./document-runtime.cjs');
const {EventEmitter}=require('node:events');
const {AsyncLocalStorage}=require('node:async_hooks');
const {randomBytes}=require('node:crypto');
const {log,withLogContext,associationLogContext}=require('../shared/logging.cjs');
const {institutionAuthPage}=require('../auth/institution-auth.cjs');
const {casErrorCode}=require('../auth/cas-credentials.cjs');
const {waitFor,checkCanceled,timeoutFailure,TASK_DEADLINE_MS}=require('./browser-task.cjs');
const {NavigationRecovery,inspectPage,waitForPage}=require('./browser-navigation.cjs');
const {BrowserCooldown,PAGE_RECOVERY_MS,reportRecovery,recoveryStop,pageRecoveryDetails,origin,loadFailure}=require('./browser-recovery.cjs');
const {operationAssociation}=require('./page-association.cjs');

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
const {PartitionedCookieAdapter}=require('./partitioned-cookies.cjs');
class BrowserRuntime {
  constructor({hostWindow,solveCloudflare,readCASCredentials,isTaskRunning=()=>false,cdpURL='',recoveryTiming={}} = {}) {
    this.solveCloudflare=solveCloudflare;
    this.readCASCredentials=readCASCredentials;
    this.isTaskRunning=isTaskRunning;
    this.recoveryTiming=recoveryTiming;
    this.cooldown=new BrowserCooldown(recoveryTiming);
    this.partition = configureBrowserSession(session.fromPartition('allfold'));
    const filter={urls:['http://*/*','https://*/*']};
    this.partition.webRequest.onBeforeRequest(filter,(details,callback)=>{
      const tab=this.tabs.get(details.webContentsId);
      if(details.resourceType==='mainFrame')tab?.navigation.observeRequestStart(details);
      callback({});
    });
    this.partition.webRequest.onErrorOccurred(filter,details=>{
      const tab=this.tabs.get(details.webContentsId);
      if(details.resourceType==='mainFrame'){tab?.navigation.observeRequestFailure(details);return;}
      const netError=String(details.error || '').match(/^(?:net::)?(ERR_[A-Z0-9_]{1,80})$/)?.[1];
      if(tab)this.reportPage('debug','page_request_failed',tab,{resource_type:details.resourceType,net_error:netError,
        net_code:loadFailure(netError,details.errorCode).diagnostic.net_code});
    });
    this.attachmentCaptures=new Set();
    this.domObservations=new Set();
    this.partition.webRequest.onHeadersReceived(filter,(details,callback)=>{
      const tab=this.tabs.get(details.webContentsId);
      if(tab && !tab.pageAttempt?.retired && details.resourceType==='mainFrame') {
        const retryAfter=Object.entries(details.responseHeaders || {}).filter(([key])=>key.toLowerCase()==='retry-after')
          .flatMap(([,values])=>values);
        this.cooldown.observe(details.url,details.statusCode,retryAfter.length===1?retryAfter[0]:undefined);
      }
      for(const capture of this.attachmentCaptures) {
        if(!this.documentFrame(capture.doc,capture.owner)
          || details.webContentsId!==capture.tab.id || !['mainFrame','subFrame'].includes(details.resourceType))continue;
        const headers=Object.fromEntries(Object.entries(details.responseHeaders || {}).map(([key,value])=>
          [key.toLowerCase(),[].concat(value).join('; ')]));
        if(/attachment/i.test(headers['content-disposition'] || '')
          || /^(application\/pdf|application\/epub\+zip)(?:;|$)/i.test(headers['content-type'] || '')) {
          capture.resolve(details.url);callback({cancel:true});return;
        }
      }
      callback({});
    });
    this.tabs = new Map();
    this.paperPages=new Map();
    this.carsiVisitOrigins=new Map();
    this.documents=new DocumentRuntime(this);
    this.events = new EventEmitter();
    this.selected = null;
    this.operationContext=new AsyncLocalStorage();
    this.operations=new Set();
    this.presentation=new BrowserPresentation(hostWindow);
    this.destroying = false;
    this.cookieAdapter=new PartitionedCookieAdapter({session:this.partition,cdpURL,
      getPage:id=>this.tabs.get(id)?.view.webContents,documentCurrent:doc=>this.documentCurrent(doc)});
    this.ready = configureBrowserIdentity(this.partition, app.getPath('sessionData'),{cookieAdapter:this.cookieAdapter}).then(identity => {
      this.identity = identity;
      if (this.destroying) {identity.dispose();throw Error('Browser closed during identity initialization');}
      return identity;
    });
  }
  createTab(options = {}, opener = null) {
    if (!this.identity || this.destroying) throw Error('Browser identity is not ready');
    const view = new WebContentsView({...(options.webContents ? {webContents:options.webContents} : {}),
      webPreferences:{...options.webPreferences, session:this.partition, sandbox:true,
      contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true, webSecurity:true}});
    const contents = view.webContents;
    view.setVisible(false);
    this.presentation.initializeView(view);
    // The Session already owns the synchronous identity preload and HTTPS headers.
    contents.setUserAgent(this.partition.getUserAgent());
    const owner=opener?.taskOwner;
    const inheriting=owner && this.ownsPage(owner,opener.id);
    const tab = {id:contents.id, view, status:null, error:null, opener,managed:options.managed===true,
      pageAttempt:inheriting?opener.pageAttempt:options.pageAttempt,
      taskOwner:inheriting?owner:null,taskSignal:inheriting?opener.taskSignal:null,
      authContext:inheriting?opener.authContext:undefined,loadOwner:inheriting?opener.loadOwner:null,
      loadAllowed:inheriting?opener.loadAllowed:false};
    this.tabs.set(tab.id, tab);
    contents.setWindowOpenHandler(({url}) => {
      if(tab.pageAttempt?.retired)return {action:'deny'};
      if (url !== 'about:blank') {
        try {browserURL(url);} catch (_) {return {action:'deny'};}
      }
      return {action:'allow', overrideBrowserWindowOptions:{webPreferences:{session:this.partition,
        sandbox:true, contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true}},
        createWindow:options => this.createTab({...options,present:false},tab).view.webContents};
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
      tab.status=null;tab.paperDocument=null;
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
      if((event.isMainFrame ?? main) && !(event.isSameDocument ?? inPlace)) {
        tab.paperDocument=null;
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
      this.tabs.delete(tab.id);
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
    const frame=wc.mainFrame;
    const binding={pageId:tab.id,processId:frame.processId,frameToken:frame.frameToken};
    let state;
    const url=new URL(wc.getURL());
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
        || tab.authDocument.frameToken!==state.binding.frameToken)
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
  async checkAuthentication(tab) {
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
    if (!this.tabs.size) this.createTab();
    if(!this.selected)this.select(this.tabs.values().next().value);
    this.presentation.show();
    return this.state();
  }
  async openURL(value) {
    const url=browserURL(value);
    await this.ready;
    const tab=this.createTab({present:false});this.select(tab,{focus:true});
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
      case 'new': this.select(this.createTab({present:false}),{focus:true});break;
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
    const owner={signal,phase:'loading',solverDocuments:new Map(),association:operationAssociation(data),
      taskTab:null,navigationAbort:null};
    this.operations.add(owner);
    try {return await this.runInOperation(owner,run);}
    finally {this.releaseOperation(owner);}
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
    checkCanceled(owner.signal);
    if(tab.taskOwner && tab.taskOwner!==owner)throw new BrowserFailure('navigation','navigation_active');
    tab.taskOwner=owner;
    return owner;
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
    return {owner,controller,signal:AbortSignal.any([controller.signal,...(signal?[signal]:[])])};
  }
  retirePageAttempt(attempt) {
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
    for(const tab of pages) {
      const contents=tab.view.webContents;
      if(contents.isDestroyed())continue;
      this.reportPage('info','page_close_requested',tab);
      contents.close({waitForBeforeUnload:false});
    }
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
  beginPageLoad(tab,signal,deadline=Infinity,{fresh=false,replayable}={}) {
    this.bindTaskPage(tab,signal);tab.loadOwner=this.operation;tab.loadAllowed=true;
    const options={...this.navigationOptions(tab,{signal,deadline}),replayable};
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
    checkCanceled(signal);
    if(navigationChain && tab.navigation.current?.chain!==navigationChain)throw new BrowserFailure('navigation','document_changed');
    tab.navigation.check();
    if(tab.view.webContents.isLoadingMainFrame() || (tab.navigation.current?.active && !tab.navigation.current.loaded))
      return {doc:null,waiting:false,loading:true};
    try {return await inspectPage({signal,deadline,automaticDeadline,stage,step,solverDocuments,onWaiting,
      authentication:()=>this.checkAuthentication(tab),inspectAuthentication:()=>this.inspectAuthentication(tab),
      snapshot:()=>this.snapshot(tab),current:doc=>{
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

  async openPaperPage(data,doi,{role,signal,onWaiting,deadline=Date.now()+TASK_DEADLINE_MS}={}) {
    const {workspace_identity:workspace,paper_id:paper}=data;
    if(typeof workspace!=='string' || !/^[a-f0-9]{64}$/.test(workspace)
      || typeof paper!=='string' || !/^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(paper))
      throw Error('Invalid managed Paper identity');
    await waitFor(()=>this.ready,signal,deadline);
    checkCanceled(signal);
    const owner=this.operation,key=workspace+':'+paper.toLowerCase();
    let tab=this.paperPages.get(key),firstFailure,sourcePageId,previousOrigin;
    const target='https://doi.org/'+encodeURIComponent(doi);
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
          tab=this.createTab({present:false,managed:true,pageAttempt:attempt});
          tab.paperKey=key;
          this.paperPages.set(key,tab);
        }
        this.bindTaskPage(tab,attempt.signal);
        tab.pageAttempt=attempt;
        this.associatePage(tab,{role,doi});
        const contents=tab.view.webContents;
        const matches=doc=>this.documentCurrent(doc) && contents.getURL()===doc.url && !contents.isLoadingMainFrame();
        const previous=tab.paperDocument;
        if(previous?.doi===doi && matches(previous.doc) && !tab.navigation.current?.failure) {
          const doc=await this.waitForPage(tab,{signal:attempt.signal,deadline,
            onWaiting:(waiting,diagnostic)=>{if(waiting)onWaiting?.(diagnostic);}});
          if(tab.paperDocument===previous && matches(previous.doc) && doc.url===previous.doc.url)return doc;
        }
        tab.paperDocument=null;
        const doc=await this.navigate(target,{tab,signal:attempt.signal,deadline,onWaiting});
        if(!matches(doc) || this.paperPages.get(key)!==tab)throw new BrowserFailure('navigation','document_changed');
        this.finishPageLoad(tab);
        const {pageId,processId,frameToken,url}=doc;
        tab.paperDocument={doi,doc:{pageId,processId,frameToken,url}};
        if(index)record('recovery_succeeded',firstFailure,{page_id:tab.id,dispatch_outcome:'confirmed'});
        return doc;
      } catch(error) {
        if(index)record('recovery_exhausted',error,{page_id:tab?.id,recovery_stop:recoveryStop(error,signal)});
        if(index || !error.rebuildPage || signal?.aborted || owner.phase!=='loading'
          || !this.ownsPage(owner,tab?.id) || this.paperPages.get(key)!==tab)throw error;
        if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
        deadline=Math.min(deadline,Date.now()+PAGE_RECOVERY_MS);
        firstFailure=error;sourcePageId=tab.id;previousOrigin=origin(tab.navigation.current?.url);
        record('recovery_scheduled',error,{page_id:tab.id,dispatch_outcome:'not_dispatched'});
        this.retirePageAttempt(attempt);
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
  async snapshot(tab=this.taskTab,frame=tab?.view.webContents.mainFrame,options={}) {
    if(!tab || !this.tabs.has(tab.id))throw new BrowserFailure('navigation','page_closed');
    tab.navigation.check();
    const root=tab.view.webContents.mainFrame;
    const binding={pageId:tab.id,processId:frame.processId,frameToken:frame.frameToken};
    if(frame.processId!==root.processId || frame.frameToken!==root.frameToken)
      Object.assign(binding,{rootProcessId:root.processId,rootFrameToken:root.frameToken});
    const doc=await this.documents.call(binding,'snapshot',{},options);
    tab.navigation.check();
    if(!this.documentCurrent(binding))throw new BrowserFailure('translation','document_changed');
    return {...doc,...binding,rootURL:root.url,status:binding.rootFrameToken?undefined:tab.status};
  }
  async translationDocuments(root,options={}) {
    if(!this.documentCurrent(root))throw new BrowserFailure('translation','document_changed');
    const tab=this.tabs.get(root.pageId),documents=[];
    for(const frame of tab.view.webContents.mainFrame.framesInSubtree) {
      checkCanceled(options.signal);
      if(!/^https?:/.test(frame.url) || frame.detached || frame.isDestroyed())continue;
      try {
        const document=await this.snapshot(tab,frame,options);
        browserURL(document.url);documents.push(document);
      }
      catch(error) {
        if(!this.documentCurrent(root))throw new BrowserFailure('translation','document_changed');
        checkCanceled(options.signal);
        if(frame.processId===root.processId && frame.frameToken===root.frameToken)throw error;
        if(options.deadline && Date.now()>=options.deadline)throw error;
        log('debug','translation_frame_skipped',{page_id:root.pageId,stage:'translation',code:error.diagnostic?.code || 'document_operation_failed'});
      }
    }
    if(!this.documentCurrent(root))throw new BrowserFailure('translation','document_changed');
    return documents.length?documents:[root];
  }
  async pageCookie(doc,options={}) {
    return this.documents.call(doc,'cookie',{},options);
  }
  captureAttachment(tab,doc,{signal,deadline=Date.now()+60000}={}) {
    checkCanceled(signal);
    if(!this.operation || this.operation.action!=='import_paper' || !this.taskActive
      || !this.ownsPage(this.operation,doc.pageId) || !this.ownsPage(this.operation,tab.id) || !this.documentCurrent(doc))
      throw new BrowserFailure('attachment','document_changed');
    const owner=this.operation,source=this.tabs.get(doc.pageId).view.webContents,contents=tab.view.webContents;
    let resolve,reject,settled=false,timer;
    const url=new Promise((yes,no)=>{resolve=yes;reject=no;});url.catch(()=>{});
    const capture={tab,doc,owner,resolve:value=>finish(null,value),dispose:()=>finish(new BrowserFailure('attachment','canceled'))};
    const changed=()=>{if(!this.documentCurrent(doc))finish(new BrowserFailure('attachment','document_changed'));};
    const closed=()=>finish(new BrowserFailure('attachment','page_closed'));
    const canceled=()=>finish(new BrowserFailure('attachment','canceled'));
    const finish=(error,value)=>{
      if(settled)return;settled=true;clearTimeout(timer);this.attachmentCaptures.delete(capture);
      signal?.removeEventListener('abort',canceled);source.removeListener('did-frame-navigate',changed);
      source.removeListener('render-process-gone',closed);source.removeListener('destroyed',closed);
      contents.removeListener('destroyed',closed);
      if(error)reject(error);else resolve(value);
    };
    this.attachmentCaptures.add(capture);
    source.on('did-frame-navigate',changed);source.once('render-process-gone',closed);source.once('destroyed',closed);
    if(source!==contents)contents.once('destroyed',closed);
    signal?.addEventListener('abort',canceled,{once:true});
    timer=setTimeout(()=>finish(new BrowserFailure('attachment','timeout')),Math.max(0,deadline-Date.now()));
    return {url,dispose:capture.dispose};
  }
  async bypassAttachment(url,doc,{signal,visible=false,deadline:budgetDeadline=Infinity}={}) {
    checkCanceled(signal);
    const owner=this.operation;
    if(!owner || owner.action!=='import_paper' || !this.taskActive || !this.ownsPage(owner,doc.pageId) || !this.documentCurrent(doc))
      throw new BrowserFailure('attachment','document_changed');
    const source=this.tabs.get(doc.pageId),deadline=Math.min(budgetDeadline,Date.now()+(visible?60000:5000));
    const validate=()=>{
      if(!this.ownsPage(owner,doc.pageId) || !this.documentCurrent(doc))
        throw new BrowserFailure('attachment','document_changed');
    };
    await this.waitForCooldown(url,{signal,deadline,validate,stage:'attachment',
      step:visible?'visible_helper':'hidden_iframe',pageId:doc.pageId,
      authorize:owner.validateRecovery?waited=>waited && owner.validateRecovery({signal,deadline,stage:'attachment'}):undefined});
    checkCanceled(signal);
    validate();
    if(Date.now()>=deadline)throw timeoutFailure('attachment',visible?'visible_helper':'hidden_iframe');
    const tab=visible?this.createTab({present:false}):source,contents=tab.view.webContents;
    if(visible)this.associatePage(tab,{role:'attachment',source,doi:source.association?.doi});
    if(visible)tab.attachmentOwner=owner;
    const id='allfold-attachment-'+randomBytes(12).toString('hex');
    let capture,observing=false,again=false,solverController;
    const controller=new AbortController();
    const bounded=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
    const helperNavigated=()=>{solverController?.abort();again=true;};
    const observe=async()=>{
      if(observing){again=true;return;}
      observing=true;
      try {
        do {
          again=false;
          if(bounded.aborted || !this.ownsPage(owner,tab.id) || tab.attachmentOwner!==owner)break;
          solverController=new AbortController();
          await this.runInOperation(owner,()=>this.inspectPage(tab,{signal:AbortSignal.any([bounded,solverController.signal]),deadline,stage:'attachment',
            solveCloudflare:async(helperDoc,options)=>{
              if(!this.ownsPage(owner,tab.id) || tab.attachmentOwner!==owner
                || !this.documentCurrent(doc))return;
              return this.solveCloudflare?.(helperDoc,options);
            }}));
        }while(again);
      }catch(_) { /* Capture, deadline and manual interaction own attachment completion. */ }
      finally{observing=false;if(again && !bounded.aborted)void observe();}
    };
    try {
      capture=this.captureAttachment(tab,doc,{signal:bounded,deadline});
      if(visible) {
        tab.attachmentOwner=owner;tab.loadOwner=owner;tab.taskSignal=bounded;
        contents.on('did-navigate',helperNavigated);
        contents.on('did-stop-loading',observe);contents.on('did-navigate-in-page',observe);contents.on('page-title-updated',observe);
        void contents.loadURL(url).then(observe,()=>{});
      } else {
        const frame=this.documentFrame(doc);
        await waitFor(()=>frame.executeJavaScript('('+((target,id)=>{
          const iframe=document.createElement('iframe');iframe.id=id;iframe.style.display='none';iframe.src=target;
          document.body.appendChild(iframe);
        }).toString()+')('+JSON.stringify(url)+','+JSON.stringify(id)+')'),bounded,deadline,'attachment','hidden_iframe');
      }
      return await capture.url;
    } finally {
      controller.abort();solverController?.abort();capture?.dispose();
      if(visible) {
        contents.removeListener('did-navigate',helperNavigated);
        contents.removeListener('did-stop-loading',observe);contents.removeListener('did-navigate-in-page',observe);contents.removeListener('page-title-updated',observe);
        if(this.tabs.get(tab.id)===tab && tab.attachmentOwner===owner && !contents.isDestroyed())
          await new Promise(resolve=>{contents.once('destroyed',resolve);contents.close();});
      } else {
        // The originating operation may be canceled while its exact document is still alive.
        const frame=this.documentFrame(doc,null);
        if(frame)await frame.executeJavaScript('document.getElementById('+JSON.stringify(id)+')?.remove();void 0').catch(()=>{});
      }
    }
  }
  async observeDOM(doc,observers,{signal,deadline=Infinity}={}) {
    checkCanceled(signal);
    if(!this.documentCurrent(doc))throw new BrowserFailure('translation','document_changed');
    const id=randomBytes(16).toString('hex'),contents=this.tabs.get(doc.pageId).view.webContents;
    const cleanup=async()=>{
      if(this.documentFrame(doc,null))await this.runInOperation(null,()=>this.documents.call(doc,'dispose',{id})).catch(()=>{});
    };
    let installed;
    try {installed=await this.documents.call(doc,'observe',{id,configs:observers},{signal,deadline});}
    catch(error){await cleanup();throw error;}
    if(!installed)return null;
    const controller=new AbortController(),bounded=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
    const observation={owner:this.operation,dispose:async()=>{
      controller.abort();this.domObservations.delete(observation);await cleanup();
    }};
    observation.changed=this.documents.call(doc,'wait',{id},{signal:bounded,deadline});
    observation.changed.catch(()=>{});this.domObservations.add(observation);
    return observation;
  }
  documentFrame(doc,owner=this.operationContext.getStore()) {
    if(owner && !this.ownsPage(owner,doc.pageId))return null;
    const tab=this.tabs.get(doc.pageId);
    if (!tab || tab.pageAttempt?.retired || tab.view.webContents.isDestroyed() || tab.view.webContents.isCrashed()) return null;
    const frame=webFrameMain.fromFrameToken(doc.processId,doc.frameToken);
    if (!frame || frame.isDestroyed() || frame.detached) return null;
    const current=tab.view.webContents.mainFrame;
    if(doc.rootFrameToken) {
      if(current.processId!==doc.rootProcessId || current.frameToken!==doc.rootFrameToken)return null;
      const top=frame.top;
      return top?.processId===current.processId && top.frameToken===current.frameToken?frame:null;
    }
    return current.processId===doc.processId && current.frameToken===doc.frameToken?frame:null;
  }
  documentCurrent(doc) {return !!this.documentFrame(doc);}
  releaseOperation(owner) {
    if(!this.operations.delete(owner))return;
    owner.navigationAbort?.abort();
    for(const capture of this.attachmentCaptures)if(capture.owner===owner)capture.dispose();
    for(const observation of this.domObservations)if(observation.owner===owner)void observation.dispose();
    for(const tab of this.tabs.values()) {
      if(tab.navigation.current?.owner===owner)tab.navigation.finish();
      if(tab.authContext?.owner===owner)tab.authContext.active=false;
      if(tab.associationOwner===owner) {
        this.reportPage('info','page_association_released',tab);
        tab.associationOwner=null;
      }
      if(tab.taskOwner===owner){tab.taskOwner=null;tab.taskSignal=null;}
      if(tab.loadOwner===owner){tab.loadOwner=null;tab.loadAllowed=false;}
    }
    this.publish();
  }
  close() {
    this.destroying=true;
    for(const owner of this.operations)this.releaseOperation(owner);
    for (const tab of [...this.tabs.values()]) {
      this.reportPage('info','page_close_requested',tab,{reason:'app_exit'});tab.view.webContents.close();
    }
    this.presentation.dispose();
    this.selected=null;
    this.partition.webRequest.onBeforeRequest(null);
    this.partition.webRequest.onErrorOccurred(null);
    this.partition.webRequest.onHeadersReceived(null);
    for(const capture of this.attachmentCaptures)capture.dispose();
    for(const observation of this.domObservations)void observation.dispose();
    this.documents.dispose();
    this.cookieAdapter.dispose();
    this.identity?.dispose();
    this.identity = null;
  }
}
module.exports={BrowserRuntime,chromiumUserAgent,configureBrowserSession};
