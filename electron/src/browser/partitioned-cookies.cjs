'use strict';
const {randomBytes}=require('node:crypto');
const MARKER='X-ALLFOLD-HTTP-Context';
function mergeCookies(ordinary,partitioned) {
  const pairs=[],seen=new Set();
  const append=(name,value)=>{
    const key=JSON.stringify([name,value]);
    if(!seen.has(key)){seen.add(key);pairs.push(name+'='+value);}
  };
  for(const text of String(ordinary || '').split(';')) {
    const at=text.indexOf('=');if(at<1)continue;
    append(text.slice(0,at).trim(),text.slice(at+1).trim());
  }
  for(const cookie of partitioned)append(cookie.name,cookie.value);
  return pairs.join('; ');
}
class PartitionedCookieAdapter {
  constructor({session,cdpURL,getPage,documentCurrent}) {
    Object.assign(this,{session,cdpURL,getPage,documentCurrent});
    this.tokens=new Map();this.ids=new Map();this.queries=new Set();
  }
  current(doc) {
    try {return !!doc && this.documentCurrent(doc) && this.getPage(doc.pageId)?.session===this.session;}
    catch {return false;}
  }
  async read(doc,url,kind,deadline=Infinity,owner) {
    if(!this.cdpURL || !this.current(doc) || deadline<=Date.now())return [];
    let endpoint,target;
    try {
      endpoint=new URL(this.cdpURL);
      if(endpoint.protocol!=='ws:' || endpoint.hostname!=='127.0.0.1' || !endpoint.port
        || !/^\/devtools\/browser\/[a-f0-9-]+$/i.test(endpoint.pathname))return [];
      target=this.getPage(doc.pageId).getOrCreateDevToolsTargetId();
    } catch {return [];}
    let socket,timer,sessionId;
    const pending=new Map();let nextId=0;
    const query={cancel:()=>{}};this.queries.add(query);owner?.queries.add(query);
    try {
      socket=new WebSocket(endpoint.href);
      const canceled=new Promise((_,reject)=>{query.cancel=()=>reject(Error('Cookie query ended'));});
      const timed=new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('Cookie query deadline')),Math.min(2000,deadline-Date.now()));});
      const call=(method,params={},attached)=>new Promise((resolve,reject)=>{
        const id=++nextId;pending.set(id,{resolve,reject});
        socket.send(JSON.stringify({id,method,params,...(attached?{sessionId:attached}:{})}));
      });
      const operation=(async()=>{
        await new Promise((resolve,reject)=>{
          socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',()=>reject(Error('CDP unavailable')),{once:true});
          socket.addEventListener('close',()=>{
            reject(Error('CDP closed'));for(const item of pending.values())item.reject(Error('CDP closed'));
          },{once:true});
          socket.addEventListener('message',event=>{
            try {
              const result=JSON.parse(event.data),item=pending.get(result.id);if(!item)return;
              pending.delete(result.id);if(result.error)item.reject(Error('CDP query failed'));else item.resolve(result.result);
            } catch {query.cancel();}
          });
        });
        sessionId=(await call('Target.attachToTarget',{targetId:target,flatten:true})).sessionId;
        const result=await call('Network.getCookies',{urls:[url]},sessionId);
        if(!this.current(doc) || owner && !owner.active)return [];
        return result.cookies.filter(cookie=>cookie.partitionKey);
      })();
      return await Promise.race([operation,canceled,timed]);
    } catch {return [];}
    finally {
      clearTimeout(timer);this.queries.delete(query);owner?.queries.delete(query);
      try {if(socket?.readyState===WebSocket.OPEN) {
        if(sessionId)socket.send(JSON.stringify({id:++nextId,method:'Target.detachFromTarget',params:{sessionId}}));
        socket.close();
      } else if(socket?.readyState===WebSocket.CONNECTING)socket.close();}catch {}
      for(const item of pending.values())item.reject(Error('Cookie query ended'));
    }
  }
  register({session,doc,kind,candidateCookieHeader,authorization,url,deadline}) {
    if(session!==this.session || !['translator','item-saver'].includes(kind))throw Error('Invalid HTTP context');
    const token=randomBytes(24).toString('hex');
    const entry={doc:{pageId:doc.pageId,processId:doc.processId,frameToken:doc.frameToken,rootProcessId:doc.rootProcessId,rootFrameToken:doc.rootFrameToken},kind,
      candidateCookieHeader:kind==='translator'?candidateCookieHeader:undefined,authorization,url,credentialsRemoved:false,deadline,active:true,ids:new Set(),queries:new Set()};
    this.tokens.set(token,entry);
    return {headers:{[MARKER]:token},redirect:target=>{
      if(entry.url && new URL(target).origin!==new URL(entry.url).origin){
        entry.credentialsRemoved=true;entry.candidateCookieHeader=undefined;entry.authorization=undefined;
      }
      entry.url=target;
    },release:()=>{
      entry.active=false;entry.candidateCookieHeader=undefined;entry.authorization=undefined;
      this.tokens.delete(token);for(const id of entry.ids)this.ids.delete(id);
      for(const query of entry.queries)query.cancel();
    }};
  }
  async merge(details,headers) {
    const result={...headers};let token;
    for(const key of Object.keys(result))if(key.toLowerCase()===MARKER.toLowerCase()){token=result[key];delete result[key];}
    const bound=this.ids.get(details.id),entry=token?this.tokens.get(token):bound;
    if(!entry?.active || bound && bound!==entry)return result;
    if(token){this.ids.set(details.id,entry);entry.ids.add(details.id);}
    const cookies=await this.read(entry.doc,details.url,entry.kind,entry.deadline,entry);
    if(!entry.active || !this.current(entry.doc))return result;
    if(entry.authorization!==undefined || entry.credentialsRemoved)
      for(const key of Object.keys(result))if(key.toLowerCase()==='authorization')delete result[key];
    if(!entry.credentialsRemoved && entry.authorization!==undefined)result.Authorization=entry.authorization;
    const cookieKey=Object.keys(result).find(key=>key.toLowerCase()==='cookie');
    const ordinary=cookieKey?result[cookieKey]:'';
    const explicit=entry.candidateCookieHeader || '';
    const merged=mergeCookies([ordinary,explicit].filter(Boolean).join('; '),cookies);
    if(cookieKey)result[cookieKey]=merged;else if(merged)result.Cookie=merged;
    return result;
  }
  dispose() {
    for(const entry of this.tokens.values()){entry.active=false;entry.candidateCookieHeader=undefined;entry.authorization=undefined;}
    this.tokens.clear();this.ids.clear();for(const query of this.queries)query.cancel();
  }
}
module.exports={PartitionedCookieAdapter,mergeCookies,MARKER};
