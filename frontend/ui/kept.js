import {KeptPlayer} from './kept-player.js';
import {sceneReady,shots} from './kept/scene';
import {preparationReason} from './business-results.js';
const $=id=>document.getElementById(id),bridge=window.inboxKept;
const exportButton=document.createElement('button');
exportButton.type='button';exportButton.className='s-button';exportButton.textContent='导出本次诊断';exportButton.hidden=true;
$('kept-queue-results').append(exportButton);
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
let workspaceEpoch=0,presentationInline=null,taskQueue=[],openingWorkflow=null;
let queueData=null,serviceFilter='all',queueEpoch=0,expandedPaper=null;
const inline=document.createElement('section'),phaseLabel=document.createElement('strong');
inline.id='kept-inline';inline.hidden=true;inline.setAttribute('aria-label','当前 Prepare / Import');
phaseLabel.id='kept-phase';phaseLabel.setAttribute('role','status');
$('kept-workflow-host').prepend(inline);inline.append(phaseLabel);
const taskPageButton=document.createElement('button');
taskPageButton.type='button';taskPageButton.className='s-button';taskPageButton.textContent='查看任务页面';taskPageButton.hidden=true;
taskPageButton.id='kept-task-page';
$('kept-flow-actions').prepend(taskPageButton);
taskPageButton.addEventListener('click',async()=>{
  if(!workflow?.workflow_id)return;
  try {
    if(!await window.allfoldWorkbench?.showTaskPage({workflowId:workflow.workflow_id,
      source:'kept',taskId:workflow.phase==='importing'?workflow.batch?.task_id:workflow.preparation_task_id}))uiNext.notice('当前任务尚无可查看的页面。');
  }catch(error){uiNext.notice(error.message);}
});
function presentInline() {
  inline.hidden=false;inline.append($('kept-flow-actions'));
  $('kept-flow-actions').hidden=false;$('kept-skip-slot').hidden=true;
}
const archiveDisabled=()=>window.allfoldUIPreferences?.archiveDisabled()===true;
let archivePreferenceQueued=false;
function queueArchivePreference() {
  if(archivePreferenceQueued)return;
  archivePreferenceQueued=true;
  void Promise.resolve().then(()=>{
    archivePreferenceQueued=false;
    if(archiveDisabled() && $('selected-view').dataset.workspaceLayout!=='array')setLayout('array');
  });
}
const arrayShown=()=>window.workspaceNavigation.current()==='workspace' && $('selected-view').dataset.workspaceLayout==='array';
const layoutHost=window.allfoldLayout.create({root:$('kept-view'),workspace:'workspace',minContentWidth:window.allfoldLayoutModel.minOperationalSize.array});
const queueLayout=window.allfoldLayout.create({root:$('kept-workspace'),workspace:'kept',minContentWidth:360});
const workflowBusy=()=>submitting || acknowledging || Boolean(workflow?.active || workflow?.navigation);
const navigationBusy=()=>submitting || acknowledging || (!presentationInline && Boolean(workflow?.active || workflow?.navigation));
const switchBusy=()=>recovering || !data || !bridge.available() || bridge.busy() || navigationBusy() || $('run-view').open || dialog.open;
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
  $('workspace-archive').hidden=archiveDisabled();
  $('workspace-archive').disabled=busy || archiveDisabled();
  queueArchivePreference();
  $('workspace-archive').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='archive'));
  $('workspace-array').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='array'));
  $('array-candidates').setAttribute('aria-pressed',String(status==='candidates'));
  $('array-kept').setAttribute('aria-pressed',String(status==='kept'));
  $('array-index-toggle').dataset.flyout=status;
  $('array-status').hidden=$('selected-view').dataset.workspaceLayout!=='array';
  if(!data)return;
  const selected=queueData?.services?.find(service=>service.id===serviceFilter);
  $('kept-start').disabled=$('kept-import-only').disabled=submitting || recovering || workflow?.active || acknowledging ||
    window.uiRun?.active() || (window.allfoldZoteroPreference && !window.allfoldZoteroPreference.value) || !selected?.eligible || ['unassigned','ambiguous'].includes(serviceFilter);
  for(const row of $('array-index').children)row.disabled=busy;
  workspaceSearch.refresh();
}
const observation=value=>value===true?'Yes':value===false?'No':'无法核验';
function importIndicators(result) {
  return `Item ${observation(result.item_exists)} · PDF ${observation(result.pdf_attached)} · Fallback ${observation(result.fallback_used)}`;
}
function importDetails(result) {
  return `Paper: ${result.paper_id}\nService: ${result.service_id || result.service_assignment || 'Unassigned'}\n${result.reason}`+
    (result.diagnostic?'\n'+[result.diagnostic.stage,result.diagnostic.step,result.diagnostic.code].filter(Boolean).join(' / '):'')+
    (result.query_diagnostic?'\n查询：'+result.query_diagnostic.code+(result.query_diagnostic.status?` (HTTP ${result.query_diagnostic.status})`:''):'');
}
function renderRecord() {
  exportButton.hidden=!lastRun?.workflow_id;
  const results=(lastRun?.results || []).filter(result=>serviceFilter==='all' || (result.service_id || result.service_assignment)===serviceFilter),exported=results.filter(r=>r.parent_outcome==='confirmed').length;
  $('kept-record-count').textContent=lastRun?`${exported} / ${lastRun.total}`:'—';
  $('kept-record-summary').textContent=lastRun?.message || '本次尚未导入。';
  $('kept-record-items').replaceChildren(...results.map(result=>{
    const item=document.createElement('li'),title=document.createElement('strong'),reason=document.createElement('small');
    item.dataset.outcome=result.outcome;title.textContent=result.title;title.title=result.title;
    reason.textContent=importIndicators(result);
    const details=document.createElement('details'),summary=document.createElement('summary'),raw=document.createElement('p');
    details.className='import-result-details';summary.textContent='详情';
    raw.textContent=importDetails(result);
    details.append(summary,raw);item.append(title,reason,details);return item;
  }));
  renderQueueResults(results);
}
function renderQueueResults(results) {
  const summary=document.createElement('p');summary.textContent=lastRun?.message || '本次尚未导入。';
  const list=document.createElement('div');
  for(const result of results){
    const details=document.createElement('details'),heading=document.createElement('summary'),body=document.createElement('p');
    heading.textContent=`${result.title} · ${importIndicators(result)}`;
    body.textContent=importDetails(result);
    details.append(heading,body);list.append(details);
  }
  $('kept-queue-results').replaceChildren(summary,exportButton,list);
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
  renderRecord();refreshActions();layoutHost.sync();
}
function saveScroll() {
  ui.indexScroll=$('array-index').scrollTop;ui.indexLeft=$('array-index').scrollLeft;
  if(ui.reader)ui.bodyScroll=$('paper-detail').scrollTop;
}
function selectIndex(id,{closeFlyout=true}={}) {
  if(switchBusy())return false;
  const choices=status==='candidates'?groups().map(g=>g.id):orderedEntries().map(e=>e.paper.id);
  if(!choices.includes(id))return false;
  saveScroll();
  if(status==='candidates'){
    if(ui.filter!==id){ui.filter=id;ui.selected=null;}
  }else ui.selected=id;
  ui.missingLinkPaper=false;render();if(closeFlyout)layoutHost.closeFlyout();return true;
}
function moveIndex(delta) {
  if(switchBusy() || !arrayShown())return false;
  const rows=[...$('array-index').children];
  if(!rows.length)return false;
  const current=rows.findIndex(row=>row.getAttribute('aria-current')==='true'),next=current+delta;
  const position=(next+rows.length)%rows.length;
  if(!selectIndex(rows[position].dataset.indexId,{closeFlyout:false}))return false;
  const row=$('array-index').children[position];
  if(!$('array-flyout').hidden){row.focus({preventScroll:true});row.scrollIntoView({block:'nearest',inline:'nearest',behavior:'instant'});}
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
  if(window.workspaceNavigation.current()!=='workspace' || switchBusy() || !['archive','array'].includes(layout) || (layout==='archive' && archiveDisabled()))return false;
  if($('selected-view').dataset.workspaceLayout===layout)return true;
  if(!closeReader())return false;
  layoutHost.closeFlyout({restoreFocus:false});
  if(!bridge.setLayout(layout))return false;
  render();refreshActions();return true;
}
function setStatus(next) {
  if(next==='kept')return openKept();
  if(!arrayShown() || switchBusy() || !Object.hasOwn(states,next))return false;
  if(next===status)return true;
  if(!closeReader())return false;
  status=next;ui=states[status];layoutHost.closeFlyout({restoreFocus:false});render();return true;
}
function openPaper(id) {
  if(switchBusy())return false;
  const candidate=bridge.candidates().find(entry=>entry.paper.id===id);
  const entry=candidate || allEntries().find(entry=>entry.paper.id===id);
  if(entry && !candidate){expandedPaper=id;serviceFilter='all';return openKept();}
  if(!entry || !window.workspaceNavigation.go('workspace') || !setLayout('array'))return false;
  if(!closeReader())return false;
  layoutHost.closeFlyout({restoreFocus:false});
  status=candidate?'candidates':'kept';ui=states[status];
  ui.filter=candidate?key(entry):null;ui.selected=id;ui.missingLinkPaper=false;
  render();return true;
}
// Recovery selects its existing business context before opening the modal.
function openKept() {
  if(!window.workspaceNavigation.go('kept',{workflowRecovery:true}))return false;
  void refreshQueue();return true;
}
window.workspaceArray={
  workflowBusy,navigationBusy,openPaper,search:()=>status,readerEntries:orderedEntries,
  leave(){closeReader();bridge.suspend();layoutHost.closeFlyout({restoreFocus:false});},
  enter(){queueArchivePreference();render();$('array-content').focus({preventScroll:true});},
};
const scopeIdentity=document.createElement('span'),scopeCounts=document.createElement('span');
scopeIdentity.className='kept-scope-identity';scopeCounts.className='kept-scope-counts';
scopeCounts.tabIndex=0;scopeCounts.setAttribute('role','group');scopeCounts.setAttribute('aria-label','Service 与批次统计');
$('kept-scope-status').replaceChildren(scopeIdentity,scopeCounts);
function renderQueue() {
  const services=queueData?.services || [],selected=services.find(service=>service.id===serviceFilter);
  const batchName=workflow?.service_name || (workflow?.service_id ?
    services.find(service=>service.id===workflow.service_id)?.name || workflow.service_id : 'All Services');
  const batchResults=[...new Map((workflow?.batch?.results || []).map(result=>[result.paper_id,result])).values()],planned=workflow?.batch?.total ?? workflow?.planned_total ?? 0;
  const batchCounts=workflow?.workflow_id?`计划 ${planned} · 已处理 ${batchResults.filter(result=>result.outcome!=='skipped').length}`+
    ` · 父条目确认 ${batchResults.filter(result=>result.parent_outcome==='confirmed').length} · 待处理 ${Math.max(0,planned-batchResults.length)}`+
    (workflow.waiting_for_login?' · 需要人工登录':workflow.can_continue?' · 等待 Continue':''):
    `Kept ${selected?.kept ?? 0} · Eligible ${selected?.eligible ?? 0}`;
  scopeIdentity.textContent=(workflow?.workflow_id?`当前批次：${batchName} · ${workflow.phase} · `:'')+`下一批：${selected?.name || 'All Services'}`;
  scopeIdentity.title=scopeIdentity.textContent;
  scopeCounts.textContent=batchCounts+(['unassigned','ambiguous'].includes(serviceFilter)?' · 请在 Journals 修正 Service 映射；此分组不能单独执行。':'');
  const focused=$('kept-service-list').contains(document.activeElement);
  $('kept-service-list').replaceChildren(...services.map(service=>{
    const button=document.createElement('button');button.type='button';button.className='kept-service-row';
    button.dataset.serviceId=service.id;button.setAttribute('aria-current',String(service.id===serviceFilter));
    button.textContent=`${service.name} · ${service.kept} / ${service.eligible}`;
    button.addEventListener('click',()=>{serviceFilter=service.id;renderQueue();renderRecord();refreshActions();queueLayout.closeFlyout();});
    return button;
  }));
  if(focused)[...$('kept-service-list').children].find(button=>button.dataset.serviceId===serviceFilter)?.focus({preventScroll:true});
  const columns=[['Service','name'],['Kept','kept'],['Eligible','eligible'],['Planned','planned'],
    ['Confirmed parents','confirmed'],['PDF','pdf_attached'],['Fallback','fallback'],['Issues','issues']];
  const table=document.createElement('table'),head=document.createElement('thead'),heading=document.createElement('tr'),body=document.createElement('tbody');
  for(const [label] of columns){const cell=document.createElement('th');cell.textContent=label;cell.setAttribute('scope','col');heading.append(cell);}
  head.append(heading);
  for(const service of services){
    const row=document.createElement('tr');row.setAttribute('aria-current',String(service.id===serviceFilter));
    for(const [,field] of columns){const cell=document.createElement('td');cell.textContent=String(service[field] ?? 0);row.append(cell);}
    body.append(row);
  }
  table.append(head,body);$('kept-statistics').replaceChildren(table);
  const papers=(queueData?.papers || []).filter(paper=>serviceFilter==='all' || (paper.service_id || paper.assignment)===serviceFilter);
  const details=document.createElement('details'),summary=document.createElement('summary');
  details.open=Boolean(expandedPaper);summary.textContent=`Paper identities · ${papers.length}`;details.append(summary);
  for(const paper of papers){
    const item=document.createElement('details'),title=document.createElement('summary'),description=document.createElement('p');
    item.open=paper.paper_id===expandedPaper;title.textContent=paper.title;
    description.textContent=`ID: ${paper.paper_id}\nDOI: ${paper.doi || '—'}\nService: ${paper.service_id || paper.assignment}\n${paper.reason}`;
    item.append(title,description);details.append(item);
  }
  $('kept-paper-identities').replaceChildren(details);
  const service=(data?.services || []).find(service=>service.id===serviceFilter);
  $('kept-service-detail').textContent=service?`${service.name}\n${service.id}\n${service.access_method}\n${service.access_url || '未配置访问链接'}`:
    selected?.name || 'All Services';
  queueLayout.sync();
}
async function refreshQueue() {
  const epoch=++queueEpoch;
  try {
    const saved=await uiNext.request('/api/kept-workflow/queue');
    if(epoch!==queueEpoch)return;
    queueData=saved;
    if(saved.services && !saved.services.some(service=>service.id===serviceFilter))serviceFilter='all';
    renderQueue();renderRecord();refreshActions();
  }catch(error){if(epoch===queueEpoch)uiNext.notice(`Queue 读取失败：${error.message}`);}
}
window.uiKept={open:openKept,refresh:refreshQueue};
window.workspaceNavigation.register('kept',{
  canNavigate:()=>!navigationBusy(),canEnter:()=>Boolean(data) && !bridge.busy(),
  enter(){void refreshQueue();queueLayout.sync();window.dispatchEvent(new Event('kept-settings-mount'));$('kept-main').focus({preventScroll:true});},
  leave(){queueLayout.closeFlyout({restoreFocus:false});window.allfoldWorkbench?.hideKeptBrowser?.();},
});
window.addEventListener('kept-open-sidebar',event=>queueLayout.openSidebar(event.detail?.view || 'access'));
$('kept-browser-open').addEventListener('click',()=>window.allfoldWorkbench?.showKeptBrowser?.({mode:'compact'}));
window.addEventListener('workbench:browser-state',event=>{
  const shown=event.detail?.visible && event.detail.source==='kept';
  $('kept-queue-body').hidden=Boolean(shown);$('kept-browser-host').hidden=!shown;
  $('kept-workspace').dataset.browserVisible=String(Boolean(shown));
});
function publishResults(state) {
  if(!state.import_started && !state.batch){lastRun=null;renderRecord();return;}
  const batch=state.batch;
  const titles=new Map([...taskQueue,...allEntries()].map(e=>[e.paper.id,e.paper.title]));
  const results=[...new Map((batch?.results || []).map(result=>[result.paper_id,result])).values()]
    .map(result=>({...result,title:titles.get(result.paper_id) || data.titles[result.paper_id] || result.paper_id}));
  lastRun={total:batch?.total || taskQueue.length || results.length,results,message:state.message,workflow_id:state.workflow_id};
  renderRecord();
}
function identity(state) {return {workflow_id:state.workflow_id,generation:state.generation};}
function closeRun(run) {
  if(active!==run)return;
  run.player.stop();active=null;dialog.close();render();$('kept-main').focus({preventScroll:true});
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
function displayGate(state) {
  phaseLabel.textContent=({preparing:'Preparation',waiting_for_user:state.waiting_for_login?'等待机构登录':'等待确认',transition:'Transition',importing:'Importing',stopping:'正在停止',completed:'Import 完成',interrupted:'流程已停止 / 失败'})[state.phase] || state.phase;
  taskPageButton.hidden=!state.active;
  $('kept-leave').hidden=!state.active;
  const preparation=state.preparation;
  const manual=new Map((preparation?.manual_services || []).map(service=>[service.id,service]));
  const messages=[state.waiting_for_login?'请查看任务页面，完成机构登录后返回。':state.message];
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
    if(service.access_url){
      link.href=service.access_url;link.target='_blank';link.rel='noopener noreferrer';
      link.addEventListener('click',event=>{
        if(!window.allfoldDesktop || !window.allfoldWorkbench?.openService)return;
        event.preventDefault();
        void window.allfoldWorkbench.openService({serviceId:service.id,workflowId:state.workflow_id,taskId:state.preparation_task_id})
          .catch(error=>uiNext.notice(error.message));
      });
    }return link;
  }));
  $('kept-flow-gate').hidden=!presentationInline && state.phase==='importing';
  $('kept-continue').hidden=!state.can_continue;$('kept-continue').disabled=submitting;
  $('kept-leave').disabled=submitting || !state.can_cancel;
}
function reconcile(run) {
  if(active!==run || run.ending)return;
  const state=run.state;
  displayGate(state);
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
async function openWorkflow(state,restored=false) {
  if(active || openingWorkflow)return;
  const target=openingWorkflow=identity(state),epoch=workspaceEpoch;
  try {
    if(!metadata)metadata=await uiNext.request(new URL('assets/kept/clips.json',document.baseURI));
    await sceneReady();
    if(epoch!==workspaceEpoch || workflow?.workflow_id!==target.workflow_id || workflow?.generation!==target.generation || !workflow.active)return;
    state=workflow;
    mountWorkflow(state,restored);
  }catch(error){
    if(epoch!==workspaceEpoch || workflow?.workflow_id!==target.workflow_id || workflow?.generation!==target.generation)return;
    uiNext.notice(`全屏界面未就绪：${error.message}；请使用当前流程控制。`);
    presentationInline=true;presentInline();displayGate(workflow);
  }finally{if(openingWorkflow===target)openingWorkflow=null;refreshActions();}
}
function mountWorkflow(state,restored) {
  const run=active={state,queue:[...allEntries()],accessDone:restored || state.mode==='import_only',
    identityDone:restored || state.mode==='import_only',continued:false,scanSkipped:false,ending:false};
  run.player=new KeptPlayer($('kept-film'),metadata,state.settings.display_name || 'LOCAL RESEARCHER',reduced.matches,clip=>onClipEnd(run,clip));
  $('kept-flow-actions').hidden=false;$('kept-flow-gate').hidden=true;$('kept-skip-slot').hidden=true;
  inline.hidden=true;dialog.append($('kept-flow-actions'));
  $('kept-skip').hidden=false;$('kept-skip-status').hidden=true;dialog.show();refreshActions();
  if(restored && state.phase==='waiting_for_user' && !state.preparation?.manual_services?.length && !state.import_started) {
    run.player.clip='access';run.player.draw(shots.access.duration);
  }
  if(run.accessDone)reconcile(run);else void run.player.play('access');
}
async function acceptState(state,{restored=false,open=false,epoch=workspaceEpoch}={}) {
  if(epoch!==workspaceEpoch)return;
  const changed=workflow?.workflow_id!==state.workflow_id || workflow?.generation!==state.generation;
  if(state.workflow_id && (changed || presentationInline===null)){
    presentationInline=window.allfoldUIPreferences?.fullscreenDisabled()===true;taskQueue=[...allEntries()];
  }
  workflow=state;publishResults(state);
  renderQueue();
  if(presentationInline && state.workflow_id){presentInline();displayGate(state);}
  if(open && !presentationInline && state.active && state.phase!=='stopping')void openWorkflow(state,restored);
  if(active && active.state.workflow_id===state.workflow_id){active.state=state;reconcile(active);}
  const completed=(state.batch?.results || []).filter(r=>r.outcome==='exported').map(r=>r.paper_id);
  const previous=new Set(bridge.papers().map(e=>e.paper.id));
  bridge.exported(completed);
  if(completed.some(id=>previous.has(id)) || !state.active) {
    await window.uiWorkspace.refresh();if(epoch!==workspaceEpoch)return;data=bridge.data();render();
  }
  if(state.navigation && !state.active) {
    await acknowledgeWorkflow();
  }
  refreshActions();
  if(window.workspaceNavigation.current()==='kept')void refreshQueue();
}
async function pollWorkflow() {
  clearTimeout(pollTimer);
  const epoch=workspaceEpoch;
  try{await acceptState(await uiNext.request('/api/kept-workflow/state'),{epoch});}
  catch(error){if(epoch===workspaceEpoch)uiNext.notice(`流程状态读取失败：${error.message}`);}
  if(epoch===workspaceEpoch && (workflow?.active || workflow?.navigation))pollTimer=setTimeout(()=>void pollWorkflow(),1000);
}
async function start(mode) {
  if(window.workspaceNavigation.current()!=='kept' || recovering || active || window.uiRun?.active() || workflowBusy() || bridge.busy() || ['unassigned','ambiguous'].includes(serviceFilter))return;
  const selectedService=serviceFilter==='all'?null:serviceFilter;
  if(!closeReader())return;
  submitting=true;refreshActions();uiNext.notice('');
  try {
    if(window.allfoldAutosave && !await window.allfoldAutosave.flush()){
      uiNext.notice('配置尚未保存；请处理 Pending / Failed / Conflict 后重试。');return;
    }
    // Always obtain the current target-bound one-use token before an explicit start.
    await window.uiWorkspace.refresh();data=bridge.data();
    const queue=await uiNext.request('/api/kept-workflow/queue'+(selectedService?`?service_id=${encodeURIComponent(selectedService)}`:''));
    const state=await uiNext.request('/api/kept-workflow/start',{mode,service_id:selectedService,import_token:queue.import_token});
    await acceptState(state,{open:true});
    if(!state.active)uiNext.notice(state.message);
    void pollWorkflow();
  }catch(error){uiNext.notice(error.message);if(error.state?.workflow_id){await acceptState(error.state);void pollWorkflow();}}
  finally{submitting=false;refreshActions();if(workflow)displayGate(workflow);}
}
async function continueImport() {
  const state=workflow;if(submitting || acknowledging || !state?.can_continue)return;
  submitting=true;refreshActions();displayGate(state);
  try {
    const next=await uiNext.request('/api/kept-workflow/continue',identity(state));
    if(active && active.state.workflow_id===state.workflow_id)active.continued=true;
    await acceptState(next);void pollWorkflow();
  }catch(error){uiNext.notice(error.message);if(error.state?.workflow_id)await acceptState(error.state);}
  finally{submitting=false;refreshActions();if(workflow)displayGate(workflow);}
}
function skipScan() {
  const run=active;if(!run || run.scanSkipped || run.state.phase!=='importing')return;
  run.scanSkipped=true;$('kept-skip').hidden=true;$('kept-skip-status').hidden=false;$('kept-skip-status').textContent='等待导入完成…';
  void run.player.play('welcome',0,shots.welcome.holdAt);
}
async function leaveWorkflow() {
  const state=workflow;if(submitting || acknowledging || !state?.can_cancel)return;
  submitting=true;refreshActions();displayGate(state);
  try {await acceptState(await uiNext.request('/api/kept-workflow/cancel',identity(state)));void pollWorkflow();}
  catch(error){uiNext.notice(`停止请求未确认：${error.message}`);await restoreWorkflow();}
  finally{submitting=false;refreshActions();if(workflow)displayGate(workflow);}
}
async function restoreWorkflow() {
  const epoch=workspaceEpoch;
  try {
    const state=await uiNext.request('/api/kept-workflow/state');if(epoch!==workspaceEpoch)return false;
    const useInline=presentationInline ?? (window.allfoldUIPreferences?.fullscreenDisabled()===true);
    if(state.active && useInline && recovering && !$('run-view').open && !window.uiRun?.active())openKept();
    const restored=state.active && (useInline || (!$('run-view').open && !window.uiRun?.active() && openKept()));
    await acceptState(state,{restored:true,open:Boolean(restored),epoch});
    if(state.active || state.navigation)void pollWorkflow();
    return state.active;
  }catch(error){if(epoch===workspaceEpoch)uiNext.notice(error.message);}
}
async function initialize() {
  data=bridge.data();render();void refreshQueue();const restored=await restoreWorkflow();recovering=false;render();
  if(restored)return;
  const initial=window.uiNextInitialLink;
  if(initial?.view==='kept'){
    const found=!initial.paper || allEntries().some(entry=>entry.paper.id===initial.paper);
    openKept();
    if(initial.paper && found){expandedPaper=initial.paper;void refreshQueue();}
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
window.addEventListener('zotero-target-changed',refreshActions);
window.addEventListener('workspace-data-changed',()=>{data=bridge.data();if(data && arrayShown()){saveScroll();render();}if(window.workspaceNavigation.current()==='kept')void refreshQueue();});
window.addEventListener('workspace-reset',()=>{
  workspaceEpoch++;clearTimeout(pollTimer);
  active?.player.stop();active=null;workflow=null;lastRun=null;readerRefreshPending=false;presentationInline=null;taskQueue=[];inline.hidden=true;
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
  $('workspace-archive').disabled=busy || archiveDisabled();
  $('workspace-archive').hidden=archiveDisabled();
  queueArchivePreference();
});
window.addEventListener('ui-preferences-changed',event=>{
  if(event.detail?.name==='archiveDisabled')refreshActions();
});
window.addEventListener('resize',()=>active?.player.resize());
reduced.addEventListener('change',event=>active?.player.setReduced(event.matches));
window.addEventListener('pagehide',()=>{clearTimeout(pollTimer);active?.player.stop();});
dialog.addEventListener('cancel',event=>{event.preventDefault();if(active?.ending)closeRun(active);else void leaveWorkflow();});
$('run-view').addEventListener('close',()=>void restoreWorkflow());
document.addEventListener('visibilitychange',()=>{if(!document.hidden){active?.player.resume();if(workflow?.active)void pollWorkflow();}});

document.addEventListener('keydown',event=>{
  if(event.defaultPrevented || $('selected-view').closest('[inert]') || !arrayShown() || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key) ||
      event.altKey || event.metaKey || event.ctrlKey || event.shiftKey || switchBusy() || document.querySelector('dialog[open]') ||
      event.target.isContentEditable || event.target.closest('input,textarea,select,[contenteditable]'))return;
  if(['ArrowLeft','ArrowRight'].includes(event.key)){
    if(status!=='candidates' || !ui.reader)return;
    const button=$(event.key==='ArrowLeft'?'previous-paper':'next-paper');
    if(button.disabled)return;
    button.click();event.preventDefault();
  }else if(moveIndex(event.key==='ArrowUp'?-1:1))event.preventDefault();
});
