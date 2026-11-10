'use strict';
const {BrowserFailure,checkPage}=require('./browser-errors.cjs');
const {checkCanceled,timeoutFailure,pause,waitFor,PAGE_LOAD_MS}=require('./browser-task.cjs');

const {REFRESH_LIMIT,REFRESH_DELAY_MS,loadFailure,transientLoad,reportRecovery,recoveryStop,
  pageRecoveryDetails,origin}=require('./browser-recovery.cjs');

function nativeFrame(event,processId,routingId) {
  processId=event.frame?.processId ?? processId;
  routingId=event.frame?.routingId ?? routingId;
  return [processId,routingId].every(id=>Number.isInteger(id) && id>=0)?{processId,routingId}:null;
}

// One transient navigation chain per WebContents. Neither site names nor credential grants enter here.
class NavigationRecovery {
  constructor(tab,{options=()=>({}),changed=()=>{},report=()=>{},now=Date.now,random=Math.random,pause:wait=pause}={}) {
    this.tab=tab;this.contents=tab.view.webContents;this.options=options;this.changed=changed;this.report=report;
    this.now=now;this.random=random;this.pause=wait;
    this.generation=0;this.current=null;this.listeners=[];
    const on=(event,run)=>{this.contents.on(event,run);this.listeners.push([event,run]);};
    on('will-navigate',(event,url)=>{
      if(event.defaultPrevented)return;
      const nav=this.current,target=event.url ?? url;
      if(this.historyOptions){this.begin(this.historyOptions);this.historyOptions=null;}
      else if(!nav?.pendingStart && !(nav?.active && nav.started && !nav.loaded && !nav.refresh && nav.url===target))
        this.begin({...this.options(),resume:true,replayable:false});
    });
    on('did-navigate-in-page',()=>{this.historyOptions=null;});
    const redirect=(event,url,inPlace,main,processId,routingId)=>{
      const nav=this.current;
      if(!event.defaultPrevented && (event.isMainFrame ?? main) && !(event.isSameDocument ?? inPlace)
        && nav?.started && !nav.pendingStart) {
        nav.url=event.url ?? url;
        nav.frame=nativeFrame(event,processId,routingId) || nav.frame;
      }
    };
    on('will-redirect',redirect);
    on('did-redirect-navigation',redirect);
    on('did-start-navigation',(event,url,inPlace,main,processId,routingId)=>{
      if(!(event.isMainFrame ?? main) || (event.isSameDocument ?? inPlace))return;
      let nav=this.current;
      if(this.historyOptions){nav=this.begin(this.historyOptions);this.historyOptions=null;}
      const target=event.url ?? url;
      this.tab.status=null;
      // Keep observing the document after recovery ends; do not reopen recovery.
      if(nav?.automatic && !nav.active){nav.url=target;return;}
      if(!nav)nav=this.begin(this.options());
      else if(!nav.pendingStart && (!nav.active || nav.loaded || nav.refresh || nav.url!==target))
        nav=this.begin({...this.options(),resume:true,replayable:false});
      if(!nav.active)return;
      nav.pendingStart=false;nav.started=true;nav.loaded=false;
      nav.url=event.url ?? url;
      nav.frame=nativeFrame(event,processId,routingId);
      if(nav.loadDeadline==null && (nav.automatic || Number.isFinite(nav.deadline)))nav.loadDeadline=this.now()+PAGE_LOAD_MS;
    });
    on('did-navigate',(_event,url,status)=>{
      if(!this.matches(url))return;
      this.tab.status=status;
      this.current.committed=true;
      if(Number.isInteger(status) && status>=100)this.tab.error=null;
      this.changed();
    });
    on('did-finish-load',()=>{
      const nav=this.current;
      if(!nav?.active || !nav.started || nav.pendingStart || nav.refresh || !nav.committed || !this.matches(this.contents.getURL()))return;
      // Retain the one-shot completion signal; the polling wait separately requires native idle.
      nav.loaded=true;
      if(!this.contents.isLoadingMainFrame())this.complete(nav);
      this.report('info','page_load_completed',{page_id:tab.id,generation:nav.generation,
        waiting:this.contents.isLoadingMainFrame()});
      if(!nav.automatic)this.finish();
      this.changed();
    });
    on('did-stop-loading',()=>{
      const nav=this.current;
      if(nav?.loaded && !nav.pendingStart && !this.contents.isLoadingMainFrame())this.complete(nav);
    });
    on('did-fail-load',(_event,code,description,url,main,processId,routingId)=>{
      if(!main || code===-3 || /^(?:net::)?ERR_ABORTED$/.test(description))return;
      const nav=this.current;
      const reason=!nav?.started || !nav.active || nav.pendingStart || nav.loaded || nav.refresh?'navigation_pending':
        !this.matches(url)?'url_mismatch':!this.matches(url,processId,routingId)?'stale_frame':'current';
      // Observation must not depend on whether the event can change the current navigation.
      const failure=loadFailure(description,code);
      this.report('warn','page_load_failed',{page_id:tab.id,...failure.diagnostic,generation:nav?.generation,reason});
      // This event cannot identify its request, including across same-URL refreshes.
      // Managed failures use a Chromium request ID or the exact loadURL promise.
      if(reason!=='current' || nav.automatic)return;
      this.handleFailure(nav,failure);
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
    const frame=this.contents.isDestroyed()?null:(!nav.committed && nav.frame) || this.contents.mainFrame;
    if([processId,routingId,frame?.processId,frame?.routingId].every(id=>Number.isInteger(id) && id>=0))
      return processId===frame.processId && routingId===frame.routingId;
    return true;
  }
  recoveryEvent(nav,event,error,extra={}) {
    reportRecovery(nav.recoveryReport,event,pageRecoveryDetails(error,'page_refresh',{
      stage:'navigation',page_id:this.tab.id,attempt:nav.reloads,attempt_limit:REFRESH_LIMIT,
      dispatch_outcome:event==='recovery_succeeded'?'confirmed':'unknown',...extra,
    }));
  }
  complete(nav) {
    if(nav.loadDeadline!=null && this.now()>=nav.loadDeadline) {
      this.recordFailure(this.now()>=nav.deadline?timeoutFailure('navigation','request'):this.pageLoadTimeout(nav));
      return;
    }
    nav.loadDeadline=null;
    if(!nav.chain.lastFailure)return;
    if(this.tab.status>=400)
      this.recoveryEvent(nav,'recovery_exhausted',new BrowserFailure('navigation','http_error',this.tab.status),{recovery_stop:'failed'});
    else this.recoveryEvent(nav,'recovery_succeeded',nav.chain.lastFailure);
    nav.chain.lastFailure=null;
  }
  recordFailure(error,reason,stop,{updateState=true}={}) {
    const nav=this.current;
    const failure=error instanceof BrowserFailure?error:loadFailure(error?.message,error?.errno);
    const code=failure.diagnostic.net_code ?? failure.diagnostic.net_error ?? failure.diagnostic.code;
    if(reason)this.report('warn','page_load_failed',{page_id:this.tab.id,...failure.diagnostic,generation:nav?.generation,reason});
    if(nav) {
      nav.failure ||= failure;
      if(nav.chain.lastFailure) {
        this.recoveryEvent(nav,'recovery_exhausted',failure,{recovery_stop:stop || recoveryStop(failure,nav.signal)});
        nav.chain.lastFailure=null;
      }
      this.finish();
    }
    if(updateState){this.tab.status=null;this.tab.error={kind:'load',code};this.changed();}
    return failure;
  }
  allowed(nav) {
    return this.current===nav && nav.active && nav.automatic && nav.enabled && nav.replayable && !nav.signal?.aborted
      && !nav.chain.unsafeRequest && nav.valid() && !this.contents.isDestroyed();
  }
  handleFailure(nav,failure) {
    nav.loaded=false;nav.dispatchToken=null;
    this.tab.status=null;this.tab.error={kind:'load',code:failure.diagnostic.net_code ?? failure.diagnostic.code};
    const transient=transientLoad(failure) && !!origin(nav.url);
    if(!transient || !this.allowed(nav))return this.recordFailure(failure);
    if(nav.reloads>=REFRESH_LIMIT) {
      failure.rebuildPage=true;
      return this.recordFailure(failure,undefined,'limit');
    }
    const limit=Math.min(nav.deadline,nav.loadDeadline ?? Infinity);
    const wait=Math.round(REFRESH_DELAY_MS*2**nav.reloads*(0.75+this.random()*0.5));
    nav.chain.reloads++;
    nav.chain.lastFailure=failure;
    this.recoveryEvent(nav,'recovery_scheduled',failure,{wait_ms:wait,dispatch_outcome:'not_dispatched'});
    const controller=nav.refresh=new AbortController();
    const signal=AbortSignal.any([controller.signal,...(nav.signal?[nav.signal]:[])]);
    const check=()=>{
      checkCanceled(signal);
      if(this.current!==nav || !this.allowed(nav))throw new BrowserFailure('navigation','document_changed');
      if(this.now()>=nav.deadline)throw timeoutFailure('navigation','request');
      if(this.now()>=limit)throw this.pageLoadTimeout(nav);
    };
    this.changed();
    void (async()=>{
      try {
        if(this.now()+wait>=limit)
          throw limit===nav.deadline?timeoutFailure('navigation','request'):this.pageLoadTimeout(nav);
        await this.pause(signal,wait);
        check();
        await nav.beforeRefresh?.(nav.url,{signal,deadline:limit,validate:check});
        check();
        nav.refresh=null;
        nav.generation=++this.generation;
        nav.requestId=undefined;
        nav.pendingStart=true;nav.started=false;nav.committed=false;
        // A provisional cross-site failure can leave the previous document committed.
        const url=nav.url;
        this.track(()=>this.contents.getURL()===url?this.contents.reload():this.contents.loadURL(url));
      }catch(error) {
        if(this.current===nav && nav.active)
          this.recordFailure(error,undefined,recoveryStop(error,signal));
      }
    })();
  }
  pageLoadTimeout(nav) {
    const failure=timeoutFailure('navigation','page_load');
    failure.rebuildPage=this.allowed(nav);
    return failure;
  }
  loadingRequest(nav,url) {
    return nav?.active && nav.started && !nav.pendingStart && !nav.loaded && !nav.refresh
      && nav.url?.split('#')[0]===url;
  }
  observeRequestStart({id,url,method}) {
    const nav=this.current;
    if(!nav?.automatic || !Number.isSafeInteger(id) || !this.loadingRequest(nav,url))return;
    if(nav.requestId!==id) {
      if(nav.requestId!==undefined || nav.chain.requestIds.has(id))return;
      nav.requestId=id;
      nav.chain.requestIds.add(id);
    }
    if(method!=='GET') {
      nav.chain.unsafeRequest=true;
      this.blockReplay();
    } else if(nav.chain.replayFollowingGets) {
      // A subsequent document can recover only after observing its main-frame GET.
      nav.replayable=true;
    }
  }
  observeRequestFailure({id,url,error}) {
    const nav=this.current;
    if(!Number.isSafeInteger(id) || nav?.requestId!==id || !this.loadingRequest(nav,url)
      || /^(?:net::)?ERR_ABORTED$/.test(error))return;
    const failure=loadFailure(error);
    this.report('warn','page_load_failed',{page_id:this.tab.id,...failure.diagnostic,
      generation:nav.generation,reason:'current'});
    this.handleFailure(nav,failure);
  }
  blockReplay() {
    const nav=this.current;
    if(!nav)return;
    nav.replayable=false;
    nav.chain.replayFollowingGets=false;
  }
  begin({automatic=false,owner=null,signal,deadline=Infinity,enabled=true,resume=false,replayable=false,valid=()=>true,
    beforeRefresh,recoveryReport,initialURL=null,replayFollowingGets=false}={}) {
    const previous=this.current;
    const sameOwner=owner && previous?.owner===owner;
    this.finish({preserve:resume});
    const chain=resume && previous?.owner===owner?previous.chain:{reloads:0,lastFailure:null,requestIds:new Set(),replayFollowingGets};
    const nav=this.current={generation:++this.generation,chain,get reloads(){return chain.reloads;},automatic,owner,signal,enabled,
      replayable,valid,beforeRefresh,recoveryReport,deadline:sameOwner?Math.min(deadline,previous.deadline):deadline,
      loadDeadline:sameOwner && resume?previous.loadDeadline:null,active:true,pendingStart:true,started:false,
      loaded:false,failure:null,url:initialURL};
    this.report('info','page_load_started',{page_id:this.tab.id,generation:nav.generation});
    this.watchSignal(nav);
    return nav;
  }
  watchSignal(nav) {
    const {signal}=nav;
    const abort=()=>{
      if(this.current===nav && nav.active)
        this.recordFailure(signal.reason instanceof BrowserFailure?signal.reason:new BrowserFailure('navigation','canceled'),
          undefined,undefined,{updateState:false});
    };
    nav.detach=()=>signal?.removeEventListener('abort',abort);
    signal?.addEventListener('abort',abort,{once:true});
    if(signal?.aborted)abort();
  }
  adopt(options) {
    const nav=this.current;
    if(!nav)return this.begin(options);
    nav.detach?.();
    const {owner,signal,deadline=Infinity,enabled=true,valid,beforeRefresh,recoveryReport}=options;
    const sameOwner=nav.owner===owner;
    nav.automatic=true;nav.owner=owner;nav.signal=signal;nav.enabled=enabled;
    if(options.replayable!==undefined)nav.replayable=options.replayable;
    if(options.replayFollowingGets)nav.chain.replayFollowingGets=true;
    nav.valid=valid;nav.beforeRefresh=beforeRefresh;nav.recoveryReport=recoveryReport;
    nav.deadline=sameOwner?Math.min(nav.deadline,deadline):deadline;
    nav.active=!nav.failure;
    if(!nav.loaded && nav.loadDeadline==null)nav.loadDeadline=this.now()+PAGE_LOAD_MS;
    this.watchSignal(nav);
    return nav;
  }
  check(owner) {
    const nav=this.current;
    if(owner && nav?.owner!==owner)throw new BrowserFailure('navigation','document_changed');
    if(nav?.failure)throw nav.failure;
    if(!nav?.active)return;
    checkCanceled(nav.signal);
    if(nav.automatic && this.now()>=nav.deadline)throw this.recordFailure(timeoutFailure('navigation','request'));
    if(nav.loadDeadline!=null && (!nav.loaded || this.contents.isLoadingMainFrame()) && this.now()>=nav.loadDeadline)
      throw this.recordFailure(this.pageLoadTimeout(nav));
  }
  track(run) {
    const nav=this.current,token=nav.dispatchToken={};
    const current=()=>this.current===nav && nav.active && nav.dispatchToken===token && !nav.failure;
    try {
      const dispatched=run();
      // reload() returns void: dispatching it is not a document-completion signal.
      if(!dispatched || typeof dispatched.then!=='function')return;
      Promise.resolve(dispatched).then(()=>{
        if(current()) {
          nav.loaded=true;nav.pendingStart=false;
          if(!this.contents.isLoadingMainFrame())this.complete(nav);
          if(!nav.automatic)this.finish();
        }
      },error=>{
        if(current() && !/ERR_ABORTED/.test(error?.message || '')) {
          const failure=loadFailure(error?.message,error?.errno);
          this.report('warn','page_load_failed',{page_id:this.tab.id,...failure.diagnostic,
            generation:nav.generation,reason:'load_promise_rejected'});
          this.handleFailure(nav,failure);
        }
      });
    } catch(error){throw current()?this.recordFailure(error,'native_call_failed'):error;}
  }
  history(run,options) {this.historyOptions=options;run();}
  async dispatch(run,options) {
    const nav=this.begin(options),owner=nav.owner;
    if(nav.loadDeadline==null && (nav.automatic || Number.isFinite(nav.deadline)))nav.loadDeadline=this.now()+PAGE_LOAD_MS;
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
  finish({preserve=false}={}) {
    const nav=this.current;
    if(!nav)return;
    if(!preserve)nav.chain.replayFollowingGets=false;
    nav.active=false;nav.detach?.();nav.refresh?.abort();
    if(nav.chain.lastFailure && (!preserve || nav.refresh)) {
      this.recoveryEvent(nav,'recovery_exhausted',nav.chain.lastFailure,{
        recovery_stop:nav.signal?.aborted?'canceled':'authority'});
      nav.chain.lastFailure=null;
    }
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
      const hcaptcha=/<iframe\b[^>]*\ssrc\s*=\s*["'](?:https:)?\/\/(?:[a-z0-9-]+\.)*hcaptcha\.com(?:[/:]|["'])/i.test(doc.html);
      if(error.diagnostic.imperva_edet!==undefined || hcaptcha)return {doc,waiting:true,diagnostic:error.diagnostic};
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
    if(result.waiting)onWaiting?.(true,result.diagnostic);
    if(!result.recheck)await waitFor(()=>pause(signal),signal,deadline,stage,step);
  }
}
module.exports={NavigationRecovery,inspectPage,waitForPage};
