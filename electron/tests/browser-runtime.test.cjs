'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const hostRequire=require('node:module').createRequire(require.resolve('../src/browser/browser-runtime.cjs'));
const {EventEmitter}=require('node:events');
const os=require('node:os');
const {BrowserFailure,checkPage}=require('../src/browser/browser-errors.cjs');
const {institutionAuthPage}=require('../src/auth/institution-auth.cjs');
const chromiumVersion='123.4.5.6';
const serviceScope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
const serviceId='svc_'+'1'.repeat(32);
function networkFailure(partition,contents,{id,url,method='GET'}) {
  const request={id,url,method,webContentsId:contents.id,resourceType:'mainFrame'};
  partition.requestHook(request,details=>assert.deepEqual(Object.keys(details),[]));
  partition.errorHook({...request,error:'net::ERR_CONNECTION_CLOSED'});
}
function fixture(t) {
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-browser-runtime-test-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  let sequence=0,frameSequence=0,failCreation=false;
  const frames=new Map();
  const handlers=new Map();
  const logs=[],menus=[];
  const partition={ua:`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 allfold-desktop/1.0.0 Chrome/${chromiumVersion} Electron/1.0.0 Safari/537.36`,
    webRequest:{onBeforeSendHeaders(filter,fn){partition.headerHook=fn;},
      onBeforeRequest(filter,fn){partition.requestHook=fn;},
      onErrorOccurred(filter,fn){partition.errorHook=fn;},onHeadersReceived(filter,fn){partition.responseHook=fn;}},
    registerPreloadScript(script){this.preload=script;return 'identity';},unregisterPreloadScript(){this.preload=null;},
    async getCacheSize(){return 0;},
    getUserAgent(){return this.ua;},setUserAgent(ua){this.ua=ua;},setPermissionRequestHandler(){},setPermissionCheckHandler(){}};
  class Contents extends EventEmitter {
    constructor(){super();this.id=++sequence;this.url='';this.replaceFrame();this.on('did-navigate',()=>this.replaceFrame());
      this.on('did-start-navigation',(_event,_url,_same,main,processId,routingId)=>{
        if(main && Number.isInteger(processId) && processId>=0 && Number.isInteger(routingId) && routingId>=0)
          Object.assign(this.mainFrame,{processId,routingId});
      });this.navigationHistory={canGoBack:()=>false,canGoForward:()=>false};}
    replaceFrame(){this.mainFrame={url:this.url,processId:100,frameToken:String(++frameSequence),routingId:frameSequence,
      isDestroyed:()=>!!this.destroyed,detached:false,
      executeJavaScript:async code=>this.runAuth?this.runAuth(code):{step:'none',waiting:false}};frames.set(this.mainFrame.frameToken,this.mainFrame);}
    setWindowOpenHandler(fn){this.popup=fn;}
    setUserAgent(ua){this.ua=ua;}
    getURL(){return this.url;}
    getZoomFactor(){return this.zoomFactor ?? 1;}
    getTitle(){return this.url;}
    isLoading(){return false;}
    isLoadingMainFrame(){return !!this.loading;}
    isDestroyed(){return !!this.destroyed;}
    isCrashed(){return false;}
    stop(){this.stopped=true;}
    reload(){this.reloads=(this.reloads || 0)+1;this.emit('did-start-navigation',{},this.url || 'https://example.org/',false,true);}
    send(channel,value){this.messages ||= [];this.messages.push({channel,value});}
    focus(){this.focused=(this.focused || 0)+1;}
    async loadURL(url){
      if(this.modernNavigation)this.emit('did-start-navigation',{url,isMainFrame:true,isSameDocument:false});
      else this.emit('did-start-navigation',{},url,false,true);
      this.url=url;this.mainFrame.url=url;this.emit('did-navigate',{},url,200);this.emit('did-frame-navigate',{},url,200);this.emit('did-finish-load');
    }
    async executeJavaScriptInIsolatedWorld(){return this.access || {markers:{},imperva:null,limited:false};}
    close(){this.closeRequested=true;if(!this.deferClose)this.destroy();}
    destroy(){if(this.destroyed)return;this.destroyed=true;this.emit('destroyed');}
  }
  class Window extends EventEmitter {
    constructor(options){super();this.options=options;this.webContents=new Contents();this.children=new Set();this.contentView={
      addChildView:v=>this.children.add(v),removeChildView:v=>this.children.delete(v)};}
    async loadURL(url){await this.webContents.loadURL(url);this.webContents.emit('did-finish-load');}
    getContentSize(){return [1200,850];}
    isDestroyed(){return !!this.destroyed;}
    show(){this.visible=true;}
    hide(){this.visible=false;}
    destroy(){this.destroyed=true;}
  }
  class View {constructor(options){if(failCreation){failCreation=false;throw Error('fixture creation failed');}this.options=options;this.webContents=options.webContents || new Contents();}setBounds(bounds){this.bounds=bounds;}setVisible(value){this.visible=value;}}
  const electron={app:{getName:()=> 'allfold-desktop',getPath:()=>profile},session:{fromPartition:()=>partition},
    webFrameMain:{fromFrameToken:(_process,token)=>frames.get(token) || null},
    BrowserWindow:Window,WebContentsView:View,Menu:{buildFromTemplate:items=>({popup(){menus.push(items);}})},
    ipcMain:{handle:(name,fn)=>handlers.set(name,fn),removeHandler:name=>handlers.delete(name)}};
  const context=vm.createContext({module:{exports:{}},__dirname:path.dirname(require.resolve('../src/browser/browser-runtime.cjs')),URL,Buffer,Date,AbortController,AbortSignal,setTimeout,clearTimeout,
    require:name=>name==='electron'?electron:name==='./document-runtime.cjs'?{DocumentRuntime:class {
      constructor(browser){this.browser=browser;}
      async call(doc,action){
        const wc=this.browser.tabs.get(doc.pageId).view.webContents;
        const access=await wc.executeJavaScriptInIsolatedWorld();
        return {documentId:'fixture-'+doc.frameToken,...(action==='access'?access:action==='article'?{access,article:wc.article || {values:['10.5555/fixture'],multiple:false,limited:false}}:{type:'text/html'})};
      }
      dispose(){}
    }}:name==='../shared/logging.cjs'?{...require('../src/shared/logging.cjs'),
      log:(level,event,details)=>logs.push({level,event,...details})}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/browser/browser-runtime.cjs'),'utf8'),context);
  return {...context.module.exports,partition,handlers,logs,menus,host:new Window(),failNextCreation(){failCreation=true;},nativeContents:()=>new Contents()};
}
test('a first background page never selects, presents or focuses the Browser',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({present:false});
  assert.deepEqual(tab.view.bounds,{x:0,y:0,width:1200,height:850});
  assert.equal(browser.state().selected,null);
  assert.equal(host.children.size,0);
  assert.equal(tab.view.webContents.focused,undefined);
  assert.equal(host.webContents.messages?.some(message=>message.channel==='browser:presentation'),false);
  assert.equal(host.destroyed,undefined);
});
test('main-window Browser uses measured bounds, preserves pages when suspended and ignores stale layout',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});
  t.after(()=>browser.close());await browser.show();
  const tab=browser.selected;
  browser.setPresentation({sequence:1,visible:true,suspended:false,bounds:{x:10.2,y:156.2,width:899.6,height:650.5}});
  assert.deepEqual(tab.view.bounds,{x:11,y:157,width:898,height:649});
  assert.equal(host.children.has(tab.view),true);
  await browser.command({action:'select',id:tab.id});
  assert.equal(tab.view.webContents.focused,1);
  browser.setPresentation({sequence:3,visible:true,suspended:true,bounds:{x:11,y:157,width:898,height:649}});
  assert.equal(host.children.size,0);assert.equal(browser.tabs.size,1);
  assert.equal(browser.setPresentation({sequence:2,visible:true,suspended:false,bounds:{x:0,y:0,width:1200,height:850}}),false);
  assert.equal(host.children.size,0);
  browser.setPresentation({sequence:4,visible:true,suspended:false,bounds:{x:11,y:157,width:898,height:649}});
  assert.equal(host.children.has(tab.view),true);assert.equal(tab.view.webContents.focused,1);
  host.emit('resize');assert.equal(host.children.size,0);
  assert.equal(host.webContents.messages.at(-1).channel,'browser:layout');
  browser.setPresentation({sequence:5,visible:true,suspended:false,bounds:{x:0,y:160,width:1400,height:900}});
  assert.deepEqual(tab.view.bounds,{x:0,y:160,width:1200,height:690});
  host.webContents.emit('did-start-navigation',{url:'http://127.0.0.1:18767/',isSameDocument:true,isMainFrame:true});
  assert.equal(host.children.has(tab.view),true,'same-document navigation must retain the mounted Page');
  host.webContents.emit('did-start-navigation',{url:'http://127.0.0.1:18767/',isSameDocument:false,isMainFrame:true});
  assert.equal(host.children.size,0);assert.equal(browser.tabs.size,1);
  assert.equal(browser.setPresentation({sequence:0,visible:false,suspended:false,bounds:null}),true);
  browser.close();assert.equal(host.destroyed,undefined);
});
test('Browser converts host-zoomed CSS bounds to DIP before clipping to native content',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});
  t.after(()=>browser.close());await browser.show();
  const tab=browser.selected,bounds={x:10.2,y:156.2,width:899.6,height:650.5};
  browser.setPresentation({sequence:1,visible:true,suspended:false,bounds});
  assert.deepEqual(tab.view.bounds,{x:11,y:157,width:898,height:649});
  host.webContents.zoomFactor=1.5;
  browser.setPresentation({sequence:2,visible:true,suspended:false,bounds});
  assert.deepEqual(tab.view.bounds,{x:16,y:235,width:1184,height:615});
  assert.equal(host.children.has(tab.view),true);
  assert.equal(tab.view.webContents.focused,undefined);
  browser.setPresentation({sequence:1,visible:false,suspended:false,bounds:null});
  assert.equal(host.children.has(tab.view),true);
});
test('a committed host document resets layout sequence after a final old-document resize',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});
  t.after(()=>browser.close());await browser.show();
  const tab=browser.selected,bounds={x:10,y:160,width:900,height:600};
  browser.setPresentation({sequence:30,visible:true,suspended:false,bounds});
  host.webContents.emit('did-start-navigation',{isSameDocument:false,isMainFrame:true});
  // The outgoing renderer can still publish while the new response is pending.
  browser.setPresentation({sequence:31,visible:true,suspended:false,bounds});
  host.webContents.emit('did-navigate',{},'http://127.0.0.1:18767/',200);
  assert.equal(host.children.size,0);
  assert.equal(browser.setPresentation({sequence:1,visible:false,suspended:false,bounds:null}),true);
  assert.equal(browser.setPresentation({sequence:2,visible:true,suspended:false,bounds}),true);
  assert.equal(browser.setPresentation({sequence:1,visible:false,suspended:false,bounds:null}),false);
  assert.equal(host.children.has(tab.view),true);
  assert.equal(browser.selected,tab);assert.equal(browser.tabs.size,1);
});
test('Browser rejects malformed commands and layout rectangles before changing native presentation',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});t.after(()=>browser.close());await browser.show();
  for(const command of [null,[],{action:'select',id:'1'},{action:'select'},{action:'new',unexpected:true},
    {action:'navigate',url:7},{action:'reload',url:'https://one.test/'},{action:'close',id:-1},{action:'arbitrary'},
    ...['devtools','cache-size','clear-cache','clear-site-data'].map(action=>({action}))])
    await assert.rejects(browser.command(command),/Invalid Browser command/);
  for(const bounds of [{x:-1,y:0,width:10,height:10},{x:0,y:0,width:Infinity,height:10},
    {x:0,y:0,width:10,height:10,extra:1}])assert.throws(()=>browser.setPresentation({sequence:1,visible:true,suspended:false,bounds}),/Invalid Browser bounds/);
  assert.equal(host.children.size,0);assert.equal(browser.tabs.size,1);
});
test('institution auth is task-scoped and a popup cannot submit after cancellation',async t=>{
  let resolveCredentials,reads=0,actions=0;
  const {BrowserRuntime}=fixture(t),controller=new AbortController();
  const browser=new BrowserRuntime({readCASCredentials:()=>{reads++;return new Promise(r=>{resolveCredentials=r;});}});
  t.after(()=>browser.close());await browser.ready;
  const ordinary=browser.createTab();await ordinary.view.webContents.loadURL('https://idp.example.edu/login');
  ordinary.view.webContents.runAuth=code=>JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1))[0]==='inspect'?{step:'login',waiting:true}:(actions++,{acted:true});
  ordinary.taskSignal=controller.signal;
  await browser.handleAuthentication(ordinary);assert.equal(reads,0);
  assert.throws(()=>browser.beginAuthentication(ordinary,controller.signal),/canceled/);
  await browser.runTask(controller.signal,{request_id:'login'},async()=>{
    await browser.reserveTaskPages(1,{signal:controller.signal,deadline:Date.now()+1000});
    browser.beginAuthentication(ordinary,controller.signal);
    const wc=ordinary.view.webContents.popup({url:'about:blank'}).createWindow({});
    const popup=browser.tabs.get(wc.id);await wc.loadURL('https://idp.example.edu/login');
    wc.runAuth=ordinary.view.webContents.runAuth;
    const pending=browser.handleAuthentication(popup);await new Promise(setImmediate);
    assert.equal(reads,1);controller.abort();resolveCredentials({username:'PRIVATE_USER',password:'PRIVATE_PASSWORD'});
    await pending;assert.equal(actions,0);
  });
});

