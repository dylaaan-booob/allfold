'use strict';
const {app, BrowserWindow, WebContentsView, session, ipcMain, webFrameMain, Menu, clipboard, dialog} = require('electron');
const path = require('node:path');
const {NATIVE_UI_DIR,PRELOAD_DIR}=require('../shared/paths.cjs');
const {pathToFileURL} = require('node:url');
const {BrowserFailure}=require('./browser-errors.cjs');
const {configureBrowserIdentity} = require('./browser-identity.cjs');
const {DocumentRuntime}=require('./document-runtime.cjs');
const {EventEmitter}=require('node:events');
const {randomBytes}=require('node:crypto');
const {log,withLogContext,associationLogContext}=require('../shared/logging.cjs');
const {institutionAuthPage}=require('../auth/institution-auth.cjs');
const {casErrorCode}=require('../auth/cas-credentials.cjs');
const {waitFor,checkCanceled}=require('./browser-task.cjs');
const {NavigationRecovery,inspectPage,waitForPage}=require('./browser-navigation.cjs');
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
  constructor({solveCloudflare,readCASCredentials,isTaskRunning=()=>false,cdpURL=''} = {}) {
    this.solveCloudflare=solveCloudflare;
    this.readCASCredentials=readCASCredentials;
    this.isTaskRunning=isTaskRunning;
    this.cacheSize=null;
    this.partition = configureBrowserSession(session.fromPartition('allfold'));
    this.partition.webRequest.onErrorOccurred({urls:['http://*/*','https://*/*']},details=>{
      if(details.resourceType==='mainFrame')return;
      const tab=this.tabs.get(details.webContentsId);
      if(tab)this.reportPage('debug','page_request_failed',tab,{resource_type:details.resourceType,net_error:String(details.error || '').match(/^(?:net::)?(ERR_[A-Z0-9_]{1,80})$/)?.[1]});
    });
    this.attachmentCaptures=new Set();
    this.domObservations=new Set();
    this.partition.webRequest.onHeadersReceived({urls:['http://*/*','https://*/*']},(details,callback)=>{
      for(const capture of this.attachmentCaptures) {
        if(capture.owner!==this.operation || !this.taskActive || !this.documentCurrent(capture.doc)
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
    this.documents=new DocumentRuntime(this);
    this.events = new EventEmitter();
    this.selected = null;
    this.taskTab = null;
    this.taskActive = false;
    this.window = null;
    this.destroying = false;
    this.cookieAdapter=new PartitionedCookieAdapter({session:this.partition,cdpURL,
      getPage:id=>this.tabs.get(id)?.view.webContents,documentCurrent:doc=>this.documentCurrent(doc)});
    this.ready = configureBrowserIdentity(this.partition, app.getPath('sessionData'),{cookieAdapter:this.cookieAdapter}).then(identity => {
      this.identity = identity;
      if (this.destroying) {identity.dispose();throw Error('Browser closed during identity initialization');}
      return identity;
    });
    this.shellURL = pathToFileURL(path.join(NATIVE_UI_DIR, 'browser.html')).href;
    ipcMain.handle('browser:command', (event, command) => {
      if (!this.window || event.sender !== this.window.webContents
        || event.senderFrame !== event.sender.mainFrame || event.senderFrame.url !== this.shellURL)
        throw Error('Untrusted Browser command sender');
      return this.command(command);
    });
  }
  ensureWindow() {
    if (this.window) return;
    this.window = new BrowserWindow({width:1200, height:850, show:false, title:'Browser — Allfold',
      webPreferences:{preload:path.join(PRELOAD_DIR, 'browser-preload.cjs'), sandbox:true,
        contextIsolation:true, nodeIntegration:false, webSecurity:true, partition:'browser-chrome'}});
    this.window.webContents.setWindowOpenHandler(() => ({action:'deny'}));
    this.window.webContents.on('will-navigate', event => event.preventDefault());
    this.window.webContents.on('did-finish-load', () => {
      this.publish();
      void this.refreshCacheSize().catch(()=>log('warn','browser_cache_failed',{code:'cache_size_failed'}));
    });
    this.window.on('resize', () => this.layout());
    this.window.on('close', event => {
      if (!this.destroying) {event.preventDefault();this.window.hide();}
    });
    void this.window.loadURL(this.shellURL);
  }
  createTab(options = {}, opener = null) {
    if (!this.identity || this.destroying) throw Error('Browser identity is not ready');
    this.ensureWindow();
    const view = new WebContentsView({...(options.webContents ? {webContents:options.webContents} : {}),
      webPreferences:{...options.webPreferences, session:this.partition, sandbox:true,
      contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true, webSecurity:true}});
    const contents = view.webContents;
    // The Session already owns the synchronous identity preload and HTTPS headers.
    contents.setUserAgent(this.partition.getUserAgent());
    const tab = {id:contents.id, view, status:null, error:null, opener,taskSignal:opener?.taskSignal,authContext:opener?.authContext,
      loadOwner:opener?.loadOwner,loadAllowed:opener?.loadAllowed};
    this.tabs.set(tab.id, tab);
    contents.setWindowOpenHandler(({url}) => {
      if (url !== 'about:blank') {
        try {browserURL(url);} catch (_) {return {action:'deny'};}
      }
      return {action:'allow', overrideBrowserWindowOptions:{webPreferences:{session:this.partition,
        sandbox:true, contextIsolation:true, nodeIntegration:false, nodeIntegrationInSubFrames:true}},
        createWindow:options => this.createTab(options,tab).view.webContents};
    });
    const guard = (event, url) => {
      if (url === 'about:blank') return;
      try {browserURL(url);} catch (_) {event.preventDefault();}
    };
    contents.on('will-navigate', guard);
    contents.on('will-redirect', guard);
    tab.navigation=new NavigationRecovery(tab,{options:()=>this.navigationOptions(tab),
      changed:()=>this.publish(),report:(level,event,details)=>this.reportPage(level,event,tab,details)});
    contents.on('render-process-gone', (_event, details) => {
      if(this.destroying)return;
      if(tab.navigation.current)tab.navigation.current.failure=new BrowserFailure('navigation','renderer_gone');
      tab.navigation.finish();
      tab.status=null;
      tab.error={kind:'renderer',reason:details.reason,exitCode:details.exitCode};
      this.reportPage('warn','page_renderer_gone',tab,{reason:details.reason,exit_code:details.exitCode});
      tab.association=null;tab.associationOwner=null;
      this.publish();
    });
    contents.on('context-menu', (_event, params) => {
      const template=[
        {label:'后退',enabled:contents.navigationHistory.canGoBack(),click:()=>{void this.command({action:'back',id:tab.id}).catch(()=>{});}},
        {label:'前进',enabled:contents.navigationHistory.canGoForward(),click:()=>{void this.command({action:'forward',id:tab.id}).catch(()=>{});}},
        {label:'刷新',click:()=>{void this.command({action:'reload',id:tab.id}).catch(()=>{});}},
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
      Menu.buildFromTemplate(template).popup({window:this.window});
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
    for (const name of ['page-title-updated', 'did-navigate-in-page', 'did-start-loading', 'did-stop-loading'])
      contents.on(name, () => this.publish());
    contents.on('destroyed', () => {
      this.reportPage('info','page_closed',tab,{reason:this.destroying?'app_exit':tab.closeReason});
      tab.association=null;tab.associationOwner=null;
      this.tabs.delete(tab.id);
      if (this.taskTab === tab) this.taskTab=null;
      if (this.importPage === tab) this.importPage=null;
      // Keep the task's initialization marker: closing A must not replay login for B.
      if (this.carsiPortal?.id === tab.id) this.carsiPortal={task:this.carsiPortal.task,id:null};
      if (this.wosDocument?.pageId === tab.id) this.wosDocument=null;
      for(const page of this.tabs.values()) {
        if(page.opener===tab)page.opener=null;
        if(page.association?.source_page_id===tab.id)
          page.association=Object.freeze({...page.association,source_page_id:null});
      }
      if (this.destroying) return;
      if (this.selected === tab) {
        this.window.contentView.removeChildView(tab.view);
        this.selected=null;this.select([...this.tabs.values()].at(-1));
      }
      this.publish();
    });
    if(opener?.association) {
      tab.association=Object.freeze({...opener.association,role:'popup',source_page_id:opener.id});
      tab.associationOwner=opener.associationOwner===this.operation?this.operation:null;
    }
    this.reportPage('info','page_created',tab);
    if(opener?.association)this.reportPage('info','page_associated',tab);
    if(options.present!==false || !this.selected)this.select(tab);
    this.events.emit('tab-created',null,tab);
    return tab;
  }
  beginAuthentication(tab,signal,{institution=true}={}) {
    // Only CARSI entry and its attributable WoS handoff call this, never generic navigate().
    const context={signal,active:true,institution,origins:new Set(tab.institutionOrigins || []),
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
    if(!context?.active || context.signal.aborted || context.failure || this.destroying || wc.isDestroyed())return;
    const operation=(async()=>{
      const state=await this.inspectAuthentication(tab);
      const current=()=>context.active && !context.signal.aborted && !context.failure
        && tab.authContext===context && !this.destroying && this.documentCurrent(state.binding)
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
        if(!this.readCASCredentials)return;
        try {credentials=await this.readCASCredentials();}
        catch(error) {this.reportPage('info','institution_auth_skipped',tab,{code:casErrorCode(error)});return;}
        if(!credentials || !current())return;
      }
      if(!current())return;
      // Reserve before execution: duplicate events cannot replay an action, even if navigation interrupts JS.
      attempted.add(state.step);context.lastAction=state.step;
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
    })();
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
      context.institution=false;context.loginSubmitted=false;context.lastAction=null;
      for(const page of this.tabs.values())if(page!==tab && page.authContext===context)page.authContext=null;
    }
  }
  select(tab) {
    if (this.selected) this.window.contentView.removeChildView(this.selected.view);
    this.selected = tab || null;
    if (tab) this.window.contentView.addChildView(tab.view);
    this.layout();this.publish();
  }
  layout() {
    if (!this.selected) return;
    const [width,height] = this.window.getContentSize();
    this.selected.view.setBounds({x:0,y:92,width,height:Math.max(1,height-92)});
  }
  state() {
    return {selected:this.selected?.id || null,cacheSize:this.cacheSize,taskRunning:this.isTaskRunning(),
      tabs:[...this.tabs.values()].map(tab => {
      const wc=tab.view.webContents;
      return {id:tab.id,title:wc.getTitle() || 'New tab',url:wc.getURL(),loading:wc.isLoading(),
        busy:this.taskActive && this.taskTab === tab,error:tab.error,
        back:wc.navigationHistory.canGoBack(),forward:wc.navigationHistory.canGoForward()};
    })};
  }
  publish() {
    if (this.window && !this.window.isDestroyed()) this.window.webContents.send('browser:state',this.state());
  }
  async show() {
    await this.ready;
    this.ensureWindow();
    if (!this.tabs.size) this.createTab();
    this.window.show();
    return this.state();
  }
  async openURL(value) {
    const url=browserURL(value);
    await this.ready;
    const tab=this.createTab();
    this.window.show();
    await tab.navigation.dispatch(()=>tab.view.webContents.loadURL(url),{});
    return tab;
  }
  async refreshCacheSize() {
    this.cacheSize=await this.partition.getCacheSize();
    this.publish();
  }
  async command(command) {
    await this.ready;
    if (!command || typeof command !== 'object') throw Error('Invalid Browser command');
    const tab = command.id == null ? this.selected : this.tabs.get(command.id);
    if (command.id != null && !tab && !['state','new'].includes(command.action)) throw Error('Unknown tab');
    switch (command.action) {
      case 'state': break;
      case 'new': this.createTab();break;
      case 'select': if (!this.tabs.has(command.id)) throw Error('Unknown tab');this.select(tab);break;
      case 'close':
        if (tab && this.taskActive && tab === this.taskTab) throw Error('The active task page cannot be closed');
        if(tab){tab.closeReason='user';this.reportPage('info','page_close_requested',tab,{reason:'user'});tab.view.webContents.close();}break;
      case 'navigate':
        if (!tab) throw Error('No Browser tab');
        tab.authContext=null;
        await tab.navigation.dispatch(()=>tab.view.webContents.loadURL(browserURL(command.url)),this.navigationOptions(tab));break;
      case 'back': if(tab?.view.webContents.navigationHistory.canGoBack())
        tab.navigation.history(()=>tab.view.webContents.navigationHistory.goBack(),this.navigationOptions(tab));break;
      case 'forward': if(tab?.view.webContents.navigationHistory.canGoForward())
        tab.navigation.history(()=>tab.view.webContents.navigationHistory.goForward(),this.navigationOptions(tab));break;
      case 'reload': if(tab){tab.navigation.begin({...this.navigationOptions(tab),resume:true});tab.navigation.track(()=>tab.view.webContents.reload());}break;
      case 'devtools': tab?.view.webContents.openDevTools({mode:'detach'});break;
      case 'cache-size': await this.refreshCacheSize();break;
      case 'clear-cache':
      case 'clear-site-data': {
        if(this.isTaskRunning())throw Error('Browser task is running');
        const siteData=command.action==='clear-site-data';
        if(siteData) {
          const answer=await dialog.showMessageBox(this.window,{type:'warning',
            title:'清除站点数据',message:'清除浏览器中所有站点的数据？',
            detail:'将清除 Cookie、Local Storage、IndexedDB、缓存和 HTTP 认证状态，可能导致网站退出登录。不会删除下载文件或下载历史。',
            buttons:['取消','清除站点数据'],defaultId:0,cancelId:0,noLink:true});
          if(answer.response!==1)break;
        }
        if(this.isTaskRunning())throw Error('Browser task is running');
        await this.partition.clearCache();
        await this.partition.clearCodeCaches({});
        if(siteData) {
          await this.partition.clearStorageData();
          await this.partition.clearAuthCache();
        } else await this.partition.clearStorageData({storages:['cachestorage','serviceworkers','shadercache']});
        await this.refreshCacheSize();
        break;
      }
      default: throw Error('Unknown Browser command');
    }
    return this.state();
  }
  reportPage(level,event,tab,details={}) {
    const snapshot=associationLogContext(tab.association,tab.id,tab.navigation?.generation);
    // Native callbacks can run in an old async context: the saved page association is authoritative for diagnostics.
    withLogContext({},()=>log(level,event,{...snapshot,...details,
      ...(typeof details.code==='number'?{net_code:details.code,code:undefined}:{})}));
  }
  beginOperation(signal,data={}) {
    this.operation={signal,phase:'loading',solverDocuments:new Map(),association:operationAssociation(data)};
    this.taskTab=null;this.taskActive=false;
  }
  associatePage(tab,{role,source=null,service=true,doi=null}={}) {
    if(this.tabs.get(tab?.id)!==tab || tab.view.webContents.isDestroyed())
      throw new BrowserFailure('navigation','page_closed');
    const association=this.operation?.association || operationAssociation();
    if(tab.association)this.reportPage('info','page_association_replaced',tab);
    tab.association=Object.freeze({...association,service_id:service?association.service_id:null,
      role,doi,source_page_id:source && source!==tab && this.tabs.get(source.id)===source?source.id:null});
    tab.associationOwner=this.operation || null;
    this.reportPage('info','page_associated',tab);
  }
  pageAssociation(id) {
    const tab=this.tabs.get(id);
    if(!tab?.association || tab.view.webContents.isDestroyed())return null;
    return Object.freeze({page_id:id,...tab.association,
      active:!!(this.taskActive && this.operation && tab.associationOwner===this.operation && !this.operation.signal?.aborted)});
  }
  servicePages(scopeId,serviceId) {
    return [...this.tabs.values()].filter(tab=>tab.association?.service_scope?.scope_id===scopeId
      && tab.association?.service_id===serviceId).map(tab=>this.pageAssociation(tab.id)).filter(Boolean);
  }
  bindTaskPage(tab,signal=this.operation?.signal) {
    checkCanceled(signal);
    if(this.destroying || this.tabs.get(tab?.id)!==tab || tab.view.webContents.isDestroyed())
      throw new BrowserFailure('navigation','page_closed');
    this.taskTab=tab;this.taskActive=true;tab.taskSignal=signal;
  }
  navigationOptions(tab,{signal,deadline}={}) {
    const owner=this.operation;
    const automatic=this.taskActive && (this.taskTab===tab || (owner && tab.loadOwner===owner) || (tab.opener && tab.opener===this.taskTab));
    return {automatic,owner:automatic?(owner || tab.taskSignal || tab):null,
      signal:automatic?(signal || tab.taskSignal || owner?.signal):undefined,
      deadline:automatic?(deadline ?? tab.navigation?.current?.deadline ?? Infinity):Infinity,
      enabled:!this.destroying && (!automatic || (owner?.phase!=='business' && tab.loadAllowed!==false))};
  }
  beginPageLoad(tab,signal,deadline=Infinity,{fresh=false}={}) {
    this.bindTaskPage(tab,signal);tab.loadOwner=this.operation;tab.loadAllowed=true;
    const options=this.navigationOptions(tab,{signal,deadline});
    return fresh?tab.navigation.begin(options):tab.navigation.adopt(options);
  }
  finishPageLoad(tab=this.taskTab) {if(tab){tab.loadAllowed=false;tab.navigation.finish();}}
  enterBusiness() {
    if(this.operation)this.operation.phase='business';
    for(const tab of this.tabs.values())if(tab.navigation.current?.automatic)tab.navigation.finish();
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
      solveCloudflare:this.taskActive && (!this.operation || !this.operation.signal?.aborted)?solveCloudflare:undefined,
      onSolverFailure:()=>this.reportPage('warn','cloudflare_solver_failed',tab,{code:'solver_failed'})});
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

  async navigate(url,{tab=this.taskTab,signal=this.operation?.signal,deadline=Infinity,onWaiting,solveCloudflare=this.solveCloudflare}={}) {
    const owner=this.operation;
    await waitFor(()=>this.ready,signal,deadline);
    checkCanceled(signal);
    if(this.destroying)throw new BrowserFailure('navigation','canceled');
    if(this.navigationAbort)throw new BrowserFailure('navigation','navigation_active');
    const target=browserURL(url);
    if(owner!==this.operation)throw new BrowserFailure('navigation','canceled');
    if(!tab) {
      if(owner)throw new BrowserFailure('navigation','page_closed');
      tab=this.createTab({present:false});
    }
    this.bindTaskPage(tab,signal);
    const controller=new AbortController();
    const cancel=()=>controller.abort(signal.reason);
    signal?.addEventListener('abort',cancel,{once:true});
    this.navigationAbort=controller;
    tab.taskSignal=signal || controller.signal;tab.loadOwner=owner;tab.loadAllowed=true;
    let chain;
    try {
      const loading=tab.navigation.dispatch(()=>tab.view.webContents.loadURL(target),
        this.navigationOptions(tab,{signal:signal || controller.signal,deadline}));
      chain=tab.navigation.current.chain;
      const navigation=await (tab.authContext?.active
        ?Promise.race([loading,tab.authContext.fatal]):loading);
      const doc=await this.waitForPage(tab,{signal:controller.signal,deadline,finish:false,navigationChain:navigation.chain,solveCloudflare,
        onWaiting:waiting=>{if(waiting)onWaiting?.();}});
      this.reportPage('info','navigation_ready',tab,{stage:'navigation',code:'page_ready',status:doc.status});
      return doc;
    } catch(error) {
      if(tab.navigation.current?.chain===chain) {
        tab.navigation.current.failure ||= error;
        this.finishPageLoad(tab);
        if(!tab.view.webContents.isDestroyed() && tab.view.webContents.isLoadingMainFrame())tab.view.webContents.stop();
      }
      throw error;
    } finally {
      signal?.removeEventListener('abort',cancel);
      if(this.navigationAbort===controller)this.navigationAbort=null;
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
      || !this.documentCurrent(doc) || this.tabs.get(tab.id)!==tab)
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
  async bypassAttachment(url,doc,{signal,visible=false}={}) {
    checkCanceled(signal);
    const owner=this.operation;
    if(!owner || owner.action!=='import_paper' || !this.taskActive || !this.documentCurrent(doc))
      throw new BrowserFailure('attachment','document_changed');
    const source=this.tabs.get(doc.pageId),deadline=Date.now()+(visible?60000:5000);
    const tab=visible?this.createTab():source,contents=tab.view.webContents;
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
          if(bounded.aborted || this.operation!==owner || tab.attachmentOwner!==owner)break;
          solverController=new AbortController();
          await this.inspectPage(tab,{signal:AbortSignal.any([bounded,solverController.signal]),deadline,stage:'attachment',
            solveCloudflare:async(helperDoc,options)=>{
              if(this.operation!==owner || owner.action!=='import_paper' || tab.attachmentOwner!==owner
                || !this.documentCurrent(doc))return;
              return this.solveCloudflare?.(helperDoc,options);
            }});
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
        this.window.show();
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
      } else if(this.documentCurrent(doc)) {
        await this.documentFrame(doc).executeJavaScript('document.getElementById('+JSON.stringify(id)+')?.remove();void 0').catch(()=>{});
      }
    }
  }
  async observeDOM(doc,observers,{signal,deadline=Infinity}={}) {
    checkCanceled(signal);
    if(!this.documentCurrent(doc))throw new BrowserFailure('translation','document_changed');
    const id=randomBytes(16).toString('hex'),contents=this.tabs.get(doc.pageId).view.webContents;
    const cleanup=async()=>{
      if(this.documentCurrent(doc))await this.documents.call(doc,'dispose',{id}).catch(()=>{});
    };
    let installed;
    try {installed=await this.documents.call(doc,'observe',{id,configs:observers},{signal,deadline});}
    catch(error){await cleanup();throw error;}
    if(!installed)return null;
    const controller=new AbortController(),bounded=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
    const observation={dispose:async()=>{
      controller.abort();this.domObservations.delete(observation);await cleanup();
    }};
    observation.changed=this.documents.call(doc,'wait',{id},{signal:bounded,deadline});
    observation.changed.catch(()=>{});this.domObservations.add(observation);
    return observation;
  }
  documentFrame(doc) {
    const tab=this.tabs.get(doc.pageId);
    if (!tab || tab.view.webContents.isDestroyed() || tab.view.webContents.isCrashed()) return null;
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
  endTask() {
    for(const capture of this.attachmentCaptures)capture.dispose();
    for(const observation of this.domObservations)void observation.dispose();
    for(const tab of this.tabs.values())if(tab.navigation.current?.automatic)tab.navigation.finish();
    for(const tab of this.tabs.values())if(this.operation && tab.associationOwner===this.operation)
      this.reportPage('info','page_association_released',tab);
    this.operation=null;
    for(const tab of this.tabs.values()) {
      if(tab.authContext)tab.authContext.active=false;
      tab.associationOwner=null;tab.taskSignal=null;tab.loadOwner=null;tab.loadAllowed=false;
    }
    this.taskTab=null;this.taskActive=false;this.publish();
  }
  close() {
    this.navigationAbort?.abort();
    this.destroying=true;
    for (const tab of [...this.tabs.values()]) {
      this.reportPage('info','page_close_requested',tab,{reason:'app_exit'});tab.view.webContents.close();
    }
    this.taskTab=null;this.importPage=null;this.carsiPortal=null;this.wosDocument=null;this.operation=null;
    this.window?.destroy();
    this.selected=null;this.taskActive=false;
    this.partition.webRequest.onErrorOccurred(null);
    this.partition.webRequest.onHeadersReceived(null);
    for(const capture of this.attachmentCaptures)capture.dispose();
    for(const observation of this.domObservations)void observation.dispose();
    this.documents.dispose();
    this.cookieAdapter.dispose();
    this.identity?.dispose();
    this.identity = null;
    ipcMain.removeHandler('browser:command');
  }
}
module.exports={BrowserRuntime,chromiumUserAgent,configureBrowserSession};
