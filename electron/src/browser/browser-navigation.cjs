'use strict';
const {BrowserFailure,checkPage}=require('./browser-errors.cjs');
const {checkCanceled,timeoutFailure,pause,waitFor}=require('./browser-task.cjs');

function loadFailure(message) {
  const error=new BrowserFailure('navigation','load_failed');
  const netError=String(message || '').match(/\bERR_[A-Z0-9_]+\b/)?.[0];
  if(netError)error.diagnostic.net_error=netError;
  return error;
}

// One transient navigation chain per WebContents. Neither site names nor credential grants enter here.
class NavigationRecovery {
  constructor(tab,{options=()=>({}),changed=()=>{},report=()=>{}}={}) {
    this.tab=tab;this.contents=tab.view.webContents;this.options=options;this.changed=changed;this.report=report;
    this.generation=0;this.current=null;this.listeners=[];
    const on=(event,run)=>{this.contents.on(event,run);this.listeners.push([event,run]);};
    on('will-navigate',(event,url)=>{
      if(event.defaultPrevented)return;
      const nav=this.current,target=event.url ?? url;
      if(this.historyOptions){this.begin(this.historyOptions);this.historyOptions=null;}
      else if(!nav?.pendingStart && !(nav?.active && nav.started && !nav.loaded && nav.url===target))
        this.begin({...this.options(),resume:true});
    });
    on('did-navigate-in-page',()=>{this.historyOptions=null;});
    on('will-redirect',(event,url)=>{
      if(!event.defaultPrevented && this.current?.started && !this.current.pendingStart)this.current.url=url;
    });
    on('did-start-navigation',(event,url,inPlace,main)=>{
      if(!(event.isMainFrame ?? main) || (event.isSameDocument ?? inPlace))return;
      let nav=this.current;
      if(this.historyOptions){nav=this.begin(this.historyOptions);this.historyOptions=null;}
      const target=event.url ?? url;
      this.tab.status=null;
      // Keep observing the document after recovery ends; do not reopen recovery.
      if(nav?.automatic && !nav.active){nav.url=target;return;}
      if(!nav)nav=this.begin(this.options());
      else if(!nav.pendingStart && (!nav.active || nav.loaded || nav.url!==target))
        nav=this.begin({...this.options(),resume:true});
      if(!nav.active)return;
      nav.pendingStart=false;nav.started=true;nav.loaded=false;
      nav.url=event.url ?? url;
      if(nav.loadDeadline==null && (nav.automatic || Number.isFinite(nav.deadline)))nav.loadDeadline=Date.now()+85000;
    });
    on('did-navigate',(_event,url,status)=>{
      if(!this.matches(url))return;
      this.tab.status=status;
      if(Number.isInteger(status) && status>=100)this.tab.error=null;
      this.changed();
    });
    on('did-finish-load',()=>{
      const nav=this.current;
      if(!nav?.active || !nav.started || nav.pendingStart)return;
      // Retain the one-shot completion signal; the polling wait separately requires native idle.
      nav.loaded=true;
      if(!this.contents.isLoadingMainFrame())nav.loadDeadline=null;
      this.report('info','page_load_completed',{page_id:tab.id,generation:nav.generation,
        waiting:this.contents.isLoadingMainFrame()});
      if(!nav.automatic)this.finish();
      this.changed();
    });
    on('did-stop-loading',()=>{
      const nav=this.current;
      if(nav?.loaded && !nav.pendingStart && !this.contents.isLoadingMainFrame())nav.loadDeadline=null;
    });
    on('did-fail-load',(_event,code,description,url,main,processId,routingId)=>{
      if(!main || code===-3 || /^(?:net::)?ERR_ABORTED$/.test(description))return;
      const nav=this.current;
      const reason=!nav?.started || nav.pendingStart?'navigation_pending':
        !this.matches(url)?'url_mismatch':!this.matches(url,processId,routingId)?'stale_frame':'current';
      // Observation must not depend on whether the event can change the current navigation.
      this.report('warn','page_load_failed',{page_id:tab.id,code,generation:nav?.generation,reason});
      if(reason!=='current')return;
      this.tab.status=null;this.tab.error={kind:'load',code};
      if(this.allowed(nav) && nav.reloads<2) {
        nav.reloads++;nav.loaded=false;nav.pendingStart=true;
        this.report('info','page_load_recovery',{page_id:tab.id,code,generation:nav.generation,attempt:nav.reloads});
        try {this.contents.reload();}
        catch(error){return this.recordFailure(error,code,'reload_failed');}
        this.changed();
      } else this.recordFailure(loadFailure(description),code);
    });
    on('destroyed',()=>{
      if(this.current)this.current.failure=new BrowserFailure('navigation','page_closed');
      this.dispose();
    });
  }
  matches(url,processId,routingId) {
    const nav=this.current;
    if(!nav)return false;
    if(url && nav.url && url!==nav.url)return false;
    // A cross-site navigation may replace the frame captured at its start.
    const frame=this.contents.isDestroyed()?null:this.contents.mainFrame;
    if([processId,routingId,frame?.processId,frame?.routingId].every(id=>Number.isInteger(id) && id>=0))
      return processId===frame.processId && routingId===frame.routingId;
    return true;
  }
  recordFailure(error,code,reason) {
    const failure=error instanceof BrowserFailure?error:loadFailure(error?.message);
    code ??= Number.isInteger(error?.errno)?error.errno:failure.diagnostic.net_error || failure.diagnostic.code;
    if(reason)this.report('warn','page_load_failed',{page_id:this.tab.id,code,generation:this.current?.generation,reason});
    if(this.current){this.current.failure ||= failure;this.finish();}
    this.tab.status=null;this.tab.error={kind:'load',code};this.changed();
    return failure;
  }
  allowed(nav) {
    return this.current===nav && nav.active && nav.enabled && !nav.signal?.aborted
      && Date.now()<nav.deadline && (nav.loadDeadline==null || Date.now()<nav.loadDeadline)
      && !this.contents.isDestroyed();
  }
  begin({automatic=false,owner=null,signal,deadline=Infinity,enabled=true,resume=false}={}) {
    const previous=this.current;
    // An explicit refresh may renew attempts, never an existing owner's time limits.
    const sameOwner=owner && previous?.owner===owner;
    this.finish();
    const nav=this.current={generation:++this.generation,chain:resume && previous?previous.chain:{},reloads:0,automatic,owner,signal,enabled,
      deadline:sameOwner?Math.min(deadline,previous.deadline):deadline,
      loadDeadline:sameOwner?previous.loadDeadline:null,active:true,pendingStart:true,started:false,
      loaded:false,failure:null,url:null};
    this.report('info','page_load_started',{page_id:this.tab.id,generation:nav.generation});
    const abort=()=>{if(this.current===nav && nav.active){nav.failure=signal.reason instanceof BrowserFailure?signal.reason:new BrowserFailure('navigation','canceled');this.finish();}};
    nav.detach=()=>signal?.removeEventListener('abort',abort);
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
    return nav;
  }
  adopt(options) {
    const nav=this.current;
    if(!nav)return this.begin(options);
    nav.detach?.();
    const {owner,signal,deadline=Infinity,enabled=true}=options;
    const sameOwner=nav.owner===owner;
    nav.automatic=true;nav.owner=owner;nav.signal=signal;nav.enabled=enabled;
    nav.deadline=sameOwner?Math.min(nav.deadline,deadline):deadline;
    nav.active=!nav.failure;
    if(!nav.loaded && nav.loadDeadline==null)nav.loadDeadline=Date.now()+85000;
    const abort=()=>{if(this.current===nav && nav.active){nav.failure=signal.reason instanceof BrowserFailure?signal.reason:new BrowserFailure('navigation','canceled');this.finish();}};
    nav.detach=()=>signal?.removeEventListener('abort',abort);
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
    return nav;
  }
  check(owner) {
    const nav=this.current;
    if(owner && nav?.owner!==owner)throw new BrowserFailure('navigation','document_changed');
    if(nav?.failure)throw nav.failure;
    if(nav?.active)checkCanceled(nav.signal);
    if(nav?.active && nav.automatic && Date.now()>=nav.deadline)throw timeoutFailure('navigation','request');
    if(nav?.active && nav.loadDeadline!=null && (!nav.loaded || this.contents.isLoadingMainFrame())
      && Date.now()>=nav.loadDeadline)
      throw timeoutFailure('navigation','page_load');
  }
  track(run) {
    const nav=this.current;
    try {
      const dispatched=run();
      // reload() returns void: dispatching it is not a document-completion signal.
      if(!dispatched || typeof dispatched.then!=='function')return;
      Promise.resolve(dispatched).then(()=>{
        if(this.current===nav && nav.active && !nav.failure && nav.reloads===0) {
          nav.loaded=true;nav.pendingStart=false;
          if(!this.contents.isLoadingMainFrame())nav.loadDeadline=null;
          if(!nav.automatic)this.finish();
        }
      },error=>{
        if(this.current===nav && nav.reloads===0 && !nav.failure && !/ERR_ABORTED/.test(error?.message || '')) {
          this.recordFailure(error,undefined,'load_promise_rejected');
        }
      });
    } catch(error){throw this.current===nav?this.recordFailure(error,undefined,'native_call_failed'):error;}
  }
  history(run,options) {this.historyOptions=options;run();}
  async dispatch(run,options) {
    const nav=this.begin(options),owner=nav.owner;
    if(nav.loadDeadline==null && (nav.automatic || Number.isFinite(nav.deadline)))nav.loadDeadline=Date.now()+85000;
    try {
      this.track(run);
      while(true) {
        this.check(owner);
        if(this.current?.chain!==nav.chain)throw new BrowserFailure('navigation','document_changed');
        const current=this.current;
        if(current.loaded && !this.contents.isLoadingMainFrame())return current;
        await waitFor(()=>pause(current.signal,100),current.signal,current.deadline);
      }
    } catch(error) {
      if(this.current?.chain===nav.chain)this.finish();
      throw error;
    }
  }
  finish() {
    if(this.current){this.current.active=false;this.current.detach?.();}
  }
  dispose() {
    this.finish();
    for(const [event,run] of this.listeners)this.contents.removeListener(event,run);
    this.listeners=[];
  }
}

