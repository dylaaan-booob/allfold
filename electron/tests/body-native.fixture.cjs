'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),vm=require('node:vm');
const assert=require('node:assert/strict'),{randomUUID}=require('node:crypto');
const {spawn}=require('node:child_process'),{createInterface}=require('node:readline');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {executeBodyNative}=require('../src/workflows/body-native.cjs');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const {invocationRecovery}=require('../src/shared/recovery-summary.cjs');
const {validateRecovery,settleRecoveryAuthority}=require('../src/workflows/recovery-authority.cjs');
const profile=process.argv[2],root=path.resolve(__dirname,'../..');
const caseNames=(process.argv[3]||'attachment,inline,iframe,popup,cancel,interrupted,no-item,replace,sciencedirect').split(',');
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('host-resolver-rules','MAP *.microbiologyresearch.org 127.0.0.1, MAP www.sciencedirect.com 127.0.0.1');
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
const identity=file=>{const info=fs.lstatSync(file);return [info.dev,info.ino];};
app.whenReady().then(async()=>{
  assert.equal(process.versions.electron,'45.0.0');
  const requests=[],payload=Buffer.alloc(256*1024,71),cases=[];let origin;
  const server=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({url:req.url,method:req.method,body});
    const url=new URL(req.url,origin),kind=url.searchParams.get('case');
    if(url.pathname==='/article') {
      if(kind==='blocked'){res.writeHead(403,{'content-type':'text/html'});res.end('<title>Login required</title>');return;}
      const setup=['iframe','action-challenge-iframe'].includes(kind)?`onsubmit="const frame=document.createElement('iframe');frame.name='new-body';document.body.appendChild(frame);this.target=frame.name"`:
        kind==='no-item'?`onsubmit="event.preventDefault()"`:
        kind==='get-changed'?`onsubmit="this.elements.once.value='changed-after-prepare'"`:
        kind==='unrelated'?`onsubmit="event.preventDefault();location.assign('/unrelated')"`:'';
      res.writeHead(200,{'content-type':'text/html'});
      const getForm=['get-form','get-changed'].includes(kind);
      res.end(`<!doctype html><html><head><meta charset="utf-8"><title>Original response</title></head><body><article><h1>Original response</h1>
        <div class="download-pdf"><form class="ft-download-content__form--pdf" method="${getForm?'GET':'POST'}" action="/once?${getForm?'discard=old-action-query&':''}case=${kind}" ${['popup','action-challenge-popup'].includes(kind)?'target="_blank"':''} ${setup}>
        ${getForm?`<input name="case" value="${kind}"><input name="once" value="fixture + &"><input name="tag" value="one"><input name="tag" value="two"><input disabled name="ignored" value="disabled"><input type="checkbox" name="ignored" value="unchecked">`:`<input name="once" value="${kind==='current-form'?'current-document':'fixture'}">`}
        <button type="submit" ${getForm?'name="download" value="PDF now"':''}>Download PDF</button></form></div></article></body></html>`);return;
    }
    if(url.pathname==='/once') {
      if(req.method!=='POST'&&kind!=='get-form'){res.writeHead(200,{'content-type':'text/html'});res.end('<title>Craft GET refused</title>');return;}
      if(['action-blocked','action-html'].includes(kind)||kind?.startsWith('action-challenge')) {
        res.writeHead(kind==='action-blocked'?403:200,{'content-type':'text/html'});
        res.end(kind.startsWith('action-challenge')?'<title>Just a moment...</title>':'<title>Body unavailable</title>');return;
      }
      res.writeHead(200,{'content-type':'application/pdf',...(kind==='attachment'?{'content-disposition':'attachment; filename="body.pdf"'}:{})});
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
        res.writeHead(200,{'content-type':!!req.headers.referer?.includes('/science/article/pii/')?'application/pdf':'text/html'});
        res.end(!!req.headers.referer?.includes('/science/article/pii/')?payload:Buffer.from('<title>Craft GET refused</title>'));return;
      }
      res.writeHead(200,{'content-type':'text/html'});res.end(`<html><head><meta name="citation_doi" content="10.5555/science"><meta name="citation_pdf_url" content="${url.pathname}/pdfft"></head><body><article><h1>ScienceDirect original</h1><div class="PdfEmbed"><a class="link-button" href="${url.pathname}/pdfft">Download PDF</a></div></article></body></html>`);return;
    }
    res.writeHead(404);res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://www.microbiologyresearch.org:${server.address().port}`;
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true}}),browser=new BrowserRuntime({hostWindow:window,pageLimits:{global_limit:4,service_limit:3}});
  browser.bodyTargetResolver=async()=>[{address:'93.184.216.34'}];await browser.ready;
  const messages=new Map(),progresses=new Map();let python;
  const send=message=>{
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
      const paper=randomUUID(),id=randomUUID(),output=capability(paper),article=kind==='sciencedirect'?
        origin.replace('www.microbiologyresearch.org','www.sciencedirect.com')+'/science/article/pii/S1234567890123456':origin+'/article?case='+kind;
      const data={...output,workspace_identity:'a'.repeat(64),paper_id:paper,attempt:1,attempt_id:id,deadline_ms:Date.now()+(kind==='no-item'?800:10000),
        workflow_id:'body-fixture',task_id:'body-'+id,identity:{confirmed_article_url:article},
        candidate:{url:kind==='sciencedirect'?article+'/pdfft':origin+'/once?case='+kind,action:kind==='sciencedirect'?null:'refresh_form',
          platform:kind==='sciencedirect'?'sciencedirect':'microbiology',rule_id:kind==='sciencedirect'?'R024':'R059'}};
      let observed,replaced=false;
      progresses.set(id,value=>{
        if(value.native_output_file){observed=value.native_output_file;assert.deepEqual(observed,identity(path.join(data.workspace_root,data.output.temporary)));}
        if(kind==='cancel'&&value.received_bytes>0)context.operations.get(id).controller.abort();
        if(kind==='replace'&&observed&&!replaced) {
          replaced=true;const directory=path.dirname(path.join(data.workspace_root,data.output.temporary));
          fs.renameSync(directory,directory+'.old');fs.mkdirSync(directory,{mode:0o700});fs.writeFileSync(path.join(directory,'body.part'),'unknown replacement');
        }
      });
      const terminal=new Promise(resolve=>messages.set(id,resolve));
      await context.execute({id,action:'native_paper_body',data});const result=await terminal;
      cases.push({kind,result});console.log('NATIVE CASE '+kind+' '+JSON.stringify(result));
      const success=['attachment','inline','iframe','popup','sciencedirect'].includes(kind);
      if(success) {
        assert.equal(result.outcome,'native_complete');assert.equal(result.resource_closed,true);assert.deepEqual(result.output_file,observed);
        const leaf=path.join(data.workspace_root,data.output.temporary);assert.deepEqual(fs.readFileSync(leaf),payload);assert.deepEqual(identity(leaf),observed);
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
          if(message.type==='execute')void context.execute(message).catch(error=>{dispatchError=error;python.kill();});
          else if(message.type==='cancel')context.operations.get(message.id)?.controller.abort();
          else if(message.type==='verify_recovery_authority_result')settleRecoveryAuthority(context.operations.get(message.id),message);
          else if(message.type==='fixture_public_native') {publicCases.push(message);console.log('PUBLIC NATIVE CASE '+JSON.stringify(message));}
          else if(message.type==='fixture_complete'){complete=true;python.stdin.end();}
        }catch(error){dispatchError=error;python.kill();}
      });
      python.stdin.write(JSON.stringify({type:'hello',token:'fixture-only'})+'\n');
      const code=await new Promise(resolve=>python.once('exit',resolve));python=null;
      if(dispatchError)throw dispatchError;
      assert.equal(code,0,stderr);assert.equal(complete,true,stderr);assert.equal(publicCases.length,16);
      for(const item of publicCases)if(item.status==='completed')assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',item.paper+'.pdf')),payload);
      assert.equal(browser.tabs.size,0);assert.equal(browser.sessionEvents.downloads.size,0);assert.equal(browser.sessionEvents.items.size,0);
      for(const kind of ['attachment','inline','iframe','popup','action-blocked','action-challenge','action-challenge-iframe','action-challenge-popup','action-html','cancel','drain'])assert.deepEqual(requests.filter(request=>request.url==='/once?case='+kind),
        [{url:'/once?case='+kind,method:'POST',body:'once=fixture'}]);
      assert.deepEqual(requests.filter(request=>request.url==='/once?case=current-form'),
        [{url:'/once?case=current-form',method:'POST',body:'once=current-document'}]);
      assert.deepEqual(requests.filter(request=>request.url.startsWith('/once?')&&request.url.includes('get-form')),
        [{url:'/once?case=get-form&once=fixture+%2B+%26&tag=one&tag=two&download=PDF+now',method:'GET',body:''}]);
      assert.equal(requests.filter(request=>request.url.startsWith('/once?')&&request.url.includes('get-changed')).length,0);
      assert.equal(requests.filter(request=>request.url.startsWith('/expired-action')).length,0);
      assert.equal(requests.filter(request=>request.url==='/once?case=blocked').length,0);
      assert.equal(requests.filter(request=>request.url.endsWith('/pdfft')).length,1);
      console.log('PUBLIC BODY NATIVE PASS');
    }
    for(const kind of ['attachment','inline','iframe','popup','cancel','interrupted']) {
      if(!caseNames.includes(kind))continue;
      const seen=requests.filter(request=>request.url==='/once?case='+kind);
      assert.deepEqual(seen,[{url:'/once?case='+kind,method:'POST',body:'once=fixture'}]);
    }
    assert.equal(requests.filter(request=>request.url==='/once?case=no-item').length,0);
    assert.equal(requests.filter(request=>request.url.endsWith('/pdfft')).length,caseNames.includes('sciencedirect')||caseNames.includes('public')?1:0,'ScienceDirect original navigation must never be replayed');
    assert.equal(browser.partition.listenerCount('will-download'),1);
    console.log('BODY NATIVE PASS');
  }finally {await browser.close();window.destroy();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1);});
