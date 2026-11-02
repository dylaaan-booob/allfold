import {RunVisual} from './run-visual.js';
import {resultHeadline,resultMessages} from './run-results.js';
const $=id=>document.getElementById(id),dialog=$('run-view');
const reduced=matchMedia('(prefers-reduced-motion: reduce)');
const animationPreferenceKey='allfold.run-animation-disabled';
let animationDisabled=false;
try {animationDisabled=localStorage.getItem(animationPreferenceKey)==='true';} catch {}
const reduceRunMotion=()=>animationDisabled || reduced.matches;
const transition=new SurfaceTransition($('run-wash'),undefined,600,600);
let active=null,pending=null,starting=false;
function stopRunAnimation() {
  if(active) {active.reduced=true;active.visual.stop();}
  transition.finish();
}
function setAnimationDisabled(disabled) {
  animationDisabled=disabled;
  if(reduceRunMotion())stopRunAnimation();
  localStorage.setItem(animationPreferenceKey,String(disabled));
}
const providerLabels={openalex:'Run OpenAlex',crossref:'Run Crossref',pubmed:'Run PubMed',wos:'Run WoS'};
function disableRunButtons(disabled) {
  if(disabled)document.querySelectorAll('[data-run-provider]').forEach(button=>{button.disabled=true;});
  else window.uiRunPage?.updateButtons();
}

