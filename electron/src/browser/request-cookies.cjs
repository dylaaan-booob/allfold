'use strict';

const pending=new WeakMap();

// Network.getCookies uses this native page's NetworkIsolationKey/SiteForCookies.
// Electron cookies.get includes all partitions but omits their keys. Never merge
// that unqualified list or move cookies between Sessions. This query reads no
// document content, navigates no page, and keeps values within Main.
async function readPartitionCookies(browser,url,sourceURL,{signal,validate}={}) {
  if(!sourceURL)return null; // An explicit no-referrer continuation supplies no guessed page context.
  let source;
  try{source=new URL(sourceURL);if(!['http:','https:'].includes(source.protocol))return null;}catch(_){return null;}
  const tab=[...(browser.tabs?.values() || [])].find(tab=>{
    const contents=tab.view.webContents;
    try{return !tab.closing && contents.session===browser.partition && !contents.isDestroyed() && !contents.isCrashed()
      && !contents.isLoadingMainFrame() && new URL(contents.getURL()).origin===source.origin;}catch(_){return false;}
  });
  if(!tab)return null;
  const contents=tab.view.webContents,prior=pending.get(contents) || Promise.resolve();
  const run=prior.catch(()=>{}).then(async()=>{
    validate();
    if(browser.tabs.get(tab.id)!==tab || tab.closing || contents.isDestroyed() || contents.isCrashed()
      || contents.session!==browser.partition || contents.isLoadingMainFrame())return null;
    const location=contents.getURL(),frame=contents.mainFrame,generation=tab.documentGeneration;
    if(new URL(location).origin!==source.origin)return null;
    const current=()=>browser.tabs.get(tab.id)===tab && !tab.closing && !contents.isDestroyed() && !contents.isCrashed()
      && contents.session===browser.partition && !contents.isLoadingMainFrame() && contents.getURL()===location
      && tab.documentGeneration===generation && contents.mainFrame.processId===frame.processId
      && contents.mainFrame.frameToken===frame.frameToken;
    const client=contents.debugger;
    if(!client || client.isAttached())return null;
    let attached=false;
    const detached=()=>{attached=false;};
    const abort=()=>{if(attached)try{client.detach();}catch(_){}};
    client.on('detach',detached);
    try {
      client.attach('1.3');attached=true;signal?.addEventListener('abort',abort,{once:true});
      validate();
      const result=await client.sendCommand('Network.getCookies',{urls:[url]});
      validate();
      if(!current() || !Array.isArray(result.cookies))return null;
      return result.cookies.filter(cookie=>cookie.partitionKey && !cookie.partitionKeyOpaque);
    }catch(_) {validate();return null;}
    finally {
      signal?.removeEventListener('abort',abort);
      try{if(attached && client.isAttached())client.detach();}
      finally{client.removeListener('detach',detached);}
    }
  });
  pending.set(contents,run);
  try{return await run;}
  finally{if(pending.get(contents)===run)pending.delete(contents);}
}

function withPartitionCookies(headers,url,initialURL,cookies=[]) {
  const target=new URL(url);
  // Chromium selected Secure/SameSite/partition eligibility for the initial URL.
  // Origin changes (including HTTPS downgrades) never inherit these additions.
  if(target.origin!==new URL(initialURL).origin)return headers;
  const key=Object.keys(headers).find(key=>key.toLowerCase()==='cookie') || 'Cookie';
  const current=String(headers[key] || ''),present=new Set(current.split(';').map(value=>value.trim()));
  const additions=cookies.filter(cookie=>{
    const domain=cookie.domain?.toLowerCase(),base=domain?.replace(/^\./,'');
    const path=cookie.path || '/';
    return cookie.partitionKey && !cookie.partitionKeyOpaque && typeof cookie.name==='string' && typeof cookie.value==='string'
      && !/[\s;=\r\n]/.test(cookie.name) && !/[;\r\n]/.test(cookie.value)
      && (domain?.startsWith('.')?target.hostname===base || target.hostname.endsWith('.'+base):target.hostname===domain)
      && (target.pathname===path || target.pathname.startsWith(path.endsWith('/')?path:path+'/'))
      && (cookie.expires<0 || cookie.expires*1000>Date.now());
  }).map(cookie=>cookie.name+'='+cookie.value).filter(value=>!present.has(value));
  return additions.length?{...headers,[key]:[...additions,current].filter(Boolean).join('; ')}:headers;
}

module.exports={readPartitionCookies,withPartitionCookies};
