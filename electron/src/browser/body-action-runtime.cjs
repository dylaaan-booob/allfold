'use strict';
// Separate mutation authority: DocumentRuntime's probes remain read-only.
const {ipcMain}=require('electron');
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('./browser-errors.cjs');
const {waitFor}=require('./browser-task.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const doiCasefold=require('./doi-casefold.json');
class BodyActionRuntime {
  constructor(browser,{ipc=ipcMain}={}) {
    this.browser=browser;this.pending=new Map();this.ipc=ipc;
    this.result=(event,message)=>{
      const entry=this.pending.get(message?.id);
      if(!entry || event.sender!==entry.contents || event.senderFrame?.processId!==entry.doc.processId
        || event.senderFrame?.frameToken!==entry.doc.frameToken)return;
      if(message.error){entry.reject(new BrowserFailure('navigation','document_operation_failed'));return;}
      const plan=message.plan;
      if(!this.browser.documentCurrent(entry.doc) || !plan || Object.keys(plan).sort().join(',')!=='method,request_url,target,target_name,url'
        || !['GET','POST'].includes(plan.method) || plan.url!==entry.candidate.url
        || !publicClueURL(plan.request_url)
        || !['self','frame','popup'].includes(plan.target) || typeof plan.target_name!=='string' || plan.target_name.length>256) {
        entry.reject(new BrowserFailure('navigation','document_changed'));return;
      }
      const action=new URL(plan.url),request=new URL(plan.request_url);
      if(plan.request_url!==plan.url && (entry.candidate.action!=='refresh_form' || plan.method!=='GET'
        || request.origin!==action.origin || request.pathname!==action.pathname || request.hash!==action.hash)) {
        entry.reject(new BrowserFailure('navigation','document_changed'));return;
      }
      entry.resolve({...plan,id:message.id});
    };
    this.actionError=(event,message)=>{
      const entry=this.pending.get(message?.id);
      if(entry?.onError&&event.sender===entry.contents&&event.senderFrame?.processId===entry.doc.processId
        &&event.senderFrame?.frameToken===entry.doc.frameToken)entry.onError(new BrowserFailure('navigation','document_changed'));
    };
    this.dispatching=(event,message)=>{
      let allowed=false;
      const entry=this.pending.get(message?.id);
      if(!entry || !entry.beforeDispatch || event.sender!==entry.contents
        || event.senderFrame?.processId!==entry.doc.processId || event.senderFrame?.frameToken!==entry.doc.frameToken
        || !this.browser.documentCurrent(entry.doc)){event.returnValue=false;return;}
      try {entry.beforeDispatch();entry.beforeDispatch=null;allowed=true;entry.resolve();}catch(error){entry.reject(error);}
      event.returnValue=allowed;
    };
    ipc.on('body:prepared',this.result);ipc.on('body:dispatching',this.dispatching);ipc.on('body:action-error',this.actionError);
  }
  async prepare(doc,candidate,{signal,deadline}={}) {
    const frame=this.browser.documentFrame(doc);
    if(!frame)throw new BrowserFailure('navigation','document_changed');
    const id=randomBytes(24).toString('hex'),contents=this.browser.tabs.get(doc.pageId).view.webContents;
    let entry;
    const response=new Promise((resolve,reject)=>{entry={doc,candidate,contents,resolve,reject};this.pending.set(id,entry);});
    try {
      const doi=validDOI(doc.identity?.doi) || doc.article?.values?.map(validDOI).find(Boolean) || null;
      const plan=await waitFor(()=>{frame.send('body:prepare',{id,candidate,documentId:doc.documentId,url:doc.url,
        subject:doc.article.subject,doi,doiCasefold});return response;},signal,Math.min(deadline,Date.now()+15000));
      // Resolve only the controlled action's named destination, never grant the
      // current frame inventory native output authority.
      const matches=plan.target==='frame'?contents.mainFrame.framesInSubtree.filter(item=>item.name===plan.target_name):[];
      if(matches.length>1)throw new BrowserFailure('navigation','document_changed');
      const foreignTarget=()=>plan.target==='frame'&&[...this.browser.tabs.values()].some(tab=>tab.id!==doc.pageId
        &&!tab.view.webContents.isDestroyed()&&tab.view.webContents.mainFrame.framesInSubtree.some(frame=>frame.name===plan.target_name));
      if(foreignTarget())throw new BrowserFailure('navigation','document_changed');
      // No match can be the fixed action's not-yet-created named destination.
      const targetFrame=matches[0];
      return {plan,targetFrame,dispatch:(beforeDispatch,onError)=>this.dispatch(entry,id,()=>{
        if(foreignTarget())throw new BrowserFailure('navigation','document_changed');
        if(targetFrame&&!contents.mainFrame.framesInSubtree.some(item=>item.processId===targetFrame.processId
          &&item.frameToken===targetFrame.frameToken&&item.name===plan.target_name))throw new BrowserFailure('navigation','document_changed');
        beforeDispatch();
      },onError,{signal,deadline}),
        dispose:()=>this.pending.delete(id)};
    } catch(error){this.pending.delete(id);throw error;}
  }
  async dispatch(entry,id,beforeDispatch,onError,{signal,deadline}) {
    const frame=this.browser.documentFrame(entry.doc);
    if(!frame) {this.pending.delete(id);throw new BrowserFailure('navigation','document_changed');}
    const response=new Promise((resolve,reject)=>Object.assign(entry,{resolve,reject,beforeDispatch,onError}));
    try {await waitFor(()=>{frame.send('body:dispatch',{id});return response;},signal,Math.min(deadline,Date.now()+5000));}
    catch(error){this.pending.delete(id);throw error;}
  }
  dispose() {
    for(const entry of this.pending.values())entry.reject(new BrowserFailure('navigation','page_closed'));
    this.pending.clear();this.ipc.removeListener('body:prepared',this.result);this.ipc.removeListener('body:dispatching',this.dispatching);
    this.ipc.removeListener('body:action-error',this.actionError);
  }
}
module.exports={BodyActionRuntime};
