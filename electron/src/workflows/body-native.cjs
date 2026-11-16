'use strict';
const {NativeOutput}=require('./native-output.cjs');
const {target}=require('./body-stream.cjs');
const {publicClueURL,qualifyReader}=require('../browser/pdf-clues.cjs');
const {BrowserFailure,checkPage}=require('../browser/browser-errors.cjs');
const {checkCanceled,waitFor,pause}=require('../browser/browser-task.cjs');
const sameFrame=(a,b)=>!!a&&!!b&&a.processId===b.processId&&a.frameToken===b.frameToken;
const failure=code=>new BrowserFailure('navigation',code);
class OriginalNavigation {
  constructor(browser,doc,candidate,{output,signal,deadline,verify,progress,cdnAllowed=false}) {
    Object.assign(this,{browser,doc,candidate,output,signal,deadline,verify,progress,cdnAllowed});
    this.sciencePII=candidate.platform==='sciencedirect'?new URL(doc.url).pathname.match(/\/science\/article\/pii\/([SB][0-9X]{16})/i)?.[1]:null;
    this.owner=browser.operation;this.sources=new Map();this.registrations=[];this.tracked=new Set();this.probes=new Set();this.dispatched=false;
    this.continuationEdges=new Set();this.continuationBytes=0;
    this.received=new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});this.received.catch(()=>{});
    this.hook=browser.sessionEvents.subscribe('beforeRequest',details=>this.request(details));
    this.headerHook=browser.sessionEvents.subscribe('beforeSendHeaders',details=>this.requestContext(details));
    this.responseHook=browser.sessionEvents.subscribe('headersReceived',details=>this.response(details));
    this.addSource(browser.tabs.get(doc.pageId));
  }
  valid() {
    checkCanceled(this.signal);this.verify();
    if(Date.now()>=this.deadline)throw failure('timeout');
    if(!this.browser.operations.has(this.owner))throw failure('document_changed');
    if(!this.dispatched&&!this.browser.documentFrame({pageId:this.doc.pageId,processId:this.doc.processId,frameToken:this.doc.frameToken}))throw failure('document_changed');
    if(!this.primary&&this.boundEntry&&!this.boundSource.contents.mainFrame.framesInSubtree.some(frame=>
      frame.frameTreeNodeId===this.boundEntry.request.frameTreeNodeId))throw failure('document_changed');
    if(this.error)throw this.error;
  }
  fail(error) {this.error ??= error;this.reject(this.error);for(const entry of this.tracked)this.browser.sessionEvents.cancelItem(entry.item);}
  dispatch() {this.valid();if(this.dispatched)throw failure('document_changed');this.dispatched=true;this.owner.phase='body';}
  acceptsURL(url) {
    if(!publicClueURL(url))return false;
    if(url===(this.requestURL || this.candidate.url))return true;
    if(this.candidate.platform!=='sciencedirect')return false;
    return this.scienceReaderURL(url)||this.scienceAsset(url);
  }
  scienceReaderURL(url) {
    if(!this.sciencePII||!publicClueURL(url))return false;
    const source=new URL(this.doc.url),next=new URL(url);
    return next.origin===source.origin&&['/science/article/pii/'+this.sciencePII+'/pdfft','/science/article/pii/'+this.sciencePII+'/pdf'].includes(next.pathname);
  }
  scienceAsset(url) {
    if(!this.cdnAllowed||!this.sciencePII||!publicClueURL(url))return false;
    const next=new URL(url);
    return next.protocol==='https:'&&next.hostname==='pdf.sciencedirectassets.com'&&next.pathname.endsWith('/1-s2.0-'+this.sciencePII+'/main.pdf');
  }
  scienceReader(source,entry,frame) {
    if(!this.sciencePII||!entry?.response||entry.continued||source!==this.boundSource||entry!==this.boundEntry
      ||entry.response.status<200||entry.response.status>=300
      ||frame.frameTreeNodeId!==entry.request.frameTreeNodeId||frame.url!==entry.response.url)return false;
    return this.scienceReaderURL(frame.url)||this.scienceAsset(frame.url);
  }
  scienceContinuation(url) {
    if(this.scienceAsset(url))return 'cdn';
    return this.scienceReaderURL(url)?'reader':null;
  }
  continueScienceReader(source,event) {
    const frame=source.contents.mainFrame,previous=this.boundEntry,kind=this.scienceContinuation(event.url);
    if(!this.dispatched||this.error||this.primary||this.continuation&&!this.continuation.used||!event.isMainFrame
      ||event.frame?.frameTreeNodeId!==frame.frameTreeNodeId||!sameFrame(event.initiator,frame)||!kind
      ||!this.scienceReader(source,previous,frame))return;
    this.valid();
    const edge=JSON.stringify([previous.response.url,event.url,previous.response.state]);
    const repeated=this.continuationEdges.has(edge);
    if(repeated&&typeof previous.context!=='string')throw failure('download_not_attributable');
    if(!repeated)this.continuationBytes+=Buffer.byteLength(edge);
    if(this.continuationBytes>1048576)throw failure('download_not_attributable');
    this.continuationEdges.add(edge);
    // Only this committed response's observed main-frame continuation inherits
    // the action. Repeated identical edges stop; changed response/Cookie evidence
    // may permit a legitimate same-URL authentication return.
    previous.continued=true;previous.registration.dispose();source.frames.delete(previous.frame.frameToken);
    this.registrations=this.registrations.filter(registration=>registration!==previous.registration);
    const entry=this.addFrame(source,event.frame,{...this.doc,url:previous.response.url});
    if(!entry)throw failure('document_changed');
    entry.previousContext=repeated?previous.context:undefined;
    this.continuation={source,entry,url:event.url,frameTreeNodeId:frame.frameTreeNodeId,used:false};
  }
  acceptPopup(url,frameName) {
    if(this.targetName&&(this.targetFrame||this.namedPopup||frameName!==this.targetName))return false;
    return !this.continuation&&this.dispatched&&!this.error&&!this.primary&&(url==='about:blank'||this.acceptsURL(url));
  }
  addPopup(tab) {
    if(!this.acceptPopup('about:blank',tab.popupFrameName))return;
    if(tab.opener?.bodyAction!==this||tab.taskOwner!==this.owner)return;
    this.addSource(tab);
    if(this.targetName){this.namedPopup=tab;this.targetFrame=tab.view.webContents.mainFrame;}
  }
  addSource(tab) {
    if(!tab||this.sources.has(tab.id))return;
    const contents=tab.view.webContents,source={tab,contents,frames:new Map(),createdFrames:new Set()};this.sources.set(tab.id,source);tab.bodyAction=this;
    this.addFrame(source,contents.mainFrame);
    source.created=(_event,{frame})=>{
      if(!this.dispatched||!frame||this.primary||this.error)return;
      if(source.createdFrames.size>=8||!sameFrame(frame.parent,contents.mainFrame))return;
      source.createdFrames.add(frame.frameToken);
    };
    contents.on('frame-created',source.created);
    source.targetNavigation=event=>{
      try {this.continueScienceReader(source,event);}catch(error){this.fail(error);}
      const frame=event.frame;
      if(!this.dispatched||this.bound||this.primary||this.error||event.isMainFrame||!frame)return;
      if(!source.createdFrames.has(frame.frameToken)||!sameFrame(event.initiator,this.doc)
        ||event.url!==(this.requestURL||this.candidate.url))return;
      if(this.targetName&&(this.targetFrame||frame.name!==this.targetName))return;
      // The fixed action's native initiator and newly created destination are
      // known before its first request; unrelated new children stay unregistered.
      if(this.targetName)this.targetFrame=frame;
      this.addFrame(source,frame);
    };
    contents.on('will-frame-navigate',source.targetNavigation);
    source.navigation=(event,url,_inPlace,main)=>{
      if(this.primary || event.isInPlace || _inPlace || !(event.isMainFrame ?? main))return;
      url=event.url ?? url;
      if(url==='about:blank'&&tab.id!==this.doc.pageId)return;
      // did-start-navigation precedes will-frame-navigate. Retire only the old
      // read probe here; native initiator/destination checks still gate the request.
      if((!this.continuation||this.continuation.used)&&this.scienceContinuation(url)&&this.scienceReader(source,this.boundEntry,contents.mainFrame))
        this.boundEntry.pendingContinuation=true;
      if(!this.dispatched||!this.acceptsURL(url))this.fail(failure('document_changed'));
    };
    source.loaded=(_event,_main,processId,routingId)=>{
      if(this.error||this.primary)return;
      const frame=source.contents.mainFrame.framesInSubtree.find(item=>item.processId===processId&&item.routingId===routingId);
      if(!frame)return;
      for(const entry of source.frames.values())if(entry.response&&!entry.continued&&!entry.probing&&entry.request.frameTreeNodeId===frame.frameTreeNodeId) {
        entry.probing=true;
        const probe=this.browser.runInOperation(this.owner,()=>this.inspectResponse(source,entry,frame));this.probes.add(probe);
        probe.catch(error=>this.fail(error)).finally(()=>this.probes.delete(probe));
      }
    };
    contents.on('did-start-navigation',source.navigation);
    contents.on('did-frame-finish-load',source.loaded);
  }
  addFrame(source,frame,document=this.doc) {
    if(!frame||source.frames.has(frame.frameToken)||source.frames.size>=8)return;
    const entry={frame,request:null};source.frames.set(frame.frameToken,entry);
    entry.registration=this.browser.sessionEvents.registerDownload({owner:this.owner,attemptId:this.owner.association.request_id,
      contents:source.contents,frame,document,requireRequest:true,filename:this.output.filename,
      deadline:this.deadline,signal:this.signal,bodyContent:true,htmlReader:!this.candidate.action,
      validate:()=>{this.valid();return !!entry.request;},beforeSave:()=>this.output.absent(),
      onItem:tracked=>{
        this.tracked.add(tracked);
        if(this.primary||!tracked.response||tracked.response.status<200||tracked.response.status>=300){this.fail(failure('download_not_attributable'));tracked.item.cancel();return;}
        this.primary=tracked;
        this.accessBlocked=entry.response?.cfMitigated===true;
        let last=0;
        const update=()=>{
          try {
            this.valid();
            const observed=this.output.capture({missing:true});
            if(observed&&!this.observed){this.observed=observed.file;this.progress({native_output_file:observed.file});}
            if(Date.now()-last>=100){last=Date.now();this.progress({received_bytes:Math.max(0,tracked.item.getReceivedBytes()),
              total_bytes:tracked.item.getTotalBytes()>0?tracked.item.getTotalBytes():null});}
          }catch(error){if(error.bodyLocal)this.outputError ??= error;this.error ??= error;
            setImmediate(()=>this.browser.sessionEvents.cancelItem(tracked.item));}
        };
        tracked.item.on('updated',update);tracked.terminal.then(()=>tracked.item.removeListener('updated',update));
        update();this.resolve(tracked);
      },
      onRejected:tracked=>{this.tracked.add(tracked);this.fail(tracked.error || failure('download_not_attributable'));},
      onAmbiguous:()=>this.fail(failure('download_not_attributable'))});
    this.registrations.push(entry.registration);
    return entry;
  }
  request(details) {
    const source=this.sources.get(details.webContentsId);
    if(this.primary)return; // A bound DownloadItem owns the transfer, not later page navigation.
    if(!source||!['mainFrame','subFrame'].includes(details.resourceType))return;
    if(details.url==='about:blank')return;
    const entry=source.frames.get(details.frame?.frameToken);
    if(details.resourceType==='subFrame') {
      // Once dispatched, authority belongs to one physical request/frame. Other
      // article children can navigate without acquiring output authority or
      // revoking that request. The action destination itself remains guarded,
      // including a successor renderer with the same FrameTreeNode ID.
      if(this.bound && !(this.boundSource===source&&this.boundEntry.request.frameTreeNodeId===details.frame?.frameTreeNodeId))return;
      if(!this.bound&&!entry)return;
    }
    try {
      this.valid();
      if(!this.bound&&this.targetName&&!this.targetFrame)throw failure('document_changed');
      if(!this.bound&&this.targetFrame&&!sameFrame(this.targetFrame,details.frame))throw failure('document_changed');
      const redirect=this.formRedirect;
      const redirected=redirect&&redirect.source===source&&redirect.entry===entry&&redirect.id===details.id
        &&redirect.url===details.url&&details.method==='GET';
      if(!this.dispatched||!entry||!sameFrame(entry.frame,details.frame)||!(this.acceptsURL(details.url)||redirected)
        ||!['GET','POST'].includes(details.method)||this.primary)throw failure('document_changed');
      if(entry.request) {
        if(entry.request.id!==details.id)throw failure('document_changed');
        return;
      }
      const continuation=this.continuation;
      const continuing=continuation&&!continuation.used&&continuation.source===source&&continuation.entry===entry;
      if(continuing) {
        if(details.url!==continuation.url||details.method!=='GET'||details.frame.frameTreeNodeId!==continuation.frameTreeNodeId)throw failure('document_changed');
      }else if(!this.bound && (details.url!==(this.requestURL || this.candidate.url)||details.method!==this.method))throw failure('document_changed');
      // Redirects keep the bound request ID. A new request after the one-shot
      // dispatch cannot borrow the action merely because its URL looks related.
      if(this.bound&&!continuing)throw failure('document_changed');
      this.bound=true;this.boundSource=source;this.boundEntry=entry;
      if(continuing)continuation.used=true;
      entry.request={id:details.id,frameTreeNodeId:details.frame.frameTreeNodeId,
        frame:{processId:details.frame.processId,frameToken:details.frame.frameToken}};
      entry.registration.bindRequest(details);
    } catch(error){this.fail(error);return {cancel:true};}
  }
  response(details) {
    const source=this.sources.get(details.webContentsId),entry=source?.frames.get(details.frame?.frameToken);
    if(!entry?.request||entry.request.id!==details.id||!sameFrame(entry.request.frame,details.frame))return;
    try {
      this.valid();
      const status=details.statusCode;
      if([401,403,407,418,429].includes(status))throw new BrowserFailure('navigation','http_error',status);
      if(status>=300&&status<400) {
        // R059's original POST can return its same-origin docserver URL. Only
        // this observed 303 can carry the same native request/frame to that GET.
        if(this.candidate.platform==='microbiology'&&this.method==='POST') {
          if(status!==303||this.formRedirect||details.method!=='POST'||details.url!==this.requestURL)throw failure('document_changed');
          const location=Object.entries(details.responseHeaders || {}).find(([name])=>name.toLowerCase()==='location')?.[1];
          if(location?.length!==1)throw failure('document_changed');
          const source=new URL(details.url),next=new URL(location[0],source);
          if(!source.pathname.startsWith('/deliver/fulltext/')||!publicClueURL(next.href)||next.hash
            ||next.origin!==source.origin||next.pathname!==source.pathname.replace(/^\/deliver\//,'/docserver/'))throw failure('document_changed');
          this.formRedirect={source:this.boundSource,entry,id:details.id,url:next.href};
        }
        return; // redirects still keep the exact original native request ID
      }
      const contentType=Object.entries(details.responseHeaders || {}).find(([name])=>name.toLowerCase()==='content-type')?.[1];
      const type=contentType?.length===1?contentType[0].split(';')[0].trim().toLowerCase():'';
      if(!['text/html','application/xhtml+xml'].includes(type)&&status>=200&&status<300)return;
      if(!['text/html','application/xhtml+xml'].includes(type))throw failure('download_not_attributable');
      const mitigated=Object.entries(details.responseHeaders || {}).filter(([name])=>name.toLowerCase()==='cf-mitigated').flatMap(([,values])=>values);
      const state=Object.entries(details.responseHeaders||{}).filter(([name])=>['etag','last-modified','set-cookie'].includes(name.toLowerCase()));
      entry.response={url:details.url,status,state,cfMitigated:mitigated.length===1 && mitigated[0].trim().toLowerCase()==='challenge'};
    }catch(error){this.fail(error);return {cancel:true};}
  }
  requestContext(details) {
    const source=this.sources.get(details.webContentsId),entry=source?.frames.get(details.frame?.frameToken);
    if(!entry?.request||entry.request.id!==details.id||!sameFrame(entry.request.frame,details.frame))return;
    try {
      this.valid();
      // These exact outgoing credentials stay ephemeral in Main. They permit
      // a repeated observed edge only when its actual authentication changed,
      // including document.cookie changes without a Set-Cookie response header.
      const context=JSON.stringify(Object.entries(details.requestHeaders||{})
        .filter(([name])=>['cookie','authorization'].includes(name.toLowerCase()))
        .map(([name,value])=>[name.toLowerCase(),value]).sort(([a],[b])=>a.localeCompare(b)));
      if(entry.previousContext!==undefined&&entry.previousContext===context)throw failure('download_not_attributable');
      entry.context=context;
    }catch(error){this.fail(error);return {cancel:true};}
  }
  async inspectResponse(source,entry,frame) {
    this.valid();
    const response=entry.response,root=source.contents.mainFrame;
    // A committed HTML response can replace its renderer frame token. Its
    // non-reused FrameTreeNode ID connects that successor to the exact request;
    // every new navigation request is still refused by the one-shot guard.
    if(frame.frameTreeNodeId!==entry.request.frameTreeNodeId||frame.url!==response.url)throw failure('document_changed');
    const binding={pageId:source.tab.id,processId:frame.processId,frameToken:frame.frameToken,url:response.url,
      navigationGeneration:source.tab.documentGeneration,rootProcessId:root.processId,rootFrameToken:root.frameToken};
    let access;
    try {access=await this.browser.documents.call(binding,'access',{}, {signal:this.signal,deadline:this.deadline});}
    catch(error) {
      if(!(entry.continued||entry.pendingContinuation)||error.diagnostic?.code!=='document_changed')throw error;
      this.valid();return;
    }
    this.valid();
    checkPage(response.status,{...access,cfMitigated:response.cfMitigated});
    if(access.markers.login || access.markers.mfa)throw new BrowserFailure('navigation','content_access_blocked',response.status);
    if(entry.continued)return;
    if(entry.response!==response||!this.browser.documentCurrent(binding))throw failure('document_changed');
    if(this.scienceReader(source,entry,frame))return;
    // A dispatched one-shot action with ordinary HTML is a finite local failure,
    // never a new source, copied body, solver action or replayed request.
    throw failure('download_not_attributable');
  }
  dispose() {
    this.hook.dispose();this.headerHook.dispose();this.responseHook.dispose();
    for(const registration of this.registrations)registration.dispose({dispatched:this.dispatched});
    for(const source of this.sources.values()) {
      source.contents.removeListener('frame-created',source.created);
      source.contents.removeListener('will-frame-navigate',source.targetNavigation);
      source.contents.removeListener('did-start-navigation',source.navigation);
      source.contents.removeListener('did-frame-finish-load',source.loaded);
      if(source.tab.bodyAction===this)source.tab.bodyAction=null;
    }
  }
  async settle() {
    if(this.signal?.aborted||this.error)for(const entry of this.tracked)this.browser.sessionEvents.cancelItem(entry.item);
    await Promise.all([...this.probes].map(probe=>probe.catch(()=>{})));
    await Promise.all([...this.tracked].map(entry=>entry.terminal));
    await Promise.all([...this.sources.values()].map(source=>this.browser.sessionEvents.waitForDownloads(source.contents)));
  }
}
async function executeBodyNative(browser,data,{signal,progress=()=>{}}={}) {
  let output,operation,prepared,primary,verify;
  const deadlineController=new AbortController(),bounded=deadlineController.signal;
  const timer=setTimeout(()=>deadlineController.abort(),Math.max(1,Math.ceil(data.deadline_ms-Date.now())));
  const stop=AbortSignal.any([signal,bounded].filter(Boolean));
  try {
    output=new NativeOutput(data);
    if(!data.candidate||Object.keys(data.candidate).some(key=>!['url','action','platform','rule_id'].includes(key)))throw failure('document_operation_failed');
    const requested=data.candidate;
    if(!(requested.action==='refresh_form'&&requested.platform==='microbiology'&&requested.rule_id==='R059'
      ||!requested.action&&requested.platform==='sciencedirect'&&requested.rule_id==='R024'))throw failure('document_operation_failed');
    await waitFor(()=>browser.ready,stop,data.deadline_ms);verify=browser.pinPreparedPaperAccess(data);verify();
    let doc=await browser.openPaperPage(data,data.identity,{role:'article',signal:stop,deadline:data.deadline_ms});
    const tab=browser.tabs.get(doc.pageId);
    let pdf=await browser.readDocument(tab,'pdf',{signal:stop,deadline:data.deadline_ms,identity:data.identity,args:{readerKind:null}});
    const hydrationEnd=Math.min(data.deadline_ms,Date.now()+2000);
    while(requested.platform==='sciencedirect'&&pdf.clues.status==='complete'&&!pdf.clues.candidates.length&&Date.now()<hydrationEnd) {
      await waitFor(()=>pause(stop,Math.min(200,hydrationEnd-Date.now())),stop,data.deadline_ms);
      pdf=await browser.readDocument(tab,'pdf',{signal:stop,deadline:data.deadline_ms,identity:data.identity,args:{readerKind:null}});
    }
    let candidate=pdf.clues.candidates.find(item=>item.url===requested.url&&item.action===requested.action&&item.rule_id===requested.rule_id);
    if(!candidate&&requested.action==='refresh_form') {
      // A stored action is a refresh locator. This Paper snapshot supplies
      // the current candidate; dispatch locates its native form and controls.
      const forms=pdf.clues.candidates.filter(item=>item.rule_id==='R059'&&item.action==='refresh_form');
      if(forms.length===1)candidate=forms[0];
    }
    if(!candidate&&requested.platform==='sciencedirect')candidate=pdf.clues.candidates.find(item=>item.rule_id==='R024'&&!item.action);
    if(!candidate)return {outcome:'failed',kind:'failed',diagnostic_code:'entry-unavailable'};
    candidate={...candidate,platform:requested.platform};
    if(requested.platform==='sciencedirect') {
      const source=new URL(doc.url),pii=source.pathname.match(/\/science\/article\/pii\/([SB][0-9X]{16})/i)?.[1];
      qualifyReader({stage:'P4',rule_id:'R024',platform:'sciencedirect',url:candidate.url,source_url:doc.url,
        identifier:pii,target:data.identity},data.identity);
    }
    await waitFor(()=>target(candidate.url,browser.bodyTargetResolver),stop,data.deadline_ms);
    let cdnAllowed=false;
    if(requested.platform==='sciencedirect')try {
      await waitFor(()=>target('https://pdf.sciencedirectassets.com/',browser.bodyTargetResolver),stop,data.deadline_ms);cdnAllowed=true;
    }catch(error) {checkCanceled(stop);if(Date.now()>=data.deadline_ms)throw error;}
    verify();
    // The action uses its current native source frame; candidate qualification
    // above remains tied to this Paper's PDF snapshot.
    const frame=tab.view.webContents.mainFrame;
    doc={pageId:tab.id,processId:frame.processId,frameToken:frame.frameToken,url:pdf.clues.landing_url,identity:data.identity};
    operation=new OriginalNavigation(browser,doc,candidate,{output,signal:stop,deadline:data.deadline_ms,verify,progress,cdnAllowed});
    prepared=await browser.bodyActions.prepare(doc,{url:candidate.url,action:candidate.action,platform:candidate.platform,rule_id:candidate.rule_id},
      {signal:stop,deadline:data.deadline_ms});
    operation.method=prepared.plan.method;operation.requestURL=prepared.plan.request_url;
    operation.targetName=prepared.plan.target==='frame'?prepared.plan.target_name:null;
    operation.targetFrame=prepared.targetFrame;
    if(prepared.targetFrame)operation.addFrame(operation.sources.get(doc.pageId),prepared.targetFrame);
    if(prepared.plan.target==='popup'||prepared.plan.target==='frame'&&!prepared.targetFrame)
      await browser.reserveChildPage({signal:stop,deadline:data.deadline_ms});
    await prepared.dispatch(plan=>{operation.requestURL=plan.request_url;operation.dispatch();},error=>operation.fail(error));
    primary=await waitFor(()=>operation.received,stop,data.deadline_ms);
    const terminal=await primary.terminal; // actual done is never raced with timeout/cancellation
    clearTimeout(timer);
    if(terminal!=='completed') {
      if(primary.observation.interrupted)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'interrupted',
        native_terminal:terminal,native_cleanup:'asynchronous'};
      if(operation.error)throw operation.error;
      return {outcome:bounded.aborted?'expired':stop.aborted?'cancelled':'local_failure',
      kind:bounded.aborted?'expired':stop.aborted?'cancelled':'local_failure',diagnostic_code:'native-interrupted',
      native_terminal:terminal,native_cleanup:'asynchronous'};
    }
    if(operation.outputError)throw operation.outputError;
    const observed=output.capture({sniff:true});
    if(!operation.observed){operation.observed=observed.file;try{progress({native_output_file:observed.file});}catch(_){}}
    try{progress({received_bytes:observed.size,total_bytes:primary.item.getTotalBytes()>0?primary.item.getTotalBytes():null});}catch(_){}
    if(!observed.pdf)return {outcome:'failed',kind:'failed',diagnostic_code:operation.accessBlocked?'access-blocked':'non-pdf',output_file:observed.file,resource_closed:true};
    return {outcome:'native_complete',kind:'pdf',pdf_type:true,transfer_complete:true,output_file:observed.file,
      size_bytes:observed.size,final_url:primary.response.url,resource_closed:true};
  }catch(error) {
    if(error.bodyLocal)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'native-output'};
    if(stop.aborted||Date.now()>=data.deadline_ms) {
      const kind=bounded.aborted||Date.now()>=data.deadline_ms?'expired':'cancelled';return {outcome:kind,kind};
    }
    const code=error.diagnostic?.code;
    if(['verification_page','content_access_blocked','site_restricted'].includes(code)
      ||code==='http_error'&&[401,403,407,418,429].includes(error.diagnostic.status))
      return {outcome:'failed',kind:'failed',diagnostic_code:'access-blocked',diagnostic:error.diagnostic};
    if(code==='body_action_unavailable')return {outcome:'failed',kind:'failed',diagnostic_code:'entry-unavailable'};
    // A source frame/navigation refusal is local after its items/pages settle.
    // Python independently rechecks the captured Workspace/Paper/attempt before
    // dispatching any later candidate; that is the task's stale boundary.
    return {outcome:'failed',kind:'failed',diagnostic_code:'native-action',diagnostic:error.diagnostic};
  }finally {
    clearTimeout(timer);
    // Keep registrations and their physical sources alive until all accepted or
    // refused native items have reached actual done, including late cancellation.
    // done(cancelled) does not acknowledge Chromium's queued pathname unlink.
    browser.cleanupStep(()=>prepared?.dispose(),operation?.owner);
    if(operation){await operation.settle();browser.cleanupStep(()=>operation.dispose(),operation.owner);}
  }
}
module.exports={executeBodyNative,OriginalNavigation};
