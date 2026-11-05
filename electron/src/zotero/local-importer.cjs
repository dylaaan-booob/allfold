'use strict';
// The production writer uses Local API only. Translation stays in its read-only sandbox.
const {LocalAPI,objectKey,validateTarget}=require('./local-api.cjs');
const {requestSessionHTTP}=require('./session-http.cjs');
const {isIP,BlockList}=require('node:net');
const {log}=require('../shared/logging.cjs');
const {reconcileImport}=require('./last-import.cjs');
const MAX_ATTACHMENT_BYTES=64*1024*1024;
// Host compatibility for the locked Connector BotBypass policy, without its writer VM.
const ATTACHMENT_RECOVERY_DOMAINS=['sciencedirect.com','pdf.sciencedirectassets.com','ncbi.nlm.nih.gov'];
function normalizeDOI(value) {
 const doi=String(value || '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
 if(!/^10\.\d{4,9}\/\S+$/.test(doi))throw Error('Invalid DOI');return doi;
}
const blockedIPv4=new BlockList();
for(const [network,prefix] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],['169.254.0.0',16],
 ['172.16.0.0',12],['192.0.0.0',24],['192.0.2.0',24],['192.168.0.0',16],['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',4],['240.0.0.0',4]])blockedIPv4.addSubnet(network,prefix,'ipv4');
const globalIPv6=new BlockList(),blockedIPv6=new BlockList();globalIPv6.addSubnet('2000::',3,'ipv6');
for(const [network,prefix] of [['2001::',23],['2001:db8::',32],['2002::',16]])blockedIPv6.addSubnet(network,prefix,'ipv6');
function safeAttachmentURL(value) {
 if(typeof value!=='string' || /[\s\\\x00-\x1f\x7f]/.test(value))throw Object.assign(Error('Unsafe attachment URL'),{code:'unsafe_url'});
 const url=new URL(value),host=url.hostname.toLowerCase().replace(/^\[|\]$/g,'').replace(/\.$/,'');
 const family=isIP(host);
 if(!['http:','https:'].includes(url.protocol) || url.username || url.password
   || !host.includes('.') && !family || /(^|\.)(localhost|local|internal|test|invalid)$/.test(host)
   || family===4 && blockedIPv4.check(host,'ipv4') || family===6 && (!globalIPv6.check(host,'ipv6') || blockedIPv6.check(host,'ipv6')))
   throw Object.assign(Error('Unsafe attachment URL'),{code:'unsafe_url'});
 url.hash='';return url.href;
}
function attachmentRecoverySite(value) {
 try {
   const host=new URL(safeAttachmentURL(value)).hostname;
   return ATTACHMENT_RECOVERY_DOMAINS.some(domain=>host===domain || host.endsWith('.'+domain));
 }catch{return false;}
}
async function validateDownloadURL(session,value) {
 const normalized=safeAttachmentURL(value),host=new URL(normalized).hostname.replace(/^\[|\]$/g,'');
 if(!isIP(host)) {
   if(typeof session?.resolveHost!=='function')throw Object.assign(Error('DNS unavailable'),{code:'unsafe_url'});
   const resolved=await session.resolveHost(host);
   if(!resolved?.endpoints?.length)throw Object.assign(Error('DNS unavailable'),{code:'unsafe_url'});
   for(const {address} of resolved.endpoints) {
     const family=isIP(address);if(!family)throw Object.assign(Error('Unsafe resolved address'),{code:'unsafe_url'});
     safeAttachmentURL('http://'+(family===6?'['+address+']':address)+'/');
   }
 }
 return normalized;
}

