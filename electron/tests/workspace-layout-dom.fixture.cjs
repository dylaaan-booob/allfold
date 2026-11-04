'use strict';
// Real Chromium DOM, synthetic HTTP responses, no Python process, accounts or native authority.
const {app,BrowserWindow}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-layout-dom-'));
app.setPath('userData',temp);app.commandLine.appendSwitch('force-prefers-reduced-motion','reduce');
const ui=path.resolve(__dirname,'../../src/allfold/web/static/ui_next');
const journals=Array.from({length:24},(_,i)=>({name:'Synthetic Journal '+i,issn:`000${i}-0000`,eissn:null,group:'Group '+i%4,labels:'Label '+i%3,access_service_id:i%2?'svc_fixture':null}));
const cover_search={phase:'Idle',busy:false,supported:false};
const settings={csrf_token:'fixture',issues:[],covers:{},cover_search,saved_workspace:'/fixture/workspace',values:{
  name:'Synthetic Monitor',keyword_expression:'causal',from_month:'2026-01',to_month:'2026-01',output_dir:'workspace',log_level:'INFO',
  monitor_revision_exists:'1',monitor_revision_digest:'fixture',journal_revision_exists:'1',journal_revision_digest:'fixture',
  institution_name:'',institution_idp_entity_id:'',auto_import_after_preparation:false,transition_delay_seconds:'3',display_name:'',
  provider_aliases:{},provider_order:['openalex','crossref','pubmed','wos'],groups:Array.from({length:20},(_,i)=>'Group '+i),
  custom_labels:['Label 0','Label 1','Label 2'],journals,access_services:[{id:'svc_fixture',name:'Synthetic Service',access_method:'manual',access_url:''}],
}};
const paper=(i,status='candidate')=>({id:'paper-'+i,title:'Synthetic Paper '+i,publication_date:'2026-10-01',abstract:('An isolated synthetic paragraph for reader scroll verification. '.repeat(12)+'\n\n').repeat(24),authors:['Synthetic Author'],doi:'10.5555/layout-'+i,discovered_at:'2026-10-01T00:00:00Z',status,enrichPhase:'Idle'});
const records=journals.map((j,i)=>({key:j.issn,issn:j.issn,name:j.name,group:j.group,labels:[],cover:null,papers:[paper(i*2),paper(i*2+1)]}));
const workspace={csrf_token:'fixture',import_token:'fixture',issues:[],counts:{candidates:48,active_journals:24},subjects:[{name:'Group 0',journals:records}],
  kept:{papers:[{paper:paper(10,'kept'),journal:records[0]},{paper:paper(11,'kept'),journal:records[1]}],journals:records,services:[],settings:{},titles:{}}};
