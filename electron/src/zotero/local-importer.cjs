'use strict';
// The production writer uses Local API only. Translation stays in its read-only sandbox.
const {LocalAPI,objectKey,validateTarget}=require('./local-api.cjs');
const {requestSessionHTTP}=require('./session-http.cjs');
const {AttachmentDownload,safeAttachmentURL,MAX_ATTACHMENT_BYTES}=require('./attachment-download.cjs');
const {log}=require('../shared/logging.cjs');
const {reconcileImport}=require('./last-import.cjs');
function normalizeDOI(value) {
 const doi=String(value || '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
 if(!/^10\.\d{4,9}\/\S+$/.test(doi))throw Error('Invalid DOI');return doi;
}
function tags(values=[]) {return values.map(value=>typeof value==='object'?value.tag || value.name:value).filter(value=>typeof value==='string'&&value.trim()).map(tag=>({tag,type:1}));}
function apiParent(item,prepared) {
 const parent=prepared?structuredClone(prepared):Object.fromEntries(Object.entries(structuredClone(item)).filter(([key])=>!['attachments','notes','id','itemID','complete','seeAlso','dateAdded','dateModified','version','key','path','date_parts'].includes(key)));
 if(!prepared && parent.creators)parent.creators=parent.creators.map(({creatorType,firstName,lastName,name,fieldMode})=>({creatorType:creatorType || 'author',...((fieldMode===1||!firstName)?{name:name || lastName || ''}:{firstName,lastName:lastName || ''})}));
 parent.tags=tags(item.tags);parent.relations=parent.relations || {};
 if(parent.accessDate==='CURRENT_TIMESTAMP')parent.accessDate=new Date().toISOString();
 delete parent.dateAdded;delete parent.dateModified;return parent;
}
async function saveImportOnce({item,apiItem,doi,doc,browser,signal,target,api,requestHTTP=requestSessionHTTP,fallbackPDF,logContext,resources,deadline,validateRecovery,recordRecovery,recoveryTiming}) {
 if(normalizeDOI(item.DOI)!==normalizeDOI(doi) || typeof item.title!=='string' || !item.title.trim() || typeof item.itemType!=='string' || ['multiple','webpage','attachment','note'].includes(item.itemType))throw Error('Parent does not match target DOI');
 target=validateTarget(target);
 const current=()=>{if(signal?.aborted || !browser.documentCurrent(doc))throw Object.assign(Error('Import canceled or document changed'),{code:signal?.aborted?'canceled':'document_changed'});};
 const result={parent:{outcome:'no_effect'},pdf:{outcome:'unverified',registered:false,source:null,receipts:[],failures:[]},
   zotero:{target,parent_key:null,attachment_keys:[],note_keys:[]},settled:true};
 const write=async operation=>{
   if(!resources)return operation(current);
   try {return await resources.write(signal,current,operation);}
   catch(error){
     if(!error.no_effect)result.uncertain_write=true;
     throw error;
   }
 };
 const record=(error,phase='initial_fetch')=>{
   const {code='failed',status,net_error}=error.diagnostic || error;
   const value={phase,code,...(status?{status}:{})};result.pdf.failures.push(value);
   log('warn','attachment_failure',{...logContext,stage:'attachment',attachment_phase:phase,...value,net_error});
 };
 try {current();await api.validate(target);current();}
 catch(error){result.stop_batch=true;result.diagnostic={stage:'parent_save',code:error.code || 'failed',...(error.status?{status:error.status}:{})};return result;}
 const parentKey=objectKey(),parent={...apiParent(item,apiItem),key:parentKey,version:0,collections:target.collection_key?[target.collection_key]:[]};
 if(normalizeDOI(parent.DOI)!==normalizeDOI(doi))throw Error('Prepared metadata does not match target DOI');
 result.zotero.parent_key=parentKey;
 result.parent={outcome:'uncertain',requested_id:parentKey};
 try {const receipt=await write(beforeDispatch=>api.create(target,parent,{beforeDispatch}));result.parent={outcome:'confirmed',requested_id:parentKey,accepted_id:parentKey,status:receipt.status,protocol:'local-api-v3'};}
 catch(error){if(error.no_effect)result.parent={...result.parent,outcome:'no_effect'};result.stop_batch=true;result.diagnostic={stage:'parent_save',code:error.code || 'failed',...(error.status?{status:error.status}:{})};result.error='Save failed or is uncertain. Inspect Zotero before retrying.';return result;}
 const createChild=async(value,kind,authorizeDispatch)=>{
   current();const key=objectKey();result.zotero[kind].push(key);
   // Once dispatched, never replay or replace this object after any error.
   await write(beforeDispatch=>api.create(target,{...value,key,version:0,parentItem:parentKey,
     tags:value.tags || [],relations:value.relations || {}},{authorizeDispatch,beforeDispatch}));
   return key;
 };
 let attachmentWriteFailed=false;
 for(const note of item.notes || []) {
   try {const text=typeof note==='string'?note:note.note;if(text)await createChild({itemType:'note',note:String(text),tags:tags(note.tags)},'note_keys');}
   catch(error){record(error,'note_save');result.stop_batch=true;attachmentWriteFailed=true;break;}
 }
 let downloader;
 const download=()=>downloader ||= new AttachmentDownload({
   browser,doc,signal,deadline,current,requestHTTP,resources,validateRecovery,recordRecovery,recoveryTiming,
 });
 const saveAttachment=async(attachment,source)=>{
   let downloaded;
   const authorizeDispatch=()=>downloader.authorize({signal,deadline:deadline ?? Infinity,check:current});
   try {
     const attachmentDownload=download();
     downloaded=await attachmentDownload.fetch(attachment,source);
     await authorizeDispatch();
   } catch(error) {
     record(downloader?.terminalError(error) || error,source==='translator'?'initial_fetch':'oa_resolver');
     return false;
   }
   const {bytes,mime,url}=downloaded,isPDF=mime==='application/pdf',filename=isPDF?'paper.pdf':mime==='application/epub+zip'?'paper.epub':'attachment.bin';
   let key;
   try {
     key=await createChild({itemType:'attachment',linkMode:'imported_url',title:attachment.title || (isPDF?'Full Text PDF':'Attachment'),
       url:safeAttachmentURL(attachment._allfoldProperURL || url),contentType:mime,filename},'attachment_keys',authorizeDispatch);
     await write(beforeDispatch=>api.upload(target,key,bytes,{filename,contentType:mime,authorizeDispatch,beforeDispatch}));
     if(isPDF){result.pdf.registered=true;result.pdf.source=source;result.pdf.receipts.push({key,endpoint_completed:true,registered:true,source});}return true;
   }catch(error){attachmentWriteFailed=true;result.stop_batch=true;record(error,key?'attachment_save':'attachment_create');if(isPDF)result.pdf.receipts.push({key:key || result.zotero.attachment_keys.at(-1),endpoint_completed:false,registered:false,source});return false;}
 };
 try {
  let candidates=(item.attachments || []).filter(value=>value && typeof value.url==='string');
  if(doc.type==='application/pdf')candidates=[...candidates.filter(value=>value.mimeType!=='application/pdf'),{url:doc.url,mimeType:'application/pdf',title:'Full Text PDF'}];
  for(const attachment of candidates) {
    if(signal?.aborted || attachmentWriteFailed || downloader?.authorityFailure || !browser.documentCurrent(doc))break;
    const mime=attachment.mimeType || attachment.contentType || '';
    if(attachment.snapshot===false) {
      try {const url=safeAttachmentURL(attachment.url);await createChild({itemType:'attachment',linkMode:'linked_url',...(typeof attachment.note==='string'?{note:attachment.note}:{}),title:attachment.title || 'Link',url:safeAttachmentURL(attachment._allfoldProperURL || url),contentType:mime,tags:tags(attachment.tags),...(attachment.accessDate?{accessDate:attachment.accessDate==='CURRENT_TIMESTAMP'?new Date().toISOString():attachment.accessDate}:{})},'attachment_keys');}
      catch(error){record(error,'attachment_save');result.stop_batch=true;attachmentWriteFailed=true;}
    }else if(mime!=='text/html' && !attachmentWriteFailed) {
      if(mime==='application/pdf' && result.pdf.registered)continue;
      await saveAttachment(attachment,'translator');
    }
  }
  if(!result.pdf.registered && !attachmentWriteFailed && !downloader?.stopped && !signal?.aborted && fallbackPDF) {
    try {
      const fallback=await download().resolveFallback(fallbackPDF,{doi,target,parent_key:parentKey});
      for(const url of [...new Set(fallback?.candidates || [])].slice(0,4)) {if(await saveAttachment({url,mimeType:'application/pdf'},'openalex') || attachmentWriteFailed || downloader.stopped)break;}
      if(fallback?.diagnostic)record(fallback.diagnostic,'oa_resolver');
    }catch(error){record(error,'oa_resolver');}
  }
 } finally {downloader?.dispose();}
 return result;
}
async function saveOnce(options) {
 const api=options.api || new LocalAPI();
 const result=await saveImportOnce({...options,api});
 result.last_import=await reconcileImport(result,{api,doi:options.doi});
 return result;
}
module.exports={saveOnce,normalizeDOI,safeAttachmentURL,apiParent,MAX_ATTACHMENT_BYTES};
