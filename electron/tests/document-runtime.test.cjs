'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const {EventEmitter}=require('node:events');
function fixture(t) {
  const ipc=new EventEmitter(),contents=new EventEmitter(),messages=[];
  const doc={pageId:1,processId:2,frameToken:'frame',documentId:'1-2-3-4',url:'https://fixture.invalid/article'};
  let current=true;
  const frame={send:(_channel,message)=>messages.push(message)};
  const browser={tabs:new Map([[1,{view:{webContents:contents}}]]),
    partition:{registerPreloadScript(){return 'preload';},unregisterPreloadScript(){}},
    documentFrame:()=>current?frame:null,documentCurrent:()=>current};
  const hostRequire=require('node:module').createRequire(require.resolve('../src/browser/document-runtime.cjs'));
  const context=vm.createContext({module:{exports:{}},setTimeout,clearTimeout,
    require:name=>name==='electron'?{ipcMain:ipc}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/browser/document-runtime.cjs'),'utf8'),context);
  const runtime=new context.module.exports.DocumentRuntime(browser);t.after(()=>runtime.dispose());
  const reply=(result,{id=messages.at(-1).id,sender=contents,processId=2,frameToken='frame',documentId='1-2-3-4',url=doc.url}={})=>{
    ipc.emit('document:result',{sender,senderFrame:{processId,frameToken}},
      {id,result,documentId,url});
  };
  return {runtime,doc,contents,frame,messages,reply,changed(){current=false;contents.emit('did-frame-navigate');}};
}
test('Document replies require the exact sender/frame/document and project bounded fields',async t=>{
  const f=fixture(t),pending=f.runtime.call(f.doc,'binding');
  f.reply({type:'text/html'},{sender:{}});f.reply({type:'text/html'},{frameToken:'other'});
  assert.equal(f.runtime.pending.size,1);
  f.reply({type:'text/html',html:'private',cookie:'secret'});
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)),{type:'text/html',documentId:'1-2-3-4'});
  const stale=f.runtime.call(f.doc,'binding');f.reply({type:'text/html'},{documentId:'9-8-7-6'});
  await assert.rejects(stale,/document_changed/);
  assert.equal(f.runtime.pending.size,0);assert.equal(f.contents.listenerCount('did-frame-navigate'),0);
});
test('navigation, crash and cancellation end pending probes and clean listeners',async t=>{
  for(const reason of ['navigation','crash','cancel']) {
    const f=fixture(t),controller=new AbortController();
    const pending=f.runtime.call(f.doc,'binding',{}, {signal:controller.signal});
    if(reason==='navigation')f.changed();
    if(reason==='crash')f.contents.emit('render-process-gone');
    if(reason==='cancel')controller.abort();
    await assert.rejects(pending,/document_changed|page_closed|canceled/);
    assert.equal(f.runtime.pending.size,0);
    for(const event of ['did-start-navigation','did-navigate-in-page','did-frame-navigate','destroyed','render-process-gone'])
      assert.equal(f.contents.listenerCount(event),0);
  }
});
test('replaced binding URLs and unsupported operations fail closed',async t=>{
  const f=fixture(t);
  await assert.rejects(f.runtime.call(f.doc,'article'),/document_operation_failed/);
  const replaced=f.runtime.call(f.doc,'binding');f.reply({type:'text/html'},{url:'https://fixture.invalid/replaced'});
  await assert.rejects(replaced,/document_changed/);
  await assert.rejects(f.runtime.call(f.doc,'execute',{code:'arbitrary'}),/document_operation_failed/);
  await assert.rejects(f.runtime.call(f.doc,'pdf',{readerKind:null,doiCasefold:{}}),/document_operation_failed/);
  assert.equal(f.messages.length,1);
});
const clues={status:'complete',landing_url:'https://journal.example/article',observed_at:'2026-11-16T00:00:00.000Z',
  platform:'generic',content_type:'unknown',identifiers:[],candidates:[],diagnostics:[]};
