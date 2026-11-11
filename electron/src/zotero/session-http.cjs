'use strict';
class RequestTransportError extends Error {
  constructor(code,error) {
    super(code==='timeout'?'Session HTTP request timed out':code==='redirect_rejected'
      ?'Redirect target rejected':'Session HTTP request failed');
    this.kind='transport';this.code=code;
    const native=String(error?.message || '').match(/\bERR_[A-Z0-9_]{1,80}\b/)?.[0];
    if(native)this.net_error=native;
  }
}
function normalizeReferrer(value) {
  try {
    const url=new URL(value);
    if(!['http:','https:'].includes(url.protocol) || url.username || url.password)return;
    url.hash='';return url.href;
  }catch{return undefined;}
}
// Raw Chromium transport; callers retain Zotero status handling and decoding.
async function requestSessionHTTP(session,{method,url,headers={},body,referrer,referrerPolicy,timeout},context={}) {
  if(!session)throw Error('HTTP request requires a Session');
  const {net}=require('electron');
  const redirectFailure=error=>error?.diagnostic?.stage==='attachment'
    ?error:new RequestTransportError('redirect_rejected',error);
  let initialURL;
  try {
    initialURL=new URL(url);
    const checked=(context.validateInitialURL || context.validateRedirect)?.(initialURL.href);
    if(checked?.then)await checked;
  } catch(error){throw redirectFailure(error);}
  context.beforeDispatch?.();
  const requestHeaders={...headers};let candidateCookieHeader,authorization;
  // Helpers run in an offscreen document; its origin is never a site Referer.
  referrer=normalizeReferrer(referrer);let headerReferrer;
  for(const key of Object.keys(requestHeaders)) {
    if(key.toLowerCase()==='x-allfold-http-context')delete requestHeaders[key];
    if(key.toLowerCase()==='cookie'){candidateCookieHeader=String(requestHeaders[key]);delete requestHeaders[key];}
    if(context.cookieAdapter && key.toLowerCase()==='authorization'){authorization=String(requestHeaders[key]);delete requestHeaders[key];}
    if(key.toLowerCase()==='referer') {
      headerReferrer=normalizeReferrer(requestHeaders[key]) || headerReferrer;delete requestHeaders[key];
    }
  }
  referrer ||= headerReferrer;
  // Electron requires the initial Referer to already satisfy its native policy.
  if(referrer && referrerPolicy==='origin-when-cross-origin' && new URL(referrer).origin!==initialURL.origin)
    referrer=new URL(referrer).origin+'/';
  if(referrer)requestHeaders.Referer=referrer;
  if(typeof body==='string' && !Object.keys(requestHeaders).some(key=>key.toLowerCase()==='content-type'))
    requestHeaders['Content-Type']='text/plain;charset=UTF-8';
  const deadline=timeout?Date.now()+timeout:Infinity;
  const registration=context.cookieAdapter?.register({session,doc:context.doc,kind:context.kind,candidateCookieHeader,authorization,url:initialURL.href,deadline});
  Object.assign(requestHeaders,registration?.headers);
  let request,timer,abort,finished=false,responseURL=initialURL.href;
  try {
    // Chromium applies the caller's attachment policy at every redirect hop.
    // Other Translator requests retain their existing explicit referrer behavior.
    try {request=net.request({url:initialURL.href,method,session,headers:requestHeaders,credentials:'include',redirect:'manual',
      ...(referrer?{referrerPolicy:referrerPolicy || 'unsafe-url'}:{})});}
    catch(error){throw new RequestTransportError('network_error',error);}
    return await new Promise((resolve,reject)=>{
      const fail=error=>{
        if(finished)return;finished=true;reject(error);request.abort();
      };
      const networkFailure=error=>fail(new RequestTransportError('network_error',error));
      request.on('error',networkFailure);
      request.on('redirect',(_status,_method,target)=>{
        if(finished)return;
        try {
          const follow=()=>{
            if(finished)return;
            context.beforeDispatch?.();
            registration?.redirect(target);responseURL=target;request.followRedirect();
          };
          const checked=context.validateRedirect?.(target);
          if(checked?.then)Promise.resolve(checked).then(follow).catch(error=>fail(redirectFailure(error)));
          else follow();
        } catch(error){fail(redirectFailure(error));}
      });
      request.on('response',incoming=>{
        if(finished)return;
        const headers=Object.entries(incoming.headers).map(([key,value])=>[key,Array.isArray(value)?value.join(', '):value]);
        try {context.onResponse?.(responseURL,incoming.statusCode,headers);}catch{}
        const chunks=[];let size=0;
        incoming.on('data',chunk=>{if(finished)return;size+=chunk.length;
          if(context.maxBytes && size>context.maxBytes){fail(new RequestTransportError('response_too_large'));return;}chunks.push(chunk);});
        incoming.once('error',networkFailure);
        incoming.once('aborted',()=>{
          if(context.kind==='item-saver')fail(new RequestTransportError('invalid_response'));
          else networkFailure();
        });
        incoming.once('end',()=>{
          if(finished)return;finished=true;
          resolve({status:incoming.statusCode,statusText:incoming.statusMessage || '',url:responseURL,body:Buffer.concat(chunks),
            headers});
        });
      });
      abort=()=>fail(new RequestTransportError('canceled'));
      context.signal?.addEventListener('abort',abort,{once:true});
      if(context.signal?.aborted){abort();return;}
      if(timeout)timer=setTimeout(()=>fail(new RequestTransportError('timeout')),timeout);
      try {if(body!=null)request.write(body instanceof ArrayBuffer?Buffer.from(body):body);request.end();}
      catch(error){networkFailure(error);}
    });
  } finally {clearTimeout(timer);context.signal?.removeEventListener('abort',abort);registration?.release();}
}
module.exports={requestSessionHTTP,RequestTransportError};
