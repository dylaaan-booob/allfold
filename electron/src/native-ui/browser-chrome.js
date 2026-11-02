'use strict';
const $=id=>document.getElementById(id);
let state={tabs:[],selected:null};
async function command(action, extra={}) {
  try {$('message').textContent='';render(await window.browserChrome.command({action,id:state.selected,...extra}));}
  catch (_) {
    $('message').textContent=state.taskRunning && ['clear-cache','clear-site-data'].includes(action)
      ?'任务运行期间不能清理浏览器数据。':'操作未完成，请检查页面或任务状态。';
    $('message').title=$('message').textContent;
  }
}
function render(value) {
  state=value;
  $('tabs').replaceChildren(...state.tabs.map(tab=>{
    const row=document.createElement('div');row.className='tab'+(tab.id===state.selected?' selected':'');
    const select=document.createElement('button');select.type='button';select.textContent=(tab.error?'! ':tab.loading?'… ':'')+tab.title;select.title=tab.title;
    select.setAttribute('aria-pressed',String(tab.id===state.selected));select.onclick=()=>command('select',{id:tab.id});
    const close=document.createElement('button');close.type='button';close.textContent='×';close.disabled=tab.busy;
    close.setAttribute('aria-label','关闭 '+tab.title);close.onclick=()=>command('close',{id:tab.id});
    row.append(select,close);return row;
  }));
  const selected=state.tabs.find(tab=>tab.id===state.selected);
  if(document.activeElement!==$('url'))$('url').value=selected?.url || '';
  $('back').disabled=!selected?.back;$('forward').disabled=!selected?.forward;$('reload').disabled=!selected;
  $('devtools').disabled=!selected;
  $('clear-cache').disabled=!!state.taskRunning;$('clear-site-data').disabled=!!state.taskRunning;
  const bytes=state.cacheSize;
  $('cache-size').textContent='HTTP 缓存：'+(bytes==null?'未查询':bytes<1024?bytes+' B':
    bytes<1024*1024?(bytes/1024).toFixed(1)+' KiB':(bytes/(1024*1024)).toFixed(1)+' MiB');
  $('message').textContent=selected?.error?.kind==='load'?`页面加载失败（${selected.error.code}），请刷新。`:
    selected?.error?.kind==='renderer'?'页面渲染进程已退出，请刷新。':'';
  $('message').title=$('message').textContent;
}
for(const action of ['new','back','forward','reload','devtools','cache-size','clear-cache','clear-site-data'])
  $(action).onclick=()=>command(action);
$('address').onsubmit=event=>{event.preventDefault();const url=$('url').value.trim();$('url').blur();void command('navigate',{url});};
window.browserChrome.onState(render);
void command('state');
