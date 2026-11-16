'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
test('native action messages require the original request, sender and frame before one dispatch',async t=>{
  const {EventEmitter}=require('node:events'),vm=require('node:vm');
  const ipc=new EventEmitter(),messages=[],contents={mainFrame:{framesInSubtree:[]}};
  const doc={pageId:1,processId:2,frameToken:'source',url:'https://www.sciencedirect.com/science/article/pii/S1234567890123456'};
  const frame={send:(_channel,message)=>messages.push(message)};
  const browser={documentFrame:()=>frame,tabs:new Map([[1,{id:1,view:{webContents:contents}}]])};
  const hostRequire=require('node:module').createRequire(require.resolve('../src/browser/body-action-runtime.cjs'));
  const context=vm.createContext({module:{exports:{}},URL,require:name=>name==='electron'?{ipcMain:ipc}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/browser/body-action-runtime.cjs'),'utf8'),context);
  const runtime=new context.module.exports.BodyActionRuntime(browser);t.after(()=>runtime.dispose());
  const candidate={url:doc.url+'/pdfft',platform:'sciencedirect',rule_id:'R024'};
  const plan={url:candidate.url,request_url:candidate.url,method:'GET',target:'self',target_name:''};
  const event=()=>({sender:contents,senderFrame:{processId:2,frameToken:'source'}});
  const pending=runtime.prepare(doc,candidate,{deadline:Date.now()+1000}),id=messages[0].id;
  ipc.emit('body:prepared',{...event(),sender:{}},{id,plan});
  ipc.emit('body:prepared',{...event(),senderFrame:{processId:2,frameToken:'other'}},{id,plan});
  ipc.emit('body:prepared',event(),{id:'other-request',plan});
  ipc.emit('body:prepared',event(),{id,plan});
  const prepared=await pending;
  let dispatched=0;
  const done=prepared.dispatch(()=>dispatched++);
  ipc.emit('body:prepared',event(),{id,plan}); // Duplicate prepare cannot settle dispatch.
  const foreign={...event(),sender:{}};ipc.emit('body:dispatching',foreign,{id,plan});assert.equal(foreign.returnValue,false);
  assert.equal(dispatched,0);
  const accepted=event();ipc.emit('body:dispatching',accepted,{id,plan});assert.equal(accepted.returnValue,true);
  await done;assert.equal(dispatched,1);
  const duplicate=event();ipc.emit('body:dispatching',duplicate,{id,plan});assert.equal(duplicate.returnValue,false);
  prepared.dispose();assert.equal(runtime.pending.size,0);
});
test('native body actions preserve original POST/navigation and first-response frame/popup output',{timeout:65000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-body-native-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,
    'mime-octet,mime-missing,mime-wrong,mime-fake,sciencedirect-missing,ambiguous-form,ambiguous-get,form-replaced,form-missing,get-replaced,sciencedirect-replaced,microbiology-redirect,microbiology-redirect-path,microbiology-redirect-origin,microbiology-redirect-twice,microbiology-redirect-status,microbiology-redirect-self-302,microbiology-redirect-self-303,microbiology-redirect-self-307,url-doi-form,named-popup,named-popup-collision,attachment,inline,iframe,popup,cancel,interrupted,no-item,unrelated,sciencedirect,completed-late-signals'],
    {timeout:60000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
test('ScienceDirect original HTML reader follows observed same-PII reader and CDN continuations',{timeout:45000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-native-reader-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,
    'sciencedirect-reader,sciencedirect-reader-self,sciencedirect-reader-auth-return,sciencedirect-reader-cycle,sciencedirect-reader-reload,sciencedirect-reader-loop,sciencedirect-reader-wrong-pii,sciencedirect-reader-wrong-origin,sciencedirect-reader-wrong-source,sciencedirect-reader-twice,sciencedirect-reader-challenge,sciencedirect-reader-http-error,sciencedirect-reader-cancel,sciencedirect-reader-cdn-unavailable,sciencedirect-direct-cdn-unavailable'],
    {timeout:40000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
test('native output replacement is refused and records the accepted Chromium cancellation race',{timeout:15000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-body-native-replacement-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  // A cancelled item can asynchronously delete the substituted pathname. The
  // accepted boundary asserts application refusal, never replacement survival.
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'replace'],
    {timeout:10000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);
  assert.match(stdout,/replacement_exists_at_terminal/);t.diagnostic(stdout.trim());
});
test('native popup completes after an unlinked empty destination reservation',{timeout:15000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-native-reservation-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'popup-reservation'],
    {timeout:10000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed|NATIVE OUTPUT FAILURE/);t.diagnostic(stdout.trim());
});
test('public native Download publishes original response through SQLite and Workspace',{timeout:65000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-public-native-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await promisify(execFile)(require('electron'),[path.join(__dirname,'body-native.fixture.cjs'),profile,'public'],
    {timeout:60000,maxBuffer:1024*1024,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/PUBLIC BODY NATIVE PASS/);assert.doesNotMatch(stderr,/Check failed/);t.diagnostic(stdout.trim());
});