for(const submission of [
  {url:'https://other.example/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/login'},
  {url:'file:///tmp/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/login'},
  {url:'https://idp.example.edu/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/stale'},
])test('Main refuses unsafe or stale consent submission metadata',async t=>{
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime(),controller=new AbortController();
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab(),wc=tab.view.webContents;
  await wc.loadURL('https://idp.example.edu/login');
  await browser.runTask(controller.signal,{request_id:'consent'},async()=>{
    browser.beginAuthentication(tab,controller.signal);
    wc.runAuth=code=>JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1))[0]==='inspect'
      ?{step:'release',waiting:true}:{submission};
    let posts=0;wc.loadURL=()=>{posts++;return Promise.resolve();};
    await browser.handleAuthentication(tab);assert.equal(posts,0);
    assert.doesNotMatch(JSON.stringify(logs),/PRIVATE|csrf=|submit|stale/);
  });
});
test('Main chooses institution mode only for a live authorized authentication context',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime(),controller=new AbortController();
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab();await tab.view.webContents.loadURL('https://idp.example.edu/login');
  const modes=[];
  tab.view.webContents.runAuth=code=>{
    const args=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));
    modes.push(args[3]);return {step:'none',waiting:false};
  };
  await browser.inspectAuthentication(tab);
  await browser.runTask(controller.signal,{request_id:'auth-mode'},async()=>{
    const auth=browser.beginAuthentication(tab,controller.signal);
    await browser.inspectAuthentication(tab);
    auth.institution=false;
    await browser.inspectAuthentication(tab);
    auth.origins.add('https://idp.example.edu');
    await browser.inspectAuthentication(tab);
    controller.abort();await assert.rejects(browser.inspectAuthentication(tab),/document_changed|canceled/);
  });
  await browser.inspectAuthentication(tab);
  assert.deepEqual(modes,['page','institution','page','institution','page']);
});
test('selecting another tab does not retarget the document, but reload/navigation invalidates it',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const task=browser.createTab({present:false});
  assert.throws(()=>browser.bindTaskPage(task),/canceled/);
  await assert.rejects(browser.navigate('https://example.org/paper',{tab:task}),/canceled/);
  await browser.runTask(new AbortController().signal,{request_id:'selection'},async()=>{
    const doc=await browser.navigate('https://example.org/paper',{tab:task});
    await browser.command({action:'new'});
    assert.notEqual(browser.selected,task);
    assert.equal(browser.documentCurrent(doc),true);
    await assert.rejects(browser.command({action:'close',id:task.id}),/active task page/);
    await browser.command({action:'navigate',id:task.id,url:'https://example.org/paper'});
    assert.equal(browser.documentCurrent(doc),false);
  });
  await browser.command({action:'close',id:task.id});
  assert.equal(browser.tabs.has(task.id),false);
});
test('Service queries isolate configurations without pages and task navigation preserves presentation',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const visible=browser.createTab();
  const signal=new AbortController().signal;
  let tab;
  await browser.runTask(signal,{request_id:'first',task_id:'batch',service_scope:serviceScope,service_id:serviceId},async()=>{
    assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
    assert.equal(browser.tabs.size,1);
    tab=browser.createTab({present:false});
    browser.associatePage(tab,{role:'article',doi:'10.5555/first'});
    const doc=await browser.navigate('https://example.org/first',{tab});
    assert.equal(browser.selected,visible);
    assert.equal(doc.pageId,tab.id);
    assert.equal(browser.servicePages(serviceScope.scope_id,serviceId)[0].active,true);
  });
  const otherScope={...serviceScope,scope_id:'d'.repeat(64)};
  assert.equal(browser.taskTab,null);
  assert.equal(browser.pageAssociation(tab.id),null);
  assert.equal(tab.view.webContents.isDestroyed(),true);
  await browser.runTask(signal,{request_id:'second',task_id:'batch',service_scope:otherScope,service_id:serviceId},async()=>{
    tab=await browser.newTaskPage({signal});browser.associatePage(tab,{role:'article',doi:'10.5555/second'});
    await browser.navigate('https://example.org/second',{tab});
    assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
    assert.equal(browser.servicePages(otherScope.scope_id,serviceId).length,1);
    assert.equal(browser.tabs.size,2);
    assert.equal(browser.selected,visible);
  });
  await browser.runTask(signal,{request_id:'third',task_id:'batch',service_scope:otherScope},async()=>{
    tab=await browser.newTaskPage({signal});
    browser.associatePage(tab,{role:'article',doi:'10.5555/unmatched'});
    browser.bindTaskPage(tab);
    assert.equal(browser.pageAssociation(tab.id).service_id,null);
    assert.equal(browser.servicePages(otherScope.scope_id,serviceId).length,0);
  });
});
test('popup provenance is descriptive, disappears on destruction, and never authorizes credentials',async t=>{
  let reads=0;
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({readCASCredentials:async()=>{reads++;return {};}});
  t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController();
  let wc,popup;
  await browser.runTask(controller.signal,{request_id:'first',service_scope:serviceScope,service_id:serviceId},async()=>{
    await browser.reserveTaskPages(2,{signal:controller.signal,deadline:Date.now()+1000});
    const source=browser.createTab();browser.associatePage(source,{role:'service-resource'});
    browser.bindTaskPage(source);
    wc=source.view.webContents.popup({url:'https://idp.example.edu/login'}).createWindow({});
    popup=browser.tabs.get(wc.id);
    await wc.loadURL('https://idp.example.edu/login');
    wc.runAuth=()=>({step:'login',waiting:true});
    await browser.handleAuthentication(popup);
    assert.equal(reads,0);
    assert.equal(browser.pageAssociation(popup.id).service_id,serviceId);
    assert.equal(browser.pageAssociation(popup.id).source_page_id,source.id);
    source.view.webContents.close();
    assert.equal(popup.opener,null);
    assert.equal(browser.pageAssociation(source.id),null);
    assert.equal(browser.pageAssociation(popup.id).source_page_id,null);
    await assert.rejects(browser.navigate('https://example.org/late'),/page_closed/);
    assert.equal(browser.tabs.size,1);
    controller.abort();assert.equal(browser.pageAssociation(popup.id).active,false);
  });
  assert.equal(browser.tabs.size,0);
  await browser.runTask(new AbortController().signal,{request_id:'second'},async()=>{
    assert.equal(browser.taskTab,null);
    await assert.rejects(browser.navigate('https://example.org/new'),/page_closed/);
  });
  wc.emit('render-process-gone',{}, {reason:'crashed',exitCode:1});
  assert.equal(browser.pageAssociation(popup.id),null);
  assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
});

test('a failed/canceled task Page can be explicitly reused, and a delayed old navigation cannot bind a new task',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const first=new AbortController(),tab=browser.createTab();
  await browser.runTask(first.signal,{request_id:'old'},()=>{
    browser.beginPageLoad(tab,first.signal);
    first.abort();
  });
  const signal=new AbortController().signal;
  await browser.runTask(signal,{request_id:'new'},async()=>{
    assert.equal((await browser.navigate('https://example.org/new',{tab})).pageId,tab.id);
  });
  let ready,pending;
  await browser.runTask(signal,{request_id:'late'},()=>{
    browser.bindTaskPage(tab);
    browser.ready=new Promise(resolve=>{ready=resolve;});
    pending=browser.navigate('https://example.org/old-late');
    pending.catch(()=>{});
  });
  await browser.runTask(signal,{request_id:'latest'},async()=>{
    const other=browser.createTab({present:false});browser.bindTaskPage(other);
    ready();await assert.rejects(pending,/canceled/);
    assert.equal(browser.taskTab,other);
    assert.equal(other.view.webContents.getURL(),'');
    assert.equal(tab.view.webContents.getURL(),'https://example.org/new');
  });
});

