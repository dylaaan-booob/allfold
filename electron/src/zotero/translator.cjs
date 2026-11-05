'use strict';
const {BrowserWindow,session,ipcMain,net}=require('electron');
const {RUNTIME_DIR,PRELOAD_DIR}=require('../shared/paths.cjs');
const fs=require('node:fs'),path=require('node:path');
const {pathToFileURL}=require('node:url');
const {randomBytes}=require('node:crypto');
const {normalizeDOI}=require('./local-importer.cjs');
const {ImportFailure}=require('../workflows/import-errors.cjs');
const {withTaskDeadline,waitFor,checkCanceled}=require('../browser/browser-task.cjs');
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
class TranslatorSandbox {
  async init(browser) {
    this.browser=browser;
    const partition=session.fromPartition('allfold-translator');
    partition.setPermissionRequestHandler((_w,_p,callback)=>callback(false));
    partition.protocol.handle('allfold-zotero',request=>{
      const url=new URL(request.url);
      if(url.hostname!=='zotero')return new Response('',{status:403});
      const base=RUNTIME_DIR;
      const file=url.pathname==='/sandbox-adapter.js'?path.join(__dirname,'sandbox-adapter.js')
        :path.resolve(base,'.'+decodeURIComponent(url.pathname));
      if((file!==path.join(__dirname,'sandbox-adapter.js')&&!file.startsWith(base+path.sep))
        || !fs.existsSync(file) || !fs.statSync(file).isFile())return new Response('',{status:404});
      return net.fetch(pathToFileURL(file).href);
    });
    this.window=new BrowserWindow({show:false,webPreferences:{session:partition,
      preload:path.join(PRELOAD_DIR,'sandbox-preload.cjs'),sandbox:true,contextIsolation:true,nodeIntegration:false}});
    this.window.webContents.setWindowOpenHandler(()=>({action:'deny'}));
    this.window.webContents.on('will-navigate',event=>event.preventDefault());
    ipcMain.handle('translator:request',async(event,spec)=>{
      const operation=this.operation;
      if(!operation || spec?.operationId!==operation.id || event.sender!==this.window.webContents
        || event.senderFrame!==event.sender.mainFrame || event.senderFrame.url!==operation.url)
        throw Error('Expired or untrusted Translator operation');
      this.current(operation);
      const {doc,signal,logContext}=operation;
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
        if(!(error instanceof RequestTransportError))throw error;
        return {ok:false,error:{kind:'transport',code:error.code,...(error.net_error?{net_error:error.net_error}:{})}};
      }
    });
    await this.window.loadURL('about:blank');
  }
  current(operation) {
    checkCanceled(operation.signal);
    if(this.operation!==operation || !this.browser.documentCurrent(operation.doc))
      throw new ImportFailure('translation','document_changed');
  }
  async openOperation(doc,{signal,logContext,deadline=Infinity}={}) {
    if(this.operation)throw Error('Translator operation already active');
    const controller=new AbortController(),id=randomBytes(16).toString('hex');
    const operation={id,doc:{...doc},controller,signal:AbortSignal.any([controller.signal,...(signal?[signal]:[])]),logContext,
      url:'allfold-zotero://zotero/offscreen.html?operation='+id};
    this.operation=operation;
    const contents=this.browser.tabs?.get(doc.pageId)?.view.webContents;
    const changed=()=>{if(!this.browser.documentCurrent(doc))controller.abort(new ImportFailure('translation','document_changed'));};
    const closed=()=>controller.abort(new ImportFailure('translation','page_closed'));
    contents?.on('did-frame-navigate',changed);contents?.once('destroyed',closed);contents?.once('render-process-gone',closed);
    operation.cleanup=()=>{contents?.removeListener('did-frame-navigate',changed);contents?.removeListener('destroyed',closed);contents?.removeListener('render-process-gone',closed);};
    try {
      this.current(operation);
      await waitFor(()=>this.window.loadURL(operation.url),operation.signal,deadline,'translation','sandbox_load');
      await waitFor(()=>this.window.webContents.executeJavaScript('window.allfoldTranslatorReady.then(()=>{if(window.allfoldTranslatorError)throw Error("Translator initialization failed");return null;})'),
        operation.signal,deadline,'translation','sandbox_init');
      this.current(operation);return operation;
    }catch(error){await this.endOperation(operation);throw error;}
  }
  async endOperation(operation) {
    operation.controller.abort();operation.cleanup?.();
    if(this.operation!==operation)return;
    this.operation=null;
    if(!this.window.isDestroyed())await this.window.loadURL('about:blank').catch(()=>{});
  }
  async run(doc,method,args,options) {
    const operation=await this.openOperation(doc,options);
    try {
      const result=await waitFor(()=>this.window.webContents.executeJavaScript(
        'window.allfoldTranslator.'+method+'('+JSON.stringify(args)+')'),operation.signal,options.deadline ?? Infinity,'translation','translator');
      this.current(operation);return result;
    }finally{await this.endOperation(operation);}
  }
  async translate(root,doi,{signal,forEnrichment=false,workspaceMetadata,logContext}={}) {
    doi=normalizeDOI(doi);
    const browser=this.browser,contents=browser.tabs?.get(root.pageId)?.view.webContents,lifecycle=new AbortController();
    const activeSignal=AbortSignal.any([lifecycle.signal,...(signal?[signal]:[])]);
    const current=()=>{checkCanceled(activeSignal);if(!browser.documentCurrent(root))throw new ImportFailure('translation','document_changed');};
    const changed=()=>{if(!browser.documentCurrent(root))lifecycle.abort(new ImportFailure('translation','document_changed'));};
    const closed=()=>lifecycle.abort(new ImportFailure('translation','page_closed'));
    contents?.on('did-frame-navigate',changed);contents?.once('destroyed',closed);contents?.once('render-process-gone',closed);
    let documents=[root],result,watches=[],frameChanged=false;
    const frameLoaded=()=>{frameChanged=true;};contents?.on('did-frame-finish-load',frameLoaded);
    const failed=result=>{
      const error=result?.error || {};
      if(result?.terminal)throw new ImportFailure('translation',error.code==='timeout'?'timeout':error.code==='document_changed'?'document_changed':'canceled');
    };
    const scan=async(bounded=activeSignal,deadline=Infinity)=>{
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
          }catch(error){current();checkCanceled(bounded);if(doc.rootFrameToken&&!browser.documentCurrent(doc)){frameChanged=true;continue;}throw error;}
        }
        candidates.sort((a,b)=>a.candidate.priority-b.candidate.priority
          || Number(!!a.doc.rootFrameToken)-Number(!!b.doc.rootFrameToken) || a.index-b.index);
        for(const {doc,candidate} of candidates) {
          try {
            current();
            const cookie=await browser.pageCookie(doc,{signal:bounded,deadline});
            last=await this.run(doc,'translate',{snapshot:doc,candidate,cookie,doi,forEnrichment},
              {signal:bounded,deadline,logContext});
            failed(last);remember(doc,last);
            if(!last.ok)log('warn','translation_attempt_failed',{...logContext,stage:'translation',metadata_source:'web',translator:last.translator,translator_id:last.translatorID,code:last.error?.code || 'translator_failed',status:last.error?.status,transport_code:last.error?.code,net_error:last.error?.net_error,
              error_kind:last.error?.error_kind,error_name:last.error?.error_name,api_name:last.error?.api_name});
            if(last.ok)return {...last,sourceDocument:doc,metadataSource:'web'};
          }catch(error){current();checkCanceled(bounded);if(doc.rootFrameToken&&!browser.documentCurrent(doc)){frameChanged=true;continue;}throw error;}
        }
        result=last;
      }while(frameChanged);
      return result;
    };
    try {
      result=await scan();
      if(!result.ok && watches.length)await withTaskDeadline(activeSignal,'translation',async(bounded,deadline)=>{
        while(!result.ok && watches.length) {
          current();const observations=[];
          const watchKey=()=>JSON.stringify(watches.map(({doc,configs})=>({pageId:doc.pageId,frameToken:doc.frameToken,configs})));
          const signature=watchKey();
          try {
            for(const watch of watches) {
              if(!browser.documentCurrent(watch.doc))continue;
              try {
                const observation=await browser.observeDOM(watch.doc,watch.configs,{signal:bounded,deadline});
                if(observation)observations.push(observation);
              }catch(error){current();checkCanceled(bounded);if(!browser.documentCurrent(watch.doc))continue;throw error;}
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
        const source=documents.find(doc=>doc.type==='application/pdf'&&browser.documentCurrent(doc)) || root;
        result=await this.run(source,'searchDOI',{doi,url:source.url,forEnrichment},{signal:activeSignal,logContext});
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
      log('info','translation_completed',details);this.lastTranslator=result.translator;
      return {item:result.items[0],apiItem:result.apiItem,proxy:result.proxy || null,sourceDocument:result.sourceDocument,metadataSource:result.metadataSource};
    }finally {
      lifecycle.abort();contents?.removeListener('did-frame-navigate',changed);contents?.removeListener('did-frame-finish-load',frameLoaded);
      contents?.removeListener('destroyed',closed);contents?.removeListener('render-process-gone',closed);
    }
  }
  close() {this.operation?.cleanup?.();this.operation?.controller.abort();this.operation=null;ipcMain.removeHandler('translator:request');if(this.window&&!this.window.isDestroyed())this.window.destroy();}
}
module.exports={TranslatorSandbox,validateTranslatorURL,workspaceItem};