function tags(values=[]) {return values.map(value=>typeof value==='object'?value.tag || value.name:value).filter(value=>typeof value==='string'&&value.trim()).map(tag=>({tag,type:1}));}
function apiParent(item,prepared) {
 const parent=prepared?structuredClone(prepared):Object.fromEntries(Object.entries(structuredClone(item)).filter(([key])=>!['attachments','notes','id','itemID','complete','seeAlso','dateAdded','dateModified','version','key','path','date_parts'].includes(key)));
 if(!prepared && parent.creators)parent.creators=parent.creators.map(({creatorType,firstName,lastName,name,fieldMode})=>({creatorType:creatorType || 'author',...((fieldMode===1||!firstName)?{name:name || lastName || ''}:{firstName,lastName:lastName || ''})}));
 parent.tags=tags(item.tags);parent.relations=parent.relations || {};
 if(parent.accessDate==='CURRENT_TIMESTAMP')parent.accessDate=new Date().toISOString();
 delete parent.dateAdded;delete parent.dateModified;return parent;
}
async function saveImportOnce({item,apiItem,doi,doc,browser,signal,target,api,requestHTTP=requestSessionHTTP,fallbackPDF,logContext}) {
 if(normalizeDOI(item.DOI)!==normalizeDOI(doi) || typeof item.title!=='string' || !item.title.trim() || typeof item.itemType!=='string' || ['multiple','webpage','attachment','note'].includes(item.itemType))throw Error('Parent does not match target DOI');
 target=validateTarget(target);
 const current=()=>{if(signal?.aborted || !browser.documentCurrent(doc))throw Object.assign(Error('Import canceled or document changed'),{code:signal?.aborted?'canceled':'document_changed'});};
 const result={parent:{outcome:'no_effect'},pdf:{outcome:'unverified',registered:false,source:null,receipts:[],failures:[]},
   zotero:{target,parent_key:null,attachment_keys:[],note_keys:[]},settled:true};
 const record=(error,phase='initial_fetch')=>{const value={phase,code:error.code || 'failed',...(error.status?{status:error.status}:{})};result.pdf.failures.push(value);log('warn','attachment_failure',{...logContext,stage:'attachment',attachment_phase:phase,...value});return value;};
 try {current();await api.validate(target);current();}
 catch(error){result.stop_batch=true;result.diagnostic={stage:'parent_save',code:error.code || 'failed',...(error.status?{status:error.status}:{})};return result;}
 const parentKey=objectKey(),parent={...apiParent(item,apiItem),key:parentKey,version:0,collections:target.collection_key?[target.collection_key]:[]};
 if(normalizeDOI(parent.DOI)!==normalizeDOI(doi))throw Error('Prepared metadata does not match target DOI');
 result.zotero.parent_key=parentKey;
 result.parent={outcome:'uncertain',requested_id:parentKey};
 try {const receipt=await api.create(target,parent,{beforeDispatch:current});result.parent={outcome:'confirmed',requested_id:parentKey,accepted_id:parentKey,status:receipt.status,protocol:'local-api-v3'};}
 catch(error){if(error.no_effect)result.parent={...result.parent,outcome:'no_effect'};result.stop_batch=true;result.diagnostic={stage:'parent_save',code:error.code || 'failed',...(error.status?{status:error.status}:{})};result.error='Save failed or is uncertain. Inspect Zotero before retrying.';return result;}
 const createChild=async(value,kind)=>{
   current();const key=objectKey();result.zotero[kind].push(key);
   // Once dispatched, never replay or replace this object after any error.
   await api.create(target,{...value,key,version:0,parentItem:parentKey,tags:value.tags || [],relations:value.relations || {}},{beforeDispatch:current});return key;
 };
 let attachmentWriteFailed=false;
 for(const note of item.notes || []) {
   try {const text=typeof note==='string'?note:note.note;if(text)await createChild({itemType:'note',note:String(text),tags:tags(note.tags)},'note_keys');}
   catch(error){record(error,'note_save');result.stop_batch=true;attachmentWriteFailed=true;break;}
 }
 const fetchAttachment=async(attachment,source)=>{
   const originalURL=await validateDownloadURL(browser.partition,attachment.url);
   let url=originalURL;
   // Preserve the locked Connector attachment download's 60-second total timeout.
   const get=()=>{current();return requestHTTP(browser.partition,{method:'GET',url,headers:{},referrer:source==='translator'?doc.url:undefined,
     referrerPolicy:'origin-when-cross-origin',timeout:60000},
     {doc,signal,kind:'item-saver',cookieAdapter:browser.cookieAdapter,maxBytes:MAX_ATTACHMENT_BYTES,maxRedirects:8,
       validateRedirect:value=>validateDownloadURL(browser.partition,value)});};
   let response=await get();
   const contentType=()=>response.headers.find(([key])=>key.toLowerCase()==='content-type')?.[1]?.split(';')[0]?.trim().toLowerCase() || '';
   const downloaded=()=>{
     current();
     if(response.status<200 || response.status>=300)throw Object.assign(Error('Download failed'),{code:'http_error',status:response.status});
     const bytes=Buffer.from(response.body),mime=attachment.mimeType || attachment.contentType || contentType();
     if(!bytes.length || bytes.length>MAX_ATTACHMENT_BYTES)throw Object.assign(Error('Attachment size invalid'),{code:bytes.length?'response_too_large':'empty_response'});
     if(mime==='application/pdf' && (!bytes.subarray(0,1024).includes(Buffer.from('%PDF-')) || !['application/pdf','application/octet-stream',''].includes(contentType()))
       || mime!=='application/pdf' && contentType()==='text/html')throw Object.assign(Error('Attachment content invalid'),{code:'mime_mismatch'});
     return {bytes,mime,url};
   };
   let downloadError;
   try {return downloaded();}catch(error){current();downloadError=error;}
   // Retain task-bound challenge helpers, with one hidden and one visible attempt.
   if(response.status!==404 && (response.status===403
     || response.headers.some(([key,value])=>key.toLowerCase()==='cf-mitigated'&&value==='challenge')
     || [originalURL,attachment._allfoldProperURL].some(attachmentRecoverySite))) {
     for(const visible of [false,true]) {
       current();
       try {
         const captured=await browser.bypassAttachment?.(originalURL,doc,{signal,visible});
         current();
         url=await validateDownloadURL(browser.partition,captured || originalURL);
         response=await get();
         return downloaded();
       }catch(error) {current();if(visible || ['canceled','document_changed'].includes(error.code))throw error;}
     }
   }
   throw downloadError;
 };
 const saveAttachment=async(attachment,source)=>{
   let downloaded;try{downloaded=await fetchAttachment(attachment,source);}catch(error){record(error,source==='translator'?'initial_fetch':'oa_resolver');return false;}
   const {bytes,mime,url}=downloaded,isPDF=mime==='application/pdf',filename=isPDF?'paper.pdf':mime==='application/epub+zip'?'paper.epub':'attachment.bin';
   let key;
   try {
     key=await createChild({itemType:'attachment',linkMode:'imported_url',title:attachment.title || (isPDF?'Full Text PDF':'Attachment'),url:safeAttachmentURL(attachment._allfoldProperURL || url),contentType:mime,filename},'attachment_keys');
     current();await api.upload(target,key,bytes,{filename,contentType:mime,beforeDispatch:current});
     if(isPDF){result.pdf.registered=true;result.pdf.source=source;result.pdf.receipts.push({key,endpoint_completed:true,registered:true,source});}return true;
   }catch(error){attachmentWriteFailed=true;result.stop_batch=true;record(error,key?'attachment_save':'attachment_create');if(isPDF)result.pdf.receipts.push({key:key || result.zotero.attachment_keys.at(-1),endpoint_completed:false,registered:false,source});return false;}
 };
 let candidates=(item.attachments || []).filter(value=>value && typeof value.url==='string');
 if(doc.type==='application/pdf')candidates=[...candidates.filter(value=>value.mimeType!=='application/pdf'),{url:doc.url,mimeType:'application/pdf',title:'Full Text PDF'}];
 for(const attachment of candidates) {
   if(signal?.aborted || attachmentWriteFailed)break;
   const mime=attachment.mimeType || attachment.contentType || '';
   if(attachment.snapshot===false) {
     try {const url=safeAttachmentURL(attachment.url);await createChild({itemType:'attachment',linkMode:'linked_url',...(typeof attachment.note==='string'?{note:attachment.note}:{}),title:attachment.title || 'Link',url:safeAttachmentURL(attachment._allfoldProperURL || url),contentType:mime,tags:tags(attachment.tags),...(attachment.accessDate?{accessDate:attachment.accessDate==='CURRENT_TIMESTAMP'?new Date().toISOString():attachment.accessDate}:{})},'attachment_keys');}
     catch(error){record(error,'attachment_save');result.stop_batch=true;attachmentWriteFailed=true;}
   }else if(mime!=='text/html' && !attachmentWriteFailed) {
     if(mime==='application/pdf' && result.pdf.registered)continue;
     await saveAttachment(attachment,'translator');
   }
 }
 if(!result.pdf.registered && !attachmentWriteFailed && !signal?.aborted && fallbackPDF) {
   try {current();const fallback=await fallbackPDF({doi,target,parent_key:parentKey});
     for(const url of [...new Set(fallback?.candidates || [])].slice(0,4)) {if(await saveAttachment({url,mimeType:'application/pdf'},'openalex') || attachmentWriteFailed || signal?.aborted)break;}
     if(fallback?.diagnostic)record(fallback.diagnostic,'oa_resolver');
   }catch(error){record(error,'oa_resolver');}
 }
 return result;
}
async function saveOnce(options) {
 const api=options.api || new LocalAPI();
 const result=await saveImportOnce({...options,api});
 result.last_import=await reconcileImport(result,{api,doi:options.doi});
 return result;
}
module.exports={saveOnce,normalizeDOI,safeAttachmentURL,apiParent,MAX_ATTACHMENT_BYTES};
