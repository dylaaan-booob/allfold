'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const hostRequire=require('node:module').createRequire(require.resolve('../src/browser/browser-runtime.cjs'));
const {EventEmitter}=require('node:events');
const os=require('node:os');
const {ImportFailure,checkPage,failedImport}=require('../src/workflows/import-errors.cjs');
const {institutionAuthPage}=require('../src/auth/institution-auth.cjs');
const chromiumVersion='123.4.5.6';
const serviceScope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
const serviceId='svc_'+'1'.repeat(32);
function fixture(t) {
  const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-browser-runtime-test-'));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  let sequence=0,frameSequence=0;
  const frames=new Map();
  const handlers=new Map();
  const logs=[],menus=[];
  const partition={ua:`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 allfold-desktop/1.0.0 Chrome/${chromiumVersion} Electron/1.0.0 Safari/537.36`,
    webRequest:{onBeforeSendHeaders(filter,fn){partition.headerHook=fn;},
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
    async loadURL(url){this.emit('did-start-navigation',{},url,false,true);this.url=url;this.mainFrame.url=url;this.emit('did-navigate',{},url,200);this.emit('did-frame-navigate',{},url,200);this.emit('did-finish-load');}
    async executeJavaScriptInIsolatedWorld(){return {html:this.html || '<title>Article</title>',title:this.title || 'Article',url:this.url,type:'text/html'};}
    close(){this.destroyed=true;this.emit('destroyed');}
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
  class View {constructor(options){this.options=options;this.webContents=options.webContents || new Contents();}setBounds(bounds){this.bounds=bounds;}setVisible(value){this.visible=value;}}
  const electron={app:{getName:()=> 'allfold-desktop',getPath:()=>profile},session:{fromPartition:()=>partition},
    webFrameMain:{fromFrameToken:(_process,token)=>frames.get(token) || null},
    BrowserWindow:Window,WebContentsView:View,Menu:{buildFromTemplate:items=>({popup(){menus.push(items);}})},
    ipcMain:{handle:(name,fn)=>handlers.set(name,fn),removeHandler:name=>handlers.delete(name)}};
  const context=vm.createContext({module:{exports:{}},__dirname:path.dirname(require.resolve('../src/browser/browser-runtime.cjs')),URL,Buffer,Date,AbortController,AbortSignal,setTimeout,clearTimeout,
    require:name=>name==='electron'?electron:name==='./document-runtime.cjs'?{DocumentRuntime:class {
      constructor(browser){this.browser=browser;}
      async call(doc,action){if(action==='snapshot')return this.browser.tabs.get(doc.pageId).view.webContents.executeJavaScriptInIsolatedWorld();return '';}
      dispose(){}
    }}:name==='../shared/logging.cjs'?{...require('../src/shared/logging.cjs'),
      log:(level,event,details)=>logs.push({level,event,...details})}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/browser/browser-runtime.cjs'),'utf8'),context);
  return {...context.module.exports,partition,handlers,logs,menus,host:new Window()};
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
  browser.beginAuthentication(ordinary,controller.signal);
  const wc=ordinary.view.webContents.popup({url:'about:blank'}).createWindow({});
  const popup=browser.tabs.get(wc.id);await wc.loadURL('https://idp.example.edu/login');
  wc.runAuth=ordinary.view.webContents.runAuth;
  const pending=browser.handleAuthentication(popup);await new Promise(setImmediate);
  assert.equal(reads,1);controller.abort();resolveCredentials({username:'PRIVATE_USER',password:'PRIVATE_PASSWORD'});
  await pending;assert.equal(actions,0);
});
for(const submission of [
  {url:'https://other.example/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/login'},
  {url:'file:///tmp/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/login'},
  {url:'https://idp.example.edu/submit',body:'csrf=PRIVATE',referrer:'https://idp.example.edu/stale'},
])test('Main refuses unsafe or stale consent submission metadata',async t=>{
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime(),controller=new AbortController();
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab(),wc=tab.view.webContents;
  await wc.loadURL('https://idp.example.edu/login');browser.beginAuthentication(tab,controller.signal);
  wc.runAuth=code=>JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1))[0]==='inspect'
    ?{step:'release',waiting:true}:{submission};
  let posts=0;wc.loadURL=()=>{posts++;return Promise.resolve();};
  await browser.handleAuthentication(tab);assert.equal(posts,0);
  assert.doesNotMatch(JSON.stringify(logs),/PRIVATE|csrf=|submit|stale/);
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
  const auth=browser.beginAuthentication(tab,controller.signal);
  await browser.inspectAuthentication(tab);
  auth.institution=false;
  await browser.inspectAuthentication(tab);
  auth.origins.add('https://idp.example.edu');
  await browser.inspectAuthentication(tab);
  controller.abort();await browser.inspectAuthentication(tab);
  assert.deepEqual(modes,['page','institution','page','institution','page']);
});
test('selecting another tab does not retarget the document, but reload/navigation invalidates it',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  const doc=await browser.navigate('https://example.org/paper');
  const task=browser.taskTab;
  await browser.command({action:'new'});
  assert.notEqual(browser.selected,task);
  assert.equal(browser.documentCurrent(doc),true);
  await assert.rejects(browser.command({action:'close',id:task.id}),/active task page/);
  await browser.command({action:'navigate',id:task.id,url:'https://example.org/paper'});
  assert.equal(browser.documentCurrent(doc),false);
  browser.endTask();await browser.command({action:'close',id:task.id});
  assert.equal(browser.tabs.has(task.id),false);
});
test('Service queries isolate configurations without pages and task navigation preserves presentation',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const visible=browser.createTab();
  browser.beginOperation(new AbortController().signal,{request_id:'first',task_id:'batch',
    service_scope:serviceScope,service_id:serviceId});
  assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
  assert.equal(browser.tabs.size,1);
  const tab=browser.createTab({present:false});
  browser.associatePage(tab,{role:'import',doi:'10.5555/first'});
  browser.bindTaskPage(tab);
  const doc=await browser.navigate('https://example.org/first');
  assert.equal(browser.selected,visible);
  assert.equal(doc.pageId,tab.id);
  assert.equal(browser.servicePages(serviceScope.scope_id,serviceId)[0].active,true);
  const otherScope={...serviceScope,scope_id:'d'.repeat(64)};
  browser.endTask();
  assert.equal(browser.taskTab,null);
  assert.equal(browser.pageAssociation(tab.id).active,false);
  browser.beginOperation(new AbortController().signal,{request_id:'second',task_id:'batch',
    service_scope:otherScope,service_id:serviceId});
  browser.associatePage(tab,{role:'import',doi:'10.5555/second'});
  browser.bindTaskPage(tab);
  await browser.navigate('https://example.org/second');
  assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
  assert.equal(browser.servicePages(otherScope.scope_id,serviceId).length,1);
  assert.equal(browser.tabs.size,2);
  assert.equal(browser.selected,visible);
  browser.endTask();
  browser.beginOperation(new AbortController().signal,{request_id:'third',task_id:'batch',service_scope:otherScope});
  browser.associatePage(tab,{role:'import',doi:'10.5555/unmatched'});
  browser.bindTaskPage(tab);
  assert.equal(browser.pageAssociation(tab.id).service_id,null);
  assert.equal(browser.servicePages(otherScope.scope_id,serviceId).length,0);
});
test('popup provenance is descriptive, disappears on destruction, and never authorizes credentials',async t=>{
  let reads=0;
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime({readCASCredentials:async()=>{reads++;return {};}});
  t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController();
  browser.beginOperation(controller.signal,{request_id:'first',service_scope:serviceScope,service_id:serviceId});
  const source=browser.createTab();browser.associatePage(source,{role:'service-resource'});
  browser.bindTaskPage(source);
  const wc=source.view.webContents.popup({url:'https://idp.example.edu/login'}).createWindow({});
  const popup=browser.tabs.get(wc.id);
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
  browser.endTask();
  assert.equal(browser.tabs.size,1);
  browser.beginOperation(new AbortController().signal,{request_id:'second'});
  assert.equal(browser.taskTab,null);
  await assert.rejects(browser.navigate('https://example.org/new'),/page_closed/);
  wc.emit('render-process-gone',{}, {reason:'crashed',exitCode:1});
  assert.equal(browser.pageAssociation(popup.id),null);
  assert.equal(browser.servicePages(serviceScope.scope_id,serviceId).length,0);
});

