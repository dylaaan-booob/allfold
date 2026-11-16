'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),vm=require('node:vm');
const assert=require('node:assert/strict'),{spawn}=require('node:child_process'),{createInterface}=require('node:readline');
const {gzipSync}=require('node:zlib');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {executeBodyStream}=require('../src/workflows/body-stream.cjs');
const {executeLocalBody}=require('../src/workflows/local-body.cjs');
const {validateRecovery,settleRecoveryAuthority}=require('../src/workflows/recovery-authority.cjs');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const {invocationRecovery}=require('../src/shared/recovery-summary.cjs');
const profile=process.argv[2],root=path.resolve(__dirname,'../..');
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('host-resolver-rules','MAP *.example.org 127.0.0.1, MAP academic.oup.com 127.0.0.1, MAP watermark02.silverchair.com 127.0.0.1, MAP ieeexplore.ieee.org 127.0.0.1');
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
app.whenReady().then(async()=>{
  const requests=[],cases=[],pairs=[],drains=[],publicCases=[],localCases=[],shellCalls=[],resolved=[],payload=Buffer.alloc(2*1024*1024,71);let origin,slowProduced=0;payload.write('%PDF-');
  const server=http.createServer(async(req,res)=>{
    requests.push({url:req.url,method:req.method,headers:req.headers});
    if(req.headers.host.startsWith('academic.oup.com:')){res.writeHead(302,{location:origin.replace('pdf.example.org','watermark02.silverchair.com')+'/'+req.url.split('/').at(-1)+'?Signature=synthetic'});res.end();return;}
    if(req.url.startsWith('/stamp/stamp.jsp')){res.writeHead(200,{'content-type':'text/html'});res.end('<iframe src="/stampPDF/getPDF.jsp?arnumber=12345"></iframe>');return;}
    if(req.url==='/cross'){res.writeHead(302,{location:origin.replace('pdf.','other.')+'/leak'});res.end();return;}
    if(req.url==='/cross-private'){res.writeHead(302,{location:origin.replace('pdf.','private.')+'/private-leak'});res.end();return;}
    if(req.url==='/cross-unsafe'){res.writeHead(302,{location:'ftp://other.example.org/unsafe-leak'});res.end();return;}
    if(req.url==='/challenge'){res.writeHead(403,{'content-type':'text/html','cf-mitigated':'challenge'});res.end('<html><title>Just a moment...</title></html>');return;}
    if(req.url==='/background-cloudflare'){res.writeHead(200,{'content-type':'text/html'});res.end('<html><title>View PDF</title><article><h1>View PDF</h1><p>access denied and captcha research</p></article><input type="password"><iframe hidden src="https://newassets.hcaptcha.com/captcha"></iframe><nav><a href="/login">Sign in</a></nav><script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></html>');return;}
    if(req.url.startsWith('/redirect')){res.writeHead(302,{location:'/body?Signature=A%2FB'});res.end();return;}
    if(req.url==='/html.pdf'){res.writeHead(200,{'content-type':'text/html','content-disposition':'attachment; filename=body.pdf'});res.end('<html><title>Login required</title><form><input type="password"></form></html>');return;}
    if(['/octet','/missing-mime','/wrong-mime','/split-prefix'].includes(req.url)){res.writeHead(200,req.url==='/missing-mime'?{}:{'content-type':req.url==='/octet'?'application/octet-stream':'text/plain'});if(req.url==='/split-prefix'){for(let i=0;i<5;i++){res.write(payload.subarray(i,i+1));await new Promise(resolve=>setTimeout(resolve,2));}res.end(payload.subarray(5));}else res.end(payload);return;}
    if(req.url==='/fake-pdf'){res.writeHead(200,{'content-type':'application/pdf'});res.end('<html><title>Login required</title><form><input type="password"></form></html>');return;}
    if(req.url==='/unknown'){res.writeHead(200,{'content-type':'application/octet-stream'});res.end('unknown');return;}
    if(req.url==='/encoded'){const data=gzipSync(payload);res.writeHead(200,{'content-type':'application/pdf','content-encoding':'gzip','content-length':data.length});res.end(data);return;}
    if(req.url==='/bad-encoding'){res.writeHead(200,{'content-type':'application/pdf','content-encoding':'gzip'});res.end('not a gzip stream');return;}
    const streamed=req.url==='/slow-writer'?Buffer.alloc(16*1024*1024,71):payload;
    if(req.url==='/slow-writer')streamed.write('%PDF-');
    if(req.url==='/close-delimited')res.useChunkedEncodingByDefault=false;
    res.writeHead(200,{'content-type':'application/pdf',...(req.url==='/truncated'?{'content-length':payload.length*2}:{}),
      ...(req.url==='/close-delimited'?{connection:'close'}:{})});
    res.write(streamed.subarray(0,65536));if(req.url==='/slow-writer')slowProduced=65536;
    if(req.url==='/truncated'){setTimeout(()=>res.destroy(),40);return;}
    for(let n=65536;n<streamed.length&&!res.destroyed;n+=65536){if(req.url!=='/slow-writer')await new Promise(r=>setTimeout(r,req.url==='/expiry'?40:8));if(req.url==='/slow-writer')slowProduced+=65536;if(!res.write(streamed.subarray(n,n+65536)))await new Promise(r=>{const done=()=>{res.removeListener('drain',done);res.removeListener('close',done);r();};res.once('drain',done);res.once('close',done);});}
    res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://pdf.example.org:${server.address().port}`;
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true}}),browser=new BrowserRuntime({hostWindow:window});
  browser.bodyTargetResolver=async host=>{resolved.push(host);return [{address:host==='private.example.org'||host==='watermark02.silverchair.com'&&faultKind==='blocked.pdf'?'127.0.0.1':'93.184.216.34'}];};
  await browser.ready;
  await browser.partition.cookies.set({url:origin,name:'fixture_session',value:'selected-session',sameSite:'unspecified'});
  for(const [host,name] of [['academic.oup.com','publisher_only'],['watermark02.silverchair.com','cdn_only'],['ieeexplore.ieee.org','reader_only'],['other.example.org','fallback_only']])
    await browser.partition.cookies.set({url:origin.replace('pdf.example.org',host),name,value:'selected-session',sameSite:'unspecified'});
  const python=spawn(path.join(root,'.venv/bin/python'),['-u',path.join(root,'tests/electron_body_stream_fixture.py'),profile,origin],
    {cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')+':'+path.join(root,'tests')},stdio:['pipe','pipe','pipe']});
  let stderr='';python.stderr.on('data',data=>{stderr+=data;});
  let lateClosed=false,lateMessage,logAcknowledged=false;
  const terminalAck=path.join(profile,'terminal-before-main-log');
  const send=message=>{
    if(message.type==='progress'&&lateClosed&&message.id===lateMessage?.id)
      context.operations.get(message.id)?.controller.abort();
    return python.stdin.write(JSON.stringify(message)+'\n');
  };
  let opened=0;
  const shell={openPath:async filename=>{assert.ok(fs.statSync(filename).isFile());shellCalls.push('open');return ++opened===2?'synthetic no default application':'';},
    showItemInFolder:filename=>{assert.ok(fs.statSync(filename).isFile());shellCalls.push('locate');}};
  const context=vm.createContext({browser,send,executeBodyStream,executeLocalBody,shell,validateRecovery,operations:new Map(),exiting:false,AbortController,WebSocket,
    CONTROL_ACTIONS:new Set(['cas_credentials','diagnostics_reset']),RESOURCE_ACTIONS:new Set(['invalidate_access','release_workflow_pages']),
    BrowserFailure,diagnosticFor,invocationRecovery,Date,Number,Promise,
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    associationLogContext:()=>({}),setLogLevel(){},withLogContext:(_context,run)=>run(),log(_level,event,data){
      if(event==='task_finished'&&data.request_id===lateMessage?.id){
        // Hold Main synchronously at its terminal diagnostic boundary. The
        // real Python host must finish publication/association and release its
        // Future/owner before this log returns; no extra bridge round trip.
        const wait=new Int32Array(new SharedArrayBuffer(4)),until=Date.now()+3000;
        while(!fs.existsSync(terminalAck)&&Date.now()<until)Atomics.wait(wait,0,0,10);
        logAcknowledged=fs.existsSync(terminalAck);
      }
    },diagnosticsStatus:()=>({available:true})});
  const source=fs.readFileSync(path.join(root,'electron/src/main.cjs'),'utf8');
  vm.runInContext(source.slice(source.indexOf('async function execute(message)'),source.indexOf('async function startPython(')),context);
  // Inject actual writer-boundary errors, without stubbing transfer or completion.
  const {Readable}=require('node:stream'),realFromWeb=Readable.fromWeb;
  let slowBytes=0,slowReadEvents=0,slowWitness=false,firstSlowWrite=true,slowOperation;
  Readable.fromWeb=(...args)=>{const readable=realFromWeb(...args);if(faultKind==='slow-writer')readable.on('data',chunk=>{slowBytes+=chunk.length;slowReadEvents++;});return readable;};
  const faults=new Map(),realOpen=fs.openSync,realWrite=fs.write,realFsync=fs.fsync,realClose=fs.close;
  let faultTarget,faultKind;
  const pin=browser.pinPreparedPaperAccess.bind(browser);
  browser.pinPreparedPaperAccess=data=>{
    const verify=pin(data);
    return ()=>{if(lateClosed&&data===lateMessage?.data)throw Error('Late Prepare change');verify();};
  };
  fs.openSync=(filename,...args)=>{const fd=realOpen(filename,...args);if(filename===faultTarget)faults.set(fd,faultKind);return fd;};
  fs.write=(fd,...args)=>{
    if(faults.get(fd)==='disk-write')return setImmediate(()=>args.at(-1)(Object.assign(Error('fixture ENOSPC'),{code:'ENOSPC'})));
    if(faults.get(fd)==='slow-writer') {
      if(firstSlowWrite){firstSlowWrite=false;assert.ok(slowReadEvents<=3&&slowBytes<16*1024*1024,'writer must start before full body aggregation');
        return setTimeout(()=>{assert.ok(slowProduced>slowBytes,'fast producer has supplied unread data');assert.ok(slowReadEvents<=3&&slowBytes<16*1024*1024,'held writer must backpressure the Node reader');slowWitness=true;realWrite(fd,...args);},100);
      }
      return setTimeout(()=>realWrite(fd,...args),3);
    }
    return realWrite(fd,...args);
  };
  fs.fsync=(fd,callback)=>faults.get(fd)==='disk-flush'?setImmediate(()=>callback(Object.assign(Error('fixture EIO'),{code:'EIO'}))):realFsync(fd,callback);
  fs.close=(fd,callback)=>{
    const mode=faults.get(fd);faults.delete(fd);
    if(mode==='completed-late-signals')return realClose(fd,error=>{
      lateClosed=true;lateMessage.data.deadline_ms=Date.now()-1;
      for(const owner of browser.operations)owner.resourceFailure=new BrowserFailure('navigation','document_changed');
      callback(error);
    });
    if(mode==='slow-writer') {
      send({type:'progress',id:slowOperation.id,action:slowOperation.action,data:{fixture_close_pending:true}});
      assert.ok(fs.fstatSync(fd).isFile());
      return setTimeout(()=>realClose(fd,error=>{assert.throws(()=>fs.fstatSync(fd));callback(error);}),100);
    }
    realClose(fd,callback);
  };
  let complete=false,dispatchError;
  const lines=createInterface({input:python.stdout});
  lines.on('line',line=>{
    try {
      const message=JSON.parse(line);
      if(message.type==='ready')return;
      if(message.type==='execute') {
        if(message.action==='stream_paper_body'){
          faultKind=new URL(message.data.url).pathname.slice(1);if(faultKind==='slow-writer')slowOperation=message;
          if(faultKind==='completed-late-signals'){lateMessage=message;lateClosed=false;}
          faultTarget=path.join(message.data.workspace_root,message.data.output.temporary);
        }
        void context.execute(message).catch(error=>{dispatchError=error;python.kill();});
      }
      else if(message.type==='cancel')context.operations.get(message.id)?.controller.abort();
      else if(message.type==='verify_recovery_authority_result')settleRecoveryAuthority(context.operations.get(message.id),message);
      else if(message.type==='fixture_case'){cases.push(message);console.log('BODY CASE '+message.path+' '+message.status);}
      else if(message.type==='fixture_public')publicCases.push(message);
      else if(message.type==='fixture_local')localCases.push(message);
      else if(message.type==='fixture_pair')pairs.push(message);
      else if(message.type==='fixture_drain')drains.push(message);
      else if(message.type==='fixture_complete'){complete=true;python.stdin.end();}
    }catch(error){dispatchError=error;python.kill();}
  });
  send({type:'hello',token:'fixture-only'});
  const code=await new Promise(resolve=>python.once('exit',resolve));
  try {
    if(dispatchError)throw dispatchError;
    assert.equal(code,0,stderr);assert.equal(complete,true,stderr);assert.equal(cases.length,28);assert.equal(slowWitness,true);
    assert.equal(logAcknowledged,true,'Python terminal/owner release must not wait for Main final logging');
    assert.deepEqual(pairs,[{type:'fixture_pair',statuses:['cancelled','completed']}]);
    assert.equal(publicCases.length,1);assert.equal(publicCases[0].status,'completed');
    assert.deepEqual(localCases,[{type:'fixture_local',status:'settled',retry_attempt:2}]);
    assert.deepEqual(shellCalls,['open','locate','open','open','open']);
    assert.equal(requests.filter(r=>r.url==='/public').length,2,'local reads add no network; explicit deletion permits one new public attempt');
    assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',publicCases[0].paper+'.pdf')),payload);
    assert.equal(requests.filter(r=>r.url==='/same').length,2);assert.equal(requests.filter(r=>r.url==='/leak').length,1);
    assert.equal(requests.filter(r=>r.url==='/private-leak'||r.url==='/unsafe-leak').length,0);
    assert.deepEqual(drains,[{type:'fixture_drain',status:'settled'}]);
    assert.equal(browser.tabs.size,0,'pure stream must create no pages');
    for(const request of requests){assert.equal(request.method,'GET');assert.equal(request.headers['x-allfold-request-context'],undefined);
      const cookie=request.headers.host.startsWith('academic.')?'publisher_only':request.headers.host.startsWith('watermark02.')?'cdn_only':request.headers.host.startsWith('ieeexplore.')?'reader_only':request.headers.host.startsWith('other.')?'fallback_only':'fixture_session';
      assert.equal(request.headers.cookie,cookie+'=selected-session');
      assert.equal(request.headers.referer,cookie==='fixture_session'&&request.url!=='/cross-referer'?origin+'/article':request.url==='/cross-referer'?origin.replace('pdf.','other.')+'/':origin+'/');}
    assert.equal(requests.filter(r=>r.headers.host.startsWith('academic.oup.com:')).length,2,'one GET to each Oxford source');
    assert.equal(requests.filter(r=>r.headers.host.startsWith('watermark02.silverchair.com:')).length,1,'one checked CDN request');
    assert.equal(resolved.filter(host=>host==='watermark02.silverchair.com').length,2,'both CDN candidates receive a fresh DNS check');
    assert.equal(requests.filter(r=>r.url.startsWith('/blocked.pdf')).length,0,'private CDN DNS is refused before headers');
    assert.equal(requests.filter(r=>r.headers.host.startsWith('ieeexplore.ieee.org:')).length,2,'reader response and its qualified PDF only');
    assert.equal(requests.filter(r=>r.url==='/body?Signature=A%2FB').length,1);
    const first=cases[0];assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',first.paper+'.pdf')),payload);
    console.log('BODY STREAM PASS '+JSON.stringify(cases.map(({path,status})=>({path,status}))));
  }finally {Readable.fromWeb=realFromWeb;fs.openSync=realOpen;fs.write=realWrite;fs.fsync=realFsync;fs.close=realClose;await browser.close();window.destroy();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1);});
