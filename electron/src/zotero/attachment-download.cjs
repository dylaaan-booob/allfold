'use strict';
const {isIP,BlockList}=require('node:net');
const {setTimeout:delay}=require('node:timers/promises');
const {waitFor,timeoutFailure}=require('../browser/browser-task.cjs');

const MAX_ATTACHMENT_BYTES=64*1024*1024;
const REQUEST_TIMEOUT_MS=60000, ATTACHMENT_BUDGET_MS=240000, PDF_ATTEMPTS=3;
const BACKOFF_BASE_MS=500, BACKOFF_JITTER_MS=250;
const COOLDOWN_PENDING=Symbol('cooldown pending');
const TRANSIENT_STATUS=new Set([408,429,500,502,503,504]);
const TRANSIENT_NETWORK=new Set(['ERR_CONNECTION_CLOSED','ERR_CONNECTION_RESET','ERR_CONNECTION_REFUSED',
  'ERR_CONNECTION_TIMED_OUT','ERR_TIMED_OUT','ERR_NETWORK_CHANGED','ERR_TEMPORARILY_THROTTLED']);
// Host compatibility for the locked Connector BotBypass policy, without its writer VM.
const ATTACHMENT_RECOVERY_DOMAINS=['sciencedirect.com','pdf.sciencedirectassets.com','ncbi.nlm.nih.gov'];

const blockedIPv4=new BlockList();
for(const [network,prefix] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],['169.254.0.0',16],
 ['172.16.0.0',12],['192.0.0.0',24],['192.0.2.0',24],['192.168.0.0',16],['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',4],['240.0.0.0',4]])blockedIPv4.addSubnet(network,prefix,'ipv4');
const globalIPv6=new BlockList(),blockedIPv6=new BlockList();globalIPv6.addSubnet('2000::',3,'ipv6');
for(const [network,prefix] of [['2001::',23],['2001:db8::',32],['2002::',16]])blockedIPv6.addSubnet(network,prefix,'ipv6');
const failure=(code,status)=>Object.assign(Error(code),{code,status});
function safeAttachmentURL(value) {
 if(typeof value!=='string' || /[\s\\\x00-\x1f\x7f]/.test(value))throw Object.assign(Error('Unsafe attachment URL'),{code:'unsafe_url'});
 let url;
 try {url=new URL(value);}catch{throw failure('unsafe_url');}
 const host=url.hostname.toLowerCase().replace(/^\[|\]$/g,'').replace(/\.$/,'');
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
   let resolved;
   try {resolved=await session.resolveHost(host);}catch{throw failure('unsafe_url');}
   if(!resolved?.endpoints?.length)throw Object.assign(Error('DNS unavailable'),{code:'unsafe_url'});
   for(const {address} of resolved.endpoints) {
     const family=isIP(address);if(!family)throw Object.assign(Error('Unsafe resolved address'),{code:'unsafe_url'});
     safeAttachmentURL('http://'+(family===6?'['+address+']':address)+'/');
   }
 }
 return normalized;
}

const evidence=error=>error?.diagnostic || error || {};
const header=(response,name)=>response.headers.find(([key])=>key.toLowerCase()===name)?.[1];
const authorityStopped=error=>['canceled','document_changed'].includes(evidence(error).code);
const recoverable=({code,status,net_error})=>code==='timeout'
  || code==='http_error' && TRANSIENT_STATUS.has(status)
  || code==='network_error' && TRANSIENT_NETWORK.has(net_error);

function verifiedBody(response,declaredMime) {
 const {status}=response;
 if(status<200 || status>=300)throw failure('http_error',status);
 const bytes=Buffer.from(response.body);
 if(!bytes.length || bytes.length>MAX_ATTACHMENT_BYTES)throw failure(bytes.length?'response_too_large':'empty_response');
 const length=header(response,'content-length'),encoding=header(response,'content-encoding');
 if(status===206 || header(response,'content-range')
   || (!encoding || encoding.toLowerCase()==='identity') && length!==undefined && (!/^\d+$/.test(length) || Number(length)!==bytes.length))
   throw failure('invalid_response',status);
 const contentType=header(response,'content-type')?.split(';')[0].trim().toLowerCase() || '';
 const mime=declaredMime || contentType;
 if(mime==='application/pdf') {
   if(!['application/pdf','application/octet-stream',''].includes(contentType) || !bytes.subarray(0,1024).includes('%PDF-'))
     throw failure('mime_mismatch');
   if(!/%%EOF[\x00\t\n\f\r ]*$/.test(bytes.subarray(-1024).toString('latin1')))throw failure('invalid_response',status);
 } else if(contentType==='text/html')throw failure('mime_mismatch');
 return {bytes,mime};
}