test('a failed/canceled ImportPage can be explicitly reused, and a delayed old navigation cannot bind a new task',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const first=new AbortController(),tab=browser.createTab();
  browser.beginOperation(first.signal,{request_id:'old'});browser.bindTaskPage(tab);
  tab.navigation.begin({automatic:true,owner:browser.operation,signal:first.signal});
  first.abort();browser.endTask();
  browser.beginOperation(new AbortController().signal,{request_id:'new'});
  browser.bindTaskPage(tab);
  assert.equal((await browser.navigate('https://example.org/new')).pageId,tab.id);
  browser.endTask();
  browser.beginOperation(new AbortController().signal,{request_id:'late'});browser.bindTaskPage(tab);
  let ready;browser.ready=new Promise(resolve=>{ready=resolve;});
  const pending=browser.navigate('https://example.org/old-late');
  browser.endTask();browser.beginOperation(new AbortController().signal,{request_id:'latest'});
  const other=browser.createTab({present:false});browser.bindTaskPage(other);
  ready();await assert.rejects(pending,/canceled/);
  assert.equal(browser.taskTab,other);
  assert.equal(other.view.webContents.getURL(),'');
  assert.equal(tab.view.webContents.getURL(),'https://example.org/new');
});

test('Browser refuses an HTTP 200 Imperva block before handing the document to the caller',async t=>{
  const {BrowserRuntime}=fixture(t);
  let solverCalls=0;
  const browser=new BrowserRuntime({solveCloudflare:async()=>{solverCalls++;}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({present:false});
  const signal=new AbortController().signal;
  browser.beginOperation(signal,{request_id:'blocked'});
  const url='https://projecteuclid.org/journals/example/10.5555/article.full';
  const contents=tab.view.webContents;
  const block='<iframe src="/_Incapsula_Resource?incident_id=123456-987654&amp;edet=15&amp;opaque=private">'
    +'Request unsuccessful. Incapsula incident ID: 123456-987654</iframe>';
  contents.html='<body><iframe src="/_Incapsula_Resource?fixture=helper" hidden></iframe>'+block+'</body>';
  await assert.rejects(browser.navigate(url,{tab,signal}),{diagnostic:{stage:'navigation',code:'site_restricted',status:200,
    imperva_edet:15,imperva_incident_id:'123456-987654'}});
  assert.equal(solverCalls,0);
  browser.endTask();

  browser.beginOperation(signal,{request_id:'article'});
  contents.html='<body><article>Example article</article>'+block+'</body>';
  assert.equal((await browser.navigate(url,{tab,signal})).status,200);
});

test('Imperva CAPTCHA waits for the same page to finish verification without calling the Solver',async t=>{
  const {BrowserRuntime}=fixture(t);
  let solverCalls=0;
  const browser=new BrowserRuntime({solveCloudflare:async()=>{solverCalls++;}});
  t.after(()=>browser.close());await browser.ready;
  const tab=browser.createTab({present:false});
  const signal=new AbortController().signal;
  browser.beginOperation(signal,{request_id:'imperva-challenge'});
  const contents=tab.view.webContents;
  contents.html='<body><iframe src="/_Incapsula_Resource?edet=12&amp;incident_id=123-456">'
    +'Request unsuccessful. Incapsula incident ID: 123-456</iframe></body>';
  const url='https://projecteuclid.org/journals/example/10.5555/article.full';
  let reportWaiting;
  const waiting=new Promise(resolve=>{reportWaiting=resolve;});
  const navigation=browser.navigate(url,{tab,signal,deadline:Date.now()+5000,onWaiting:reportWaiting});
  const diagnostic=await Promise.race([waiting,navigation.then(()=>assert.fail('Returned before verification'))]);
  assert.deepEqual(diagnostic,{stage:'navigation',code:'verification_page',status:200,
    imperva_edet:12,imperva_incident_id:'123-456'});
  assert.equal(browser.taskTab,tab);
  assert.equal(solverCalls,0);

  contents.html='<body><article>Example article after verification</article></body>';
  await contents.loadURL(url);
  const doc=await navigation;
  assert.equal(doc.pageId,tab.id);
  assert.match(doc.html,/Example article after verification/);
  assert.equal(solverCalls,0);
});

test('Imperva diagnostics omit ambiguous parameters and accept a displayed incident ID',()=>{
  const {checkPage}=require('../src/browser/browser-errors.cjs');
  const page=(query,id)=>'<body><iframe src="/_Incapsula_Resource?'+query
    +'">Request unsuccessful. Incapsula incident ID: '+id+'</iframe></body>';
  const blocked={stage:'navigation',code:'site_restricted',status:200};
  assert.throws(()=>checkPage(200,'',page('edet=15&amp;edet=16&amp;incident_id=111-222','333-444')),
    {diagnostic:blocked});
  assert.throws(()=>checkPage(200,'',page('edet=16%20private','123-456')),
    {diagnostic:{...blocked,imperva_incident_id:'123-456'}});
});

test('Prepare reuses an unassigned Portal across Services and records resource/target popup provenance',async t=>{
  const {prepareService}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const portal=browser.createTab(),wc=portal.view.webContents;
  await wc.loadURL('https://ds.carsi.edu.cn/resource/resource.php');
  browser.carsiPortal={task:'prepare',id:portal.id};
  wc.runAuth=code=>{
    const [action]=JSON.parse(code.slice(code.lastIndexOf('(...')+4,-1));
    if(action==='ready')return {status:'ready',checked:false};
    if(action==='poll')return {status:'complete',selection:{status:'selected',url:'https://ds.carsi.edu.cn/resource/resourceDetail.php?id=fixture'}};
    return {status:'pending'};
  };
  browser.events.on('tab-created',(_event,tab)=>{
    const contents=tab.view.webContents,original=contents.executeJavaScriptInIsolatedWorld.bind(contents);
    contents.executeJavaScriptInIsolatedWorld=async(world,scripts)=>{
      if(!scripts)return original();
      const [action]=JSON.parse(scripts[0].code.slice(scripts[0].code.lastIndexOf('(...')+4,-1));
      if(action==='check')return {status:'ready'};
      assert.equal(action,'visit');
      const popup=contents.popup({url:'https://example.org/target'}).createWindow({});
      await popup.loadURL('https://example.org/target');
      return {status:'visited_click'};
    };
  });
  for(const [index,id] of [serviceId,'svc_'+'2'.repeat(32)].entries()) {
    const controller=new AbortController();
    browser.beginOperation(controller.signal,{request_id:'prepare'+index,task_id:'prepare',service_id:id,service_scope:serviceScope});
    const result=await prepareService(browser,{task_id:'prepare',service_id:id,name:'Saved Service',institution_name:'Test'},
      {signal:controller.signal,progress(){}});
    assert.equal(result.outcome,'Opened');
    const {source_page_id:detail,target_page_id:target}=result.evidence;
    assert.equal(browser.pageAssociation(portal.id).service_id,null);
    assert.equal(browser.pageAssociation(detail).service_id,id);
    assert.equal(browser.pageAssociation(detail).source_page_id,portal.id);
    assert.equal(browser.pageAssociation(target).service_id,id);
    assert.equal(browser.pageAssociation(target).source_page_id,detail);
    assert.equal(browser.pageAssociation(target).role,'service-target');
    assert.equal(browser.carsiPortal.id,portal.id);
    assert.equal(browser.events.listenerCount('tab-created'),1);
    browser.endTask();
  }
  assert.equal(browser.tabs.size,5);
});

test('Manual URL opening preserves the task; Covers use an auxiliary page without Service authority',async t=>{
  const {searchJournalCover}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal;
  browser.beginOperation(signal,{request_id:'import',service_scope:serviceScope,service_id:serviceId});
  const task=browser.createTab();browser.associatePage(task,{role:'import'});browser.bindTaskPage(task);
  const manual=await browser.openURL('https://manual.example.org/');
  assert.equal(browser.taskTab,task);assert.equal(browser.selected,manual);
  assert.equal(browser.pageAssociation(manual.id),null);
  browser.endTask();
  browser.beginOperation(signal,{request_id:'cover',service_scope:{...serviceScope,secret:'PRIVATE'},service_id:serviceId});
  browser.events.once('tab-created',(_event,tab)=>{
    const original=tab.view.webContents.executeJavaScriptInIsolatedWorld.bind(tab.view.webContents);
    tab.view.webContents.executeJavaScriptInIsolatedWorld=async(world,scripts)=>scripts?{ready:true,source_url:null}:original();
  });
  assert.equal((await searchJournalCover(browser,{name:'Saved Journal'},{signal,progress(){}})).source_url,null);
  const cover=browser.taskTab;
  assert.equal(browser.pageAssociation(cover.id).role,'auxiliary');
  assert.equal(browser.pageAssociation(cover.id).service_id,null);
  assert.equal(browser.selected,manual);
  browser.endTask();assert.equal(browser.tabs.size,3);
  assert.doesNotMatch(JSON.stringify(browser.pageAssociation(cover.id)),/PRIVATE|secret/);
  assert.doesNotMatch(JSON.stringify(logs),/PRIVATE|secret/);
  assert.equal(logs.find(event=>event.event==='page_associated').scope_id,serviceScope.scope_id);
  assert.throws(()=>browser.beginOperation(signal,{service_id:serviceId}),/Invalid browser Service identity/);
  browser.close();assert.equal(browser.tabs.size,0);assert.equal(browser.selected,null);
});

test('closing the shared Portal keeps the Prepare initialization marker and refuses login replay',async t=>{
  const {prepareService}=require('../src/workflows/browser-operations.cjs');
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const signal=new AbortController().signal;
  browser.beginOperation(signal,{request_id:'first',task_id:'prepare',service_id:serviceId,service_scope:serviceScope});
  const portal=browser.createTab(),detail=browser.createTab();
  browser.carsiPortal={task:'prepare',id:portal.id};
  browser.bindTaskPage(detail);
  await browser.command({action:'close',id:portal.id});
  browser.endTask();
  browser.beginOperation(signal,{request_id:'second',task_id:'prepare',service_id:serviceId,service_scope:serviceScope});
  const recreated=()=>{throw Error('Unexpected Portal recreation');};
  browser.events.once('tab-created',recreated);
  try {
    await assert.rejects(prepareService(browser,{task_id:'prepare',name:'Next saved Service',institution_name:'Test'},
      {signal,progress(){}}),/page_closed/);
    assert.equal(browser.carsiPortal.task,'prepare');
    assert.equal(browser.carsiPortal.id,null);
    assert.equal(browser.tabs.size,1);
  } finally {browser.events.removeListener('tab-created',recreated);}
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
test('explicit saved Service opening retains descriptive identity without task or credential authority',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const command={action:'open-service',url:'https://library.example.org/',service_scope:serviceScope,
    service_id:serviceId,workflow_id:'kept_a',task_id:'prepare_a'};
  await browser.command(command);
  const page=browser.selected;
  assert.equal(browser.pageAssociation(page.id).role,'manual-service');
  assert.equal(browser.pageAssociation(page.id).service_id,serviceId);
  assert.equal(browser.pageAssociation(page.id).active,false);
  assert.equal(page.authContext,undefined);assert.equal(browser.taskTab,null);
  await browser.command({...command,workflow_id:'kept_b',task_id:'prepare_b'});
  assert.equal(browser.tabs.size,1);assert.equal(browser.selected,page);
  assert.equal(browser.pageAssociation(page.id).workflow_id,'kept_b');
  assert.equal(browser.pageAssociation(page.id).task_id,'prepare_b');
  await assert.rejects(browser.command({...command,service_id:'invalid'}),/Invalid browser Service/);
});
const cloudflarePageOptions='<script>window._cf_chl_opt = {cType:"managed"};</script>';
const cloudflarePageScript='<script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>';
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



test('canceled attachment recovery cannot create a helper tab',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController();browser.beginOperation(controller.signal);browser.operation.action='import_paper';
  const tab=browser.createTab();browser.bindTaskPage(tab);
  await tab.view.webContents.loadURL('https://one.test/article');const doc=await browser.snapshot(tab);controller.abort();
  const count=browser.tabs.size;
  await assert.rejects(browser.bypassAttachment('https://one.test/file',doc,{visible:true,signal:controller.signal}));
  assert.equal(browser.tabs.size,count);
});

test('attachment capture timeout and source replacement cannot leak listeners or accept late responses',async t=>{
  t.mock.timers.enable({apis:['Date','setTimeout'],now:1000});
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  browser.beginOperation(new AbortController().signal);browser.operation.action='import_paper';
  const tab=browser.createTab();browser.bindTaskPage(tab);
  await tab.view.webContents.loadURL('https://one.test/article');const doc=await browser.snapshot(tab);
  const first=browser.captureAttachment(tab,doc,{deadline:Date.now()+5000});t.mock.timers.tick(5000);
  await assert.rejects(first.url,error=>error.diagnostic?.code==='timeout');assert.equal(browser.attachmentCaptures.size,0);
  const second=browser.captureAttachment(tab,doc);
  await tab.view.webContents.loadURL('https://one.test/replacement');
  await assert.rejects(second.url,error=>error.diagnostic?.code==='document_changed');assert.equal(browser.attachmentCaptures.size,0);
  browser.operation.action='enrich_paper';
  assert.throws(()=>browser.captureAttachment(tab,doc));
});
test('reused page lifecycle records retain each workflow association before replacement and renderer invalidation',async t=>{
  const {BrowserRuntime,logs}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController(),tab=browser.createTab();
  browser.beginOperation(controller.signal,{request_id:'request_a',task_id:'task_a',workflow_id:'workflow_a',service_scope:serviceScope,service_id:serviceId});
  browser.associatePage(tab,{role:'import'});browser.bindTaskPage(tab,controller.signal);browser.endTask();
  assert.equal(browser.pageAssociation(tab.id).workflow_id,'workflow_a');
  browser.beginOperation(controller.signal,{request_id:'request_b',task_id:'task_b',workflow_id:'workflow_b',service_scope:serviceScope,service_id:serviceId});
  browser.associatePage(tab,{role:'import'});browser.bindTaskPage(tab,controller.signal);
  tab.view.webContents.emit('render-process-gone',{}, {reason:'crashed',exitCode:1});
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
      wc.html=cloudflarePageOptions+cloudflarePageScript+(hcaptcha?'<iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe>':'');
      await wc.loadURL('https://example.org/challenge');
      const result=await browser.inspectPage(tab,{signal});
      assert.equal(result.waiting,true);
      if(hcaptcha)assert.equal(result.diagnostic?.code,'verification_page');
      else assert.deepEqual(solved,[tab.id]);
      assert.equal(solved.length,1);
    });
  }
});