test('Browser refuses an HTTP 200 Imperva block before handing the document to the caller',async t=>{
  const {BrowserRuntime}=fixture(t);
  let solverCalls=0;
  const browser=new BrowserRuntime({solveCloudflare:async()=>{solverCalls++;}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({present:false});
  const signal=new AbortController().signal;
  const url='https://projecteuclid.org/journals/example/10.5555/article.full';
  const contents=tab.view.webContents;
  contents.access={markers:{},imperva:{edet:15,incident:'123456-987654'}};
  await assert.rejects(browser.runTask(signal,{request_id:'blocked'},()=>browser.navigate(url,{tab,signal})),{diagnostic:{stage:'navigation',code:'site_restricted',status:200,
    imperva_edet:15,imperva_incident_id:'123456-987654'}});
  assert.equal(solverCalls,0);
  contents.access={markers:{},imperva:null};
  await browser.runTask(signal,{request_id:'article'},async()=>{
    assert.equal((await browser.navigate(url,{tab,signal})).status,200);
  });
});

test('Imperva CAPTCHA waits for the same page to finish verification without calling the Solver',async t=>{
  const {BrowserRuntime}=fixture(t);
  let solverCalls=0;
  const browser=new BrowserRuntime({solveCloudflare:async()=>{solverCalls++;}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({present:false});
  const signal=new AbortController().signal;
  const contents=tab.view.webContents;
  contents.access={markers:{},imperva:{edet:12,incident:'123-456'}};
  const url='https://projecteuclid.org/journals/example/10.5555/article.full';
  let reportWaiting;
  const waiting=new Promise(resolve=>{reportWaiting=resolve;});
  const navigation=browser.runTask(signal,{request_id:'imperva-challenge'},()=>
    browser.navigate(url,{tab,signal,deadline:Date.now()+5000,onWaiting:reportWaiting}));
  const diagnostic=await Promise.race([waiting,navigation.then(()=>assert.fail('Returned before verification'))]);
  assert.deepEqual(diagnostic,{stage:'navigation',code:'verification_page',status:200,
    imperva_edet:12,imperva_incident_id:'123-456'});
  assert.equal(browser.state().taskPageId,tab.id);
  assert.equal(solverCalls,0);

  contents.access={markers:{},imperva:null};
  await contents.loadURL(url);
  const doc=await navigation;
  assert.equal(doc.pageId,tab.id);
  assert.equal(doc.imperva,null);
  assert.equal(solverCalls,0);
});

test('Manual URL opening preserves the task; Covers use an auxiliary page without Service authority',async t=>{
  const {searchJournalCover}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal;
  let manual,cover;
  await browser.runTask(signal,{request_id:'article',service_scope:serviceScope,service_id:serviceId},async()=>{
    const task=browser.createTab();browser.associatePage(task,{role:'article'});browser.bindTaskPage(task);
    manual=await browser.openURL('https://manual.example.org/');
    assert.equal(browser.taskTab,task);assert.equal(browser.selected,manual);
    assert.equal(browser.pageAssociation(manual.id),null);
  });
  await browser.runTask(signal,{request_id:'cover',service_scope:{...serviceScope,secret:'PRIVATE'},service_id:serviceId},async()=>{
    browser.events.once('tab-created',(_event,tab)=>{
      const original=tab.view.webContents.executeJavaScriptInIsolatedWorld.bind(tab.view.webContents);
      tab.view.webContents.executeJavaScriptInIsolatedWorld=async(world,scripts)=>scripts?{ready:true,source_url:null}:original();
    });
    assert.equal((await searchJournalCover(browser,{name:'Saved Journal'},{signal,progress(){}})).source_url,null);
    cover=browser.taskTab;
    assert.equal(browser.pageAssociation(cover.id).role,'auxiliary');
    assert.equal(browser.pageAssociation(cover.id).service_id,null);
    assert.equal(browser.selected,manual);
  });
  assert.equal(browser.tabs.size,1);assert.equal(cover.view.webContents.isDestroyed(),true);
  assert.doesNotMatch(JSON.stringify(browser.pageAssociation(cover.id)),/PRIVATE|secret/);
  assert.doesNotMatch(JSON.stringify(logs),/PRIVATE|secret/);
  assert.equal(logs.find(event=>event.event==='page_associated').scope_id,serviceScope.scope_id);
  await assert.rejects(browser.runTask(signal,{service_id:serviceId},()=>{}),/Invalid browser Service identity/);
  await browser.close();assert.equal(browser.tabs.size,0);assert.equal(browser.selected,null);
});

test('remote popups remain hidden managed tabs and unsafe URLs are refused',async t=>{
  const {BrowserRuntime,host}=fixture(t),browser=new BrowserRuntime({hostWindow:host});t.after(()=>browser.close());await browser.show();
  const source=browser.selected.view.webContents;
  assert.equal(source.popup({url:'file:///etc/passwd'}).action,'deny');
  const popup=source.popup({url:'https://example.org/popup'});
  assert.equal(popup.action,'allow');
  assert.equal(popup.overrideBrowserWindowOptions.webPreferences.sandbox,true);
  assert.equal(popup.overrideBrowserWindowOptions.webPreferences.nodeIntegration,false);
  assert.equal(popup.overrideBrowserWindowOptions.webPreferences.nodeIntegrationInSubFrames,true);
  const nativeContents=new source.constructor();
  const contents=popup.createWindow({webContents:nativeContents,
    webPreferences:{customNativeFlag:'preserve',sandbox:false,nodeIntegration:true}});
  assert.equal(contents,nativeContents);assert.equal(browser.tabs.has(contents.id),true);
  const view=browser.tabs.get(contents.id).view;
  assert.equal(view.options.webPreferences.customNativeFlag,'preserve');
  assert.equal(view.options.webPreferences.sandbox,true);assert.equal(view.options.webPreferences.nodeIntegration,false);
  await assert.rejects(browser.command({action:'navigate',url:'javascript:alert(1)'}));
  await assert.rejects(browser.command({action:'navigate',url:'https://user:password@example.org/'}));
  assert.equal(browser.selected.view.webContents,source);
  browser.setPresentation({sequence:1,visible:false,suspended:false,bounds:null});
  assert.equal(host.children.size,0);assert.equal(browser.tabs.size,2);
});
test('explicit Manual Service Visit retains a scoped target without CARSI credential authority',async t=>{
  const {visitManualService}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime}=fixture(t);
  let reads=0;
  const browser=new BrowserRuntime({readCASCredentials:async()=>{reads++;}});
  t.after(()=>browser.close());await browser.ready;
  const data={access_url:'https://library.example.org/',service_scope:serviceScope,
    service_id:serviceId,workflow_id:'login_manual',task_id:'visit_manual',preparation_key:'e'.repeat(64)};
  const signal=new AbortController().signal;
  const result=await browser.runTask(signal,data,()=>visitManualService(browser,data,{signal,progress(){}}));
  assert.equal(result.outcome,'Opened');
  const page=browser.tabs.get(result.evidence.target_page_id),association=browser.pageAssociation(page.id);
  assert.equal(page.view.webContents.getURL(),data.access_url);
  assert.equal(page.preparationKey,data.preparation_key);
  assert.equal(association.role,'service-target');assert.equal(association.service_id,serviceId);
  assert.equal(association.active,false);assert.equal(page.managed,true);assert.equal(page.authContext,undefined);
  assert.equal(browser.selected,null);assert.equal(browser.tabs.size,1);assert.equal(reads,0);
});

function turnstileHitFixture(modes=[]) {
  const calls=[],roots=[];
  const root=(name,extra={})=>({name,...extra,elementFromPoint(x,y){
    calls.push(name);
    assert.equal(x,74);assert.equal(y,32.5);
    return this.hit;
  }});
  const document=root('document',{nodeType:9});roots.push(document);
  const checkbox={isConnected:true,disabled:false,ownerDocument:document,
    style:{visibility:'visible',display:'block',pointerEvents:'auto',opacity:'1'},
    rect:{x:9,y:20.5,width:130,height:24},children:[],
    getRootNode(){return this.root;},getBoundingClientRect(){return this.rect;},
    contains(node){return node===this || this.children.includes(node);}};
  let enclosing=document;
  for(const mode of modes) {
    const parent=enclosing;
    const host={nodeName:'BODY',children:[],getRootNode:()=>parent,
      contains(node){return node===this || this.children.includes(node);}};
    enclosing=root('shadow-'+roots.length,{host,mode});roots.push(enclosing);
    host.shadowRoot=mode==='open'?enclosing:null;parent.hit=host;
  }
  checkbox.root=enclosing;enclosing.hit=checkbox;
  const source=fs.readFileSync(path.join(__dirname,'../../src/allfold/integrations/cloudflare_solver.py'),'utf8');
  const check=vm.runInNewContext('('+source.match(/_CHECKBOX_INTERACTABLE = """([\s\S]*?)"""/)[1]+')',
    {window:{getComputedStyle:node=>node.style}});
  return {checkbox,roots,calls,check:()=>check.call(checkbox)};
}

// Opening a Manual Service link must preserve the active task's document.

function authDOM({title='Institution Login',fields=[],buttons=['登录'],error='',messages=[],body='',headings=[],
  formHeading='',formText='',widgets=[],dialogText='',forms=null,url='https://idp.example.edu/login'}={}) {
  let clicks=0;
  class Input {
    constructor({type='text',label='',value='',...values}={}) {
      Object.assign(this,{type,isConnected:true,disabled:false,readOnly:false,required:false,
        name:'',id:'',autocomplete:'',checked:false,tagName:'INPUT'},values);
      this.labels=[{textContent:label}];this.value=value;
    }
    get value(){return this.savedValue;}set value(value){this.savedValue=value;}
    get checked(){return this.savedChecked;}
    set checked(value){
      if(value && this.type==='radio' && this.form)for(const node of this.form.elements)
        if(node!==this && node.type==='radio' && node.name===this.name)node.savedChecked=false;
      this.savedChecked=value;
    }
    getClientRects(){return this.type==='hidden'?[]:[{}];}
    getAttribute(key){return this[key] ?? null;}
    matches(selector){return selector===':disabled' && (this.disabled || this.fieldsetDisabled===true);}
    focus(){}blur(){}dispatchEvent(){}
    click(){this.checked=true;}
  }
  const definitions=forms || [{fields,buttons}];
  const groups=definitions.map(definition=>{
    const inputs=(definition.fields || []).map(field=>new Input(field));
    const controls=(definition.buttons || []).map(button=>({isConnected:true,tagName:'BUTTON',type:'submit',
      name:'',value:'',innerText:typeof button==='string'?button:'',disabled:false,readOnly:false,
      getClientRects:()=>[{}],getAttribute(key){return this[key] ?? null;},
      matches(selector){return selector===':disabled' && (this.disabled || this.fieldsetDisabled===true);},
      click(){clicks++;},...(typeof button==='string'?{}:button)}));
    return {definition,inputs,controls};
  });
  const inputs=groups.flatMap(group=>group.inputs);
  const controls=groups.flatMap(group=>group.controls);
  let form;
  const messageNodes=[...(error?[{textContent:error,role:'alert'}]:[]),...messages].map(message=>({
    ...message,isConnected:true,getClientRects:()=>[{}],getAttribute:key=>message[key] || null}));
  const headingNodes=headings.map(textContent=>({textContent,isConnected:true,getClientRects:()=>[{}]}));
  if(formHeading)headingNodes.push({textContent:formHeading,isConnected:true,getClientRects:()=>[{}]});
  const widgetNodes=widgets.map(widget=>({isConnected:true,tagName:'IFRAME',getClientRects:()=>[{}],
    getAttribute:key=>widget[key] || null,querySelector:()=>null,...widget}));
  const select=selector=>{
    if(selector==='input')return inputs;
    if(selector==='[name]')return [...inputs,...controls].filter(node=>node.name);
    if(selector.startsWith('button,'))return controls;
    if(selector.startsWith('h1,'))return headingNodes;
    if(selector.startsWith('[role=alert]'))return messageNodes;
    if(selector==='p,span,div')return error?[{textContent:error,children:[],isConnected:true,getClientRects:()=>[{}]}]:[];
    if(selector.startsWith('iframe['))return widgetNodes;
    if(selector==='img,canvas')return widgetNodes.filter(node=>['IMG','CANVAS'].includes(node.tagName));
    if(selector==='img,canvas,input')return [...inputs,...widgetNodes.filter(node=>['IMG','CANVAS'].includes(node.tagName))];
    return [];
  };
  form={textContent:formText || error,tagName:'FORM',isConnected:true,getClientRects:()=>[{}],getAttribute:()=>null,
    querySelectorAll:select,querySelector:selector=>select(selector)[0] || null,
    contains:node=>[...inputs,...controls,...messageNodes,...headingNodes,...widgetNodes].includes(node) && !node.outside};
  const dialog={...form,textContent:dialogText,getAttribute:key=>key==='role'?'dialog':null};
  for(const node of [...inputs,...controls,...messageNodes,...headingNodes,...widgetNodes]) {
    if(inputs.includes(node) || controls.includes(node))node.form=form;
    node.closest=()=>node.outside?null:form;node.parentElement=form;
  }
  const formNodes=groups.map((group,index)=>{
    const own=index===0?form:{...form};
    Object.assign(own,{action:'https://idp.example.edu/continue?execution=current',method:'post',
      enctype:'application/x-www-form-urlencoded',...group.definition,
      elements:[...group.inputs,...group.controls]});
    for(const node of own.elements){node.form=own;node.closest=()=>own;node.parentElement=own;}
    return own;
  });
  // VM substitute for native successful-control serialization; no real IdP or Session is used here.
  class DOMFormData extends FormData {
    constructor(form,submitter) {
      super();
      for(const node of form.elements) {
        if(!node.name || node.matches(':disabled') || ['button','reset'].includes(node.type)
          || (node.type==='submit' && node!==submitter)
          || (['checkbox','radio'].includes(node.type) && !node.checked))continue;
        this.append(node.name,node.value);
      }
    }
  }
  const document={title,baseURI:url,body:{innerText:body},getElementById:()=>null,
    querySelectorAll(selector){
      if(selector.startsWith('form,'))return dialogText?[...formNodes,dialog]:formNodes;
      if(selector.startsWith('iframe,'))return [...widgetNodes,...(dialogText?[dialog]:[])];
      return select(selector);
    }};
  const context=vm.createContext({document,location:{href:url},URL,URLSearchParams,FormData:DOMFormData,
    HTMLInputElement:Input,Event:class {},getComputedStyle:()=>({visibility:'visible',display:'block'})});
  context.window=context;context.top=context;
  const run=(action='inspect',step=null,mode='institution')=>vm.runInContext('('+institutionAuthPage.toString()+')(...'
    +JSON.stringify([action,{username:'PRIVATE_USER',password:'PRIVATE_PASSWORD'},step,mode])+')',context);
  const runDefault=(action='inspect',step=null)=>vm.runInContext('('+institutionAuthPage.toString()+')(...'
    +JSON.stringify([action,{username:'PRIVATE_USER',password:'PRIVATE_PASSWORD'},step])+')',context);
  return {run,runDefault,inputs,controls,forms:formNodes,clicks:()=>clicks,document};
}
function consentDOM(step,{fields=step==='terms'?[{type:'checkbox',name:'_shib_idp_consentIds',required:true,value:'terms-current'}]:[],
  buttons=[{name:'_eventId_proceed',innerText:'Unfamiliar caption',value:''}],url,...form}={}) {
  return authDOM({title:'Unfamiliar template',url,forms:[
    {fields,buttons,...form},
    {fields:[{type:'hidden',name:step==='terms'?'_eventId_TermsRejected':'_eventId_AttributeReleaseRejected',value:'Reject'}]},
  ]});
}
test('page is the default mode and cannot execute a recognized institution login',()=>{
  const page=authDOM({fields:[{label:'Username'},{type:'password',label:'Password'}]});
  assert.equal(page.runDefault('act','login').waiting,true);
  assert.equal(page.clicks(),0);assert.equal(page.inputs[0].value,'');assert.equal(page.inputs[1].value,'');
});
test('an optional password sign-in entry does not block an ordinary article, while institution switching stays authorized',()=>{
  const page=authDOM({title:'Article abstract',formHeading:'Sign in',buttons:['Sign in with password'],
    url:'https://academic.oup.com/biometrics/article/doi/10.1093/biomtc/ujag169/fixture'});
  assert.equal(page.runDefault().step,'none');
  assert.equal(page.runDefault().waiting,false);
  assert.equal(page.runDefault('act','account').acted,false);
  assert.equal(page.clicks(),0);
  assert.equal(page.run().step,'account');
  assert.equal(page.run('act','account').acted,true);
  assert.equal(page.clicks(),1);
});

test('ordinary verification controls and explicit QR login still wait for manual completion',()=>{
  const otp=authDOM({fields:[{label:'Verification code',autocomplete:'one-time-code'}],buttons:['Verify']});
  assert.equal(otp.runDefault().waiting,true);
  const qr=authDOM({formHeading:'扫码登录',buttons:['密码登录'],widgets:[{tagName:'IMG'}]});
  assert.equal(qr.runDefault().waiting,true);
  assert.equal(qr.runDefault('act','account').acted,false);
  assert.equal(qr.clicks(),0);
});



test('reused page lifecycle records retain each workflow association before replacement and renderer invalidation',async t=>{
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController(),tab=browser.createTab();
  await browser.runTask(controller.signal,{request_id:'request_a',task_id:'task_a',workflow_id:'workflow_a',service_scope:serviceScope,service_id:serviceId},()=>{
    browser.associatePage(tab,{role:'article'});browser.bindTaskPage(tab,controller.signal);
  });
  assert.equal(browser.pageAssociation(tab.id).workflow_id,'workflow_a');
  await browser.runTask(controller.signal,{request_id:'request_b',task_id:'task_b',workflow_id:'workflow_b',service_scope:serviceScope,service_id:serviceId},()=>{
    browser.associatePage(tab,{role:'article'});browser.bindTaskPage(tab,controller.signal);
    tab.view.webContents.emit('render-process-gone',{}, {reason:'crashed',exitCode:1});
  });
  assert.equal(browser.pageAssociation(tab.id),null);
  const replaced=logs.find(e=>e.event==='page_association_replaced');assert.equal(replaced.workflow_id,'workflow_a');assert.equal(replaced.request_id,'request_a');
  const crashed=logs.find(e=>e.event==='page_renderer_gone');assert.equal(crashed.workflow_id,'workflow_b');assert.equal(crashed.service_id,serviceId);
  tab.view.webContents.close();assert.equal(logs.find(e=>e.event==='page_closed').page_id,tab.id);
});

test('parallel native tasks keep page navigation, credentials and cleanup with their owning request',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const first=browser.createTab({present:false}),second=browser.createTab({present:false});
  const stopA=new AbortController(),stopB=new AbortController();
  let settleA,settleB,arrivedA,arrivedB;
  const aReady=new Promise(resolve=>{arrivedA=resolve;}),bReady=new Promise(resolve=>{arrivedB=resolve;});
  const aGate=new Promise(resolve=>{settleA=resolve;}),bGate=new Promise(resolve=>{settleB=resolve;});
  const run=(tab,id,signal,arrived,gate)=>browser.runTask(signal,{request_id:id,workflow_id:'workflow'},async()=>{
    browser.associatePage(tab,{role:'service-resource'});
    browser.bindTaskPage(tab,signal);
    browser.beginAuthentication(tab,signal,{institution:false});
    const doc=await browser.navigate('https://fixture.example/'+id);
    arrived(doc);
    await gate;
    assert.equal(browser.taskTab,tab);
    assert.equal(browser.documentCurrent(doc),!signal.aborted);
  });
  const a=run(first,'first',stopA.signal,arrivedA,aGate);
  const b=run(second,'second',stopB.signal,arrivedB,bGate);
  const results=Promise.all([a,b]);results.catch(()=>{});
  try {
    const [aDoc,bDoc]=await Promise.race([Promise.all([aReady,bReady]),results]);
    assert.equal(aDoc.pageId,first.id);assert.equal(bDoc.pageId,second.id);
    assert.deepEqual([...browser.state().taskPageIds].sort(),[first.id,second.id]);
    await browser.runTask(new AbortController().signal,{request_id:'foreign',workflow_id:'workflow'},()=>{
      assert.equal(browser.documentCurrent(bDoc),false);
      assert.throws(()=>browser.bindTaskPage(second),/navigation_active/);
    });
    await assert.rejects(browser.command({action:'close',id:second.id}),/active task page/);
    stopA.abort();settleA();await a;
    assert.equal(browser.pageAssociation(first.id).active,false);
    assert.equal(browser.pageAssociation(second.id).active,true);
    assert.equal(first.authContext.active,false);assert.equal(second.authContext.active,true);
    assert.equal(second.navigation.current.active,true);
  } finally {settleA();settleB();await results;}
  assert.equal(browser.pageAssociation(second.id).active,false);
});

test('supported Cloudflare challenges invoke Solver while hCaptcha remains manual',async t=>{
  const {BrowserRuntime}=fixture(t),solved=[];
  const browser=new BrowserRuntime({solveCloudflare:async doc=>{solved.push(doc.pageId);return {outcome:'clicked'};}});
  t.after(()=>browser.close());await browser.ready;
  for(const hcaptcha of [false,true]) {
    const signal=new AbortController().signal;
    await browser.runTask(signal,{request_id:hcaptcha?'manual':'auto'},async()=>{
      const tab=browser.createTab({present:false});
      browser.bindTaskPage(tab);
      const wc=tab.view.webContents;
      wc.access={markers:{cloudflareOptions:true,cloudflareOrchestrator:true,hcaptcha}};
      await wc.loadURL('https://example.org/challenge');
      const result=await browser.inspectPage(tab,{signal});
      assert.equal(result.waiting,true);
      if(hcaptcha)assert.equal(result.diagnostic?.code,'verification_page');
      else assert.deepEqual(solved,[tab.id]);
      assert.equal(solved.length,1);
    });
  }
});

test('Article pages are reused only within their active operation and close on cancellation failure and completion',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const data={workspace_identity:'a'.repeat(64),paper_id:'fd8460a2-7cf1-4f02-b346-cbcbd2fe6e45'},doi='10.5555/fixture';
  const stop=new AbortController();let first;
  await browser.runTask(stop.signal,{...data,request_id:'article'},async()=>{
    first=await browser.openPaperPage(data,doi,{role:'article',signal:stop.signal});
    const page=browser.state().tabs.find(tab=>tab.id===first.pageId);assert.equal(page.managed,true);assert.equal(page.busy,true);
    await assert.rejects(browser.command({action:'reload',id:page.id}),/active task page/i);stop.abort();
  });
  assert.equal(browser.tabs.has(first.pageId),false);assert.equal(browser.paperPages.size,0);
  const signal=new AbortController().signal;
  await browser.runTask(signal,{...data,request_id:'retry'},async()=>{
    const opened=await browser.openPaperPage(data,doi,{role:'article',signal});assert.notEqual(opened.pageId,first.pageId);
    const same=await browser.openPaperPage(data,doi,{role:'article',signal});assert.equal(same.pageId,opened.pageId);
    const other=await browser.openPaperPage({...data,workspace_identity:'b'.repeat(64)},doi,{role:'article',signal});
    assert.notEqual(other.pageId,opened.pageId);
  });
  assert.equal(browser.tabs.size,0);assert.equal(browser.paperPages.size,0);
  await assert.rejects(browser.runTask(signal,{...data,request_id:'failed'},async()=>{
    await browser.openPaperPage(data,doi,{role:'article',signal});throw Error('fixture article failure');
  }),/fixture article failure/);
  assert.equal(browser.tabs.size,0);assert.equal(browser.paperPages.size,0);
});

test('Login opens one managed CARSI Portal and prepares independent Service pages without resubmitting credentials',{timeout:5000},async t=>{
  const {loginInstitution,prepareLoggedInService}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime}=fixture(t);
  const idp='https://idp.example.edu/login',portalURL='https://ds.carsi.edu.cn/resource/resource.php';
  const targetURL='https://publisher.example/challenge';
  const manualId='svc_'+'2'.repeat(32),noClickId='svc_'+'3'.repeat(32);
  let reads=0,submissions=0,releaseSearches,reportManual,manualWaiting=false;
  const simultaneous=new Promise(resolve=>{releaseSearches=resolve;});
  const manualReady=new Promise(resolve=>{reportManual=resolve;});
  const searches=[],solved=[],serviceModes=[];
  const browser=new BrowserRuntime({
    readCASCredentials:async()=>{reads++;return {username:'fixture',password:'synthetic'};},
    solveCloudflare:async doc=>{
      const owner=browser.operation;
      assert.equal(browser.ownsPage(owner,doc.pageId),true);
      assert.equal(browser.documentCurrent(doc),true);
      solved.push({pageId:doc.pageId,serviceId:owner.association.service_id});
      const contents=browser.tabs.get(doc.pageId).view.webContents;
      contents.access={markers:{}};
      return {outcome:'clicked'};
    },
  });
  t.after(()=>browser.close());await browser.ready;
  browser.events.on('tab-created',(_event,tab)=>{
    const wc=tab.view.webContents,load=wc.loadURL.bind(wc);
    if(tab.opener)wc.modernNavigation=true;
    wc.loadURL=url=>load(url.startsWith('https://ds.carsi.edu.cn/Shibboleth.sso/Login')?idp:url);
    wc.runAuth=async code=>{
      const [action,name,_query,mode]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));
      if(action==='inspect' && wc.getURL()===idp) {
        if(tab.association?.service_id)serviceModes.push(mode);
        return {step:'login',waiting:true};
      }
      if(action==='act' && wc.getURL()===idp) {
        submissions++;await load(portalURL);return {acted:true};
      }
      if(action==='ready')return {status:'ready',checked:false};
      if(action==='search') {
        searches.push({tabId:tab.id,serviceId:tab.association.service_id,name});
        if(searches.length===2)releaseSearches();
        await simultaneous;
        return {status:'pending'};
      }
      if(action==='poll')return {status:'complete',selection:{status:'selected',
        url:'https://ds.carsi.edu.cn/resource/resourceDetail.php?id='+tab.association.service_id}};
      return {step:'none',waiting:false};
    };
    const execute=wc.executeJavaScriptInIsolatedWorld.bind(wc);
    wc.executeJavaScriptInIsolatedWorld=async(world,scripts)=>{
      if(!scripts)return execute();
      const [action]=JSON.parse(scripts[0].code.slice(scripts[0].code.lastIndexOf('(...')+4,-1));
      if(action==='check')return {status:'ready'};
      assert.equal(action,'visit');
      const popup=wc.popup({url:idp}).createWindow({});
      await popup.loadURL(idp);
      await browser.handleAuthentication(browser.tabs.get(popup.id));
      if(tab.association.service_id===noClickId) {
        await popup.loadURL('https://publisher.example/unrelated');
        return {status:'pending'};
      }
      popup.access={markers:{cloudflareTitle:true,cloudflareOptions:true,cloudflareOrchestrator:true,hcaptcha:tab.association.service_id===manualId}};
      await popup.loadURL(targetURL);
      return {status:'visited_click'};
    };
  });
  const signal=new AbortController().signal;
  const common={workflow_id:'login_workflow',service_scope:serviceScope,authentication_key:'e'.repeat(64)};
  const institution={...common,request_id:'login',task_id:'institution',use_shibboleth:true,
    login_url:'https://ds.carsi.edu.cn/Shibboleth.sso/Login'};
  const login=await browser.runTask(signal,institution,()=>loginInstitution(browser,institution,{signal,progress(){}}));
  assert.equal(login.outcome,'Opened');assert.equal(reads,1);assert.equal(submissions,1);
  const entry=browser.tabs.get(login.portal_page_id);
  const prepare=(id,name,progress=()=>{})=>{
    const data={...common,request_id:name,task_id:name,service_id:id,portal_page_id:entry.id,name,
      preparation_key:id.slice(4).repeat(2)};
    return browser.runTask(signal,data,()=>prepareLoggedInService(browser,data,{signal,progress}));
  };
  const manual=prepare(manualId,'ManualCaptcha',value=>{
    if(value.waiting_for_user){manualWaiting=true;reportManual();}
  });
  const automatic=prepare(serviceId,'Automatic');
  await Promise.race([manualReady,manual]);
  const auto=await automatic;
  assert.equal(auto.outcome,'Opened');assert.equal(manualWaiting,true);
  assert.equal(searches.length,2);assert.notEqual(searches[0].tabId,searches[1].tabId);
  assert.equal(searches.some(search=>search.tabId===entry.id),false);
  const {target_page_id:autoId}=auto.evidence;
  assert.equal(browser.tabs.get(autoId).preparationKey,serviceId.slice(4).repeat(2));
  assert.deepEqual(solved,[{pageId:autoId,serviceId}]);
  const manualTarget=browser.servicePages(serviceScope.scope_id,manualId).find(page=>page.role==='service-target');
  assert.ok(manualTarget);assert.notEqual(manualTarget.page_id,autoId);
  const manualContents=browser.tabs.get(manualTarget.page_id).view.webContents;
  manualContents.access={markers:{}};
  await manualContents.loadURL('https://publisher.example/verified');
  assert.equal((await manual).outcome,'Opened');
  assert.equal((await prepare(noClickId,'NoClick')).outcome,'Needs attention');
  for(const id of [entry.id,autoId,manualTarget.page_id]) {
    const page=browser.state().tabs.find(tab=>tab.id===id);
    assert.equal(page.managed,true);
    await assert.rejects(browser.command({action:'close',id}),/managed page/i);
  }
  assert.ok(serviceModes.includes('institution'));
  assert.equal(reads,1);assert.equal(submissions,1);
  assert.equal(browser.pageAssociation(autoId).source_page_id,null);
  assert.equal(browser.tabs.has(auto.evidence.source_page_id),false);
  entry.view.webContents.close();
  const retained=browser.tabs.size;
  await assert.rejects(prepare(serviceId,'StalePortal'),{diagnostic:{stage:'authentication',code:'carsi_session_expired'}});
  assert.equal(browser.tabs.size,retained);
  assert.equal(reads,1);assert.equal(submissions,1);
});

