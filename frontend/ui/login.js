const $=id=>document.getElementById(id);
const layout=window.allfoldLayout.create({root:$('login-page'),workspace:'login',minContentWidth:360});
let state=null,timer=null,busy=false,recovering=false,cancelRequested=false,revision=0,selectedService=null;

function button(label,action,disabled=false) {
  const node=document.createElement('button');
  node.type='button';node.className='s-button';node.textContent=label;node.disabled=disabled;
  node.addEventListener('click',action);return node;
}
function row(name,preparation,{id,manual=false}={}) {
  const item=document.createElement('section'),title=document.createElement('strong'),status=document.createElement('span');
  item.className='login-service-row';
  item.dataset.loginKey=id || 'carsi';item.tabIndex=-1;
  if(id)item.dataset.serviceId=id;
  title.textContent=name;
  status.textContent=preparation?.waiting_for_user?'Needs attention':preparation?.status || 'Not prepared';
  item.append(title,status);
  if(preparation?.page_id) {
    const target={pageId:preparation.page_id,workflowId:preparation.workflow_id,taskId:preparation.task_id};
    const open=button('查看任务页面',()=>window.allfoldWorkbench.showTaskPage(target));
    open.dataset.loginAction='page';item.append(open);
  }
  if(manual){
    const visit=button('Visit',()=>mutate('start',{service_id:id}),busy || recovering || Boolean(state?.active));
    visit.dataset.loginAction='visit';item.append(visit);
  }
  const diagnostic=preparation?.diagnostic;
  if(preparation?.reason || diagnostic || preparation?.task_id){
    const details=document.createElement('details'),summary=document.createElement('summary'),text=document.createElement('p');
    summary.textContent='详情';
    text.textContent=[preparation.reason,diagnostic?.stage,diagnostic?.step,diagnostic?.code,preparation.task_id]
      .filter(Boolean).join(' · ');
    details.append(summary,text);item.append(details);
  }
  return item;
}
function render() {
  $('login-start').disabled=!state?.services?.length || busy || recovering || state.active;
  $('login-cancel').hidden=!state?.active;$('login-cancel').disabled=busy || cancelRequested;
  if(!state)return;
  const phase=cancelRequested?'正在取消':({carsi:'机构登录中',preparing:'正在准备 Services',completed:'准备结束',failed:'Login 失败',
    interrupted:'Browser 连接已中断',canceled:'Login 已取消'})[state.phase] || '';
  const opened=state.services.filter(service=>service.preparation?.status==='Opened').length;
  $('login-status').textContent=state.services.length?[phase,`${opened} / ${state.services.length} Services opened`].filter(Boolean).join(' · '):
    '请先在 Journals 的 Access 中保存 Service。';
  const focused=document.activeElement,action=focused?.dataset.loginAction;
  const focusedKey=focused?.closest('[data-login-key]')?.dataset.loginKey;
  const carsi=state.services.some(service=>service.access_method==='carsi')?row('CARSI',state.carsi):null;
  const expanded=new Set([...$('login-main').querySelectorAll('.login-service-row details[open]')]
    .map(details=>details.closest('[data-login-key]').dataset.loginKey));
  const rows=state.services.map(service=>row(service.name,service.preparation,
    {id:service.id,manual:service.access_method==='manual' && Boolean(service.access_url)}));
  for(const entry of [carsi,...rows])if(entry && expanded.has(entry.dataset.loginKey)){
    const details=entry.querySelector('details');if(details)details.open=true;
  }
  $('login-carsi').replaceChildren(...(carsi?[carsi]:[]));
  $('login-services').replaceChildren(...rows);
  if(selectedService){
    const match=rows.find(node=>node.dataset.serviceId===selectedService);
    if(match){match.scrollIntoView({block:'nearest'});match.focus({preventScroll:true});selectedService=null;}
  }else if(focusedKey){
    const entry=[carsi,...rows].find(node=>node?.dataset.loginKey===focusedKey);
    (action?entry?.querySelector(`[data-login-action="${action}"]:not(:disabled)`):entry)?.focus({preventScroll:true});
  }
}
function poll() {
  clearTimeout(timer);
  if(recovering || state?.active)timer=setTimeout(()=>void refresh(),1000);
}
function accept(next) {
  const changed=state?.active!==next.active || state?.phase!==next.phase || state?.workflow_id!==next.workflow_id;
  if(!next.active || state?.workflow_id!==next.workflow_id)cancelRequested=false;
  recovering=false;state=next;render();
  if(changed)window.dispatchEvent(new Event('login-state-changed'));
}
async function refresh() {
  if(busy)return;
  const read=++revision;clearTimeout(timer);
  try {const next=await uiNext.request('/api/login/state');if(read===revision)accept(next);}
  catch(error){if(read===revision)$('login-status').textContent=error.message;}
  finally{if(read===revision)poll();}
}
async function mutate(action,body) {
  if(busy || recovering || (action==='start' && state?.active) || (action==='cancel' && cancelRequested))return;
  ++revision;busy=true;clearTimeout(timer);render();
  try {
    if(action==='start' && window.allfoldAutosave && !await window.allfoldAutosave.flush()){
      uiNext.notice('配置尚未保存，请处理保存状态后重试。');return;
    }
    const next=await uiNext.request('/api/login/'+action,body);
    if(action==='cancel')cancelRequested=true;
    accept(next);
  }catch(error){recovering=true;uiNext.notice(error.message);}
  finally{
    busy=false;render();
    if(recovering)await refresh();else poll();
  }
}
$('login-start').addEventListener('click',()=>mutate('start',{}));
$('login-cancel').addEventListener('click',()=>{if(state?.workflow_id)void mutate('cancel',{workflow_id:state.workflow_id});});
window.workspaceNavigation.register('login',{
  enter(){
    window.dispatchEvent(new Event('login-settings-mount'));
    layout.sync();$('login-main').focus({preventScroll:true});
    void refresh();
  },
});
window.addEventListener('workflow-service-selected',event=>{selectedService=event.detail.serviceId;render();});
window.addEventListener('settings-saved',()=>{if(window.workspaceNavigation.current()==='login')void refresh();});
window.addEventListener('pagehide',()=>clearTimeout(timer));
if(window.workspaceNavigation.current()==='login')void refresh();
