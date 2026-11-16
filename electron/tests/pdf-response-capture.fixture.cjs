'use strict';
// Mechanism evidence only. This never grants a body-output capability or reports
// native_complete: Fetch's downstream terminal is not the original HTTP result.
const {app,BrowserWindow,session}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const http=require('node:http'),{gzipSync}=require('node:zlib');
const {Writable}=require('node:stream');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
const profile=process.argv[2];
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('no-proxy-server');app.on('window-all-closed',()=>{});
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const within=async(promise,ms=4000)=>{
  let timer;
  try{return await Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('fixture deadline')),ms);})]);}
  finally{clearTimeout(timer);}
};
const terminalEvents=new Set(['completed','errorOccurred','Network.loadingFinished','Network.loadingFailed']);
const pdf=Buffer.alloc(128*1024);
for(let i=0;i<pdf.length;i++)pdf[i]=i%256;
pdf.write('%PDF-');
const html=Buffer.from('<!doctype html><meta charset="utf-8"><title>Reader é</title>'+
  '<script>document.cookie="reader_untrusted=bad; Path=/"</script><!--'+'x'.repeat(300*1024)+'-->'+
  '<script nonce="fixture">document.cookie="reader_script=present; Path=/";location.assign("/reader-pdf")</script>');

app.whenReady().then(async()=>{
  assert.equal(process.versions.electron,'45.0.0');assert.equal(process.versions.chrome,'156.0.8078.48');
  const requests=[];
  const server=http.createServer((req,res)=>{
    requests.push({path:req.url,method:req.method,cookie:req.headers.cookie||'',referer:req.headers.referer||''});
    if(req.url==='/reader-pdf') {
      assert.match(req.headers.cookie||'',/reader_http=present/);assert.match(req.headers.cookie||'',/reader_script=present/);
      assert.doesNotMatch(req.headers.cookie||'',/reader_untrusted/);
      assert.equal(new URL(req.headers.referer).pathname,'/reader');
      res.writeHead(200,{'Content-Type':'application/pdf','Content-Disposition':'attachment; filename="reader.pdf"','Cache-Control':'no-store'});
      res.end(pdf);return;
    }
    if(req.url==='/reader') {
      res.writeHead(203,{'Content-Type':'text/html; charset=utf-8','Content-Encoding':'gzip','Cache-Control':'no-store',
        'Set-Cookie':'reader_http=present; HttpOnly; Path=/','Content-Security-Policy':"script-src 'nonce-fixture'; connect-src 'self'",
        'Referrer-Policy':'same-origin'});
      res.end(gzipSync(html));return;
    }
    const name=req.url.slice(1),closed=name.includes('close'),broken=name.includes('broken');
    if(closed)res.useChunkedEncodingByDefault=false;
    res.writeHead(200,{'Content-Type':name.includes('xhtml')?'application/xhtml+xml':'text/html',
      'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',Connection:'close'});
    // A real protocol error: destroying a chunked response omits its terminating
    // chunk. By contrast, the close-delimited control ends legally with EOF.
    res.write(pdf.subarray(0,2));
    setTimeout(()=>{
      if(res.destroyed)return;
      res.write(pdf.subarray(2,65536));
      setTimeout(()=>{if(!res.destroyed){if(broken)res.destroy();else res.end(pdf.subarray(65536));}},30);
    },10);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const origin='http://127.0.0.1:'+server.address().port,ses=session.fromPartition('r024-response-fixture');
  const events=sharedSessionEvents(ses),results=[];
  try {
    for(const name of ['control-good','control-broken','control-close','capture-html-fill-good','capture-xhtml-fill-good',
      'capture-html-fill-broken','capture-html-abort-good','capture-html-abort-broken','capture-close-fill-good','capture-continue-good','reader']) {
      const log=[],ids=new Set(),networkFrames=new Map(),handles=new Set(),win=new BrowserWindow({show:false,webPreferences:{session:ses,sandbox:true}}),wc=win.webContents;
      let capture,observed,items=0,resolveItem,rejectItem;
      const itemDone=new Promise((resolve,reject)=>{resolveItem=resolve;rejectItem=reject;});itemDone.catch(()=>{});
      const itemListener=(_event,item,contents)=>{
        if(contents!==wc)return;
        items++;assert.equal(name,'reader');item.setSavePath(path.join(profile,'reader.pdf'));
        item.once('done',(_event,state)=>state==='completed'?resolveItem():rejectItem(Error('reader item '+state)));
      };
      const hooks=['beforeRequest','headersReceived','completed','errorOccurred'].map(event=>events.subscribe(event,d=>{
        if(event==='beforeRequest'&&d.webContentsId===wc.id)ids.add(d.id);
        if(!ids.has(d.id))return;
        log.push({event,id:d.id,type:d.resourceType,error:d.error,frame:d.frame?.frameTreeNodeId});
      }));
      ses.on('will-download',itemListener);
      try {
        // Initial target creation must finish before issuing debugger commands.
        await wc.loadURL('about:blank');wc.debugger.attach('1.3');
        await wc.debugger.sendCommand('Page.enable');await wc.debugger.sendCommand('Network.enable');
        const {frameTree}=await wc.debugger.sendCommand('Page.getFrameTree');
        assert.equal((await wc.debugger.sendCommand('Target.getTargetInfo')).targetInfo.targetId,wc.getOrCreateDevToolsTargetId());
        const electronFrame=wc.mainFrame;
        wc.debugger.on('message',(_event,method,p)=>{
          if(method==='Network.requestWillBeSent')networkFrames.set(p.requestId,p.frameId);
          if(['Network.loadingFinished','Network.loadingFailed'].includes(method))log.push({event:method,id:p.requestId,error:p.errorText});
          if(method!=='Fetch.requestPaused')return;
          assert.equal(capture,undefined,'one response per action');
          assert.equal(p.resourceType,'Document');assert.equal(p.frameId,frameTree.frame.id);
          // The root of this WebContents' own CDP target maps to its actual main
          // frame; CDP and Electron frame/request tokens are different domains.
          assert.equal(wc.mainFrame.frameTreeNodeId,electronFrame.frameTreeNodeId);
          assert.notEqual(p.frameId,electronFrame.frameToken);assert.ok(ids.size===1&&p.networkId);
          assert.equal(networkFrames.get(p.networkId),p.frameId,'Fetch networkId refers to this target/frame request');
          log.push({event:method,id:p.requestId,network:p.networkId});
          capture=(async()=>{
            const {stream}=await wc.debugger.sendCommand('Fetch.takeResponseBodyAsStream',{requestId:p.requestId});handles.add(stream);
            let received=0,reads=0,plain=0,encoded=0,prefix=Buffer.alloc(0),isPDF,writing=false;
            const chunks=[];
            const sink=new Writable({highWaterMark:16384,write(chunk,_encoding,done){
              assert.equal(writing,false);writing=true;
              assert.deepEqual(chunk,pdf.subarray(received,received+chunk.length));received+=chunk.length;
              setTimeout(()=>{writing=false;done();},2);
            }});
            try {
              while(true) {
                assert.equal(writing,false,'read waits for the preceding sink callback');
                const block=await wc.debugger.sendCommand('IO.read',{handle:stream,size:reads<2?2:16384});reads++;
                if(block.base64Encoded)encoded++;else plain++;
                const bytes=Buffer.from(block.data,block.base64Encoded?'base64':'utf8');
                let output=bytes;
                if(isPDF===undefined) {
                  prefix=Buffer.concat([prefix,bytes]);
                  if(prefix.length>=5||block.eof){isPDF=prefix.subarray(0,5).equals(Buffer.from('%PDF-'));output=prefix;prefix=null;}
                  else output=null;
                }
                if(output) {
                  if(isPDF)await new Promise((resolve,reject)=>sink.write(output,error=>error?reject(error):resolve()));
                  else chunks.push(output); // Only real HTML is collected for fulfillRequest.
                }
                if(block.eof)break;
              }
              await new Promise((resolve,reject)=>{sink.once('error',reject);sink.end(resolve);});
              log.push({event:'stream-eof'});
              // Give the original network completion a chance to arrive while
              // paused, before any synthetic downstream terminal is requested.
              await pause(80);
              assert.equal(log.some(entry=>terminalEvents.has(entry.event)),false);
              observed={received,reads,plain,encoded,isPDF,original_terminal_exposed:false};
              if(name==='reader') {
                assert.equal(isPDF,false);assert.equal(p.responseStatusCode,203);
                const body=Buffer.concat(chunks);assert.deepEqual(body,html);assert.ok(body.length>256*1024);
                // IO delivers decoded gzip bytes. Retain status, charset, CSP,
                // Cookie and Referer policy, removing stale wire-encoding headers.
                const responseHeaders=p.responseHeaders.filter(h=>!['content-encoding','content-length','transfer-encoding'].includes(h.name.toLowerCase()));
                log.push({event:'release-html'});
                await wc.debugger.sendCommand('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:p.responseStatusCode,
                  responseHeaders,body:body.toString('base64')});
                observed.html_bytes=body.length;
              } else {
                assert.equal(isPDF,true);assert.ok(plain>0&&encoded>0,'decode each chunk using its actual encoding');
                assert.equal(received,name.includes('broken')?65536:pdf.length);
                if(name.includes('continue')) {
                  await assert.rejects(wc.debugger.sendCommand('Fetch.continueRequest',{requestId:p.requestId}),/after body is taken/);
                  observed.continue_rejected=true;log.push({event:'continue-rejected'});return;
                }
                log.push({event:'release-pdf'});
                if(name.includes('fill'))await wc.debugger.sendCommand('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:200,
                  responseHeaders:[{name:'Content-Type',value:'text/html'}],body:''});
                else await wc.debugger.sendCommand('Fetch.failRequest',{requestId:p.requestId,errorReason:'Aborted'});
              }
            }finally {
              sink.destroy();await wc.debugger.sendCommand('IO.close',{handle:stream});handles.delete(stream);
            }
          })();capture.catch(()=>{});
        });
        if(!name.startsWith('control'))await wc.debugger.sendCommand('Fetch.enable',{
          patterns:[{urlPattern:origin+'/'+name,resourceType:'Document',requestStage:'Response'}]});
        const loading=wc.loadURL(origin+'/'+name).then(()=>true,()=>false);
        if(name.startsWith('control')) {
          await within(loading);await pause(40);
          const terminal=log.find(entry=>entry.event==='Network.loadingFailed'||entry.event==='Network.loadingFinished');
          assert.ok(terminal);
          if(name.includes('broken'))assert.equal(terminal.error,'net::ERR_INCOMPLETE_CHUNKED_ENCODING');
          else assert.equal(terminal.event,'Network.loadingFinished');
        }else {
          await within((async()=>{while(!capture)await pause(5);await capture;})());
          if(!name.includes('continue')) {
            if(name==='reader')await within(itemDone);else await within(loading);
            await pause(40);
            const release=log.findIndex(entry=>entry.event==='release-pdf'||entry.event==='release-html');
            assert.ok(release>=0);
            const terminal=log.filter(entry=>terminalEvents.has(entry.event));
            assert.ok(terminal.length>=2);assert.ok(log.findIndex(entry=>terminalEvents.has(entry.event))>release);
            if(name.includes('abort')) {
              assert.equal(terminal.find(entry=>entry.event==='errorOccurred').error,'net::ERR_ABORTED');
              assert.equal(terminal.find(entry=>entry.event==='Network.loadingFailed').error,'net::ERR_ABORTED');
            }else {
              assert.ok(terminal.some(entry=>entry.event==='completed'));
              assert.ok(terminal.some(entry=>entry.event==='Network.loadingFinished'));
            }
          }
        }
        assert.equal(requests.filter(entry=>entry.path==='/'+name).length,1);assert.equal(items,name==='reader'?1:0);
        if(name==='reader') {
          assert.deepEqual(fs.readFileSync(path.join(profile,'reader.pdf')),pdf);
          assert.equal(requests.filter(entry=>entry.path==='/reader-pdf').length,1);
        }
        assert.equal(handles.size,0);
        const result={case:name,requests:1,download_items:items,...observed,
          terminal:log.filter(entry=>terminalEvents.has(entry.event)).map(({event,error})=>({event,...(error?{error}:{})}))};
        results.push(result);console.log('RESPONSE CAPTURE CASE '+JSON.stringify(result));
      } finally {
        // The rejected continue cannot restore its consumed pipe; destroy only
        // this probe's Page. No shared debugger/solver connection is touched.
        win.destroy();hooks.forEach(h=>h.dispose());ses.removeListener('will-download',itemListener);
      }
    }
    const normal=results.find(r=>r.case==='capture-html-fill-good'),broken=results.find(r=>r.case==='capture-html-fill-broken');
    assert.deepEqual(normal.terminal,broken.terminal,'a synthetic fill masks the real upstream failure');
    console.log('RESPONSE CAPTURE MECHANISM PASS '+JSON.stringify({electron:process.versions.electron,chrome:process.versions.chrome,
      production_capture:false,original_terminal_available:false,cases:results.length}));
  }finally {
    assert.equal(events.handlers.get('completed').size,0);assert.equal(events.items.size,0);
    events.dispose();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
}).then(()=>app.exit(0)).catch(error=>{console.error(error);app.exit(1);});
setTimeout(()=>{console.error('response-capture fixture timeout');app.exit(1);},25000).unref();