test('initial Paper loading allows two delayed refreshes before replacing only the failed page',async t=>{
  const {BrowserRuntime,partition}=fixture(t);
  const waits=[],recovery=[];
  const browser=new BrowserRuntime({recoveryTiming:{random:()=>0.5,pause:async(_signal,ms)=>{waits.push(ms);}}});
  t.after(()=>browser.close());await browser.ready;
  const selected=browser.createTab();
  const pages=[];
  let requestId=0;
  const data={workspace_identity:'a'.repeat(64),paper_id:'fd8460a2-7cf1-4f02-b346-cbcbd2fe6e45',request_id:'paper-reopen'};
  browser.events.on('tab-created',(_event,tab)=>{
    pages.push(tab);
    const wc=tab.view.webContents;
    if(pages.length!==1)return;
    const fail=()=>{
      wc.emit('did-start-navigation',{},wc.url,false,true);
      networkFailure(partition,wc,{id:++requestId,url:wc.url});
    };
    wc.loadURL=async url=>{wc.url=url;fail();throw Error('ERR_CONNECTION_CLOSED');};
    wc.reload=()=>fail();
  });
  const signal=new AbortController().signal;
  const doc=await browser.runTask(signal,data,async()=>{
    browser.operation.recordRecovery=(event,details)=>recovery.push({event,...details});
    return browser.openPaperPage(data,'10.5555/fixture',{role:'article',signal});
  });
  assert.deepEqual(waits,[350,700]);
  assert.equal(pages.length,2);
  assert.equal(pages[0].view.webContents.isDestroyed(),true);
  assert.equal(doc.pageId,pages[1].id);
  assert.equal(browser.state().selected,selected.id);
  assert.equal(browser.documentCurrent(doc),false);assert.equal(pages[1].view.webContents.isDestroyed(),true);
  assert.deepEqual(recovery.filter(event=>event.event==='recovery_scheduled').map(event=>[event.recovery_action,event.net_code]),[
    ['page_refresh',-100],['page_refresh',-100],['paper_reopen',-100]]);
  assert.equal(recovery.at(-1).source_page_id,pages[0].id);
});

