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
    getTitle(){return this.url;}
    isLoading(){return false;}
    isLoadingMainFrame(){return !!this.loading;}
    isDestroyed(){return !!this.destroyed;}
    isCrashed(){return false;}
    stop(){this.stopped=true;}
    reload(){this.reloads=(this.reloads || 0)+1;this.emit('did-start-navigation',{},this.url || 'https://example.org/',false,true);}
    send(){}
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
  class View {constructor(options){this.options=options;this.webContents=options.webContents || new Contents();}setBounds(bounds){this.bounds=bounds;}}
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
  return {...context.module.exports,partition,handlers,logs,menus};
}
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
test('remote popups remain native managed tabs; shell IPC and unsafe URLs are refused',async t=>{
  const {BrowserRuntime,handlers}=fixture(t),browser=new BrowserRuntime();await browser.show();
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
  assert.throws(()=>handlers.get('browser:command')({sender:source},{action:'state'}),/Untrusted/);
  let prevented=false;
  browser.window.emit('close',{preventDefault(){prevented=true;}});
  assert.equal(prevented,true);assert.equal(browser.window.visible,false);assert.equal(browser.tabs.size,2);
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



test('canceled attachment recovery cannot create a helper tab',async t=>{
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  const controller=new AbortController();browser.beginOperation(controller.signal);browser.operation.action='import_paper';
  const tab=browser.createTab();browser.taskTab=tab;browser.taskActive=true;
  await tab.view.webContents.loadURL('https://one.test/article');const doc=await browser.snapshot(tab);controller.abort();
  const count=browser.tabs.size;
  await assert.rejects(browser.bypassAttachment('https://one.test/file',doc,{visible:true,signal:controller.signal}));
  assert.equal(browser.tabs.size,count);
});

test('attachment capture timeout and source replacement cannot leak listeners or accept late responses',async t=>{
  t.mock.timers.enable({apis:['Date','setTimeout'],now:1000});
  const {BrowserRuntime}=fixture(t),browser=new BrowserRuntime();t.after(()=>browser.close());await browser.ready;
  browser.beginOperation(new AbortController().signal);browser.operation.action='import_paper';
  const tab=browser.createTab();browser.taskTab=tab;browser.taskActive=true;
  await tab.view.webContents.loadURL('https://one.test/article');const doc=await browser.snapshot(tab);
  const first=browser.captureAttachment(tab,doc,{deadline:Date.now()+5000});t.mock.timers.tick(5000);
  await assert.rejects(first.url,error=>error.diagnostic?.code==='timeout');assert.equal(browser.attachmentCaptures.size,0);
  const second=browser.captureAttachment(tab,doc);
  await tab.view.webContents.loadURL('https://one.test/replacement');
  await assert.rejects(second.url,error=>error.diagnostic?.code==='document_changed');assert.equal(browser.attachmentCaptures.size,0);
  browser.operation.action='enrich_paper';
  assert.throws(()=>browser.captureAttachment(tab,doc));
});