test('snapshot replies stay with the original request across navigation and later destruction',async t=>{
  const f=fixture(t),pending=f.runtime.call(f.doc,'extract',{wantAbstract:true});
  f.changed();
  f.reply({metadata:{dates:[],abstract:'Captured text.'},diagnostics:[],clues},{sender:{}});
  f.reply({metadata:{dates:[],abstract:'Captured text.'},diagnostics:[],clues},
    {url:'https://journal.example/article#current',documentId:'9-8-7-6'});
  f.contents.emit('destroyed');
  assert.equal((await pending).metadata.abstract,'Captured text.');
  assert.equal(f.runtime.pending.size,0);
});
test('fixed extraction forwards only boolean qualification and accepts legal empty metadata',async t=>{
  const f=fixture(t);
  await assert.rejects(f.runtime.call(f.doc,'extract',{wantAbstract:'false'}),/document_operation_failed/);
  await assert.rejects(f.runtime.call(f.doc,'extract',{wantAbstract:false,code:'arbitrary'}),/document_operation_failed/);
  assert.equal(f.messages.length,0);
  const pending=f.runtime.call(f.doc,'extract',{wantAbstract:false});
  assert.deepEqual(JSON.parse(JSON.stringify(f.messages.at(-1).args)),{wantAbstract:false});
  f.reply({metadata:{dates:[],abstract:null},diagnostics:[],clues});
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)),{metadata:{dates:[],abstract:null},diagnostics:[],clues});
});
test('malformed metadata cannot discard independent PDF clues; unwanted abstract is refused',async t=>{
  for(const metadata of [
    {dates:[{value:'2020-02-30',precision:'day'}],abstract:null},
    {dates:[{value:'2020-02',precision:'day'}],abstract:null},
    {dates:[{value:'2020-02',precision:'month'},{value:'2020-02-02',precision:'day'}],abstract:null},
    {dates:[{value:'2020-03',precision:'month'},{value:'2020-02',precision:'month'}],abstract:null},
    {dates:[{value:'2020-02',precision:'month',source:'page'}],abstract:null},
    {dates:[],abstract:'x'.repeat(65537)},
    {dates:[],abstract:'must remain null'},
  ]) {
    const f=fixture(t),pending=f.runtime.call(f.doc,'extract',{wantAbstract:false});
    f.reply({metadata,diagnostics:[],clues});
    if(metadata.abstract==='must remain null')await assert.rejects(pending,/page_probe_unconfirmed/);
    else {const result=await pending;assert.equal(result.metadata,null);assert.equal(result.clues.status,'complete');}
    assert.equal(f.runtime.pending.size,0);
  }
});

test('snapshot requests still fail on cancellation, closure or renderer exit before a reply',async t=>{
  for(const reason of ['destroyed','render-process-gone','cancel']) {
    const f=fixture(t),controller=new AbortController();
    const pending=f.runtime.call(f.doc,'pdf',{readerKind:null},{signal:controller.signal});
    if(reason==='cancel')controller.abort();else f.contents.emit(reason);
    await assert.rejects(pending,/page_closed|canceled/);
    assert.equal(f.runtime.pending.size,0);
  }
});
test('old and duplicate snapshot replies cannot settle another request',async t=>{
  const f=fixture(t),first=f.runtime.call(f.doc,'pdf',{readerKind:null}),id=f.messages.at(-1).id;
  f.reply({clues});await first;
  const second=f.runtime.call(f.doc,'pdf',{readerKind:null});
  const stale={clues:{...clues,landing_url:'https://journal.example/old'}};
  f.reply(stale,{id});f.reply(stale,{processId:99});f.reply(stale,{frameToken:'another-frame'});
  assert.equal(f.runtime.pending.size,1);
  f.reply({clues});assert.equal((await second).clues.landing_url,clues.landing_url);
});
