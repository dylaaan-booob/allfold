'use strict';
// Only authenticated application dispatch can supply this attempt capability.
// PDF bytes remain in Main: Web stream -> Node pipeline -> verified file fd.
const fs=require('node:fs'),path=require('node:path'),dns=require('node:dns/promises');
const {BlockList,isIP}=require('node:net');
const {Readable,Transform}=require('node:stream');
const {pipeline}=require('node:stream/promises');
const {publicClueURL}=require('../browser/pdf-clues.cjs');
const {readPartitionCookies}=require('../browser/request-cookies.cjs');
const {checkCanceled,timeoutFailure,waitFor}=require('../browser/browser-task.cjs');
const {BrowserFailure}=require('../browser/browser-errors.cjs');
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const same=(info,pair)=>Array.isArray(pair)&&pair.length===2&&info.dev===pair[0]&&info.ino===pair[1];
const failure=code=>Object.assign(Error(code),{bodyLocal:true});
function capability(data) {
  const output=data.output;
  if(!UUID.test(data.paper_id)||!Number.isSafeInteger(data.attempt)||data.attempt<1||!output
    ||!path.isAbsolute(data.workspace_root)||path.normalize(data.workspace_root)!==data.workspace_root
    ||output.temporary!==`Documents/.downloads/${data.paper_id}.${data.attempt}.part`
    ||output.target!==`Documents/${data.paper_id}.pdf`||!Number.isSafeInteger(data.deadline_ms))throw failure('invalid-output');
  return output;
}
function directories(root,output) {
  // No writes through a pathname: after opening, fstat must prove the exact
  // exclusively created inode. Directory replacement cannot redirect that fd.
  try {
  let current=path.parse(root).root;
  for(const part of path.relative(current,root).split(path.sep).filter(Boolean)) {
    current=path.join(current,part);const info=fs.lstatSync(current);
    if(!info.isDirectory()||info.isSymbolicLink())throw failure('output-directory');
  }
  for(const [name,pair] of [[root,output.workspace],[path.join(root,'Documents'),output.documents],
    [path.join(root,'Documents/.downloads'),output.staging]]) {
    const info=fs.lstatSync(name);if(!info.isDirectory()||!same(info,pair))throw failure('output-directory');
  }
  }catch(error){error.bodyLocal=true;throw error;}
}
function openOutput(root,output) {
  directories(root,output);
  const filename=path.join(root,output.temporary);
  const prior=fs.lstatSync(filename);
  if(!prior.isFile()||prior.nlink!==1||!same(prior,output.file)||prior.size!==0)throw failure('output-object');
  // Darwin O_NOFOLLOW_ANY (sys/fcntl.h): refuse symlinks in every component.
  const fd=fs.openSync(filename,fs.constants.O_WRONLY|fs.constants.O_NONBLOCK|(process.platform==='darwin'?0x20000000:fs.constants.O_NOFOLLOW));
  try {
    const actual=fs.fstatSync(fd);
    if(!actual.isFile()||actual.nlink!==1||actual.size!==0||!same(actual,output.file))throw failure('output-object');
    directories(root,output);
    return fd;
  }catch(error){fs.closeSync(fd);throw error;}
}
// Exact special-purpose ranges matching the pinned Python ipaddress.is_global
// policy used by PdfHttpClient. BlockList also handles IPv4-mapped IPv6 forms.
const nonGlobal=new BlockList(),globalExceptions=new BlockList();
for(const [address,prefix] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],
  ['169.254.0.0',16],['172.16.0.0',12],['192.0.0.0',24],['192.0.2.0',24],['192.168.0.0',16],
  ['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['240.0.0.0',4]])nonGlobal.addSubnet(address,prefix,'ipv4');
for(const address of ['192.0.0.9','192.0.0.10'])globalExceptions.addAddress(address,'ipv4');
for(const [address,prefix] of [['::',128],['::1',128],['64:ff9b:1::',48],['100::',64],['2001::',23],
  ['2001:db8::',32],['2002::',16],['3fff::',20],['fc00::',7],['fe80::',10]])nonGlobal.addSubnet(address,prefix,'ipv6');
for(const [address,prefix] of [['2001:1::1',128],['2001:1::2',128],['2001:3::',32],['2001:4:112::',48],
  ['2001:20::',28],['2001:30::',28]])globalExceptions.addSubnet(address,prefix,'ipv6');
function publicAddress(address) {
  const version=isIP(address);if(!version)return false;
  const family=version===4?'ipv4':'ipv6';
  return globalExceptions.check(address,family)||!nonGlobal.check(address,family);
}
async function target(url,resolver=dns.lookup) {
  if(!publicClueURL(url))throw new BrowserFailure('navigation','pdf_target_refused');
  const parsed=new URL(url);
  let addresses;
  try{addresses=await resolver(parsed.hostname,{all:true});}
  catch(_){throw new BrowserFailure('navigation','pdf_dns_failed');}
  if(!addresses.length||addresses.some(item=>!publicAddress(item.address)))throw new BrowserFailure('navigation','pdf_target_refused');
  return parsed;
}

async function recoverBodyAccess(browser,destination,referer,{signal,deadline,verify,onWaiting}) {
  const owner=browser.operation;
  await owner.validateRecovery?.({signal,deadline});
  verify();
  const tab=await browser.newTaskPage({signal,deadline,managed:true});
  browser.associatePage(tab,{role:'verification'});
  tab.view.webContents.setWindowOpenHandler(()=>({action:'deny'}));
  const reachedHeaders=new AbortController();
  const navigationSignal=AbortSignal.any([signal,reachedHeaders.signal].filter(Boolean));
  let mainRequest,bodyRequest,bodyStatus,refusal,sawChallenge=false;
  const checkedHosts=new Map([[destination.hostname,Promise.resolve()]]);
  browser.sessionEvents.guardPageRequests(tab.view.webContents,async details=>{
    try {
      checkCanceled(navigationSignal);verify();
      if(!publicClueURL(details.url))throw new BrowserFailure('navigation','pdf_target_refused');
      const host=new URL(details.url).hostname;
      if(!checkedHosts.has(host))checkedHosts.set(host,target(details.url,browser.bodyTargetResolver));
      await waitFor(()=>checkedHosts.get(host),navigationSignal,deadline);
      verify();
      if(!browser.ownsPage(owner,tab.id))throw new BrowserFailure('navigation','page_closed');
    }catch(error){if(details.resourceType==='mainFrame')refusal=error;throw error;}
  });
  const requestGuard=browser.sessionEvents.subscribe('beforeRequest',details=>{
    if(details.webContentsId!==tab.id)return;
    verify();
    if(navigationSignal.aborted || Date.now()>=deadline || !browser.ownsPage(owner,tab.id) || !publicClueURL(details.url))
      return {cancel:true};
    if(details.resourceType==='mainFrame') {
      mainRequest={id:details.id,url:details.url,method:details.method,referer:null};
    }
  });
  const requestHeaders=browser.sessionEvents.subscribe('beforeSendHeaders',details=>{
    if(details.webContentsId===tab.id && details.id===mainRequest?.id && details.url===mainRequest.url) {
      const headers=Object.entries(details.requestHeaders || {});
      mainRequest.referer=headers.find(([name])=>name.toLowerCase()==='referer')?.[1] || null;
      mainRequest.cookie=headers.find(([name])=>name.toLowerCase()==='cookie')?.[1];
    }
  });
  const headerGuard=browser.sessionEvents.subscribe('headersReceived',details=>{
    if(details.webContentsId!==tab.id || details.resourceType!=='mainFrame' || details.id!==mainRequest?.id
      || navigationSignal.aborted || Date.now()>=deadline || !browser.ownsPage(owner,tab.id))return;
    verify();
    const headers=Object.entries(details.responseHeaders || {});
    if(headers.some(([name,values])=>name.toLowerCase()==='cf-mitigated'
      && values.some(value=>value.trim().toLowerCase()==='challenge'))){sawChallenge=true;return;}
    if(details.statusCode<200 || details.statusCode>=300 || details.url!==mainRequest.url)return;
    const value=name=>headers.find(([key])=>key.toLowerCase()===name)?.[1]?.[0] || '';
    const mime=value('content-type').split(';')[0].trim().toLowerCase();
    const attachment=/^\s*attachment(?:\s*;|\s*$)/i.test(value('content-disposition'));
    if(!attachment && !['application/pdf','application/octet-stream'].includes(mime))return;
    if(mainRequest.method!=='GET') {
      // The browser can finish its own verification or form. An unsafe
      // request is never converted into an application download GET.
      refusal=new BrowserFailure('navigation','pdf_get_unobserved');
      reachedHeaders.abort();
      return {cancel:true};
    }
    // Bound to the owned successful request. MIME/attachment can indicate a
    // body entry, but only the separate Session stream can prove PDF bytes.
    bodyRequest=mainRequest;
    bodyStatus=details.statusCode;
    reachedHeaders.abort();
    return {cancel:true};
  });
  // The task owner drains the page and Solver before replying to Python. Keep
  // the request scope in place until that physical page has gone away.
  tab.view.webContents.once('destroyed',()=>{requestGuard.dispose();requestHeaders.dispose();headerGuard.dispose();});
  let doc;
  try {
    doc=await browser.navigate(destination.href,{tab,signal:navigationSignal,deadline,onWaiting,
      httpReferrer:referer?{url:referer,policy:'strict-origin-when-cross-origin'}:undefined});}
  catch(error){if(!reachedHeaders.signal.aborted)throw refusal || error;}
  checkCanceled(signal);verify();
  if(Date.now()>=deadline)throw timeoutFailure('navigation','request');
  // HTML without download headers must reach the normal access probe. A
  // second challenge may only be visible in the rendered document.
  if(!bodyRequest && mainRequest?.method==='GET' && doc?.status>=200 && doc.status<300 && doc.url.split('#')[0]===mainRequest.url
    && (sawChallenge || tab.challenge?.kind==='cloudflare' || mainRequest.url===destination.href.split('#')[0]))
    bodyRequest=mainRequest;
  if(!bodyRequest)throw refusal || new BrowserFailure('navigation','pdf_get_unobserved');
  if(bodyStatus)browser.reportPage('info','navigation_ready',tab,{stage:'navigation',code:'page_ready',status:bodyStatus});
  // Read only the partition of this actual Page in the same native owner.
  // Neither Cookie values nor the scoped view leave the stream invocation.
  const partitionCookies=await readPartitionCookies(browser,bodyRequest.url,null,
    {signal,validate:verify,page:tab});
  const navigationCookie=!partitionCookies?bodyRequest.cookie:undefined;
  await browser.closePage(tab);
  return {url:bodyRequest.url,referer:publicClueURL(bodyRequest.referer),partitionCookies,navigationCookie};
}
const API_SCOPES={
  elsevier:['api.elsevier.com','/content/article/','X-ELS-APIKey'],
  wiley_tdm:['api.wiley.com','/onlinelibrary/tdm/v1/articles/','Wiley-TDM-Client-Token'],
  aps_harvest:['harvest.aps.org','/v2/journals/articles/','X-API-Key'],
};
function credentialHeaders(credential,url) {
  if(credential===undefined)return {};
  const scope=API_SCOPES[credential?.kind],parsed=new URL(url),value=credential?.value;
  if(!scope||Object.keys(credential).sort().join(',')!=='kind,value'||typeof value!=='string'||!value
    ||value.length>16384||/[\x00-\x1f\x7f]/.test(value)||parsed.protocol!=='https:'
    ||parsed.hostname!==scope[0]||(parsed.port&&parsed.port!=='443')||!parsed.pathname.startsWith(scope[1]))
    throw Error('credential-scope');
  return {[scope[2]]:value};
}
async function readResponse(response,signal) {
  const reader=response.body?.getReader();if(!reader)return {body:'',partial:false};
  const decoder=new TextDecoder(),chunks=[];
  // The Uvicorn bridge accepts an 8 MiB WebSocket message, including the
  // JSON-escaped response, URL and terminal envelope.
  const capacity=8*1024*1024-Buffer.byteLength(JSON.stringify(response.url))-8192;
  const byteLength=text=>Buffer.byteLength(JSON.stringify(text))-2;
  let bytes=0,partial=false,readError;
  const append=text=>{
    if(bytes+byteLength(text)<=capacity){chunks.push(text);bytes+=byteLength(text);return true;}
    let low=0,high=text.length;
    while(low<high) {
      const middle=Math.ceil((low+high)/2);
      if(bytes+byteLength(text.slice(0,middle))<=capacity)low=middle;
      else high=middle-1;
    }
    if(/[\uD800-\uDBFF]/.test(text.charAt(low-1)))low--;
    chunks.push(text.slice(0,low));return false;
  };
  try {
    while(true) {
      checkCanceled(signal);
      const {done,value}=await reader.read();
      if(!append(done?decoder.decode():decoder.decode(value,{stream:true}))){partial=true;break;}
      if(done)break;
    }
  }catch(error) {
    readError=error;checkCanceled(signal);
    if(!bytes)throw error;
    partial=true;
  }finally {
    try{await reader.cancel();}catch(error){if(error!==readError)throw error;}
    finally{reader.releaseLock();}
  }
  return {body:chunks.join(''),partial};
}
async function sniffBody(body,signal) {
  if(!body)return {pdf:false,body:null};
  const reader=body.getReader(),chunks=[];let prefix=Buffer.alloc(0),ended=false,firstByteAt;
  try {
    while(prefix.length<5) {
      checkCanceled(signal);const {done,value}=await reader.read();
      if(done){ended=true;reader.releaseLock();break;}
      if(value.length && firstByteAt===undefined)firstByteAt=performance.now();
      chunks.push(value);prefix=Buffer.concat([prefix,Buffer.from(value.subarray(0,5-prefix.length))]);
    }
  }catch(error){try{await reader.cancel();}finally{reader.releaseLock();}throw error;}
  return {pdf:prefix.equals(Buffer.from('%PDF-')),firstByteAt,body:new ReadableStream({
    async pull(controller) {
      if(chunks.length){controller.enqueue(chunks.shift());return;}
      if(ended){controller.close();return;}
      try{const {done,value}=await reader.read();if(done){ended=true;reader.releaseLock();controller.close();}else controller.enqueue(value);}
      catch(error){ended=true;reader.releaseLock();controller.error(error);}
    },
    async cancel(){if(!ended){ended=true;try{await reader.cancel();}finally{reader.releaseLock();}}},
  },{highWaterMark:0})};
}
async function executeBodyStream(browser,data,{signal,progress=()=>{},observe=()=>{}}={}) {
  const output=capability(data);
  const started=performance.now();
  const controller=new AbortController();
  const deadlineController=new AbortController(),bounded=deadlineController.signal;
  const timer=setTimeout(()=>deadlineController.abort(),Math.max(1,Math.ceil(data.deadline_ms-Date.now())));
  const stop=AbortSignal.any([signal,controller.signal,bounded].filter(Boolean));
  let fd,writer,response,body,localError,requests=[],size=0,lastProgress=0,closeError,redirect,completed=false,partitionCookies=null,navigationCookie;
  try {
    await waitFor(()=>browser.ready,stop,data.deadline_ms);checkCanceled(stop);
    const verify=browser.pinPreparedPaperAccess(data);
    verify();
    // Preflight both output and target before the first physical request.
    try{fd=openOutput(data.workspace_root,output);}catch(error){error.bodyLocal=true;throw error;}
    let url=data.url,referer=data.referer;
    let initial=await waitFor(()=>target(url,browser.bodyTargetResolver),stop,data.deadline_ms);
    const owner=browser.operation;
    const validate=()=>{if(completed)return;checkCanceled(stop);verify();if(Date.now()>=data.deadline_ms)throw Error('expired');};
    if(referer && !publicClueURL(referer))throw Error('unsafe-referer');
    if(data.recover_access===true) {
      if(data.pdf_credential!==undefined)throw Error('credential-scope');
      ({url,referer,partitionCookies,navigationCookie}=await recoverBodyAccess(browser,initial,referer,
        {signal:stop,deadline:data.deadline_ms,verify:validate,onWaiting:diagnostic=>
          progress({waiting_for_user:true},'navigation',diagnostic)}));
      if(new URL(url).origin!==initial.origin)
        initial=await waitFor(()=>target(url,browser.bodyTargetResolver),stop,data.deadline_ms);
      progress({waiting_for_user:false},'navigation');
    }
    const validateRequest=details=>{
      validate();
      if(!publicClueURL(details.url)||new URL(details.url).origin!==initial.origin)throw Error('redirect-scope');
      credentialHeaders(data.pdf_credential,details.url);
      if(details.redirectURL && publicClueURL(details.redirectURL)) {
        let scoped=true;
        try{credentialHeaders(data.pdf_credential,details.redirectURL);}catch(_){scoped=false;}
        if(new URL(details.redirectURL).origin!==initial.origin || !scoped)
          redirect={url:details.url,status:details.statusCode,location:details.redirectURL};
      }
    };
    const headers={Accept:'application/pdf',...credentialHeaders(data.pdf_credential,url)};
    const priorCookies=await waitFor(()=>browser.sessionEvents.cookieContext(url),stop,data.deadline_ms);
    if(referer) {
      const referrer=new URL(referer);referrer.hash='';
      // Electron net.fetch accepts explicit Referer as a header; Chromium rejects
      // a full cross-origin value under strict-origin policy. Project that same
      // policy before dispatch, including HTTPS-to-HTTP suppression.
      if(!(referrer.protocol==='https:'&&initial.protocol==='http:'))
        headers.Referer=referrer.origin===initial.origin?referrer.href:referrer.origin+'/';
    }
    if(data.recover_access!==true) {
      const source=data.cookie_source || referer;
      const prepared=data.service_id && data.target_page_id?browser.accessContexts.get(browser.accessKey(data))?.tab:null;
      partitionCookies=await readPartitionCookies(browser,url,source,{signal:stop,validate,
        page:prepared && (!source || prepared.view.webContents.mainFrame.origin===new URL(source).origin)?prepared:undefined});
    }
    validate();
    const requestAt=performance.now();
    ({response,requests}=await browser.sessionEvents.fetch(url,
      {method:'GET',redirect:'follow',credentials:'include',headers,referrerPolicy:'strict-origin-when-cross-origin'},
      {owner,attemptId:data.attempt_id,deadline:data.deadline_ms,signal:stop,validate,validateRequest,partitionCookies,navigationCookie}));
    const responseAt=performance.now();validate();
    const facts=requests.flatMap(request=>request.responses),final=facts.at(-1);
    if(!final||!publicClueURL(final.url))throw Error('missing-native-response');
    const contentType=(response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase();
    const sniffed=await sniffBody(response.body,stop);body=sniffed.body;
    if(response.status>=200&&response.status<300&&sniffed.pdf) {
      const writerFS=Object.create(fs);
      for(const method of ['write','writev','fsync','close'])writerFS[method]=(...args)=>{
        const callback=args.pop();fs[method](...args,(error,...values)=>{
          if(error){localError=error;if(method==='close')closeError=error;controller.abort(error);}
          callback(error,...values);
        });
      };
      writer=fs.createWriteStream('',{fd,autoClose:true,flush:true,fs:writerFS});fd=undefined;
      const meter=new Transform({transform(chunk,_encoding,callback){
        size+=chunk.length;
        try {
          if(Date.now()-lastProgress>=100){lastProgress=Date.now();progress({received_bytes:size});}
          callback(null,chunk);
        }catch(error){controller.abort(error);callback(error);}
      }});
      await pipeline(Readable.fromWeb(body),meter,writer,{signal:stop});
      completed=true;clearTimeout(timer);
      // Relative monotonic marks, published only after the real writer closes.
      // They neither carry response data nor participate in save settlement.
      try{observe({...partitionCookies && {stream_partition_cookie_count:partitionCookies.cookies.length},
        stream_request_ms:Math.round(requestAt-started),stream_response_ms:Math.round(responseAt-started),
        stream_first_byte_ms:Math.round(sniffed.firstByteAt-started),stream_closed_ms:Math.round(performance.now()-started)});}catch(_){}
      try{progress({received_bytes:size});}catch(_){}
      return {outcome:'stream_complete',kind:'pdf',pdf_type:true,transfer_complete:true,
        size_bytes:size,output_file:output.file,final_url:final.url};
    }
    const sampled=await readResponse({body,url:final.url},stop);
    const currentCookies=await waitFor(()=>browser.sessionEvents.cookieContext(final.url),stop,data.deadline_ms);
    // Only native response facts are assigned here. The existing bounded HTML
    // carrier is classified by Python's shared contextual response parser.
    const access=response.headers.get('cf-mitigated')?.trim().toLowerCase()==='challenge'?'challenge':
      [401,403,407].includes(response.status)?'authorization':null;
    return {outcome:'response',kind:'response',
      response:{url:final.url,content_type:contentType,status:response.status,...sampled,access,
        context_changed:priorCookies!==currentCookies,context_key:currentCookies}};
  }catch(error) {
    if(localError||error.bodyLocal)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'file-io',resource_closed:!closeError};
    if(stop.aborted)return {outcome:bounded.aborted?'expired':'cancelled',kind:bounded.aborted?'expired':'cancelled'};
    // Stop before an origin/credential-scope escape. Return that actual HTTP
    // redirect to the same candidate chain; the next Session request repeats
    // URL/DNS validation and uses destination cookies without source API keys.
    if(redirect)return {outcome:'response',kind:'redirect',response:redirect};
    const diagnostic=error instanceof BrowserFailure?error.diagnostic:undefined;
    const reason=diagnostic?.code==='http_error' && [401,403,407,418,429].includes(diagnostic.status)?'access-blocked':
      ({pdf_target_refused:'unsafe-target',pdf_dns_failed:'dns-failed',pdf_get_unobserved:'reader-unavailable',
      verification_page:'access-challenge',content_access_blocked:'access-blocked',site_restricted:'access-blocked',
      document_changed:'service-invalidated',page_closed:'page-access-failed',timeout:'page-access-failed'})[diagnostic?.code];
    return {outcome:'failed',kind:'failed',diagnostic_code:reason || (diagnostic?'page-access-failed':
      ['credential-scope','redirect-scope','unsafe-referer','missing-native-response'].includes(error.message)
        ?error.message:'transport-failed'),...(diagnostic && {diagnostic})};
  }finally {
    clearTimeout(timer);
    // pipeline is awaited, then writer/fd close before the native result exists.
    // Cancellation of a response is also awaited; an expired timer never races cleanup.
    try {
      try {
        const current=body||response?.body;
        if(!completed&&current&&!current.locked) {
          const reader=current.getReader();
          const closed=reader.closed.then(()=>({failed:false}),error=>({failed:true,error}));
          try {await reader.cancel();}
          catch(error) {
            // An already errored Fetch body rejects cancel with its stored
            // terminal error. That closed stream is distinct from a live
            // source whose cancellation actually failed.
            const terminal=await closed;
            if(!terminal.failed||terminal.error!==error)throw error;
          }finally {reader.releaseLock();}
        }
      }
      finally {
        if(writer&&!writer.closed){const closed=new Promise(resolve=>writer.once('close',resolve));writer.destroy();await closed;}
        if(fd!==undefined)fs.closeSync(fd);
      }
    }catch(_){return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'resource-close',resource_closed:false};}
    if(!completed && partitionCookies!==null)try{observe({stream_partition_cookie_count:partitionCookies.cookies.length});}catch(_){}
  }
}
module.exports={executeBodyStream,openOutput,publicAddress,target,directories,credentialHeaders};