for(const mode of ['same-tab','popup','follow-up','follow-up-post','after-limit-get','after-limit-post',
  'timeout','unknown','ambiguous','unsafe-method','authority','double-fail']) {
  test('CARSI Visit recovery preserves authority for '+mode,async t=>{
    if(mode==='timeout')t.mock.timers.enable({apis:['Date'],now:1000});
    const {loginInstitution,prepareLoggedInService}=require('../src/workflows/browser-operations.cjs');
    const {BrowserRuntime,partition}=fixture(t);
    const browser=new BrowserRuntime({recoveryTiming:{random:()=>0.5,pause:async()=>{}}});
    t.after(()=>browser.close());await browser.ready;
    const portalURL='https://ds.carsi.edu.cn/resource/resource.php';
    const detailURL='https://ds.carsi.edu.cn/resource/resourceDetail.php?id=synthetic';
    const targetURL='https://publisher.example/target';
    const afterRefreshURL='https://publisher.example/after-refresh';
    const afterLimitMethod={'after-limit-get':'GET','after-limit-post':'POST'}[mode];
    const followUp=mode==='follow-up' || mode==='follow-up-post';
    const method=mode==='unsafe-method' || mode==='follow-up-post'?'POST':'GET';
    let visits=0,refreshes=0,authorities=0,requestId=0,oldTarget;
    const recovery=[],created=[];
    browser.events.on('tab-created',(_event,tab)=>{
      created.push(tab);
      const wc=tab.view.webContents,load=wc.loadURL.bind(wc),access=wc.executeJavaScriptInIsolatedWorld.bind(wc);
      wc.loadURL=url=>{
        assert.notEqual(url,afterRefreshURL,'resource reentry must not load the failed request URL');
        return load(url.includes('/Shibboleth.sso/')?portalURL:url);
      };
      wc.runAuth=async code=>{
        const [action]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));
        if(action==='ready')return {status:'ready',checked:false};
        if(action==='search')return {status:'pending'};
        if(action==='poll')return {status:'complete',selection:{status:'selected',url:detailURL}};
        return {step:'none',waiting:false};
      };
      wc.executeJavaScriptInIsolatedWorld=async(_world,scripts)=>{
        if(!scripts)return access();
        const [action]=JSON.parse(scripts[0].code.slice(scripts[0].code.lastIndexOf('(...')+4,-1));
        if(action==='check')return {status:'ready'};
        const target=['popup','unknown','ambiguous'].includes(mode)?wc.popup({url:targetURL}).createWindow({}):wc;
        visits++;
        if(visits===1 || mode==='double-fail') {
          oldTarget ||= target;
          let failedURL=followUp?'https://publisher.example/landing':targetURL;
          const fail=(requestMethod=method)=>{
            target.url=failedURL;
            target.emit('did-start-navigation',{},failedURL,false,true);
            if(mode==='timeout' && refreshes===1) {
              target.loading=true;
              setImmediate(()=>t.mock.timers.setTime(86000));
              return;
            }
            networkFailure(partition,target,{id:++requestId,url:failedURL,method:requestMethod});
          };
          target.reload=()=>{
            refreshes++;
            if(afterLimitMethod && refreshes===2) {
              void target.loadURL(failedURL);
              failedURL=afterRefreshURL;
              target.emit('will-navigate',{},failedURL);
              fail(afterLimitMethod);
              return;
            }
            if(mode==='follow-up' && refreshes===1) {
              void target.loadURL(failedURL);
              failedURL='https://publisher.example/final';
              target.emit('will-navigate',{},failedURL);
            }
            fail();
          };
          if(followUp) {
            await target.loadURL(targetURL);
            target.emit('will-navigate',{},failedURL);
          }
          fail();
          if(mode==='unknown')return {status:'pending'};
          if(mode==='ambiguous'){const admission=wc.popup({url:'about:blank'});if(admission.action==='allow')admission.createWindow({});}
        } else {
          oldTarget.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',targetURL,true,
            oldTarget.mainFrame.processId,oldTarget.mainFrame.routingId);
          await target.loadURL(targetURL);
        }
        return {status:'visited_click'};
      };
    });
    const signal=new AbortController().signal;
    const institution={workflow_id:'login_reentry',request_id:'login',task_id:'login',service_scope:serviceScope,authentication_key:'e'.repeat(64),
      use_shibboleth:true,login_url:'https://ds.carsi.edu.cn/Shibboleth.sso/Login'};
    const login=await browser.runTask(signal,institution,()=>loginInstitution(browser,institution,{signal,progress(){}}));
    const userPage=browser.createTab();
    const data={...institution,request_id:'prepare',task_id:'prepare',service_id:serviceId,name:'Example',
      portal_page_id:login.portal_page_id,preparation_key:'a'.repeat(64)};
    const preparation=browser.runTask(signal,data,()=>{
      browser.operation.recordRecovery=(event,details)=>recovery.push({event,...details});
      if(mode==='authority')browser.operation.validateRecovery=async()=>{
        if(++authorities===3)throw Error('document_changed');
      };
      const {request_id,...payload}=data;
      return prepareLoggedInService(browser,payload,{signal,progress(){}});
    });
    const isLoadFailure=error=>error.diagnostic?.code==='load_failed' && error.diagnostic?.net_code===-100;
    if(mode==='double-fail') {
      await assert.rejects(preparation,isLoadFailure);
      assert.equal(visits,2);
      assert.equal(refreshes,4);
      assert.equal(oldTarget.isDestroyed(),true);
      assert.equal(recovery.at(-1).recovery_action,'resource_reentry');
      assert.equal(recovery.at(-1).event,'recovery_exhausted');
      assert.equal(recovery.at(-1).source_page_id,oldTarget.id);
      return;
    }
    if(method==='POST' || ['unknown','ambiguous','authority'].includes(mode)) {
      if(method==='POST')await assert.rejects(preparation,isLoadFailure);
      else if(mode==='authority')await assert.rejects(preparation,/document_changed/);
      else if(mode==='ambiguous')await assert.rejects(preparation,/page_capacity/);
      else assert.equal((await preparation).outcome,'Needs attention');
      assert.equal(visits,1);
      assert.equal(refreshes,mode==='authority'?2:0);
      assert.equal(browser.tabs.has(login.portal_page_id),true);
      assert.equal(recovery.some(event=>event.recovery_action==='resource_reentry' && event.event==='recovery_succeeded'),false);
      return;
    }
    const result=await preparation;
    assert.equal(visits,2);
    assert.equal(refreshes,mode==='timeout'?1:2);
    assert.equal(result.outcome,'Opened');
    assert.equal(result.evidence.target_page_id,created.at(-1).id);
    assert.equal(oldTarget.isDestroyed(),true);
    assert.deepEqual(created.filter(tab=>!tab.view.webContents.isDestroyed()).map(tab=>tab.id).sort((a,b)=>a-b),
      [userPage.id,login.portal_page_id,result.evidence.target_page_id].sort((a,b)=>a-b));
    assert.equal(browser.tabs.has(login.portal_page_id),true);
    assert.equal(browser.state().selected,userPage.id);
    assert.equal(recovery.filter(event=>event.recovery_action==='resource_reentry').length,2);
    assert.equal(recovery.at(-1).source_page_id,oldTarget.id);
    assert.equal(recovery.at(-1).page_id,result.evidence.target_page_id);
  });
}

