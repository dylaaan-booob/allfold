'use strict';
// Real Chromium DOM, synthetic HTTP responses, no Python process, accounts or native authority.
const {app,BrowserWindow,ipcMain}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-layout-dom-'));
app.setPath('userData',temp);app.commandLine.appendSwitch('force-prefers-reduced-motion','reduce');
const ui=path.resolve(__dirname,'../../src/allfold/web/static/ui_next');
const journals=Array.from({length:24},(_,i)=>({name:'Synthetic Journal '+i,issn:`000${i}-0000`,eissn:null,group:'Group '+i%4,labels:'Label '+i%3,access_service_id:i%2?'svc_fixture':null}));
const conference={id:'conf_00000000000000000000000000000001',name:'International Conference on Machine Learning',abbreviation:'ICML',aliases:[],dblp_stream:'streams/conf/icml',group:null,labels:[]};
const cover_search={phase:'Idle',busy:false,supported:false};
const settings={config_path:'/fixture/monitor.yaml',csrf_token:'fixture',issues:[],covers:{},cover_search,saved_workspace:'/fixture/workspace',values:{
  name:'Synthetic Monitor',keyword_expression:'causal',from_month:'2026-01',to_month:'2026-01',output_dir:'workspace',log_level:'INFO',
  monitor_revision_exists:'1',monitor_revision_digest:'fixture',journal_revision_exists:'1',journal_revision_digest:'fixture',
  institution_name:'',institution_idp_entity_id:'',auto_import_after_preparation:false,transition_delay_seconds:'3',display_name:'',
  provider_aliases:{},provider_order:['openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv','wos'],enabled_providers:['openalex','europe_pmc'],completion_providers:['openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv'],groups:Array.from({length:20},(_,i)=>'Group '+i),
  conferences:[],custom_labels:['Label 0','Label 1','Label 2'],journals,access_services:[{id:'svc_fixture',name:'Synthetic Service',access_method:'manual',access_url:''}],
}};
const paper=(i,status='candidate')=>({id:'paper-'+i,title:'Synthetic Paper '+i,publication_date:'2026-10',conference:'Synthetic Conference',publication_type:'conference',first_public_at:'2022-04',date_evidence:[{kind:'preprint',year:2022,month:4,provider:'arxiv',record_id:'2204.12345',version:'v1',publication_type:'preprint',first_version:true},{kind:'accepted',year:2026,month:9,provider:'crossref',record_id:'10.5555/formal',publication_type:'journal'},{kind:'published-online',year:2026,month:10,provider:'crossref',record_id:'10.5555/formal',publication_type:'journal'}],external_ids:{dblp:'conf/example/Paper'},indexed_terms:[{value:'statistics',kind:'topic',source:'openalex'}],sources:[{provider:'dblp',record_id:'conf/example/Paper',role:'discovery'}],abstract:('An isolated synthetic paragraph for reader scroll verification. '.repeat(12)+'\n\n').repeat(24),authors:['Synthetic Author'],doi:i===0?null:'10.5555/layout-'+i,discovered_at:'2026-10-01T00:00:00Z',status,enrichPhase:'Idle'});
const records=journals.map((j,i)=>({key:j.issn,issn:j.issn,name:j.name,group:j.group,labels:[],cover:null,papers:[paper(i*2),paper(i*2+1)]}));
Object.assign(records[0],{name:'Synthetic Conference',source_type:'conference',issn:null,dblp_stream:'streams/conf/icml',group:'Old scope'});
const workspace={csrf_token:'fixture',import_token:'fixture',issues:[],counts:{candidates:48,active_journals:24},subjects:[{name:'Group 0',journals:records}],
  kept:{papers:[{paper:paper(10,'kept'),journal:records[0]},{paper:paper(11,'kept'),journal:records[1]}],journals:records,services:[],settings:{},titles:{}}};
