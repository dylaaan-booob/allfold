'use strict';
const {NativeOutput}=require('./native-output.cjs');
const {target}=require('./body-stream.cjs');
const {publicClueURL,qualifyReader}=require('../browser/pdf-clues.cjs');
const {BrowserFailure,checkPage}=require('../browser/browser-errors.cjs');
const {checkCanceled,waitFor,pause}=require('../browser/browser-task.cjs');
const sameFrame=(a,b)=>!!a&&!!b&&a.processId===b.processId&&a.frameToken===b.frameToken;
const failure=code=>new BrowserFailure('navigation',code);
class OriginalNavigation {
  constructor(browser,doc,candidate,{output,signal,deadline,verify,progress}) {
    Object.assign(this,{browser,doc,candidate,output,signal,deadline,verify,progress});
    this.owner=browser.operation;this.sources=new Map();this.registrations=[];this.tracked=new Set();this.probes=new Set();this.dispatched=false;
    this.received=new Promise((resolve,reject)=>{this.resolve=resolve;this.reject=reject;});this.received.catch(()=>{});
    this.hook=browser.sessionEvents.subscribe('beforeRequest',details=>this.request(details));
    this.responseHook=browser.sessionEvents.subscribe('headersReceived',details=>this.response(details));
    this.addSource(browser.tabs.get(doc.pageId));
  }
  valid() {
    checkCanceled(this.signal);this.verify();
    if(Date.now()>=this.deadline)throw failure('timeout');
    if(!this.browser.operations.has(this.owner))throw failure('document_changed');
    if(!this.dispatched&&!this.browser.documentCurrent(this.doc))throw failure('document_changed');
    if(this.boundEntry&&!this.boundSource.contents.mainFrame.framesInSubtree.some(frame=>
      frame.frameTreeNodeId===this.boundEntry.request.frameTreeNodeId))throw failure('document_changed');
    if(this.error)throw this.error;
  }
  fail(error) {this.error ??= error;this.reject(this.error);for(const entry of this.tracked)this.browser.sessionEvents.cancelItem(entry.item);}
  dispatch() {this.valid();if(this.dispatched)throw failure('document_changed');this.dispatched=true;this.owner.phase='body';}
  acceptsURL(url) {
    if(!publicClueURL(url))return false;
    if(url===(this.requestURL || this.candidate.url))return true;
    if(this.candidate.platform!=='sciencedirect')return false;
    const source=new URL(this.doc.url),next=new URL(url),pii=source.pathname.match(/\/science\/article\/pii\/([SB][0-9X]{16})/i)?.[1];
    return !!pii && (next.origin===source.origin&&['/science/article/pii/'+pii+'/pdfft','/science/article/pii/'+pii+'/pdf'].includes(next.pathname)
      ||next.protocol==='https:'&&next.hostname==='pdf.sciencedirectassets.com'&&next.pathname.endsWith('/1-s2.0-'+pii+'/main.pdf'));
  }
  acceptPopup(url) {return !this.targetName&&this.dispatched&&!this.error&&!this.primary&&(url==='about:blank'||this.acceptsURL(url));}
  addPopup(tab) {
    if(!this.acceptPopup('about:blank'))return;
    if(tab.opener?.bodyAction!==this||tab.taskOwner!==this.owner)return;
    this.addSource(tab);
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
      if(!(event.isMainFrame ?? main))return;
      url=event.url ?? url;
      if(url==='about:blank'&&tab.id!==this.doc.pageId)return;
      if(!this.dispatched||!this.acceptsURL(url)||this.primary)this.fail(failure('document_changed'));
    };
    source.replaced=(_event,_url,main,processId,routingId)=>{
      if(main||this.boundSource===source&&this.boundEntry?.frame.processId===processId
        &&this.boundEntry.frame.routingId===routingId)this.fail(failure('document_changed'));
    };
    source.loaded=(_event,_main,processId,routingId)=>{
      if(this.error||this.primary)return;
      const frame=source.contents.mainFrame.framesInSubtree.find(item=>item.processId===processId&&item.routingId===routingId);
      if(!frame)return;
      for(const entry of source.frames.values())if(entry.response&&!entry.probing&&entry.request.frameTreeNodeId===frame.frameTreeNodeId) {
        entry.probing=true;
        const probe=this.browser.runInOperation(this.owner,()=>this.inspectResponse(source,entry,frame));this.probes.add(probe);
        probe.catch(error=>this.fail(error)).finally(()=>this.probes.delete(probe));
      }
    };
    contents.on('did-start-navigation',source.navigation);contents.on('did-navigate-in-page',source.replaced);
    contents.on('did-frame-finish-load',source.loaded);
  }
  addFrame(source,frame) {
    if(!frame||source.frames.has(frame.frameToken)||source.frames.size>=8)return;
    const entry={frame,request:null};source.frames.set(frame.frameToken,entry);
    entry.registration=this.browser.sessionEvents.registerDownload({owner:this.owner,attemptId:this.owner.association.request_id,
      contents:source.contents,frame,document:this.doc,requireRequest:true,filename:this.output.filename,
      deadline:this.deadline,signal:this.signal,inlineMimeTypes:['application/pdf'],
      validate:()=>{this.valid();return !!entry.request;},beforeSave:()=>this.output.absent(),
      onItem:tracked=>{
        this.tracked.add(tracked);
        if(this.primary||tracked.response?.contentType!=='application/pdf'||tracked.item.getMimeType()!=='application/pdf'
          ||tracked.response.status<200||tracked.response.status>=300){this.fail(failure('download_not_attributable'));tracked.item.cancel();return;}
        this.primary=tracked;
        let last=0;
        const update=()=>{
          try {
            this.valid();
            const observed=this.output.capture({missing:true});
            if(observed&&!this.observed){this.observed=observed.file;this.progress({native_output_file:observed.file});}
            if(Date.now()-last>=100){last=Date.now();this.progress({received_bytes:Math.max(0,tracked.item.getReceivedBytes()),
              total_bytes:tracked.item.getTotalBytes()>0?tracked.item.getTotalBytes():null});}
          }catch(error){this.error ??= error;setImmediate(()=>tracked.item.cancel());}
        };
        tracked.item.on('updated',update);tracked.terminal.then(()=>tracked.item.removeListener('updated',update));
        update();this.resolve(tracked);
      },
      onRejected:tracked=>{this.tracked.add(tracked);this.fail(tracked.error || failure('download_not_attributable'));},
      onAmbiguous:()=>this.fail(failure('download_not_attributable'))});
    this.registrations.push(entry.registration);
  }
  request(details) {
    const source=this.sources.get(details.webContentsId);
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
      if(!this.dispatched||!entry||!sameFrame(entry.frame,details.frame)||!this.acceptsURL(details.url)
        ||!['GET','POST'].includes(details.method)||this.primary)throw failure('document_changed');
      if(entry.request) {
        if(entry.request.id!==details.id)throw failure('document_changed');
        return;
      }
      if(!this.bound && (details.url!==(this.requestURL || this.candidate.url)||details.method!==this.method))throw failure('document_changed');
      // Redirects keep the bound request ID. A new request after the one-shot
      // dispatch cannot borrow the action merely because its URL looks related.
      if(this.bound)throw failure('document_changed');
      this.bound=true;this.boundSource=source;this.boundEntry=entry;
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
      if(status>=300&&status<400)return; // the same request ID may redirect
      const contentType=Object.entries(details.responseHeaders || {}).find(([name])=>name.toLowerCase()==='content-type')?.[1];
      const type=contentType?.length===1?contentType[0].split(';')[0].trim().toLowerCase():'';
      if(type==='application/pdf'&&status>=200&&status<300)return;
      if(!['text/html','application/xhtml+xml'].includes(type))throw failure('download_not_attributable');
      entry.response={url:details.url,status};
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
    const access=await this.browser.documents.call(binding,'access',{}, {signal:this.signal,deadline:this.deadline});
    this.valid();
    if(entry.response!==response||!this.browser.documentCurrent(binding))throw failure('document_changed');
    checkPage(response.status,access);
    if(access.markers.login)throw new BrowserFailure('navigation','content_access_blocked',response.status);
    // A dispatched one-shot action with ordinary HTML is a finite local failure,
    // never a new source, copied body, solver action or replayed request.
    throw failure('download_not_attributable');
  }
  dispose() {
    this.hook.dispose();this.responseHook.dispose();
    for(const registration of this.registrations)registration.dispose({dispatched:this.dispatched});
    for(const source of this.sources.values()) {
      source.contents.removeListener('frame-created',source.created);
      source.contents.removeListener('will-frame-navigate',source.targetNavigation);
      source.contents.removeListener('did-start-navigation',source.navigation);source.contents.removeListener('did-navigate-in-page',source.replaced);
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
  const bounded=AbortSignal.timeout(Math.max(1,Math.ceil(data.deadline_ms-Date.now())));
  const stop=AbortSignal.any([signal,bounded].filter(Boolean));
  try {
    output=new NativeOutput(data);
    if(!data.candidate||Object.keys(data.candidate).some(key=>!['url','action','platform','rule_id'].includes(key)))throw failure('document_operation_failed');
    const requested=data.candidate;
    if(!(requested.action==='refresh_form'&&requested.platform==='microbiology'&&requested.rule_id==='R059'
      ||!requested.action&&requested.platform==='sciencedirect'&&requested.rule_id==='R024'))throw failure('document_operation_failed');
    await waitFor(()=>browser.ready,stop,data.deadline_ms);verify=browser.pinPreparedPaperAccess(data);verify();
    const doc=await browser.openPaperPage(data,data.identity,{role:'article',signal:stop,deadline:data.deadline_ms});
    const tab=browser.tabs.get(doc.pageId);
    let pdf=await browser.readDocument(tab,'pdf',{signal:stop,deadline:data.deadline_ms,args:{readerKind:null}});
    const hydrationEnd=Math.min(data.deadline_ms,Date.now()+2000);
    while(requested.platform==='sciencedirect'&&pdf.clues.status==='complete'&&!pdf.clues.candidates.length&&Date.now()<hydrationEnd) {
      if(!browser.documentCurrent(doc)||pdf.documentId!==doc.documentId||pdf.subject!==doc.article.subject)throw failure('document_changed');
      await waitFor(()=>pause(stop,Math.min(200,hydrationEnd-Date.now())),stop,data.deadline_ms);
      pdf=await browser.readDocument(tab,'pdf',{signal:stop,deadline:data.deadline_ms,args:{readerKind:null}});
    }
    if(!browser.documentCurrent(doc)||pdf.documentId!==doc.documentId||pdf.subject!==doc.article.subject)throw failure('document_changed');
    let candidate=pdf.clues.candidates.find(item=>item.url===requested.url&&item.action===requested.action&&item.rule_id===requested.rule_id);
    if(!candidate&&requested.action==='refresh_form') {
      // A stored action is a refresh locator. Only this verified current
      // Document supplies the unique form, its present action and original body.
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
    await browser.confirmArticlePage(data.identity,doc,{signal:stop,deadline:data.deadline_ms});verify();
    operation=new OriginalNavigation(browser,doc,candidate,{output,signal:stop,deadline:data.deadline_ms,verify,progress});
    prepared=await browser.bodyActions.prepare(doc,{url:candidate.url,action:candidate.action,platform:candidate.platform,rule_id:candidate.rule_id},
      {signal:stop,deadline:data.deadline_ms});
    operation.method=prepared.plan.method;operation.requestURL=prepared.plan.request_url;
    operation.targetName=prepared.plan.target==='frame'?prepared.plan.target_name:null;
    operation.targetFrame=prepared.targetFrame;
    if(prepared.targetFrame)operation.addFrame(operation.sources.get(doc.pageId),prepared.targetFrame);
    if(prepared.plan.target==='popup')await browser.reserveChildPage({signal:stop,deadline:data.deadline_ms});
    await prepared.dispatch(()=>operation.dispatch(),error=>operation.fail(error));
    primary=await waitFor(()=>operation.received,stop,Math.min(data.deadline_ms,Date.now()+15000));
    const terminal=await primary.terminal; // actual done is never raced with timeout/cancellation
    if(primary.observation.interrupted)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'interrupted',
      native_terminal:terminal,native_cleanup:'asynchronous'};
    if(operation.error)throw operation.error;
    if(terminal!=='completed'||stop.aborted)return {outcome:bounded.aborted?'expired':stop.aborted?'cancelled':'local_failure',
      kind:bounded.aborted?'expired':stop.aborted?'cancelled':'local_failure',diagnostic_code:'native-interrupted',
      native_terminal:terminal,native_cleanup:'asynchronous'};
    operation.valid();
    const observed=output.capture();
    if(!operation.observed){operation.observed=observed.file;progress({native_output_file:observed.file});}
    progress({received_bytes:observed.size,total_bytes:primary.item.getTotalBytes()>0?primary.item.getTotalBytes():null});
    return {outcome:'native_complete',kind:'pdf',pdf_type:true,transfer_complete:true,output_file:observed.file,
      size_bytes:observed.size,final_url:primary.response.url,resource_closed:true};
  }catch(error) {
    if(error.bodyLocal)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'native-output'};
    if(stop.aborted||Date.now()>=data.deadline_ms) {
      const kind=bounded.aborted||Date.now()>=data.deadline_ms?'expired':'cancelled';return {outcome:kind,kind};
    }
    const code=error.diagnostic?.code;
    if(['verification_page','content_access_blocked','site_restricted','article_identity_conflict','article_identity_unconfirmed'].includes(code)
      ||code==='http_error'&&[401,403,407,418,429].includes(error.diagnostic.status))
      return {outcome:'failed',kind:'failed',diagnostic_code:'access-blocked',diagnostic:error.diagnostic};
    const kind=code==='document_changed'?'stale':operation?.dispatched?'local_failure':'failed';
    return {outcome:kind,kind,diagnostic_code:'native-action',diagnostic:error.diagnostic};
  }finally {
    // Keep registrations and their physical sources alive until all accepted or
    // refused native items have reached actual done, including late cancellation.
    // done(cancelled) does not acknowledge Chromium's queued pathname unlink.
    prepared?.dispose();
    if(operation){await operation.settle();operation.dispose();}
  }
}
module.exports={executeBodyNative,OriginalNavigation};
