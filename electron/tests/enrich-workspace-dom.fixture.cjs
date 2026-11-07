'use strict';
// Independent Enrich acceptance: the initial Workspace already contains its Paper.
const {app,BrowserWindow,ipcMain}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs'),{installBrowserIPC}=require('../src/browser/browser-ipc.cjs');
const {fixtureDiagnostics}=require('./browser-dom-diagnostics.cjs');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-enrich-workspace-'));
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
  provider_aliases:{},provider_order:['openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv','wos'],enabled_providers:['openalex','europe_pmc'],completion_providers:['openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv'],groups:['Synthetic Group'],custom_labels:[],journals,access_services:services,
}};
const paper={id:'paper-1',title:'Synthetic kept paper',doi:'10.5555/presentation',publication_date:'2026-10-01',status:'kept',abstract:'Synthetic fixture only',authors:[],enrichPhase:'Idle'};
const enrichPaper={...paper,id:'paper-enrich',title:'Synthetic Enrich paper',doi:'10.5555/enrich',status:'candidate',abstract:''};
const record={key:'0000-0001',...journals[0],labels:[],papers:[enrichPaper]};
const workspace={csrf_token:'fixture',import_token:'fixture',issues:[],counts:{candidates:1,active_journals:1},subjects:[{name:'Synthetic Group',journals:[record]}],kept:{papers:[{paper,journal:record}],journals:[record],services,settings:{},titles:{'paper-1':paper.title}}};
let enrichState={phase:'Idle',supported:true,waiting_for_user:false};
const queue={services:[{id:'all',name:'All Services',kept:1,eligible:1},{id:serviceId,name:services[0].name,kept:1,eligible:1},{id:'unassigned',name:'Unassigned',kept:0,eligible:0},{id:'ambiguous',name:'Ambiguous',kept:0,eligible:0}],papers:[{paper_id:'paper-1',title:paper.title,doi:paper.doi,service_id:serviceId,assignment:'assigned',reason:''}],import_token:'fixture'};
const keptState={active:false,phase:'idle',navigation:null,can_continue:false,can_cancel:false};
const runData={active:false,snapshot:{status:'IDLE',provider:null},providers:Object.fromEntries(['integrated','wos'].map(id=>[id,{enabled:false,message:'Offline fixture',snapshot:{status:'IDLE'},result_summary:null}]))};
const requests=[],workspaceReads={started:0,inFlight:0,lastCandidateIds:[]};
const challenge=`<!doctype html><html><head><meta charset="utf-8"><style>body{font:16px sans-serif}label{display:block;margin:12px}input,button{font:inherit}</style></head><body><form><label><input id="human" type="checkbox"> Local synthetic verification</label><label>Code <input id="code"></label><button id="verify">Verify</button><output id="result">Waiting</output></form><script>window.fixtureLoad=crypto.randomUUID();document.cookie='synthetic_session=preserved; SameSite=Lax';document.querySelector('form').onsubmit=event=>{event.preventDefault();result.textContent=human.checked&&code.value==='42'?'Synthetic challenge complete':'Try code 42'};</script></body></html>`;
const mimes={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.mp4':'video/mp4'};
const server=http.createServer(async(req,res)=>{
  const route=new URL(req.url,'http://fixture').pathname;
  if(route==='/challenge'){res.writeHead(200,{'Content-Type':'text/html'});res.end(challenge);return;}
  if(route.startsWith('/api/')||route==='/settings/covers/search'){
    let body='';for await(const chunk of req)body+=chunk;
    requests.push({route,body:body?JSON.parse(body):null});
    if(route==='/api/papers/paper-enrich/enrichment/start'){
      browser.beginOperation(new AbortController().signal,{workflow_id:'enrich-a',task_id:'enrich-a',request_id:'native-enrich'});
      tab=browser.createTab({present:false});browser.associatePage(tab,{role:'auxiliary',service:false});browser.bindTaskPage(tab);
      await tab.view.webContents.loadURL(origin+'/challenge');
      enrichState={phase:'Retrieving',request_id:'enrich-a',waiting_for_user:true,message:'Complete verification in BROWSER',saved:{}};
    }
    if(route==='/api/papers/paper-enrich/enrichment/cancel')enrichState={...enrichState,phase:'Cancelled',waiting_for_user:false};
    const data=route.startsWith('/api/papers/paper-enrich/enrichment/')?enrichState:
      route==='/api/papers/api-completion/state'?{phase:'Idle',results:[]}:
      route==='/api/ui-next/workspace'?workspace:route==='/api/ui-next/settings'?settings:route==='/api/kept-workflow/queue'?queue:
      route==='/api/ui-next/browser-services'?{scope,services}:route.startsWith('/api/ui-next/run')&&!route.endsWith('expression')?runData:
      route==='/api/ui-next/run-expression'?{providers:Object.fromEntries([...settings.values.provider_order,'integrated'].map(id=>[id,{expression:'causal',error:null}]))}:
      route==='/api/kept-workflow/state'?keptState:route==='/settings/covers/search'?cover_search:
      route.includes('/history')?{records:[]}:route.includes('/institutions')?{institutions:[]}:{};
    if(route==='/api/ui-next/workspace'){
      workspaceReads.started++;workspaceReads.inFlight++;workspaceReads.lastCandidateIds=record.papers.map(paper=>paper.id);
      res.once('finish',()=>{workspaceReads.inFlight--;});
    }
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
const diagnostics=()=>fixtureDiagnostics(win,browser,{expectedPaperId:enrichPaper.id,workspaceReads,requests});
async function ready(check,label){for(let i=0;i<240;i++){if(await check())return;await wait(25);}throw Error('Timed out '+label+'; '+JSON.stringify(await diagnostics()));}
async function click(contents,selector){app.focus({steal:true});win.focus();await ready(()=>Promise.resolve(win.isFocused()),'native input focus');await evaluate(contents,'new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');const point=await evaluate(contents,`(()=>{const element=document.querySelector(${JSON.stringify(selector)});element.scrollIntoView({block:'nearest',inline:'nearest'});const r=element.getBoundingClientRect();return {x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}})()`),zoom=contents.getZoomFactor();contents.sendInputEvent({type:'mouseMove',x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});for(const type of ['mouseDown','mouseUp'])contents.sendInputEvent({type,button:'left',clickCount:1,x:Math.round(point.x*zoom),y:Math.round(point.y*zoom)});await wait(55);}
async function key(contents,keyCode,modifiers=[]){contents.sendInputEvent({type:'keyDown',keyCode,modifiers});if(keyCode==='Enter')contents.sendInputEvent({type:'char',keyCode:'\r',modifiers});contents.sendInputEvent({type:'keyUp',keyCode,modifiers});await wait(25);}
async function measured(label){await host('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');await ready(async()=>{const r=await host("document.getElementById('browser-body').getBoundingClientRect().toJSON()"),reported=browser.presentation.bounds;return browser.presentation.mounted&&reported&&['x','y','width','height'].every(name=>Math.abs(r[name]-reported[name])<1);},label);const value={label,window:win.getBounds(),content:win.getContentSize(),zoom:win.webContents.getZoomFactor(),viewport:tab.view.getBounds()};measurements.push(value);return value.viewport;}
async function capture(name){const directory=process.env.ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS;if(!directory)return;await host('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))');fs.mkdirSync(directory,{recursive:true});fs.writeFileSync(path.join(directory,name+'.png'),(await win.webContents.capturePage()).toPNG());if(browser.presentation.mounted)fs.writeFileSync(path.join(directory,name+'-page.png'),(await tab.view.webContents.capturePage()).toPNG());}
async function completeChallenge(){await page('scrollTo(0,0)');const checked=await page('human.checked');await click(tab.view.webContents,'#human');if(checked)await key(tab.view.webContents,'Space');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Tab',['shift']);assert(await page("document.activeElement.id==='human'"),'Shift+Tab focus');await key(tab.view.webContents,'Tab');await tab.view.webContents.insertText('42');await key(tab.view.webContents,'Tab');await key(tab.view.webContents,'Enter');assert(await page("result.textContent==='Synthetic challenge complete'"),'constrained challenge did not complete');}
app.whenReady().then(async()=>{
  try{
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin=`http://127.0.0.1:${server.address().port}`;
    win=new BrowserWindow({width:1200,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,partition:'enrich-workspace-host',preload:path.join(__dirname,'../src/preload/preload.cjs')}});
    browser=new BrowserRuntime({hostWindow:win,isTaskRunning:()=>['Retrieving','Saving'].includes(enrichState.phase)});
    await browser.ready;const update=browser.setPresentation.bind(browser);browser.setPresentation=value=>{nativeUpdates.push({...value});return update(value)};
    for(const partition of [win.webContents.session,browser.partition])partition.webRequest.onBeforeRequest({urls:['http://*/*','https://*/*']},(details,callback)=>callback({cancel:new URL(details.url).origin!==origin}));
    ipcMain.handle('cas:status',()=>({available:false,configured:false,revision:'fixture'}));
    disposeIPC=installBrowserIPC({ipcMain,hostWindow:win,origin,browser});
    await win.loadURL(origin+'/');win.show();win.focus();await ready(()=>Promise.resolve(win.isFocused()),'fixture Window focus');
    // Readiness includes the actual fixture Paper, rather than a previous scene's refresh.
    await ready(()=>host("window.uiWorkspace?.ready()&&window.inboxKept.candidates().some(entry=>entry.paper.id==='paper-enrich')&&!document.getElementById('array-candidates').disabled"),'initial Enrich Paper loaded');
    assert(await host("workspaceArray.openPaper('paper-enrich')"),'initial Enrich Paper could not open');
    await ready(()=>host("!!document.querySelector('#paper-detail [data-enrich]:not(:disabled)')"),'Enrich start ready');
    await click(win.webContents,'#paper-detail [data-enrich]:not(:disabled)');
    await ready(()=>host("!!document.getElementById('enrich-task-page')&&!document.getElementById('enrich-task-page').hidden"),'Enrich verification entry');
    const id=tab.id,session=tab.view.webContents.session,load=await page('fixtureLoad');
    assert(browser.selected===null&&!browser.presentation.mounted,'background Enrich page was selected or presented');
    assert(await page('innerWidth>0&&innerHeight>0'),'background Enrich page has no layout viewport');
    await click(win.webContents,'#enrich-task-page');
    await measured('shipped Enrich task handoff');
    assert(browser.presentation.mounted===tab,'Enrich task Browser mounted an unrelated Page');
    assert(browser.selected===tab&&await host("workspaceNavigation.current()==='workspace'&&document.getElementById('browser-pane').dataset.source==='enrich'"),'Enrich Browser handoff left Workspace or retargeted task');
    await capture('enrich-task-handoff');await completeChallenge();await click(win.webContents,'#browser-return');
    assert(await host("document.activeElement.id==='enrich-task-page'&&document.getElementById('cancel-enrich').hidden===false"),'Enrich return lost focus or task controls');
    assert(tab.id===id&&tab.view.webContents.session===session&&await page('fixtureLoad')===load,'Enrich handoff recreated Page, Session or document');
    assert((await session.cookies.get({url:origin})).some(cookie=>cookie.name==='synthetic_session'),'Enrich handoff lost Cookie');
    enrichPaper.abstract='Enriched synthetic abstract';enrichState={...enrichState,phase:'Completed',waiting_for_user:false,message:'Enrichment saved',saved:{abstract:enrichPaper.abstract}};
    await ready(()=>host("document.getElementById('paper-abstract').textContent.includes('Enriched synthetic abstract')&&document.getElementById('enrich-task-page').hidden&&document.getElementById('cancel-enrich').hidden"),'Enrich completion refresh');
    assert(requests.filter(request=>request.route==='/api/papers/paper-enrich/enrichment/start').length===1,'Enrich handoff restarted task');
    assert(!requests.some(request=>request.route==='/api/papers/paper-enrich/enrichment/cancel'),'Enrich Browser handoff cancelled task');
    await capture('enrich-completed');browser.endTask();
    if(process.env.ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS)fs.writeFileSync(path.join(process.env.ALLFOLD_ENRICH_WORKSPACE_SCREENSHOTS,'measurements.json'),JSON.stringify(measurements,null,2)+'\n');
    console.log('ENRICH WORKSPACE DOM PASS');
  }catch(error){failed=true;console.error(error.stack);console.error('RECENT NATIVE UPDATES',JSON.stringify(nativeUpdates.slice(-12)));console.error('FIXTURE DIAGNOSTICS',JSON.stringify({...await diagnostics(),enrichPhase:enrichState.phase}));await capture('enrich-failure');}
  finally{ipcMain.removeHandler('cas:status');disposeIPC?.();browser?.close();win?.destroy();await new Promise(resolve=>server.close(resolve));fs.rmSync(temp,{recursive:true,force:true});app.exit(failed?1:0);}
});
