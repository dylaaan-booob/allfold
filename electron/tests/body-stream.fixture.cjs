'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),https=require('node:https'),vm=require('node:vm');
const assert=require('node:assert/strict'),{spawn}=require('node:child_process'),{createInterface}=require('node:readline');
const {X509Certificate}=require('node:crypto');
const {gzipSync}=require('node:zlib');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {executeBodyStream}=require('../src/workflows/body-stream.cjs');
const {executeLocalBody}=require('../src/workflows/local-body.cjs');
const {visitManualService}=require('../src/workflows/browser-operations.cjs');
const {validateRecovery,settleRecoveryAuthority}=require('../src/workflows/recovery-authority.cjs');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const {invocationRecovery}=require('../src/shared/recovery-summary.cjs');
const profile=process.argv[2],root=path.resolve(__dirname,'../..');
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
const failFixture=error=>{console.error(error);app.exit(1);};
// The delayed writer assertions can throw outside the fixture promise.
// Report them to the runner instead of opening Electron's error dialog.
process.once('uncaughtException',failFixture);
(async()=>{
  const requests=[],cases=[],pairs=[],drains=[],publicCases=[],localCases=[],shellCalls=[],resolved=[],solves=[],payload=Buffer.alloc(2*1024*1024,71);let origin,slowProduced=0,canceledSolver=false;payload.write('%PDF-');
  const ebscoHosts=['research.ebsco.com','content.ebscohost.com'];
  const ebscoPath='/c/test-profile',licensedPDF='https://content.ebscohost.com/cds/retrieve?Signature=A%2FB';
  const licensedBytes=Buffer.from('%PDF-licensed-ebsco');
  const serve=async(req,res)=>{
    requests.push({url:req.url,method:req.method,headers:req.headers});
    const input=new URL(req.url,origin);
    if(req.headers.host==='doi.org') {
      if(decodeURIComponent(input.pathname)==='/10.5555/licensed')res.writeHead(302,{location:origin+'/fixture-publisher'});
      else res.writeHead(404);
      res.end();return;
    }
    if(ebscoHosts.includes(req.headers.host)) {
      if(req.headers.host==='content.ebscohost.com' && req.url==='/cds/retrieve?Signature=A%2FB') {
        res.writeHead(200,{'content-type':'application/pdf'});res.end(licensedBytes);return;
      }
      const pages={
        [ebscoPath+'/search']:'<main><h1>Licensed library</h1><p>All databases</p></main>',
        [ebscoPath+'/search/results']:'<main><h1>Search results</h1><h2><a href="'+ebscoPath+'/search/details/licensed">Licensed fixture</a></h2></main>',
        [ebscoPath+'/search/details/licensed']:'<main><h1>Licensed fixture</h1><p>DOI: 10.5555/licensed</p><a href="'+ebscoPath+'/viewer/pdf/licensed">View PDF</a></main>'
          +'<script>fetch('+JSON.stringify(new URL('/cds/retrieve?Signature=preview',licensedPDF).href)+').catch(()=>{});</script>',
        [ebscoPath+'/viewer/pdf/licensed']:'<meta name="referrer" content="no-referrer"><main><h1>Licensed full text</h1><p>Institution viewer</p></main><script>fetch('+JSON.stringify(licensedPDF)+').catch(()=>{});</script>',
      };
      res.writeHead(pages[input.pathname]?200:404,{'content-type':'text/html','cache-control':'no-store'});
      res.end(pages[input.pathname] || '<main><h1>Missing page</h1></main>');return;
    }
    if(input.pathname==='/fixture-publisher') {
      res.writeHead(200,{'content-type':'text/html'});res.end('<head><meta name="citation_doi" content="10.5555/licensed"></head><main><h1>Licensed fixture</h1><p>Publisher article</p></main>');return;
    }
    if(input.pathname==='/fixture-publisher-pdf') {
      res.writeHead(403,{'content-type':'text/html'});res.end('<title>Access denied</title>');return;
    }
    if(input.pathname==='/cookie-return') {
      res.writeHead(302,{location:origin+'/cookie-progress'+input.search});res.end();return;
    }
    if(input.pathname==='/cookie-progress'&&!req.headers.cookie?.includes('cookie_progress=two')) {
      const step=req.headers.cookie?.includes('cookie_progress=one')?'two':'one';
      res.writeHead(200,{'content-type':'text/html','set-cookie':'cookie_progress='+step+'; Path=/cookie-progress'});
      res.end('<head><meta name="citation_doi" content="'+input.searchParams.get('doi')+'"><meta name="citation_pdf_url" content="'+origin.replace('pdf.','other.')+'/cookie-return'+input.search+'"></head>');return;
    }
    if(req.headers.host.startsWith('academic.oup.com:')){res.writeHead(302,{location:origin.replace('pdf.example.org','watermark02.silverchair.com')+'/'+req.url.split('/').at(-1)+'?Signature=synthetic'});res.end();return;}
    if(req.url.startsWith('/stamp/stamp.jsp')){res.writeHead(200,{'content-type':'text/html'});res.end('<iframe src="/stampPDF/getPDF.jsp?arnumber=12345"></iframe>');return;}
    if(req.url==='/cross'){res.writeHead(302,{location:origin.replace('pdf.','other.')+'/leak'});res.end();return;}
    if(req.url==='/cross-private'){res.writeHead(302,{location:origin.replace('pdf.','private.')+'/private-leak'});res.end();return;}
    if(req.url==='/cross-unsafe'){res.writeHead(302,{location:'ftp://other.example.org/unsafe-leak'});res.end();return;}
    if(req.url==='/challenge'){
      const headers={'content-type':'text/html'};
      if(req.headers.accept==='application/pdf')headers['cf-mitigated']='challenge';
      res.writeHead(403,headers);res.end('<title>Unavailable</title>');return;
    }
    if(req.url==='/unrelated-ready'){
      const headers={'content-type':'text/html'};
      if(req.headers.accept==='application/pdf'){
        res.writeHead(403,{...headers,'cf-mitigated':'challenge'});res.end('<title>Just a moment...</title>');return;
      }
      res.writeHead(302,{location:'/unrelated-article'});res.end();return;
    }
    if(req.url==='/unrelated-article'){
      res.writeHead(200,{'content-type':'text/html'});res.end('<title>Unrelated article</title><main>Ordinary HTML</main>');return;
    }
    if(req.url==='/pending-challenge'){
      res.writeHead(403,{'content-type':'text/html','cf-mitigated':'challenge'});
      res.end('<title>Just a moment...</title>');return;
    }
    if(input.pathname==='/protected.pdf'&&!req.headers.cookie?.includes('fixture_access=ok')){
      if(input.searchParams.get('Signature')==='second'){
        res.writeHead(200,{'content-type':'text/html'});
        res.end('<title>Just a moment...</title><script>window._cf_chl_opt = {};</script>'
          +'<a id="fixture-check" href="/fixture-check">Finish</a>');return;
      }
      res.writeHead(403,{'content-type':'text/html','cf-mitigated':'challenge'});
      res.end('<title>Just a moment...</title><a id="fixture-check" href="?Signature=second">Continue</a>'
        +'<img src="'+origin.replace('pdf.','other.')+'/unrelated-image">');return;
    }
    if(req.url==='/fixture-check'){
      res.writeHead(302,{'set-cookie':'fixture_access=ok; Path=/protected.pdf; Secure; HttpOnly; SameSite=None; Partitioned',location:'/protected.pdf?Signature=renewed'});res.end();return;
    }
    if(input.pathname==='/protected.pdf'){
      if(!['renewed','inline'].includes(input.searchParams.get('Signature'))){
        res.writeHead(403,{'content-type':'text/html'});res.end('<title>Expired signature</title>');return;
      }
      res.writeHead(200,{'content-type':'text/html',...(input.searchParams.get('Signature')==='renewed'
        ?{'content-disposition':'attachment; filename=article.pdf'}:{})});res.end(payload);return;
    }
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
  };
  const server=http.createServer(serve);
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://pdf.example.org:${server.address().port}`;
  const cert=fs.readFileSync(path.join(root,'tests/fixtures/http/localhost-cert.pem'));
  const fingerprint=new X509Certificate(cert).fingerprint256;
  const secureServer=https.createServer({cert,key:fs.readFileSync(path.join(root,'tests/fixtures/http/localhost-key.pem'))},serve);
  await new Promise(resolve=>secureServer.listen(0,'127.0.0.1',resolve));
  const secureOrigin=`https://pdf.example.org:${secureServer.address().port}`;
  app.commandLine.appendSwitch('host-resolver-rules',[
    'MAP *.example.org 127.0.0.1','MAP academic.oup.com 127.0.0.1','MAP watermark02.silverchair.com 127.0.0.1',
    'MAP ieeexplore.ieee.org 127.0.0.1',...['doi.org',...ebscoHosts].map(host=>'MAP '+host+' 127.0.0.1:'+secureServer.address().port),
  ].join(', '));
  await app.whenReady();
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true}}),browser=new BrowserRuntime({hostWindow:window,
    solveCloudflare:async(tab,{signal})=>{
      const contents=tab.view.webContents;
      if(new URL(contents.getURL()).pathname==='/pending-challenge'){
        await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));
        canceledSolver=true;
        return {outcome:'not_executed',reason:'canceled'};
      }
      assert.equal(new URL(contents.getURL()).pathname,'/protected.pdf');
      solves.push(tab.id);
      await contents.executeJavaScript('document.querySelector("#fixture-check").click()');
      return {outcome:'solved'};
    }});
  browser.bodyTargetResolver=async host=>{resolved.push(host);return [{address:host==='private.example.org'||host==='watermark02.silverchair.com'&&faultKind==='blocked.pdf'?'127.0.0.1':'93.184.216.34'}];};
  await browser.ready;
  browser.partition.setCertificateVerifyProc((request,callback)=>callback((['doi.org','pdf.example.org',...ebscoHosts].includes(request.hostname))
    && new X509Certificate(request.certificate.data).fingerprint256===fingerprint?0:-3));
  const fetch=browser.sessionEvents.fetch.bind(browser.sessionEvents);
  browser.sessionEvents.fetch=async(url,options,context)=>{
    if(new URL(url).searchParams.get('Signature')==='renewed'){
      assert.ok(solves.length===2 && solves[0]===solves[1] && !browser.tabs.has(solves[0]),
        'Both verification pages are observed on the same tab and the tab drains before streaming');
      if(context.navigationCookie)
        await browser.partition.cookies.set({url,name:'fixture_recent',value:'rotated',path:'/protected.pdf',secure:true});
    }
    return fetch(url,options,context);
  };
  await browser.partition.cookies.set({url:origin,name:'fixture_session',value:'selected-session',sameSite:'unspecified'});
  await browser.partition.cookies.set({url:secureOrigin+'/protected.pdf',name:'fixture_recent',value:'original',path:'/protected.pdf',secure:true});
  for(const [host,name] of [['academic.oup.com','publisher_only'],['watermark02.silverchair.com','cdn_only'],['ieeexplore.ieee.org','reader_only'],['other.example.org','fallback_only']])
    await browser.partition.cookies.set({url:origin.replace('pdf.example.org',host),name,value:'selected-session',sameSite:'unspecified'});
  const python=spawn(path.join(root,'.venv/bin/python'),['-u',path.join(root,'tests/electron_body_stream_fixture.py'),profile,origin,secureOrigin],
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
  const streamTimings=[];
  let ebscoCase;
  const context=vm.createContext({browser,send,executeBodyStream:(browser,data,options)=>executeBodyStream(browser,data,{...options,observe:timing=>{
    options.observe(timing);throw Error('synthetic observation failure');
  }}),executeLocalBody,visitManualService,shell,validateRecovery,operations:new Map(),exiting:false,AbortController,WebSocket,
    CONTROL_ACTIONS:new Set(['cas_credentials','diagnostics_reset']),RESOURCE_ACTIONS:new Set(['invalidate_access','release_workflow_pages']),
    BrowserFailure,diagnosticFor,invocationRecovery,Date,Number,Promise,
    readerDiagnosticFields:require('../src/browser/pdf-clues.cjs').readerDiagnosticFields,
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    associationLogContext:()=>({}),setLogLevel(){},withLogContext:(_context,run)=>run(),log(_level,event,data){
      if(event==='task_finished'&&data.action==='stream_paper_body'&&data.outcome==='stream_complete')streamTimings.push(data);
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
  let slowBytes=0,slowWitness=false,firstSlowWrite=true,slowOperation,slowReader;
  Readable.fromWeb=(...args)=>{
    const readable=realFromWeb(...args);
    if(faultKind==='slow-writer'){
      slowReader=readable;
      readable.on('data',chunk=>{slowBytes+=chunk.length;});
    }
    return readable;
  };
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
      if(firstSlowWrite){
        firstSlowWrite=false;
        assert.ok(slowBytes<16*1024*1024,'writer must start before full body aggregation');
        return setTimeout(()=>{
          assert.ok(slowProduced>slowBytes,'fast producer has supplied unread data');
          assert.ok(slowReader?.isPaused(),'held writer must pause the Node reader');
          assert.ok(slowBytes<16*1024*1024,'held writer must leave some body unread');
          slowWitness=true;
          realWrite(fd,...args);
        },100);
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
      else if(message.type==='fixture_ebsco')ebscoCase=message;
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
    assert.equal(code,0,stderr);assert.equal(complete,true,stderr);assert.equal(cases.length,34);assert.equal(slowWitness,true);
    assert.equal(solves.length,2);
    assert.equal(browser.tabs.has(solves[0]),false,'challenge page is destroyed before the managed retry settles');
    const protectedRequests=requests.filter(r=>r.url.startsWith('/protected.pdf?Signature='));
    assert.deepEqual(protectedRequests.map(r=>r.headers.accept==='application/pdf'),[true,false,false,false,true,true,false,true,true,false,true]);
    assert.deepEqual(protectedRequests.map(r=>r.headers.cookie?.includes('fixture_access=ok')),[false,false,false,true,true,false,true,true,false,true,true]);
    assert.deepEqual(protectedRequests.map(r=>new URL(r.url,origin).searchParams.get('Signature')),
      ['fixture','fixture','second','renewed','renewed','renewed','renewed','renewed','inline','inline','inline']);
    assert.deepEqual(protectedRequests.map(r=>new URL(r.headers.referer).pathname+new URL(r.headers.referer).search),
      ['/article','/article','/protected.pdf?Signature=fixture','/protected.pdf?Signature=second','/protected.pdf?Signature=second',
        '/article','/article','/article','/article','/article','/article']);
    assert.match(protectedRequests[7].headers.cookie,/fixture_recent=rotated/);
    assert.doesNotMatch(protectedRequests[7].headers.cookie,/fixture_recent=original/);
    assert.equal(requests.filter(r=>r.url==='/unrelated-ready').length,2,'ordinary unchallenged HTML cannot trigger a new stream');
    assert.equal(requests.filter(r=>r.url==='/unrelated-image').length,0,'recovery page cannot reach unrelated origins');
    assert.equal(requests.filter(r=>r.url==='/fixture-check').length,1);
    assert.equal(canceledSolver,true,'canceling the captured Paper drains the waiting verification solver');
    assert.equal(requests.filter(r=>r.url==='/pending-challenge').length,2,'cancelled verification cannot resume the stream');
    assert.equal(logAcknowledged,true,'Python terminal/owner release must not wait for Main final logging');
    assert.ok(streamTimings.length>0);
    for(const event of streamTimings){
      const marks=['stream_request_ms','stream_response_ms','stream_first_byte_ms','stream_closed_ms'].map(key=>event[key]);
      assert.ok(marks.every(value=>Number.isSafeInteger(value)&&value>=0),'successful streams retain bounded relative timings');
      assert.deepEqual(marks,[...marks].sort((a,b)=>a-b));
      assert.ok(marks.at(-1)<=event.duration_ms+2,'closed writer mark precedes the final diagnostic');
    }
    assert.deepEqual(pairs,[{type:'fixture_pair',statuses:['cancelled','completed']}]);
    assert.equal(publicCases.length,1);assert.equal(publicCases[0].status,'completed');
    assert.deepEqual(localCases,[{type:'fixture_local',status:'settled',retry_attempt:2}]);
    assert.deepEqual(shellCalls,['open','locate','open','open','open']);
    assert.equal(requests.filter(r=>r.url==='/public').length,2,'local reads add no network; explicit deletion permits one new public attempt');
    assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',publicCases[0].paper+'.pdf')),payload);
    assert.equal(requests.filter(r=>r.url==='/same').length,2);assert.equal(requests.filter(r=>r.url==='/leak').length,1);
    const cookieRequests=requests.filter(r=>r.url.startsWith('/cookie-progress'));
    assert.deepEqual(cookieRequests.map(r=>r.headers.cookie.split('; ').sort()),[
      ['fixture_session=selected-session'],['cookie_progress=one','fixture_session=selected-session'],
      ['cookie_progress=two','fixture_session=selected-session']]);
    assert.deepEqual(cookieRequests.map(r=>r.headers.referer),Array.from({length:3},()=>origin+'/article'));
    assert.equal(requests.filter(r=>r.url.startsWith('/cookie-return')).length,2);
    assert.equal(requests.filter(r=>r.url==='/private-leak'||r.url==='/unsafe-leak').length,0);
    assert.deepEqual(drains,[{type:'fixture_drain',status:'settled'}]);
    assert.equal(ebscoCase?.status,'completed');
    assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',ebscoCase.paper+'.pdf')),licensedBytes);
    const deniedPublisher=requests.filter(r=>r.url==='/fixture-publisher-pdf');
    assert.equal(deniedPublisher.length,1);
    assert.equal(deniedPublisher[0].headers.referer,origin+'/fixture-publisher');
    assert.equal(requests.filter(r=>r.url==='/fixture-publisher').length,0,'a licensed body ends discovery before refreshing the refused publisher');
    assert.equal(requests.filter(r=>r.url==='/fixture-preprint').length,0);
    const licensedRequests=requests.filter(r=>r.headers.host==='content.ebscohost.com');
    assert.equal(licensedRequests.length,1,'the managed stream sends the sole licensed PDF request');
    assert.equal(licensedRequests[0].url,'/cds/retrieve?Signature=A%2FB');
    assert.equal(licensedRequests[0].headers.referer,undefined);
    const retained=[...browser.tabs.values()];assert.equal(retained.length,1,'only the prepared target is retained');
    await browser.closePage(retained[0]);
    assert.equal(browser.tabs.size,0,'all temporary pages drain before body completion');
    for(const request of requests){assert.equal(request.method,'GET');assert.equal(request.headers['x-allfold-request-context'],undefined);
      if(['doi.org',...ebscoHosts].includes(request.headers.host) || ['/fixture-publisher','/fixture-publisher-pdf'].includes(request.url))continue;
      if(request.url.startsWith('/cookie-progress'))continue; // Exact evolving values checked above.
      if(protectedRequests.includes(request) || ['/fixture-check','/unrelated-article'].includes(request.url))continue; // Browser challenge sequence checked above.
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
  }finally {Readable.fromWeb=realFromWeb;fs.openSync=realOpen;fs.write=realWrite;fs.fsync=realFsync;fs.close=realClose;await browser.close();window.destroy();
    await Promise.all([server,secureServer].map(listener=>{listener.closeAllConnections();return new Promise(resolve=>listener.close(resolve));}));}
})().then(()=>app.exit(0)).catch(failFixture);
