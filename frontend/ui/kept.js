const $=id=>document.getElementById(id),bridge=window.inboxKept;
const states=Object.fromEntries(['candidates','downloaded','trash'].map(status=>[status,{filter:null,selected:null,reader:false,indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false}]));
let status='candidates',ui=states.candidates;
let data,readerRefreshPending=false;
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
const workflowBusy=()=>false;
const navigationBusy=()=>false;
const switchBusy=()=>!data || !bridge.available() || bridge.busy() || navigationBusy() || $('run-view').open;
const allEntries=()=>bridge.entries(status);
const visibleEntries=()=>status==='candidates'?bridge.candidates():allEntries();
const key=entry=>entry.journal.key || entry.journal.name;
function groups(entries=visibleEntries(),journals=data?.journals || []) {
  const buckets=new Map(),ranks=new Map(journals.map((j,i)=>[j.key,i]));
  for(const entry of entries) {
    const id=key(entry);
    if(!buckets.has(id)) buckets.set(id,{id,journal:entry.journal,entries:[]});
    buckets.get(id).entries.push(entry);
  }
  return [...buckets.values()].sort((a,b)=>(ranks.get(a.journal.key)??Infinity)-(ranks.get(b.journal.key)??Infinity));
}
function orderedEntries(entries=visibleEntries(),journals=data?.journals || []) {
  return groups(entries,journals).filter(g=>status!=='candidates' || g.id===ui.filter).flatMap(g=>status==='candidates'?g.entries:[...g.entries].sort((a,b)=>{
    return (b.paper.first_public_at||b.paper.publication_date||'').localeCompare(a.paper.first_public_at||a.paper.publication_date||'') ||
      (b.paper.discovered_at||'').localeCompare(a.paper.discovered_at||'') || a.paper.id.localeCompare(b.paper.id);
  }));
}
function refreshActions() {
  const layout=$('workspace-layout'),host=$($('selected-view').dataset.workspaceLayout==='array'?'array-layout-controls':'archive-layout-controls');
  if(layout.parentElement!==host)host.append(layout);
  window.workspaceNavigation.refresh();
  const busy=switchBusy();
  for(const id of ['workspace-archive','workspace-array','array-candidates','array-downloaded','array-trash'])$(id).disabled=busy;
  $('workspace-archive').hidden=archiveDisabled();
  $('workspace-archive').disabled=busy || archiveDisabled();
  queueArchivePreference();
  $('workspace-archive').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='archive'));
  $('workspace-array').setAttribute('aria-pressed',String($('selected-view').dataset.workspaceLayout==='array'));
  $('array-candidates').setAttribute('aria-pressed',String(status==='candidates'));
  for(const kind of ['downloaded','trash'])$('array-'+kind).setAttribute('aria-pressed',String(status===kind));
  $('array-index-toggle').dataset.flyout=status;
  $('array-status').hidden=$('selected-view').dataset.workspaceLayout!=='array';
  if(!data)return;
  for(const row of $('array-index').children)row.disabled=busy;
  workspaceSearch.refresh();
}
function render() {
  if(!data)return;
  const journals=groups();
  if(status==='candidates' && !journals.some(g=>g.id===ui.filter)){
    ui.filter=journals[ui.indexPosition % journals.length]?.id || null;
  }
  const entries=orderedEntries();
  if(!entries.some(e=>e.paper.id===ui.selected)){
    ui.selected=ui.missingLinkPaper?null:(entries[(status!=='candidates'?ui.indexPosition:0) % entries.length]?.paper.id || null);
  }
  const choices=status==='candidates'
    ? journals.map(g=>({id:g.id,name:g.journal.name,count:g.entries.length}))
    : entries.map(entry=>({id:entry.paper.id,name:entry.paper.title || entry.paper.identity_label}));
  const selected=status==='candidates'?ui.filter:ui.selected;
  ui.indexPosition=Math.max(0,choices.findIndex(choice=>choice.id===selected));
  const index=$('array-index'),focused=index.contains(document.activeElement);
  const previous=[...index.children].find(row=>row.getAttribute('aria-current')==='true')?.dataset.indexId;
  const maxCount=Math.max(10,...choices.map(c=>c.count || 0));
  index.setAttribute('aria-label',status==='candidates'?'Candidate Journals':status==='trash'?'Trash Papers':'Downloaded Papers');
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
  $('kept-reading-tools').hidden=!ui.reader;
  $('kept-empty').hidden=Boolean(ui.selected);
  $('kept-empty').textContent=ui.missingLinkPaper?'当前视图中没有该 Paper。':status==='downloaded'?'尚无已关联正文的文献。':status==='trash'?'回收区为空。':'当前没有待审阅文献。可选择 Run 检索新文献。';
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
  // Mount the shared Reader after recording the current selection.
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
  if(!arrayShown() || switchBusy() || !Object.hasOwn(states,next))return false;
  if(next===status)return true;
  if(!closeReader())return false;
  status=next;ui=states[status];layoutHost.closeFlyout({restoreFocus:false});render();return true;
}
function openPaper(id) {
  if(switchBusy())return false;
  const candidate=bridge.candidates().find(entry=>entry.paper.id===id);
  const downloaded=bridge.entries('downloaded').find(entry=>entry.paper.id===id);
  const entry=candidate || downloaded || bridge.entries('trash').find(entry=>entry.paper.id===id);
  if(!entry || !window.workspaceNavigation.go('workspace') || !setLayout('array'))return false;
  if(!closeReader())return false;
  layoutHost.closeFlyout({restoreFocus:false});
  status=candidate?'candidates':downloaded?'downloaded':'trash';ui=states[status];
  ui.filter=candidate?key(entry):null;ui.selected=id;ui.missingLinkPaper=false;
  render();$('view-paper-title').focus({preventScroll:true});return true;
}
window.workspaceArray={
  workflowBusy,navigationBusy,openPaper,readerEntries:orderedEntries,
  leave(){closeReader();bridge.suspend();layoutHost.closeFlyout({restoreFocus:false});},
  enter(){queueArchivePreference();render();$('array-content').focus({preventScroll:true});},
};
window.addEventListener('workspace-data-changed',()=>{data=bridge.data();if(data && arrayShown()){saveScroll();render();}});
window.addEventListener('workspace-reset',()=>{
  data=null;readerRefreshPending=false;
  for(const value of Object.values(states))Object.assign(value,{filter:null,selected:null,reader:false,indexPosition:0,indexScroll:0,indexLeft:0,bodyScroll:0,bodyPaper:null,missingLinkPaper:false});
  $('kept-reader').hidden=true;$('array-index').replaceChildren();refreshActions();
});
window.addEventListener('array-reader-empty',()=>{ui.reader=false;ui.selected=null;ui.bodyPaper=null;ui.bodyScroll=0;$('kept-reader').hidden=true;});
window.addEventListener('array-paper-selected',event=>{ui.selected=event.detail;ui.bodyPaper=event.detail;ui.bodyScroll=0;render();});
for(const next of Object.keys(states))$('array-'+next).addEventListener('click',()=>setStatus(next));
$('workspace-archive').addEventListener('click',()=>setLayout('archive'));
$('workspace-array').addEventListener('click',()=>setLayout('array'));
$('array-index').addEventListener('scroll',()=>{ui.indexScroll=$('array-index').scrollTop;ui.indexLeft=$('array-index').scrollLeft;});
function initialize(){
  data=bridge.data();render();
  const initial=window.uiNextInitialLink;
  if(initial?.paper && !openPaper(initial.paper)){ui.missingLinkPaper=true;render();uiNext.notice('该 Paper 不在当前 Workspace 中。');}
}
if(bridge.available())initialize();else window.addEventListener('inbox-ready',initialize,{once:true});
window.addEventListener('ui-preferences-changed',()=>{queueArchivePreference();refreshActions();});
window.addEventListener('resize',()=>layoutHost.sync());
refreshActions();
window.addEventListener('paper-reading-state',()=>{if(arrayShown() && !bridge.busy() && readerRefreshPending)render();else refreshActions();});
window.addEventListener('workspace-navigation-state',()=>{
  const busy=switchBusy();
  for(const id of ['workspace-archive','workspace-array','array-candidates','array-downloaded','array-trash'])$(id).disabled=busy;
  $('workspace-archive').hidden=archiveDisabled();queueArchivePreference();
});
document.addEventListener('keydown',event=>{
  if(event.defaultPrevented || $('selected-view').closest('[inert]') || !arrayShown() || !['ArrowUp','ArrowDown','ArrowLeft','ArrowRight'].includes(event.key) ||
      event.altKey || event.metaKey || event.ctrlKey || event.shiftKey || switchBusy() || document.querySelector('dialog[open]') ||
      event.target.isContentEditable || event.target.closest('input,textarea,select,[contenteditable]'))return;
  if(['ArrowLeft','ArrowRight'].includes(event.key)){
    if(!ui.reader)return;
    const button=$(event.key==='ArrowLeft'?'previous-paper':'next-paper');if(button.disabled)return;
    button.click();event.preventDefault();
  }else if(moveIndex(event.key==='ArrowUp'?-1:1))event.preventDefault();
});