const run={active:false,snapshot:{status:'IDLE',provider:null},providers:Object.fromEntries(['integrated','wos'].map(id=>[id,{enabled:false,message:'Offline fixture',result_summary:null}]))};
const keptQueue={services:[{id:'all',name:'All Services',kept:2,eligible:2},{id:'unassigned',name:'Unassigned',kept:2,eligible:2}],papers:[],import_token:'fixture'};
let keptState={active:false,phase:'idle',navigation:null,can_continue:false,can_cancel:false};
const mimes={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.mp4':'video/mp4'};
let rejectAutosave=false,holdWorkspaceResponse,resolveInitialCAS,credentialState={ok:false,error:'cas_store_unreadable',configured:false,username:'',revision:'d'.repeat(64)};
const credentialWrites=[];
const completionStarts=[];
let completionState={phase:'Idle',results:[],total:0,processed:0};
const server=http.createServer((req,res)=>{
  const route=new URL(req.url,'http://fixture').pathname;
  if(route==='/api/papers/api-completion/start'){
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{
      const value=JSON.parse(text);completionStarts.push(value);
      completionState={phase:'Running',request_id:'fixture-completion',total:value.paper_ids.length,processed:0,results:[]};
      res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(completionState));
    });return;
  }
  if(route==='/api/papers/api-completion/state' || route==='/api/papers/api-completion/cancel'){
    if(route.endsWith('/cancel'))completionState={...completionState,phase:'Cancelled',processed:completionState.total,
      results:completionStarts.at(-1).paper_ids.map(paper_id=>({paper_id,status:'cancelled',lookups:[],issues:[]}))};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(route.endsWith('/cancel')?{accepted:true}:completionState));return;
  }
  if(route==='/api/ui-next/zotero'){
    const data={ok:true,server_id:'SERVERFIXTUR',version:'10.0.6',authorized:true,libraries:[
      {type:'user',id:'0',name:'My Library',editable:true,files_editable:true,collections:[]},
      {type:'group',id:'12',name:'Synthetic Group',editable:null,files_editable:null,collections:[
        {key:'ABCDEFGH',path:'Parent',name:'Parent'}, {key:'JKLMNPQR',path:'Parent / Child',name:'Child',parent_key:'ABCDEFGH'}]}]};
    res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(data));return;
  }
  if(route==='/api/ui-next/settings/credentials'){
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{
      const value=JSON.parse(text);credentialWrites.push(value);
      const matches=value.expected_revision===credentialState.revision;
      if(matches)credentialState={ok:true,configured:true,username:value.username,revision:'f'.repeat(64)};
      res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(matches?credentialState:{ok:false,error:'cas_revision_conflict'}));
    });return;
  }
  if(route==='/api/ui-next/settings/autosave'){
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{const patch=JSON.parse(text);if(rejectAutosave){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({...settings,saved:false,outcome:'WRITE_FAILED',message:'Synthetic offline write'}));return;}if(patch.changes.keyword_expression==='lea*'){res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({...settings,saved:false,outcome:'INVALID_DRAFT',validation:{issues:[{field:'keyword_expression',message:'Prefix needs at least four characters'}]}}));return;}Object.assign(settings.values,patch.changes);settings.values.monitor_revision_digest+='x';setTimeout(()=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify({...settings,saved:true,outcome:'SAVED'}));},90);});return;
  }
  if(route==='/api/ui-next/workspace' && holdWorkspaceResponse){
    const body=JSON.stringify(workspace),release=holdWorkspaceResponse;holdWorkspaceResponse=null;
    release(()=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(body);});return;
  }
  if(route.startsWith('/api/') || route==='/settings/covers/search'){
    const data=route==='/api/ui-next/settings/conferences/search'?{candidates:[conference]}:route==='/api/ui-next/workspace'?workspace:route==='/api/ui-next/settings'?settings:
      route==='/api/ui-next/run'?run:route==='/api/kept-workflow/queue'?keptQueue:route==='/api/ui-next/run-expression'?{providers:Object.fromEntries([...settings.values.provider_order,'integrated'].map(id=>[id,{expression:'causal',error:null}]))}:route==='/settings/covers/search'?cover_search:
      route==='/api/kept-workflow/state'?keptState:{active:false,phase:'idle',navigation:null,can_continue:false,can_cancel:false};
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
    let firstCAS=true;ipcMain.handle('layout:cas-status',()=>{
      if(!firstCAS)return credentialState;
      firstCAS=false;return new Promise(resolve=>{resolveInitialCAS=()=>resolve(credentialState);});
    });
    win=new BrowserWindow({width:1200,height:800,show:false,webPreferences:{sandbox:true,contextIsolation:true,backgroundThrottling:false,partition:'layout-test',preload:path.join(__dirname,'workspace-layout-preload.fixture.cjs')}});
    win.webContents.on('console-message',event=>{if(event.level==='error')console.error('RENDERER',event.message,event.lineNumber,event.sourceId);});
    await win.loadURL(`http://127.0.0.1:${server.address().port}/`);
    await ready("window.uiWorkspace?.ready() && !document.getElementById('array-candidates').disabled && document.querySelectorAll('#s-journals [data-journal]').length===24");
    await check(()=>{
      if(!document.getElementById('array-journal-issn').parentElement.hidden || !document.getElementById('array-journal-eissn').parentElement.hidden)throw Error('Conference profile displays Journal ISSN fields');
      if(document.getElementById('array-source-stream')?.textContent!=='streams/conf/icml')throw Error('Conference profile lost its native DBLP Stream');
    });
    await check(()=>{
      window.workspaceNavigation.go('journals',{instant:true});
      const category=document.getElementById('s-source-kind'),label=document.getElementById('s-add-journal');
      const updates=new MutationObserver(()=>{});updates.observe(label,{childList:true});
      try{
        for(let i=0;i<8;i++){
          const conferences=i%2===0;
          category.value=conferences?'conferences':'journals';category.dispatchEvent(new Event('change'));
          if(label.textContent!==(conferences?'+ CONFERENCE':'+ JOURNAL') || document.querySelectorAll('#s-journals [data-journal]').length!==(conferences?0:24))throw Error('Repeated category switch displayed the wrong source list');
          if(updates.takeRecords().length!==1)throw Error('One category switch repeatedly rebuilt its displayed label');
        }
      }finally{updates.disconnect();}
    });
    await check(()=>{
      window.workspaceNavigation.go('journals',{instant:true});
      const category=document.getElementById('s-source-kind');category.value='conferences';category.dispatchEvent(new Event('change'));
      if(document.querySelectorAll('#s-journals [data-journal]').length!==0)throw Error('Registry automatically followed series');
      document.getElementById('s-add-journal').click();
      document.getElementById('s-add-query').value='ICML';
      [...document.querySelectorAll('#s-dialog button')].find(b=>b.textContent==='Search Registry').click();
    });
    await ready("document.querySelector('[name=conference-candidate]')");
    await check(()=>{
      document.querySelector('[name=conference-candidate]').checked=true;
      [...document.querySelectorAll('#s-dialog button')].find(b=>b.textContent==='Follow').click();
    });
    await ready("window.allfoldAutosave.status==='Saved' && document.querySelectorAll('#s-journals [data-journal]').length===1");
    await check(()=>{
      if(document.getElementById('s-journal-detail').textContent.includes('ISSN') || document.getElementById('s-journal-service'))throw Error('Conference received Journal identity or Service controls');
      const group=document.getElementById('s-conference-group');group.value='group:Group 0';group.dispatchEvent(new Event('change'));
      const label=document.querySelector('[data-conference-label="Label 1"]');label.checked=true;label.dispatchEvent(new Event('change'));
    });
    await ready("window.allfoldAutosave.status==='Saved'");
    await ready("window.inboxRun.available()");
    const firstWorkspaceResponse=new Promise(resolve=>{holdWorkspaceResponse=resolve;});
    records[0].group='Earlier saved group';
    await check(()=>window.dispatchEvent(new Event('settings-saved')));
    const releaseWorkspace=await firstWorkspaceResponse;
    records[0].group='Group 0';records[0].labels=['Label 1'];
    await check(()=>window.dispatchEvent(new Event('settings-saved')));
    releaseWorkspace();
    await ready("window.inboxRun.available() && window.inboxKept.candidates().find(entry=>entry.journal.source_type==='conference')?.journal.group==='Group 0'");
    await check(()=>window.workspaceNavigation.go('workspace',{instant:true}));
    await ready("document.getElementById('array-journal-subject').textContent==='Group 0'");
    await check(()=>window.workspaceNavigation.go('journals',{instant:true}));
    await size(600,480,"window.workspaceNavigation.current()==='journals'");
    await capture('conferences-600');
    await check(()=>{
      if(document.getElementById('s-conference-group').value!=='group:Group 0' || !document.querySelector('[data-conference-label="Label 1"]').checked)throw Error('Conference assignments lost');
      const category=document.getElementById('s-source-kind');category.value='journals';category.dispatchEvent(new Event('change'));
      if(document.querySelectorAll('#s-journals [data-journal]').length!==24)throw Error('Conference edits modified Journals');
    });
    await size(1200,800,"window.workspaceNavigation.current()==='journals'");
    await check(()=>{
      window.workspaceNavigation.go('run',{instant:true});
      const field=document.querySelector('[data-monitor="expression"]');field.value='lea*';field.dispatchEvent(new Event('input',{bubbles:true}));
    });
    await ready("document.querySelector('[data-monitor=expression]').getAttribute('aria-invalid')==='true'");
    await check(()=>{
      const field=document.querySelector('[data-monitor="expression"]');field.value='causal';field.dispatchEvent(new Event('input',{bubbles:true}));
    });
    await ready("window.allfoldAutosave.status==='Saved'");
    await check(()=>{
      if(document.querySelector('.s-validation-error') || document.querySelector('[data-monitor="expression"]').getAttribute('aria-invalid')==='true' || document.getElementById('s-message').textContent.includes('Prefix needs'))throw Error('Saved expression retains obsolete validation errors');
    });
    await check(()=>{
      window.workspaceNavigation.go('kept',{instant:true});
      document.querySelector('[data-zotero-refresh]').click();
    });
    await ready("!document.querySelector('[data-zotero-library]').disabled");
    await check(()=>{
      const library=document.querySelector('[data-zotero-library]');library.value='group:12';library.dispatchEvent(new Event('change'));
    });
    await ready("window.allfoldZoteroPreference.value?.library_id==='12' && !document.querySelector('[data-zotero-collection]').disabled && window.allfoldAutosave.status==='Saved'");
    await check(()=>{
      const collection=document.querySelector('[data-zotero-collection]');
      if(![...collection.options].some(row=>row.textContent==='Parent / Child'))throw Error('Nested Collection path missing');
      collection.value='JKLMNPQR';collection.dispatchEvent(new Event('change'));
    });
    await ready("window.allfoldZoteroPreference.value?.collection_key==='JKLMNPQR' && window.allfoldAutosave.status==='Saved'");
    await size(600,480,"window.workspaceNavigation.current()==='kept'");
    win.webContents.setZoomFactor(1.25);await wait(100);
    await check(()=>{
      const host=document.getElementById('kept-zotero-target'),rect=host.getBoundingClientRect();
      for(const node of host.querySelectorAll('select,button')){const box=node.getBoundingClientRect();if(box.left<rect.left-1 || box.right>rect.right+1)throw Error('Zotero target control overflows narrow Queue');}
      if(document.querySelector('[data-zotero-library]').value!=='group:12' || document.querySelector('[data-zotero-collection]').value!=='JKLMNPQR')throw Error('Saved target changed in narrow Queue');
    });
    await capture('zotero-target-600-zoom125');
    keptState={...keptState,workflow_id:'last-import-fixture',generation:1,phase:'completed',import_started:true,
      message:'Import finished: 3 imported',batch:{total:3,results:[
        {paper_id:'paper-10',service_id:null,service_assignment:'unassigned',outcome:'exported',parent_outcome:'confirmed',reason:'Registered OpenAlex PDF',item_exists:true,pdf_attached:true,pdf_source:'openalex',fallback_used:true},
        {paper_id:'paper-11',service_id:null,service_assignment:'unassigned',outcome:'exported',parent_outcome:'confirmed',reason:'OpenAlex has no direct PDF',item_exists:true,pdf_attached:false,pdf_source:'none',fallback_used:false,diagnostic:{stage:'attachment',step:'oa_resolver',code:'openalex_no_pdf'}},
        {paper_id:'paper-query',service_id:null,service_assignment:'unassigned',outcome:'exported',parent_outcome:'confirmed',reason:'Parent saved',item_exists:true,pdf_attached:null,pdf_source:null,fallback_used:null,query_diagnostic:{code:'connection_lost'}}]}};
    await js("document.getElementById('run-view').dispatchEvent(new Event('close'))");
    await ready("document.querySelectorAll('#kept-record-items li').length===3");
    await check(()=>{
      document.querySelector('#kept-workspace [data-sidebar-view=results]').click();
      const results=document.getElementById('kept-record-items');
      if(!results.textContent.includes('Item Yes · PDF Yes · Fallback Yes') || !results.textContent.includes('PDF 无法核验 · Fallback 无法核验'))throw Error('Last Import indicators lost their evidence');
      if(results.scrollWidth>results.clientWidth+1)throw Error('Last Import overflows narrow Results Sidebar');
      const details=results.querySelector('li:last-child details');details.open=true;
      details.scrollIntoView({block:'nearest'});
    });
    await capture('last-import-600-zoom125');
    await check(()=>document.querySelector('#kept-sidebar [data-sidebar-close]').click());
    win.webContents.setZoomFactor(1);await size(1200,800,"window.workspaceNavigation.current()==='kept'");
    await check(()=>{
      window.workspaceNavigation.go('kept',{instant:true});
      document.querySelector('#kept-workspace [data-sidebar-view=access]').click();
      for(const [field,value] of [['username','new-fixture-user'],['password','synthetic-complete-replacement']]){
        const input=document.getElementById('s-cas-'+field);input.value=value;input.dispatchEvent(new Event('input',{bubbles:true}));
      }
    });
    resolveInitialCAS();await ready("!document.getElementById('s-cas-status').hidden");
    await check(()=>{
      if(document.getElementById('s-cas-username').value!=='new-fixture-user' || document.getElementById('s-cas-password').value!=='synthetic-complete-replacement')throw Error('late credential status discarded newer input');
      if(!document.getElementById('s-cas-status').textContent.includes('无法读取或解密'))throw Error('unreadable credential status reported usable');
    });
    credentialState={...credentialState,revision:'e'.repeat(64)};
    await js("[...document.querySelectorAll('#s-institution-auth button')].find(button=>button.textContent==='Re-read credential status').click()");
    await ready("document.getElementById('s-cas-status').textContent.includes('未提交输入保留')");
    await check(()=>{
      if(document.getElementById('s-cas-username').value!=='new-fixture-user' || document.getElementById('s-cas-password').value!=='synthetic-complete-replacement')throw Error('credential re-read discarded typed replacement');
      document.getElementById('s-cas-save').click();document.querySelector('#s-dialog-actions .s-primary').click();
    });
    await ready("!document.getElementById('s-dialog').open");
    if(credentialWrites.length!==1 || credentialWrites[0].expected_revision!=='e'.repeat(64))throw Error('unreadable credential status did not retain the displayed revision');
    await check(()=>{
      if(document.getElementById('s-cas-password').value==='synthetic-complete-replacement')throw Error('confirmed credential replacement left plaintext input');
      const raw=localStorage.getItem('allfold.configuration-draft:/fixture/monitor.yaml') || '';
      if(raw.includes('synthetic-complete-replacement') || raw.includes('new-fixture-user'))throw Error('credential input entered ordinary recovery storage');
      document.querySelector('#kept-sidebar [data-sidebar-close]').click();
      window.workspaceNavigation.go('workspace',{instant:true});
      document.getElementById('paper-detail').scrollTop=0;
    });
    await capture('paper-identity');
    if(completionStarts.length)throw Error('Viewing results automatically started API completion');
    await js("document.getElementById('array-api-completion-open').click()");
    await ready("document.getElementById('api-completion-dialog').open");
    await check(()=>{
      const choices=[...document.querySelectorAll('#api-completion-papers input')];
      if(choices.filter(input=>input.checked).length!==1 || choices.find(input=>input.checked).value!=='paper-0')throw Error('API completion did not select the current unkept DOI-free Paper');
      choices.find(input=>!input.checked).click();
      document.getElementById('api-completion-start').click();
    });
    await ready("document.getElementById('api-completion-status').textContent.startsWith('Running') && !document.getElementById('api-completion-cancel').hidden");
    await capture('api-completion');
    await js("document.getElementById('api-completion-cancel').click()");
    await ready("document.getElementById('api-completion-status').textContent.startsWith('Cancelled') && document.querySelectorAll('#api-completion-results li').length===2");
    if(completionStarts.length!==1 || completionStarts[0].paper_ids.length!==2)throw Error('API completion did not retain the explicit batch selection');
    await js("document.getElementById('api-completion-close').click()");
    await check(async()=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
      assert($('paper-first-public').textContent==='2022-04','first-public precision was not rendered');
      assert($('paper-journal-dates').textContent==='Accepted · 2026-09 · crossrefPublished online · 2026-10 · crossref','named journal events were not rendered in date order');
      assert(!$('paper-journal-dates').textContent.includes('2022'),'preprint dates entered the journal date collection');
      assert($('paper-first-public').title.includes('arxiv') && !$('paper-first-public').title.includes('crossref'),'First public basis contains journal evidence');
      assert($('paper-source').textContent==='Synthetic Conference','conference source was lost');
      assert($('paper-identifiers').textContent.includes('dblp: conf/example/Paper'),'DOI-free identity was hidden');
      assert($('paper-indexed-terms').textContent.includes('topic · openalex'),'indexed term type/source was lost');
      assert($('paper-doi').textContent==='DOI unavailable' && !$('paper-doi').hasAttribute('href'),'DOI-free paper acquired a DOI link');
      assert([...$('paper-metadata-details').querySelectorAll('[data-enrich]')].every(node=>node.disabled),'DOI-free external Enrich was enabled');
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
      if($('s-save') || document.querySelector('.header-browse #s-save'))throw Error('ordinary global SAVE remains');
      if($('s-settings').querySelector('[data-monitor="name"], [data-monitor="displayName"], #s-institution'))throw Error('Settings contains task-owned fields');
      if($('s-settings').querySelector('.navigation-rail').getBoundingClientRect().width<36)throw Error('Settings navigation rail missing');
      document.querySelector('#s-settings [data-sidebar-view]').click();
      if($('s-settings').dataset.sidebarMode!=='overlay' || $('settings-system-sidebar').hidden)throw Error('Settings System must overlay at 600x480');
      document.querySelector('#settings-system-sidebar [data-sidebar-close]').click();
      $('run-open').click();
      $('s-run-overview-open').click();
      if(document.querySelectorAll('[data-discovery-provider]').length!==2)throw Error('Integrated Provider choices missing');
      if(document.querySelector('[data-provider="pubmed"], [data-monitor="pubmedKey"]'))throw Error('Retired PubMed still displayed');
      const starts=[...document.querySelectorAll('#s-run [data-run-provider]')].filter(node=>!node.hidden && node.getClientRects().length);
      if(starts.length!==2 || !starts.some(node=>node.dataset.runProvider==='integrated') || !starts.some(node=>node.dataset.runProvider==='wos'))throw Error('Run must expose Integrated and independent WoS only');

      if($('s-run').getBoundingClientRect().width>600 || $('s-run').querySelector('.workspace-content').clientWidth<360)throw Error('Run content lost available width');
      document.querySelector('#s-run [data-flyout]').click();
      if($('run-provider-flyout').hidden || $('s-providers').children.length!==7)throw Error('Run Provider Directory did not open');
      $('s-providers').querySelector('[data-provider="crossref"]').click();
      if($('run-configuration-sidebar').hidden || $('s-run').dataset.sidebarMode!=='overlay')throw Error('Provider configuration must overlay at 600x480');
      if(!document.querySelector('#run-configuration-sidebar [data-monitor="crossrefMailto"]'))throw Error('Provider settings not in Functional Sidebar');
      document.querySelector('#run-configuration-sidebar [data-sidebar-close]').click();$('s-run-overview-open').click();

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
    await js("window.workspaceNavigation.go('run',{instant:true}),document.getElementById('s-run-overview-open').click()");
    await capture('run-small');
    await js("document.querySelector('#s-run .s-run-body').scrollTop=document.getElementById('s-run-operations').offsetTop");
    await capture('run-providers-small');
    await js("document.querySelector('#s-run [data-flyout]').click(),document.querySelector('#s-providers [data-provider=crossref]').click()");
    await capture('run-provider-overlay');
    await js("window.workspaceNavigation.go('settings',{instant:true})");
    await capture('settings-small');
    await js("window.workspaceNavigation.go('kept',{instant:true}),document.querySelector('#kept-workspace [data-sidebar-view=access]').click()");
    await check(()=>{
      const $=id=>document.getElementById(id);
      if(!$('kept-access-settings').contains($('s-institution')) || !$('kept-workflow-settings').contains($('s-kept-workflow-fields')))throw Error('Kept did not mount the sole existing settings controls');
      if($('kept-sidebar').hidden || $('kept-workspace').dataset.sidebarMode!=='overlay')throw Error('Kept Access sidebar did not overlay at 600x480');
      const institution=document.querySelector('#kept-access-settings [data-monitor="institutionName"]');
      if(!institution || institution.getBoundingClientRect().width<120)throw Error('Institution input not operable');
      document.querySelector('#kept-workspace [data-sidebar-view=workflow]').click();
      if(document.querySelectorAll('[data-monitor="displayName"]').length!==1 || !document.querySelector('#kept-workflow-settings [data-monitor="delay"]'))throw Error('Workflow controls duplicated or missing');
      const name=document.querySelector('#kept-workflow-settings [data-monitor="displayName"]');name.focus();name.value='Synthetic display';name.dispatchEvent(new Event('input',{bubbles:true}));
      if(document.activeElement!==name || name.value!=='Synthetic display')throw Error('Kept mount bridge lost input focus');
    });
    await capture('kept-workflow-small');

    await check(async()=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);};
      $('run-open').click();
      $('s-run-overview-open').click();
      if(document.querySelectorAll('[data-discovery-provider]').length!==2)throw Error('Integrated Provider choices missing');
      if(document.querySelector('[data-provider="pubmed"], [data-monitor="pubmedKey"]'))throw Error('Retired PubMed still displayed');
      const starts=[...document.querySelectorAll('#s-run [data-run-provider]')].filter(node=>!node.hidden && node.getClientRects().length);
      if(starts.length!==2 || !starts.some(node=>node.dataset.runProvider==='integrated') || !starts.some(node=>node.dataset.runProvider==='wos'))throw Error('Run must expose Integrated and independent WoS only');
$('s-run-overview-open').click();
      const input=document.querySelector('#s-run [data-monitor="name"]');input.focus();input.value='First autosave';input.dispatchEvent(new Event('input',{bubbles:true}));
      const pending=window.allfoldAutosave.flush();await new Promise(resolve=>setTimeout(resolve,20));
      input.value='Newer autosave';input.dispatchEvent(new Event('input',{bubbles:true}));
      $('settings-open').click();$('run-open').click();
      assert(input.value==='Newer autosave','workspace navigation overwrote newer input');
      assert(await pending,'autosave flush failed');assert(input.value==='Newer autosave','late response overwrote newer input');
      assert(await window.allfoldAutosave.flush(),'final autosave did not settle');assert(window.allfoldAutosave.status==='Saved','settled autosave not Saved');
      window.workspaceNavigation.go('workspace',{instant:true});
    });
    await check(async()=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);};
      $('journals-open').click();
      document.querySelector('#s-journals [data-journal]').click();
      const journalId=document.querySelector('#s-journals [data-current=true]').dataset.journal;
      const settle=async()=>assert(await window.allfoldAutosave.flush(),'Journal autosave failed');
      const verify=async field=>{
        const state=await window.uiNext.request('/api/ui-next/settings');
        return state.values.journals.find(journal=>(journal.issn || journal.eissn)===journalId)[field];
      };
      const service=$('s-journal-service');service.value='svc_fixture';service.dispatchEvent(new Event('change',{bubbles:true}));await settle();
      $('s-journal-group').value='group:Group 3';$('s-journal-group').dispatchEvent(new Event('change',{bubbles:true}));await settle();
      assert(await verify('group')==='Group 3','Journal association after autosave was lost');
      $('s-journal-service').value='';$('s-journal-service').dispatchEvent(new Event('change',{bubbles:true}));await settle();
      assert(!await verify('access_service_id'),'repeated Journal Service edit did not persist');
      document.querySelector('[data-flyout=access]').click();
      document.querySelector('#s-entities [data-entity=svc_fixture]').click();$('s-edit-entity').click();
      const url=document.querySelector('[data-service-field=url]');
      for(const value of ['https://example.test/first','https://example.test/second']){
        url.value=value;url.dispatchEvent(new Event('input',{bubbles:true}));await settle();
        assert(document.querySelector('[data-service-field=url]')===url,'ordinary save remounted the Service editor');
        assert((await window.uiNext.request('/api/ui-next/settings')).values.access_services[0].access_url===value,'repeated Service URL edit did not persist');
      }
      window.workspaceNavigation.go('workspace',{instant:true});
    });
    rejectAutosave=true;
    await check(async()=>{
      const input=document.querySelector('[data-monitor="name"]');input.value='Recover ordinary draft';input.dispatchEvent(new Event('input',{bubbles:true}));
      const secret=document.querySelector('[data-monitor="openalexKey"]');secret.value='synthetic-secret-not-for-recovery';secret.dispatchEvent(new Event('input',{bubbles:true}));
      const workspace=document.querySelector('[data-monitor="workspace"]');workspace.value='unsaved-high-impact-path';workspace.dispatchEvent(new Event('input',{bubbles:true}));
      const raw=localStorage.getItem('allfold.configuration-draft:/fixture/monitor.yaml');
      if(!raw || raw.includes('synthetic-secret') || raw.includes('unsaved-high-impact-path'))throw Error('recovery contains explicit secret or Workspace change');
    });
    await win.webContents.executeJavaScript('void 0',true);
    win.webContents.once('will-prevent-unload',event=>event.preventDefault());
    await win.webContents.reload();
    await ready("window.allfoldAutosave && document.querySelector('[data-monitor=name]').value==='Recover ordinary draft'");
    await check(()=>{
      if(document.querySelector('[data-monitor="openalexKey"]').value==='synthetic-secret-not-for-recovery')throw Error('secret restored from ordinary draft');
      if(document.querySelector('[data-monitor="workspace"]').value!=='workspace')throw Error('unconfirmed Workspace restored');
      if(!window.allfoldAutosave.dirty || window.allfoldAutosave.status==='Saved')throw Error('restored unsaved draft reported Saved');
    });
    rejectAutosave=false;
    await check(async()=>{if(!await window.allfoldAutosave.flush())throw Error('recovered draft did not save');});
    await ready("window.uiWorkspace?.ready() && !document.getElementById('array-candidates').disabled");
    await js("window.workspaceNavigation.go('workspace',{instant:true}),document.getElementById('workspace-array').click(),document.querySelector('#kept-view [data-sidebar-view]').click()");
    // Browser is a separate full view; this fixture has no native page Session.
    await js("window.allfoldWorkbench.show()");
    await check(()=>{
      const $=id=>document.getElementById(id),bounds=$('browser-body').getBoundingClientRect();
      if(document.body.dataset.workbench!=='browser' || !$('allfold-pane').inert || bounds.width<240 || bounds.height<120)throw Error('600x480 Browser body is not operable');
      window.allfoldWorkbench.hide();
      if($('allfold-pane').inert || $('kept-view').dataset.sidebarMode!=='overlay')throw Error('Browser return lost Array presentation '+JSON.stringify({inert:$('allfold-pane').inert,mode:$('kept-view').dataset.sidebarMode,layout:$('selected-view').dataset.workspaceLayout,sidebar:$('array-sidebar').hidden}));
    });
    console.log('LAYOUT DOM PASS');
  }catch(error){console.error(error.stack);process.exitCode=1;}
  finally {ipcMain.removeHandler('layout:cas-status');win?.destroy();server.close();fs.rmSync(temp,{recursive:true,force:true});app.exit(process.exitCode || 0);}
});
