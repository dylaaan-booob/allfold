import {renderHistoryRecord,filterHistoryRecords,historyIntegrityMessage,requestDiagnosticBundle} from './history-view.js';
const $=id=>document.getElementById(id),dialog=$('history-dialog');
let timer,focus,loading=false;
async function csrfToken() {
  if(uiNext.csrf_token)return uiNext.csrf_token;
  const state=await uiNext.request('/api/ui-next/settings');
  uiNext.csrf_token=state.csrf_token;return state.csrf_token;
}
async function exportTask(taskId=null) {
  const blob=await requestDiagnosticBundle(taskId,await csrfToken());
  const url=URL.createObjectURL(blob),link=document.createElement('a');
  link.href=url;link.download='allfold-diagnostics.zip';document.body.append(link);link.click();link.remove();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
}
async function refresh() {
  if(loading || !dialog.open)return;
  loading=true;clearTimeout(timer);$('history-refresh').disabled=true;
  try {
    const data=await uiNext.request('/api/history');
    if(!dialog.open)return;
    const expanded=new Set([...$('history-records').querySelectorAll('details[open]')].map(node=>node.closest('[data-history-task]').dataset.historyTask));
    const select=$('history-service-filter'),selected=select.value;
    const services=new Set(data.records.flatMap(record=>[record.details?.service_id,
      ...(record.details?.service_statistics || []).map(item=>item.service_id),
      ...(record.details?.results || []).map(item=>item.service_id)]).filter(Boolean));
    select.replaceChildren(...['',...services].map(id=>{const option=document.createElement('option');option.value=id;option.textContent=id || 'All Services';return option;}));
    select.value=services.has(selected)?selected:'';
    $('history-records').innerHTML=filterHistoryRecords(data.records,select.value).map(renderHistoryRecord).join('') || '<p>尚无运行记录。</p>';
    for(const node of $('history-records').querySelectorAll('details'))node.open=expanded.has(node.closest('[data-history-task]').dataset.historyTask);
    $('history-status').textContent=historyIntegrityMessage(data.integrity);
    if(data.records.some(record=>record.outcome==='running'))timer=setTimeout(()=>void refresh(),3000);
  }catch(error){$('history-status').textContent=error.message;}
  finally {loading=false;$('history-refresh').disabled=false;}
}
function open() {
  if(!dialog.open){focus=document.activeElement;dialog.showModal();}
  void refresh();
}
$('history-open').addEventListener('click',open);
$('history-refresh').addEventListener('click',()=>void refresh());
$('history-service-filter').addEventListener('change',()=>void refresh());
$('history-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{clearTimeout(timer);if(focus?.isConnected && !focus.disabled)focus.focus({preventScroll:true});});
$('history-records').addEventListener('click',async event=>{
  const button=event.target.closest('[data-history-export]');if(!button || button.disabled)return;
  button.disabled=true;$('history-status').textContent='正在生成本地诊断包…';
  try {await exportTask(button.dataset.historyExport);$('history-status').textContent='诊断包已生成；仅在本地下载，未上传。';}
  catch(error){$('history-status').textContent=error.message;}
  finally {button.disabled=false;}
});
window.addEventListener('logs-reset',()=>{if(dialog.open)void refresh();});
window.addEventListener('workspace-reset',()=>{if(dialog.open)void refresh();});
window.allfoldHistory={open,exportTask};
