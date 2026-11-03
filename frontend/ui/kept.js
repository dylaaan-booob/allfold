import {KeptPlayer} from './kept-player.js';
import {sceneReady,shots} from './kept/scene';
import {importOutcomeMessage,preparationReason} from './business-results.js';
const $=id=>document.getElementById(id),bridge=window.inboxKept;
const exportButton=document.createElement('button');
exportButton.type='button';exportButton.className='s-button';exportButton.textContent='导出本次诊断';exportButton.hidden=true;
$('array-import-profile').append(exportButton);
exportButton.addEventListener('click',async()=>{
  if(!lastRun?.workflow_id)return;
  exportButton.disabled=true;
  try {await window.allfoldHistory.exportTask(lastRun.workflow_id);uiNext.notice('诊断包已在本地生成，未上传。');}
  catch(error){uiNext.notice(error.message);}
  finally {exportButton.disabled=false;}
});
const reduced=matchMedia('(prefers-reduced-motion: reduce)'),dialog=$('kept-flow');
const states=Object.fromEntries(['candidates','kept'].map(status=>[status,{filter:null,selected:null,reader:false,indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false}]));
let status='candidates',ui=states.candidates;
let data,metadata,active=null,lastRun=null,workflow=null,pollTimer=null,submitting=false,acknowledging=false,recovering=true,readerRefreshPending=false;
let workspaceEpoch=0;
const arrayShown=()=>window.workspaceNavigation.current()==='workspace' && $('selected-view').dataset.workspaceLayout==='array';
const workflowBusy=()=>submitting || acknowledging || Boolean(workflow?.active || workflow?.navigation);
const switchBusy=()=>recovering || !data || !metadata || !bridge.available() || bridge.busy() || workflowBusy() || $('run-view').open || dialog.open;
const allEntries=()=>bridge.papers();
const visibleEntries=()=>status==='candidates'?bridge.candidates():allEntries();
const key=entry=>entry.journal.key || entry.journal.name;
function groups(entries=visibleEntries(),journals=data.journals) {
  const buckets=new Map(),ranks=new Map(journals.map((j,i)=>[j.key,i]));
  for(const entry of entries) {
    const id=key(entry);
    if(!buckets.has(id)) buckets.set(id,{id,journal:entry.journal,entries:[]});
    buckets.get(id).entries.push(entry);
  }
  return [...buckets.values()].sort((a,b)=>(ranks.get(a.journal.key)??Infinity)-(ranks.get(b.journal.key)??Infinity));
}
function orderedEntries(entries=visibleEntries(),journals=data.journals) {
  return groups(entries,journals).filter(g=>status==='kept' || g.id===ui.filter).flatMap(g=>status==='candidates'?g.entries:[...g.entries].sort((a,b)=>{
    return (b.paper.publication_date||'').localeCompare(a.paper.publication_date||'') ||
      (b.paper.discovered_at||'').localeCompare(a.paper.discovered_at||'') || a.paper.id.localeCompare(b.paper.id);
  }));
}
function refreshActions() {
  const layout=$('workspace-layout'),host=$($('selected-view').dataset.workspaceLayout==='array'?'array-layout-controls':'archive-layout-controls');
  if(layout.parentElement!==host)host.append(layout);
  window.workspaceNavigation.refresh();
  const busy=switchBusy();
  for(const id of ['workspace-archive','workspace-array','array-candidates','array-kept'])$(id).disabled=busy;
  $('workspace-archive').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='archive'));
  $('workspace-array').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='array'));
  $('array-candidates').setAttribute('aria-pressed',String(status==='candidates'));
  $('array-kept').setAttribute('aria-pressed',String(status==='kept'));
  $('array-status').hidden=$('selected-view').dataset.workspaceLayout!=='array';
  if(!data)return;
  $('kept-start').disabled=$('kept-import-only').disabled=busy || workflow?.active || !allEntries().length;
  for(const row of $('array-index').children)row.disabled=busy;
  workspaceSearch.refresh();
}
function renderRecord() {
  exportButton.hidden=!lastRun?.workflow_id;
  const results=lastRun?.results || [],exported=results.filter(r=>r.outcome==='exported').length;
  $('kept-record-count').textContent=lastRun?`${exported} / ${lastRun.total}`:'—';
  $('kept-record-summary').textContent=lastRun?.message || '本次尚未导入。';
  $('kept-record-items').replaceChildren(...results.map(result=>{
    const item=document.createElement('li'),title=document.createElement('strong'),reason=document.createElement('small');
    item.dataset.outcome=result.outcome;title.textContent=result.title;title.title=result.title;
    reason.textContent=result.outcome==='exported'
      ? importOutcomeMessage(result.outcome,result.pdf_outcome)
      : result.reason;
    const details=document.createElement('details'),summary=document.createElement('summary'),raw=document.createElement('p');
    details.className='import-result-details';summary.textContent='详情';
    const pdf=result.pdf_outcome;
    raw.textContent=result.reason+(pdf && !result.reason.toLowerCase().includes(`pdf ${pdf}`)?`\nPDF: ${pdf}`:'');
    details.append(summary,raw);item.append(title,reason,details);return item;
  }));
}
function render() {
  if(!data)return;
  const journals=groups();
  if(status==='candidates' && !journals.some(g=>g.id===ui.filter)){
    ui.filter=journals[ui.indexPosition % journals.length]?.id || null;
  }
  const entries=orderedEntries();
  if(!entries.some(e=>e.paper.id===ui.selected)){
    ui.selected=ui.missingLinkPaper?null:(entries[(status==='kept'?ui.indexPosition:0) % entries.length]?.paper.id || null);
  }
  const choices=status==='candidates'
    ? journals.map(g=>({id:g.id,name:g.journal.name,count:g.entries.length}))
    : entries.map(entry=>({id:entry.paper.id,name:entry.paper.title}));
  const selected=status==='candidates'?ui.filter:ui.selected;
  ui.indexPosition=Math.max(0,choices.findIndex(choice=>choice.id===selected));
  const index=$('array-index'),focused=index.contains(document.activeElement);
  const previous=[...index.children].find(row=>row.getAttribute('aria-current')==='true')?.dataset.indexId;
  const maxCount=Math.max(10,...choices.map(c=>c.count || 0));
  index.setAttribute('aria-label',status==='candidates'?'Candidate Journals':'Kept Papers');
  index.replaceChildren(...choices.map((choice,i)=>{
    const button=document.createElement('button');button.className='kept-manager-row';button.title=choice.name;
    button.dataset.indexId=choice.id;
    button.setAttribute('aria-current',String(choice.id===selected));
    button.style.setProperty('--index-rail',choice.count===undefined?'6px':Math.round(6+18*Math.log10(choice.count+1)/Math.log10(maxCount+1))+'px');
    const columns=[['number',String(i).padStart(2,'0')],['name',choice.name]];
    if(choice.count!==undefined)columns.push(['count',String(choice.count)]);
    for(const [role,text] of columns){const span=document.createElement('span');span.className='rhine-index-'+role;span.textContent=text;button.append(span);}
    button.addEventListener('click',()=>selectIndex(choice.id));return button;
  }));
  index.scrollTop=ui.indexScroll;index.scrollLeft=ui.indexLeft;
  if(focused)index.children[ui.indexPosition]?.focus({preventScroll:true});
  if(arrayShown() && previous!==selected){
    index.children[ui.indexPosition]?.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
    ui.indexScroll=index.scrollTop;ui.indexLeft=index.scrollLeft;
  }
  $('array-journal-profile').hidden=status!=='candidates';
  $('array-import-profile').hidden=status!=='kept';
  const journal=journals.find(group=>group.id===ui.filter)?.journal;
  $('array-journal-name').textContent=journal?.name || '尚无待审阅期刊';
  $('array-journal-issn').textContent=journal?.issn || '—';
  $('array-journal-eissn').textContent=journal?.eissn || '—';
  $('array-journal-subject').textContent=journal?.group || journal?.logicalGroupName || '—';
  $('array-journal-labels').textContent=journal?.labels?.join('; ') || '—';
  $('kept-view').dataset.status=status;
  if(arrayShown()){
    $('mode-label').textContent=`ARRAY / ${status.toUpperCase()}`;
    if(ui.selected){
      if(!ui.reader || ui.bodyPaper!==ui.selected)openReader(ui.selected);
    }else closeReader();
  }
  $('kept-reader').hidden=!ui.reader;
  $('kept-reading-tools').hidden=!ui.reader || status!=='candidates';
  $('kept-empty').hidden=Boolean(ui.selected);
  $('kept-empty').textContent=ui.missingLinkPaper?'该 Paper 不在当前 Kept 中，请从左栏选择其他论文。':status==='kept'
    ? '尚无保留文献。审阅时点击 Keep，论文会出现在这里。':'当前没有待审阅文献。可选择 Run 检索新文献。';
  renderRecord();refreshActions();
}
function saveScroll() {
  ui.indexScroll=$('array-index').scrollTop;ui.indexLeft=$('array-index').scrollLeft;
  if(ui.reader)ui.bodyScroll=$('paper-detail').scrollTop;
}
function selectIndex(id) {
  if(switchBusy())return false;
  const choices=status==='candidates'?groups().map(g=>g.id):orderedEntries().map(e=>e.paper.id);
  if(!choices.includes(id))return false;
  saveScroll();
  if(status==='candidates'){
    if(ui.filter!==id){ui.filter=id;ui.selected=null;}
  }else ui.selected=id;
  ui.missingLinkPaper=false;render();return true;
}
function moveIndex(delta) {
  if(switchBusy() || !arrayShown())return false;
  const rows=[...$('array-index').children];
  if(!rows.length)return false;
  const current=rows.findIndex(row=>row.getAttribute('aria-current')==='true'),next=current+delta;
  const position=(next+rows.length)%rows.length;
  if(!selectIndex(rows[position].dataset.indexId))return false;
  const row=$('array-index').children[position];
  row.focus({preventScroll:true});row.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});
  saveScroll();return true;
}
for(const source of ['candidates','kept'])workspaceSearch.register(source,{
  label:source==='kept'?'SEARCH KEPT PAPERS':'SEARCH CANDIDATES JOURNALS',
  emptyMessage:source==='kept'?'没有匹配的论文':'没有匹配的期刊',
  disabled:switchBusy,
  items:()=>!data?[]:source==='kept'
    ? allEntries().map(entry=>({id:entry.paper.id,name:entry.paper.title,detail:entry.journal.name}))
    : groups(bridge.candidates()).map(group=>({id:group.id,name:group.journal.name,detail:`${group.entries.length} CANDIDATES PAPERS`})),
  select:item=>{if(selectIndex(item.id))$('view-paper-title').focus({preventScroll:true});},
});
function openReader(id) {
  if(!arrayShown())return false;
  const wasReading=ui.reader,previous=ui.bodyPaper;
  // The shared renderer publishes Enrich state synchronously while mounting.
  ui.reader=true;ui.bodyPaper=id;
  if(!bridge.openReader(orderedEntries(),id,status,ui.filter)){
    ui.reader=wasReading;ui.bodyPaper=previous;readerRefreshPending=true;return false;
  }
  readerRefreshPending=false;
  ui.selected=id;ui.missingLinkPaper=false;
  $('kept-reader').hidden=false;
  $('paper-detail').scrollTop=previous===id?ui.bodyScroll:0;
  return true;
}
function closeReader() {
  if(bridge.busy())return false;
  saveScroll();
  if(ui.reader && !bridge.closeReader())return false;
  readerRefreshPending=false;
  ui.reader=false;$('kept-reader').hidden=true;return true;
}
function setLayout(layout) {
  if(window.workspaceNavigation.current()!=='workspace' || switchBusy() || !['archive','array'].includes(layout))return false;
  if($('selected-view').dataset.workspaceLayout===layout)return true;
  if(!closeReader() || !bridge.setLayout(layout))return false;
  render();refreshActions();return true;
}
function setStatus(next) {
  if(!arrayShown() || switchBusy() || !Object.hasOwn(states,next))return false;
  if(next===status)return true;
  if(!closeReader())return false;
  status=next;ui=states[status];render();return true;
}
// Recovery selects its existing business context before opening the modal.
function openKept() {
  if(!window.workspaceNavigation.go('workspace',{workflowRecovery:true}))return false;
  if(!closeReader() || !bridge.setLayout('array'))return false;
  status='kept';ui=states.kept;render();return true;
}
window.workspaceArray={
  workflowBusy,search:()=>status,readerEntries:orderedEntries,
  leave(){closeReader();bridge.suspend();},
  enter(){render();$('array-index').focus({preventScroll:true});},
};
function publishResults(state) {
  if(!state.import_started && !state.batch){lastRun=null;renderRecord();return;}
  const batch=state.batch;
  const titles=new Map([...(active?.queue || []),...allEntries()].map(e=>[e.paper.id,e.paper.title]));
  const results=(batch?.results || []).map(result=>({...result,title:titles.get(result.paper_id) || data.titles[result.paper_id] || result.paper_id}));
  lastRun={total:batch?.total || active?.queue.length || results.length,results,message:state.message,workflow_id:state.workflow_id};
  renderRecord();
}
function identity(state) {return {workflow_id:state.workflow_id,generation:state.generation};}
function closeRun(run) {
  if(active!==run)return;
  run.player.stop();active=null;dialog.close();render();$('array-index').focus({preventScroll:true});
  if(workflow?.navigation && !workflow.active)void acknowledgeWorkflow().catch(error=>uiNext.notice(error.message));
}
async function acknowledgeWorkflow() {
  if(acknowledging || !workflow?.navigation || workflow.active)return;
  const state=workflow;
  acknowledging=true;refreshActions();
  try {
    await uiNext.request('/api/kept-workflow/acknowledge',identity(state));
    if(workflow?.workflow_id===state.workflow_id && workflow.generation===state.generation)workflow={...workflow,navigation:null};
  }finally{acknowledging=false;refreshActions();}
}
function terminal(run) {
  if(active!==run || run.ending)return;
  run.ending=true;run.gate=null;$('kept-flow-actions').hidden=true;
  if(reduced.matches){closeRun(run);return;}
  // Continue a skipped WELCOME from its current frame rather than replaying it.
  void run.player.play('welcome',run.scanSkipped?run.player.liveTime:0);
}
function onClipEnd(run,clip) {
  if(active!==run)return;
  if(run.ending){if(clip==='welcome')closeRun(run);return;}
  if(clip==='access')run.accessDone=true;
  if(clip==='identity')run.identityDone=true;
  if(clip==='scan' && !run.scanSkipped)void run.player.play('scan-loop');
  reconcile(run);
}
function displayGate(run,state) {
  const preparation=state.preparation;
  const manual=new Map((preparation?.manual_services || []).map(service=>[service.id,service]));
  const messages=[state.waiting_for_login?'请在顶栏 BROWSER 工作区完成机构登录。':state.message];
  if(state.phase==='transition')messages.push(`${Math.max(0,state.transition_deadline-Date.now()/1000).toFixed(1)} s`);
  for(const result of preparation?.results || []) {
    const service=preparation.services.find(s=>s.id===result.service_id);
    const diagnostic=result.diagnostic;
    const detail=diagnostic?[diagnostic.stage,diagnostic.step,diagnostic.code,
      Number.isInteger(diagnostic.status)?`HTTP ${diagnostic.status}`:null,diagnostic.net_error].filter(Boolean).join(' / '):'';
    messages.push(`${service?.name || result.service_id}: ${result.outcome} · ${preparationReason(result.reason) || result.reason}${detail?` · ${detail}`:''}`);
    if(service && result.outcome!=='Opened')manual.set(service.id,service);
  }
  $('kept-gate-message').textContent=messages.filter(Boolean).join('\n');
  $('kept-manual-services').replaceChildren(...[...manual.values()].map(service=>{
    const link=document.createElement(service.access_url?'a':'span');link.textContent=service.name+(service.access_url?' ↗':' · 未配置访问链接');
    if(service.access_url){link.href=service.access_url;link.target='_blank';link.rel='noopener noreferrer';}return link;
  }));
  $('kept-flow-gate').hidden=state.phase==='importing';
  $('kept-continue').hidden=!state.can_continue;$('kept-continue').disabled=submitting;
  $('kept-leave').disabled=submitting || !state.can_cancel;
}
function reconcile(run) {
  if(active!==run || run.ending)return;
  const state=run.state;
  displayGate(run,state);
  if(!state.active){terminal(run);return;}
  if(state.phase==='stopping'){closeRun(run);return;}
  if(run.scanSkipped)return;
  const manual=state.preparation?.manual_services?.length;
  if(!run.accessDone)return;
  // Ordinary explicit continuation holds ACCESS; Manual links hold PROCESSING.
  if(!manual && !run.continued && (!state.settings.auto_import_after_preparation || state.waiting_for_login) && !state.import_started)return;
  if(!run.identityDone){if(run.player.clip!=='identity')void run.player.play('identity');return;}
  if(state.phase==='importing') {
    if(!['scan','scan-loop'].includes(run.player.clip))void run.player.play('scan',state.mode==='import_only'?.32:0);
    $('kept-skip-slot').hidden=false;
  } else if(run.player.clip!=='processing')void run.player.play('processing');
}
function openWorkflow(state,restored=false) {
  if(active)return;
  const run=active={state,queue:[...allEntries()],accessDone:restored || state.mode==='import_only',
    identityDone:restored || state.mode==='import_only',continued:false,scanSkipped:false,ending:false};
  run.player=new KeptPlayer($('kept-film'),metadata,state.settings.display_name || 'LOCAL RESEARCHER',reduced.matches,clip=>onClipEnd(run,clip));
  $('kept-flow-actions').hidden=false;$('kept-flow-gate').hidden=true;$('kept-skip-slot').hidden=true;
  $('kept-skip').hidden=false;$('kept-skip-status').hidden=true;dialog.show();refreshActions();
  if(restored && state.phase==='waiting_for_user' && !state.preparation?.manual_services?.length && !state.import_started) {
    run.player.clip='access';run.player.draw(shots.access.duration);
  }
  if(run.accessDone)reconcile(run);else void run.player.play('access');
}
async function acceptState(state,{restored=false,open=false,epoch=workspaceEpoch}={}) {
  if(epoch!==workspaceEpoch)return;
  workflow=state;publishResults(state);
  if(open && state.active && state.phase!=='stopping')openWorkflow(state,restored);
  if(active && active.state.workflow_id===state.workflow_id){active.state=state;reconcile(active);}
  const completed=(state.batch?.results || []).filter(r=>r.outcome==='exported').map(r=>r.paper_id);
  const previous=new Set(bridge.papers().map(e=>e.paper.id));
  bridge.exported(completed);
  if(completed.some(id=>previous.has(id)) || !state.active) {
    await window.uiWorkspace.refresh();if(epoch!==workspaceEpoch)return;data=bridge.data();render();
  }
  if(state.navigation && !active && !state.active) {
    await acknowledgeWorkflow();
  }
  refreshActions();
}
async function pollWorkflow() {
  clearTimeout(pollTimer);
  const epoch=workspaceEpoch;
  try{await acceptState(await uiNext.request('/api/kept-workflow/state'),{epoch});}
  catch(error){if(epoch===workspaceEpoch)uiNext.notice(`流程状态读取失败：${error.message}`);}
  if(epoch===workspaceEpoch && (workflow?.active || workflow?.navigation))pollTimer=setTimeout(()=>void pollWorkflow(),1000);
}
async function start(mode) {
  if(status!=='kept' || !arrayShown() || recovering || active || workflowBusy() || bridge.busy() || !allEntries().length)return;
  if(!closeReader())return;
  submitting=true;refreshActions();uiNext.notice('');
  try {
    // Always obtain the current target-bound one-use token before an explicit start.
    await window.uiWorkspace.refresh();data=bridge.data();
    const state=await uiNext.request('/api/kept-workflow/start',{mode,import_token:uiNext.data.import_token});
    await acceptState(state,{open:true});
    if(!state.active)uiNext.notice(state.message);
    void pollWorkflow();
  }catch(error){uiNext.notice(error.message);if(error.state?.workflow_id){await acceptState(error.state);void pollWorkflow();}}
  finally{submitting=false;refreshActions();if(active)displayGate(active,active.state);}
}
async function continueImport() {
  const run=active;if(!run || submitting || !run.state.can_continue)return;
  submitting=true;displayGate(run,run.state);
  try {
    const state=await uiNext.request('/api/kept-workflow/continue',identity(run.state));
    run.continued=true;await acceptState(state);void pollWorkflow();
  }catch(error){uiNext.notice(error.message);if(error.state?.workflow_id)await acceptState(error.state);}
  finally{submitting=false;if(active)displayGate(active,active.state);}
}
function skipScan() {
  const run=active;if(!run || run.scanSkipped || run.state.phase!=='importing')return;
  run.scanSkipped=true;$('kept-skip').hidden=true;$('kept-skip-status').hidden=false;$('kept-skip-status').textContent='等待导入完成…';
  void run.player.play('welcome',0,shots.welcome.holdAt);
}
async function leaveWorkflow() {
  const run=active;if(!run || submitting)return;
  if(run.ending){closeRun(run);return;}
  if(!run.state.can_cancel)return;
  const state=run.state;closeRun(run);submitting=true;refreshActions();
  try {await acceptState(await uiNext.request('/api/kept-workflow/cancel',identity(state)));void pollWorkflow();}
  catch(error){uiNext.notice(`停止请求未确认：${error.message}`);await restoreWorkflow();}
  finally{submitting=false;refreshActions();}
}
async function restoreWorkflow() {
  const epoch=workspaceEpoch;
  try {
    const state=await uiNext.request('/api/kept-workflow/state');if(epoch!==workspaceEpoch)return false;workflow=state;
    const restored=state.active && !$('run-view').open && openKept();
    await acceptState(state,{restored:true,open:Boolean(restored),epoch});
    if(state.active || state.navigation)void pollWorkflow();
    return state.active;
  }catch(error){if(epoch===workspaceEpoch)uiNext.notice(error.message);}
}
async function initialize() {
  data=bridge.data();metadata=await uiNext.request(new URL('assets/kept/clips.json',document.baseURI));
  await sceneReady();render();const restored=await restoreWorkflow();recovering=false;refreshActions();
  if(restored)return;
  const initial=window.uiNextInitialLink;
  if(initial?.view==='kept'){
    const found=!initial.paper || allEntries().some(entry=>entry.paper.id===initial.paper);
    openKept();
    if(!found){ui.missingLinkPaper=true;ui.selected=null;render();}
    if(initial.paper && found && !dialog.open && arrayShown()){ui.selected=initial.paper;render();}
    if(!found)uiNext.notice('该 Paper 不在当前 Kept 中，可能已移出保留列表。');
  }else if(initial?.view==='inbox' && initial.paper){
    if(window.workspaceNavigation.go('workspace') && !bridge.openArchivePaper(initial.paper))uiNext.notice('该 Paper 不在当前 Inbox 中，可能已移出待审阅列表。');
  }
}
if(bridge.available())void initialize();else window.addEventListener('inbox-ready',()=>void initialize(),{once:true});
$('kept-start').addEventListener('click',()=>void start('full'));$('kept-import-only').addEventListener('click',()=>void start('import_only'));
$('kept-continue').addEventListener('click',()=>void continueImport());$('kept-leave').addEventListener('click',()=>void leaveWorkflow());
$('kept-skip').addEventListener('click',skipScan);
window.addEventListener('enrich-state',()=>{if(arrayShown() && !bridge.busy() && readerRefreshPending)render();else refreshActions();});
window.addEventListener('workspace-data-changed',()=>{data=bridge.data();if(data && arrayShown()){saveScroll();render();}});
window.addEventListener('workspace-reset',()=>{
  workspaceEpoch++;clearTimeout(pollTimer);
  active?.player.stop();active=null;workflow=null;lastRun=null;readerRefreshPending=false;
  dialog.close();bridge.suspend();
  data=bridge.data();
  for(const value of Object.values(states))Object.assign(value,{filter:null,selected:null,reader:false,
    indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false});
  $('kept-reader').hidden=true;$('array-index').replaceChildren();renderRecord();
});
window.addEventListener('array-reader-empty',()=>{ui.reader=false;ui.selected=null;ui.bodyPaper=null;ui.bodyScroll=0;$('kept-reader').hidden=true;});
window.addEventListener('array-paper-selected',event=>{ui.selected=event.detail;ui.bodyPaper=event.detail;ui.bodyScroll=0;});
for(const layout of ['archive','array'])$('workspace-'+layout).addEventListener('click',()=>setLayout(layout));
for(const next of ['candidates','kept'])$('array-'+next).addEventListener('click',()=>setStatus(next));
window.addEventListener('workspace-navigation-state',()=>{
  const busy=switchBusy();
  for(const id of ['workspace-archive','workspace-array','array-candidates','array-kept'])$(id).disabled=busy;
});
window.addEventListener('resize',()=>active?.player.resize());
reduced.addEventListener('change',event=>active?.player.setReduced(event.matches));
window.addEventListener('pagehide',()=>{clearTimeout(pollTimer);active?.player.stop();});
dialog.addEventListener('cancel',event=>{event.preventDefault();void leaveWorkflow();});
$('run-view').addEventListener('close',()=>void restoreWorkflow());
document.addEventListener('visibilitychange',()=>{if(!document.hidden){active?.player.resume();if(workflow?.active)void pollWorkflow();}});

document.addEventListener('keydown',event=>{
  if(event.defaultPrevented || !arrayShown() || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key) ||
      event.altKey || event.metaKey || event.ctrlKey || event.shiftKey || switchBusy() || document.querySelector('dialog[open]') ||
      event.target.isContentEditable || event.target.closest('input,textarea,select,[contenteditable]'))return;
  if(['ArrowLeft','ArrowRight'].includes(event.key)){
    if(status!=='candidates' || !ui.reader)return;
    const button=$(event.key==='ArrowLeft'?'previous-paper':'next-paper');
    if(button.disabled)return;
    button.click();event.preventDefault();
  }else if(moveIndex(event.key==='ArrowUp'?-1:1))event.preventDefault();
});
