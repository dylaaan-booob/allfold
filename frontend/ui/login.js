import {recoveryLabel} from './business-results.js';
const $=id=>document.getElementById(id);
const layout=window.allfoldLayout.create({root:$('login-page'),workspace:'login',minContentWidth:360});
const excludedServices=new Set();
let state=null,timer=null,busy=false,recovering=false,cancelRequested=false,revision=0,selectedService=null;

function button(label,action,disabled=false) {
  const node=document.createElement('button');
  node.type='button';node.className='s-button';node.textContent=label;node.disabled=disabled;
  node.addEventListener('click',action);return node;
}
function row(name,preparation,{id,manual=false,accessURL=null}={}) {
  const item=document.createElement('section'),title=document.createElement('strong'),status=document.createElement('span');
  item.className='login-service-row';
  item.dataset.loginKey=id;item.tabIndex=-1;
  if(id)item.dataset.serviceId=id;
  title.textContent=name;
  status.textContent=preparation?.waiting_for_user
    ? '请在 Browser 的对应分组完成验证'
    : recoveryLabel(preparation?.recovery_action) || preparation?.status || 'Not prepared';
  if(manual)item.append(title);
  else {
    const label=document.createElement('label'),check=document.createElement('input');
    label.className='s-check';
    check.type='checkbox';check.checked=!excludedServices.has(id);
    check.disabled=busy || recovering || Boolean(state?.active) || preparation?.status==='Unavailable';
    check.addEventListener('change',()=>{
      if(check.checked)excludedServices.delete(id);else excludedServices.add(id);
      $('login-start').disabled=!selection().length;
    });
    label.append(check,title);item.append(label);
  }
  item.append(status);
  if(manual && accessURL){
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
function selection() {
  return (state?.services || []).filter(service=>service.access_method==='carsi'
    && service.preparation?.status!=='Unavailable' && !excludedServices.has(service.id)).map(service=>service.id);
}
function render() {
  $('login-start').disabled=!selection().length || busy || recovering || state.active;
  $('login-cancel').hidden=!state?.active;$('login-cancel').disabled=busy || cancelRequested;
  if(!state)return;
  const phase=cancelRequested?'正在取消':({preparing:'正在准备 Services',completed:'准备结束',failed:'Login 失败',
   interrupted:'Browser 连接已中断',canceled:'Login 已取消'})[state.phase] || '';
  const opened=state.services.filter(service=>service.preparation?.status==='Opened').length;
  $('login-status').textContent=state.services.length?[phase,`${opened} / ${state.services.length} Services opened`].filter(Boolean).join(' · '):
    '请先在 Journals 的 Access 中保存 Service。';
  const focused=document.activeElement,action=focused?.dataset.loginAction;
  const focusedKey=focused?.closest('[data-login-key]')?.dataset.loginKey;
  const expanded=new Set([...$('login-main').querySelectorAll('.login-service-row details[open]')]
    .map(details=>details.closest('[data-login-key]').dataset.loginKey));
  const rows=state.services.map(service=>row(service.name,service.preparation,
    {id:service.id,manual:service.access_method==='manual',accessURL:service.access_url}));
  for(const entry of rows)if(entry && expanded.has(entry.dataset.loginKey)){
    const details=entry.querySelector('details');if(details)details.open=true;
  }
  $('login-services').replaceChildren(...rows);
  if(selectedService){
    const match=rows.find(node=>node.dataset.serviceId===selectedService);
    if(match){match.scrollIntoView({block:'nearest'});match.focus({preventScroll:true});selectedService=null;}
  }else if(focusedKey){
    const entry=rows.find(node=>node?.dataset.loginKey===focusedKey);
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
  if(busy || recovering || (action!=='cancel' && state?.active) || (action==='cancel' && cancelRequested))return;
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
$('login-start').addEventListener('click',()=>mutate('start',{service_ids:selection()}));
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