// One observation shared by all task waits; business controls stay with their workflows.
async function inspectPage({snapshot,current,authentication,inspectAuthentication,solveCloudflare,solverDocuments,
  signal,deadline=Infinity,automaticDeadline=deadline,stage='navigation',step='verification',extraWaiting=()=>false,onWaiting=()=>{},onSolverFailure=()=>{}}) {
  const call=(run,limit=automaticDeadline)=>waitFor(run,signal,limit,stage,step);
  const authWaiting=await call(authentication);
  const auth=await call(inspectAuthentication,authWaiting?deadline:automaticDeadline);
  const doc=await call(snapshot,authWaiting || auth.waiting?deadline:automaticDeadline);
  if(!current(doc) || (auth.binding && (auth.binding.processId!==doc.processId || auth.binding.frameToken!==doc.frameToken)))
    return {doc,loading:true,waiting:false};
  const waiting=authWaiting || auth.waiting || extraWaiting(doc);
  try {
    checkPage(doc.status,doc.title,doc.html);
  } catch(error) {
    if(error.diagnostic?.code!=='verification_page') {
      if(!authWaiting && !auth.waiting)throw error;
    } else {
      const key=JSON.stringify([doc.pageId,doc.processId,doc.frameToken]);
      const attempt=solveCloudflare?solverDocuments.get(key):null;
      if(solveCloudflare && (!attempt || attempt.attempts<2 && attempt.retryable)) {
        onWaiting(true);
        const state={attempts:(attempt?.attempts || 0)+1,retryable:false};
        solverDocuments.set(key,state);
        let result;
        try {result=await call(()=>solveCloudflare(doc,{signal,deadline}),deadline);}
        catch(error){checkCanceled(signal);if(error.diagnostic?.code==='timeout')throw error;onSolverFailure();}
        checkCanceled(signal);
        if(!current(doc))return {doc,loading:true,waiting:false,recheck:true};
        state.retryable=state.attempts===1 && result?.outcome==='not_found';
        return {doc,waiting:true,recheck:true};
      }
      return {doc,waiting:true};
    }
  }
  return {doc,waiting:!!waiting || !Number.isInteger(doc.status)};
}
async function waitForPage(observe,{signal,deadline=Infinity,onWaiting,stage='navigation',step='verification'}={}) {
  while(true) {
    checkCanceled(signal);
    const result=await observe();
    if(!result.loading && !result.waiting && result.doc.status>=200 && result.doc.status<300) {
      onWaiting?.(false);return result.doc;
    }
    if(!result.loading && !result.waiting && Number.isInteger(result.doc.status))
      throw new BrowserFailure('navigation','http_error',result.doc.status);
    if(result.waiting)onWaiting?.(true);
    if(!result.recheck)await waitFor(()=>pause(signal),signal,deadline,stage,step);
  }
}
module.exports={NavigationRecovery,inspectPage,waitForPage};
