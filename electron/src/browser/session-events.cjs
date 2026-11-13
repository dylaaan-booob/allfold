'use strict';
const {BrowserCooldown}=require('./browser-recovery.cjs');
const {randomBytes}=require('node:crypto');
const {checkCanceled,timeoutFailure}=require('./browser-task.cjs');
const {BrowserFailure}=require('./browser-errors.cjs');

const sessions=new WeakMap();
const FILTER={urls:['<all_urls>']};
const MARKER='x-allfold-request-context';
const PRIVATE_HEADERS=new Set(['x-allfold-request-context','x-allfold-http-context']);
function withoutMarkers(headers={}) {
  return Object.fromEntries(Object.entries(headers).filter(([name])=>!PRIVATE_HEADERS.has(name.toLowerCase())));
}

// Electron has one listener slot per webRequest event. Only this Session lifetime
// installs native listeners; consumers receive synchronous, ordered scoped hooks.
class SharedSessionEvents {
  constructor(session,timing) {
    this.session=session;this.cooldown=new BrowserCooldown(timing);this.handlers=new Map();this.closed=false;
    this.requests=new Map();this.fetches=new Map();
    this.downloads=new Set();this.downloadGuards=new Map();this.items=new Set();this.taskPages=new Set();
    this.installed=[];
    for(const [native,event,callback] of [['onBeforeRequest','beforeRequest',true],
      ['onBeforeSendHeaders','beforeSendHeaders',true],['onHeadersReceived','headersReceived',true],
      ['onBeforeRedirect','beforeRedirect'],['onCompleted','completed'],['onErrorOccurred','errorOccurred']]) {
      if(typeof session.webRequest?.[native]!=='function')continue;
      session.webRequest[native](FILTER,(details,finish)=>this.dispatch(event,details,callback?finish:undefined));
      this.installed.push(native);
    }
    this.downloadListener=(event,item,contents,frame)=>this.routeDownload(event,item,contents,frame);
    session.on?.('will-download',this.downloadListener);
  }
  subscribe(event,handler,{signal}={}) {
    if(this.closed)throw Error('Browser Session is closed');
    const handlers=this.handlers.get(event) || new Set();this.handlers.set(event,handlers);
    const registration={handler,dispose:()=>{handlers.delete(registration);signal?.removeEventListener('abort',registration.dispose);}};
    if(!signal?.aborted){handlers.add(registration);signal?.addEventListener('abort',registration.dispose,{once:true});}
    return registration;
  }
  emit(event,details,state={}) {
    for(const registration of [...(this.handlers.get(event) || [])]) {
      try {
        const canceled=state.cancel===true;
        const result=registration.handler(details,state);
        // Asynchronous handlers cannot own Electron's callback or hold a request.
        if(result?.then){result.catch(()=>{});state.cancel=true;}
        else if(result)Object.assign(state,result);
        if(canceled)state.cancel=true;
      } catch(_){state.cancel=true;}
    }
    return state;
  }
  dispatch(event,details,finish) {
    let state={};
    try {
      const request=this.observe(event,details);
      if(event==='beforeSendHeaders')state.requestHeaders=withoutMarkers(details.requestHeaders);
      if(event==='headersReceived')state.responseHeaders=details.responseHeaders;
      if(event==='headersReceived')this.overrideInline(details,state);
      // Private association tokens never reach consumers, diagnostics or the wire.
      this.emit(event,event==='beforeSendHeaders'?{...details,requestHeaders:state.requestHeaders}:details,state);
      if(event==='beforeSendHeaders')state.requestHeaders=withoutMarkers(state.requestHeaders);
      request?.controlled?.validate();
    } catch(_){state={cancel:true};}
    finally {
      finish?.(state);
      if(event==='completed' || event==='errorOccurred')this.requests.delete(details.id);
    }
  }
  observe(event,details) {
    let request=this.requests.get(details.id);
    if(event==='beforeRequest' && !request) {
      request={id:details.id,method:details.method,url:details.url,webContentsId:details.webContentsId,
        frame:details.frame?{processId:details.frame.processId,frameToken:details.frame.frameToken}:null,
        redirects:[],responses:[]};
      this.requests.set(details.id,request);
    }
    if(event==='beforeSendHeaders') {
      const token=Object.entries(details.requestHeaders || {}).find(([key])=>key.toLowerCase()===MARKER)?.[1];
      const controlled=this.fetches.get(token);
      if(controlled && request && !request.controlled) {
        Object.defineProperty(request,'controlled',{value:controlled,configurable:true});request.identity=controlled.identity;
        controlled.requests.push(request);this.fetches.delete(token);
      }
    }
    if(event==='beforeRedirect' && request && request.redirects.length<32)
      request.redirects.push({url:details.url,redirectURL:details.redirectURL,statusCode:details.statusCode});
    if(event==='headersReceived') {
      if(request && request.responses.length<33)request.responses.push({url:details.url,statusCode:details.statusCode});
      const retryAfter=Object.entries(details.responseHeaders || {}).filter(([name])=>name.toLowerCase()==='retry-after').flatMap(([,values])=>values);
      if(details.resourceType==='mainFrame' || request?.identity)
        this.cooldown.observe(details.url,details.statusCode,retryAfter.length===1?retryAfter[0]:undefined);
    }
    if(request && (event==='completed' || event==='errorOccurred')){request.terminal=event;delete request.controlled;}
    return request;
  }
  associateRequest(id,identity) {
    const request=this.requests.get(id);
    if(request && !request.identity)request.identity=Object.freeze({...identity});
  }
  async fetch(url,options={},context={}) {
    const {owner,attemptId,document,deadline,validate=()=>{}}=context;
    if(!owner || !attemptId || !Number.isFinite(deadline))throw Error('Controlled request owner, attempt and deadline required');
    const sourceSignals=[context.signal,options.signal].filter(Boolean);
    const signal=sourceSignals.length?AbortSignal.any(sourceSignals):undefined;
    const check=()=>{if(this.closed)throw Error('Browser Session is closed');checkCanceled(signal);
      if(Date.now()>=deadline)throw timeoutFailure('navigation','request');validate();};
    check();await this.cooldown.wait(url,{signal,deadline,validate:check});check();
    const token=randomBytes(24).toString('hex'),requests=[];
    const identity=Object.freeze({...owner.association || owner,attempt_id:attemptId,
      page_id:document?.pageId,document_id:document?.documentId});
    const controlled={identity,requests,validate:check};this.fetches.set(token,controlled);
    const headers=new Headers(options.headers);headers.set(MARKER,token);
    // The deadline belongs to this physical request, including its response body.
    const bounded=Number.isFinite(deadline)?AbortSignal.timeout(Math.max(1,Math.ceil(deadline-Date.now()))):null;
    const signals=[signal,bounded].filter(Boolean);
    const requestSignal=signals.length?AbortSignal.any(signals):undefined;
    try {
      const response=await this.session.fetch(url,{...options,headers,signal:requestSignal});check();
      return {response,requests};
    } finally {
      this.fetches.delete(token);
      // Request-ID facts live only until Chromium's completed/error event.
    }
  }
  registerDownload(options) {
    if(this.closed || !options.owner || !options.attemptId || !options.contents || !options.document || !options.filename
      || !Number.isFinite(options.deadline))
      throw Error('Managed download context required');
    if(this.downloadSourceUnsafe(options.contents))throw new BrowserFailure('wos_download','download_not_attributable');
    const registration={...options,active:true,item:null};this.downloads.add(registration);
    const retire=()=>{registration.active=false;registration.item?.cancel();};
    const timer=setTimeout(retire,Math.max(1,options.deadline-Date.now()));timer.unref?.();
    options.signal?.addEventListener('abort',retire,{once:true});
    if(options.signal?.aborted)retire();
    const dispose=({dispatched=false}={})=>{
      if(!this.downloads.delete(registration))return;
      clearTimeout(timer);options.signal?.removeEventListener('abort',retire);registration.active=false;
      if(dispatched && !registration.item)this.guardDownload(registration);
    };registration.dispose=dispose;return {dispose};
  }
  registerTaskPage(options) {
    if(this.closed || !options.owner || !options.contents)throw Error('Managed task Page required');
    const entry={...options};this.taskPages.add(entry);
    return {dispose:()=>this.taskPages.delete(entry)};
  }
  overrideInline(details,state) {
    if(!['mainFrame','subFrame'].includes(details.resourceType) || !details.frame)return;
    const candidates=[...this.downloads].filter(entry=>entry.contents.id===details.webContentsId
      && this.matchesDownload(entry,entry.contents,details.frame));
    if(candidates.length!==1)return;
    const entry=candidates[0];
    if(!entry.active || entry.signal?.aborted || Date.now()>=entry.deadline || !entry.inlineMimeTypes)return;
    try{if(entry.validate()===false)return;}catch(_){return;}
    const type=Object.entries(state.responseHeaders || {}).find(([name])=>name.toLowerCase()==='content-type')?.[1];
    if(!Array.isArray(type) || type.length!==1 || !entry.inlineMimeTypes.includes(type[0].split(';')[0].trim().toLowerCase()))return;
    state.responseHeaders={...Object.fromEntries(Object.entries(state.responseHeaders)
      .filter(([name])=>name.toLowerCase()!=='content-disposition')),'Content-Disposition':['attachment']};
  }
  guardDownload(registration) {
    // A dispatched action without an item can still produce one after cancellation.
    // Its source must not be handed to a newer attempt while attribution is ambiguous.
    const contents=registration.contents;
    if(contents.isDestroyed?.() || this.downloadGuards.has(contents))return;
    // Chromium provides no request identity proving that a no-item action has
    // ended. One owner-free tombstone per physical source survives all timers.
    const remove=()=>{this.downloadGuards.delete(contents);contents.removeListener?.('destroyed',remove);};
    this.downloadGuards.set(contents,{remove});contents.once?.('destroyed',remove);
  }
  downloadSourceUnsafe(contents) {return this.downloadGuards.has(contents);}
  matchesDownload(registration,contents,frame) {
    if(!contents || registration.contents!==contents)return false;
    if(!frame)return false;
    const expected=registration.frame || registration.document;
    return expected?.processId===frame.processId && expected?.frameToken===frame.frameToken;
  }
  trackItem(item,contents) {
    let finish;const terminal=new Promise(resolve=>{finish=resolve;});
    const observation={interrupted:false,terminal:null};
    const entry={item,contents,terminal,observation};this.items.add(entry);
    let cancellation;
    const updated=(_event,state)=>{
      if(state!=='interrupted')return;
      observation.interrupted=true;
      // Chromium's DownloadItem observer list disallows reentrant mutation.
      // Cancel after its updated callback unwinds, retaining the item meanwhile.
      cancellation ??= setImmediate(()=>{if(this.items.has(entry))item.cancel();});
    };
    item.on('updated',updated);
    item.once('done',(_event,state)=>{clearImmediate(cancellation);item.removeListener('updated',updated);observation.terminal=state;this.items.delete(entry);finish(state);});
    return entry;
  }
  routeDownload(event,item,contents,frame) {
    const candidates=[...this.downloads].filter(entry=>this.matchesDownload(entry,contents,frame));
    const sourceScopes=[...this.downloads].filter(entry=>contents && entry.contents===contents);
    const guarded=this.downloadSourceUnsafe(contents);
    if(!frame && sourceScopes.length) {
      const tracked=this.trackItem(item,contents);
      for(const scope of sourceScopes)try{scope.onRejected?.({...tracked,reason:'download_not_attributable'});}catch(_){}
      item.cancel();return;
    }
    if(guarded || candidates.length>1) {
      this.trackItem(item,contents);item.cancel();
      for(const candidate of candidates){try{candidate.onAmbiguous?.();}catch(_){}candidate.item?.cancel();}
      return;
    }
    const registration=candidates[0];
    if(!registration) {
      const owned=contents && [...this.taskPages].some(entry=>{
        if(entry.contents!==contents)return false;
        try{return entry.validate()!==false;}catch(_){return false;}
      });
      if(owned){this.trackItem(item,contents);item.cancel();}
      return;
    }
    let valid=registration.active && !registration.signal?.aborted && Date.now()<registration.deadline;
    try{valid=valid && registration.validate()!==false;}catch(_){valid=false;}
    try {
      const initiator=item.getInitiatorOrigin?.();
      if(registration.document.url && initiator!==undefined)valid=valid && initiator===new URL(registration.document.url).origin;
    }catch(_){valid=false;}
    if(!valid){const tracked=this.trackItem(item,contents);try{registration.onRejected?.(tracked);}catch(_){}item.cancel();return;}
    if(registration.item) {
      this.trackItem(item,contents);item.cancel();try{registration.onAmbiguous?.();}catch(_){}registration.item.cancel();return;
    }
    registration.item=item;
    // The staging path was prepared before dispatch. Never await in this callback.
    const tracked=this.trackItem(item,contents);
    try {
      item.setSavePath(registration.filename);
      registration.onItem?.({...tracked,frame});
    }catch(_){item.cancel();}
  }
  async waitForDownloads(contents) {
    while(true) {
      const active=[...this.items].filter(entry=>!contents || entry.contents===contents);
      if(!active.length)return;
      await Promise.all(active.map(entry=>entry.terminal));
    }
  }
  dispose() {
    if(this.closed)return;this.closed=true;
    for(const name of this.installed)this.session.webRequest[name](null);
    this.session.removeListener?.('will-download',this.downloadListener);
    for(const guard of this.downloadGuards.values())guard.remove();
    for(const registration of [...this.downloads]){registration.item?.cancel();registration.dispose();}
    this.taskPages.clear();
    this.handlers.clear();this.requests.clear();this.fetches.clear();sessions.delete(this.session);
  }
}
function sharedSessionEvents(session,{timing}={}) {
  let entry=sessions.get(session);
  if(!entry){entry=new SharedSessionEvents(session,timing);sessions.set(session,entry);}
  return entry;
}
module.exports={sharedSessionEvents};