test('Paper page-load timeout replaces the provisional page without renewing the original deadline',async t=>{
  t.mock.timers.enable({apis:['Date'],now:1000});
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const data={workspace_identity:'a'.repeat(64),paper_id:'fd8460a2-7cf1-4f02-b346-cbcbd2fe6e45',request_id:'paper-timeout'};
  const pages=[],recovery=[];
  let authorities=0,firstDispatched;
  const started=new Promise(resolve=>{firstDispatched=resolve;});
  browser.events.on('tab-created',(_event,tab)=>{
    pages.push(tab);
    const wc=tab.view.webContents;
    wc.loadURL=url=>{
      wc.loading=true;
      wc.emit('did-start-navigation',{},url,false,true);
      if(pages.length===1)firstDispatched();
      else t.mock.timers.setTime(91000);
      return new Promise(()=>{});
    };
  });
  const signal=new AbortController().signal;
  const opened=browser.runTask(signal,data,()=>{
    browser.operation.recordRecovery=(event,details)=>recovery.push({event,...details});
    browser.operation.validateRecovery=async()=>{authorities++;};
    return browser.openPaperPage(data,'10.5555/fixture',{role:'article',signal,deadline:91000});
  });
  await started;
  t.mock.timers.setTime(86000);
  await assert.rejects(opened,{diagnostic:{stage:'navigation',code:'timeout',step:'request'}});
  assert.equal(authorities,1);
  assert.equal(pages.length,2);
  assert.equal(pages[0].view.webContents.isDestroyed(),true);
  assert.equal(pages[1].view.webContents.isDestroyed(),true);
  assert.equal(recovery[0].recovery_action,'paper_reopen');
  assert.equal(recovery[0].step,'page_load');
  assert.equal(recovery.at(-1).step,'request');
  assert.equal(recovery.at(-1).recovery_stop,'budget');
});

test('the existing Session hook gates only matching entry origins and retains an extension after waiter cancellation',async t=>{
  const {BrowserRuntime,partition}=fixture(t);
  let now=Date.parse('Tue, 10 Nov 2026 09:00:00 GMT');
  const sleepers=[];
  const browser=new BrowserRuntime({recoveryTiming:{now:()=>now,pause:(signal,ms)=>new Promise((resolve,reject)=>{
    const abort=()=>reject(signal.reason);
    signal.addEventListener('abort',abort,{once:true});
    sleepers.push({ms,release(){signal.removeEventListener('abort',abort);resolve();}});
  })}});
  t.after(()=>browser.close());await browser.ready;
  const from=browser.createTab(),same=browser.createTab(),canceled=browser.createTab(),other=browser.createTab();
  const url='https://publisher.example/limited';
  const headers=(resourceType,statusCode,retryAfter)=>partition.responseHook({
    webContentsId:from.id,resourceType,statusCode,url,
    responseHeaders:retryAfter?{'Retry-After':[retryAfter]}:{},
  },response=>assert.equal(response.cancel,undefined));
  const run=(id,tab,target,signal=new AbortController().signal)=>browser.runTask(signal,{request_id:id},()=>
    browser.navigate(target,{tab,signal}));
  const tick=()=>new Promise(resolve=>setImmediate(resolve));
  headers('subFrame',429,'3600');
  await run('ignore-subframe',from,url);
  headers('mainFrame',429,'2');
  const stop=new AbortController();
  const pending=run('match',same,url),aborted=run('cancel',canceled,url,stop.signal);
  const rejected=assert.rejects(aborted,{diagnostic:{stage:'navigation',code:'canceled'}});
  await tick();
  assert.deepEqual(sleepers.map(({ms})=>ms),[2000,2000]);
  assert.equal(same.view.webContents.getURL(),'');
  assert.equal((await run('other',other,'https://other.example/')).pageId,other.id);
  headers('mainFrame',503,'Tue, 10 Nov 2026 09:00:05 GMT');
  headers('mainFrame',200);
  stop.abort();await rejected;
  now+=2000;sleepers[0].release();await tick();
  assert.deepEqual(sleepers.map(({ms})=>ms),[2000,2000,3000]);
  assert.equal(same.view.webContents.getURL(),'');
  now+=3000;sleepers[2].release();
  assert.equal((await pending).pageId,same.id);
  headers('mainFrame',429,'3600');
  await assert.rejects(run('budget',from,url),{diagnostic:{stage:'navigation',step:'page_load',code:'http_error',status:429}});
  assert.equal(sleepers.length,3);
});

