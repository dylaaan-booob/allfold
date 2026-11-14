'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),vm=require('node:vm');
const assert=require('node:assert/strict'),{spawn}=require('node:child_process'),{createInterface}=require('node:readline');
const {gzipSync}=require('node:zlib');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {executeBodyStream}=require('../src/workflows/body-stream.cjs');
const {BrowserFailure,diagnosticFor}=require('../src/browser/browser-errors.cjs');
const {invocationRecovery}=require('../src/shared/recovery-summary.cjs');
const profile=process.argv[2],root=path.resolve(__dirname,'../..');
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('host-resolver-rules','MAP *.example.org 127.0.0.1');
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
app.whenReady().then(async()=>{
  const requests=[],cases=[],pairs=[],payload=Buffer.alloc(2*1024*1024,71);let origin;
  const server=http.createServer(async(req,res)=>{
    requests.push({url:req.url,method:req.method,headers:req.headers});
    if(req.url==='/cross'){res.writeHead(302,{location:origin.replace('pdf.','other.')+'/leak'});res.end();return;}
    if(req.url==='/challenge'){res.writeHead(403,{'content-type':'text/html'});res.end('<html>cf-chl-challenge-platform</html>');return;}
    if(req.url.startsWith('/redirect')){res.writeHead(302,{location:'/body?Signature=A%2FB'});res.end();return;}
    if(req.url==='/html.pdf'){res.writeHead(200,{'content-type':'text/html','content-disposition':'attachment; filename=body.pdf'});res.end('<html>login required</html>');return;}
    if(req.url==='/unknown'){res.writeHead(200,{'content-type':'application/octet-stream'});res.end('unknown');return;}
    if(req.url==='/encoded'){const data=gzipSync(payload);res.writeHead(200,{'content-type':'application/pdf','content-encoding':'gzip','content-length':data.length});res.end(data);return;}
    res.writeHead(200,{'content-type':'application/pdf',...(req.url==='/truncated'?{'content-length':payload.length*2}:{})});
    res.write(payload.subarray(0,65536));
    if(req.url==='/truncated'){setTimeout(()=>res.destroy(),40);return;}
    for(let n=65536;n<payload.length&&!res.destroyed;n+=65536){await new Promise(r=>setTimeout(r,req.url==='/expiry'?40:8));if(!res.write(payload.subarray(n,n+65536)))await new Promise(r=>{const done=()=>{res.removeListener('drain',done);res.removeListener('close',done);r();};res.once('drain',done);res.once('close',done);});}
    res.end();
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://pdf.example.org:${server.address().port}`;
  const window=new BrowserWindow({show:false,webPreferences:{sandbox:true}}),browser=new BrowserRuntime({hostWindow:window});
  browser.bodyTargetResolver=async()=>[{address:'93.184.216.34'}];
  await browser.ready;
  await browser.partition.cookies.set({url:origin,name:'fixture_session',value:'selected-session',sameSite:'unspecified'});
  const python=spawn(path.join(root,'.venv/bin/python'),['-u',path.join(root,'tests/electron_body_stream_fixture.py'),profile,origin],
    {cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')+':'+path.join(root,'tests')},stdio:['pipe','pipe','pipe']});
  let stderr='';python.stderr.on('data',data=>{stderr+=data;});
  const send=message=>python.stdin.write(JSON.stringify(message)+'\n');
  const context=vm.createContext({browser,send,executeBodyStream,operations:new Map(),exiting:false,AbortController,WebSocket,
    CONTROL_ACTIONS:new Set(['cas_credentials','diagnostics_reset']),RESOURCE_ACTIONS:new Set(['invalidate_access','release_workflow_pages']),
    BrowserFailure,diagnosticFor,invocationRecovery,Date,Number,Promise,
    operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    associationLogContext:()=>({}),setLogLevel(){},withLogContext:(_context,run)=>run(),log(){},diagnosticsStatus:()=>({available:true})});
  const source=fs.readFileSync(path.join(root,'electron/src/main.cjs'),'utf8');
  vm.runInContext(source.slice(source.indexOf('async function execute(message)'),source.indexOf('async function startPython(')),context);
  // Inject actual writer-boundary errors, without stubbing transfer or completion.
  const faults=new Map(),realOpen=fs.openSync,realWrite=fs.write,realFsync=fs.fsync,realClose=fs.close;
  let faultTarget,faultKind;
  fs.openSync=(filename,...args)=>{const fd=realOpen(filename,...args);if(filename===faultTarget)faults.set(fd,faultKind);return fd;};
  fs.write=(fd,...args)=>{
    if(faults.get(fd)==='disk-write')return setImmediate(()=>args.at(-1)(Object.assign(Error('fixture ENOSPC'),{code:'ENOSPC'})));
    return realWrite(fd,...args);
  };
  fs.fsync=(fd,callback)=>faults.get(fd)==='disk-flush'?setImmediate(()=>callback(Object.assign(Error('fixture EIO'),{code:'EIO'}))):realFsync(fd,callback);
  fs.close=(fd,callback)=>{faults.delete(fd);realClose(fd,callback);};
  let complete=false,dispatchError;
  const lines=createInterface({input:python.stdout});
  lines.on('line',line=>{
    try {
      const message=JSON.parse(line);
      if(message.type==='ready')return;
      if(message.type==='execute') {
        faultKind=new URL(message.data.url).pathname.slice(1);
        faultTarget=path.join(message.data.workspace_root,message.data.output.temporary);
        void context.execute(message).catch(error=>{dispatchError=error;python.kill();});
      }
      else if(message.type==='cancel')context.operations.get(message.id)?.controller.abort();
      else if(message.type==='fixture_case')cases.push(message);
      else if(message.type==='fixture_pair')pairs.push(message);
      else if(message.type==='fixture_complete'){complete=true;python.stdin.end();}
    }catch(error){dispatchError=error;python.kill();}
  });
  send({type:'hello',token:'fixture-only'});
  const code=await new Promise(resolve=>python.once('exit',resolve));
  try {
    if(dispatchError)throw dispatchError;
    assert.equal(code,0,stderr);assert.equal(complete,true,stderr);assert.equal(cases.length,12);assert.deepEqual(pairs,[{type:'fixture_pair',statuses:['cancelled','completed']}]);
    assert.equal(requests.filter(r=>r.url==='/same').length,2);assert.equal(requests.filter(r=>r.url==='/leak').length,0);
    assert.equal(browser.tabs.size,0,'pure stream must create no pages');
    for(const request of requests){assert.equal(request.method,'GET');assert.equal(request.headers['x-allfold-request-context'],undefined);assert.equal(request.headers.cookie,'fixture_session=selected-session');assert.equal(request.headers.referer,origin+'/article');}
    assert.equal(requests.filter(r=>r.url==='/body?Signature=A%2FB').length,1);
    const first=cases[0];assert.deepEqual(fs.readFileSync(path.join(profile,'workspace/Documents',first.paper+'.pdf')),payload);
    console.log('BODY STREAM PASS '+JSON.stringify(cases.map(({path,status})=>({path,status}))));
  }finally {fs.openSync=realOpen;fs.write=realWrite;fs.fsync=realFsync;fs.close=realClose;await browser.close();window.destroy();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1);});
