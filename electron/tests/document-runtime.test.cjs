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
  const reply=(result,{sender=contents,processId=2,frameToken='frame',documentId='1-2-3-4',url=doc.url}={})=>{
    ipc.emit('document:result',{sender,senderFrame:{processId,frameToken}},
      {id:messages.at(-1).id,result,documentId,url});
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
test('unbounded evidence, replaced URLs and unsupported operations fail closed',async t=>{
  const f=fixture(t);
  const pending=f.runtime.call(f.doc,'article');
  f.reply({article:{values:Array(33).fill('10.5555/target'),limited:false,multiple:false,article:true}});
  await assert.rejects(pending,/page_probe_unconfirmed/);
  const replaced=f.runtime.call(f.doc,'binding');f.reply({type:'text/html'},{url:'https://fixture.invalid/replaced'});
  await assert.rejects(replaced,/document_changed/);
  await assert.rejects(f.runtime.call(f.doc,'execute',{code:'arbitrary'}),/document_operation_failed/);
  assert.equal(f.messages.length,2);
});
test('fixed extraction forwards only boolean qualification and accepts legal empty metadata',async t=>{
  const f=fixture(t);
  await assert.rejects(f.runtime.call(f.doc,'extract',{wantAbstract:'false'}),/document_operation_failed/);
  await assert.rejects(f.runtime.call(f.doc,'extract',{wantAbstract:false,code:'arbitrary'}),/document_operation_failed/);
  assert.equal(f.messages.length,0);
  const pending=f.runtime.call(f.doc,'extract',{wantAbstract:false});
  assert.deepEqual(JSON.parse(JSON.stringify(f.messages.at(-1).args)),{wantAbstract:false});
  f.reply({metadata:{dates:[],abstract:null},diagnostics:[],subject:'1:2:3'});
  assert.deepEqual(JSON.parse(JSON.stringify(await pending)),{metadata:{dates:[],abstract:null},diagnostics:[],subject:'1:2:3',documentId:'1-2-3-4'});
});
test('extraction refuses malformed calendar, precision, ordering, size and unwanted abstract',async t=>{
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
    f.reply({metadata,diagnostics:[],subject:'1:2:3'});
    await assert.rejects(pending,/page_probe_unconfirmed/);assert.equal(f.runtime.pending.size,0);
  }
});
