'use strict';
// The shipped, built index + controllers, isolated API responses and production native Browser.
const {app,BrowserWindow,ipcMain}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs'),{installBrowserIPC}=require('../src/browser/browser-ipc.cjs');
const {fixtureDiagnostics}=require('./browser-dom-diagnostics.cjs');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-browser-workspaces-'));
app.setPath('userData',temp);app.commandLine.appendSwitch('disable-background-networking');app.commandLine.appendSwitch('force-prefers-reduced-motion','reduce');
app.on('window-all-closed',()=>{}); // Cleanup owns the explicit success/failure exit code.
const ui=path.resolve(__dirname,'../../src/allfold/web/static/ui_next'),serviceId='svc_'+'a'.repeat(32),scope={scope_id:'a'.repeat(64),config_revision:'b'.repeat(64),user_state_revision:'c'.repeat(64)};
const services=[{id:serviceId,name:'Synthetic Service A',access_method:'manual',access_url:''}];
const journals=[{name:'Synthetic Journal',issn:'0000-0001',group:'Synthetic Group',labels:'',access_service_id:serviceId}];
const cover_search={phase:'Idle',busy:false,supported:false};
const settings={csrf_token:'fixture',issues:[],covers:{},cover_search,saved_workspace:'/fixture/workspace',values:{
  name:'Synthetic Monitor',keyword_expression:'causal',from_month:'2026-01',to_month:'2026-01',output_dir:'workspace',log_level:'INFO',
  monitor_revision_exists:'1',monitor_revision_digest:'b'.repeat(64),journal_revision_exists:'1',journal_revision_digest:'c'.repeat(64),
  institution_name:'',institution_idp_entity_id:'',auto_import_after_preparation:false,transition_delay_seconds:'3',display_name:'Synthetic researcher',
  zotero_target:{server_id:'SyntheticServer',library_type:'user',library_id:'0',collection_key:null},
  provider_aliases:{},provider_order:['pubmed','openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv','wos'],enabled_providers:['pubmed','openalex'],groups:['Synthetic Group'],custom_labels:[],journals,access_services:services,
}};
const paper={id:'paper-1',title:'Synthetic kept paper',doi:'10.5555/presentation',publication_date:'2026-10-01',status:'kept',abstract:'Synthetic fixture only',authors:[],enrichPhase:'Idle'};
const record={key:'0000-0001',...journals[0],labels:[],papers:[]};
const workspace={csrf_token:'fixture',import_token:'fixture',issues:[],counts:{candidates:0,active_journals:1},subjects:[{name:'Synthetic Group',journals:[record]}],kept:{papers:[{paper,journal:record}],journals:[record],services,settings:{},titles:{'paper-1':paper.title}}};
const queue={unprepared_services:[services[0]],services:[{id:'all',name:'All Services',kept:1,eligible:1},{id:serviceId,name:services[0].name,kept:1,eligible:1},{id:'unassigned',name:'Unassigned',kept:0,eligible:0},{id:'ambiguous',name:'Ambiguous',kept:0,eligible:0}],papers:[{paper_id:'paper-1',title:paper.title,doi:paper.doi,service_id:serviceId,assignment:'assigned',reason:''}],import_token:'fixture'};
let loginState={active:false,phase:'idle',scope,carsi:{status:'Not prepared'},services:services.map(service=>({...service,preparation:{status:'Not prepared'}}))};
let keptState={active:false,phase:'idle',navigation:null,can_cancel:false},runActive=false;
const runData=()=>({active:runActive,snapshot:{status:runActive?'RUNNING':'IDLE',provider:'integrated',task_id:'run-a',browser_active:runActive,waiting_for_user:runActive},progress:{stage_label:'Waiting for synthetic challenge',elapsed_text:'2s',announcement_message:'Local fixture only'},providers:Object.fromEntries(['integrated','wos'].map(id=>[id,{enabled:true,message:'',snapshot:{status:id==='wos'&&runActive?'RUNNING':'IDLE'},result_summary:null}]))});
const requests=[],workspaceReads={started:0,inFlight:0,lastCandidateIds:[]};
const challenge=`<!doctype html><html><head><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;padding:10px;font:16px/1.4 sans-serif;background:#f2f5fb;color:#192942}h1{font-size:18px;margin:0 0 8px}.box{border:2px solid #4a68a0;background:white;padding:8px}label{display:block;margin:4px 0}input,button{font:inherit;min-height:30px;max-width:100%}#result{font-weight:bold}#long{height:700px;background:linear-gradient(#edf2fa,#c5d3e8)}</style></head><body><h1>Local synthetic challenge</h1><form class="box"><label><input id="human" type="checkbox"> Check square</label><label>Code <input id="code" size="5"></label><button id="verify">Verify code</button><output id="result">Waiting</output></form><div id="long">Scroll to final control</div><button id="bottom">Final control</button><p id="bottom-result"></p><script>window.fixtureLoad=crypto.randomUUID();document.cookie='synthetic_session=preserved; SameSite=Lax';document.querySelector('form').onsubmit=event=>{event.preventDefault();result.textContent=human.checked&&code.value==='42'?'Synthetic challenge complete':'Try code 42'};bottom.onclick=()=>document.getElementById('bottom-result').textContent='Clicked';</script></body></html>`;
const mimes={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.mp4':'video/mp4'};
const server=http.createServer(async(req,res)=>{
  const url=new URL(req.url,'http://fixture'),route=url.pathname;
  if(route==='/challenge'){res.writeHead(200,{'Content-Type':'text/html'});res.end(challenge);return;}
  if(route==='/background-layout'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<iframe style="width:100%;border:0" src="/checkbox-frame"></iframe>');return;}
  if(route==='/checkbox-frame'){res.writeHead(200,{'Content-Type':'text/html'});res.end('<input type="checkbox">');return;}
  if(route.startsWith('/api/')||route==='/settings/covers/search'){
    let body='';for await(const chunk of req)body+=chunk;requests.push({route,body:body?JSON.parse(body):null});
    if(route==='/api/login/start')loginState={...loginState,phase:'completed',
      services:services.map(service=>({...service,preparation:{status:'Needs attention',reason:'manual_action_required'}}))};
    if(route==='/api/kept-workflow/start')keptState={workflow_id:'kept-a',generation:7,planned_total:1,
      batch:{total:1,task_id:'import-a',results:[{paper_id:'paper-1',service_id:serviceId,
        parent_outcome:'not_saved',outcome:'skipped',reason:'Unprepared Service skipped'}]},
      phase:'completed',active:false,can_cancel:false,message:'Local synthetic Import settled'};
    const data=route.startsWith('/api/login/')?loginState:route==='/api/ui-next/workspace'?workspace:route==='/api/ui-next/settings'?settings:route==='/api/kept-workflow/queue'?queue:
      route==='/api/ui-next/browser-services'?{scope,services}:route.startsWith('/api/ui-next/run')&&!route.endsWith('expression')?runData():
      route==='/api/ui-next/run-expression'?{providers:Object.fromEntries([...settings.values.provider_order,'integrated'].map(id=>[id,{expression:'causal',error:null}]))}:
      route==='/api/kept-workflow/state'||route==='/api/kept-workflow/start'||route==='/api/kept-workflow/cancel'||route==='/api/kept-workflow/acknowledge'?keptState:route==='/settings/covers/search'?cover_search:
      route.includes('/history')?{records:[]}:route.includes('/institutions')?{institutions:[]}:{};
    if(route==='/api/ui-next/workspace'){workspaceReads.started++;workspaceReads.inFlight++;workspaceReads.lastCandidateIds=record.papers.map(paper=>paper.id);res.once('finish',()=>{workspaceReads.inFlight--;});}
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
  }
  const relative=route==='/'?'index.html':decodeURIComponent(route.replace(/^\/static\/ui_next\//,'')),file=path.resolve(ui,relative);
  if(!file.startsWith(ui+path.sep)||!fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':mimes[path.extname(file)]||'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
let win,browser,disposeIPC,origin,tab,failed=false;const measurements=[],nativeUpdates=[];
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms)),assert=(ok,message)=>{if(!ok)throw Error(message);};
async function evaluate(contents,code){const result=await contents.executeJavaScript(`(async()=>{try{return {ok:true,value:await (${code})}}catch(error){return {ok:false,error:String(error.stack||error)}}})()`);if(!result.ok)throw Error(result.error);return result.value;}
const host=code=>evaluate(win.webContents,code),page=code=>evaluate(tab.view.webContents,code);
const diagnostics=()=>fixtureDiagnostics(win,browser,{workspaceReads,requests});
async function ready(check,label){for(let i=0;i<240;i++){if(await check())return;await wait(25);}throw Error('Timed out '+label+'; '+JSON.stringify(await diagnostics()));}
async function click(contents,selector){app.focus({steal:true});win.focus();await ready(()=>Promise.resolve(win.isFocused()),'native input focus');await evaluate(contents,'new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');const point=await evaluate(contents,`(()=>{const element=document.querySelector(${JSON.stringify(selector)});element.scrollIntoView({block:'nearest',inline:'nearest'});const r=element.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`),zoom=contents.getZoomFactor();contents.sendInputEvent({type:'mouseMove',x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});for(const type of ['mouseDown','mouseUp'])contents.sendInputEvent({type,button:'left',clickCount:1,x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});await wait(55);}
async function key(contents,keyCode,modifiers=[]){contents.sendInputEvent({type:'keyDown',keyCode,modifiers});if(keyCode==='Enter')contents.sendInputEvent({type:'char',keyCode:'\r',modifiers});contents.sendInputEvent({type:'keyUp',keyCode,modifiers});await wait(25);}
async function measured(label){await host('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await ready(async()=>{const r=await host("document.getElementById('browser-body').getBoundingClientRect().toJSON()"),reported=browser.presentation.bounds;return browser.presentation.mounted&&reported&&['x','y','width','height'].every(name=>Math.abs(r[name]-reported[name])<1);},label);const value={label,window:win.getBounds(),content:win.getContentSize(),zoom:win.webContents.getZoomFactor(),viewport:tab.view.getBounds()};measurements.push(value);return value.viewport;}
async function size(width,height){win.setSize(width,height);await ready(async()=>{const actual=await host('({width:innerWidth,height:innerHeight})'),zoom=win.webContents.getZoomFactor(),content=win.getContentSize();return Math.abs(actual.width*zoom-content[0])<2&&Math.abs(actual.height*zoom-content[1])<2;},'resize');}
async function capture(name){const directory=process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS;if(!directory)return;fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(path.join(directory,name+'.png'),(await win.webContents.capturePage()).toPNG());if(browser.presentation.mounted)fs.writeFileSync(path.join(directory,name+'-page.png'),(await tab.view.webContents.capturePage()).toPNG());}
async function completeChallenge(){await page('scrollTo(0,0)');const checked=await page('human.checked');await click(tab.view.webContents,'#human');if(checked)await key(tab.view.webContents,'Space');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Tab',['shift']);assert(await page("document.activeElement.id==='human'"),'Shift+Tab focus');await key(tab.view.webContents,'Tab');await tab.view.webContents.insertText('42');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');assert(await page("result.textContent==='Synthetic challenge complete'"),'constrained challenge did not complete');}
app.whenReady().then(async()=>{
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
    win=new BrowserWindow({width:1200,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,partition:'browser-workspaces-host',preload:path.join(__dirname,'../src/preload/preload.cjs')}});
    browser=new BrowserRuntime({hostWindow:win,isTaskRunning:()=>keptState.active||runActive});await browser.ready;const update=browser.setPresentation.bind(browser);browser.setPresentation=value=>{nativeUpdates.push({...value});return update(value)};
    for(const partition of [win.webContents.session,browser.partition])partition.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(details,callback)=>callback({cancel:new URL(details.url).origin!==origin}));
    ipcMain.handle('cas:status',()=>({available:false,configured:false,revision:'fixture'}));disposeIPC=installBrowserIPC({ipcMain,hostWindow:win,origin,browser});await win.loadURL(origin+'/');win.show();app.focus({steal:true});win.focus();await ready(()=>Promise.resolve(win.isFocused()),'fixture Window focus');
    await ready(()=>host("window.uiWorkspace?.ready()&&!document.getElementById('settings-open').disabled&&document.querySelectorAll('#s-journals [data-journal]').length===1"),'shipped UI ready');
    assert(await host("Array.from(document.querySelectorAll('.view-nav > button .nav-label'),node=>node.textContent).join('|')==='WORKSPACE|WORKFLOWS|JOURNALS|SETTINGS'"),'top-level Workflows navigation');
    const type=async value=>host(`Object.assign(document.getElementById('s-search'),{value:${JSON.stringify(value)}}).dispatchEvent(new Event('input'))`);
    const search=async value=>{await click(win.webContents,'#search-open');await ready(()=>host("document.activeElement.id==='s-search'"),'Quick Open focus');await type(value);};
    await click(win.webContents,'#settings-open');
    await search('Synthetic');
    for(const kind of ['Paper','Journal','Service']){
      await ready(()=>host(`Array.from(document.querySelectorAll('#workspace-search-results [role=option] small')).some(node=>node.textContent.startsWith('${kind}'))`),kind+' in global Search');
    }
    await type('> History');
    assert(await host("document.querySelectorAll('#workspace-search-results [role=option]').length===1"),'command search mixed in other results');
    await key(win.webContents,'Enter');
    await ready(()=>host("document.getElementById('history-dialog').open"),'Search runs a registered command');
    await click(win.webContents,'#history-close');
    await search('Synthetic Journal 0000-0001');await key(win.webContents,'Enter');
    await ready(()=>host("workspaceNavigation.current()==='journals'&&!document.querySelector('#s-journals-page .functional-sidebar').hidden"),'journal search opens Details');
    await host("window.addEventListener('workflow-service-selected',event=>window.selectedService=event.detail.serviceId)");
    await search('Synthetic Service A');await key(win.webContents,'Enter');
    await ready(()=>host(`workspaceNavigation.current()==='login'&&window.selectedService===${JSON.stringify(serviceId)}`),'service search opens Login');
    await ready(()=>host(`document.activeElement.dataset.serviceId===${JSON.stringify(serviceId)}`),'Service result focuses its Login row');
    await click(win.webContents,'#login-start');
    await ready(()=>host("document.getElementById('login-services').textContent.includes('Needs attention')"),'Login presents the Service result');
    assert(requests.filter(request=>request.route==='/api/login/start').length===1,'Login did not submit one explicit task');
    await search('Synthetic kept paper');await key(win.webContents,'Enter');
    await ready(()=>host("workspaceNavigation.current()==='workspace'&&document.getElementById('view-paper-title').textContent==='Synthetic kept paper'"),'paper search opens Reader');
    const background=browser.createTab({present:false});await background.view.webContents.loadURL(origin+'/background-layout');
    assert(await background.view.webContents.executeJavaScript('(()=>{const frame=document.querySelector("iframe"),box=frame.contentDocument.querySelector("input"),rect=box.getBoundingClientRect();return innerWidth>0&&innerHeight>0&&frame.contentDocument.elementFromPoint(rect.x+rect.width/2,rect.y+rect.height/2)===box;})()'),'background responsive checkbox has no usable viewport');
    assert(browser.selected===null&&!browser.presentation.mounted,'background layout selected or presented a Page');await browser.command({action:'close',id:background.id});
    tab=browser.createTab({present:false});await tab.view.webContents.loadURL(origin+'/challenge');const id=tab.id,session=tab.view.webContents.session,load=await page('fixtureLoad');
    const sameSite=browser.createTab({present:false});await sameSite.view.webContents.loadURL(origin+'/challenge');
    await sameSite.view.webContents.executeJavaScript("document.title='Unassigned Local Page'");
    browser.beginOperation(new AbortController().signal,{workflow_id:'login-a',task_id:'prepare-a',request_id:'request-login',service_id:serviceId,service_scope:scope});
    browser.associatePage(tab,{role:'service-target'});browser.endTask();
    const portal=browser.createTab({present:false});
    browser.beginOperation(new AbortController().signal,{workflow_id:'login-a',task_id:'carsi-a',request_id:'request-carsi'});
    browser.associatePage(portal,{role:'carsi-portal'});browser.endTask();
    await page("document.title='Synthetic Service Page'");
    await search('Synthetic Service Page');await key(win.webContents,'Enter');
    let rect=await measured('shipped wide Focus');
    assert(browser.selected===tab&&rect.width>=700&&rect.height>=400,'Search did not mount the selected tab in Focus');
    await completeChallenge();await capture('shipped-wide-focus');
    await click(win.webContents,'#browser-tabs-toggle');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'grouped Tabs flyout');
    const groups=await host("Array.from(document.querySelectorAll('#browser-tabs details > summary'),node=>node.textContent)");
    assert(groups.join('|')==='CARSI|Synthetic Service A|Other','Tabs did not group by saved identity and role: '+groups.join('|'));
    assert(await host(`document.querySelector('#browser-tabs [data-group-key="other"] [data-page-id="${sameSite.id}"]')!==null`),'ordinary tab was classified by its URL');
    const selectedGroup=`#browser-tabs [data-service-id="${serviceId}"]`;
    await click(win.webContents,selectedGroup+' > summary');
    assert(await host(`!document.querySelector('${selectedGroup}').open`),'Service group did not collapse');
    await key(win.webContents,'Escape');
    await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Tabs dismissal restores native Page');
    assert(await host("document.activeElement.id==='browser-tabs-toggle'"),'Tabs dismissal did not restore trigger focus');
    await click(win.webContents,'#search-open');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'Search suspends native Page');
    await capture('shipped-quick-open');await key(win.webContents,'Escape');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'Search restores native Page');
    await click(win.webContents,'#history-open');await ready(()=>Promise.resolve(browser.presentation.suspended&&!browser.presentation.mounted),'History suspends native Page');
    await click(win.webContents,'#history-close');await ready(()=>Promise.resolve(!!browser.presentation.mounted),'History restores native Page');
    win.webContents.setZoomFactor(1.25);await size(600,480);rect=await measured('shipped 600x480 Zoom 1.25 Focus');
    assert(rect.height>=180&&rect.width>=300,'zoomed Focus viewport unusable '+JSON.stringify(rect));
    await page("code.value='' ");await completeChallenge();await page('scrollTo(0,0)');await capture('shipped-600x480-zoom125-complete');
    await click(win.webContents,'#browser-return');await ready(()=>host("workspaceNavigation.current()==='workspace'&&document.getElementById('view-paper-title').textContent==='Synthetic kept paper'"),'Browser returns to the same Paper');
    win.webContents.setZoomFactor(1);await size(1200,800);
    await click(win.webContents,'#workflows-open');await click(win.webContents,'#workflow-nav [data-workflow="kept"]');
    await ready(()=>host("workspaceNavigation.current()==='kept'&&!document.getElementById('kept-workspace').hidden"),'Import Workflows page');
    await click(win.webContents,'#browser-open');await measured('shipped Import Focus');
    await click(win.webContents,'#browser-return');assert(await host("workspaceNavigation.current()==='kept'&&document.activeElement.id==='browser-open'"),'Import page return focus');
    await ready(()=>host("!document.getElementById('kept-start').disabled"),'Import is ready');
    await click(win.webContents,'#kept-start');
    await ready(()=>host("document.getElementById('kept-confirm').open"),'Import asks about unprepared Services');
    assert(!requests.some(request=>request.route==='/api/kept-workflow/start'),'Import dispatched before explicit skip');
    await click(win.webContents,'#kept-continue');
    await ready(()=>host("document.getElementById('kept-progress').textContent.includes('已跳过 1')"),'Import displays skipped count');
    const importRequest=requests.find(request=>request.route==='/api/kept-workflow/start')?.body;
    assert(importRequest?.skip_unprepared?.join()===serviceId&&!Object.hasOwn(importRequest,'mode'),'Import changed the skip decision or sent a legacy mode');
    keptState={active:false,phase:'idle',navigation:null,can_cancel:false};browser.endTask();runActive=true;browser.beginOperation(new AbortController().signal,{workflow_id:'run-a',task_id:'query-wos',request_id:'request-run'});browser.associatePage(tab,{role:'wos-query'});browser.bindTaskPage(tab);await win.reload();
    await ready(()=>host("document.getElementById('run-view').open&&!document.querySelector('.run-task-page').hidden"),'actual restored Run fullscreen');assert(await host("workspaceNavigation.current()==='run'"),'restored Run fullscreen did not enter Run workspace');await click(win.webContents,'.run-task-page');await measured('shipped Run fullscreen handoff');
    assert(await host("!document.getElementById('browser-pane').hidden"),'actual Run handoff did not request Run Focus host');assert(browser.selected===tab,'Run retargeted unrelated task page');await capture('shipped-run-fullscreen-handoff');
    await click(win.webContents,'#browser-return');assert(await host("document.getElementById('run-view').open&&getComputedStyle(document.getElementById('run-view')).visibility==='visible'&&document.activeElement.classList.contains('run-task-page')&&!document.getElementById('run-wos-cancel').disabled"),'Run fullscreen return rights/focus');
    assert(tab.id===id&&tab.view.webContents.session===session&&await page('fixtureLoad')===load,'actual workspace presentation recreated native Page/Session');assert((await session.cookies.get({url:origin})).some(cookie=>cookie.name==='synthetic_session'),'actual workspace presentation lost Cookie');
    runActive=false;await ready(()=>host('!uiRun.active()'),'Run terminal state');browser.endTask();
    if(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS)fs.writeFileSync(path.join(process.env.ALLFOLD_BROWSER_WORKSPACES_SCREENSHOTS,'measurements.json'),JSON.stringify(measurements,null,2)+'\n');console.log(JSON.stringify(measurements));console.log('BROWSER WORKSPACES DOM PASS');
  }catch(error){failed=true;console.error(error.stack);console.error('RECENT NATIVE UPDATES',JSON.stringify(nativeUpdates.slice(-12)));console.error('FIXTURE DIAGNOSTICS',JSON.stringify(await diagnostics()));await capture('shipped-failure');}
  finally{ipcMain.removeHandler('cas:status');disposeIPC?.();browser?.close();win?.destroy();await new Promise(resolve=>server.close(resolve));fs.rmSync(temp,{recursive:true,force:true});app.exit(failed?1:0);}
});
