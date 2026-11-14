'use strict';
const {ipcMain}=require('electron');
const path=require('node:path');
const {PRELOAD_DIR}=require('../shared/paths.cjs');
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('./browser-errors.cjs');
const {waitFor}=require('./browser-task.cjs');
const {boundedPdfClues}=require('./pdf-clues.cjs');
const doiCasefold=Object.freeze(require('./doi-casefold.json'));
// Project each reply through its fixed DTO; never forward arbitrary page-owned properties.
function boundedResult(action,value) {
  const invalid=()=>{throw new BrowserFailure('navigation','page_probe_unconfirmed');};
  if(!value || typeof value!=='object')invalid();
  if(action==='pdf') {
    if(typeof value.subject!=='string'||!/^[0-9:]{1,80}$/.test(value.subject))invalid();
    return {clues:boundedPdfClues(value.clues),subject:value.subject};
  }
  if(action==='extract') {
    const metadata=value.metadata,diagnostics=value.diagnostics;
    if(!metadata || Object.keys(metadata).sort().join(',')!=='abstract,dates' || !Array.isArray(metadata.dates) || metadata.dates.length>256
      || ![null,'string'].includes(metadata.abstract===null?null:typeof metadata.abstract)
      || typeof metadata.abstract==='string' && (!metadata.abstract.trim() || metadata.abstract.length>65536 || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(metadata.abstract))
      || !Array.isArray(diagnostics) || diagnostics.length>4 || diagnostics.some(code=>!['json_ld_invalid','json_ld_ambiguous','abstract_candidate_failed','abstract_budget_exceeded'].includes(code))
      || typeof value.subject!=='string' || !/^[0-9:]{1,80}$/.test(value.subject))invalid();
    const dates=metadata.dates.map(date=>{
      if(!date || Object.keys(date).sort().join(',')!=='precision,value' || typeof date.value!=='string'
        || !/^\d{4}-\d{2}(?:-\d{2})?$/.test(date.value) || date.precision!==(date.value.length===7?'month':'day'))invalid();
      const [year,month,day]=date.value.split('-').map(Number),leap=year%4===0 && (year%100!==0 || year%400===0);
      if(year<1 || month<1 || month>12 || day!==undefined && (day<1 || day>[31,leap?29:28,31,30,31,30,31,31,30,31,30,31][month-1]))invalid();
      return {value:date.value,precision:date.precision};
    });
    const values=dates.map(date=>date.value);
    if(values.some((date,index)=>index && date<=values[index-1]) || dates.some(date=>date.precision==='month' && values.some(value=>value.startsWith(date.value+'-'))))invalid();
    return {metadata:{dates,abstract:metadata.abstract},diagnostics:[...new Set(diagnostics)],subject:value.subject};
  }
  if(action==='binding') {
    if(typeof value.type!=='string' || value.type.length>128)invalid();
    return {type:value.type};
  }
  if(action==='article') {
    const article=value.article;
    if(!article || !Array.isArray(article.values) || article.values.length>32
      || article.values.some(item=>typeof item!=='string' || item.length>1024)
      || !['limited','multiple','article'].every(key=>typeof article[key]==='boolean'))invalid();
    return {access:boundedResult('access',value.access),article:{values:article.values,
      limited:article.limited,multiple:article.multiple,article:article.article,
      ...(typeof article.subject==='string' && /^[0-9:]{1,80}$/.test(article.subject)?{subject:article.subject}:{})}};
  }
  const names=['unusualTraffic','cloudflareTitle','cloudflareOptions','cloudflareOrchestrator','robot','contentDenied','hcaptcha','hcaptchaVisible','login'];
  if(!value.markers || !names.every(key=>typeof value.markers[key]==='boolean'))invalid();
  const markers=Object.fromEntries(names.map(key=>[key,value.markers[key]]));
  let imperva=null;
  if(value.imperva) {
    imperva={};
    if(Number.isInteger(value.imperva.edet) && value.imperva.edet>=0 && value.imperva.edet<=999)imperva.edet=value.imperva.edet;
    if(typeof value.imperva.incident==='string' && /^[0-9]{1,32}-[0-9]{1,32}$/.test(value.imperva.incident))imperva.incident=value.imperva.incident;
  }
  return {markers,imperva};
}
class DocumentRuntime {
  constructor(browser) {
    this.browser=browser;this.pending=new Map();
    this.preload=browser.partition.registerPreloadScript({type:'frame',filePath:path.join(PRELOAD_DIR,'document-preload.cjs')});
    this.listener=(event,message)=>{
      const entry=this.pending.get(message?.id);if(!entry)return;
      const frame=browser.documentFrame(entry.doc);
      if(!frame || event.sender!==browser.tabs.get(entry.doc.pageId)?.view.webContents
        || event.senderFrame?.processId!==entry.doc.processId || event.senderFrame?.frameToken!==entry.doc.frameToken)return;
      if(message.error)entry.reject(new BrowserFailure('navigation',message.error==='document_changed'?'document_changed':'document_operation_failed'));
      else if(typeof message.documentId!=='string' || !/^[0-9-]{7,64}$/.test(message.documentId)
        || message.url!==entry.doc.url || entry.doc.documentId && message.documentId!==entry.doc.documentId)
        entry.reject(new BrowserFailure('navigation','document_changed'));
      else {try {const result=boundedResult(entry.action,message.result);
        if(entry.action==='extract' && !entry.args.wantAbstract && result.metadata.abstract!==null)throw new BrowserFailure('navigation','page_probe_unconfirmed');
        entry.resolve({...result,documentId:message.documentId});}catch(error){entry.reject(error);}}
    };
    ipcMain.on('document:result',this.listener);
  }
  async call(doc,action,args={},options={}) {
    if(!['binding','access','article','extract','pdf'].includes(action))throw new BrowserFailure('navigation','document_operation_failed');
    if(!args || typeof args!=='object' || Array.isArray(args) || (action==='extract'
      ? Object.keys(args).length!==1 || typeof args.wantAbstract!=='boolean' : action==='pdf'?Object.keys(args).length!==1 || ![null,'sciencedirect','ieee','optica','lww','oce'].includes(args.readerKind):Object.keys(args).length!==0))
      throw new BrowserFailure('navigation','document_operation_failed');
    const frame=this.browser.documentFrame(doc);
    if(!frame)throw new BrowserFailure('navigation','document_changed');
    const id=randomBytes(16).toString('hex'),contents=this.browser.tabs.get(doc.pageId).view.webContents;
    let reject;
    const response=new Promise((resolve,no)=>{reject=no;this.pending.set(id,{doc,action,args,resolve,reject:no});});
    const changed=()=>{if(!this.browser.documentCurrent(doc))reject(new BrowserFailure('navigation','document_changed'));};
    const closed=()=>reject(new BrowserFailure('navigation','page_closed'));
    contents.on('did-start-navigation',changed);contents.on('did-navigate-in-page',changed);contents.on('did-frame-navigate',changed);contents.once('destroyed',closed);contents.once('render-process-gone',closed);
    try {
      const result=await waitFor(()=>{frame.send('document:operation',{id,action,args,expectedDocumentId:doc.documentId,expectedURL:doc.url,
        ...(action==='pdf'?{doiCasefold}:{})});return response;},
        options.signal,Math.min(options.deadline ?? Infinity,Date.now()+15000),'navigation','document_operation');
      if(!this.browser.documentCurrent(doc))throw new BrowserFailure('navigation','document_changed');
      return result;
    }finally {
      this.pending.delete(id);contents.removeListener('did-start-navigation',changed);contents.removeListener('did-navigate-in-page',changed);contents.removeListener('did-frame-navigate',changed);
      contents.removeListener('destroyed',closed);contents.removeListener('render-process-gone',closed);
    }
  }
  dispose() {
    for(const entry of this.pending.values())entry.reject(new BrowserFailure('navigation','page_closed'));
    this.pending.clear();ipcMain.removeListener('document:result',this.listener);
    this.browser.partition.unregisterPreloadScript(this.preload);
  }
}
module.exports={DocumentRuntime};
