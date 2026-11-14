'use strict';
// Only authenticated application dispatch can supply this attempt capability.
// PDF bytes remain in Main: Web stream -> Node pipeline -> verified file fd.
const fs=require('node:fs'),path=require('node:path'),dns=require('node:dns/promises');
const {BlockList,isIP}=require('node:net');
const {Readable,Transform}=require('node:stream');
const {pipeline}=require('node:stream/promises');
const {publicClueURL}=require('../browser/pdf-clues.cjs');
const {checkCanceled,waitFor}=require('../browser/browser-task.cjs');
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
  const fd=fs.openSync(filename,fs.constants.O_WRONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK|(process.platform==='darwin'?0x20000000:0));
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
  if(!publicClueURL(url))throw Error('unsafe-target');
  const parsed=new URL(url),addresses=await resolver(parsed.hostname,{all:true});
  if(!addresses.length||addresses.some(item=>!publicAddress(item.address)))throw Error('unsafe-target');
  return parsed;
}
async function boundedResponse(response,signal) {
  const reader=response.body?.getReader();if(!reader)return '';
  const decoder=new TextDecoder();let text='',bytes=0;
  try {
    while(true) {
      checkCanceled(signal);const {done,value}=await reader.read();if(done)break;
      bytes+=value.length;if(bytes>262144)throw Error('response-budget');
      text+=decoder.decode(value,{stream:true});
    }
    return text+decoder.decode();
  }finally {await reader.cancel();reader.releaseLock();}
}
async function executeBodyStream(browser,data,{signal,progress=()=>{}}={}) {
  const output=capability(data);
  const controller=new AbortController();
  const bounded=AbortSignal.timeout(Math.max(1,Math.ceil(data.deadline_ms-Date.now())));
  const stop=AbortSignal.any([signal,controller.signal,bounded].filter(Boolean));
  let fd,writer,response,localError,requests=[],size=0,lastProgress=0,closeError;
  try {
    await waitFor(()=>browser.ready,stop,data.deadline_ms);checkCanceled(stop);
    const verify=browser.pinPreparedPaperAccess(data);
    verify();
    // Preflight both output and target before the first physical request.
    try{fd=openOutput(data.workspace_root,output);}catch(error){error.bodyLocal=true;throw error;}
    const initial=await waitFor(()=>target(data.url,browser.bodyTargetResolver),stop,data.deadline_ms);
    const owner=browser.operation;
    const validate=()=>{checkCanceled(stop);verify();if(Date.now()>=data.deadline_ms)throw Error('expired');};
    const validateRequest=details=>{
      validate();
      if(!publicClueURL(details.url)||new URL(details.url).origin!==initial.origin)throw Error('redirect-scope');
    };
    const headers={Accept:'application/pdf'};
    if(data.referer) {
      if(!publicClueURL(data.referer))throw Error('unsafe-referer');
      headers.Referer=data.referer;
    }
    ({response,requests}=await browser.sessionEvents.fetch(data.url,
      {method:'GET',redirect:'follow',credentials:'include',headers,referrerPolicy:'strict-origin-when-cross-origin'},
      {owner,attemptId:data.attempt_id,deadline:data.deadline_ms,signal:stop,validate,validateRequest}));
    validate();
    const facts=requests.flatMap(request=>request.responses),final=facts.at(-1);
    if(!final||!publicClueURL(final.url))throw Error('missing-native-response');
    const contentType=(response.headers.get('content-type')||'').split(';')[0].trim().toLowerCase();
    if(response.status>=200&&response.status<300&&contentType==='application/pdf'&&response.body) {
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
      await pipeline(Readable.fromWeb(response.body),meter,writer,{signal:stop});
      validate();
      directories(data.workspace_root,output);
      progress({received_bytes:size});
      return {outcome:'stream_complete',kind:'pdf',pdf_type:true,transfer_complete:true,
        size_bytes:size,output_file:output.file,final_url:final.url};
    }
    const body=await boundedResponse(response,stop);
    const access=/cf-chl-|challenge-platform|Just a moment/i.test(body)?'challenge':
      [401,403,407].includes(response.status)?'authorization':
      /(?:sign in|log in|login required)/i.test(body)?'login':null;
    return {outcome:'response',kind:contentType.includes('html')?'response':'failed',
      response:{url:final.url,content_type:contentType,status:response.status,body,access}};
  }catch(error) {
    if(localError||error.bodyLocal)return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'file-io',resource_closed:!closeError};
    if(stop.aborted)return {outcome:bounded.aborted?'expired':'cancelled',kind:bounded.aborted?'expired':'cancelled'};
    return {outcome:'failed',kind:'failed',diagnostic_code:'source-failed'};
  }finally {
    // pipeline is awaited, then writer/fd close before the native result exists.
    // Cancellation of a response is also awaited; an expired timer never races cleanup.
    try {
      try {if(response?.body&&!response.body.locked)await response.body.cancel();}
      finally {
        if(writer&&!writer.closed){const closed=new Promise(resolve=>writer.once('close',resolve));writer.destroy();await closed;}
        if(fd!==undefined)fs.closeSync(fd);
      }
    }catch(_){return {outcome:'local_failure',kind:'local_failure',diagnostic_code:'resource-close',resource_closed:false};}
  }
}
module.exports={executeBodyStream,openOutput,publicAddress};
