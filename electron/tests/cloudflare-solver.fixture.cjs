'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs/promises'),path=require('node:path');
const {execFile,spawn}=require('node:child_process'),{promisify}=require('node:util');
const assert=require('node:assert/strict');
const {createCloudflareSolver}=require('../src/browser/cloudflare-dispatch.cjs');
const {createInterface}=require('node:readline');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {PROJECT_ROOT}=require('../src/shared/paths.cjs');
const profile=process.argv[2];
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port','0');
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(check,message) {
  const end=Date.now()+10000;
  while(Date.now()<end){if(await check())return;await pause(50);}
  throw Error(message);
}
app.whenReady().then(async()=>{
  const host=new BrowserWindow({show:false,width:800,height:600});
  const browser=new BrowserRuntime({hostWindow:host});
  let worker,lines,ready=false,dispatch;
  try {
    await browser.ready;
    const frameURL='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/fixture';
    const pages=['https://fixture.invalid/challenge','https://challenges.cloudflare.com/challenge'];
    const widget=`<iframe width="400" height="240" src="${frameURL}"></iframe>`;
    const challenge=`<title>Just a moment...</title><script>window._cf_chl_opt={};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>`;
    browser.partition.protocol.handle('https',request=>{
      const url=new URL(request.url);
      const html=pages.includes(url.origin+url.pathname)?`<!doctype html>${url.searchParams.has('native')?widget.replace(frameURL,frameURL+'?native'):widget}`
        :url.origin==='https://challenges.cloudflare.com' && url.pathname===new URL(frameURL).pathname?
          url.searchParams.has('native')?'<input type="checkbox" style="width:60px;height:60px">':
          '<label style="display:block;width:180px;height:60px;background:#ddd"><input type="checkbox" style="opacity:0;width:30px;height:30px">Verify human</label>'
        :url.pathname==='/normal'?'<article><h1>Normal content</h1></article>':'';
      return new Response(html,{status:html?200:404,headers:{'Content-Type':'text/html'}});
    });
    const tabs=[browser.createTab({present:false,user:true}),browser.createTab({present:false,user:true})];
    const [port,browserPath]=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);
    const cdp='ws://127.0.0.1:'+port+browserPath;
    const python=process.env.ALLFOLD_SOLVER_TEST_PYTHON || path.join(PROJECT_ROOT,'.venv','bin','python');
    const script=[
      'import asyncio,json,sys','from threading import Event,Timer',
      'from allfold.logging_setup import configure_logging','configure_logging()',
      'from allfold.integrations.cloudflare_solver import solve_cloudflare','stop=Event()',
      'async def progress(result):',' if result["outcome"]=="clicked": print(json.dumps(result),flush=True); stop.set()',
      'timer=Timer(8,stop.set)','timer.start()',
      'try: asyncio.run(solve_cloudflare(sys.argv[1],stop,target_id=sys.argv[2],progress=progress))',
      'finally: timer.cancel()',
    ].join('\n');
    // Exact target isolation for native/styled controls in same-process and OOPIF frames.
    for(const page of pages) {
      for(const styled of [false,true]) {
        await Promise.all(tabs.map(tab=>tab.view.webContents.loadURL(page+(styled?'':'?native')+'#verification')));
        if(styled)await tabs[1].view.webContents.executeJavaScript(`document.body.insertAdjacentHTML('beforeend',
          '<div style="position:fixed;left:190px;top:110px;width:40px;height:40px;background:red;z-index:10"></div>')`);
        await until(()=>tabs.every(tab=>tab.view.webContents.mainFrame.framesInSubtree.some(item=>item.url===frameURL+(styled?'':'?native'))),'control frame loaded');
        const target=tabs[1].view.webContents.getOrCreateDevToolsTargetId();
        const {stdout}=await promisify(execFile)(python,['-c',script,cdp,target],
          {timeout:10000,env:{...process.env,PYTHONPATH:path.join(PROJECT_ROOT,'src')}});
        assert.ok(stdout.trim(),'the owned Cloudflare control must be clicked');
        assert.deepEqual(JSON.parse(stdout),{outcome:'clicked',reason:'checkbox_clicked'});
        const checked=await Promise.all(tabs.map(tab=>tab.view.webContents.mainFrame.framesInSubtree.find(item=>item.url===frameURL+(styled?'':'?native'))
          .executeJavaScript('document.querySelector("input").checked')));
        assert.deepEqual(checked,[false,true]);
      }
    }
    await Promise.all(tabs.map(tab=>tab.view.webContents.loadURL('https://fixture.invalid/normal')));
    const requests=[],replies=[],progress=[];
    worker=spawn(python,[path.join(PROJECT_ROOT,'tests/electron_solver_bridge_fixture.py'),cdp],
      {env:{...process.env,PYTHONPATH:path.join(PROJECT_ROOT,'src')},stdio:['pipe','pipe','pipe']});
    lines=createInterface({input:worker.stdout});let stderr='',fixtureComplete=false;
    worker.stderr.on('data',data=>{stderr+=data;});
    const send=message=>{requests.push(message);worker.stdin.write(JSON.stringify(message)+'\n');};
    dispatch=createCloudflareSolver({getBrowser:()=>browser,send,isBridgeReady:()=>ready});
    browser.solveCloudflare=dispatch;
    lines.on('line',line=>{
      const message=JSON.parse(line);
      if(message.type==='ready')ready=true;
      else if(message.type==='cloudflare_progress'){progress.push(message);dispatch.receive(message);}
      else if(message.type==='solve_cloudflare_result'){replies.push(message);dispatch.receive(message);}
      else if(message.type==='fixture_complete')fixtureComplete=true;
    });
    const exited=new Promise((resolve,reject)=>worker.once('exit',code=>code===0?resolve():reject(Error('Bridge fixture failed: '+stderr))));
    exited.catch(()=>{});
    send({token:'fixture-only'});await until(()=>ready,'Bridge ready');
    await pause(850);assert.equal(requests.filter(item=>item.type==='solve_cloudflare').length,0,'normal pages never invoke Pydoll');
    const install=async(tab,body)=>tab.view.webContents.executeJavaScript(`document.head.innerHTML=${JSON.stringify(challenge)};document.body.innerHTML=${JSON.stringify(body)}`);
    const clicked=tab=>progress.filter(item=>item.page_id===tab.id && item.data.outcome==='clicked').length;
    await Promise.all(tabs.map(tab=>tab.view.webContents.loadURL(pages[0])));
    await install(tabs[0],widget+'<button id="occluder" style="position:fixed;left:90px;top:30px;width:40px;height:40px;z-index:10" onclick="this.dataset.clicked=\'true\'">Cover</button>');
    await install(tabs[1],'');
    await until(()=>requests.filter(item=>item.type==='solve_cloudflare').length===2,'both independent tabs observe challenges without pending operations');
    assert.equal(browser.operations.size,0);
    // First discovery finds nothing, then a delayed closed shadow root and a hidden unrelated hCaptcha appear.
    await tabs[1].view.webContents.executeJavaScript(`const host=document.createElement('div');document.body.append(host);host.attachShadow({mode:'closed'}).innerHTML=${JSON.stringify(widget)};document.body.insertAdjacentHTML('beforeend','<iframe hidden src="https://newassets.hcaptcha.com/captcha"></iframe>')`);
    await until(()=>clicked(tabs[1])===1,'delayed shadow/OOPIF control clicked');
    assert.equal(clicked(tabs[0]),0,'long waiting tab cannot consume or receive the other target interaction');
    assert.equal(await tabs[0].view.webContents.executeJavaScript('!!document.querySelector("#occluder").dataset.clicked'),false,'covered controls must not click an unrelated parent button');
    assert.equal((await browser.inspectPage(tabs[1])).waiting,true,'click is not passage');
    await pause(800);assert.equal(clicked(tabs[1]),1,'unchanged control is not repeatedly clicked');
    await tabs[0].view.webContents.executeJavaScript('document.querySelector("#occluder").remove()');
    await until(()=>clicked(tabs[0])===1,'uncovering the actual point allows the same waiting control to proceed');
    // A replacement frame and history change stay on the original native target.
    await install(tabs[1],widget+`<iframe hidden src="${frameURL}?rebuilding"></iframe>`);
    await tabs[1].view.webContents.executeJavaScript('history.replaceState({},"","#replacement")');
    await until(()=>clicked(tabs[1])===2,'replacement frame retried');
    const recover=tab=>tab.view.webContents.executeJavaScript('document.head.innerHTML="<title>Article</title>";document.body.innerHTML="<article><h1>Accessible content</h1></article>"');
    await recover(tabs[1]);await until(()=>tabs[1].challenge.state==='recovered' && !tabs[1].challenge.active,'passage drains solver');
    assert.equal((await browser.waitForPage(tabs[1],{deadline:Date.now()+1500})).status,200);
    await install(tabs[1],widget);await until(()=>clicked(tabs[1])===3,'later independent challenge');
    const first=requests.find(item=>item.type==='solve_cloudflare' && item.page_id===tabs[1].id);
    const prior=tabs[1].challenge.state;
    dispatch.receive({...first,type:'cloudflare_progress',target_id:'f'.repeat(32),data:{outcome:'waiting',reason:'checkbox_ambiguous'}});
    dispatch.receive({...first,type:'cloudflare_progress',data:{outcome:'waiting',reason:'checkbox_ambiguous'}});
    assert.equal(tabs[1].challenge.state,prior,'wrong target and expired challenge IDs cannot change state');
    await browser.closePage(tabs[1]);assert.equal(tabs[1].challenge.active,null,'close joins real worker');
    // Retained Service page keeps its observer after its operation settles.
    const data={request_id:'retained-fixture',service_id:'svc_'+'1'.repeat(32),service_scope:{scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)},preparation_key:'d'.repeat(64)};
    let retained;
    await browser.runTask(new AbortController().signal,data,async()=>{
      retained=browser.createTab({present:false});browser.bindTaskPage(retained);
      await retained.view.webContents.loadURL('https://fixture.invalid/normal');browser.retainAccessPage(retained,data);
    });
    assert.equal(retained.taskOwner,null);await install(retained,widget);
    await until(()=>clicked(retained)===1,'retained Service challenge');
    await recover(retained);await until(()=>!retained.challenge.active,'retained passage');
    // Popup follows the same createTab observer even when its opener has no business owner.
    const created=new Promise(resolve=>browser.events.once('tab-created',(_event,tab)=>resolve(tab)));
    await retained.view.webContents.executeJavaScript('void window.open("https://fixture.invalid/normal","fixture-popup")');
    const popup=await created;await until(()=>popup.view.webContents.getURL().endsWith('/normal')&&!popup.view.webContents.isLoadingMainFrame(),'popup loaded');
    await install(popup,widget);await until(()=>clicked(popup)===1,'popup challenge');
    await browser.closePage(popup);
    // Renderer exit cancels real CDP work, and a later navigation can observe anew.
    const crashed=new Promise(resolve=>tabs[0].view.webContents.once('render-process-gone',resolve));
    tabs[0].view.webContents.forcefullyCrashRenderer();await crashed;
    await until(()=>!tabs[0].challenge.active,'renderer cleanup');
    await tabs[0].view.webContents.loadURL('https://fixture.invalid/normal');
    await install(tabs[0],'');
    await until(()=>!!tabs[0].challenge.active,'observer survives renderer replacement');
    await recover(tabs[0]);await until(()=>!tabs[0].challenge.active,'noninteractive auto passage');
    const canceled=new AbortController();let temporary;
    await browser.runTask(canceled.signal,{request_id:'temporary'},async()=>{
      temporary=browser.createTab({present:false});browser.bindTaskPage(temporary);
      await temporary.view.webContents.loadURL('https://fixture.invalid/normal');await install(temporary,widget);
      await until(()=>clicked(temporary)===1,'temporary page solver');canceled.abort();
    });
    assert.equal(temporary.challenge.active,null);assert.equal(browser.tabs.has(temporary.id),false);
    await browser.close();
    worker.stdin.end();await exited;assert.equal(fixtureComplete,true);
    console.log('CLOUDFLARE TARGET ISOLATION PASS');
  } finally {
    if(worker?.exitCode===null){ready=false;worker.stdin.end();await new Promise(resolve=>worker.once('exit',resolve));dispatch?.drained();}
    lines?.close();await browser.close();host.destroy();
  }
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