test('Enrich, cancellation and Import retain the same locked Paper tab for its Workspace',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();
  t.after(()=>browser.close());await browser.ready;
  const data={workspace_identity:'a'.repeat(64),paper_id:'fd8460a2-7cf1-4f02-b346-cbcbd2fe6e45'};
  const doi='10.5555/fixture',stop=new AbortController();
  let first;
  await browser.runTask(stop.signal,{...data,request_id:'enrich'},async()=>{
    first=await browser.openPaperPage(data,doi,{role:'enrich',signal:stop.signal});
    const page=browser.state().tabs.find(tab=>tab.id===first.pageId);
    assert.equal(page.managed,true);assert.equal(page.busy,true);
    await assert.rejects(browser.command({action:'reload',id:page.id}),/active task page/i);
    stop.abort();
  });
  const tab=browser.tabs.get(first.pageId);
  assert.ok(tab);assert.equal(browser.pageAssociation(tab.id).active,false);
  for(const action of ['close','navigate','back','forward']) {
    const command={action,id:tab.id,...(action==='navigate'?{url:'https://unrelated.example/'}:{})};
    await assert.rejects(browser.command(command),/managed page/i);
  }
  const signal=new AbortController().signal;
  await browser.runTask(signal,{...data,request_id:'import'},async()=>{
    const imported=await browser.openPaperPage(data,doi,{role:'import',signal});
    assert.equal(imported.pageId,first.pageId);
    assert.equal(imported.frameToken,first.frameToken);
    assert.equal(browser.pageAssociation(tab.id).role,'import');
  });
  await browser.command({action:'reload',id:tab.id});
  assert.equal(tab.view.webContents.reloads,1);
  await tab.view.webContents.loadURL('https://publisher.example/site-navigation');
  await browser.runTask(signal,{...data,request_id:'retry'},async()=>{
    const restored=await browser.openPaperPage(data,doi,{role:'import',signal});
    assert.equal(restored.pageId,tab.id);
    assert.equal(restored.url,'https://doi.org/10.5555%2Ffixture');
    assert.notEqual(restored.frameToken,first.frameToken);
  });
  await assert.rejects(browser.runTask(signal,{...data,request_id:'changed'},async()=>{
    const changed=await browser.openPaperPage(data,'10.5555/corrected',{role:'enrich',signal});
    assert.equal(changed.pageId,tab.id);
    assert.equal(changed.url,'https://doi.org/10.5555%2Fcorrected');
    throw Error('fixture translation failure');
  }),/fixture translation failure/);
  assert.ok(browser.tabs.has(tab.id));
  assert.equal(browser.pageAssociation(tab.id).active,false);
  const other={...data,workspace_identity:'b'.repeat(64)};
  await browser.runTask(signal,{...other,request_id:'other'},async()=>{
    const opened=await browser.openPaperPage(other,doi,{role:'import',signal});
    assert.notEqual(opened.pageId,tab.id);
  });
  assert.equal(browser.tabs.size,2);
});
