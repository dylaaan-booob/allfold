'use strict';
const {ipcMain}=require('electron');
const path=require('node:path');
const {PRELOAD_DIR}=require('../shared/paths.cjs');
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('./browser-errors.cjs');
const {waitFor}=require('./browser-task.cjs');
class DocumentRuntime {
  constructor(browser) {
    this.browser=browser;this.pending=new Map();
    this.preload=browser.partition.registerPreloadScript({type:'frame',filePath:path.join(PRELOAD_DIR,'document-preload.cjs')});
    this.listener=(event,message)=>{
      const entry=this.pending.get(message?.id);if(!entry)return;
      const frame=browser.documentFrame(entry.doc);
      if(!frame || event.sender!==browser.tabs.get(entry.doc.pageId)?.view.webContents
        || event.senderFrame?.processId!==entry.doc.processId || event.senderFrame?.frameToken!==entry.doc.frameToken)return;
      if(message.error)entry.reject(new BrowserFailure('translation','document_operation_failed'));
      else entry.resolve(message.result);
    };
    ipcMain.on('document:result',this.listener);
  }
  async call(doc,action,args={},options={}) {
    const frame=this.browser.documentFrame(doc);
    if(!frame)throw new BrowserFailure('translation','document_changed');
    const id=randomBytes(16).toString('hex'),contents=this.browser.tabs.get(doc.pageId).view.webContents;
    let reject;
    const response=new Promise((resolve,no)=>{reject=no;this.pending.set(id,{doc,resolve,reject:no});});
    const changed=()=>{if(!this.browser.documentCurrent(doc))reject(new BrowserFailure('translation','document_changed'));};
    const closed=()=>reject(new BrowserFailure('translation','page_closed'));
    contents.on('did-frame-navigate',changed);contents.once('destroyed',closed);contents.once('render-process-gone',closed);
    try {
      return await waitFor(()=>{frame.send('document:operation',{id,action,args});return response;},
        options.signal,action==='wait'?(options.deadline ?? Infinity):Math.min(options.deadline ?? Infinity,Date.now()+15000),'translation','document_operation');
    }finally {
      this.pending.delete(id);contents.removeListener('did-frame-navigate',changed);
      contents.removeListener('destroyed',closed);contents.removeListener('render-process-gone',closed);
    }
  }
  dispose() {
    for(const entry of this.pending.values())entry.reject(new BrowserFailure('translation','page_closed'));
    this.pending.clear();ipcMain.removeListener('document:result',this.listener);
    this.browser.partition.unregisterPreloadScript(this.preload);
  }
}
module.exports={DocumentRuntime};
