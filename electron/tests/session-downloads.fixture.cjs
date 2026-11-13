'use strict';
const {app,BrowserWindow,session}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
app.on('window-all-closed',()=>{});
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const limited=(promise,ms=3000)=>Promise.race([promise,new Promise((_,reject)=>{const timer=setTimeout(()=>reject(Error('fixture deadline')),ms);timer.unref();})]);
app.whenReady().then(async()=>{
  assert.equal(process.versions.electron,'45.0.0');
  const requests=[],windows=[],observations=[],sourceLifetime=[];let origin,sequence=0;
  const payload=Buffer.from('%PDF-1.4\nfixture original response\n%%EOF\n');
  const server=http.createServer(async(request,response)=>{
    let body='';for await(const chunk of request)body+=chunk;
    const url=new URL(request.url,origin);requests.push({path:url.pathname,method:request.method,body,headers:request.headers});
    if(url.pathname==='/source') {response.setHeader('content-type','text/html');response.end('<!doctype html><title>Fixture source</title><body>source</body>');return;}
    if(url.pathname==='/redirect') {response.writeHead(307,{location:'/fetch-final'});response.end();return;}
    if(url.pathname==='/fetch-final') {response.writeHead(429,{'content-type':'text/plain','retry-after':'1'});response.end(body);return;}
    if(url.pathname==='/close-before')await delay(150);
    response.writeHead(200,{'content-type':'application/pdf',...(url.pathname.startsWith('/inline')?{}:{'content-disposition':'attachment; filename="untrusted.pdf"'})});
    if(url.pathname.startsWith('/slow') || url.pathname==='/interrupted') {
      response.write(payload);
      if(url.pathname==='/interrupted'){setTimeout(()=>response.destroy(),60);return;}
      for(let index=0;index<8 && !response.destroyed;index++){await delay(35);response.write(Buffer.alloc(8192,index));}
    }
    response.end(payload);
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port;
  const partition=session.fromPartition('allfold'),events=sharedSessionEvents(partition);
  const open=async()=>{const window=new BrowserWindow({show:false,webPreferences:{session:partition,sandbox:true,contextIsolation:true,nodeIntegration:false}});
    windows.push(window);await window.loadURL(origin+'/source');return window;};
  const register=(window,{frame=window.webContents.mainFrame,...options}={})=>{
    let accept;const ready=new Promise(resolve=>{accept=resolve;});const id='fixture-'+(++sequence),filename=path.join(profile,id+'.tmp');
    const registration=events.registerDownload({owner:{workflow_id:id,task_id:id},attemptId:id,contents:window.webContents,frame,
      document:{pageId:window.webContents.id,processId:frame.processId,frameToken:frame.frameToken,documentId:id,url:frame.url},
      filename,deadline:Date.now()+3000,validate:()=>!window.isDestroyed(),
      onItem:download=>{observations.push({id,frame:download.frame?{processId:download.frame.processId,frameToken:download.frame.frameToken}:null});accept(download);},...options});
    return {ready,filename,registration};
  };
  const post=(frame,target,value='one-shot')=>frame.executeJavaScript(`(()=>{const form=document.createElement('form');form.method='POST';form.action=${JSON.stringify(target)};
    const input=document.createElement('input');input.name='ticket';input.value=${JSON.stringify(value)};form.append(input);document.body.append(form);form.submit();})()`);
  try {
    const window=await open(),download=register(window);
    await post(window.webContents.mainFrame,origin+'/once');
    const original=await limited(download.ready);assert.equal(await limited(original.terminal),'completed');
    assert.deepEqual(fs.readFileSync(download.filename),payload);download.registration.dispose({dispatched:true});
    window.destroy();assert.equal(window.isDestroyed(),true);sourceLifetime.push({stage:'after-terminal',result:'completed'});
    assert.deepEqual(requests.filter(entry=>entry.path==='/once').map(({method,body})=>({method,body})),[{method:'POST',body:'ticket=one-shot'}]);
    const inlineWindow=await open(),inline=register(inlineWindow,{inlineMimeTypes:['application/pdf']});
    await post(inlineWindow.webContents.mainFrame,origin+'/inline','inline');
    const inlineItem=await limited(inline.ready);assert.equal(await limited(inlineItem.terminal),'completed');
    assert.deepEqual(fs.readFileSync(inline.filename),payload);inline.registration.dispose({dispatched:true});
    assert.deepEqual(requests.filter(entry=>entry.path==='/inline').map(({method,body})=>({method,body})),[{method:'POST',body:'ticket=inline'}]);
    const framed=await open();await framed.webContents.executeJavaScript(`new Promise(resolve=>{const iframe=document.createElement('iframe');iframe.name='child';iframe.src=${JSON.stringify(origin+'/source')};iframe.onload=()=>resolve(true);document.body.append(iframe);})`);
    const child=framed.webContents.mainFrame.frames.find(frame=>frame.name==='child');assert.ok(child);
    const iframeDownload=register(framed,{frame:child,inlineMimeTypes:['application/pdf']});
    await post(child,origin+'/inline-frame','iframe');
    const iframeItem=await limited(iframeDownload.ready);assert.equal(await limited(iframeItem.terminal),'completed');
    assert.equal(iframeItem.frame.frameToken,child.frameToken);iframeDownload.registration.dispose({dispatched:true});
    const parent=await open();parent.webContents.setWindowOpenHandler(()=>({action:'allow',overrideBrowserWindowOptions:{show:false,webPreferences:{session:partition,sandbox:true,contextIsolation:true,nodeIntegration:false}}}));
    const popupReady=new Promise(resolve=>parent.webContents.once('did-create-window',window=>{windows.push(window);window.webContents.once('did-finish-load',()=>resolve(window));}));
    await parent.webContents.executeJavaScript(`window.open(${JSON.stringify(origin+'/source')});void 0`,true);
    const popup=await limited(popupReady),popupDownload=register(popup,{inlineMimeTypes:['application/pdf']});
    await post(popup.webContents.mainFrame,origin+'/inline-popup','popup');
    const popupItem=await limited(popupDownload.ready);assert.equal(await limited(popupItem.terminal),'completed');
    assert.equal(popupItem.contents,popup.webContents);popupDownload.registration.dispose({dispatched:true});
    for(const target of ['/inline-frame','/inline-popup'])assert.deepEqual(requests.filter(entry=>entry.path===target).map(entry=>entry.method),['POST']);
    const a=await open(),b=await open(),left=register(a),right=register(b);
    await Promise.all([post(a.webContents.mainFrame,origin+'/same','left'),post(b.webContents.mainFrame,origin+'/same','right')]);
    const [ia,ib]=await limited(Promise.all([left.ready,right.ready]));
    assert.deepEqual(await limited(Promise.all([ia.terminal,ib.terminal])),['completed','completed']);
    assert.equal(ia.contents,a.webContents);assert.equal(ib.contents,b.webContents);
    assert.deepEqual(fs.readFileSync(left.filename),payload);assert.deepEqual(fs.readFileSync(right.filename),payload);
    left.registration.dispose({dispatched:true});right.registration.dispose({dispatched:true});
    assert.equal(requests.filter(entry=>entry.path==='/same').length,2);
    // A missing item expires. The source stays unsafe until actual destruction,
    // and refuses another attempt before that attempt can dispatch an action.
    const missingWindow=await open(),missing=register(missingWindow,{deadline:Date.now()+30});
    await delay(50);missing.registration.dispose({dispatched:true});
    assert.throws(()=>register(missingWindow),/download_not_attributable/);
    const lateDone=new Promise(resolve=>partition.prependOnceListener('will-download',(_event,item)=>item.once('done',(_event,state)=>resolve(state))));
    await post(missingWindow.webContents.mainFrame,origin+'/late');assert.equal(await limited(lateDone),'cancelled');
    assert.equal(fs.existsSync(missing.filename),false);
    const oldContents=missingWindow.webContents,destroyed=new Promise(resolve=>oldContents.once('destroyed',resolve));
    missingWindow.destroy();await limited(destroyed);assert.equal(events.downloadSourceUnsafe(oldContents),false);
    const freshWindow=await open(),fresh=register(freshWindow);
    await post(freshWindow.webContents.mainFrame,origin+'/fresh-after-late');
    const freshItem=await limited(fresh.ready);assert.equal(await limited(freshItem.terminal),'completed');
    assert.deepEqual(fs.readFileSync(fresh.filename),payload);fresh.registration.dispose({dispatched:true});
    // A source-less host download is deliberately outside managed task ownership.
    // The fixture supplies its own path only to avoid native save UI.
    const unownedDone=new Promise(resolve=>partition.prependOnceListener('will-download',(_event,item,contents,frame)=>{
      item.setSavePath(path.join(profile,'unowned.tmp'));
      item.once('done',(_event,state)=>resolve({state,contents,frame}));
    }));
    partition.downloadURL(origin+'/source-less');const unowned=await limited(unownedDone);
    assert.equal(unowned.state,'completed');assert.equal(unowned.contents,null);assert.equal(unowned.frame,null);
    const ambiguousWindow=await open();let claimed=0;
    const ambiguousA=register(ambiguousWindow,{onItem:()=>{claimed++;}}),ambiguousB=register(ambiguousWindow,{onItem:()=>{claimed++;}});
    const ambiguousDone=new Promise(resolve=>partition.prependOnceListener('will-download',(_event,item)=>item.once('done',(_event,state)=>resolve(state))));
    await post(ambiguousWindow.webContents.mainFrame,origin+'/ambiguous');assert.equal(await limited(ambiguousDone),'cancelled');assert.equal(claimed,0);
    ambiguousA.registration.dispose();ambiguousB.registration.dispose();
    // Closing the source before native handoff and during transfer are separate
    // measured stages. Production conservatively retains sources until done.
    const beforeWindow=await open(),before=register(beforeWindow);
    await post(beforeWindow.webContents.mainFrame,origin+'/close-before');
    while(!requests.some(entry=>entry.path==='/close-before'))await delay(5);
    beforeWindow.destroy();
    const beforeResult=await Promise.race([before.ready.then(item=>item.terminal),delay(250).then(()=> 'no-item')]);
    sourceLifetime.push({stage:'before-handoff',result:beforeResult});before.registration.dispose({dispatched:true});
    assert.equal(beforeResult,'no-item');
    const duringWindow=await open(),during=register(duringWindow);
    await post(duringWindow.webContents.mainFrame,origin+'/slow-close');
    const duringItem=await limited(during.ready);duringWindow.destroy();
    const duringResult=await limited(duringItem.terminal);sourceLifetime.push({stage:'during-transfer',result:duringResult});
    assert.equal(duringResult,'completed');
    during.registration.dispose({dispatched:true});
    const cancelWindow=await open(),cancelController=new AbortController(),cancelled=register(cancelWindow,{signal:cancelController.signal});
    await post(cancelWindow.webContents.mainFrame,origin+'/slow-cancel');const cancelItem=await limited(cancelled.ready);
    cancelController.abort();assert.equal(await limited(cancelItem.terminal),'cancelled');cancelled.registration.dispose({dispatched:true});
    const interruptedWindow=await open(),interrupted=register(interruptedWindow);
    await post(interruptedWindow.webContents.mainFrame,origin+'/interrupted');const interruptedItem=await limited(interrupted.ready);
    assert.equal(await limited(interruptedItem.terminal),'cancelled');assert.equal(interruptedItem.observation.interrupted,true);
    interrupted.registration.dispose({dispatched:true});
    for(const target of ['/late','/fresh-after-late','/ambiguous','/close-before','/slow-close','/slow-cancel','/interrupted'])
      assert.deepEqual(requests.filter(entry=>entry.path===target).map(entry=>entry.method),['POST']);
    // Real host requests have no WebContents; association follows the stripped
    // private token and Chromium's request ID across the actual 307 redirect.
    const fetches=await Promise.all(['left','right'].map(id=>events.fetch(origin+'/redirect',{method:'POST',body:id,credentials:'omit'},
      {owner:{workflow_id:id,task_id:id},attemptId:id,deadline:Date.now()+2000})));
    assert.deepEqual(await Promise.all(fetches.map(({response})=>response.text())),['left','right']);
    for(const [index,result] of fetches.entries()) {
      assert.equal(result.requests.length,1);assert.equal(result.requests[0].identity.workflow_id,['left','right'][index]);
      assert.equal(result.requests[0].redirects[0].redirectURL,origin+'/fetch-final');
      assert.equal(result.requests[0].responses.at(-1).url,origin+'/fetch-final');
    }
    const coolCancel=new AbortController();
    const blocked=events.fetch(origin+'/blocked',{},
      {owner:{workflow_id:'later-operation'},attemptId:'later',signal:coolCancel.signal,deadline:Date.now()+2000});
    const blockedResult=assert.rejects(blocked,error=>error.diagnostic?.code==='canceled');
    await delay(20);coolCancel.abort();await blockedResult;
    assert.equal(requests.some(entry=>entry.path==='/blocked'),false);
    const independent=http.createServer((_request,response)=>response.end('independent'));
    await new Promise(resolve=>independent.listen(0,'127.0.0.1',resolve));
    try {
      const other=await events.fetch('http://127.0.0.1:'+independent.address().port+'/independent',{},
        {owner:{workflow_id:'independent-origin'},attemptId:'independent',deadline:Date.now()+500});
      assert.equal(await other.response.text(),'independent');
    }finally {independent.closeAllConnections();await new Promise(resolve=>independent.close(resolve));}
    assert.equal(requests.some(entry=>Object.keys(entry.headers).some(name=>name.startsWith('x-allfold-'))),false);
    console.log('SESSION DOWNLOADS OBSERVATIONS '+JSON.stringify(observations));
    console.log('SESSION SOURCE LIFETIME '+JSON.stringify(sourceLifetime));
    console.log('SESSION SOURCELESS FRAME '+JSON.stringify({source:unowned.contents,frame:unowned.frame,state:unowned.state}));
    console.log('SESSION DOWNLOADS PASS');
  } catch(error) {
    console.error('Native fixture requests '+JSON.stringify(requests.map(({path,method})=>({path,method}))));
    console.error('Native fixture observed sources '+JSON.stringify(observations));throw error;
  } finally {
    for(const window of windows)if(!window.isDestroyed())window.destroy();
    await events.waitForDownloads();events.dispose();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
  }
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
