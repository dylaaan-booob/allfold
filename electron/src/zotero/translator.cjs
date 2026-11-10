'use strict';
const {BrowserWindow,session,ipcMain,net}=require('electron');
const {RUNTIME_DIR,PRELOAD_DIR}=require('../shared/paths.cjs');
const fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const {randomBytes}=require('node:crypto');
const {normalizeDOI}=require('./local-importer.cjs');
const {ImportFailure}=require('../workflows/import-errors.cjs');
const {withTaskDeadline,waitFor,checkCanceled,pause}=require('../browser/browser-task.cjs');
const {log,attachmentCounts}=require('../shared/logging.cjs');
const {requestSessionHTTP,RequestTransportError}=require('./session-http.cjs');
function validateTranslatorURL(value) {
  const url=new URL(value);
  if(!['http:','https:'].includes(url.protocol) || url.username || url.password)throw Error('Translator target blocked');
}
function workspaceItem(metadata,doi) {
  if(!metadata || typeof metadata.doi!=='string' || metadata.doi.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase()!==doi || typeof metadata.title!=='string' || !metadata.title.trim())return null;
  return {itemType:'journalArticle',DOI:doi,title:metadata.title,
    ...(typeof metadata.journal==='string'?{publicationTitle:metadata.journal}:{}),
    ...(typeof metadata.abstract==='string'?{abstractNote:metadata.abstract}:{}),
    ...(typeof metadata.publication_date==='string'?{date:metadata.publication_date}:{}),
    ...(metadata.journal_issns?.length?{ISSN:metadata.journal_issns[0]}:{}),
    creators:(Array.isArray(metadata.authors)?metadata.authors:[]).filter(name=>typeof name==='string'&&name.trim())
      .map(name=>({creatorType:'author',lastName:name,fieldMode:1})),attachments:[]};
}
const sandboxOperations=new Map();
let sandboxPartition;
function translatorPartition() {
  if(sandboxPartition)return sandboxPartition;
  const partition=session.fromPartition('allfold-translator');
  partition.setPermissionRequestHandler((_w,_p,callback)=>callback(false));
  partition.setPermissionCheckHandler(()=>false);
  partition.protocol.handle('allfold-zotero',request=>{
    const url=new URL(request.url);
    if(url.hostname!=='zotero')return new Response('',{status:403});
    const adapter=path.join(__dirname,'sandbox-adapter.js');
    const file=url.pathname==='/sandbox-adapter.js'?adapter:path.resolve(RUNTIME_DIR,'.'+decodeURIComponent(url.pathname));
    if((file!==adapter&&!file.startsWith(RUNTIME_DIR+path.sep))
      || !fs.existsSync(file) || !fs.statSync(file).isFile())return new Response('',{status:404});
    return net.fetch(pathToFileURL(file).href);
  });
  ipcMain.handle('translator:request',async(event,spec)=>{
    const operation=sandboxOperations.get(event.sender),frame=event.senderFrame;
    if(!operation || spec?.operationId!==operation.id || !frame || frame!==event.sender.mainFrame
      || frame.url!==operation.url)throw Error('Expired or untrusted Translator operation');
    const request=inBrowserOperation(operation.browser,operation.owner,()=>operation.request(spec));
    operation.requests.add(request);
    try {return await request;}
    finally {operation.requests.delete(request);}
  });
  sandboxPartition=partition;
  return partition;
}
function inBrowserOperation(browser,owner,run) {
  return browser.runInOperation?browser.runInOperation(owner,run):run();
}
function documentCurrent(browser,owner,doc) {
  if(browser.ownsPage && !browser.ownsPage(owner,doc.pageId))return false;
  return browser.documentCurrent(doc) && (!browser.documentFrame || browser.documentFrame(doc)?.url===doc.url);
}
function newSandboxWindow(partition) {
  const window=new BrowserWindow({show:false,webPreferences:{session:partition,
    preload:path.join(PRELOAD_DIR,'sandbox-preload.cjs'),sandbox:true,contextIsolation:true,nodeIntegration:false}});
  window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  window.webContents.on('will-navigate',event=>event.preventDefault());
  return window;
}
class TranslatorSandbox {
  constructor({maxWorkers=2}={}) {
    if(!Number.isSafeInteger(maxWorkers) || maxWorkers<1)throw new TypeError('Invalid Translator worker limit');
    this.maxWorkers=maxWorkers;
    this.stopped=new AbortController();
    this.pending=[];
    this.active=new Set();
    this.idle=[];
    this.translations=new Set();
  }
  async init(browser) {
    this.browser=browser;
    this.partition=translatorPartition();
  }
  dispatch() {
    while(!this.stopped.signal.aborted && this.pending.length && this.active.size<this.maxWorkers) {
      const operation=this.pending.shift();
      if(operation.signal.aborted || Date.now()>=operation.deadline)continue;
      try {
        let window;
        while(this.idle.length) {
          window=this.idle.pop();
          if(window.isDestroyed())window=undefined;
          else if(window.webContents.isCrashed()){window.destroy();window=undefined;}
          else break;
        }
        operation.window=window ||= newSandboxWindow(this.partition);
        operation.contents=window.webContents;
        this.active.add(operation);
        sandboxOperations.set(operation.contents,operation);
        operation.ready.resolve();
      }catch(error){operation.ready.reject(error);}
    }
  }
  current(operation) {
    checkCanceled(operation.signal);
    if(!this.active.has(operation) || !documentCurrent(operation.browser,operation.owner,operation.doc))
      throw new ImportFailure('translation','document_changed');
  }
  async request(operation,spec) {
    this.current(operation);
    const {browser,doc,signal,logContext}=operation;
    if(!['GET','POST','HEAD','OPTIONS'].includes(spec.method))throw Error('Translator method blocked');
    const headers={};
    for(const [key,value] of Object.entries(spec.headers || {}))
      if(!/^(host|connection|proxy-|sec-|x-allfold-http-context$)/i.test(key))headers[key]=String(value);
    try {
      const response=await requestSessionHTTP(browser.partition,{url:spec.url,method:spec.method,
        headers,body:spec.body,referrer:spec.referrer,timeout:spec.timeout===undefined?15000:spec.timeout},
        {doc,signal,kind:'translator',cookieAdapter:browser.cookieAdapter,validateRedirect:validateTranslatorURL});
      this.current(operation);
      const safeHeaders=response.headers.filter(([key])=>!/^set-cookie2?$/i.test(key));
      log('debug','translator_http',{...logContext,stage:'translation',host:new URL(response.url).hostname,
        status:response.status,content_type:safeHeaders.find(([key])=>key.toLowerCase()==='content-type')?.[1]?.split(';')[0],
        response_bytes:response.body.length,challenge:safeHeaders.some(([key,value])=>key.toLowerCase()==='cf-mitigated'&&value==='challenge')?'cf-mitigated':undefined});
      return {ok:true,status:response.status,statusText:response.statusText,url:response.url,headers:safeHeaders,bytes:new Uint8Array(response.body)};
    }catch(error) {
      this.current(operation);
      if(!(error instanceof RequestTransportError))throw error;
      return {ok:false,error:{kind:'transport',code:error.code,...(error.net_error?{net_error:error.net_error}:{})}};
    }
  }
  async openOperation(doc,{signal,logContext,deadline=Infinity}={}) {
    const browser=this.browser,owner=browser.operation;
    const controller=new AbortController(),id=randomBytes(16).toString('hex');
    const operation={id,browser,owner,doc:{...doc},controller,deadline,logContext,ready:Promise.withResolvers(),requests:new Set(),
      signal:AbortSignal.any([controller.signal,this.stopped.signal,...(signal?[signal]:[])]),
      url:'allfold-zotero://zotero/offscreen.html?operation='+id};
    operation.request=spec=>this.request(operation,spec);
    const contents=browser.tabs?.get(doc.pageId)?.view.webContents;
    const changed=()=>inBrowserOperation(browser,owner,()=>{
      if(!documentCurrent(browser,owner,doc))controller.abort(new ImportFailure('translation','document_changed'));
    });
    const navigating=event=>{
      const frame=event.frame;
      if((event.isMainFrame || (frame && !frame.isDestroyed() && frame.frameToken===doc.frameToken))
        && !(event.isSameDocument && event.url===(event.isMainFrame?doc.rootURL || doc.url:doc.url)))
        controller.abort(new ImportFailure('translation','document_changed'));
    };
    const closed=()=>controller.abort(new ImportFailure('translation','page_closed'));
    const workerGone=()=>controller.abort(new ImportFailure('translation','document_operation_failed'));
    contents?.on('did-start-navigation',navigating);contents?.on('did-frame-navigate',changed);
    contents?.once('destroyed',closed);contents?.once('render-process-gone',closed);
    operation.cleanup=()=>{
      contents?.removeListener('did-start-navigation',navigating);contents?.removeListener('did-frame-navigate',changed);
      contents?.removeListener('destroyed',closed);contents?.removeListener('render-process-gone',closed);
      if(operation.contents && !operation.contents.isDestroyed()) {
        operation.contents.removeListener('destroyed',workerGone);operation.contents.removeListener('render-process-gone',workerGone);
      }
    };
    try {
      await waitFor(()=>{
        this.pending.push(operation);this.dispatch();return operation.ready.promise;
      },operation.signal,deadline,'translation','sandbox_queue');
      this.current(operation);
      operation.contents.once('destroyed',workerGone);operation.contents.once('render-process-gone',workerGone);
      await waitFor(()=>operation.window.loadURL(operation.url),operation.signal,deadline,'translation','sandbox_load');
      await waitFor(()=>operation.contents.executeJavaScript('window.allfoldTranslatorReady.then(()=>{if(window.allfoldTranslatorError)throw Error("Translator initialization failed");return null;})'),
        operation.signal,deadline,'translation','sandbox_init');
      this.current(operation);return operation;
    }catch(error){operation.interrupted=true;await this.endOperation(operation);throw error;}
  }
  endOperation(operation) {
    return operation.ended ||= this.release(operation);
  }
  async release(operation) {
    const {window,contents}=operation;
    const reusable=!operation.signal.aborted && !operation.interrupted;
    operation.controller.abort();operation.cleanup();
    const index=this.pending.indexOf(operation);
    if(index!==-1)this.pending.splice(index,1);
    if(!window)return;
    // Revoke the renderer's authority before draining its native HTTP requests.
    sandboxOperations.delete(contents);
    try {
      // Electron navigation callbacks can trigger this cleanup. Leave their
      // native callback scope before destroying the worker window.
      await new Promise(resolve=>setImmediate(resolve));
      if(!reusable && !window.isDestroyed())window.destroy();
      await Promise.allSettled(operation.requests);
      if(reusable && !window.isDestroyed() && !this.stopped.signal.aborted) {
        // An empty document removes callbacks and operation tokens before reuse.
        await waitFor(()=>window.loadURL('about:blank'),this.stopped.signal,Date.now()+5000,'translation','sandbox_reset');
        this.idle.push(window);
      }
    }catch {
      // Failed reset discards this worker. An unrelated queued request can still run.
    }finally {
      if(!this.idle.includes(window) && !window.isDestroyed())window.destroy();
      this.active.delete(operation);this.dispatch();
    }
  }
  async run(doc,method,args,options) {
    const operation=await this.openOperation(doc,options);
    try {
      return await this.invoke(operation,method,args,options.deadline);
    }finally{await this.endOperation(operation);}
  }
  async invoke(operation,method,args,deadline) {
    try {
      this.current(operation);
      const result=await waitFor(()=>operation.contents.executeJavaScript(
        'window.allfoldTranslator.'+method+'('+JSON.stringify(args)+')'),operation.signal,deadline,'translation','translator');
      this.current(operation);return result;
    }catch(error){operation.interrupted=true;throw error;}
  }
  async completeHistory(source,doi,historyKinds,initial,{signal,deadline,logContext,sourceFrame,translatorID}) {
    const candidates=new Map(initial.map(item=>[item.kind+':'+item.value,item]));
    const missing=()=>historyKinds.some(kind=>![...candidates.values()].some(item=>item.kind===kind));
    const end=Math.min(deadline,Date.now()+30000);
    let operation;
    try {
      // Confirm the live DOI and document even when the original snapshot
      // already supplied both dates while the official Translator was running.
      while(Date.now()<end) {
        const frame=sourceFrame();
        const fresh=await this.browser.snapshot(this.browser.tabs.get(source.pageId),frame,{signal,deadline:end});
        sourceFrame();
        if(!source.documentId || fresh.documentId!==source.documentId || fresh.url!==source.url)
          throw new ImportFailure('translation','document_changed');
        operation ||= await this.openOperation(source,{signal,deadline:end,logContext});
        const observed=await this.invoke(operation,'readHistory',{snapshot:fresh,doi,translatorID},end);
        if(observed.mismatch)throw new ImportFailure('translation','document_changed');
        for(const item of observed.dateCandidates)candidates.set(item.kind+':'+item.value,item);
        if(!missing() || Date.now()>=end)break;
        await pause(signal,Math.min(1250,end-Date.now()));
      }
    } catch(error) {
      checkCanceled(signal);
      if(error.diagnostic?.code!=='timeout')throw error;
    } finally {
      if(operation)await this.endOperation(operation);
    }
    sourceFrame();
    return [...candidates.values()];
  }
  translate(root,doi,options) {
    const running=this.translateDocument(root,doi,options);
    this.translations.add(running);
    return running.finally(()=>this.translations.delete(running));
  }
  async translateDocument(root,doi,{signal,deadline:taskDeadline=Infinity,forEnrichment=false,historyKinds=[],workspaceMetadata,logContext}={}) {
    doi=normalizeDOI(doi);
    const browser=this.browser,contents=browser.tabs?.get(root.pageId)?.view.webContents,lifecycle=new AbortController();
    const owner=browser.operation;
    const activeSignal=AbortSignal.any([lifecycle.signal,this.stopped.signal,...(signal?[signal]:[])]);
    const isCurrent=doc=>documentCurrent(browser,owner,doc);
    const current=()=>{checkCanceled(activeSignal);if(!isCurrent(root))throw new ImportFailure('translation','document_changed');};
    const changed=()=>inBrowserOperation(browser,owner,()=>{
      if(!isCurrent(root))lifecycle.abort(new ImportFailure('translation','document_changed'));
    });
    const closed=()=>lifecycle.abort(new ImportFailure('translation','page_closed'));
    const navigatedFrames=new Set();
    let historySource;
    const navigationStarted=event=>{
      const frame=event.frame;
      const token=frame && !frame.isDestroyed()?frame.frameToken:null;
      const selected=historySource && token===historySource.frameToken;
      const originalURL=event.isMainFrame?root.url:selected?historySource.url:token?frame.url:null;
      // A site's replaceState with the current URL keeps both the document and the route.
      if(event.isSameDocument && event.url===originalURL)return;
      if(token && forEnrichment && historyKinds.length)navigatedFrames.add(token);
      if(event.isMainFrame || selected)
        lifecycle.abort(new ImportFailure('translation','document_changed'));
    };
    contents?.on('did-start-navigation',navigationStarted);
    contents?.on('did-frame-navigate',changed);contents?.once('destroyed',closed);contents?.once('render-process-gone',closed);
    let documents=[root],result,watches=[],frameChanged=false;
    const frameLoaded=()=>{frameChanged=true;};contents?.on('did-frame-finish-load',frameLoaded);
    const failed=result=>{
      const error=result?.error || {};
      if(result?.terminal)throw new ImportFailure('translation',error.code==='timeout'?'timeout':error.code==='document_changed'?'document_changed':'canceled');
    };
    const scan=async(bounded=activeSignal,deadline=taskDeadline)=>{
      do {
        frameChanged=false;current();watches=[];
        documents=await browser.translationDocuments(root,{signal:bounded,deadline});
        const candidates=[];
        let last={ok:false,error:{code:'translator_no_items'}};
        const remember=(doc,value)=>{if(value?.observers?.length)watches.push({doc,configs:value.observers});};
        for(const [index,doc] of documents.entries()) {
          try {
            const detected=await this.run(doc,'detect',{html:doc.html,url:doc.url,rootURL:doc.rootURL},
              {signal:bounded,deadline,logContext});
            failed(detected);remember(doc,detected);
            log('info','translator_detected',{...logContext,stage:'translation',candidate_count:detected.candidates?.length || 0});
            if(!detected.ok)last=detected;
            for(const candidate of detected.candidates || [])candidates.push({doc,candidate,index});
          }catch(error){current();checkCanceled(bounded);if(doc.rootFrameToken&&!isCurrent(doc)){frameChanged=true;continue;}throw error;}
        }
        candidates.sort((a,b)=>a.candidate.priority-b.candidate.priority
          || Number(!!a.doc.rootFrameToken)-Number(!!b.doc.rootFrameToken) || a.index-b.index);
        for(const {doc,candidate} of candidates) {
          try {
            current();
            const cookie=await browser.pageCookie(doc,{signal:bounded,deadline});
            last=await this.run(doc,'translate',{snapshot:doc,candidate,cookie,doi,forEnrichment,historyKinds},
              {signal:bounded,deadline,logContext});
            failed(last);remember(doc,last);
            if(!last.ok)log('warn','translation_attempt_failed',{...logContext,stage:'translation',metadata_source:'web',translator:last.translator,translator_id:last.translatorID,code:last.error?.code || 'translator_failed',status:last.error?.status,transport_code:last.error?.code,net_error:last.error?.net_error,
              error_kind:last.error?.error_kind,error_name:last.error?.error_name,api_name:last.error?.api_name});
            if(last.ok)return {...last,sourceDocument:doc,metadataSource:'web',historyDeadline:deadline};
          }catch(error){current();checkCanceled(bounded);if(doc.rootFrameToken&&!isCurrent(doc)){frameChanged=true;continue;}throw error;}
        }
        result=last;
      }while(frameChanged);
      return result;
    };
    try {
      result=await scan();
      if(!result.ok && watches.length)await withTaskDeadline(activeSignal,'translation',async(bounded,watchDeadline)=>{
        const deadline=Math.min(taskDeadline,watchDeadline);
        while(!result.ok && watches.length) {
          current();const observations=[];
          const watchKey=()=>JSON.stringify(watches.map(({doc,configs})=>({pageId:doc.pageId,frameToken:doc.frameToken,configs})));
          const signature=watchKey();
          try {
            for(const watch of watches) {
              if(!isCurrent(watch.doc))continue;
              try {
                const observation=await browser.observeDOM(watch.doc,watch.configs,{signal:bounded,deadline});
                if(observation)observations.push(observation);
              }catch(error){current();checkCanceled(bounded);if(!isCurrent(watch.doc))continue;throw error;}
            }
            if(!observations.length)break;
            result=await scan(bounded,deadline);
            if(result.ok || !watches.length)break;
            if(watchKey()!==signature || frameChanged)continue;
            let wake;
            const newFrame=new Promise(resolve=>{wake=resolve;contents?.once('did-frame-finish-load',wake);});
            try {
              await waitFor(()=>Promise.race([...observations.map(observation=>observation.changed),newFrame]),bounded,deadline,'translation','dom_observer');
            }catch(error){current();checkCanceled(bounded);if(error.diagnostic?.code!=='document_changed')throw error;}
            finally{contents?.removeListener('did-frame-finish-load',wake);}
          }finally{await Promise.all(observations.map(observation=>observation.dispose()));}
          result=await scan(bounded,deadline);
        }
      });
      current();
      if(!result.ok) {
        const source=documents.find(doc=>doc.type==='application/pdf'&&isCurrent(doc)) || root;
        result=await this.run(source,'searchDOI',{doi,url:source.url,forEnrichment},{signal:activeSignal,deadline:taskDeadline,logContext});
        failed(result);current();
        if(!result.ok)log('warn','translation_attempt_failed',{...logContext,stage:'translation',metadata_source:'doi',code:result.error?.code || 'translator_failed',status:result.error?.status,transport_code:result.error?.code,net_error:result.error?.net_error,
          error_kind:result.error?.error_kind,error_name:result.error?.error_name,api_name:result.error?.api_name});
        if(result.ok)result={...result,sourceDocument:source,metadataSource:'doi'};
        else if(!forEnrichment) {
          const item=workspaceItem(workspaceMetadata,doi);
          if(item)result={ok:true,items:[item],itemCount:1,proxy:result.proxy || null,sourceDocument:source,metadataSource:'workspace'};
        }
      }
      current();
      const details={...logContext,stage:'translation',translator:result.translator,translator_id:result.translatorID,
        item_count:result.itemCount || 0,metadata_source:result.metadataSource,
        ...(result.ok?attachmentCounts(result.items):{})};
      if(!result.ok) {
        const http=['http_status','transport'].includes(result.error?.kind);
        const code=http?'http_error':result.error?.code || 'translator_no_items';
        log('warn','translation_failed',{...details,code,status:result.error?.status,transport_code:result.error?.code,net_error:result.error?.net_error,
          error_kind:result.error?.error_kind,error_name:result.error?.error_name,api_name:result.error?.api_name});
        throw new ImportFailure('translation',code,result.error?.status);
      }
      let dateCandidates=result.dateCandidates;
      if(dateCandidates) {
        historySource=result.sourceDocument;
        const sourceFrame=()=>{
          current();
          if(navigatedFrames.has(historySource.frameToken) || !isCurrent(historySource))
            throw new ImportFailure('translation','document_changed');
          const frame=browser.documentFrame?.(historySource);
          if(frame && frame.url!==historySource.url)throw new ImportFailure('translation','document_changed');
          return frame;
        };
        dateCandidates=await this.completeHistory(historySource,doi,historyKinds,dateCandidates,
          {signal:activeSignal,deadline:result.historyDeadline,logContext,sourceFrame,translatorID:result.translatorID});
      }
      log('info','translation_completed',details);
      return {item:result.items[0],apiItem:result.apiItem,proxy:result.proxy || null,sourceDocument:result.sourceDocument,metadataSource:result.metadataSource,
        dateCandidates,translator:result.translator,translatorID:result.translatorID};
    }finally {
      lifecycle.abort();contents?.removeListener('did-frame-navigate',changed);contents?.removeListener('did-frame-finish-load',frameLoaded);
      contents?.removeListener('destroyed',closed);contents?.removeListener('render-process-gone',closed);
      contents?.removeListener('did-start-navigation',navigationStarted);
    }
  }
  close() {
    if(this.drained)return this.drained;
    this.stopped.abort(new ImportFailure('translation','canceled'));
    for(const window of this.idle.splice(0))if(!window.isDestroyed())window.destroy();
    const operations=[...this.pending,...this.active];
    this.drained=Promise.allSettled([...operations.map(operation=>this.endOperation(operation)),...this.translations]).then(()=>{});
    return this.drained;
  }
}
module.exports={TranslatorSandbox,validateTranslatorURL,workspaceItem};
