'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {randomBytes} = require('node:crypto');
const {log,errorCode,hostname,attachmentCounts}=require('../shared/logging.cjs');
const {requestSessionHTTP}=require('./session-http.cjs');
const {RUNTIME_DIR:SOURCE}=require('../shared/paths.cjs');
const METHODS = new Set(['saveItems','getSelectedCollection','saveAttachment','hasAttachmentResolvers','saveAttachmentFromResolver']);
function normalizeDOI(value) {
  const doi = String(value || '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
  if (!/^10\.\d{4,9}\/\S+$/.test(doi)) throw Error('Invalid DOI');
  return doi;
}
function verifyParent(id,status,body) {
  return typeof id === 'string' && !!id.trim() && status === 201
    && (body === '' || body === null || (Array.isArray(body?.items) && body.items.length === 1
      && body.items[0].id === id));
}
async function saveOnce({item,proxy,doi,doc,browser,signal,logContext}) {
  const pageURL=doc.url,partition=browser.partition;
  if (normalizeDOI(item.DOI) !== normalizeDOI(doi) || typeof item.title !== 'string' || !item.title.trim() || typeof item.itemType !== 'string'
    || ['multiple','webpage','attachment','note'].includes(item.itemType)) throw Error('Parent does not match target DOI');
  let dispatched = false;
  let parent = {outcome:'no_effect'};
  let parentID;
  const receipts=[],failures=[],seenFailures=new Set();
  const savingItems=[{...structuredClone(item),attachments:structuredClone(item.attachments || [])}];
  let attachmentPhase='initial_fetch';
  const recordFailure=(phase,error,url,status)=>{
    const message=String(error?.message || error || '');
    const code=/no resolvers found/i.test(message)?'no_resolver':/MIME type/i.test(message)?'mime_mismatch':/empty response/i.test(message)?'empty_response':
      error?.kind==='transport'?error.code:Number.isInteger(status)&&status>=400?'http_error':errorCode(error);
    const failure={phase,code,...(Number.isInteger(status)?{status}:{})};
    const key=JSON.stringify([phase,code,status,hostname(url)]);
    if(!seenFailures.has(key)) {
      seenFailures.add(key);failures.push(failure);
      log('warn','attachment_failure',{...logContext,stage:'attachment',attachment_phase:phase,code,status,host:hostname(url)});
    }
  };
  const Zotero = {
    isSafari:false,isFirefox:false,isConnector:true,isBackground:true,isManifestV3:false,version:'5.0',
    debug() {},logError(error) {recordFailure('callback',error);},
    Messaging:{sendMessage() {},addMessageListener() {}},
    Utilities:{deepCopy:value=>structuredClone(value),
      randomString:(len=8)=>randomBytes(len).toString('hex').slice(0,len)},
    Connector_Browser:{getAllCookies:async({url,name})=>
      (await browser.cookieAdapter.read(doc,url,'item-saver')).filter(cookie=>!name || cookie.name===name)},
    Connector:{getPref:async key=>key === 'downloadAssociatedFiles',
      callMethod:async (options,data) => {
        const spec = typeof options === 'string'?{method:options}:options;
        if(signal?.aborted || !browser.documentCurrent(doc))throw Error('Import task canceled or document changed');
        if (!METHODS.has(spec.method)) throw Error('Unsupported local Zotero method');
        if (spec.method === 'saveItems') {
          if (dispatched || data?.items?.length !== 1 || normalizeDOI(data.items[0].DOI) !== normalizeDOI(doi))
            throw Error('Parent save can be dispatched only once for target DOI');
          // The official payload omits binary attachments; count the actual prepared items.
          log('info','attachment_inventory',{...logContext,stage:'attachment',step:'prepared',...attachmentCounts(savingItems)});
          parentID=data.items[0].id; dispatched=true; parent={outcome:'uncertain'};
        }
        const contentType=spec.headers?.['Content-Type'] || 'application/json';
        let response;
        try {
          response=await partition.fetch('http://127.0.0.1:23119/connector/'+spec.method
            +(spec.queryString?'?'+spec.queryString:''),{
            method:data == null?'GET':'POST',redirect:'error',
            headers:{'Content-Type':contentType,'X-Zotero-Version':'5.0',
              'X-Zotero-Connector-API-Version':'3',...spec.headers},
            body:data == null?undefined:contentType === 'application/json'?JSON.stringify(data):data,
            signal:AbortSignal.timeout(spec.timeout || 60000),
          });
          if (spec.method === 'saveItems') parent={outcome:'uncertain',status:response.status};
          const text=await response.text();
          let body=text;
          if (text && (response.headers.get('content-type') || '').includes('application/json')) body=JSON.parse(text);
          if (!response.ok) throw Error('Local Zotero request failed');
          if (spec.method === 'saveItems') {
            if (!verifyParent(parentID,response.status,body)) throw Error('Unattributable parent response');
            parent={outcome:'confirmed',status:201,requested_id:parentID,
              accepted_id:body?.items?.[0]?.id ?? null,empty_response:body === '' || body === null};
          }
          return body;
        } catch (error) {
          if(spec.method!=='saveItems')recordFailure(spec.method==='saveAttachmentFromResolver' || spec.method==='hasAttachmentResolvers'?'oa_resolver':'desktop_attachment',error,undefined,response?.status);
          log('warn','zotero_request_failed',{...logContext,stage:spec.method==='saveItems'?'parent_save':'attachment',
            host:'127.0.0.1',method:spec.method,code:response?(response.ok?'unattributable_response':'http_error'):errorCode(error),status:response?.status});
          // The original ItemSaver falls back to cloud only for status == 0.
          // This host exposes local Desktop only and never reports status 0.
          throw Object.assign(Error('Zotero Desktop failed or its response is uncertain'),{status:response?.status || 503});
        }
      }},
  };
  const context=vm.createContext({Zotero,URL,Date,ArrayBuffer,Uint8Array,TextEncoder,TextDecoder,
    setTimeout,clearTimeout,document:{contentType:doc.type,location:{href:pageURL}}});
  const hostUtilities=Zotero.Utilities;
  vm.runInContext(fs.readFileSync(path.join(SOURCE,'utilities/utilities.js'),'utf8'),context,{filename:'utilities/utilities.js'});
  Object.assign(Zotero.Utilities,hostUtilities);
  vm.runInContext(fs.readFileSync(path.join(SOURCE,'utilities.js'),'utf8'),context,{filename:'utilities.js'});
  vm.runInContext(fs.readFileSync(path.join(SOURCE,'document-compat.js'),'utf8'),context,{filename:'document-compat.js'});
  for(const file of ['translate/tlds.js','proxy.js','botBypass.js'])
    vm.runInContext(fs.readFileSync(path.join(SOURCE,file),'utf8'),context,{filename:file});
  // Both official files keep their own request wrapper and Promise semantics.
  for(const file of ['translate/promise.js','http.js'])
    vm.runInContext(fs.readFileSync(path.join(SOURCE,file),'utf8'),context,{filename:file,timeout:1000});
  Zotero.HTTP._requestXHR=async(method,url,options)=>{
    if(method!=='GET')throw Error('Attachment requires HTTP(S) GET');
    options.headers ||= {};if(options.successCodes===undefined)options.successCodes=null;
    if(options.body!=null)throw Error('HTTP GET cannot have a request body');
    let response;
    try {
      response=await requestSessionHTTP(partition,{method,url,headers:options.headers,
        referrer:options.referrer,timeout:options.timeout},
        {doc,signal,kind:'item-saver',cookieAdapter:browser.cookieAdapter,validateRedirect:value=>{
          const target=new URL(value);
          if(!['http:','https:'].includes(target.protocol) || target.username || target.password)throw Error('Attachment requires HTTP(S) GET without URL credentials');
        }});
      const headers=new Map(response.headers.filter(([key])=>!/^set-cookie2?$/i.test(key))
        .map(([key,value])=>[key.toLowerCase(),value]));
      const xhr={status:response.status,statusText:response.statusText || '',responseURL:response.url,responseType:options.responseType || '',
        getResponseHeader:name=>headers.get(name.toLowerCase()) ?? null,
        getAllResponseHeaders:()=>[...headers].map(([key,value])=>key+': '+value).join('\r\n')};
      log('debug','attachment_http',{...logContext,stage:'attachment',attachment_phase:attachmentPhase,host:hostname(response.url),status:response.status,
        content_type:headers.get('content-type')?.split(';')[0],response_bytes:response.body.length,
        challenge:headers.get('cf-mitigated')==='challenge'?'cf-mitigated':undefined});
      if(options.successCodes===null && (xhr.status<200 || xhr.status>=300)
        || Array.isArray(options.successCodes) && !options.successCodes.includes(xhr.status))
        throw new Zotero.HTTP.StatusError(xhr,url);
      if(options.responseType==='arraybuffer')
        xhr.response=response.body.buffer.slice(response.body.byteOffset,response.body.byteOffset+response.body.byteLength);
      else {
        xhr.responseText=context.LiteratureDocumentCompat.decode(response.body,options.responseCharset || headers.get('content-type')?.match(/charset\s*=\s*["']?([^;\s"']+)/i)?.[1] || 'utf-8');
        xhr.response=options.responseType==='json'?context.LiteratureDocumentCompat.json(xhr.responseText):xhr.responseText;
      }
      return xhr;
    } catch(error) {
      recordFailure(attachmentPhase,error,url,response?.status);
      log('warn','attachment_request_failed',{...logContext,stage:'attachment',host:hostname(url),
        code:error.kind==='transport' || error instanceof Zotero.HTTP.StatusError?'http_error':errorCode(error),transport_code:error.code,net_error:error.net_error,status:response?.status});
      throw error;
    }
  };
  for(const file of ['itemSaver.js','itemSaver_background.js'])
    vm.runInContext(fs.readFileSync(path.join(SOURCE,file),'utf8'),context,{filename:file,timeout:1000});
  const tab=browser.tabs.get(doc.pageId);
  const assertAttachmentCurrent=()=>{
    if(signal?.aborted || !browser.documentCurrent(doc) || browser.tabs.get(doc.pageId)!==tab)
      throw Error('Attachment task canceled or document changed');
  };
  const bypass=async(url,visible)=>{
    const phase=visible?'visible_helper':'hidden_iframe';
    assertAttachmentCurrent();
    log('info','attachment_bypass',{...logContext,stage:'attachment',attachment_phase:phase,host:hostname(url)});
    try{return await browser.bypassAttachment(url,doc,{signal,visible});}
    catch(error){recordFailure(phase,error,url);throw error;}
  };
  Zotero.BotBypass.passJSDetectionViaHiddenIframe=url=>bypass(url,false);
  Zotero.BotBypass.passJSDetectionViaWindowPrompt=url=>bypass(url,true);
  const amazon=Zotero.BotBypass.bypassAmazonCaptcha;
  Zotero.BotBypass.bypassAmazonCaptcha=async function(attachment,options) {
    const previous=attachmentPhase;attachmentPhase='amazon_bypass';
    try{return await amazon.call(this,attachment,options);}
    catch(error){recordFailure('amazon_bypass',error,attachment.url);throw error;}
    finally{attachmentPhase=previous;}
  };
  const validate=Zotero.ItemSaver._validateResponse;
  Zotero.ItemSaver._validateResponse=function(attachment,xhr,...args) {
    const error=validate.call(this,attachment,xhr,...args);
    if(error)recordFailure(attachmentPhase,error,attachment.url,xhr.status);
    return error;
  };
  const saveAttachment=Zotero.ItemSaver.saveAttachmentToZotero;
  Zotero.ItemSaver.saveAttachmentToZotero=async function(attachment,sessionID) {
    assertAttachmentCurrent();
    try{return await saveAttachment.call(this,attachment,sessionID,tab);}
    catch(error){recordFailure('attachment_save',error,attachment.url,error.status);throw error;}
  };
  // Only the outer fetch owns bypass; its recursive re-GET cannot restart it.
  const fetchAttachment=Zotero.ItemSaver._fetchAttachment;let fetching=false;
  Zotero.ItemSaver._fetchAttachment=async function(attachment,sourceTab,attempt=true) {
    assertAttachmentCurrent();
    const nested=fetching,previous=attachmentPhase;attachmentPhase=nested?'refetch':'initial_fetch';fetching=true;
    try{return await fetchAttachment.call(this,attachment,sourceTab,nested?false:attempt);}
    catch(error){recordFailure(attachmentPhase,error,attachment.url,error.status);throw error;}
    finally{fetching=nested;attachmentPhase=previous;}
  };
  const ItemSaver=vm.runInContext('ItemSaver',context);
  const resolver=ItemSaver.prototype.saveAttachmentFromResolver;
  ItemSaver.prototype.saveAttachmentFromResolver=async function(...args) {
    const previous=attachmentPhase;attachmentPhase='oa_resolver';
    try{return await resolver.apply(this,args);}finally{attachmentPhase=previous;}
  };
  const saver=new ItemSaver({sessionID:randomBytes(16).toString('hex'),baseURI:pageURL,itemType:item.itemType,proxy:proxy?new Zotero.Proxy(proxy):null});
  let error;
  try {
    await saver.saveItems(savingItems,
      (attachment,progress,error)=>{
        if(progress===false)recordFailure(attachmentPhase==='oa_resolver' || attachment.isOpenAccess?'oa_resolver':'callback',error,attachment.url,error?.status);
        if (attachment.mimeType === 'application/pdf' && [100,false].includes(progress)) {
          receipts.push({endpoint_completed:progress === 100});
          if(progress===false)log('warn','attachment_failed',{...logContext,stage:'attachment',
            host:hostname(attachment.url),code:'attachment_rejected'});
        }
      });
  } catch (_) {error='Save failed or is uncertain. Inspect Zotero before retrying.';}
  const diagnostic=parent.outcome === 'uncertain'
    ? {stage:'parent_save',code:parent.status?'http_error':'failed',...(parent.status?{status:parent.status}:{})} : null;
  return {parent,pdf:{outcome:'unverified',receipts,failures},...(error?{error}:{}),...(diagnostic?{diagnostic}:{}),settled:true};
}
module.exports={saveOnce,verifyParent,normalizeDOI};