class AttachmentDownload {
 constructor({browser,doc,signal,deadline=Infinity,current,requestHTTP,resources,validateRecovery,recordRecovery,
   recoveryTiming:{now=Date.now,wait=(ms,signal)=>delay(ms,undefined,{signal}),random=Math.random}={}}) {
   Object.assign(this,{browser,doc,current,requestHTTP,resources,validateRecovery,recordRecovery,now,wait,random});
   this.deadline=Math.min(deadline,now()+ATTACHMENT_BUDGET_MS);
   this.attempts=new Map();
   const budget=new AbortController();
   this.signal=signal?AbortSignal.any([signal,budget.signal]):budget.signal;
   this.timer=setTimeout(()=>budget.abort(timeoutFailure('attachment','download')),Math.max(0,this.deadline-now()));
 }
 dispose() {clearTimeout(this.timer);}
 check=()=>{
   this.current();
   if(this.authorityFailure)throw this.authorityFailure;
   if(this.signal.aborted)throw this.signal.reason;
   if(this.now()>=this.deadline)throw timeoutFailure('attachment','download');
 };
 get stopped() {
   try {this.check();return false;}catch{return true;}
 }
 terminalError(error) {
   try {this.check();return error;}
   catch(stopped){return evidence(stopped).code==='timeout' && evidence(error).status?error:stopped;}
 }
 stopReason(error,fallback='failed') {
   if(evidence(error).code==='canceled')return 'canceled';
   if(authorityStopped(error) || error===this.authorityFailure)return 'authority';
   if(this.stopped || error?.cooldownBudget)return 'budget';
   return fallback;
 }
 report=(event,details)=>{
   try {this.recordRecovery?.(event,{stage:'attachment',step:'download',page_id:this.doc.pageId,...details});}catch{}
 };
 async authorize({signal,deadline,check}={signal:this.signal,deadline:this.deadline,check:this.check}) {
   check();
   try {
     if(this.validateRecovery)await waitFor(()=>this.validateRecovery({signal,deadline,stage:'attachment'}),
       signal,Infinity,'attachment','download');
   } catch(error) {
     this.authorityFailure=error;
     throw error;
   }
   check();
 }
 async readyURL(value,{deadline=this.deadline,report=this.report}={}) {
   const url=safeAttachmentURL(value);
   // A cooldown wait can outlive the authority check and DNS result. Run both when the gate opens.
   const authorize=async()=>{
     await this.authorize();
     await waitFor(()=>validateDownloadURL(this.browser.partition,url),this.signal,Infinity,'attachment','download');
     this.check();
   };
   if(this.browser.cooldown)await this.browser.cooldown.wait(url,{signal:this.signal,deadline,
     authorize,validate:this.check,report,stage:'attachment',step:'download',pageId:this.doc.pageId});
   else await authorize();
   this.check();
 }
 async dispatch(url,operation) {
   if(!this.resources) {
     await this.readyURL(url);
     return operation();
   }
   while(true) {
     const result=await this.resources.download(this.signal,async()=>{
       // Try to admit this request without holding a download permit across a cooldown wait.
       try {await this.readyURL(url,{deadline:this.now(),report:null});}
       catch(error){if(error?.cooldownBudget)return COOLDOWN_PENDING;throw error;}
       return operation();
     });
     if(result!==COOLDOWN_PENDING)return result;
     await this.browser.cooldown.wait(url,{signal:this.signal,deadline:this.deadline,validate:this.check,
       report:this.report,stage:'attachment',step:'download',pageId:this.doc.pageId});
   }
 }
 async resolveFallback(fallbackPDF,context) {
   await this.authorize();
   const result=await waitFor(()=>fallbackPDF({...context,signal:this.signal,deadline:this.deadline}),this.signal,Infinity,'attachment','download');
   this.check();
   return result;
 }
 async get(value,{source,declaredMime,challenge}) {
   const url=safeAttachmentURL(value), canRetry=!declaredMime || declaredMime==='application/pdf';
   const previous=canRetry?this.attempts.get(url):undefined;
   const limit=canRetry?PDF_ATTEMPTS:1;
   let attempt=previous?.attempt || 0,last=previous?.error;
   let retrying=false;
   const report=(event,error,details)=>{
     const {code,status,net_error}=evidence(error);
     const failure_kind=code==='http_error'?[401,403].includes(status)?'access':'remote_service'
       :['network_error','timeout'].includes(code)?'transport':authorityStopped(error)?undefined:'protocol';
     this.report(event,{recovery_action:'pdf_get',code,status,net_error,failure_kind,
       dispatch_outcome:status?'confirmed':'unknown',attempt,attempt_limit:limit,
       remaining_ms:Math.max(0,this.deadline-this.now()),...details});
   };
   while(attempt<limit) {
     let dispatched=false,status,response;
     const observeResponse=(responseURL,responseStatus,headers)=>{
       status=responseStatus;
       const retryAfter=headers.find(([key])=>key.toLowerCase()==='retry-after')?.[1];
       try {this.browser.cooldown?.observe(responseURL,responseStatus,retryAfter);}catch{}
     };
     try {
       response=await this.dispatch(url,()=>{
         this.check();
         dispatched=true;attempt++;
         return this.requestHTTP(this.browser.partition,{method:'GET',url,headers:{},
           referrer:source==='translator'?this.doc.url:undefined,referrerPolicy:'origin-when-cross-origin',
           timeout:Math.min(REQUEST_TIMEOUT_MS,this.deadline-this.now())},
           {doc:this.doc,signal:this.signal,kind:'item-saver',cookieAdapter:this.browser.cookieAdapter,maxBytes:MAX_ATTACHMENT_BYTES,
             validateInitialURL:this.check,validateRedirect:value=>this.readyURL(value),beforeDispatch:this.check,onResponse:observeResponse});
       });
       if(status===undefined)observeResponse(response.url || url,response.status,response.headers);
       this.check();
       const result=verifiedBody(response,declaredMime);
       if(retrying)report('recovery_succeeded',last,{dispatch_outcome:'confirmed'});
       if(canRetry)this.attempts.set(url,{attempt});
       return {...result,url};
     } catch(error) {
       if(!dispatched) {
         const stopped=this.terminalError(error);
         if(retrying)report('recovery_exhausted',stopped,{attempt:attempt+1,dispatch_outcome:'not_dispatched',
           recovery_stop:this.stopReason(stopped)});
         throw stopped;
       }
       const receivedStatus=status>=400 && ['timeout','network_error'].includes(evidence(error).code);
       const stopped=this.terminalError(receivedStatus?failure('http_error',status):error), reason=evidence(stopped);
       last=stopped;
       if(canRetry)this.attempts.set(url,{attempt,error:stopped});
       const retryable=canRetry && recoverable(reason) && !this.stopped;
       if(!retryable || attempt===limit) {
         if(retrying || retryable)report('recovery_exhausted',stopped,{recovery_stop:this.stopReason(stopped,retryable?'limit':'failed')});
         if(response && !this.stopped && challenge(response,reason.code))stopped.challenge=true;
         throw stopped;
       }
       const wait_ms=BACKOFF_BASE_MS*2**(attempt-1)+Math.floor(BACKOFF_JITTER_MS*this.random());
       if(wait_ms>=this.deadline-this.now()) {
         report('recovery_exhausted',stopped,{recovery_stop:'budget'});
         throw stopped;
       }
       retrying=true;
       report('recovery_scheduled',stopped,{attempt:attempt+1,wait_ms});
       try {
         await this.wait(wait_ms,this.signal);
         this.check();
       } catch(error) {
         const stopped=this.terminalError(error);
         report('recovery_exhausted',stopped,{recovery_stop:this.stopReason(stopped)});
         throw stopped;
       }
     }
   }
   throw last || failure('failed');
 }
 async fetch(attachment,source) {
   const originalURL=safeAttachmentURL(attachment.url);
   const declaredMime=attachment.mimeType || attachment.contentType;
   const challenge=(response,code)=>response.status!==404 && (response.status===403 || header(response,'cf-mitigated')==='challenge'
     || code==='mime_mismatch' && [originalURL,attachment._allfoldProperURL].some(attachmentRecoverySite));
   const get=url=>this.get(url,{source,declaredMime,challenge});
   try {return await get(originalURL);}
   catch(error){if(!error.challenge || !this.browser.bypassAttachment)throw error;}
   // A captured URL can be retried, but both helpers still begin at the original challenge URL.
   for(const visible of [false,true]) {
     try {
       const captured=await this.dispatch(originalURL,
         ()=>this.browser.bypassAttachment(originalURL,this.doc,{signal:this.signal,visible,deadline:this.deadline}));
       this.check();
       return await get(captured || originalURL);
     } catch(error) {
       const stopped=this.terminalError(error);
       if(visible || this.stopped || authorityStopped(stopped))throw stopped;
     }
   }
 }
}

module.exports={AttachmentDownload,safeAttachmentURL,MAX_ATTACHMENT_BYTES};