const run={active:false,providers:Object.fromEntries(settings.values.provider_order.map(id=>[id,{enabled:false,message:'Offline fixture',result_summary:null}]))};
const keptQueue={services:[{id:'all',name:'All Services',kept:2,eligible:2},{id:'unassigned',name:'Unassigned',kept:2,eligible:2}],papers:[],import_token:'fixture'};
const mimes={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.mp4':'video/mp4'};
const server=http.createServer((req,res)=>{
  const route=new URL(req.url,'http://fixture').pathname;
  if(route.startsWith('/api/') || route==='/settings/covers/search'){
    const data=route==='/api/ui-next/workspace'?workspace:route==='/api/ui-next/settings'?settings:
      route==='/api/ui-next/run'?run:route==='/api/kept-workflow/queue'?keptQueue:route==='/api/ui-next/run-expression'?{}:route==='/settings/covers/search'?cover_search:
      {active:false,phase:'idle',navigation:null,can_continue:false,can_cancel:false};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
  }
  const relative=route==='/'?'index.html':decodeURIComponent(route.replace(/^\/static\/ui_next\//,''));
  const file=path.resolve(ui,relative);
  if(!file.startsWith(ui+path.sep) || !fs.existsSync(file)){res.writeHead(404);res.end();return;}
  res.writeHead(200,{'Content-Type':mimes[path.extname(file)] || 'application/octet-stream'});fs.createReadStream(file).pipe(res);
});
let win;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function js(code){
  // Electron may replace a renderer exception with a generic cross-process error.
  const result=await win.webContents.executeJavaScript(`(async()=>{try{return {ok:true,value:await (${code})};}catch(error){return {ok:false,error:String(error.stack || error)};}})()`);
  if(!result.ok)throw Error(result.error);return result.value;
}
async function capture(name){if(process.env.ALLFOLD_LAYOUT_SCREENSHOTS){await wait(50);fs.mkdirSync(process.env.ALLFOLD_LAYOUT_SCREENSHOTS,{recursive:true});fs.writeFileSync(path.join(process.env.ALLFOLD_LAYOUT_SCREENSHOTS,name+'.png'),(await win.webContents.capturePage()).toPNG());}}
async function ready(condition){
  for(let i=0;i<150;i++){if(await js(condition))return;await wait(50);}
  const actual=await js(`({width:innerWidth,height:innerHeight,workspace:window.workspaceNavigation?.current(),arrayMode:document.getElementById('kept-view')?.dataset.sidebarMode,arrayWidth:document.getElementById('kept-view')?.getBoundingClientRect().width,journalMode:document.getElementById('s-journals-page')?.dataset.sidebarMode})`);
  throw Error('UI readiness timeout: '+condition+'; native='+JSON.stringify(win.getBounds())+'; DOM='+JSON.stringify(actual));
}
async function size(width,height,condition){win.setSize(width,height);await ready(`innerWidth===${width} && (${condition})`);}
async function check(fn){await js(`(${fn.toString()})()`);}
app.whenReady().then(async()=>{
  try {
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    win=new BrowserWindow({width:1200,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,partition:'layout-test',preload:path.join(__dirname,'workspace-layout-preload.fixture.cjs')}});
    await win.loadURL(`http://127.0.0.1:${server.address().port}/`);
    await ready("window.uiWorkspace?.ready() && !document.getElementById('array-candidates').disabled && document.querySelectorAll('#s-journals [data-journal]').length===24");
    await check(async()=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
      window.layoutReader=$('paper-detail');window.layoutParent=layoutReader.parentElement;
      window.layoutOpenCount=0;window.layoutCloseCount=0;
      const open=window.inboxKept.openReader,close=window.inboxKept.closeReader;
      window.inboxKept.openReader=function(...args){window.layoutOpenCount++;return open.apply(this,args);};
      window.inboxKept.closeReader=function(...args){window.layoutCloseCount++;return close.apply(this,args);};
      layoutReader.scrollTop=240;const before=layoutReader.getBoundingClientRect().width;
      $('array-index-toggle').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));
      await sleep(200);assert(!$('array-flyout').hidden,'hover must open Index');
      assert(layoutReader.getBoundingClientRect().width===before,'flyout changed Reader width');
      $('array-index-toggle').dispatchEvent(new PointerEvent('pointerleave'));
      $('array-flyout').dispatchEvent(new PointerEvent('pointerenter'));await sleep(320);
      assert(!$('array-flyout').hidden,'crossing into flyout closed it');
      $('array-index').querySelector('button').focus();
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      assert($('array-flyout').hidden && document.activeElement===$('array-index-toggle'),'Escape focus restoration');
      $('array-index-toggle').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
      assert(document.activeElement===$('array-index').children[0],'arrow entry did not focus the first Index item');
      for(let i=0;i<2;i++)document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
      assert(!$('array-flyout').hidden && document.activeElement===$('array-index').children[2],'Index arrows did not keep list focus');
      assert(layoutReader.dataset.paperId==='paper-0','focus navigation changed Paper selection');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      document.querySelector('#kept-view [data-sidebar-view]').click();
      assert(!$('array-sidebar').hidden,'Info did not open');
      assert(layoutReader=== $('paper-detail') && layoutReader.parentElement===layoutParent,'layout remounted Reader');
      assert(layoutReader.scrollTop===240,'layout lost Reader scroll');
      assert(window.layoutOpenCount===0 && window.layoutCloseCount===0,'layout invoked Reader lifecycle');
      $('array-index-toggle').click();$('array-index').children[1].click();
      assert(!$('array-sidebar').hidden && $('array-flyout').hidden,'selection changed Info state / left flyout open');
      assert($('array-journal-name').textContent==='Synthetic Journal 1','metadata did not follow selection');
      document.querySelector('#kept-view [data-sidebar-view]').click();
      $('array-index-toggle').click();$('array-index').scrollTop=200;document.querySelector('#array-flyout [data-flyout-close]').click();
      $('array-kept').click();assert(window.workspaceNavigation.current()==='kept','legacy Kept entry must open independent Kept');
      assert($('kept-sidebar').hidden,'Kept automatically opened a Sidebar');
      assert(!$('kept-start').closest('[hidden]') && !$('kept-import-only').closest('[hidden]'),'primary actions hidden with sidebar');
      $('workspace-open').click();$('array-index-toggle').click();assert($('array-index').scrollTop===200,'Candidates Index scroll lost after visiting Kept');document.querySelector('#array-flyout [data-flyout-close]').click();
      window.layoutReader=$('paper-detail');window.layoutParent=layoutReader.parentElement;layoutReader.scrollTop=180;
      document.querySelector('#kept-view [data-sidebar-view]').click();
    });
    await capture('array-wide');
    await size(700,500,"document.getElementById('kept-view').dataset.sidebarMode==='overlay'");
    await check(()=>{
      const root=document.getElementById('kept-view'),reader=document.getElementById('paper-detail');
      if(root.dataset.sidebarMode!=='overlay')throw Error('narrow Array must overlay');
      if(reader!==window.layoutReader || reader.parentElement!==window.layoutParent || reader.scrollTop!==180)throw Error('resize changed Reader identity/scroll');
      document.getElementById('journals-open').click();
    });
    await ready("!document.getElementById('s-journals-page').hidden");
    await check(async()=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);};
      $('s-journals').children[0].click();assert(!$('journal-sidebar').hidden,'Journal selection did not open Details');
      const detail=$('s-journal-detail'),original=detail.querySelector('select');
      document.querySelector('#s-journal-layout [data-layout=grid]').click();
      assert(detail.querySelector('select')===original && !$('journal-sidebar').hidden,'GRID rebuilt/closed Details');
      const title=$('s-journals-title').textContent,count=$('s-journals').children.length;
      document.querySelector('[data-flyout=subject]').dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
      assert(document.activeElement===$('s-entities').children[0],'arrow entry did not focus Directory list');
      for(let i=0;i<2;i++)document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowDown',bubbles:true,cancelable:true}));
      assert(!$('journal-flyout').hidden && document.activeElement===$('s-entities').children[2] && $('s-journals-title').textContent===title,'Directory arrows applied/closed filter');
      $('s-entities').scrollTop=160;
      document.querySelector('[data-flyout=access]').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));await new Promise(r=>setTimeout(r,200));
      assert(!$('journal-flyout').hidden,'hover preview closed while replacing focused list');
      document.querySelector('[data-flyout=subject]').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));await new Promise(r=>setTimeout(r,200));
      assert($('s-entities').scrollTop===160,'switching open preview lost Directory scroll');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      document.querySelector('[data-flyout=access]').dispatchEvent(new PointerEvent('pointerenter',{pointerType:'mouse'}));
      await new Promise(r=>setTimeout(r,200));
      assert($('s-journals-title').textContent===title && $('s-journals').children.length===count,'hover applied a filter');
      assert(document.querySelector('[data-scope=subject]').getAttribute('aria-pressed')==='true','hover changed scope');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      document.querySelector('[data-flyout=subject]').click();
      assert($('s-entities').scrollTop===160,'Directory scroll lost across close / another scope / reopen');
      document.activeElement.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true,cancelable:true}));
      const transfer=new DataTransfer(),row=$('s-journals').children[0],access=document.querySelector('[data-flyout=access]');
      row.dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));
      access.dispatchEvent(new DragEvent('dragenter',{bubbles:true,dataTransfer:transfer}));
      await new Promise(r=>setTimeout(r,200));
      assert(!$('journal-flyout').hidden && $('journal-directory-title').textContent==='ACCESS','drag hover failed to open target Directory');
      const service=$('s-entities').children[2];service.dispatchEvent(new DragEvent('dragover',{bubbles:true,cancelable:true,dataTransfer:transfer}));
      service.dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
      assert($('s-journal-service').value==='svc_fixture','drop did not assign Service');
      assert(document.querySelector('[data-scope=subject]').getAttribute('aria-pressed')==='true','drag preview changed active scope');
      access.click();
      $('s-entities').children[2].click();assert($('journal-sidebar').hidden,'directory selection did not close Details');
      document.querySelector('[data-flyout=access]').click();$('s-edit-entity').click();
      const input=$('s-entity-description').querySelector('[data-service-field=url]');input.value='https://synthetic.test/draft';input.dispatchEvent(new Event('input',{bubbles:true}));input.focus();
      window.layoutDraft=input;window.layoutDraftParent=input.parentElement;window.layoutJournalList=$('s-journals');layoutJournalList.scrollTop=100;
    });
    await capture('journals-overlay');
    await size(1200,800,"document.getElementById('s-journals-page').dataset.sidebarMode==='docked'");
    await check(()=>{
      const $=id=>document.getElementById(id),input=$('s-entity-description').querySelector('[data-service-field=url]');
      if(input!==window.layoutDraft || input.parentElement!==window.layoutDraftParent || input.value!=='https://synthetic.test/draft' || document.activeElement!==input)throw Error('resize lost Service draft/focus');
      if($('s-journals-page').dataset.sidebarMode!=='docked')throw Error('wide Journals must dock');
      const resize=document.querySelector('#journal-sidebar .sidebar-resize');resize.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
      if(input!==window.layoutDraft || document.activeElement!==input)throw Error('sidebar sizing rebuilt editor');
      $('s-developer-mode').checked=true;$('s-developer-mode').dispatchEvent(new Event('change'));
      const target=$('layout-sidebarPreferredWidth');target.value='420';target.dispatchEvent(new Event('input'));$('layout-save').click();$('layout-origin').click();
      if(target.value!=='320')throw Error('ORIGIN did not restore defaults');$('layout-reset').click();if(target.value!=='420')throw Error('RESET lost saved target');
      if(document.querySelector('footer').getBoundingClientRect().height>86)throw Error('developer footer unbounded');
      $('workspace-open').click();
    });
    await capture('array-developer');
    await size(600,480,"document.getElementById('kept-view').dataset.sidebarMode==='overlay'");
    await check(()=>{
      const $=id=>document.getElementById(id),root=$('kept-view'),tools=root.querySelector('.tool-rail'),main=$('array-content');
      if(root.dataset.sidebarMode!=='overlay')throw Error('600px Array must overlay');
      if(tools.getBoundingClientRect().right>root.getBoundingClientRect().right+1 || main.clientWidth<360)throw Error('rails/content overflow');
      if($('keep-paper').getBoundingClientRect().bottom>main.getBoundingClientRect().bottom)throw Error('low-height primary decision unreachable');
      if(document.querySelector('.masthead').getBoundingClientRect().bottom>root.getBoundingClientRect().top+1 || document.querySelector('footer').getBoundingClientRect().top<root.getBoundingClientRect().bottom-1)throw Error('Chrome or Status overlaps content');
      $('journals-open').click();
    });
    await wait(100);
    await check(()=>{
      const root=document.getElementById('s-journals-page'),list=document.getElementById('s-journals');
      if(root.dataset.sidebarMode!=='overlay' || list.clientHeight<100)throw Error('600x480 Journals is not operable');
      const trigger=document.querySelector('[data-flyout=subject]');trigger.click();
      if(document.getElementById('s-entities').clientHeight<100)throw Error('low-height Directory cannot scroll');
    });
    await capture('journals-small');
    await check(()=>{
      const $=id=>document.getElementById(id);$('settings-open').click();
      if($('s-settings').clientHeight<100)throw Error('Settings lost its parent height');
      window.workspaceNavigation.go('workspace',{instant:true});
      window.allfoldUIPreferences.setArchiveDisabled(false);$('array-index-toggle').click();$('array-index').scrollTop=200;$('workspace-archive').click();
      if($('selected-view').dataset.workspaceLayout!=='archive' || !$('kept-view').hidden)throw Error('Archive restoration failed');
      archiveDebug.values.height=200;window.dispatchEvent(new Event('archive-debug-change'));
      if(Math.abs($('selected-view').getBoundingClientRect().height-200)>1)throw Error('Archive tuned height is overridden by flexible fill');
      $('workspace-array').click();
      if($('selected-view').getBoundingClientRect().height!==$('allfold-pane').getBoundingClientRect().height)throw Error('Archive height leaked into ARRAY');
      $('array-index-toggle').click();if($('array-index').scrollTop!==200)throw Error('Index scroll lost through Archive entry');
      document.querySelector('#array-flyout [data-flyout-close]').click();
    });
    // Browser is a separate full view; this fixture has no native page Session.
    await js("window.allfoldWorkbench.show()");
    await check(()=>{
      const $=id=>document.getElementById(id),bounds=$('browser-body').getBoundingClientRect();
      if(document.body.dataset.workbench!=='browser' || !$('allfold-pane').inert || bounds.width<240 || bounds.height<120)throw Error('600x480 Browser body is not operable');
      window.allfoldWorkbench.hide();
      if($('allfold-pane').inert || $('kept-view').dataset.sidebarMode!=='overlay')throw Error('Browser return lost Array presentation');
    });
    console.log('LAYOUT DOM PASS');
  }catch(error){console.error(error.stack);process.exitCode=1;}
  finally {win?.destroy();server.close();fs.rmSync(temp,{recursive:true,force:true});app.exit(process.exitCode || 0);}
});
