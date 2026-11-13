'use strict';
const {app,BrowserWindow,webContents}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),path=require('node:path'),fs=require('node:fs');
const {randomUUID}=require('node:crypto');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {prepareLoggedInService}=require('../src/workflows/browser-operations.cjs');
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
const signal=new AbortController().signal;
const scope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
const saved={service_scope:scope,authentication_key:'f'.repeat(64)};
const service={...saved,service_id:'svc_'+'1'.repeat(32),preparation_key:'d'.repeat(64)};
const other={...saved,service_id:'svc_'+'2'.repeat(32),preparation_key:'e'.repeat(64)};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};
async function until(check){const deadline=Date.now()+3000;while(!check()){if(Date.now()>=deadline)throw Error('Native page state timed out');await delay(10);}}
let finishSlow,origin;const requests=[];
const server=http.createServer((req,res)=>{
  requests.push({method:req.method,url:req.url});req.resume();
  if(req.url==='/post') {res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="post.bin"'});res.end(Buffer.alloc(8192,3));return;}
  if(req.url==='/slow') {
    res.writeHead(200,{'Content-Type':'application/octet-stream','Content-Disposition':'attachment; filename="original.bin"','Content-Length':8192});
    res.write(Buffer.alloc(1024,1));finishSlow=()=>res.end(Buffer.alloc(7168,2));return;
  }
  res.writeHead(200,{'Content-Type':'text/html'});
  res.end('<!doctype html><html><body><h1>Controlled resource</h1><a href="/slow" download="original.bin">Original transfer</a><form method="POST" action="/post"><input name="once" value="fixture"></form></body></html>');
});
app.whenReady().then(async()=>{
  const host=new BrowserWindow({show:false,width:900,height:650});
  const browser=new BrowserRuntime({hostWindow:host,pageLimits:{global_limit:4,service_limit:3}});
  const physical=()=>webContents.getAllWebContents().filter(contents=>!contents.isDestroyed() && contents.session===browser.partition).length;
  const task=(data,run,taskSignal=signal)=>browser.runTask(taskSignal,{request_id:randomUUID(),...data},run);
  const page=async(role)=>{const tab=await browser.newTaskPage({signal,deadline:Date.now()+3000,managed:true});browser.associatePage(tab,{role});return tab;};
  try {
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port;await browser.ready;
    const resourceHTML=`<!doctype html><html><body><input id="searchKey" class="searchInput"><button class="Btn1 searBtn">Search</button>
      <input type="checkbox" id="onlyMySchool" name="onlyMySchool"><input id="isShowAll" value="y"><script>
      const handlers=new Map();function jQuery(){return {on(name,fn){handlers.set(name,fn)},off(namespace){for(const key of handlers.keys())if(key.includes(namespace))handlers.delete(key)}}}
      jQuery.fn={on(){},off(){}};window.jQuery=jQuery;
      document.querySelector('button').onclick=()=>{const xhr={responseURL:'https://ds.carsi.edu.cn/resource/getResource.php'},settings={type:'GET',url:'/resource/getResource.php?isShowAll=y&searchKey='+encodeURIComponent(document.getElementById('searchKey').value)};
        for(const [key,fn] of handlers)if(key.startsWith('ajaxSend'))fn({},xhr,settings);
        for(const [key,fn] of handlers)if(key.startsWith('ajaxSuccess'))fn({},xhr,settings,[]);
        for(const [key,fn] of handlers)if(key.startsWith('ajaxComplete'))fn({},xhr,settings);};</script></body></html>`;
    browser.partition.protocol.handle('https',()=>new Response(resourceHTML,{headers:{'Content-Type':'text/html'}}));
    let portal,target,opener,openerContents,targetContents;
    await task(saved,async()=>{portal=await page('carsi-portal');await browser.navigate('https://ds.carsi.edu.cn/resource/resource.php',{tab:portal,signal,deadline:Date.now()+3000});portal.carsiSessionReady=true;browser.retainAccessPage(portal,saved,'portal');});
    assert.equal(physical(),1);
    const later={...service,workflow_id:'later_login',task_id:'later_prepare',portal_page_id:portal.id,name:'Absent fixture Service',
      service_scope:{...scope,config_revision:'9'.repeat(64),user_state_revision:'8'.repeat(64)}};
    const reused=await task(later,()=>prepareLoggedInService(browser,later,{signal,progress(){}}));
    assert.equal(reused.reason,'resource_not_found');assert.equal(browser.tabs.get(portal.id),portal);assert.equal(physical(),1);
    await task(service,async()=>{
      browser.pinAccessPage(portal,service);await browser.reserveTaskPages(3,{signal,deadline:Date.now()+3000});
      await page('service-resource');opener=await page('service-resource');openerContents=opener.view.webContents;
      await browser.navigate(origin+'/opener',{tab:opener,signal,deadline:Date.now()+3000});
      const created=deferred();browser.events.once('tab-created',(_event,tab)=>created.resolve(tab));
      await opener.view.webContents.executeJavaScript('void window.open('+JSON.stringify(origin+'/target')+',"_blank")',true);
      target=await created.promise;targetContents=target.view.webContents;await until(()=>target.view.webContents.getURL()===origin+'/target' && !target.view.webContents.isLoadingMainFrame());
      assert.equal(physical(),4);assert.equal(browser.selected,null);assert.equal(browser.presentation.visible,false);
      assert.ok(target.view.getBounds().width>0 && target.view.getBounds().height>0);
      browser.retainAccessPage(target,service);browser.loanWorkflowPage(target,await browser.documentBinding(target));
    });
    assert.equal(openerContents.isDestroyed(),true);assert.equal(targetContents.isDestroyed(),false);
    assert.equal(target.view.webContents.getURL(),origin+'/target');assert.equal(physical(),2);
    for(let index=0;index<6;index++) {
      await task(other,async()=>{browser.pinAccessPage(portal,other);await browser.reserveTaskPages(2,{signal,deadline:Date.now()+3000});await page('auxiliary');await page('auxiliary');assert.equal(physical(),4);});
      assert.equal(physical(),2,'completed batches return to the bounded Portal/target base');
    }
    const filled=deferred(),finish=deferred();
    const active=task(other,async()=>{browser.pinAccessPage(portal,other);await page('auxiliary');await page('auxiliary');filled.resolve();await finish.promise;});
    await filled.promise;assert.equal(physical(),4);
    const abort=new AbortController();let admitted=false;
    const queued=task({...saved,service_id:'svc_'+'3'.repeat(32)},async()=>{await browser.newTaskPage({signal:abort.signal,deadline:Date.now()+3000});admitted=true;},abort.signal);
    await delay(30);assert.equal(admitted,false);assert.equal(physical(),4);abort.abort();await assert.rejects(queued,/canceled/);
    finish.resolve();await active;assert.equal(physical(),2);
    // WF03 navigation-generation authority refuses this Runtime form-POST entry; record the bounded refusal without another GET.
    await task(other,async()=>{
      browser.pinAccessPage(portal,other);const source=await page('auxiliary'),contents=source.view.webContents;
      const doc=await browser.navigate(origin+'/post-source',{tab:source,signal,deadline:Date.now()+3000}),observed=deferred();
      const registration=browser.sessionEvents.registerDownload({owner:browser.operation,attemptId:'post-document-boundary',contents,
        frame:contents.mainFrame,document:doc,validate:()=>browser.documentCurrent(doc),filename:path.join(profile,'post.bin'),signal,
        deadline:Date.now()+3000,onItem:entry=>observed.resolve({...entry,rejected:false}),onRejected:entry=>observed.resolve({...entry,rejected:true})});
      await contents.executeJavaScript('document.forms[0].submit();void 0',true);
      const item=await observed.promise;assert.equal(item.rejected,true);assert.equal(await item.terminal,'cancelled');registration.dispose();
      assert.equal(fs.existsSync(path.join(profile,'post.bin')),false);
    });
    assert.deepEqual(requests.filter(request=>request.url==='/post'),[{method:'POST',url:'/post'}]);assert.equal(physical(),2);
    // The task returns after its original item is claimed. Runtime cleanup must retain its source and physical slot until actual done.
    const downloading=deferred();let source,sourceContents;
    const transfer=task(other,async()=>{
      browser.pinAccessPage(portal,other);source=await page('auxiliary');sourceContents=source.view.webContents;
      const doc=await browser.navigate(origin+'/source',{tab:source,signal,deadline:Date.now()+3000}),contents=source.view.webContents;
      const owner=browser.operation,filename=path.join(profile,'original.bin');
      const registration=browser.sessionEvents.registerDownload({owner,attemptId:'physical-original',contents,frame:contents.mainFrame,document:doc,
        validate:()=>browser.documentCurrent(doc),filename,signal,deadline:Date.now()+5000,onItem:entry=>downloading.resolve(entry),onRejected:entry=>downloading.resolve({...entry,rejected:true})});
      await contents.executeJavaScript('document.querySelector("a").click();void 0',true);await downloading.promise;registration.dispose();
    });
    const native=await downloading.promise;await delay(30);assert.equal(sourceContents.isDestroyed(),false);assert.equal(physical(),3);
    let nextCreated=false;
    const next=task({...saved,service_id:'svc_'+'3'.repeat(32)},async()=>{await browser.reserveTaskPages(2,{signal,deadline:Date.now()+3000});await page('auxiliary');nextCreated=true;});
    await delay(30);assert.equal(nextCreated,false);assert.equal(physical(),3);finishSlow();
    assert.equal(await native.terminal,'completed');await transfer;await next;
    assert.equal(sourceContents.isDestroyed(),true);assert.equal(physical(),2);assert.equal(fs.statSync(path.join(profile,'original.bin')).size,8192);
    assert.deepEqual(requests.filter(request=>request.url==='/slow'),[{method:'GET',url:'/slow'}]);
    // Explicit user ownership is separate and bounded; automatic cleanup cannot acquire it by relabelling.
    const users=[];for(let index=0;index<16;index++)users.push(browser.createTab({present:false,user:true}));
    assert.throws(()=>browser.createTab({present:false,user:true}),/page_capacity/);assert.equal(physical(),18);
    await Promise.all(users.map(tab=>browser.closePage(tab,'user')));assert.equal(physical(),2);
    await browser.close();assert.equal(physical(),0);assert.equal(browser.sessionEvents.closed,true);
    console.log('PAGE RESOURCES PASS');
  }finally {finishSlow?.();await browser.close();host.destroy();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
