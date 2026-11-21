'use strict';

const pending=new WeakMap();

// Network.getCookies uses this native page's NetworkIsolationKey/SiteForCookies.
// Electron cookies.get includes all partitions but omits their keys. Never merge
// that unqualified list or move cookies between Sessions. This query reads no
// document content, navigates no page, and keeps values within Main.
async function readPartitionCookies(browser,url,sourceURL,{signal,validate=()=>{},page}={}) {
  if(!sourceURL && !page)return null;
  const source=URL.canParse(sourceURL)?new URL(sourceURL).origin:null;
  const current=tab=>{const contents=tab.view.webContents;
    return browser.tabs.get(tab.id)===tab && !tab.closing && contents.session===browser.partition
      && !contents.isDestroyed() && !contents.isCrashed();};
  const tab=(page?[page]:[...(browser.tabs?.values() || [])]).find(tab=>{
    try{return current(tab) && (!source || tab.view.webContents.mainFrame.origin===source);}catch(_){return false;}
  });
  if(!tab)return null;
  const contents=tab.view.webContents,prior=pending.get(contents) || Promise.resolve();
  const run=prior.catch(()=>{}).then(async()=>{
    validate();
    if(!current(tab))return null;
    const client=contents.debugger;
    if(!client || client.isAttached())return null;
    let attached=false;
    const detached=()=>{attached=false;};
    const abort=()=>{if(attached)try{client.detach();}catch(_){}};
    client.on('detach',detached);
    try {
      client.attach('1.3');attached=true;signal?.addEventListener('abort',abort,{once:true});
      validate();
      // Chrome supplies the registrable domain for the committed root even
      // when its URL or renderer changes during the query.
      const site=async()=>{
        const {frameTree:{frame}}=await client.sendCommand('Page.getFrameTree');
        const origin=new URL(frame.securityOrigin);
        if(!['http:','https:'].includes(origin.protocol) || contents.mainFrame.origin!==origin.origin)return null;
        return {origin:origin.origin,key:`${origin.protocol}//${frame.domainAndRegistry || origin.hostname}`};
      };
      const before=await site();
      if(!before || source && before.origin!==source || !current(tab))return null;
      const result=await client.sendCommand('Network.getCookies',{urls:[url]});
      validate();
      if(!current(tab) || !Array.isArray(result.cookies))return null;
      const after=await site();validate();
      if(!current(tab) || after?.key!==before.key)return null;
      // Network.getCookies is inclusive of SameSite. Dispatch applies the
      // actual Chromium request's site relation before sending these cookies.
      return {origin:before.origin,cookies:result.cookies.filter(cookie=>!cookie.partitionKeyOpaque
        && cookie.partitionKey?.topLevelSite===before.key),
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
  const contextOrigin=context.origin && new URL(context.origin);
  const site=Object.entries(headers).find(([name])=>name.toLowerCase()==='sec-fetch-site')?.[1];
  const sameSite=site==='same-site' || site==='same-origin'
    || contextOrigin?.hostname===target.hostname && contextOrigin.protocol===target.protocol;
  const additions=context.cookies.filter(cookie=>cookie.partitionKey && !cookie.partitionKeyOpaque
      && (sameSite || cookie.sameSite==='None')
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
