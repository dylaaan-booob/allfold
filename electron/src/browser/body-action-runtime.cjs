'use strict';
// Separate mutation authority: DocumentRuntime's probes remain read-only.
const {ipcMain}=require('electron');
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('./browser-errors.cjs');
const {waitFor}=require('./browser-task.cjs');
const {publicClueURL}=require('./pdf-clues.cjs');
const {validDOI}=require('./article-identity.cjs');
const doiCasefold=require('./doi-casefold.json');
// Native request ownership survives same-frame URL and DOM changes.
const sourceFrame=doc=>({pageId:doc.pageId,processId:doc.processId,frameToken:doc.frameToken});
class BodyActionRuntime {
  constructor(browser,{ipc=ipcMain}={}) {
    this.browser=browser;this.pending=new Map();this.ipc=ipc;
    this.result=(event,message)=>{
      const entry=this.pending.get(message?.id);
      if(!entry || entry.prepared || event.sender!==entry.contents || event.senderFrame?.processId!==entry.doc.processId
        || event.senderFrame?.frameToken!==entry.doc.frameToken)return;
      if(message.error){entry.reject(new BrowserFailure('navigation','body_action_unavailable'));return;}
      const plan=message.plan;
      if(!this.browser.documentFrame(sourceFrame(entry.doc)) || !plan || Object.keys(plan).sort().join(',')!=='method,request_url,target,target_name,url'
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
      entry.prepared=true;entry.resolve({...plan,id:message.id});
    };
    this.actionError=(event,message)=>{
      const entry=this.pending.get(message?.id);
      if(entry&&event.sender===entry.contents&&event.senderFrame?.processId===entry.doc.processId
        &&event.senderFrame?.frameToken===entry.doc.frameToken) {
        const error=new BrowserFailure('navigation','body_action_unavailable');entry.reject(error);entry.onError?.(error);
      }
    };
    this.dispatching=(event,message)=>{
      let allowed=false;
      const entry=this.pending.get(message?.id);
      if(!entry || !entry.beforeDispatch || event.sender!==entry.contents
        || event.senderFrame?.processId!==entry.doc.processId || event.senderFrame?.frameToken!==entry.doc.frameToken
        || !this.browser.documentFrame(sourceFrame(entry.doc))){event.returnValue=false;return;}
      try {
        const plan=message.plan,previous=entry.plan;
        if(!plan || Object.keys(plan).sort().join(',')!=='method,request_url,target,target_name,url'
          || ['url','method','target','target_name'].some(key=>plan[key]!==previous[key]) || !publicClueURL(plan.request_url))
          throw new BrowserFailure('navigation','body_action_unavailable');
        const request=new URL(plan.request_url),action=new URL(plan.url);
        if(plan.request_url!==plan.url && (entry.candidate.action!=='refresh_form'||plan.method!=='GET'
          || request.origin!==action.origin||request.pathname!==action.pathname||request.hash!==action.hash))
          throw new BrowserFailure('navigation','body_action_unavailable');
        entry.beforeDispatch(plan);entry.beforeDispatch=null;allowed=true;entry.resolve();
      }catch(error){entry.reject(error);}
      event.returnValue=allowed;
    };
    ipc.on('body:prepared',this.result);ipc.on('body:dispatching',this.dispatching);ipc.on('body:action-error',this.actionError);
  }
  async prepare(doc,candidate,{signal,deadline}={}) {
    const frame=this.browser.documentFrame(sourceFrame(doc));
    if(!frame)throw new BrowserFailure('navigation','document_changed');
    const id=randomBytes(24).toString('hex'),contents=this.browser.tabs.get(doc.pageId).view.webContents;
    let entry;
    const response=new Promise((resolve,reject)=>{entry={doc,candidate,contents,resolve,reject};this.pending.set(id,entry);});
    try {
      let path=new URL(doc.url).pathname;
      try {path=decodeURI(path);}catch { /* Preserve the literal path when escapes cannot be decoded. */ }
      const doi=validDOI(doc.identity?.doi) || validDOI(path.match(/\/doi\/(?:abs\/|full\/)?(10\.\d{4,9}\/[^\s]+)$/)?.[1]);
      const plan=await this.waitForReply(entry,'body:prepare',{id,candidate,doi,doiCasefold},frame,response,signal,deadline);
      entry.plan=plan;
      // Resolve only the controlled action's named destination, never grant the
      // current frame inventory native output authority.
      const matches=plan.target==='frame'?contents.mainFrame.framesInSubtree.filter(item=>item.name===plan.target_name):[];
      if(matches.length>1)throw new BrowserFailure('navigation','document_changed');
      const foreignTarget=()=>plan.target==='frame'&&[...this.browser.tabs.values()].some(tab=>tab.id!==doc.pageId
        &&!tab.view.webContents.isDestroyed()&&tab.view.webContents.mainFrame.framesInSubtree.some(frame=>frame.name===plan.target_name));
      if(foreignTarget())throw new BrowserFailure('navigation','document_changed');
      // No match can be the fixed action's not-yet-created named destination.
      const targetFrame=matches[0];
      return {plan,targetFrame,dispatch:(beforeDispatch,onError)=>this.dispatch(entry,id,currentPlan=>{
        if(foreignTarget())throw new BrowserFailure('navigation','document_changed');
        if(targetFrame&&!contents.mainFrame.framesInSubtree.some(item=>item.processId===targetFrame.processId
          &&item.frameToken===targetFrame.frameToken&&item.name===plan.target_name))throw new BrowserFailure('navigation','document_changed');
        beforeDispatch(currentPlan);
      },onError,{signal,deadline}),
        dispose:()=>this.pending.delete(id)};
    } catch(error){this.pending.delete(id);throw error;}
  }
  async dispatch(entry,id,beforeDispatch,onError,{signal,deadline}) {
    const frame=this.browser.documentFrame(sourceFrame(entry.doc));
    if(!frame) {this.pending.delete(id);throw new BrowserFailure('navigation','document_changed');}
    const response=new Promise((resolve,reject)=>Object.assign(entry,{resolve,reject,beforeDispatch,onError}));
    try {await this.waitForReply(entry,'body:dispatch',{id},frame,response,signal,deadline);}
    catch(error){this.pending.delete(id);throw error;}
  }
  async waitForReply(entry,channel,message,frame,response,signal,deadline) {
    const closed=()=>entry.reject(new BrowserFailure('navigation','page_closed'));
    entry.contents.once('destroyed',closed);entry.contents.once('render-process-gone',closed);
    try {return await waitFor(()=>{frame.send(channel,message);return response;},signal,deadline);}
    finally {entry.contents.removeListener('destroyed',closed);entry.contents.removeListener('render-process-gone',closed);}
  }
  dispose() {
    for(const entry of this.pending.values())entry.reject(new BrowserFailure('navigation','page_closed'));
    this.pending.clear();this.ipc.removeListener('body:prepared',this.result);this.ipc.removeListener('body:dispatching',this.dispatching);
    this.ipc.removeListener('body:action-error',this.actionError);
  }
}
module.exports={BodyActionRuntime};
