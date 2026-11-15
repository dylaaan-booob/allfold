'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),https=require('node:https'),vm=require('node:vm');
const assert=require('node:assert/strict'),{randomUUID}=require('node:crypto');
const {spawn}=require('node:child_process'),{createInterface}=require('node:readline');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {executeBodyNative}=require('../src/workflows/body-native.cjs');
const {NativeOutput}=require('../src/workflows/native-output.cjs');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const {invocationRecovery}=require('../src/shared/recovery-summary.cjs');
const {validateRecovery,settleRecoveryAuthority}=require('../src/workflows/recovery-authority.cjs');
const profile=process.argv[2],root=path.resolve(__dirname,'../..');
const caseNames=(process.argv[3]||'attachment,inline,iframe,popup,cancel,interrupted,no-item,replace,sciencedirect').split(',');
const reservations=new Map();
for(const method of ['check','absent','capture']) {
  const run=NativeOutput.prototype[method];
  NativeOutput.prototype[method]=function(...args) {
    const reservation=method==='capture'&&args[0]?.missing&&!this.file&&reservations.get(this.filename);
    const lstat=fs.lstatSync;
    if(reservation&&!reservation.observed)fs.lstatSync=(filename,...options)=>{
      if(filename===this.filename&&!reservation.observed){reservation.observed=true;return reservation.info;}
      return lstat(filename,...options);
    };
    try{return run.apply(this,args);}catch(error) {
      // Main intentionally returns only a bounded native-output code. Preserve
      // its failing phase here without changing production results or guards.
      console.error('NATIVE OUTPUT FAILURE '+JSON.stringify({phase:method,code:error.code,
        syscall:error.syscall,owned_file:!!this.file,site:String(error.stack).split('\n').slice(1,5)}));
      throw error;
    }finally{fs.lstatSync=lstat;}
  };
}
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('host-resolver-rules','MAP *.microbiologyresearch.org 127.0.0.1, MAP www.sciencedirect.com 127.0.0.1, MAP pdf.sciencedirectassets.com 127.0.0.1');
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
const identity=file=>{const info=fs.lstatSync(file);return [info.dev,info.ino];};
app.whenReady().then(async()=>{
  assert.equal(process.versions.electron,'45.0.0');
  const requests=[],payload=Buffer.alloc(256*1024,71),cases=[],childBarriers=new Map(),bodyResponses=new Map(),activeBodies=new Set();let origin;
  const certificate=fs.readFileSync(path.join(root,'tests/fixtures/http/localhost-cert.pem'),'utf8');
  const cdn=https.createServer({cert:certificate,key:fs.readFileSync(path.join(root,'tests/fixtures/http/localhost-key.pem'))},(req,res)=>{
    requests.push({url:req.url,method:req.method,body:'',cdn:true});
    const kind=new URL(req.url,'https://pdf.sciencedirectassets.com').searchParams.get('case');
    if(kind==='sciencedirect-reader-twice'&&!req.url.includes('next=1')) {
      res.writeHead(200,{'content-type':'text/html'});res.end('<script>location.replace('+JSON.stringify(req.url+'&next=1')+')</script>');return;
    }
    res.writeHead(200,{'content-type':'application/pdf'});
    if(kind==='sciencedirect-reader-cancel'){res.write(payload.subarray(0,65536));return;}
    res.end(payload);
  });
  await new Promise(resolve=>cdn.listen(0,'127.0.0.1',resolve));
  const cdnOrigin=`https://pdf.sciencedirectassets.com:${cdn.address().port}`;
  app.on('certificate-error',(event,_contents,url,_error,cert,done)=>{
    if(new URL(url).origin===cdnOrigin&&cert.data.trim()===certificate.trim()){event.preventDefault();done(true);}else done(false);
  });
  const server=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({url:req.url,method:req.method,body});
    const url=new URL(req.url,origin),kind=url.searchParams.get('case');
    if(url.pathname==='/article') {
      if(kind==='blocked'){res.writeHead(403,{'content-type':'text/html'});res.end('<title>Login required</title>');return;}
      const background=['iframe-background','popup-background','iframe-replaced','popup-source-replaced'].includes(kind);
      const popup=['popup','popup-reservation','popup-background','popup-source-replaced','action-challenge-popup'].includes(kind);
      const setup=['iframe','predeclared-iframe','predeclared-popup-guard','iframe-background','iframe-replaced','action-challenge-iframe'].includes(kind)?`onsubmit="${kind==='predeclared-popup-guard'?`window.open(this.action,'_blank');`:''}const frame=document.createElement('iframe');frame.name='new-body';document.body.appendChild(frame);${kind.startsWith('predeclared-')?'':'this.target=frame.name'}"`:
        kind==='no-item'?`onsubmit="event.preventDefault()"`:
        kind==='get-changed'?`onsubmit="this.elements.once.value='changed-after-prepare'"`:
        ['existing-target-changed','predeclared-target-changed'].includes(kind)?`onsubmit="this.target='_self'"`:
        kind==='unrelated'?`onsubmit="event.preventDefault();location.assign('/unrelated')"`:'';
      res.writeHead(200,{'content-type':'text/html'});
      const getForm=['get-form','get-changed'].includes(kind);
      res.end(`<!doctype html><html><head><meta charset="utf-8"><title>Original response</title></head><body><article><h1>Original response</h1>
        ${['existing-iframe','existing-target-changed'].includes(kind)?'<iframe name="body" src="/frame"></iframe>':''}
        ${background?`<iframe id="background" name="background" src="/frame"></iframe><script>fetch('/child-ready?case=${kind}').then(()=>{${kind==='iframe-replaced'?`document.querySelector('iframe[name="new-body"]').remove();const replacement=document.createElement('iframe');replacement.name='new-body';replacement.src='/source-replaced?case=${kind}';document.body.appendChild(replacement)`:
          kind==='popup-source-replaced'?`location.assign('/source-replaced?case=${kind}')`:`document.getElementById('background').src='/unrelated?case=${kind}'`}})</script>`:''}
        ${kind==='inline'?'<nav aria-label="Article navigation">':''}<div class="download-pdf"><form class="ft-download-content__form--pdf" method="${getForm?'GET':'POST'}" action="/once?${getForm?'discard=old-action-query&':''}case=${kind}" ${popup?'target="_blank"':kind.startsWith('predeclared-')?'target="new-body"':['existing-iframe','existing-target-changed'].includes(kind)?'target="body"':''} ${setup}>
        ${getForm?`<input name="case" value="${kind}"><input name="once" value="fixture + &"><input name="tag" value="one"><input name="tag" value="two"><input disabled name="ignored" value="disabled"><input type="checkbox" name="ignored" value="unchecked">`:`<input name="once" value="${kind==='current-form'?'current-document':'fixture'}">`}
        <button type="submit" ${getForm?'name="download" value="PDF now"':''}>Download PDF</button></form></div>${kind==='inline'?'</nav>':''}</article></body></html>`);return;
    }
    if(url.pathname==='/frame') {res.writeHead(200,{'content-type':'text/html'});res.end('<title>Existing target</title>');return;}
    if(url.pathname==='/child-ready') {
      childBarriers.set(kind,res);if(activeBodies.has(kind))res.end('go');return;
    }
    if(url.pathname==='/unrelated') {
      assert.equal(activeBodies.has(kind),true,'background navigation waits for actual native output progress');
      const native=bodyResponses.get(kind);assert.ok(native&&!native.destroyed&&!native.writableEnded,'original item is still transferring');
      res.writeHead(200,{'content-type':'text/html'});res.end(`<title>Unrelated child</title><script>location.hash='steady';fetch('/child-finished?case=${kind}')</script>`);return;
    }
    if(['/child-finished','/source-replaced'].includes(url.pathname)) {
      const native=bodyResponses.get(kind);assert.ok(native&&!native.destroyed&&!native.writableEnded,'original item remains active at child settlement');
      res.writeHead(200,{'content-type':'text/html'});res.end('<title>Child settled</title>');
      native.end(payload.subarray(65536));return;
    }
    if(url.pathname==='/once') {
      if(req.method!=='POST'&&kind!=='get-form'){res.writeHead(200,{'content-type':'text/html'});res.end('<title>Craft GET refused</title>');return;}
      if(['action-blocked','action-html'].includes(kind)||kind?.startsWith('action-challenge')) {
        res.writeHead(kind==='action-blocked'?403:200,{'content-type':'text/html'});
        res.end(kind.startsWith('action-challenge')?'<title>Just a moment...</title>':'<title>Body unavailable</title>');return;
      }
      res.writeHead(200,{'content-type':'application/pdf',...(kind==='attachment'?{'content-disposition':'attachment; filename="body.pdf"'}:{})});
      if(['iframe-background','popup-background','iframe-replaced','popup-source-replaced'].includes(kind)) {
        bodyResponses.set(kind,res);res.write(payload.subarray(0,65536));return;
      }
      if(['cancel','drain','interrupted','replace'].includes(kind)) {
        res.write(payload.subarray(0,65536));
        if(kind==='interrupted'){setTimeout(()=>res.destroy(),80);return;}
        let n=65536;
        const timer=setInterval(()=>{if(res.destroyed){clearInterval(timer);return;}res.write(payload.subarray(0,65536));n+=65536;if(n>=4*1024*1024){clearInterval(timer);res.end();}},20);
        return;
      }
      res.end(payload);return;
    }
    if(url.pathname.startsWith('/science/article/pii/')) {
      if(url.pathname.endsWith('/pdfft')) {
        if(kind?.startsWith('sciencedirect-reader')) {
          res.writeHead(kind==='sciencedirect-reader-http-error'?500:200,{'content-type':'text/html'});
          if(kind==='sciencedirect-reader-challenge'){res.end('<title>Just a moment...</title>');return;}
          const pii=kind==='sciencedirect-reader-wrong-pii'?'S9999999999999999':'S1234567890123456';
          const pdf=(kind==='sciencedirect-reader-wrong-origin'?cdnOrigin.replace('pdf.sciencedirectassets.com','assets.example'):cdnOrigin)+'/fixture/1-s2.0-'+pii+'/main.pdf?case='+kind;
          res.end('<script>'+(kind==='sciencedirect-reader-wrong-source'?'window.opener.location':'location')+'.replace('+JSON.stringify(pdf)+')</script>');return;
        }
        res.writeHead(200,{'content-type':!!req.headers.referer?.includes('/science/article/pii/')?'application/pdf':'text/html'});
        res.end(!!req.headers.referer?.includes('/science/article/pii/')?payload:Buffer.from('<title>Craft GET refused</title>'));return;
      }
      res.writeHead(200,{'content-type':'text/html'});res.end(`<html><head><meta name="citation_doi" content="10.5555/science"><meta name="citation_pdf_url" content="${url.pathname}/pdfft${url.search}"></head><body><article><h1>ScienceDirect original</h1><div class="PdfEmbed"><a class="link-button" ${kind?.startsWith('sciencedirect-reader')&&kind!=='sciencedirect-reader-self'?'target="_blank" rel="opener"':''} href="${url.pathname}/pdfft${url.search}">Download PDF</a></div></article></body></html>`);return;
    }
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://www.microbiologyresearch.org:${server.address().port}`;
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true}}),browser=new BrowserRuntime({hostWindow:window,pageLimits:{global_limit:4,service_limit:3}});
  browser.bodyTargetResolver=async()=>[{address:'93.184.216.34'}];await browser.ready;
  const messages=new Map(),progresses=new Map(),nativeCases=new Map();let python;
  const send=message=>{
    const kind=nativeCases.get(message.id);
    if(message.type==='progress'&&message.data.native_output_file&&['iframe-background','popup-background','iframe-replaced','popup-source-replaced'].includes(kind)) {
      activeBodies.add(kind);childBarriers.get(kind)?.end('go');
    }
    if(python)python.stdin.write(JSON.stringify(message)+'\n');
    if(message.type==='progress')progresses.get(message.id)?.(message.data);
    if(message.type==='result')messages.get(message.id)?.(message.data);
  };
  const context=vm.createContext({browser,send,executeBodyNative,validateRecovery,operations:new Map(),exiting:false,AbortController,WebSocket,
    CONTROL_ACTIONS:new Set(['cas_credentials','diagnostics_reset']),RESOURCE_ACTIONS:new Set(['invalidate_access','release_workflow_pages']),
    BrowserFailure,diagnosticFor,invocationRecovery,Date,Number,Promise,
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    associationLogContext:()=>({}),setLogLevel(){},withLogContext:(_context,run)=>run(),log(){},diagnosticsStatus:()=>({available:true})});
  const source=fs.readFileSync(path.join(root,'electron/src/main.cjs'),'utf8');
  vm.runInContext(source.slice(source.indexOf('async function execute(message)'),source.indexOf('async function startPython(')),context);
  function capability(paper) {
    const workspace=path.join(profile,'workspace'),documents=path.join(workspace,'Documents'),staging=path.join(documents,'.downloads'),disposal=path.join(staging,'.cleanup');
    fs.mkdirSync(disposal,{recursive:true,mode:0o700});
    const directory=path.join(staging,paper+'.1.native');fs.mkdirSync(directory,{mode:0o700});
    return {workspace_root:workspace,output:{temporary:`Documents/.downloads/${paper}.1.native/body.part`,target:`Documents/${paper}.pdf`,
      workspace:identity(workspace),documents:identity(documents),staging:identity(staging),disposal:identity(disposal),native_directory:identity(directory),file:null}};
  }
  try {
    for(const kind of caseNames.filter(kind=>kind!=='public')) {
      const science=kind.startsWith('sciencedirect');
      const paper=randomUUID(),id=randomUUID(),output=capability(paper),article=science?
        origin.replace('www.microbiologyresearch.org','www.sciencedirect.com')+'/science/article/pii/S1234567890123456'+(kind==='sciencedirect'?'':'?case='+kind):origin+'/article?case='+kind;
      const data={...output,workspace_identity:'a'.repeat(64),paper_id:paper,attempt:1,attempt_id:id,deadline_ms:Date.now()+(kind==='no-item'?800:10000),
        workflow_id:'body-fixture',task_id:'body-'+id,identity:{confirmed_article_url:article},
        candidate:{url:science?new URL(article).origin+new URL(article).pathname+'/pdfft'+new URL(article).search:origin+'/once?case='+kind,action:science?null:'refresh_form',
          platform:science?'sciencedirect':'microbiology',rule_id:science?'R024':'R059'}};
      if(kind==='popup-reservation') {
        // lstat can overlap Chromium unlinking its empty destination reservation.
        // Use an actual unlinked descriptor's stat at that filesystem boundary;
        // the original DownloadItem still writes and completes its real output.
        const temporary=path.join(profile,'empty-reservation');fs.writeFileSync(temporary,'');
        const fd=fs.openSync(temporary,'r');fs.unlinkSync(temporary);
        try {
          const info=fs.fstatSync(fd);assert.equal(info.isFile(),true);assert.equal(info.size,0);assert.equal(info.nlink,0);
          reservations.set(path.join(data.workspace_root,data.output.temporary),{info,observed:false});
        }finally{fs.closeSync(fd);}
      }
      let observed,replaced=false;
      progresses.set(id,value=>{
        if(value.native_output_file){observed=value.native_output_file;assert.deepEqual(observed,identity(path.join(data.workspace_root,data.output.temporary)));}
        if(['cancel','sciencedirect-reader-cancel'].includes(kind)&&value.received_bytes>0)context.operations.get(id).controller.abort();
        if(kind==='replace'&&observed&&!replaced) {
          replaced=true;const directory=path.dirname(path.join(data.workspace_root,data.output.temporary));
          fs.renameSync(directory,directory+'.old');fs.mkdirSync(directory,{mode:0o700});fs.writeFileSync(path.join(directory,'body.part'),'unknown replacement');
        }
      });
      const terminal=new Promise(resolve=>messages.set(id,resolve));
      await context.execute({id,action:'native_paper_body',data});const result=await terminal;
      cases.push({kind,result});console.log('NATIVE CASE '+kind+' '+JSON.stringify(result));
      const success=['attachment','inline','iframe','popup','popup-reservation','sciencedirect','sciencedirect-reader','sciencedirect-reader-self'].includes(kind);
      if(success) {
        assert.equal(result.outcome,'native_complete');assert.equal(result.resource_closed,true);assert.deepEqual(result.output_file,observed);
        const leaf=path.join(data.workspace_root,data.output.temporary);assert.deepEqual(fs.readFileSync(leaf),payload);assert.deepEqual(identity(leaf),observed);
        if(kind==='popup-reservation')assert.equal(reservations.get(leaf)?.observed,true);
      } else if(kind.startsWith('sciencedirect-reader')) {
        assert.equal(result.kind,kind==='sciencedirect-reader-challenge'?'failed':kind==='sciencedirect-reader-cancel'?'cancelled':'stale');
        assert.equal(result.output_file,undefined);
      } else if(kind==='interrupted')assert.equal(result.diagnostic_code,'interrupted');
      else if(kind==='replace') {
        assert.equal(replaced,true);assert.equal(result.kind,'local_failure');assert.equal(result.output_file,undefined);
        const leaf=path.join(data.workspace_root,data.output.temporary),exists=fs.existsSync(leaf);
        if(exists)assert.equal(fs.readFileSync(leaf,'utf8'),'unknown replacement');
        console.log('NATIVE ACCEPTED RISK '+JSON.stringify({replacement_exists_at_terminal:exists,
          cancellation_file_tasks_acknowledged:false}));
      } else assert.equal(result.kind,kind==='no-item'?'expired':kind==='unrelated'?'stale':'cancelled');
      assert.equal(browser.tabs.size,0,'source pages retain quota through terminal and then close');
      assert.equal(browser.sessionEvents.downloads.size,0);assert.equal(browser.sessionEvents.items.size,0);
    }
    if(caseNames.includes('public')) {
      python=spawn(path.join(root,'.venv/bin/python'),['-u',path.join(root,'tests/electron_body_native_fixture.py'),profile,origin],
        {cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')+':'+path.join(root,'tests')},stdio:['pipe','pipe','pipe']});
      let stderr='',dispatchError,complete=false;const publicCases=[];
      python.stderr.on('data',data=>{stderr+=data;});
      createInterface({input:python.stdout}).on('line',line=>{
        try {
          const message=JSON.parse(line);
          if(message.type==='execute') {
            if(message.action==='native_paper_body')nativeCases.set(message.id,new URL(message.data.candidate.url).searchParams.get('case'));
            void context.execute(message).catch(error=>{dispatchError=error;python.kill();});
          }
          else if(message.type==='cancel')context.operations.get(message.id)?.controller.abort();
          else if(message.type==='verify_recovery_authority_result')settleRecoveryAuthority(context.operations.get(message.id),message);
          else if(message.type==='fixture_public_native') {publicCases.push(message);console.log('PUBLIC NATIVE CASE '+JSON.stringify(message));}
          else if(message.type==='fixture_complete'){complete=true;python.stdin.end();}
        }catch(error){dispatchError=error;python.kill();}
      });
      python.stdin.write(JSON.stringify({type:'hello',token:'fixture-only'})+'\n');
      const code=await new Promise(resolve=>python.once('exit',resolve));python=null;
      if(dispatchError)throw dispatchError;
      assert.equal(code,0,stderr);assert.equal(complete,true,stderr);assert.equal(publicCases.length,25);
      for(const item of publicCases)if(item.status==='completed')assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',item.paper+'.pdf')),payload);
      assert.equal(browser.tabs.size,0);assert.equal(browser.sessionEvents.downloads.size,0);assert.equal(browser.sessionEvents.items.size,0);
      for(const kind of ['attachment','inline','iframe','predeclared-iframe','predeclared-popup-guard','existing-iframe','iframe-background','popup-background','iframe-replaced','popup-source-replaced','popup','action-blocked','action-challenge','action-challenge-iframe','action-challenge-popup','action-html','cancel','drain'])assert.deepEqual(requests.filter(request=>request.url==='/once?case='+kind),
        [{url:'/once?case='+kind,method:'POST',body:'once=fixture'}]);
      for(const kind of ['iframe-background','popup-background'])assert.equal(requests.filter(request=>request.url==='/unrelated?case='+kind).length,1);
      assert.deepEqual(requests.filter(request=>request.url==='/once?case=current-form'),
        [{url:'/once?case=current-form',method:'POST',body:'once=current-document'}]);
      assert.deepEqual(requests.filter(request=>request.url.startsWith('/once?')&&request.url.includes('get-form')),
        [{url:'/once?case=get-form&once=fixture+%2B+%26&tag=one&tag=two&download=PDF+now',method:'GET',body:''}]);
      assert.equal(requests.filter(request=>request.url.startsWith('/once?')&&request.url.includes('get-changed')).length,0);
      assert.equal(requests.filter(request=>request.url==='/once?case=existing-target-changed').length,0);
      assert.equal(requests.filter(request=>request.url==='/once?case=predeclared-target-changed').length,0);
      assert.equal(requests.filter(request=>request.url.startsWith('/expired-action')).length,0);
      assert.equal(requests.filter(request=>request.url==='/once?case=blocked').length,0);
      assert.equal(requests.filter(request=>request.url.endsWith('/pdfft')).length,1);
      console.log('PUBLIC BODY NATIVE PASS');
    }
    for(const kind of ['attachment','inline','iframe','popup','popup-reservation','cancel','interrupted']) {
      if(!caseNames.includes(kind))continue;
      const seen=requests.filter(request=>request.url==='/once?case='+kind);
      assert.deepEqual(seen,[{url:'/once?case='+kind,method:'POST',body:'once=fixture'}]);
    }
    assert.equal(requests.filter(request=>request.url==='/once?case=no-item').length,0);
    assert.equal(requests.filter(request=>request.url.endsWith('/pdfft')).length,caseNames.includes('sciencedirect')||caseNames.includes('public')?1:0,'ScienceDirect original navigation must never be replayed');
    for(const kind of caseNames.filter(kind=>kind.startsWith('sciencedirect-reader'))) {
      assert.equal(requests.filter(request=>request.url==='/science/article/pii/S1234567890123456/pdfft?case='+kind).length,1);
      assert.equal(requests.filter(request=>request.cdn&&request.url.endsWith('?case='+kind)).length,
        ['sciencedirect-reader','sciencedirect-reader-self','sciencedirect-reader-twice','sciencedirect-reader-cancel'].includes(kind)?1:0,kind);
      assert.equal(requests.filter(request=>request.cdn&&request.url.endsWith('?case='+kind+'&next=1')).length,0,'a second HTML continuation is refused');
    }
    assert.equal(browser.partition.listenerCount('will-download'),1);
    console.log('BODY NATIVE PASS');
  }finally {
    await browser.close();window.destroy();server.closeAllConnections();cdn.closeAllConnections();
    await Promise.all([new Promise(resolve=>server.close(resolve)),new Promise(resolve=>cdn.close(resolve))]);
  }
}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1);});
