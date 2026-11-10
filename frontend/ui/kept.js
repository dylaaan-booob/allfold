const $=id=>document.getElementById(id),bridge=window.inboxKept;
const exportButton=document.createElement('button');
exportButton.type='button';exportButton.className='s-button';exportButton.textContent='导出本次诊断';exportButton.hidden=true;
$('array-import-profile').append(exportButton);
exportButton.addEventListener('click',async()=>{
  if(!workflow?.workflow_id || exportButton.disabled)return;
  exportButton.disabled=true;
  try {await window.allfoldHistory.exportTask(workflow.workflow_id);uiNext.notice('诊断包已在本地生成，未上传。');}
  catch(error){uiNext.notice(error.message);}
  finally {exportButton.disabled=false;}
});
const dialog=$('kept-confirm');
const states=Object.fromEntries(['candidates','kept'].map(status=>[status,{filter:null,selected:null,reader:false,indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false}]));
let status='candidates',ui=states.candidates;
let data,workflow=null,pollTimer=null,submitting=false,acknowledging=false,recovering=true,readerRefreshPending=false;
let workspaceEpoch=0,stateRead=0,taskTitles=new Map();
let queueData=null,serviceFilter='all',queueEpoch=0,confirmation=null;
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
const navigationBusy=()=>submitting || acknowledging;
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
    return (b.paper.first_public_at||b.paper.publication_date||'').localeCompare(a.paper.first_public_at||a.paper.publication_date||'') ||
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
  $('kept-start').disabled=recovering || workflowBusy() || window.uiRun?.active() ||
    (window.allfoldZoteroPreference && !window.allfoldZoteroPreference.value) || !selected?.eligible || queueData?.qualification_pending ||
    ['unassigned','ambiguous'].includes(serviceFilter) || dialog.open;
  $('kept-leave').hidden=!workflow?.active;$('kept-leave').disabled=submitting || !workflow?.can_cancel;
  $('kept-task-page').hidden=!workflow?.active;
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
const settledResults=batch=>[...new Map((batch?.results || []).map(result=>[result.paper_id,result])).values()];
function renderRecord() {
  const batch=workflow?.batch,results=settledResults(batch);
  exportButton.hidden=!workflow?.workflow_id;
  $('kept-record-count').textContent=batch?`${results.filter(result=>result.parent_outcome==='confirmed').length} / ${batch.total}`:'—';
  $('kept-record-summary').textContent=workflow?.message || '本次尚未导入。';
  const expanded=new Set([...$('kept-record-items').querySelectorAll('details[open]')].map(node=>node.dataset.paperId));
  $('kept-record-items').replaceChildren(...results.map(result=>{
    const item=document.createElement('li'),title=document.createElement('strong'),reason=document.createElement('small');
    item.dataset.outcome=result.outcome;title.textContent=taskTitles.get(result.paper_id) || data?.titles?.[result.paper_id] || result.paper_id;
    reason.textContent=result.outcome==='skipped'?result.reason:importIndicators(result);
    const details=document.createElement('details'),summary=document.createElement('summary'),raw=document.createElement('p');
    details.className='import-result-details';details.dataset.paperId=result.paper_id;details.open=expanded.has(result.paper_id);
    summary.textContent='详情';raw.textContent=importDetails(result);
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
  const journal=journals.find(group=>group.id===ui.filter)?.journal;
  $('array-journal-name').textContent=journal?.name || '尚无待审阅来源';
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
  refreshActions();layoutHost.sync();
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
function openPaper(id,{readKept=false}={}) {
  if(switchBusy())return false;
  const candidate=bridge.candidates().find(entry=>entry.paper.id===id);
  const entry=candidate || allEntries().find(entry=>entry.paper.id===id);
  if(entry && !candidate && !readKept){serviceFilter='all';return openKept();}
  if(!entry || !window.workspaceNavigation.go('workspace') || !setLayout('array'))return false;
  if(!closeReader())return false;
  layoutHost.closeFlyout({restoreFocus:false});
  status=candidate?'candidates':'kept';ui=states[status];
  ui.filter=candidate?key(entry):null;ui.selected=id;ui.missingLinkPaper=false;
  render();if(readKept)$('view-paper-title').focus({preventScroll:true});return true;
}
// Recovery selects its existing business context before opening the modal.
function openKept() {
  if(!window.workspaceNavigation.go('kept',{workflowRecovery:true}))return false;
  void refreshQueue();return true;
}
window.workspaceArray={
  workflowBusy,navigationBusy,openPaper,readerEntries:orderedEntries,
  leave(){closeReader();bridge.suspend();layoutHost.closeFlyout({restoreFocus:false});},
  enter(){queueArchivePreference();render();$('array-content').focus({preventScroll:true});},
};
function renderQueue() {
  renderProgress();
  const services=queueData?.services || [],selected=services.find(service=>service.id===serviceFilter);
  $('kept-scope-status').textContent=`${selected?.name || 'All Services'} · Kept ${selected?.kept ?? 0} · Eligible ${selected?.eligible ?? 0}`+
    (queueData?.qualification_pending?' · 正在确认导入计划':'')+
    (['unassigned','ambiguous'].includes(serviceFilter)?' · 此分组不能单独执行':'');
  const list=$('kept-service-list'),focused=list.contains(document.activeElement);
  list.replaceChildren(...services.map(service=>{
    const button=document.createElement('button');button.type='button';button.className='kept-service-row';
    button.dataset.serviceId=service.id;button.setAttribute('aria-current',String(service.id===serviceFilter));
    button.textContent=`${service.name} · ${service.kept} / ${service.eligible}`;
    button.addEventListener('click',()=>{
      if(submitting || dialog.open)return;
      serviceFilter=service.id;queueLayout.closeFlyout();renderQueue();refreshActions();void refreshQueue();
    });
    return button;
  }));
  if(focused)[...list.children].find(button=>button.dataset.serviceId===serviceFilter)?.focus({preventScroll:true});
  queueLayout.sync();
}
function queueURL(serviceId) {
  return '/api/kept-workflow/queue'+(serviceId?`?service_id=${encodeURIComponent(serviceId)}`:'');
}
async function refreshQueue() {
  const read=++queueEpoch,serviceId=['all','unassigned','ambiguous'].includes(serviceFilter)?null:serviceFilter;
  try {
    const next=await uiNext.request(queueURL(serviceId));
    if(read!==queueEpoch)return;
    queueData=next;
    if(!queueData.services.some(service=>service.id===serviceFilter))serviceFilter='all';
    renderQueue();refreshActions();
  }catch(error){if(read===queueEpoch)uiNext.notice(`导入计划读取失败：${error.message}`);}
}
window.uiKept={open:openKept,refresh:refreshQueue};
window.workspaceNavigation.register('kept',{
  canNavigate:()=>!navigationBusy(),canEnter:()=>Boolean(data) && !bridge.busy(),
  enter(){void refreshQueue();void pollWorkflow();queueLayout.sync();window.dispatchEvent(new Event('kept-settings-mount'));$('kept-main').focus({preventScroll:true});},
  leave(){queueLayout.closeFlyout({restoreFocus:false});},
});
window.addEventListener('kept-open-sidebar',event=>queueLayout.openSidebar(event.detail?.view || 'workflow'));

const identity=state=>({workflow_id:state.workflow_id,generation:state.generation});
function renderProgress() {
  const state=workflow;
  if(!state)return;
  const batch=state.batch,results=settledResults(batch),planned=batch?.total ?? state.planned_total ?? 0;
  const confirmed=results.filter(result=>result.parent_outcome==='confirmed').length,skipped=results.filter(result=>result.outcome==='skipped').length;
  const phase=({importing:'Importing',stopping:'正在停止',completed:'Import 完成',interrupted:'Import 已停止'})[state.phase] || '';
  const scope=queueData?.services?.find(service=>service.id===state.service_id)?.name || state.service_id || 'All Services';
  const progress=$('kept-progress');progress.hidden=!state.workflow_id;
  progress.textContent=[phase,scope,`已处理 ${results.length} / ${planned}`,`已确认 ${confirmed}`,`已跳过 ${skipped}`,
    state.active?`执行中 ${batch?.active_paper_ids?.length || 0}`:state.message].filter(Boolean).join(' · ');
}
async function acceptState(state,epoch) {
  if(epoch!==workspaceEpoch)return;
  const previous=workflow;
  if(state.workflow_id && previous?.workflow_id!==state.workflow_id)
    taskTitles=new Map(allEntries().map(entry=>[entry.paper.id,entry.paper.title]));
  workflow=state;
  const results=settledResults(state.batch);
  renderProgress();
  renderRecord();refreshActions();
  const exported=results.filter(result=>result.outcome==='exported').map(result=>result.paper_id),existing=new Set(allEntries().map(entry=>entry.paper.id));
  if(exported.some(id=>existing.has(id)) || (previous?.active && !state.active)){
    bridge.exported(exported);await window.uiWorkspace.refresh();
    if(epoch!==workspaceEpoch)return;
    data=bridge.data();render();
    if(window.workspaceNavigation.current()==='kept')void refreshQueue();
  }
  if(state.navigation && !state.active && !acknowledging){
    acknowledging=true;refreshActions();
    try {
      await uiNext.request('/api/kept-workflow/acknowledge',identity(state));
      if(workflow===state)workflow={...state,navigation:null};
    }finally{acknowledging=false;refreshActions();}
  }
}
function schedulePoll() {
  clearTimeout(pollTimer);
  if(workflow?.active || workflow?.navigation)pollTimer=setTimeout(()=>void pollWorkflow(),1000);
}
async function pollWorkflow() {
  if(submitting || acknowledging)return;
  const read=++stateRead,epoch=workspaceEpoch;
  clearTimeout(pollTimer);
  try {
    const state=await uiNext.request('/api/kept-workflow/state');
    if(read===stateRead)await acceptState(state,epoch);
  }catch(error){if(epoch===workspaceEpoch && read===stateRead)uiNext.notice(`导入状态读取失败：${error.message}`);}
  finally{if(epoch===workspaceEpoch && read===stateRead)schedulePoll();}
}
async function submit(action,body) {
  const epoch=workspaceEpoch;
  try {
    await acceptState(await uiNext.request('/api/kept-workflow/'+action,body),epoch);
  }catch(error){
    uiNext.notice(error.message);
    if(error.state?.workflow_id)await acceptState(error.state,epoch);
    if(window.workspaceNavigation.current()==='kept')void refreshQueue();
    // A request can be accepted even when its response is lost. Read state rather than replaying.
    submitting=false;void pollWorkflow();
  }
}
async function prepareImport() {
  if(window.workspaceNavigation.current()!=='kept' || $('kept-start').disabled || !closeReader())return;
  const serviceId=serviceFilter==='all'?null:serviceFilter,epoch=workspaceEpoch;
  submitting=true;++stateRead;clearTimeout(pollTimer);refreshActions();uiNext.notice('');
  try {
    if(window.allfoldAutosave && !await window.allfoldAutosave.flush()){
      uiNext.notice('配置尚未保存，请处理保存状态后重试。');return;
    }
    // Pin the current scope, target and one-use plan token before confirmation.
    const queue=await uiNext.request(queueURL(serviceId));
    if(epoch!==workspaceEpoch)return;
    if(queue.qualification_pending){uiNext.notice('导入计划尚未确认，请稍后重试。');return;}
    const missing=queue.unprepared_services || [];
    const body={service_id:serviceId,import_token:queue.import_token,skip_unprepared:missing.map(service=>service.id)};
    if(missing.length){
      confirmation=body;
      $('kept-confirm-services').replaceChildren(...missing.map(service=>{
        const li=document.createElement('li');li.textContent=service.name;return li;
      }));
      dialog.showModal();
    }else await submit('start',body);
  }catch(error){uiNext.notice(error.message);}
  finally{submitting=false;refreshActions();schedulePoll();}
}
async function confirmImport() {
  const body=confirmation;if(!body || submitting)return;
  submitting=true;++stateRead;dialog.close();refreshActions();
  try {await submit('start',body);}
  finally{submitting=false;refreshActions();schedulePoll();}
}
async function cancelImport() {
  const state=workflow;if(submitting || !state?.can_cancel)return;
  submitting=true;++stateRead;clearTimeout(pollTimer);refreshActions();
  try {await submit('cancel',identity(state));}
  finally{submitting=false;refreshActions();schedulePoll();}
}
async function initialize() {
  data=bridge.data();render();void refreshQueue();await pollWorkflow();recovering=false;render();
  if(workflow?.active){openKept();return;}
  const initial=window.uiNextInitialLink;
  if(initial?.view==='kept'){
    if(initial.paper && allEntries().some(entry=>entry.paper.id===initial.paper))openPaper(initial.paper,{readKept:true});
    else {openKept();if(initial.paper)uiNext.notice('该 Paper 不在当前 Kept 中，可能已移出保留列表。');}
  }else if(initial?.view==='inbox' && initial.paper){
    if(window.workspaceNavigation.go('workspace') && !bridge.openArchivePaper(initial.paper))uiNext.notice('该 Paper 不在当前 Inbox 中，可能已移出待审阅列表。');
  }
}
if(bridge.available())void initialize();else window.addEventListener('inbox-ready',()=>void initialize(),{once:true});
$('kept-start').addEventListener('click',prepareImport);
$('kept-continue').addEventListener('click',confirmImport);
$('kept-confirm-close').addEventListener('click',()=>dialog.close());
$('kept-confirm-login').addEventListener('click',()=>{dialog.close();window.workspaceNavigation.go('login');});
dialog.addEventListener('close',()=>{confirmation=null;refreshActions();});
$('kept-leave').addEventListener('click',cancelImport);
$('kept-task-page').addEventListener('click',()=>{
  if(workflow?.workflow_id)void window.allfoldWorkbench.showTaskPage({workflowId:workflow.workflow_id,taskId:workflow.batch?.task_id});
});
window.addEventListener('enrich-state',()=>{if(arrayShown() && !bridge.busy() && readerRefreshPending)render();else refreshActions();});
window.addEventListener('zotero-target-changed',refreshActions);
for(const event of ['login-state-changed','settings-saved'])
  window.addEventListener(event,()=>{if(window.workspaceNavigation.current()==='kept')void refreshQueue();});
window.addEventListener('workspace-data-changed',()=>{data=bridge.data();if(data && arrayShown()){saveScroll();render();}if(window.workspaceNavigation.current()==='kept')void refreshQueue();});
window.addEventListener('workspace-reset',()=>{
  workspaceEpoch++;queueEpoch++;stateRead++;clearTimeout(pollTimer);
  workflow=null;queueData=null;readerRefreshPending=false;taskTitles.clear();$('kept-progress').hidden=true;
  dialog.close();bridge.suspend();
  data=bridge.data();
  for(const value of Object.values(states))Object.assign(value,{filter:null,selected:null,reader:false,
    indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false});
  $('kept-reader').hidden=true;$('array-index').replaceChildren();renderRecord();renderQueue();refreshActions();
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
window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
document.addEventListener('visibilitychange',()=>{if(!document.hidden && workflow?.active)void pollWorkflow();});

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
