'use strict';
// Snapshot serialization adapts pinned remoteTranslate.js (AGPL-3.0-or-later).
// Host-initiated fixed operations only. No contextBridge API is exposed to sites.
const {ipcRenderer,webFrame}=require('electron');
const operations={
  snapshot() {
    let html=document.documentElement?.outerHTML || '';
    const allowed=new Set(['base','link','meta','title','style','script','template']);
    const invalid=node=>node.nodeType===1?!allowed.has(node.localName):node.nodeType===3&&!!node.nodeValue.trim();
    if(document.head && [...document.head.childNodes].some(invalid)) {
      const head=document.head.cloneNode(true);
      for(const node of [...head.childNodes])if(invalid(node))node.remove();
      const root=document.documentElement.cloneNode(false).outerHTML,closing='</'+document.documentElement.localName+'>';
      html=root.slice(0,-closing.length)+head.outerHTML+(document.body?.outerHTML || '')+closing;
    }
    return {html,url:location.href,type:document.contentType,title:document.title};
  },
  cookie() {try{return document.cookie;}catch{return '';}},
  observe({id,configs}) {
    globalThis.__allfoldDocumentObservers ||= new Map();
    const observers=[];let complete;
    const promise=new Promise(resolve=>{complete=resolve;});
    const finish=()=>{for(const observer of observers)observer.disconnect();complete();};
    for(const config of configs)try {
      const node=config.selector===null?document:document.querySelector(config.selector);
      if(!node)continue;
      const observer=new MutationObserver(finish);observer.observe(node,config.options);observers.push(observer);
    }catch { /* Invalid or vanished selectors do not establish an observer. */ }
    if(!observers.length)return false;
    globalThis.__allfoldDocumentObservers.set(id,{promise,finish});return true;
  },
  wait({id}) {return globalThis.__allfoldDocumentObservers?.get(id)?.promise;},
  dispose({id}) {
    globalThis.__allfoldDocumentObservers?.get(id)?.finish();globalThis.__allfoldDocumentObservers?.delete(id);
  },
};
ipcRenderer.on('document:operation',async(_event,{id,action,args})=>{
  if(!Object.hasOwn(operations,action))return;
  const operation=operations[action];
  try {
    const result=await webFrame.executeJavaScriptInIsolatedWorld(999,[{code:
      '('+operation.toString().replace(/^\w+\(/,'function(')+')('+JSON.stringify(args || {})+')'}]);
    ipcRenderer.send('document:result',{id,result});
  }catch {ipcRenderer.send('document:result',{id,error:'document_operation_failed'});}
});