function report(text,details=[]) {
  window.uiRunPage?.report(text,details,pending!==null);
}
function resultDetails(snapshot) {
  const result=snapshot.result;
  if(!result)return snapshot.unexpected_error?[snapshot.unexpected_error.message]:[];
  const pubmed=result.provider==='pubmed' && result.statistics
    ? [`PubMed: ${result.statistics.pubmed_search_total} search results · ${result.statistics.pubmed_records} fetched · ${result.statistics.pubmed_failed_batches} failed batches`,
       ...(result.coverage||[]).map(unit=>`PubMed Discovery Coverage: ${unit.status}`)] : [];
  return [...pubmed,...(result.warnings||[]),...(result.errors||[]),...(result.diagnostics||[]),...(result.issues||[])].map(item=>typeof item==='string'?item:item.message);
}
function showState(data) {
  const {snapshot,progress}=data;
  $('run-title').textContent='Run '+(window.uiRunPage?.providerName(snapshot.provider) || providerLabels[snapshot.provider]);
  if(data.providers)window.dispatchEvent(new CustomEvent('run-state',{detail:data}));
  $('run-elapsed').textContent=progress.elapsed_text || '0s';
  $('run-stage').textContent=progress.stage_label || snapshot.status;
  $('run-description').textContent=progress.announcement_message || (snapshot.inactivity_warning?'暂未收到新的活动。':'');
  dialog.dataset.waitingForUser=String(snapshot.provider==='wos' && !!snapshot.waiting_for_user);
}
async function finish(run,data) {
  if(active!==run || run.ended)return;
  run.ended=true;clearTimeout(run.timer);run.visual.stop();showState(data);
  const snapshot=data.snapshot,label='Run '+window.uiRunPage.providerName(snapshot.provider);
  const summary=resultHeadline(data.result_summary);
  $('run-stage').textContent='RUN FINISHED';$('run-description').textContent=summary;
  const details=resultMessages(data.result_summary);
  try {await window.inboxRun.prepare(null,run.selection);pending=null;}
  catch(error){pending=run.selection;details.push(`Inbox 刷新失败：${error.message}`);}
  report(`${label} · ${summary}`,details);
  try {
    if(!run.reduced && !reduceRunMotion()) {
      await new Promise(resolve=>{transition.show(false);const animation=transition.animations[0];if(animation)void animation.finished.then(resolve,resolve);else resolve();});
      $('run-stage-layer').hidden=true;dialog.classList.add('returning');dialog.querySelector('.run-background').hidden=true;
      await new Promise(resolve=>transition.hide(run.reduced || reduceRunMotion(),resolve));
    }
  }
  finally {
    dialog.close();run.visual.stop();active=null;$('run-wos-cancel').hidden=true;
    window.uiRunPage.open();
    try {await window.uiRunPage.refresh();} finally {disableRunButtons(false);}
  }
  const focus=run.trigger?.isConnected && !run.trigger.disabled?run.trigger:document.querySelector(`[data-run-provider="${run.provider}"]:not([hidden])`);focus?.focus({preventScroll:true});
}
async function poll(run) {
  if(active!==run || run.ended)return;
  try {
    const data=await uiNext.request('/api/ui-next/'+run.kind);showState(data);
    if(data.snapshot.status!=='RUNNING'){await finish(run,data);return;}
  }catch(error){$('run-description').textContent=`连接中断：${error.message}；正在等待状态恢复。`;}
  if(active===run && !run.ended)run.timer=setTimeout(()=>void poll(run),750);
}
function open(data,trigger=null) {
  if(active)return;
  window.uiRunPage?.open();
  const run=active={selection:window.inboxRun.selection(),ended:false,reduced:reduceRunMotion(),provider:data.snapshot.provider,kind:data.snapshot.provider==='wos'?'run-wos':'run',taskID:data.snapshot.task_id,trigger};
  $('run-wash').hidden=true;$('run-stage-layer').hidden=false;
  dialog.classList.remove('returning');dialog.querySelector('.run-background').hidden=false;
  run.visual=new RunVisual(dialog,run.reduced);
  $('run-wos-cancel').hidden=run.provider!=='wos';$('run-wos-cancel').disabled=false;
  disableRunButtons(true);
  dialog.show();showState(data);void run.visual.start();
  if(data.snapshot.status==='FINISHED')void finish(run,data);else void poll(run);
}
async function start(provider,trigger=null) {
  if(active || starting || !window.uiRunPage?.canRun(provider) || !window.inboxRun?.available())return;
  starting=true;disableRunButtons(true);
  const endpoint=provider==='wos'?'run-wos':'run';
  try {open(await uiNext.request('/api/ui-next/'+endpoint,provider==='wos'?{}:{provider}),trigger);}
  catch(error){report(providerLabels[provider]+' 启动失败',resultDetails(error.state?.snapshot || {}).concat(error.message));}
  finally {starting=false;if(!active){try{await window.uiRunPage.refresh();}finally{disableRunButtons(false);}}}
}
$('run-wos-cancel').addEventListener('click',async()=>{
  if(active?.kind!=='run-wos')return;
  $('run-wos-cancel').disabled=true;
  try {await uiNext.request('/api/ui-next/run-wos/cancel',{task_id:active.taskID});}
  catch(error){$('run-description').textContent=error.message;$('run-wos-cancel').disabled=false;}
});
dialog.addEventListener('cancel',event=>event.preventDefault());
reduced.addEventListener('change',()=>{if(reduceRunMotion())stopRunAnimation();});
async function retry() {
  $('s-run-retry').disabled=true;
  try{await window.inboxRun.prepare(null,pending);pending=null;report('Inbox 已刷新。');}
  catch(error){report('Inbox 尚未准备完成',[error.message]);}
  finally{$('s-run-retry').disabled=false;}
}
async function restore() {
  if(active || starting)return;
  try {
    const data=await uiNext.request('/api/ui-next/run');
    window.dispatchEvent(new CustomEvent('run-state',{detail:data}));
    const wos=data.providers.wos;
    if(wos.snapshot?.status==='RUNNING'){
      if(!$('kept-flow').open)open(await uiNext.request('/api/ui-next/run-wos'));
    }else if(data.snapshot.status==='RUNNING' && !$('kept-flow').open)open(data);
  }catch(error){window.uiRunPage?.report(error.message);}
}
window.uiRun={start,retry,active:()=>!!active || starting,
  animationDisabled:()=>animationDisabled,setAnimationDisabled};
window.addEventListener('settings-draft-changed',()=>{if(!active && !starting)disableRunButtons(false);});
const availabilityTimer=setInterval(()=>{if(!active && !starting)void restore();},5000);
if(window.uiWorkspace.ready())void restore();else window.addEventListener('inbox-ready',()=>void restore(),{once:true});
window.addEventListener('pagehide',()=>{clearInterval(availabilityTimer);if(active){clearTimeout(active.timer);active.visual.stop();}});
$('kept-flow').addEventListener('close',()=>{if(!active)void restore();});
