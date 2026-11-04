'use strict';
// Production Runtime / Session / View and trusted IPC. Only synthetic loopback pages.
const {app,BrowserWindow,ipcMain}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {installBrowserIPC}=require('../src/browser/browser-ipc.cjs');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-browser-presentation-'));
app.setPath('userData',temp);app.commandLine.appendSwitch('disable-background-networking');
app.on('window-all-closed',()=>{}); // Cleanup owns the explicit success/failure exit code.
const source=path.resolve(__dirname,'../../frontend/ui'),index=fs.readFileSync(path.join(source,'index.html'),'utf8');
let pane=index.match(/  <section id="browser-pane"[\s\S]*?\n  <\/section>/)[0];
if(!pane.includes('id="browser-compact"'))pane=pane.replace('<div id="browser-tabs"','<button id="browser-compact" type="button">COMPACT</button><button id="browser-focus" type="button">FOCUS</button><div id="browser-tabs"');
const debug=index.match(/    <div id="layout-debug"[\s\S]*?\n    <\/div>/)[0];
const shell=`<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/style.css"><link rel="stylesheet" href="/workbench.css"><link rel="stylesheet" href="/workspace-layout.css">
<style>.masthead{height:56px;display:flex;align-items:center;gap:12px;padding:8px 12px}#kept-workspace{flex:1}#kept-main{display:flex;flex-direction:column;overflow:hidden}#kept-scope-status{flex:0 0 auto;padding:6px 8px;font-size:11px;line-height:18px}#kept-queue-body{overflow:auto;padding:12px}#kept-queue-body button{border:1px solid;padding:8px}footer{margin:0;min-height:35px}#run-page{padding:16px}dialog{max-width:90vw;max-height:85vh}.sidebar-scroll button{padding:8px;border:1px solid}</style></head>
<body data-workbench="allfold"><header class="masthead"><b>ALLFOLD</b><button id="fixture-kept">KEPT</button><button id="fixture-run">RUN</button><button id="fixture-dialog">DIALOG</button><button id="fixture-popover-open">POPOVER</button></header>
<div id="workbench-content"><div id="allfold-pane"><section id="kept-workspace" class="workbench-layout"><nav class="navigation-rail"><button id="fixture-directory" data-flyout="services" class="rail-button">☰</button></nav>
<aside id="fixture-flyout" class="navigation-flyout" hidden tabindex="-1"><div class="flyout-heading">SERVICES<button data-flyout-close>×</button></div><div data-flyout-list>${Array.from({length:24},(_,i)=>`<button>Service ${i}</button>`).join('')}</div></aside>
<main id="kept-main" class="workspace-content"><div id="kept-scope-status">Service A · batch A · 2 planned · 0 processed · waiting for manual input</div><div id="kept-queue-body"><p>Queue · Service A 2 / Service B 1 / Unassigned 1</p><button id="fixture-browser">BROWSER</button></div><div id="kept-browser-host" hidden></div></main>
<aside id="fixture-sidebar" class="functional-sidebar" hidden><div class="sidebar-resize" tabindex="0" role="separator"></div><div class="sidebar-heading">WORKFLOW<button data-sidebar-close>×</button></div><div class="sidebar-scroll" data-functional-view="workflow"><input id="fixture-draft" value="preserved"><button id="fixture-sidebar-action">Action</button></div></aside><nav class="tool-rail"><button id="fixture-workflow" class="rail-button" data-sidebar-view="workflow">⚙</button></nav></section>
<section id="run-page" hidden><h2>Run · Web of Science</h2><input id="fixture-run-draft" value="immutable query"><button id="fixture-task-page">查看任务页面</button><p id="fixture-run-progress">run-a · prepare-a · waiting</p></section></div>${pane}</div>
<footer><span id="browser-status"></span>${debug}</footer><div id="fixture-popover" popover="manual" style="position:fixed;inset:190px auto auto 60px;width:280px;height:100px;margin:0;background:var(--paper)">Trusted Popover<button id="fixture-popover-close">Close Popover</button></div><dialog id="fixture-modal"><h2>Trusted dialog</h2><input id="fixture-dialog-input"><button id="fixture-dialog-close">Close</button></dialog><dialog id="run-view"></dialog><dialog id="kept-flow"></dialog>
<script>window.workspaceNavigation={current:()=>window.fixtureWorkspace||'kept'};window.uiNext={notice:message=>{window.fixtureNotice=message},request:async()=>({scope:{scope_id:'fixture'},services:[{id:'service-a',name:'Service A'}]})};</script><script src="/workspace-layout-model.js"></script><script src="/workspace-layout.js"></script><script src="/workbench.js"></script>
<script>const $=id=>document.getElementById(id);window.fixtureLayout=allfoldLayout.create({root:$('kept-workspace'),workspace:'kept',minContentWidth:320});
window.addEventListener('workbench:browser-state',event=>{if(event.detail.source==='kept'){$('kept-browser-host').hidden=!event.detail.visible;$('kept-queue-body').hidden=event.detail.visible;}});
$('fixture-browser').onclick=()=>allfoldWorkbench.showKeptBrowser();$('fixture-task-page').onclick=()=>allfoldWorkbench.showTaskPage({workflowId:'run-a',source:'run'});
for(const page of ['kept','run'])$('fixture-'+page).onclick=()=>{allfoldWorkbench.hide();window.fixtureWorkspace=page;$('kept-workspace').hidden=page!=='kept';$('run-page').hidden=page!=='run';window.dispatchEvent(new Event('workspace-navigation-state'));};
$('fixture-dialog').onclick=()=>$('fixture-modal').showModal();$('fixture-dialog-close').onclick=()=>$('fixture-modal').close();$('fixture-popover-open').onclick=()=>$('fixture-popover').showPopover();$('fixture-popover-close').onclick=()=>$('fixture-popover').hidePopover();</script></body></html>`;
const challenge=`<!doctype html><html><head><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;font:16px/1.45 sans-serif;background:#f3f6fb;color:#17253d;padding:12px}main{max-width:700px}h1{font-size:18px;margin:0 0 8px}.challenge{border:2px solid #335b9b;background:white;padding:10px}input,button{font:inherit;min-height:32px;max-width:100%}label{display:block;margin:6px 0}button{padding:4px 10px}dialog{max-width:90vw;max-height:85vh}#long{height:650px;background:linear-gradient(#e8edf8,#c5d3ec);padding:12px}#result{font-weight:bold}</style></head><body><main><h1>Local synthetic challenge</h1><div class="challenge"><label><input id="human" type="checkbox"> Check the square</label><label>Code <input id="code" size="8" autocomplete="off"></label><button id="verify">Verify local code</button><button id="popup">Open local dialog</button><p id="result">Waiting for input</p></div><div id="long">Scroll to the final control</div><button id="bottom">Final control</button><p id="bottom-result"></p><dialog id="local-dialog"><h2>Local challenge dialog</h2><button id="close-dialog">Close dialog</button></dialog></main><script>window.fixtureLoad=crypto.randomUUID();window.fixtureChecks=0;document.cookie='synthetic_session=preserved; SameSite=Lax';human.onchange=()=>window.fixtureChecks++;verify.onclick=()=>result.textContent=human.checked&&code.value==='42'?'Synthetic challenge complete':'Try code 42';popup.onclick=()=>document.getElementById('local-dialog').showModal();document.getElementById('close-dialog').onclick=()=>document.getElementById('local-dialog').close();bottom.onclick=()=>document.getElementById('bottom-result').textContent='Final control clicked';</script></body></html>`;
const mimes={'.js':'text/javascript','.css':'text/css','.ttf':'font/ttf','.woff2':'font/woff2','.otf':'font/otf'};
let reloadResponseDelay=0;
const server=http.createServer((req,res)=>{
  const url=new URL(req.url,'http://fixture');
  if(url.pathname==='/'){const send=()=>{res.writeHead(200,{'Content-Type':'text/html'});res.end(shell);};if(reloadResponseDelay)setTimeout(send,reloadResponseDelay);else send();return;}
  if(url.pathname==='/challenge' || url.pathname==='/other'){res.writeHead(200,{'Content-Type':'text/html'});res.end(challenge);return;}
  const file=path.resolve(source,'.'+url.pathname);
  if(!file.startsWith(source+path.sep) || !fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':mimes[path.extname(file)] || 'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
let win,browser,disposeIPC,origin;const results=[];
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const assert=(ok,message)=>{if(!ok)throw Error(message);};
async function evaluate(contents,code){const value=await contents.executeJavaScript(`(async()=>{try{return {ok:true,value:await (${code})}}catch(error){return {ok:false,error:String(error.stack||error)}}})()`);if(!value.ok)throw Error(value.error);return value.value;}
const host=code=>evaluate(win.webContents,code),page=(tab,code)=>evaluate(tab.view.webContents,code);
async function ready(check,label){for(let i=0;i<160;i++){if(await check())return;await wait(25);}throw Error('Timed out: '+label);}
async function click(contents,selector){const point=await evaluate(contents,`(()=>{const element=document.querySelector(${JSON.stringify(selector)});element.scrollIntoView({block:'nearest',inline:'nearest'});const r=element.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`),zoom=contents.getZoomFactor();contents.sendInputEvent({type:'mouseDown',button:'left',clickCount:1,x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});contents.sendInputEvent({type:'mouseUp',button:'left',clickCount:1,x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});await wait(45);}
async function key(contents,keyCode,modifiers=[]){contents.sendInputEvent({type:'keyDown',keyCode,modifiers});if(keyCode==='Enter')contents.sendInputEvent({type:'char',keyCode:'\r',modifiers});contents.sendInputEvent({type:'keyUp',keyCode,modifiers});await wait(30);}
async function capture(name,tab){if(!process.env.ALLFOLD_BROWSER_SCREENSHOTS)return;const directory=process.env.ALLFOLD_BROWSER_SCREENSHOTS;fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(path.join(directory,name+'.png'),(await win.webContents.capturePage()).toPNG());if(tab)fs.writeFileSync(path.join(directory,name+'-page.png'),(await tab.view.webContents.capturePage()).toPNG());}
async function bounds(label){await host("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))");await ready(async()=>{const current=await host("(()=>{const r=document.getElementById('browser-body').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()"),reported=browser.presentation.bounds;return browser.presentation.mounted&&reported&&Object.keys(current).every(key=>Math.abs(current[key]-reported[key])<1);},'native matches measured host');const rect=browser.selected.view.getBounds();results.push({label,window:win.getContentSize(),hostZoom:win.webContents.getZoomFactor(),viewport:rect});return rect;}
async function size(width,height){win.setSize(width,height);await ready(async()=>{const actual=await host('({width:innerWidth,height:innerHeight})');return Math.abs(actual.width*win.webContents.getZoomFactor()-win.getContentSize()[0])<2&&Math.abs(actual.height*win.webContents.getZoomFactor()-win.getContentSize()[1])<2;},'window resize');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'resized native mounted');}
async function target(name,value){await host(`(()=>{const input=document.getElementById('layout-${name}');input.value=${JSON.stringify(String(value))};input.dispatchEvent(new Event('input',{bubbles:true}));})()`);await wait(40);}
app.whenReady().then(async()=>{
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
    win=new BrowserWindow({width:1200,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,partition:'browser-presentation-host',preload:path.join(__dirname,'../src/preload/preload.cjs')}});
    browser=new BrowserRuntime({hostWindow:win});await browser.ready;
    for(const partition of [win.webContents.session,browser.partition])partition.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(details,callback)=>callback({cancel:new URL(details.url).origin!==origin}));
    disposeIPC=installBrowserIPC({ipcMain,hostWindow:win,origin,browser});await win.loadURL(origin+'/');
    // Native child Views need a compositor surface for real input and capture on macOS.
    win.show();win.focus();await ready(()=>Promise.resolve(win.isFocused()),'fixture Window focus');
    await ready(()=>host('!!window.allfoldWorkbench'),'shell');
    const tab=browser.createTab({present:false});await tab.view.webContents.loadURL(origin+'/challenge');
    browser.beginOperation(new AbortController().signal,{workflow_id:'run-a',task_id:'prepare-a',request_id:'request-a'});browser.associatePage(tab,{role:'wos-query'});browser.bindTaskPage(tab);
    const id=tab.id,session=tab.view.webContents.session,load=await page(tab,'fixtureLoad');
    await click(win.webContents,'#fixture-browser');await bounds('wide compact default');
    await host("document.getElementById('kept-flow').show()");
    assert(await host("document.getElementById('kept-flow').open&&getComputedStyle(document.getElementById('kept-flow')).visibility==='hidden'"),'Kept fullscreen surface covers task Browser');
    await capture('wide-compact-default',tab);
    // Mouse and keyboard go through Chromium's input path, never element.click().
    await click(tab.view.webContents,'#human');assert(await page(tab,'human.checked'),'mouse could not check synthetic challenge');
    await key(tab.view.webContents,'Tab');assert(await page(tab,"document.activeElement.id==='code'"),'Tab did not enter code field');
    await key(tab.view.webContents,'Tab',['shift']);assert(await page(tab,"document.activeElement.id==='human'"),'Shift+Tab did not restore checkbox');
    await key(tab.view.webContents,'Tab');await tab.view.webContents.insertText('42');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');
    assert(await page(tab,"result.textContent==='Synthetic challenge complete'"),'keyboard could not submit local challenge: '+JSON.stringify(await page(tab,'({active:document.activeElement.id,code:code.value,result:result.textContent})')));
    await click(tab.view.webContents,'#popup');assert(await page(tab,"document.getElementById('local-dialog').open"),'local webpage dialog did not open');await key(tab.view.webContents,'Escape');
    assert(!(await page(tab,"document.getElementById('local-dialog').open")),'Escape did not close local webpage dialog');
    // Each chosen Compact height is actually measured. Defaults are evaluated against these.
    for(const height of [140,240,300,420]){await target('browserPreferredHeight',height);const rect=await bounds('wide compact height '+height);assert(rect.height===height,'Compact height preference was not effective: '+JSON.stringify(rect));}
    await target('browserPreferredWidth',320);await target('browserPreferredHeight',140);await bounds('narrow flat compact 320x140');
    await page(tab,'scrollTo(0,0)');await click(tab.view.webContents,'#human');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');
    assert(await page(tab,"result.textContent==='Try code 42'"),'flat Compact did not scroll keyboard focused submit into view');
    await key(tab.view.webContents,'Tab',['shift']);await key(tab.view.webContents,'Tab',['shift']);await key(tab.view.webContents,'Space');
    await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');
    assert(await page(tab,"human.checked&&result.textContent==='Synthetic challenge complete'"),'flat Compact checkbox / keyboard flow failed');await capture('flat-320x140',tab);
    await target('browserPreferredWidth',640);await target('browserPreferredHeight',240);await host("document.getElementById('layout-save').click()");
    const compactWide=await bounds('wide compact 640x240');await click(win.webContents,'#browser-focus');const focusWide=await bounds('wide Focus');
    assert(focusWide.height>compactWide.height&&focusWide.width>compactWide.width,'Focus did not use available main area');await capture('wide-focus',tab);
    await click(win.webContents,'#browser-compact');const restoredWide=await bounds('wide restored compact');assert(restoredWide.width===compactWide.width&&restoredWide.height===compactWide.height,'RESTORE changed Compact preference');
    await host("document.getElementById('layout-origin').click()");assert(await host('allfoldLayout.targets().browserPreferredHeight===300'),'ORIGIN');
    await host("document.getElementById('layout-reset').click()");assert(await host('allfoldLayout.targets().browserPreferredWidth===640&&allfoldLayout.targets().browserPreferredHeight===240'),'RESET');
    await size(600,480);let rect=await bounds('600x480 compact');assert(rect.width>=320&&rect.height>=140,'600x480 Compact is not operable: '+JSON.stringify(rect));
    assert(await host("allfoldLayout.targets().browserPreferredWidth===640&&allfoldLayout.targets().browserPreferredHeight===240"),'constraint overwrote preferred dimensions');
    await capture('600x480-compact',tab);
    await click(win.webContents,'#browser-focus');const focus=await bounds('600x480 focus');assert(focus.height>=rect.height,'Focus made viewport smaller');
    await capture('600x480-focus',tab);await click(win.webContents,'#browser-compact');await bounds('600x480 restored compact');
    tab.view.webContents.sendInputEvent({type:'mouseWheel',x:100,y:80,deltaY:-650,deltaX:0,canScroll:true});await ready(()=>page(tab,'scrollY>100'),'native webpage scroll');
    await page(tab,"document.getElementById('bottom').scrollIntoView()");await click(tab.view.webContents,'#bottom');assert(await page(tab,"document.getElementById('bottom-result').textContent==='Final control clicked'"),'scrolled control unreachable');
    const focusedBeforeOverlay=await page(tab,'document.activeElement.id');
    // Existing Layout Host opens trusted overlays and notifies Browser before rendering them.
    await click(win.webContents,'#fixture-directory');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'Flyout occlusion');
    assert(await host("!document.getElementById('fixture-flyout').hidden"),'Flyout did not open');await capture('600x480-flyout');
    await key(win.webContents,'Escape');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Flyout restore');
    await click(win.webContents,'#fixture-workflow');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'Sidebar occlusion');
    await capture('600x480-sidebar');await click(win.webContents,'[data-sidebar-close]');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Sidebar restore');
    await click(win.webContents,'#fixture-dialog');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'Dialog occlusion');
    await capture('600x480-dialog');await click(win.webContents,'#fixture-dialog-close');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Dialog restore');
    await click(win.webContents,'#fixture-popover-open');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'Popover occlusion');await click(win.webContents,'#fixture-popover-close');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Popover restore');
    assert(await page(tab,'fixtureLoad')===load&&await page(tab,'human.checked&&code.value===\'42\'')&&await page(tab,'document.activeElement.id')===focusedBeforeOverlay,'overlay changed page or focused form');
    // Another existing page can be selected and restored; no new Runtime / Session.
    const other=browser.createTab({present:false});await other.view.webContents.loadURL(origin+'/other');
    await click(win.webContents,`#browser-tabs [data-page-id="${other.id}"] button`);assert(browser.selected===other,'page switch');
    await click(win.webContents,`#browser-tabs [data-page-id="${id}"] button`);assert(browser.selected===tab,'page restore');
    await click(win.webContents,'#browser-return');assert(await host("!document.getElementById('kept-queue-body').hidden&&document.activeElement.id==='fixture-browser'"),'Queue/focus return');assert(!browser.presentation.mounted,'Queue intercepted by native view');
    assert(await host("document.getElementById('kept-flow').open&&getComputedStyle(document.getElementById('kept-flow')).visibility==='visible'"),'Kept fullscreen task not restored');await host("document.getElementById('kept-flow').close()");
    await click(win.webContents,'#fixture-run');await host("(()=>{const dialog=document.getElementById('run-view');dialog.append(document.getElementById('fixture-task-page'));dialog.show()})()");
    await click(win.webContents,'#fixture-task-page');await bounds('Run task Focus');assert(browser.selected===tab,'Run selected unrelated page');
    await capture('run-task-focus',tab);await click(win.webContents,'#browser-return');assert(await host("document.activeElement.id==='fixture-task-page'&&document.getElementById('fixture-run-draft').value==='immutable query'&&document.getElementById('run-view').open&&getComputedStyle(document.getElementById('run-view')).visibility==='visible'"),'Run draft/focus lost');await host("document.getElementById('run-view').close()");
    await host("allfoldWorkbench.showTaskPage({workflowId:'missing',source:'run'})");assert(!browser.presentation.mounted&&await host("fixtureNotice.includes('尚无')"),'missing task page did not remain a no-op');
    await click(win.webContents,'#fixture-kept');await click(win.webContents,'#fixture-browser');await size(1400,900);await bounds('wide restored preference');
    assert(await host('allfoldLayout.targets().browserPreferredWidth===640'),'wide restore lost preference');
    win.webContents.setZoomFactor(1.25);await size(600,480);rect=await bounds('600x480 zoom 1.25');
    assert(rect.x>=0&&rect.y>=0&&rect.x+rect.width<=600&&rect.y+rect.height<=480&&rect.height>=140,'zoomed native rectangle escapes content or is unusably short');
    await page(tab,'scrollTo(0,0)');await click(tab.view.webContents,'#human');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');assert(await page(tab,"result.textContent==='Try code 42'"),'zoomed Compact input failed');await capture('600x480-zoom-125',tab);
    await click(win.webContents,'#browser-focus');await bounds('600x480 zoom 1.25 Focus');await page(tab,'scrollTo(0,0)');await capture('600x480-zoom-125-focus',tab);
    assert(tab.id===id&&tab.view.webContents.session===session&&await page(tab,'fixtureLoad')===load,'presentation recreated the page/session');
    assert((await session.cookies.get({url:origin})).some(cookie=>cookie.name==='synthetic_session'&&cookie.value==='preserved'),'presentation lost Session cookie');
    // Host reload restores saved target values, while native Page identity survives.
    await win.reload();await ready(()=>host('!!window.allfoldWorkbench'),'reload');assert(await host('allfoldLayout.targets().browserPreferredWidth===640&&allfoldLayout.targets().browserPreferredHeight===240'),'restart preference restore');
    await host("localStorage.setItem('allfold.workbench-layout',JSON.stringify({browserPreferredWidth:-1,browserPreferredHeight:'bad'}))");await win.reload();await ready(()=>host('!!window.allfoldWorkbench'),'invalid storage reload');
    assert(await host('allfoldLayout.targets().browserPreferredWidth===960&&allfoldLayout.targets().browserPreferredHeight===300'),'invalid storage did not fall back');
    // Keep the old document alive while a real resize requests its final layout.
    reloadResponseDelay=200;
    for(let index=0;index<3;index++){
      await host('window.fixtureReloadPending=true');
      win.webContents.once('did-start-navigation',()=>win.setSize(1180+index*10,800));
      win.reload();await ready(()=>host('!window.fixtureReloadPending&&!!window.allfoldWorkbench'),'committed host reload');
      await ready(()=>Promise.resolve(!browser.presentation.visible&&!browser.presentation.mounted),'new host hides old native presentation');
      await host('allfoldWorkbench.showKeptBrowser()');await bounds('host reload with final old-document layout '+index);
    }
    assert(browser.selected.id===id&&browser.selected.view.webContents.session===session&&await page(tab,'fixtureLoad')===load,'host reload stress recreated the Page/Session');
    if(process.env.ALLFOLD_BROWSER_SCREENSHOTS)fs.writeFileSync(path.join(process.env.ALLFOLD_BROWSER_SCREENSHOTS,'measurements.json'),JSON.stringify(results,null,2)+'\n');
    console.log(JSON.stringify(results));console.log('BROWSER PRESENTATION DOM PASS');
  }catch(error){console.error('PRESENTATION FAILURE',JSON.stringify({windowFocused:win?.isFocused(),sequence:browser?.presentation.sequence,visible:browser?.presentation.visible,mounted:browser?.presentation.mounted?.id}));console.error(error.stack);process.exitCode=1;}
  finally{disposeIPC?.();browser?.close();win?.destroy();await new Promise(resolve=>server.close(resolve));fs.rmSync(temp,{recursive:true,force:true});app.exit(process.exitCode||0);}
});
