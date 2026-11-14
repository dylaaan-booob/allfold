'use strict';
// Real Chromium DOM, isolated HTTP responses; optional actual disk→HTTP Paper input.
const {app,BrowserWindow,ipcMain}=require('electron'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-layout-dom-'));
app.setPath('userData',temp);app.commandLine.appendSwitch('force-prefers-reduced-motion','reduce');
const ui=path.resolve(__dirname,'../../src/allfold/web/static/ui_next');
const journals=Array.from({length:24},(_,i)=>({name:'Synthetic Journal '+i,issn:`000${i}-0000`,eissn:null,group:'Group '+i%4,labels:'Label '+i%3,access_service_id:i%2?'svc_fixture':null}));
const cover_search={phase:'Idle',busy:false,supported:false};
const settings={config_path:'/fixture/monitor.yaml',csrf_token:'fixture',issues:[],covers:{},cover_search,saved_workspace:'/fixture/workspace',values:{
  name:'Synthetic Monitor',keyword_expression:'causal',from_month:'2026-01',to_month:'2026-01',output_dir:'workspace',log_level:'INFO',
  monitor_revision_exists:'1',monitor_revision_digest:'fixture',journal_revision_exists:'1',journal_revision_digest:'fixture',
  institution_name:'',institution_idp_entity_id:'',auto_import_after_preparation:false,transition_delay_seconds:'3',display_name:'',
  provider_aliases:{},provider_order:['pubmed','openalex','europe_pmc','crossref','arxiv','biorxiv','medrxiv','wos'],enabled_providers:['pubmed','openalex'],groups:Array.from({length:20},(_,i)=>'Group '+i),
  custom_labels:['Label 0','Label 1','Label 2'],journals,access_services:[{id:'svc_fixture',name:'Synthetic Service',access_method:'manual',access_url:''}],
}};
const conferenceDates=[
  {kind:'source-date',year:2026,month:10,provider:'openalex',record_id:'W123',publication_type:'conference'},
  {kind:'preprint',year:2022,month:4,provider:'arxiv',record_id:'2204.12345',version:'v1',
    version_family:'arxiv:2204.12345',publication_type:'preprint',first_version:true,source_label:'published',
    url:'https://arxiv.org/abs/2204.12345'},
];
const journalDates=[
  {kind:'published',year:2026,month:3,day:13,provider:'crossref',record_id:'10.5555/layout-1',publication_type:'journal',source_label:'published-print'},
  {kind:'published-online',year:2026,month:3,provider:'wos',record_id:'WOS:fixture',publication_type:'journal',source_label:'EA'},
  {kind:'accepted',year:2026,month:2,provider:'crossref',record_id:'10.5555/layout-1',publication_type:'journal'},
  {kind:'received',year:2025,month:12,day:31,provider:'pubmed',record_id:'12345',publication_type:'journal'},
];
const paper=(i,status='candidate')=>({
  id:'paper-'+i,revision:0,title:'Synthetic Paper '+i,publication_date:'2026-10',
  ...(i===1?{journal:'Synthetic Journal',publication_type:'journal'}:{conference:'Synthetic Conference',publication_type:'conference'}),
  first_public_at:i===0?'2022-04':null,ordinary_dates:i===1?['2025-12-31','2026-02','2026-03-13']:['2026-10'],preprint_evidence:i===0?[conferenceDates[1]]:[],metadata_present:true,excluded:status==='trash',identities:[{namespace:'openalex',value:'W123'}],identity_label:'openalex: W123',
  external_ids:{openalex:'W123'},indexed_terms:[{value:'statistics',kind:'topic',source:'openalex'}],
  sources:[{provider:'openalex',record_id:'W123',role:'discovery'}],
  abstract:('An isolated synthetic paragraph for reader scroll verification. '.repeat(12)+'\n\n').repeat(24),
  authors:['Synthetic Author'],doi:i===0?null:'10.5555/layout-'+i,preprint_lookup_available:i!==0,discovered_at:'2026-10-01T00:00:00Z',status,
});
const records=journals.map((j,i)=>({key:j.issn,issn:j.issn,name:j.name,group:j.group,labels:[],cover:null,papers:[paper(i*2),paper(i*2+1)]}));
const extractedPapers=process.argv[2]?JSON.parse(fs.readFileSync(process.argv[2],'utf8')).papers:[];
if(extractedPapers.length)records.at(-1).papers=extractedPapers;
Object.assign(records[0],{name:'Synthetic Conference',source_type:'unmapped',issn:null,group:'Old scope'});
const workspace={workspace_id:'fixture-library',revision:0,initialized:true,csrf_token:'fixture',issues:[],counts:{candidates:48,active_journals:24},subjects:[{name:'Group 0',journals:records}],
  trash:{papers:[]},downloaded:{papers:[{paper:paper(100,'downloaded'),journal:records[0]},{paper:paper(101,'downloaded'),journal:records[1]}],journals:records,services:[],settings:{},titles:{}}};
const workspaceSnapshot=()=>({...workspace,subjects:workspace.subjects.map(group=>({...group,
  journals:group.journals.filter(journal=>journal.papers.length)})).filter(group=>group.journals.length)});
const run={active:false,snapshot:{status:'IDLE',provider:null},providers:Object.fromEntries(['integrated','wos'].map(id=>[id,{enabled:false,message:'Offline fixture',result_summary:null}]))};
let loginState={active:false,phase:'idle',services:[]};
const mimes={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.ttf':'font/ttf','.otf':'font/otf','.png':'image/png','.mp4':'video/mp4'};
let rejectAutosave=false,holdWorkspaceResponse,holdPaperActionResponse,resolveInitialCAS,credentialState={ok:false,error:'cas_store_unreadable',configured:false,username:'',revision:'d'.repeat(64)};
const credentialWrites=[];
const preprintStarts=[],collectionRetries=[],fieldWrites=[];
let holdFieldResponse;
let preprintState={phase:'Idle',saved_fields:[]};
const server=http.createServer((req,res)=>{
  const route=new URL(req.url,'http://fixture').pathname;
  const action=route.match(/^\/api\/ui-next\/papers\/([^/]+)\/(reject|restore|unexclude|clear-metadata)$/);
  if(action){
    const [,id,kind]=action;
    const candidate=records.flatMap(journal=>journal.papers.map(paper=>({paper,journal}))).find(entry=>entry.paper.id===id);
    const entry=candidate || workspace.downloaded.papers.find(entry=>entry.paper.id===id) || workspace.trash.papers.find(entry=>entry.paper.id===id);
    if(!entry){res.writeHead(404);res.end('{}');return;}
    if(kind==='reject'){
      entry.journal.papers=entry.journal.papers.filter(paper=>paper.id!==id);
      workspace.downloaded.papers=workspace.downloaded.papers.filter(item=>item.paper.id!==id);
      entry.paper.excluded=true;entry.paper.status='trash';workspace.trash.papers.push(entry);
    }else if(kind==='clear-metadata'){
      Object.assign(entry.paper,{title:null,metadata_present:false,abstract:null,authors:[],ordinary_dates:[],preprints:[],preprint_evidence:[],first_public_at:null,sources:[],indexed_terms:[],publication_date:null,preprint_lookup_available:false});
    }else {
      workspace.trash.papers=workspace.trash.papers.filter(item=>item.paper.id!==id);
      entry.paper.excluded=false;entry.paper.status='candidate';if(entry.paper.metadata_present)entry.journal.papers.push(entry.paper);
    }
    workspace.revision++;
    const body=JSON.stringify({workspace_id:workspace.workspace_id,revision:workspace.revision,paper:entry.paper});
    const send=()=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(body);};
    if(holdPaperActionResponse){const release=holdPaperActionResponse;holdPaperActionResponse=null;release(send);}else send();
    return;
  }
  const retry=route.match(/^\/api\/papers\/([^/]+)\/collection\/retry$/);
  if(retry){
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{
      const body=JSON.parse(text),item=records.flatMap(journal=>journal.papers).find(paper=>paper.id===retry[1]);
      collectionRetries.push({id:retry[1],body});
      const valid=body.workspace_id===workspace.workspace_id && body.attempt===item.collection.attempt && body.revision===item.revision;
      if(valid){item.collection_status='running';item.collection={...item.collection,status:'running',attempt:body.attempt+1,retry_available:false};item.revision++;workspace.revision++;}
      res.writeHead(valid?200:409,{'Content-Type':'application/json'});res.end(JSON.stringify(valid?
        {workspace_id:workspace.workspace_id,revision:workspace.revision,paper:item}:{message:'stale retry'}));
    });return;
  }
  const field=route.match(/^\/api\/papers\/([^/]+)\/(fields|fields\/reset|abstract\/input)$/);
  if(field){
    const item=records.flatMap(journal=>journal.papers).find(paper=>paper.id===field[1]);
    const fields=()=>({workspace_id:workspace.workspace_id,snapshot_revision:workspace.revision,
      revision:JSON.stringify([item.abstract,item.authors,item.publication_date]),
      abstract:item.abstract,authors:item.authors,publication_date:item.publication_date});
    const send=value=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
    if(field[2]==='fields'){send(fields());return;}
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{
      const body=JSON.parse(text),valid=body.revision===fields().revision;
      fieldWrites.push({id:item.id,action:field[2],valid,body});
      if(!valid){res.writeHead(409,{'Content-Type':'application/json'});res.end(JSON.stringify({message:'stale field revision'}));return;}
      if(field[2]==='fields/reset'){for(const name of body.fields)item[name]=name==='authors'?[]:null;}
      else item.abstract=body.abstract;
      item.revision++;workspace.revision++;
      const value={saved:true,workspace_id:workspace.workspace_id,revision:workspace.revision,paper:{...item},fields:fields()};
      const deliver=()=>send(value);
      if(holdFieldResponse){const hold=holdFieldResponse;holdFieldResponse=null;hold(deliver);}else deliver();
    });return;
  }
  const preprint=route.match(/^\/api\/papers\/([^/]+)\/preprint-lookup\/(state|start|cancel)$/);
  if(preprint){
    const [,id,action]=preprint;
    const send=(data,status=200)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(data));};
    if(action==='state'){
      send({workspace_id:workspace.workspace_id,revision:workspace.revision,
        ...(preprintStarts.at(-1)?.id===id ? preprintState : {phase:'Idle',saved_fields:[]})});return;
    }
    let text='';req.on('data',chunk=>{text+=chunk;});req.on('end',()=>{
      const body=JSON.parse(text);
      if(action==='start'){
        preprintStarts.push({id,body});
        preprintState={phase:'Running',request_id:'fixture-preprint',message:'Looking up…',saved_fields:[]};
        if(id==='paper-2'){
          records[1].papers.find(paper=>paper.id===id).sources.push({provider:'biorxiv',record_id:'10.1101/fixture:publication',role:'supplement'});
          preprintState={...preprintState,phase:'Completed',message:'Preprint evidence saved',saved_fields:['sources']};
        }
        send({workspace_id:workspace.workspace_id,revision:workspace.revision,...preprintState});
      }else if(id===preprintStarts.at(-1)?.id && body.request_id===preprintState.request_id){
        preprintState={...preprintState,phase:'Cancelled',message:'Preprint lookup cancelled'};
        send({accepted:true});
      }else send({error:'Unexpected preprint target'},409);
    });return;
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
    const body=JSON.stringify(workspaceSnapshot()),release=holdWorkspaceResponse;holdWorkspaceResponse=null;
    release(()=>{res.writeHead(200,{'Content-Type':'application/json'});res.end(body);});return;
  }
  if(route.startsWith('/api/') || route==='/settings/covers/search'){
    const data=route==='/api/ui-next/workspace'?workspaceSnapshot():route==='/api/ui-next/settings'?settings:
      route==='/api/ui-next/run'?run:route==='/api/ui-next/run-expression'?{providers:Object.fromEntries([...settings.values.provider_order,'integrated'].map(id=>[id,{expression:'causal',error:null}]))}:route==='/settings/covers/search'?cover_search:
      route==='/api/login/state'?loginState:{active:false,phase:'idle',navigation:null,can_cancel:false};
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
async function navigateInRenderer(view,buttonId=null) {
  const workflow=!buttonId && ['login','run','kept'].includes(view);
  for(let attempt=0;attempt<150;attempt++){
    if(workflow && document.getElementById('workflow-nav').hidden)document.getElementById('workflows-open').click();
    const button=workflow?document.querySelector(`#workflow-nav [data-workflow="${view}"]`):document.getElementById(buttonId || view+'-open');
    if(button && !button.disabled){
      button.click();
      if(window.workspaceNavigation.current()===view)return;
    }
    await new Promise(resolve=>setTimeout(resolve,50));
  }
  throw Error('Navigation did not reach '+view+' from '+window.workspaceNavigation.current());
}
async function navigate(view){await js(`(${navigateInRenderer.toString()})(${JSON.stringify(view)})`);}
async function check(fn){await js(`(${fn.toString()})(${navigateInRenderer.toString()})`);}
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
    for(const actual of extractedPapers) {
      await navigate('workspace');
      await js(`window.workspaceArray.openPaper(${JSON.stringify(actual.id)})`);
      await ready(`document.getElementById('paper-detail').dataset.paperId===${JSON.stringify(actual.id)} && document.getElementById('paper-abstract').classList.contains('paragraph-layout')`);
      await js(`(()=>{
        const root=document.getElementById('paper-abstract'),reader=document.getElementById('paper-detail');
        const expected=${JSON.stringify(actual.abstract)},selection=getSelection(),range=document.createRange();
        range.selectNodeContents(root);selection.removeAllRanges();selection.addRange(range);
        const transfer=new DataTransfer(),event=new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:transfer});
        root.dispatchEvent(event);
        if(transfer.getData('text/plain')!==expected)throw Error('DTO/disk/HTTP Reader copy changed structured text');
        window.chainReader=reader;window.chainAbstract=root;window.chainParent=reader.parentElement;
        reader.scrollTop=Math.min(120,reader.scrollHeight-reader.clientHeight);window.chainScroll=reader.scrollTop;
      })()`);
      // A same-Paper ordinary-date increment must keep the actual text and Reader.
      actual.ordinary_dates=[...actual.ordinary_dates,'2099-12-31'];workspace.revision++;
      await js('window.uiWorkspace.refresh()');
      await js(`(()=>{
        const reader=document.getElementById('paper-detail'),root=document.getElementById('paper-abstract');
        if(reader!==chainReader || reader.parentElement!==chainParent || root!==chainAbstract || reader.scrollTop!==chainScroll)throw Error('incremental date refresh changed Reader/position');
        const transfer=new DataTransfer();root.dispatchEvent(new ClipboardEvent('copy',{bubbles:true,cancelable:true,clipboardData:transfer}));
        if(transfer.getData('text/plain')!==${JSON.stringify(actual.abstract)})throw Error('incremental refresh lost original selection');
        if(${actual.abstract.length}>1000 && chainScroll<=0)throw Error('long provider abstract did not provide a real scroll check');
      })()`);
    }
    if(extractedPapers.length)await js("getSelection().removeAllRanges(),window.workspaceArray.openPaper('paper-0')");
    await check(async navigate=>{
      if(document.getElementById('array-source-stream'))throw Error('Retired source field remains');
      await navigate('journals');
      if(document.getElementById('s-source-kind'))throw Error('Retired source category remains');
      if(document.getElementById('s-add-journal').textContent!=='+ JOURNAL')throw Error('Journal add control missing');
    });
    await ready("window.inboxRun.available()");
    const firstWorkspaceResponse=new Promise(resolve=>{holdWorkspaceResponse=resolve;});
    records[0].group='Earlier saved group';
    await check(()=>window.dispatchEvent(new Event('settings-saved')));
    const releaseWorkspace=await firstWorkspaceResponse;
    records[0].group='Group 0';records[0].labels=['Label 1'];
    await check(()=>window.dispatchEvent(new Event('settings-saved')));
    releaseWorkspace();
    await ready("window.inboxRun.available() && window.inboxKept.candidates().find(entry=>entry.journal.source_type==='unmapped')?.journal.group==='Group 0'");
    await navigate('workspace');
    await ready("document.getElementById('array-journal-subject').textContent==='Group 0'");
    await navigate('journals');
    await size(600,480,"window.workspaceNavigation.current()==='journals'");
    await size(1200,800,"window.workspaceNavigation.current()==='journals'");
    await check(async navigate=>{
      await navigate('run');
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
    await check(async navigate=>{
      await navigate('login');
      document.querySelector('#login-page [data-sidebar-view=access]').click();
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
      document.querySelector('#login-sidebar [data-sidebar-close]').click();
      document.getElementById('paper-detail').scrollTop=0;
    });
    await navigate('workspace');
    await capture('paper-identity');
    // Resetting the last Paper keeps list membership stable and must patch its existing row.
    const originalPublicationDate=records[0].papers[1].publication_date;
    await js(`(()=>{window.workspaceArray.openPaper('paper-1');document.documentElement.classList.add('developer-mode');window.dispatchEvent(new Event('workspace-navigation-state'));})()`);
    await ready("!document.querySelector('[data-paper-reset=publication_date]').disabled");
    await js(`(()=>{
      window.dateRow=document.querySelector('.paper-row[data-paper-id="paper-1"]');window.dateTime=dateRow.querySelector('time');
      window.dateReader=document.getElementById('paper-detail');window.dateAbstract=document.getElementById('paper-abstract');
      dateReader.scrollTop=160;window.dateScroll=dateReader.scrollTop;
      const range=document.createRange();range.selectNodeContents(dateAbstract);getSelection().removeAllRanges();getSelection().addRange(range);
      const reset=document.querySelector('[data-paper-reset=publication_date]');reset.checked=true;reset.dispatchEvent(new Event('change',{bubbles:true}));
    })()`);
    await ready("!document.getElementById('paper-reset-fields').disabled");
    await js("document.getElementById('paper-reset-fields').click()");
    await ready("window.uiNext.data.subjects.flatMap(g=>g.journals).flatMap(j=>j.papers).find(p=>p.id==='paper-1').publication_date===null && !window.inboxKept.busy()");
    await js(`(()=>{
      const row=document.querySelector('.paper-row[data-paper-id="paper-1"]'),time=row.querySelector('time');
      if(row!==dateRow || time!==dateTime || document.getElementById('paper-detail')!==dateReader ||
        document.getElementById('paper-abstract')!==dateAbstract || dateReader.scrollTop!==dateScroll || !getSelection().toString())throw Error('Date reset remounted Reader/list or lost reading position/selection');
      if(time.textContent!=='—' || time.hasAttribute('datetime') || time.getAttribute('aria-label')!=='Publication date unavailable')throw Error('Date reset left stale Archive row date');
      getSelection().removeAllRanges();
    })()`);
    records[0].papers[1].publication_date=originalPublicationDate;records[0].papers[1].revision++;workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(dateRow.querySelector('time')!==dateTime || dateTime.textContent!=='2026-10' || dateTime.dateTime!=='2026-10' || dateTime.hasAttribute('aria-label'))throw Error('Background date did not patch the existing Archive row');document.documentElement.classList.remove('developer-mode');window.dispatchEvent(new Event('workspace-navigation-state'));window.workspaceArray.openPaper('paper-0');})()`);
    // Same membership/revision increments retain actual Reader DOM, selection and Infos state.
    await js(`(()=>{
      const $=id=>document.getElementById(id);window.wf08Index=$('array-index').firstElementChild;
      window.wf08Reader=$('paper-detail');window.wf08Abstract=$('paper-abstract');
      $('paper-metadata-details').open=false;$('paper-detail').scrollTop=160;window.wf08Scroll=$('paper-detail').scrollTop;
      const range=document.createRange();range.selectNodeContents($('paper-abstract'));getSelection().removeAllRanges();getSelection().addRange(range);
    })()`);
    Object.assign(records[0].papers[0],{revision:1,collection_status:'queued',collection:{status:'queued',attempt:1,cleaning_up:true,retry_available:false}});
    workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{
      const $=id=>document.getElementById(id);
      if($('array-index').firstElementChild!==wf08Index || $('paper-detail')!==wf08Reader || $('paper-abstract')!==wf08Abstract ||
        $('paper-detail').scrollTop!==wf08Scroll || $('paper-metadata-details').open || !getSelection().toString())throw Error('collection state refresh rebuilt reading state');
      if($('paper-collection-status').textContent!=='等待采集')throw Error('queued collection was displayed as terminal cleanup');
      getSelection().removeAllRanges();
    })()`);
    Object.assign(records[0].papers[0],{collection_status:'running',collection:{status:'running',attempt:1,cleaning_up:true,retry_available:false}});
    records[0].papers[0].revision++;workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(document.getElementById('paper-collection-status').textContent!=='正在采集')throw Error('running collection was displayed as terminal cleanup');})()`);
    let deliverCollectionPoll;
    const collectionPollHeld=new Promise(resolve=>{holdWorkspaceResponse=send=>{deliverCollectionPoll=send;resolve();};});
    await collectionPollHeld;
    try {
      await js(`(()=>{if(!window.inboxRun.available() || window.uiRun.active())throw Error('background collection polling occupied foreground Run controls');})()`);
    }finally{deliverCollectionPoll();}
    Object.assign(records[0].papers[0],{revision:2,collection_status:'completed',collection:{status:'completed',attempt:1,retry_available:false}});workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(document.getElementById('paper-collection-status').textContent!=='采集完成' || !document.getElementById('paper-collection-retry').hidden)throw Error('empty completed collection still loads or retries');})()`);
    await capture('wf08-collection-completed');
    // Background fields/status cannot replace an open Abstract draft or a pending save.
    const originalAbstract=records[0].papers[0].abstract,originalDates=[...records[0].papers[0].ordinary_dates];
    records[0].papers[0].abstract=null;records[0].papers[0].revision++;workspace.revision++;
    await js(`window.uiWorkspace.refresh().then(()=>{document.documentElement.classList.add('developer-mode');window.dispatchEvent(new Event('workspace-navigation-state'));})`);
    await ready("!document.getElementById('paper-abstract-input').disabled");
    const originalInputDate=records[0].papers[0].publication_date;
    Object.assign(records[0].papers[0],{abstract:'Background supplied Abstract',publication_date:'2027-03'});
    records[0].papers[0].revision++;workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await ready("document.getElementById('paper-abstract').textContent.includes('Background supplied Abstract') && document.getElementById('paper-abstract-input').disabled && !document.querySelector('[data-paper-reset=abstract]').disabled");
    await js(`(()=>{for(const name of ['abstract','publication_date']){const input=document.querySelector('[data-paper-reset="'+name+'"]');input.checked=true;input.dispatchEvent(new Event('change',{bubbles:true}));}})()`);
    await ready("!document.getElementById('paper-reset-fields').disabled");
    await js("document.getElementById('paper-reset-fields').click()");
    await ready("window.uiNext.data.subjects.flatMap(g=>g.journals).flatMap(j=>j.papers).find(p=>p.id==='paper-0').abstract===null && !window.inboxKept.busy()");
    if(fieldWrites.at(-1)?.id!=='paper-0' || fieldWrites.at(-1)?.action!=='fields/reset' || !fieldWrites.at(-1)?.valid ||
      records[0].papers[0].publication_date!==null)throw Error('Idle field tools sent an obsolete revision after background fields changed');
    records[0].papers[0].publication_date=originalInputDate;records[0].papers[0].revision++;workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await ready("!document.getElementById('paper-abstract-input').disabled");
    await js(`(()=>{document.getElementById('paper-abstract-input').click();const input=document.getElementById('paper-input-text');input.value='Unsubmitted WF08 draft';input.dispatchEvent(new Event('input'));window.wf08Draft=input;})()`);
    records[0].papers[0].ordinary_dates.push('2098-01-01');records[0].papers[0].revision++;workspace.revision++;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{const input=document.getElementById('paper-input-text');if(input!==wf08Draft || input.value!=='Unsubmitted WF08 draft' || !document.getElementById('paper-tools-dialog').open)throw Error('background increment replaced local draft');})()`);
    let deliverField;
    const fieldHeld=new Promise(resolve=>{holdFieldResponse=send=>{deliverField=send;resolve();};});
    await js("document.getElementById('paper-dialog-save').click()");await fieldHeld;
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(document.getElementById('paper-input-text').value!=='Unsubmitted WF08 draft' || !document.getElementById('paper-tools-dialog').open)throw Error('status/snapshot disrupted pending save');})()`);
    deliverField();
    await ready("!document.getElementById('paper-tools-dialog').open && document.getElementById('paper-abstract').textContent.includes('Unsubmitted WF08 draft')");
    records[0].papers[0].abstract=originalAbstract;records[0].papers[0].ordinary_dates=originalDates;records[0].papers[0].revision++;workspace.revision++;
    await js("window.uiWorkspace.refresh().then(()=>{document.documentElement.classList.remove('developer-mode');window.dispatchEvent(new Event('workspace-navigation-state'));})");
    records[0].papers[0].revision++;workspace.revision++;
    Object.assign(records[0].papers[0],{collection_status:'failed',cleanup_pending:true,collection:{status:'failed',attempt:1,
      cleaning_up:true,retry_available:false}});
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(!document.getElementById('paper-collection-retry').disabled || !document.getElementById('paper-collection-status').textContent.includes('清理'))throw Error('Retry was available before cleanup');})()`);
    const retryRevision=++records[0].papers[0].revision;workspace.revision++;
    Object.assign(records[0].papers[0],{cleanup_pending:false,collection:{status:'failed',attempt:1,cleaning_up:false,
      retry_available:false,retry_reason:'unavailable',retry:{attempt:1,revision:retryRevision,token:{metadata_generation:1,operation_generation:1,abstract_generation:1,body_generation:0}}}});
    await js('window.uiWorkspace.refresh()');
    await js(`(()=>{if(!document.getElementById('paper-collection-retry').disabled)throw Error('Retry ignored unavailable access');})()`);
    // Prepare changes access qualification without changing Paper/Workspace content revisions.
    const preparedWorkspaceRevision=workspace.revision;
    loginState={active:true,phase:'preparing',workflow_id:'wf08-prepare-retry',services:[
      {id:'svc_fixture',name:'Synthetic Service',access_method:'manual',access_url:'',preparation:{status:'Preparing'}}]};
    await navigate('login');
    await ready("!document.getElementById('login-cancel').hidden");
    await ready("window.inboxRun.available()");
    Object.assign(records[0].papers[0].collection,{retry_available:true,retry_reason:null});
    loginState={...loginState,active:false,phase:'completed',services:loginState.services.map(service=>({...service,preparation:{status:'Opened'}}))};
    await ready("document.getElementById('login-status').textContent.includes('1 / 1 Services opened')");
    await navigate('workspace');
    await ready("!document.getElementById('paper-collection-retry').disabled");
    if(workspace.revision!==preparedWorkspaceRevision || records[0].papers[0].revision!==retryRevision)throw Error('Prepare qualification refresh changed content revisions');
    await capture('wf08-retry-ready');
    await js("document.getElementById('paper-collection-retry').click()");
    await ready("document.getElementById('paper-collection-status').textContent==='正在采集' && !window.inboxKept.busy()");
    if(collectionRetries.length!==1 || collectionRetries[0].id!=='paper-0' || collectionRetries[0].body.revision!==retryRevision ||
      collectionRetries[0].body.workspace_id!==workspace.workspace_id || collectionRetries[0].body.attempt!==1)throw Error('Retry did not dispatch the captured Paper qualification');
    records[0].papers[0].revision++;workspace.revision++;
    Object.assign(records[0].papers[0],{collection_status:'completed',collection:{status:'completed',attempt:2,retry_available:false}});
    // No explicit refresh: Paper polling continues independently after the foreground is idle.
    await ready("document.getElementById('paper-collection-status').textContent==='采集完成' && document.getElementById('paper-collection-retry').hidden");
    if(preprintStarts.length)throw Error('Viewing results automatically started a preprint lookup');
    await check(()=>{
      const $=id=>document.getElementById(id);
      if($('array-api-completion-open') || $('api-completion-dialog') || $('api-completion-open'))throw Error('Retired completion UI is still present');
      if($('array-sidebar').hidden)document.querySelector('#kept-view [data-sidebar-view=info]').click();
      if($('paper-preprint-lookup').closest('[hidden]') || !$('preprint-lookup-start').disabled ||
         !$('preprint-lookup-status').textContent.includes('正式论文 DOI'))throw Error('DOI-free Paper can dispatch a lookup or lacks a reason');
      window.workspaceArray.openPaper('paper-1');
    });
    await ready("document.getElementById('paper-detail').dataset.paperId==='paper-1' && !document.getElementById('preprint-lookup-start').disabled");
    await js("document.getElementById('preprint-lookup-start').click()");
    await ready("!document.getElementById('preprint-lookup-cancel').hidden");
    await capture('paper-preprint-lookup');
    await check(()=>{
      window.workspaceArray.openPaper('paper-0');
      if(!document.getElementById('preprint-lookup-cancel').hidden)throw Error('A different Paper acquired the active lookup');
      window.workspaceArray.openPaper('paper-1');
      document.getElementById('preprint-lookup-cancel').click();
    });
    await ready("document.getElementById('preprint-lookup-status').textContent==='Preprint lookup cancelled'");
    if(preprintStarts.length!==1 || preprintStarts[0].id!=='paper-1' || preprintStarts[0].body.workspace_id!==workspace.workspace_id)throw Error('Lookup dispatch was not limited to the selected Paper');
    await check(()=>{
      window.workspaceArray.openPaper('paper-2');
      document.getElementById('preprint-lookup-start').click();
    });
    await ready("document.getElementById('preprint-lookup-status').textContent==='Preprint evidence saved' && document.getElementById('paper-providers').textContent.includes('10.1101/fixture:publication')");
    if(preprintStarts.length!==2 || preprintStarts[1].id!=='paper-2')throw Error('Second lookup used the wrong Paper');
    await check(()=>{
      window.workspaceArray.openPaper('paper-0');
      document.querySelector('#array-sidebar [data-sidebar-close]').click();
    });
    await ready("window.inboxRun.available()");
    await check(async navigate=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);},sleep=ms=>new Promise(r=>setTimeout(r,ms));
      assert([...$('paper-dates').querySelectorAll('dt')].map(node=>node.textContent).join('|')==='Dates|Preprint','Reader date labels differ');
      assert([...$('paper-dates').querySelectorAll('dd')].map(node=>node.textContent).join('|')==='2026-10|2022-04','conference date entered the journal dates or First public was lost');
      const evidence=$('paper-date-evidence');
      assert(evidence.closest('#array-sidebar') && evidence.children[0].textContent.includes('2022-04 · arxiv'),'raw evidence is absent from Info or out of order');
      assert(evidence.querySelector('a').href==='https://arxiv.org/abs/2204.12345' && evidence.textContent.includes('Family arxiv:2204.12345'),'First public source link or version facts missing');
      assert($('paper-source').textContent==='Synthetic Conference','conference source was lost');
      assert($('paper-identifiers').textContent==='openalex: W123','Paper direct identity was changed');
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
      $('array-downloaded').click();assert($('kept-view').dataset.status==='downloaded','Downloaded entry did not switch the ARRAY classification');
      $('array-candidates').click();$('array-index-toggle').click();assert($('array-index').scrollTop===200,'Candidate Index scroll lost after visiting Downloaded');document.querySelector('#array-flyout [data-flyout-close]').click();
      window.layoutReader=$('paper-detail');window.layoutParent=layoutReader.parentElement;layoutReader.scrollTop=180;
      document.querySelector('#kept-view [data-sidebar-view]').click();
    });
    await capture('array-wide');
    await size(700,500,"document.getElementById('kept-view').dataset.sidebarMode==='overlay'");
    await check(async navigate=>{
      const root=document.getElementById('kept-view'),reader=document.getElementById('paper-detail');
      if(root.dataset.sidebarMode!=='overlay')throw Error('narrow Array must overlay');
      if(reader!==window.layoutReader || reader.parentElement!==window.layoutParent || reader.scrollTop!==180)throw Error('resize changed Reader identity/scroll');
      await navigate('journals');
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
    await check(async navigate=>{
      const $=id=>document.getElementById(id),input=$('s-entity-description').querySelector('[data-service-field=url]');
      if(input!==window.layoutDraft || input.parentElement!==window.layoutDraftParent || input.value!=='https://synthetic.test/draft' || document.activeElement!==input)throw Error('resize lost Service draft/focus');
      if($('s-journals-page').dataset.sidebarMode!=='docked')throw Error('wide Journals must dock');
      const resize=document.querySelector('#journal-sidebar .sidebar-resize');resize.dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowLeft',bubbles:true,cancelable:true}));
      if(input!==window.layoutDraft || document.activeElement!==input)throw Error('sidebar sizing rebuilt editor');
      $('s-developer-mode').checked=true;$('s-developer-mode').dispatchEvent(new Event('change'));
      const target=$('layout-sidebarPreferredWidth');target.value='420';target.dispatchEvent(new Event('input'));$('layout-save').click();$('layout-origin').click();
      if(target.value!=='320')throw Error('ORIGIN did not restore defaults');$('layout-reset').click();if(target.value!=='420')throw Error('RESET lost saved target');
      if(document.querySelector('footer').getBoundingClientRect().height>86)throw Error('developer footer unbounded');
      await navigate('workspace');
    });
    await capture('array-developer');
    await size(600,480,"document.getElementById('kept-view').dataset.sidebarMode==='overlay'");
    await check(async navigate=>{
      const $=id=>document.getElementById(id),root=$('kept-view'),tools=root.querySelector('.tool-rail'),main=$('array-content');
      if(root.dataset.sidebarMode!=='overlay')throw Error('600px Array must overlay');
      if(tools.getBoundingClientRect().right>root.getBoundingClientRect().right+1 || main.clientWidth<360)throw Error('rails/content overflow');
      if($('reject-paper').getBoundingClientRect().bottom>main.getBoundingClientRect().bottom)throw Error('low-height primary decision unreachable');
      if(document.querySelector('.masthead').getBoundingClientRect().bottom>root.getBoundingClientRect().top+1 || document.querySelector('footer').getBoundingClientRect().top<root.getBoundingClientRect().bottom-1)throw Error('Chrome or Status overlaps content');
      await navigate('journals');
    });
    await wait(100);
    await check(()=>{
      const root=document.getElementById('s-journals-page'),list=document.getElementById('s-journals');
      if(root.dataset.sidebarMode!=='overlay' || list.clientHeight<100)throw Error('600x480 Journals is not operable');
      const trigger=document.querySelector('[data-flyout=subject]');trigger.click();
      if(document.getElementById('s-entities').clientHeight<100)throw Error('low-height Directory cannot scroll');
    });
    await capture('journals-small');
    await check(async navigate=>{
      const $=id=>document.getElementById(id);await navigate('settings');
      if($('s-settings').clientHeight<100)throw Error('Settings lost its parent height');
      for(const [key,min,max,label] of [['managedPageGlobalLimit','4','64','Managed pages total'],['managedPageServiceLimit','3','16','Pages per Service']]) {
        const input=document.querySelector(`[data-monitor="${key}"]`);
        if(!input || input.min!==min || input.max!==max || !input.closest('label').textContent.includes(label) || input.getBoundingClientRect().height===0)throw Error('Physical Browser page limits are not visible with their actual ranges');
      }
      if(document.querySelector('[data-monitor="pdfConcurrency"]'))throw Error('Inactive PDF controls must stay hidden');
      if($('s-save') || document.querySelector('.header-browse #s-save'))throw Error('ordinary global SAVE remains');
      if($('s-settings').querySelector('[data-monitor="name"], [data-monitor="displayName"], #s-institution'))throw Error('Settings contains task-owned fields');
      if($('s-settings').querySelector('.navigation-rail').getBoundingClientRect().width<36)throw Error('Settings navigation rail missing');
      document.querySelector('#s-settings [data-sidebar-view]').click();
      if($('s-settings').dataset.sidebarMode!=='overlay' || $('settings-system-sidebar').hidden)throw Error('Settings System must overlay at 600x480');
      document.querySelector('#settings-system-sidebar [data-sidebar-close]').click();
      await navigate('run');
      $('s-run-overview-open').click();
      if(document.querySelectorAll('[data-discovery-provider]').length!==3)throw Error('Integrated Provider choices missing');
      if(!document.querySelector('[data-provider="pubmed"]') || !document.querySelector('[data-monitor="pubmedKey"]'))throw Error('PubMed provider or optional credential missing');
      if(document.querySelector('[data-discovery-provider="europe_pmc"]'))throw Error('Europe PMC must remain completion-only');
      if(!document.querySelector('[data-discovery-provider="pubmed"]').checked || !document.querySelector('[data-discovery-provider="openalex"]').checked)throw Error('PubMed/OpenAlex Discovery defaults missing');
      const starts=[...document.querySelectorAll('#s-run [data-run-provider]')].filter(node=>!node.hidden && node.getClientRects().length);
      if(starts.length!==1 || starts[0].dataset.runProvider!=='integrated')throw Error('Run must expose one unified selected-source action');
      if(document.querySelector('[data-discovery-provider="wos"]').checked)throw Error('WoS must not become enabled automatically');

      if($('s-run').getBoundingClientRect().width>600 || $('s-run').querySelector('.workspace-content').clientWidth<360)throw Error('Run content lost available width');
      document.querySelector('#s-run [data-flyout]').click();
      if($('run-provider-flyout').hidden || $('s-providers').children.length!==8)throw Error('Run Provider Directory did not open');
      $('s-providers').querySelector('[data-provider="crossref"]').click();
      if($('run-configuration-sidebar').hidden || $('s-run').dataset.sidebarMode!=='overlay')throw Error('Provider configuration must overlay at 600x480');
      if(!document.querySelector('#run-configuration-sidebar [data-monitor="crossrefMailto"]'))throw Error('Provider settings not in Functional Sidebar');
      document.querySelector('#run-configuration-sidebar [data-sidebar-close]').click();$('s-run-overview-open').click();

      await navigate('workspace');
      window.allfoldUIPreferences.setArchiveDisabled(false);$('array-index-toggle').click();$('array-index').scrollTop=200;$('workspace-archive').click();
      if($('selected-view').dataset.workspaceLayout!=='archive' || !$('kept-view').hidden)throw Error('Archive restoration failed');
      archiveDebug.values.height=200;window.dispatchEvent(new Event('archive-debug-change'));
      if(Math.abs($('selected-view').getBoundingClientRect().height-200)>1)throw Error('Archive tuned height is overridden by flexible fill');
      $('workspace-array').click();
      if($('selected-view').getBoundingClientRect().height!==$('allfold-pane').getBoundingClientRect().height)throw Error('Archive height leaked into ARRAY');
      $('array-index-toggle').click();if($('array-index').scrollTop!==200)throw Error('Index scroll lost through Archive entry');
      document.querySelector('#array-flyout [data-flyout-close]').click();
    });
    await navigate('run');
    await js("document.getElementById('s-run-overview-open').click()");
    await capture('run-small');
    await js("document.querySelector('#s-run .s-run-body').scrollTop=document.getElementById('s-run-operations').offsetTop");
    await capture('run-providers-small');
    await js("document.querySelector('#s-run [data-flyout]').click(),document.querySelector('#s-providers [data-provider=crossref]').click()");
    await capture('run-provider-overlay');
    const integratedSummary={availability:'available',provider:'integrated',status:'incomplete',
      outcome:'COMPLETED_WITH_ERRORS',coverage_status:'partial',created_papers:2,existing_papers:1,
      finished_at:'2026-11-07T01:00:00Z',resolved_date_range:{from_date:'2026-01-01',to_date:'2026-03-31'},
      journals:[],statistics:{integrated_candidates:3,integrated_deduplicated:3,conflicts:1,identity_targets:2,identity_requests:3,collection_admitted:2,collection_registration_failed:1},
      issues:[{category:'discovery',severity:'error',message:'pubmed / Synthetic Journal: request failed'}],
      details:{discovery_status:'partial',provider_runs:[
        {provider:'openalex',source:'Synthetic Journal',status:'complete',candidates:3,retained:3,limitations:[]},
        {provider:'pubmed',source:'Synthetic Journal',status:'failed',candidates:0,retained:0,limitations:['request failed']}]}};
    run.providers.integrated.result_summary=integratedSummary;
    await js("document.getElementById('s-run-overview-open').click(),window.uiRunPage.refresh()");
    await check(()=>{
      const root=document.querySelector('#s-run-records .s-run-record');
      root.querySelector('details').open=true;
      const text=root.innerText;
      for(const expected of ['完成，检索不完整','2 new papers','1 already saved','Provider Details','Candidates','Distinct Papers','Paper collection','Identity targets','Identity HTTP requests','Collection admitted','Registration failed','Identity conflicts','openalex','pubmed','request failed','检索'])if(!text.includes(expected))throw Error('Missing Integrated result: '+expected);
      if(/Source Resolution|OpenAlex records/.test(text) || root.querySelector('.s-run-coverage'))throw Error('Obsolete OpenAlex result surface');
      const content=document.querySelector('#s-run .workspace-content');
      if(content.scrollWidth>content.clientWidth+1)throw Error('Run result overflows constrained content');
    });
    await js("document.getElementById('s-run-records').scrollIntoView({block:'start'})");
    await capture('run-results-partial');
    await js("document.querySelector('#s-run-records .s-run-provider-details').scrollIntoView({block:'start'})");
    await capture('run-results-partial-details');
    for(const [status,retrieval,outcome] of [
      ['completed','complete','COMPLETED'],['completed','empty','COMPLETED'],
      ['failed','failed','FAILED'],['cancelled','cancelled','CANCELLED'],
      ['capture_issues','complete','COMPLETED_WITH_ERRORS'],
      ['completed_with_notices','complete','COMPLETED_WITH_WARNINGS']]){
      const hasHits=['complete','partial'].includes(retrieval);
      run.providers.integrated.result_summary={...integratedSummary,status,outcome,coverage_status:retrieval,
        created_papers:hasHits?2:0,existing_papers:hasHits?1:0,
        statistics:{integrated_candidates:hasHits?6:0,integrated_deduplicated:hasHits?3:0},
        issues:status==='capture_issues'?[{category:'write',severity:'error',message:'Synthetic Paper creation failed'}]:
          status==='completed_with_notices'?[{category:'snapshot_write',severity:'warning',message:'Synthetic snapshot unavailable'}]:[],
        details:{discovery_status:retrieval,provider_runs:integratedSummary.details.provider_runs.map(row=>({...row,
          status:retrieval,candidates:hasHits?3:0,retained:hasHits?3:0,limitations:[]}))}};
      await js('window.uiRunPage.refresh()');
      const rendered=await js("document.querySelector('#s-run-records [data-result-status]').dataset.resultStatus");
      if(rendered!==status)throw Error('Run terminal status changed: '+status+' / '+rendered);
    }
    run.providers.integrated.result_summary={...integratedSummary,outcome:'COMPLETED_WITH_ERRORS',
      journals:[{key:'0006-341X',name:'Synthetic WoS Journal',status:'hint',records:2,
        identifiers:[{issn:'0006-341X',status:'local_not_listed',records:null}]}],
      statistics:{...integratedSummary.statistics,returned_records:2,eligible_records:1,unmatched_journal_records:1},
      details:{...integratedSummary.details,query_finished:false,search_total:3,
        provider_runs:[{provider:'wos',source:'Synthetic WoS Journal',status:'partial',candidates:3,
          retained:2,created:1,existing:1,limitations:['batch_count_mismatch']},...integratedSummary.details.provider_runs],
        batches:[{first:1,last:3,expected:3,exported:2,eligible:1,complete:false,issues:['batch_count_mismatch']}],
        date_warnings:[{record_number:1,doi:'10.5555/wos',reasons:['PD_PY_year_conflict']}]},
      issues:[{category:'snapshot_write',severity:'warning',message:'Synthetic result not saved'}]};
    await js("window.uiRunPage.refresh().then(()=>{document.querySelector('#s-run [data-flyout]').click();document.querySelector('#s-providers [data-provider=wos]').click();document.querySelector('#run-configuration-sidebar [data-sidebar-close]').click();})");
    await check(()=>{
      const root=document.getElementById('s-run-records');
      root.querySelector('.s-run-provider-details').open=true;
      root.querySelector('.s-run-journals details').open=true;
      const text=root.innerText;
      for(const expected of ['Journal Coverage','Synthetic WoS Journal','Export batches','Export 1–3','导出记录数与预期不一致','Publication date hints','出版日期与出版年份不一致','最近结果未保存','Unmatched Journal records','wos','openalex','pubmed'])if(!text.includes(expected))throw Error('Missing unified WoS result: '+expected);
      if(root.querySelectorAll('.s-run-record').length!==1)throw Error('WoS results must share one Run record');
    });
    await js("document.getElementById('s-run-records').scrollIntoView({block:'start'})");
    await capture('run-results-wos');
    await js("document.querySelector('#s-run-records .s-run-provider-details').scrollIntoView({block:'start'})");
    await capture('run-results-wos-details');
    run.providers.integrated.result_summary={availability:'unsupported',error:'旧版运行记录，请重新运行生成结果。'};
    await js("window.uiRunPage.refresh().then(()=>document.getElementById('s-run-overview-open').click())");
    await check(()=>{
      const rows=document.querySelectorAll('#s-run-records .s-run-record');
      if(!rows[0].innerText.includes('旧版运行记录，请重新运行生成结果。'))throw Error('Missing old Integrated rerun prompt');
      if(rows.length!==1)throw Error('Unsupported unified snapshot must not restore a separate legacy result');
    });
    await js("document.getElementById('s-run-records').scrollIntoView({block:'start'})");
    await capture('run-results-unsupported');
    await navigate('settings');
    await capture('settings-small');
    await ready("window.inboxRun.available()");
    const pendingLibrarySnapshot=new Promise(resolve=>{holdWorkspaceResponse=resolve;});
    await js("void window.allfoldRefreshWorkspace()");
    const releaseLibrarySnapshot=await pendingLibrarySnapshot;
    await check(()=>{if(window.workspaceNavigation.go('journals',{instant:true}))throw Error('Pending Workspace snapshot did not guard navigation');});
    setTimeout(releaseLibrarySnapshot,90);
    await navigate('login');
    await js("document.querySelector('#login-page [data-sidebar-view=access]').click()");
    await check(async navigate=>{
      const $=id=>document.getElementById(id);
      if(!$('login-access-settings').contains($('s-institution')))throw Error('Login did not mount the existing Institution controls');
      if($('login-sidebar').hidden || $('login-page').dataset.sidebarMode!=='overlay')throw Error('Login Access sidebar did not overlay at 600x480');
      const institution=document.querySelector('#login-access-settings [data-monitor="institutionName"]');
      if(!institution || institution.getBoundingClientRect().width<120)throw Error('Institution input not operable');
      document.querySelector('#login-page [data-sidebar-view=workflow]').click();
      if(document.querySelectorAll('#login-workflow-settings [data-monitor="prepareServiceConcurrency"]').length!==1)throw Error('Login concurrency missing');
    });
    await capture('login-workflow-small');

    await check(async navigate=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);};
      await navigate('run');
      $('s-run-overview-open').click();
      if(document.querySelectorAll('[data-discovery-provider]').length!==3)throw Error('Integrated Provider choices missing');
      if(!document.querySelector('[data-provider="pubmed"]') || !document.querySelector('[data-monitor="pubmedKey"]'))throw Error('PubMed provider or optional credential missing');
      if(document.querySelector('[data-discovery-provider="europe_pmc"]'))throw Error('Europe PMC must remain completion-only');
      if(!document.querySelector('[data-discovery-provider="pubmed"]').checked || !document.querySelector('[data-discovery-provider="openalex"]').checked)throw Error('PubMed/OpenAlex Discovery defaults missing');
      const starts=[...document.querySelectorAll('#s-run [data-run-provider]')].filter(node=>!node.hidden && node.getClientRects().length);
      if(starts.length!==1 || starts[0].dataset.runProvider!=='integrated')throw Error('Run must expose one unified selected-source action');
      if(document.querySelector('[data-discovery-provider="wos"]').checked)throw Error('WoS must not become enabled automatically');
$('s-run-overview-open').click();
      const input=document.querySelector('#s-run [data-monitor="name"]');input.focus();input.value='First autosave';input.dispatchEvent(new Event('input',{bubbles:true}));
      const pending=window.allfoldAutosave.flush();await new Promise(resolve=>setTimeout(resolve,20));
      input.value='Newer autosave';input.dispatchEvent(new Event('input',{bubbles:true}));
      await navigate('settings');await navigate('run');
      assert(input.value==='Newer autosave','workspace navigation overwrote newer input');
      assert(await pending,'autosave flush failed');assert(input.value==='Newer autosave','late response overwrote newer input');
      assert(await window.allfoldAutosave.flush(),'final autosave did not settle');assert(window.allfoldAutosave.status==='Saved','settled autosave not Saved');
      await navigate('workspace');
    });
    await check(async navigate=>{
      const $=id=>document.getElementById(id),assert=(ok,message)=>{if(!ok)throw Error(message);};
      await navigate('journals');
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
      await navigate('workspace');
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
    await navigate('workspace');
    await js("document.getElementById('workspace-array').click(),document.querySelector('#kept-view [data-sidebar-view]').click()");
    // Browser is a separate full view; this fixture has no native page Session.
    await js("window.allfoldWorkbench.show()");
    await check(()=>{
      const $=id=>document.getElementById(id),bounds=$('browser-body').getBoundingClientRect();
      if(document.body.dataset.workbench!=='browser' || !$('allfold-pane').inert || bounds.width<240 || bounds.height<120)throw Error('600x480 Browser body is not operable');
      window.allfoldWorkbench.hide();
      if($('allfold-pane').inert || $('kept-view').dataset.sidebarMode!=='overlay')throw Error('Browser return lost Array presentation '+JSON.stringify({inert:$('allfold-pane').inert,mode:$('kept-view').dataset.sidebarMode,layout:$('selected-view').dataset.workspaceLayout,sidebar:$('array-sidebar').hidden}));
    });
    await navigate('workspace');
    await js("window.workspaceArray.openPaper('paper-1')");
    await ready("document.getElementById('paper-detail').dataset.paperId==='paper-1'");
    await check(()=>{
      const dates=[...document.querySelectorAll('#paper-dates dd')].map(node=>node.textContent).join('|');
      if(dates!=='2025-12-31 · 2026-02 · 2026-03-13|—')throw Error('Reader ordinary dates differ: '+dates);
      if(document.querySelector('[data-enrich]') || document.getElementById('keep-paper') || document.querySelector('[data-workflow="kept"]'))throw Error('Retired business action remains executable');
    });
    await ready("!document.getElementById('reject-paper').disabled");
    const pendingReject=new Promise(resolve=>{holdPaperActionResponse=resolve;});
    await js("document.getElementById('reject-paper').click()");
    const releaseReject=await pendingReject;
    await js("uiNext.request('/api/papers/paper-1/preprint-lookup/state')");
    releaseReject();
    await ready("!window.inboxKept.candidates().some(entry=>entry.paper.id==='paper-1') && window.inboxKept.entries('trash').some(entry=>entry.paper.id==='paper-1')");
    await js("document.getElementById('array-trash').click()");
    await ready("document.getElementById('paper-detail').dataset.paperId==='paper-1' && !document.getElementById('restore-paper').disabled");
    await js("document.getElementById('restore-paper').click()");
    await ready("window.inboxKept.candidates().some(entry=>entry.paper.id==='paper-1') && !window.inboxKept.entries('trash').some(entry=>entry.paper.id==='paper-1')");
    await js("document.getElementById('array-candidates').click(),window.workspaceArray.openPaper('paper-0')");
    await ready("document.getElementById('paper-detail').dataset.paperId==='paper-0' && !document.getElementById('reject-paper').disabled");
    await js("document.getElementById('reject-paper').click()");
    await ready("window.inboxKept.entries('trash').some(entry=>entry.paper.id==='paper-0')");
    await js("document.getElementById('array-trash').click(),window.workspaceArray.openPaper('paper-0')");
    await ready("!document.getElementById('clear-paper-metadata').disabled");
    await js("document.getElementById('clear-paper-metadata').click()");
    await ready("document.getElementById('view-paper-title').textContent==='openalex: W123' && document.getElementById('paper-preprint-lookup').hidden && document.getElementById('paper-dev-tools').hidden");
    await check(()=>{
      if(document.getElementById('paper-date-evidence').children.length || [...document.querySelectorAll('#paper-dates dd')].some(node=>node.textContent!=='—'))throw Error('Cleared metadata reappeared');
    });
    for(const id of ['paper-8','paper-9']){
      await js(`document.getElementById('array-candidates').click(),window.workspaceArray.openPaper('${id}')`);
      await ready(`document.getElementById('paper-detail').dataset.paperId==='${id}' && !document.getElementById('reject-paper').disabled`);
      await js("document.getElementById('reject-paper').click()");
      await ready(`window.inboxKept.entries('trash').some(entry=>entry.paper.id==='${id}')`);
    }
    await check(()=>{
      if(uiNext.data.subjects.some(group=>group.journals.some(journal=>journal.key==='0004-0000')))throw Error('Last Candidate Journal remained in subjects');
    });
    await js("window.allfoldRefreshWorkspace()");
    await js("document.getElementById('array-trash').click(),window.workspaceArray.openPaper('paper-9')");
    await ready("document.getElementById('paper-detail').dataset.paperId==='paper-9' && !document.getElementById('restore-paper').disabled");
    await js("document.getElementById('restore-paper').click()");
    await ready("window.inboxKept.candidates().some(entry=>entry.paper.id==='paper-9')");
    await check(()=>{
      const group=uiNext.data.subjects.find(group=>group.journals.some(journal=>journal.papers.some(paper=>paper.id==='paper-9')));
      const journal=window.inboxKept.candidates().find(entry=>entry.paper.id==='paper-9').journal;
      if(group?.name!=='Group 0' || journal.key!=='0004-0000' || journal.group!=='Group 0' || journal.logicalGroupName!=='Group 0')throw Error('Restore lost the saved Journal/Group projection');
      document.getElementById('array-candidates').click();window.workspaceArray.openPaper('paper-9');
      if(document.getElementById('array-journal-subject').textContent!=='Group 0')throw Error('ARRAY restored the wrong group label');
    });
    await ready("!document.getElementById('reject-paper').disabled");
    await js("document.getElementById('reject-paper').click()");
    await ready("window.inboxKept.entries('trash').some(entry=>entry.paper.id==='paper-9')");
    await js("document.getElementById('array-trash').click(),window.workspaceArray.openPaper('paper-9')");
    await ready("!document.getElementById('clear-paper-metadata').disabled");
    await js("document.getElementById('clear-paper-metadata').click()");
    await ready("!window.inboxKept.entries('trash').find(entry=>entry.paper.id==='paper-9').paper.metadata_present");
    await check(()=>{
      const journal=window.inboxKept.entries('trash').find(entry=>entry.paper.id==='paper-9').journal;
      if(journal.source_type!=='unmapped' || journal.issn!==null || journal.group!==null)throw Error('Cleared Paper retained its former Journal grouping');
    });
    console.log('LAYOUT DOM PASS');
  }catch(error){console.error(error.stack);process.exitCode=1;}
  finally {ipcMain.removeHandler('layout:cas-status');win?.destroy();server.close();fs.rmSync(temp,{recursive:true,force:true});app.exit(process.exitCode || 0);}
});