test('managed refresh ignores obsolete frame and URL failures and reopens the provisional destination',async t=>{
  const {BrowserRuntime,logs}=fixture(t);
  const waits=[],urls=[];
  const browser=new BrowserRuntime({recoveryTiming:{random:()=>0.5,pause:async(_signal,ms)=>{waits.push(ms);}}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({managed:true}),wc=tab.view.webContents,load=wc.loadURL.bind(wc);
  await load('https://previous.example/');
  const original='https://entry.example/start',target='https://publisher.example/provisional';
  wc.loadURL=async url=>{
    urls.push(url);
    if(url===target)return load(url);
    const {processId,routingId}=wc.mainFrame;
    wc.emit('did-start-navigation',{},url,false,true);
    wc.emit('will-redirect',{},target,false,true,processId+1,routingId+1);
    wc.emit('will-redirect',{},'https://unrelated-subframe.example/',false,false);
    wc.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',url,true,processId,routingId);
    wc.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',target,true,processId,routingId-1);
    wc.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',target,false,processId,routingId);
    wc.emit('did-fail-load',{},-3,'ERR_ABORTED',target,true,processId,routingId);
    assert.deepEqual(waits,[]);
    wc.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',target,true,processId+1,routingId+1);
    throw Error('ERR_CONNECTION_CLOSED');
  };
  const signal=new AbortController().signal;
  const doc=await browser.runTask(signal,{request_id:'provisional'},()=>browser.navigate(original,{tab,signal}));
  assert.equal(doc.url,target);
  assert.deepEqual(urls,[original,target]);
  assert.deepEqual(waits,[350]);
  assert.equal(wc.reloads,undefined);
  assert.deepEqual(logs.filter(entry=>entry.event==='page_load_failed')
    .map(entry=>[entry.reason,entry.code,entry.net_code,entry.net_error]),[
    ['url_mismatch','load_failed',-100,'ERR_CONNECTION_CLOSED'],
    ['stale_frame','load_failed',-100,'ERR_CONNECTION_CLOSED'],
    ['current','load_failed',-100,'ERR_CONNECTION_CLOSED'],
    ['load_promise_rejected','load_failed',-100,'ERR_CONNECTION_CLOSED'],
  ]);
});

test('cancel during managed refresh backoff destroys the failed temporary page and dispatches no further action',async t=>{
  const {BrowserRuntime,partition}=fixture(t);
  let sleeping;
  const waiting=new Promise(resolve=>{sleeping=resolve;});
  const browser=new BrowserRuntime({recoveryTiming:{pause:signal=>new Promise((_,reject)=>{
    signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
    sleeping();
  })}});
  t.after(()=>browser.close());await browser.ready;
  const data={workspace_identity:'a'.repeat(64),paper_id:'fd8460a2-7cf1-4f02-b346-cbcbd2fe6e45',request_id:'paper-cancel'};
  const pages=[];
  browser.events.on('tab-created',(_event,tab)=>{
    pages.push(tab);
    const wc=tab.view.webContents;
    wc.loadURL=async url=>{
      wc.url=url;
      wc.emit('did-start-navigation',{},url,false,true);
      networkFailure(partition,wc,{id:1,url});
      throw Error('ERR_CONNECTION_CLOSED');
    };
  });
  const stop=new AbortController(),{signal}=stop;
  const pending=browser.runTask(signal,data,()=>browser.openPaperPage(data,'10.5555/fixture',{role:'article',signal}));
  await waiting;
  stop.abort();
  await assert.rejects(pending,{diagnostic:{stage:'navigation',code:'canceled'}});
  assert.equal(pages.length,1);
  assert.equal(pages[0].view.webContents.reloads,undefined);
  assert.equal(pages[0].view.webContents.isDestroyed(),true);
});

test('a stale failure from the same URL and frame cannot consume a newer refresh budget',async t=>{
  const {BrowserRuntime,partition}=fixture(t);
  const waits=[],recovery=[];
  const browser=new BrowserRuntime({recoveryTiming:{random:()=>0.5,pause:async(_signal,ms)=>{waits.push(ms);}}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({managed:true}),wc=tab.view.webContents,load=wc.loadURL.bind(wc);
  const url='https://publisher.example/article';
  const request=id=>({id,url,method:'GET',resourceType:'mainFrame',webContentsId:tab.id,frame:wc.mainFrame});
  const error=id=>partition.errorHook({...request(id),error:'net::ERR_CONNECTION_CLOSED'});
  const rawError=()=>wc.emit('did-fail-load',{},-100,'ERR_CONNECTION_CLOSED',url,true,wc.mainFrame.processId,wc.mainFrame.routingId);
  let refreshes=0;
  wc.loadURL=async value=>{
    wc.url=value;
    wc.emit('did-start-navigation',{},value,false,true);
    partition.requestHook(request(1),()=>{});
    error(1);rawError();
    throw Error('ERR_CONNECTION_CLOSED');
  };
  wc.reload=()=>{
    refreshes++;
    wc.emit('did-start-navigation',{},url,false,true);
    partition.requestHook(request(refreshes+1),()=>{});
    error(1);rawError();
    if(refreshes===1)error(2);
    else void load(url);
  };
  const signal=new AbortController().signal;
  const doc=await browser.runTask(signal,{request_id:'stale-connection'},()=>{
    browser.operation.recordRecovery=(event,details)=>recovery.push({event,...details});
    return browser.navigate(url,{tab,signal});
  });
  assert.equal(doc.pageId,tab.id);
  assert.equal(refreshes,2);
  assert.deepEqual(waits,[350,700]);
  assert.equal(recovery.at(-1).event,'recovery_succeeded');
});

test('Covers manual waiting cannot renew the absolute parent deadline',async t=>{
  t.mock.timers.enable({apis:['Date','setTimeout'],now:1000});
  const {searchJournalCover}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();await browser.ready;t.after(()=>browser.close());
  browser.events.once('tab-created',(_event,tab)=>{tab.view.webContents.access={markers:{hcaptcha:true,hcaptchaVisible:true}};});
  const signal=new AbortController().signal;
  const pending=browser.runTask(signal,{request_id:'cover-expiry'},()=>searchJournalCover(browser,{name:'Fixture'},
    {signal,progress(){t.mock.timers.tick(600000);}}));
  await assert.rejects(pending,error=>error.diagnostic?.code==='timeout');
  assert.equal(browser.operations.size,0);
});

for(const outcome of ['not_found','clicked','failed'])test(`solver ${outcome} shares the Document attempt ledger across repeated waits`,async t=>{
  const {BrowserRuntime}=fixture(t);let calls=0;
  const browser=new BrowserRuntime({solveCloudflare:async()=>{calls++;return {outcome};}});
  await browser.ready;t.after(()=>browser.close());
  const signal=new AbortController().signal,tab=browser.createTab({present:false});
  tab.view.webContents.access={markers:{cloudflareOptions:true,cloudflareOrchestrator:true}};
  await tab.view.webContents.loadURL('https://fixture.invalid/challenge');
  const expected=outcome==='not_found'?2:1;
  await browser.runTask(signal,{request_id:'attempt-budget'},async()=>{
    browser.bindTaskPage(tab,signal);
    for(let index=0;index<4;index++)assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
    await assert.rejects(browser.waitForPage(tab,{signal,deadline:Date.now()+20}),/timeout/);
    assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
    assert.equal(calls,expected);
    await tab.view.webContents.loadURL('https://fixture.invalid/replacement');
    await browser.inspectPage(tab,{signal});assert.equal(calls,expected+1);
  });
  await browser.runTask(signal,{request_id:'independent-operation'},async()=>{
    browser.bindTaskPage(tab,signal);await browser.inspectPage(tab,{signal});assert.equal(calls,expected+2);
  });
});

test('authentication binding replaced during an owned redirect returns loading instead of ending Login',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();await browser.ready;t.after(()=>browser.close());
  const controller=new AbortController(),tab=browser.createTab({present:false});
  await tab.view.webContents.loadURL('https://idp.example.edu/login');
  await browser.runTask(controller.signal,{request_id:'auth-binding-redirect'},async()=>{
    browser.bindTaskPage(tab,controller.signal);browser.beginAuthentication(tab,controller.signal);
    const original=browser.documents.call.bind(browser.documents);let changed=false;
    browser.documents.call=async(...args)=>{
      const result=await original(...args);
      if(!changed && args[1]==='binding'){changed=true;await tab.view.webContents.loadURL('https://idp.example.edu/verification');}
      return result;
    };
    const waiting=await browser.inspectAuthentication(tab);
    assert.equal(waiting.step,'loading');assert.equal(waiting.waiting,true);assert.equal(waiting.binding,undefined);
    const current=await browser.inspectAuthentication(tab);
    assert.equal(current.binding.url,'https://idp.example.edu/verification');
    assert.equal(browser.documentCurrent(current.binding),true);
    controller.abort();await assert.rejects(browser.inspectAuthentication(tab),/canceled|document_changed/);
  });
});


test('shared Service admission waits for actual destruction and task completion cleans every temporary page',{timeout:5000},async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,pages=[];let finish,ready;
  const started=new Promise(resolve=>{ready=resolve;});
  const first=browser.runTask(signal,{request_id:'physical_a',service_scope:serviceScope,service_id:serviceId},async()=>{
    for(let i=0;i<3;i++){const tab=await browser.newTaskPage({signal,deadline:Date.now()+2000});tab.view.webContents.deferClose=true;pages.push(tab);}
    ready();await new Promise(resolve=>{finish=resolve;});
  });
  await started;finish();await new Promise(setImmediate);
  assert.equal(pages.every(tab=>tab.view.webContents.closeRequested),true);
  assert.equal(browser.tabs.size,3);
  let admitted=false;
  const next=browser.runTask(signal,{request_id:'physical_b',service_scope:serviceScope,service_id:serviceId},async()=>{
    const tab=await browser.newTaskPage({signal,deadline:Date.now()+2000});admitted=true;
    assert.notEqual(tab.id,pages[0].id);
  });
  await new Promise(setImmediate);assert.equal(admitted,false);assert.equal(browser.tabs.size,3);
  pages[0].view.webContents.destroy();await next;
  assert.equal(admitted,true);assert.equal(browser.tabs.size,2);
  pages[1].view.webContents.destroy();pages[2].view.webContents.destroy();await first;
  assert.equal(browser.tabs.size,0);
});

test('Manual Prepare transfers its target to one bounded access context and replaces the previous physical target',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});
  const {visitManualService}=require('../src/workflows/browser-operations.cjs');
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={request_id:'prepare_one',task_id:'prepare_one',workflow_id:'login',
    service_scope:serviceScope,service_id:serviceId,preparation_key:'d'.repeat(64),access_url:'https://manual.example/'};
  const prepare=()=>browser.runTask(signal,data,()=>visitManualService(browser,data,{signal,progress(){}}));
  const first=await prepare(),old=browser.tabs.get(first.evidence.target_page_id);
  assert.ok(old);assert.equal(browser.tabs.size,1);
  const second=await prepare(),current=browser.tabs.get(second.evidence.target_page_id);
  assert.ok(current);assert.notEqual(current.id,old.id);assert.equal(old.view.webContents.isDestroyed(),true);assert.equal(browser.tabs.size,1);
  await browser.runTask(signal,{...data,request_id:'borrow'},()=>browser.bindTaskPage(current,signal));
  assert.equal(browser.tabs.get(current.id),current);assert.equal(current.taskOwner,null);
});

test('managed popup consumes reserved capacity and retained target survives temporary opener cleanup',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={request_id:'popup',workflow_id:'login',service_scope:serviceScope,
    service_id:serviceId,preparation_key:'d'.repeat(64)};
  let parent,child;
  await browser.runTask(signal,data,async()=>{
    await browser.reserveTaskPages(3,{signal,deadline:Date.now()+2000});
    parent=await browser.newTaskPage({signal});browser.associatePage(parent,{role:'service-resource'});
    const response=parent.view.webContents.popup({url:'https://target.example/'});
    assert.equal(response.action,'allow');assert.equal(response.outlivesOpener,true);
    const contents=response.createWindow({});child=browser.tabs.get(contents.id);
    assert.equal(child.resourceOwner,parent.resourceOwner);assert.equal(browser.tabs.size,2);
    browser.retainAccessPage(child,data);
  });
  assert.equal(parent.view.webContents.isDestroyed(),true);assert.equal(child.view.webContents.isDestroyed(),false);
  assert.equal(browser.tabs.size,1);assert.equal(parent.view.webContents.popup({url:'https://late.example/'}).action,'deny');
});

