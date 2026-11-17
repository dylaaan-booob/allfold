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
    if(new URL(location).origin!==source.origin || frame.origin!==source.origin)return null;
    const current=()=>browser.tabs.get(tab.id)===tab && !tab.closing && !contents.isDestroyed() && !contents.isCrashed()
      && contents.session===browser.partition && !contents.isLoadingMainFrame() && contents.getURL()===location
      && tab.documentGeneration===generation && contents.mainFrame.processId===frame.processId
      && contents.mainFrame.frameToken===frame.frameToken && contents.mainFrame.origin===source.origin;
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
      // The query is inclusive of SameSite cookies. Only the actual same-origin
      // top-level document proves Strict/Lax eligibility without a site guess.
      const sameOrigin=new URL(url).origin===source.origin;
      return {cookies:result.cookies.filter(cookie=>cookie.partitionKey && !cookie.partitionKeyOpaque
        && (sameOrigin || cookie.sameSite==='None')),
        metadata:result.cookies.filter(cookie=>!cookie.partitionKey && !Object.hasOwn(cookie,'partitionKeyOpaque'))};
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

function applies(cookie,target) {
  const domain=cookie.domain?.toLowerCase(),base=domain?.replace(/^\./,''),path=cookie.path || '/';
  return (domain?.startsWith('.')?target.hostname===base || target.hostname.endsWith('.'+base):target.hostname===domain)
    && (target.pathname===path || target.pathname.startsWith(path.endsWith('/')?path:path+'/'))
    && (cookie.expires<0 || cookie.expires*1000>Date.now());
}
function withPartitionCookies(headers,url,initialURL,context) {
  const target=new URL(url);
  // Chromium selected Secure/partition eligibility for the initial URL; the
  // qualified source above separately limits SameSite eligibility.
  // Origin changes (including HTTPS downgrades) never inherit these additions.
  if(target.origin!==new URL(initialURL).origin || !context?.cookies.length)return headers;
  const key=Object.keys(headers).find(key=>key.toLowerCase()==='cookie') || 'Cookie';
  const original=String(headers[key] || '').split(';').map(value=>value.trim()).filter(Boolean),present=new Set(original);
  const paths=new Map();
  for(const cookie of context.metadata)if(applies(cookie,target)) {
    const pair=cookie.name+'='+cookie.value;
    paths.set(pair,paths.has(pair)?null:(cookie.path || '/').length);
  }
  // The wire header omits paths. Multiple ordinary descriptors for an identical
  // pair do not prove which one was sent; leave that current credential intact.
  for(const [pair,path] of paths)if(path===null)paths.delete(pair);
  const additions=context.cookies.filter(cookie=>cookie.partitionKey && !cookie.partitionKeyOpaque
      && typeof cookie.name==='string' && typeof cookie.value==='string'
      && !/[\s;=\r\n]/.test(cookie.name) && !/[;\r\n]/.test(cookie.value)
      && applies(cookie,target) && !present.has(cookie.name+'='+cookie.value))
    .sort((a,b)=>(b.path || '/').length-(a.path || '/').length);
  const merged=original.map(pair=>({pair,path:paths.get(pair)}));let changed=false;
  for(const cookie of additions) {
    // A response may have changed the ordinary jar since the query. Unknown
    // same-name metadata must not displace that current ordinary credential.
    if(original.some(pair=>pair.split('=')[0]===cookie.name && !paths.has(pair)))continue;
    const path=(cookie.path || '/').length,index=merged.findIndex(item=>item.path!==undefined && item.path<path);
    merged.splice(index<0?merged.length:index,0,{pair:cookie.name+'='+cookie.value,path});changed=true;
  }
  // Keep ordinary order and ordinary-first ties; insert known longer paths first.
  return changed?{...headers,[key]:merged.map(item=>item.pair).join('; ')}:headers;
}

module.exports={readPartitionCookies,withPartitionCookies};
