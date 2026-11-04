'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {installBrowserIPC}=require('../src/browser/browser-ipc.cjs');
test('Browser commands and presentation trust only the main Allfold document',async()=>{
  const handlers=new Map(),contents={mainFrame:{url:'http://127.0.0.1:18767/'}},host={webContents:contents};
  const calls=[],browser={show:()=>calls.push('show'),state:()=>({tabs:[]}),
    command:value=>calls.push(value),setPresentation:value=>calls.push(value)};
  const dispose=installBrowserIPC({ipcMain:{handle:(name,fn)=>handlers.set(name,fn),removeHandler:name=>handlers.delete(name)},
    hostWindow:host,origin:'http://127.0.0.1:18767',browser});
  const event={sender:contents,senderFrame:contents.mainFrame};
  handlers.get('browser:command')(event,{action:'new'});
  assert.deepEqual(calls,[{action:'new'}]);
  for(const bad of [
    {sender:{mainFrame:contents.mainFrame},senderFrame:contents.mainFrame},
    {sender:contents,senderFrame:{url:contents.mainFrame.url}},
    {sender:contents,senderFrame:{url:'https://remote.test/'}},
  ])for(const handler of handlers.values())assert.throws(()=>handler(bad,{}),/Untrusted/);
  for(const url of ['http://127.0.0.1:18767/static/ui_next/index.html','https://remote.test/','about:blank']){
    contents.mainFrame.url=url;
    for(const handler of handlers.values())assert.throws(()=>handler(event,{}),/Untrusted/);
  }
  dispose();assert.equal(handlers.size,0);
});