test('saved lower limits revoke unused popup reservations and queued cancellation never creates a page',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:8,service_limit:6}});
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={request_id:'limits',service_scope:serviceScope,service_id:serviceId};
  let parent;
  await assert.rejects(browser.runTask(signal,data,async()=>{
    await browser.reserveTaskPages(5,{signal,deadline:Date.now()+1000});
    parent=await browser.newTaskPage({signal});
    browser.updatePageLimits({global_limit:4,service_limit:3});
    assert.equal(parent.view.webContents.popup({url:'https://unreserved.example/'}).action,'deny');
    assert.equal(browser.tabs.size,1);
  }),/page_capacity/);
  assert.equal(parent.view.webContents.isDestroyed(),true);assert.equal(browser.tabs.size,0);
  let ready,finish;const started=new Promise(resolve=>{ready=resolve;});
  const first=browser.runTask(signal,{...data,request_id:'fill'},async()=>{
    for(let i=0;i<3;i++)await browser.newTaskPage({signal});ready();await new Promise(resolve=>{finish=resolve;});
  });
  await started;const abort=new AbortController();let admitted=false;
  const waiting=browser.runTask(abort.signal,{...data,request_id:'queued'},async()=>{await browser.newTaskPage({signal:abort.signal,deadline:Date.now()+1000});admitted=true;});
  await new Promise(setImmediate);abort.abort();await assert.rejects(waiting,/canceled/);
  assert.equal(admitted,false);assert.equal(browser.tabs.size,3);finish();await first;assert.equal(browser.tabs.size,0);
});

test('late access invalidation closes only the captured old key and reports actual retained Page destruction',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={service_scope:serviceScope,service_id:serviceId,preparation_key:'a'.repeat(64)};
  const closed=[];browser.events.on('access-pages-closed',ids=>closed.push(...ids));
  const prepare=async(key)=>browser.runTask(signal,{...data,request_id:key},async()=>{
    await browser.replaceAccess({...data,preparation_key:key});const tab=await browser.newTaskPage({signal});
    browser.retainAccessPage(tab,{...data,preparation_key:key});return tab;
  });
  const old=await prepare('a'.repeat(64)),current=await prepare('b'.repeat(64));
  await browser.invalidateAccess({scope_id:serviceScope.scope_id,preparation_keys:{[serviceId]:'a'.repeat(64)},authentication_key:null});
  assert.equal(browser.tabs.get(current.id),current);assert.deepEqual(closed,[old.id]);
  current.view.webContents.deferClose=true;
  let settled=false;const cleanup=browser.invalidateAccess({scope_id:serviceScope.scope_id,
    preparation_keys:{[serviceId]:'b'.repeat(64)},authentication_key:null}).then(()=>{settled=true;});
  await new Promise(setImmediate);assert.equal(settled,false);assert.equal(browser.tabs.has(current.id),true);
  current.view.webContents.destroy();await cleanup;assert.deepEqual(closed,[old.id,current.id]);assert.equal(browser.tabs.size,0);
});

test('WoS result workflow loan survives native-operation gaps and stale release cannot free another loan',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:4}});t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={request_id:'query',workflow_id:'run_a',task_id:'run_a',service_scope:serviceScope,
    service_id:serviceId,preparation_key:'c'.repeat(64)};
  let target;
  await browser.runTask(signal,data,async()=>{
    target=await browser.newTaskPage({signal});await target.view.webContents.loadURL('https://www.webofscience.com/wos/woscc/summary/test');
    browser.retainAccessPage(target,data);browser.loanWorkflowPage(target,await browser.documentBinding(target));
  });
  assert.equal(browser.releaseWorkflowPages({workflow_id:'old_run',task_id:'old_run'}).released,false);
  await assert.rejects(browser.runTask(signal,{request_id:'other',service_scope:serviceScope,service_id:'svc_'+'2'.repeat(32)},
    ()=>browser.reserveTaskPages(4,{signal,deadline:Date.now()+20})),/timeout/);
  assert.equal(browser.tabs.get(target.id),target);
  assert.equal(browser.releaseWorkflowPages({workflow_id:'run_a',task_id:'run_a'}).released,true);
  assert.equal(browser.releaseWorkflowPages({workflow_id:'run_a',task_id:'run_a'}).released,false);
  await browser.runTask(signal,{request_id:'after',service_scope:serviceScope,service_id:'svc_'+'2'.repeat(32)},async()=>{
    await browser.reserveTaskPages(4,{signal,deadline:Date.now()+1000});await browser.newTaskPage({signal});
  });
  assert.equal(target.view.webContents.isDestroyed(),true);assert.equal(browser.tabs.size,0);
});

test('an unresolved download closes its retained source at operation cleanup before a fresh context is reused',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,data={request_id:'query',workflow_id:'run_a',task_id:'run_a',service_scope:serviceScope,
    service_id:serviceId,preparation_key:'c'.repeat(64)};
  const closed=[];browser.events.on('access-pages-closed',ids=>closed.push(...ids));
  let target;
  await browser.runTask(signal,data,async()=>{
    target=await browser.newTaskPage({signal});await target.view.webContents.loadURL('https://www.webofscience.com/wos/woscc/summary/test');
    browser.retainAccessPage(target,data);browser.loanWorkflowPage(target,await browser.documentBinding(target));
  });
  const contents=target.view.webContents;contents.deferClose=true;
  let settled=false;
  const cleanup=browser.runTask(signal,{...data,request_id:'export'},async()=>{
    browser.bindTaskPage(target,signal);
    const registration=browser.sessionEvents.registerDownload({owner:browser.operation,attemptId:'missing',contents,
      frame:contents.mainFrame,document:await browser.documentBinding(target),filename:'/tmp/unused',
      deadline:Date.now()+1000,validate:()=>true});
    registration.dispose({dispatched:true});
  }).then(()=>{settled=true;});
  try {
    await new Promise(setImmediate);
    assert.equal(contents.closeRequested,true);assert.equal(settled,false);
    assert.equal(browser.tabs.has(target.id),true);assert.deepEqual(closed,[]);
  } finally {contents.destroy();await cleanup;}
  assert.deepEqual(closed,[target.id]);assert.equal(browser.tabs.has(target.id),false);
  assert.equal(browser.releaseWorkflowPages({workflow_id:'run_a',task_id:'run_a'}).released,false);
  await browser.runTask(signal,{...data,request_id:'retry',workflow_id:'run_b',task_id:'run_b'},async()=>{
    const fresh=await browser.newTaskPage({signal});
    const registration=browser.sessionEvents.registerDownload({owner:browser.operation,attemptId:'fresh',contents:fresh.view.webContents,
      frame:fresh.view.webContents.mainFrame,document:await browser.documentBinding(fresh),filename:'/tmp/fresh',
      deadline:Date.now()+1000,validate:()=>true});
    registration.dispose();
  });
  assert.equal(browser.tabs.size,0);
});


test('creation failure returns its reservation and Session shutdown waits actual destroyed',async t=>{
  const {BrowserRuntime,failNextCreation}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});
  t.after(()=>browser.close());await browser.ready;const signal=new AbortController().signal;
  await browser.runTask(signal,{request_id:'creation',service_scope:serviceScope,service_id:serviceId},async()=>{
    await browser.reserveTaskPages(3,{signal,deadline:Date.now()+1000});failNextCreation();
    await assert.rejects(browser.newTaskPage({signal}),/fixture creation failed/);
    for(let i=0;i<3;i++)await browser.newTaskPage({signal,deadline:Date.now()+1000});
    assert.equal(browser.tabs.size,3);
  });
  assert.equal(browser.tabs.size,0);const tab=browser.createTab({user:true}),contents=tab.view.webContents;contents.deferClose=true;
  const closing=browser.close();assert.equal(browser.close(),closing);await new Promise(setImmediate);
  assert.equal(contents.closeRequested,true);assert.equal(browser.sessionEvents.closed,false);assert.equal(browser.closed,undefined);
  assert.throws(()=>browser.createTab({user:true}),/not ready/);
  try {await assert.rejects(browser.runTask(signal,{request_id:'late'},()=>{throw Error('late task executed');}),/canceled/);}
  finally {contents.destroy();await closing;}
  assert.equal(browser.sessionEvents.closed,true);assert.equal(browser.closed,true);assert.equal(browser.tabs.size,0);
});

test('minimum global capacity evicts an idle completed target so the next queued Prepare tree can finish',{timeout:3000},async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal,saved={request_id:'portal',service_scope:serviceScope,authentication_key:'f'.repeat(64)};let portal,old;
  await browser.runTask(signal,saved,async()=>{portal=await browser.newTaskPage({signal});browser.retainAccessPage(portal,saved,'portal');});
  const firstData={...saved,request_id:'first',service_id:serviceId,preparation_key:'d'.repeat(64)};
  let ready,finish;const started=new Promise(resolve=>{ready=resolve;});
  const first=browser.runTask(signal,firstData,async()=>{
    browser.pinAccessPage(portal,firstData);await browser.reserveTaskPages(3,{signal,deadline:Date.now()+1000});
    await browser.newTaskPage({signal});await browser.newTaskPage({signal});old=await browser.newTaskPage({signal});
    browser.retainAccessPage(old,firstData);ready();await new Promise(resolve=>{finish=resolve;});
  });
  await started;let admitted=false;
  const second=browser.runTask(signal,{...saved,request_id:'second',service_id:'svc_'+'2'.repeat(32)},async()=>{
    browser.pinAccessPage(portal,saved);await browser.reserveTaskPages(3,{signal,deadline:Date.now()+1000});
    admitted=true;for(let i=0;i<3;i++)await browser.newTaskPage({signal});
  });
  await new Promise(setImmediate);assert.equal(admitted,false);finish();await first;await second;
  assert.equal(admitted,true);assert.equal(old.view.webContents.isDestroyed(),true);assert.equal(browser.tabs.size,1);assert.equal(browser.tabs.get(portal.id),portal);
});


test('failed native WebContents adoption retains its slot and cleanup until actual destruction',{timeout:3000},async t=>{
  const {BrowserRuntime,failNextCreation,nativeContents}=fixture(t),browser=new BrowserRuntime({pageLimits:{global_limit:4,service_limit:3}});
  t.after(()=>browser.close());await browser.ready;const signal=new AbortController().signal,contents=nativeContents();contents.deferClose=true;
  let ended=false,failed;
  const result=browser.runTask(signal,{request_id:'adoption',service_scope:serviceScope,service_id:serviceId},async()=>{
    failNextCreation();try{browser.createTab({webContents:contents,present:false});}catch(error){failed=error;}
  }).then(()=>{ended=true;});
  await new Promise(setImmediate);
  try {assert.match(failed.message,/fixture creation failed/);assert.equal(contents.closeRequested,true);assert.equal(ended,false);}
  finally {contents.destroy();await result;}
  let admitted=false;await browser.runTask(signal,{request_id:'after_adoption',service_scope:serviceScope,service_id:serviceId},async()=>{
    await browser.reserveTaskPages(3,{signal,deadline:Date.now()+1000});for(let i=0;i<3;i++)await browser.newTaskPage({signal});admitted=true;
  });
  assert.equal(admitted,true);assert.equal(browser.tabs.size,0);
});
