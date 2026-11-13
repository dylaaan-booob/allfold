'use strict';
// Host-initiated fixed observations only. No contextBridge API is exposed to sites.
const {ipcRenderer,webFrame}=require('electron');
const documentId=Array.from(crypto.getRandomValues(new Uint32Array(4))).join('-');
const operations={
  binding() {return {type:document.contentType};},
  access() {
    const title=document.title.slice(0,512);
    const markers={unusualTraffic:/Unusual Traffic Detected\s*\(Error 418\)/i.test(title),
      cloudflareTitle:/^(Just a moment|Attention Required)/i.test(title),
      cloudflareOptions:false,cloudflareOrchestrator:false,robot:false,contentDenied:false,hcaptcha:false,login:false};
    let limited=false;
    const scripts=document.querySelectorAll('script');
    if(scripts.length>256)limited=true;
    for(let i=0;i<Math.min(256,scripts.length);i++) {
      const script=scripts[i],src=script.getAttribute('src') || '';
      if(/\/cdn-cgi\/challenge-platform\/[^\s"'<>]*orchestrate\/chl_page\//i.test(src))markers.cloudflareOrchestrator=true;
      const text=script.textContent || '';
      if(/\b_cf_chl_opt\s*=\s*\{/.test(text.slice(0,16384)))markers.cloudflareOptions=true;
    }
    const nodes=[...document.querySelectorAll('h1,h2,p,[id="error"],[class="error"]'),
      ...[...(document.body?.childNodes || [])].filter(node=>node.nodeType===3)];
    let robot=false,human=false,cpe=false,denied=false;
    if(nodes.length>256)limited=true;
    for(let i=0;i<Math.min(256,nodes.length);i++) {
      const text=(nodes[i].textContent || '').slice(0,2048);
      robot ||= /Are you a robot\?/.test(text);
      human ||= /Please confirm you are a human by completing the captcha challenge/i.test(text);
      cpe ||= /\bCPE00001\b/.test(text);
      denied ||= /There was a problem providing the content you requested/i.test(text);
    }
    markers.robot=robot && human;markers.contentDenied=cpe && denied;
    const frames=document.querySelectorAll('iframe[src]');
    // Resource presence alone never identifies a Cloudflare main challenge.
    for(let i=0;i<Math.min(256,frames.length);i++) {
      try {const url=new URL(frames[i].getAttribute('src'),location.href);
        if(/(^|\.)hcaptcha\.com$/i.test(url.hostname))markers.hcaptcha=true;
      } catch { /* No URL evidence. */ }
    }
    markers.login=[...document.querySelectorAll('input[type="password"],input[autocomplete="one-time-code"]')].some(node=>node.getClientRects().length>0);
    let imperva=null;
    const children=document.body?.children;
    const shell=children?.length>0 && children.length<=32 && [...children].every(node=>node.localName==='iframe')
      && [...document.body.childNodes].every(node=>node.nodeType!==3 || !node.nodeValue.trim());
    if(shell)for(const frame of children) {
      const fallback=frame.textContent || '';
      if(!/^\s*Request unsuccessful\.\s*Incapsula incident ID:/i.test(fallback))continue;
      let url;try {url=new URL(frame.getAttribute('src'),location.href);}catch {continue;}
      if(url.origin!==location.origin || url.pathname!=='/_Incapsula_Resource')continue;
      const params=url.searchParams,codes=params.getAll('edet'),ids=params.getAll('incident_id');
      const displayed=fallback.match(/Incapsula incident ID:\s*([0-9]{1,32}-[0-9]{1,32})(?=\s|$)/i)?.[1];
      imperva={};
      if(codes.length===1 && /^[0-9]{1,3}$/.test(codes[0]))imperva.edet=Number(codes[0]);
      const incident=ids.length?ids[0]:displayed;
      if(ids.length<=1 && /^[0-9]{1,32}-[0-9]{1,32}$/.test(incident) && (!displayed || displayed===incident))imperva.incident=incident;
      break;
    }
    return {markers,imperva,limited};
  },
  article() {
    const keys=new Set(['citation_doi','bepress_citation_doi','prism.doi','dc.identifier','dc.identifier.doi','dcterms.identifier']);
    const values=[];let limited=false;
    const add=value=>{
      if(typeof value!=='string')return;
      if(value.length>1024 || values.length>=32){limited=true;return;}
      values.push(value);
    };
    // Only head scholarly metadata belongs to the main Document, never references/frames.
    for(const node of document.head?.querySelectorAll('meta[content]') || [])
      if(keys.has((node.getAttribute('name') || node.getAttribute('property') || '').toLowerCase()))add(node.getAttribute('content'));
    const peripheral='nav,#references,.references,[role="doc-bibliography"],.related-articles,.recommended-articles';
    const articles=[...document.querySelectorAll('article')].filter(node=>!node.closest(peripheral) && !node.parentElement?.closest('article'));
    const multiple=articles.length>1;
    // Scoped replacement for the historical SciELO DOI locator, without Translator IDs.
    if(/(^|\.)scielo\.(?:br|org|cl|sa\.cr|org\.mx|org\.za)$/i.test(location.hostname))
      for(const node of document.querySelectorAll('article a._doi[href],.article a._doi[href]'))
        if(!node.closest(peripheral))add(node.getAttribute('href'));
    return {values,limited,multiple,article:articles.length===1 || !!document.querySelector('main,[role="main"]')};
  },
};
ipcRenderer.on('document:operation',async(_event,{id,action,expectedDocumentId,expectedURL})=>{
  if(!Object.hasOwn(operations,action))return;
  const url=location.href;
  if(expectedDocumentId && expectedDocumentId!==documentId || expectedURL!==url) {
    ipcRenderer.send('document:result',{id,error:'document_changed'});return;
  }
  try {
    const source=name=>'('+operations[name].toString().replace(/^\w+\(/,'function(')+')()';
    // Access and article facts are observed in one synchronous DOM turn.
    const code=action==='article'?'({access:'+source('access')+',article:'+source('article')+'})':source(action);
    const result=await webFrame.executeJavaScriptInIsolatedWorld(999,[{code}]);
    if(location.href!==url)throw Error('document_changed');
    ipcRenderer.send('document:result',{id,result,documentId,url});
  }catch {ipcRenderer.send('document:result',{id,error:'document_operation_failed'});}
});
