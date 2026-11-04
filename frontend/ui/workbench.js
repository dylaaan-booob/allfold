'use strict';
// One Browser pane moves between presentation hosts; pages and task authority stay native.
window.allfoldWorkbench=(()=>{
  const $=id=>document.getElementById(id),desktop=window.allfoldDesktop;
  let visible=false,returning=false,returnFocus=null,sequence=0,frame=null,state={tabs:[],selected:null};
  let scrollSnapshot=[],workspaceAtShow=null;
  let source=null,mode='focus',requested=null;
  let savedServices={scope:null,services:[]},lastSelected=null;
  const preferenceKeys={expanded:'allfold.browser-services-expanded',width:'allfold.browser-services-width'};
  const readPreference=(key,fallback)=>{try{const value=localStorage.getItem(key);return value===null?fallback:JSON.parse(value);}catch(_){return fallback;}};
  const expandedPreference=readPreference(preferenceKeys.expanded,true),widthPreference=readPreference(preferenceKeys.width,288);
  let expanded=typeof expandedPreference==='boolean'?expandedPreference:true;
  let preferredWidth=typeof widthPreference==='number' && Number.isFinite(widthPreference) && widthPreference>=180 && widthPreference<=560?Math.round(widthPreference):288;
  let drag=null;
  const savePreference=(key,value)=>{try{localStorage.setItem(key,JSON.stringify(value));}catch(_){/* UI remains usable if local storage is unavailable. */}};
  function sizeServices() {
    const area=$('browser-work-area'),width=Math.max(0,area.getBoundingClientRect().width-320-6);
    const effective=source!=='run' && expanded && width>=180?Math.min(preferredWidth,width):0;
    area.style.setProperty('--browser-services-width',effective+'px');
    $('browser-services').hidden=$('browser-services-resize').hidden=!expanded || effective<=0;
    $('browser-services-toggle').setAttribute('aria-expanded',String(expanded && effective>0));
    $('browser-services-resize').setAttribute('aria-valuenow',String(preferredWidth));schedule();
  }
  const roles={'carsi-portal':'CARSI 共享认证','service-resource':'Service','service-target':'Service 目标',
    'manual-service':'Manual Service','wos-query':'WoS Query','wos-export':'WoS Export',
    popup:'Popup',import:'ImportPage',attachment:'附件 · 需要人工操作',auxiliary:'辅助页'};
  function active(){return visible && (source!=='kept' || window.workspaceNavigation?.current?.()==='kept');}
  function suspended(){
    if([...document.querySelectorAll('dialog[open]')].some(dialog=>!['run-view','kept-flow'].includes(dialog.id)))return true;
    const rect=$('browser-body').getBoundingClientRect();
    return [...document.querySelectorAll('.navigation-flyout:not([hidden]),[data-sidebar-mode="overlay"] .functional-sidebar:not([hidden])')].some(overlay=>{
      if(overlay.closest('[hidden]'))return false;
      const box=overlay.getBoundingClientRect();
      return box.width>0 && box.height>0 && box.left<rect.left+rect.width && box.left+box.width>rect.left
        && box.top<rect.top+rect.height && box.top+box.height>rect.top;
    });
  }
  function sizeBrowser() {
    const pane=$('browser-pane'),preferred=window.allfoldLayout?.targets?.() || {browserPreferredWidth:960,browserPreferredHeight:300};
    pane.style.setProperty('--browser-preferred-width',preferred.browserPreferredWidth+'px');
    pane.style.setProperty('--browser-preferred-height',preferred.browserPreferredHeight+'px');
  }
  function publish() {
    if(!desktop)return;
    const rect=$('browser-body').getBoundingClientRect();
    const showing=active();
    for(const [name,value] of [['Width',rect.width],['Height',rect.height]])if($('layout-browserEffective'+name))$('layout-browserEffective'+name).textContent=showing?Math.round(value):'—';
    void desktop.setBrowserPresentation({sequence:++sequence,visible:showing,suspended:suspended(),
      bounds:showing?{x:rect.left,y:rect.top,width:rect.width,height:rect.height}:null}).catch(()=>{
      $('browser-message').textContent='Browser 显示未能更新，请重新打开 Browser。';
    });
  }
  function schedule(){if(frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;publish();});}
  function present(value,options={}) {
    if(value && (!visible || !active() || (options.source && source!==options.source))){
      source=null;mode='focus';
      returnFocus=document.activeElement;workspaceAtShow=window.workspaceNavigation?.current?.();
      scrollSnapshot=[...$('allfold-pane').querySelectorAll('*')].filter(node=>node.scrollTop || node.scrollLeft).map(node=>({
        node,top:node.scrollTop,left:node.scrollLeft,firstChild:node.firstChild,paper:node.dataset.paperId,
      }));
    }
    if(value){
      source=options.source || source || (window.workspaceNavigation?.current?.()==='kept'?'kept':null);
      mode=options.mode==='compact'?'compact':options.mode==='focus'?'focus':mode;
      const host=source==='kept'?$('kept-browser-host'):$('workbench-content');
      if(!host){window.uiNext.notice('Browser 呈现区域尚未就绪，请返回后重试。');return false;}
      host.append($('browser-pane'));
    }
    visible=value;document.body.dataset.workbench=value?(source==='kept'?'kept-browser':'browser'):'allfold';
    $('allfold-pane').inert=value && source!=='kept';$('browser-pane').hidden=!value;
    $('browser-pane').dataset.mode=mode;$('browser-pane').dataset.source=source || 'legacy';
    $('browser-return').textContent=source==='run'?'← RUN':source==='kept'?'← QUEUE':'← ALLFOLD';
    $('browser-compact')?.setAttribute('aria-pressed',String(mode==='compact'));
    $('browser-focus')?.setAttribute('aria-pressed',String(mode==='focus'));
    if($('browser-compact'))$('browser-compact').hidden=source!=='kept';
    if($('browser-compact'))$('browser-compact').textContent=mode==='focus'?'RESTORE':'COMPACT';
    if($('browser-focus'))$('browser-focus').hidden=source==='run';
    $('browser-services-toggle').hidden=source==='run';
    $('browser-open')?.setAttribute('aria-pressed',String(value));
    $('browser-open')?.setAttribute('aria-label',value?'返回 Allfold':'打开 Browser 工作视图');
    // The business host reveals Queue before its saved control receives focus.
    window.dispatchEvent(new CustomEvent('workbench:browser-state',{detail:{visible:value,source,mode}}));
    if(!value){returning=true;if(returnFocus?.isConnected && !returnFocus.disabled)returnFocus.focus({preventScroll:true});
      requestAnimationFrame(()=>{
        if(!visible && window.workspaceNavigation?.current?.()===workspaceAtShow)
          for(const saved of scrollSnapshot)if(saved.node.isConnected && saved.node.firstChild===saved.firstChild && saved.node.dataset.paperId===saved.paper){
            saved.node.scrollTop=saved.top;saved.node.scrollLeft=saved.left;
          }
        scrollSnapshot=[];returning=false;
      });}
    sizeBrowser();sizeServices();publish();schedule();
    window.dispatchEvent(new Event('workbench-presentation-changed'));
    return true;
  }
  async function show(options={}) {
    if(!desktop){window.uiNext.notice('请在 Electron 桌面应用中使用 Browser');return false;}
    requested=options;
    try {render(await desktop.showBrowser());if(!present(true,options))return false;await refreshServices();return true;}
    catch(error){window.uiNext.notice(error.message);return false;}
    finally{requested=null;}
  }
  async function showTaskPage({workflowId,taskId,source:origin}={}) {
    if(!desktop)return false;
    try {
      const snapshot=await desktop.browserState(),pages=snapshot.tabs.filter(page=>{
        const association=page.association;
        return association && (workflowId?association.workflow_id===workflowId:true)
          && (taskId?association.task_id===taskId:true) && (workflowId || taskId);
      });
      const score=page=>(page.association.active?100:0)+(page.id===snapshot.taskPageId?20:0)
        +({attachment:40,popup:30}[page.association.role] || 0);
      pages.sort((a,b)=>score(b)-score(a) || b.id-a.id);
      if(!pages.length){window.uiNext.notice('当前任务尚无可查看的网页，或页面已关闭。');return false;}
      // A user handoff chooses a real Page ID; this does not bind or retarget the task.
      render(await desktop.browserCommand({action:'select',id:pages[0].id}));
      if(!present(true,{source:origin || (window.workspaceNavigation?.current?.()==='kept'?'kept':null),mode:origin==='run'?'focus':mode}))return false;
      await refreshServices();return true;
    }catch(error){window.uiNext.notice(error.message);return false;}
  }
  async function command(action,extra={}) {
    if(!desktop)return;
    try {$('browser-message').textContent='';render(await desktop.browserCommand({action,...extra}));}
    catch(_){$('browser-message').textContent=state.taskRunning && ['clear-cache','clear-site-data'].includes(action)
      ?'任务运行期间不能清理浏览器数据。':'操作未完成，请检查页面或任务状态。';}
  }
  async function refreshServices() {
    try {savedServices=await window.uiNext.request('/api/ui-next/browser-services');}
    catch(_){savedServices={scope:null,services:[]};}
    render(state);
  }
  async function openService({serviceId,workflowId,taskId}={}) {
    if(!desktop)return false;
    await refreshServices();
    const service=savedServices.services.find(service=>service.id===serviceId);
    if(!service?.access_url){window.uiNext.notice('此 Service 没有已保存的访问链接，请检查 Settings。');return false;}
    try {
      render(await desktop.browserCommand({action:'open-service',url:service.access_url,service_id:service.id,
        service_scope:savedServices.scope,workflow_id:workflowId || null,task_id:taskId || null}));
      present(true);return true;
    }catch(_){window.uiNext.notice('无法打开此 Service，请检查已保存的访问链接。');return false;}
  }
  function pageButton(page) {
    const button=document.createElement('button');button.type='button';button.dataset.pageId=String(page.id);
    button.textContent=(page.error?'! ':page.loading?'… ':'')+(page.title || 'New page');
    button.setAttribute('aria-pressed',String(page.id===state.selected));
    button.onclick=()=>void command('select',{id:page.id});return button;
  }
  function render(value) {
    state=value || state;
    const tabs=state.tabs || [];
    $('browser-tabs').replaceChildren(...tabs.map(page=>{
      const row=document.createElement('div');row.className='browser-tab';row.dataset.pageId=String(page.id);
      row.dataset.selected=String(page.id===state.selected);
      const select=pageButton(page);select.title=page.title || 'New page';
      const close=document.createElement('button');close.type='button';close.textContent='×';close.disabled=!!page.busy;
      close.setAttribute('aria-label','关闭 '+(page.title || 'New page'));close.onclick=()=>void command('close',{id:page.id});
      row.append(select,close);return row;
    }));
    const selected=tabs.find(page=>page.id===state.selected);
    if(document.activeElement!==$('browser-url'))$('browser-url').value=selected?.url || '';
    $('browser-back').disabled=!selected?.back;$('browser-forward').disabled=!selected?.forward;
    for(const id of ['browser-reload','browser-devtools'])$(id).disabled=!selected;
    for(const id of ['browser-clear-cache','browser-clear-site-data'])$(id).disabled=!!state.taskRunning;
    const bytes=state.cacheSize;
    $('browser-cache-size').textContent='HTTP 缓存：'+(bytes==null?'未查询':bytes<1024?bytes+' B':
      bytes<1024*1024?(bytes/1024).toFixed(1)+' KiB':(bytes/(1024*1024)).toFixed(1)+' MiB');
    $('browser-message').textContent=selected?.error?.kind==='load'?`页面加载失败（${selected.error.code || 'load_failed'}），请刷新。`:
      selected?.error?.kind==='renderer'?'页面渲染进程已退出，请刷新。':selected?.loading?'正在加载…':'';
    $('browser-empty').hidden=!!selected;
    $('browser-status').textContent=`BROWSER · ${tabs.length} PAGES`;
    const groups=new Map();
    for(const page of tabs) {
      const association=page.association,scope=association?.service_scope?.scope_id,serviceId=association?.service_id;
      const service=scope===savedServices.scope?.scope_id?savedServices.services.find(service=>service.id===serviceId):null;
      const key=scope && serviceId?scope+':'+serviceId:association?.role==='carsi-portal'?'carsi':'other';
      if(!groups.has(key))groups.set(key,{name:scope && serviceId?
        (service?.name || 'Service '+serviceId)+(service?.access_method==='manual'?' · Manual Service':''):
        key==='carsi'?'CARSI 共享认证':'其他 / 共享',pages:[],scope,serviceId});
      groups.get(key).pages.push(page);
    }
    $('browser-service-pages').replaceChildren(...[...groups.values()].map(group=>{
      const section=document.createElement('section'),heading=document.createElement('h3'),list=document.createElement('div');
      heading.textContent=group.name;section.dataset.scope=group.scope || '';section.dataset.serviceId=group.serviceId || '';
      if(group.scope)heading.title=`Scope ${group.scope} · ${group.serviceId}`;
      list.replaceChildren(...group.pages.map(page=>{
        const row=pageButton(page),association=page.association;
        const description=document.createElement('small');
        description.textContent=[roles[association?.role] || (page.openerId?'Popup':'手动页'),
          association?.paper_id?`Paper ${association.paper_id}`:association?.doi,
          association?.source_page_id?`来源 #${association.source_page_id}`:page.openerId?`来源 #${page.openerId}`:null,
          association?.active?'任务中':null].filter(Boolean).join(' · ');
        row.append(description);return row;
      }));section.append(heading,list);return section;
    }));
    if(state.selected!==lastSelected){lastSelected=state.selected;
      const index=tabs.findIndex(page=>page.id===state.selected);$('browser-tabs').children[index]?.scrollIntoView({block:'nearest',inline:'nearest'});}
    schedule();
  }
  $('browser-open')?.addEventListener('click',()=>{if(visible)present(false);else void show();});
  $('browser-return').addEventListener('click',()=>present(false));
  for(const next of ['compact','focus'])$('browser-'+next)?.addEventListener('click',()=>present(true,{source,mode:next}));
  for(const action of ['new','back','forward','reload','devtools','cache-size','clear-cache','clear-site-data'])
    $('browser-'+action).addEventListener('click',()=>void command(action,['back','forward','reload','devtools'].includes(action)?{id:state.selected}:{}));
  $('browser-address').addEventListener('submit',event=>{event.preventDefault();void command('navigate',{id:state.selected,url:$('browser-url').value.trim()});});
  $('browser-services-toggle').addEventListener('click',()=>{expanded=!expanded;savePreference(preferenceKeys.expanded,expanded);sizeServices();});
  const resizer=$('browser-services-resize');
  resizer.addEventListener('pointerdown',event=>{
    if(event.button!==0)return;event.preventDefault();drag={x:event.clientX,width:preferredWidth,pointer:event.pointerId};
    resizer.setPointerCapture(event.pointerId);
  });
  resizer.addEventListener('pointermove',event=>{
    if(!drag || event.pointerId!==drag.pointer)return;
    preferredWidth=Math.round(Math.max(180,Math.min(560,drag.width+drag.x-event.clientX)));sizeServices();
  });
  function endResize(){if(drag){drag=null;savePreference(preferenceKeys.width,preferredWidth);}}
  resizer.addEventListener('pointerup',endResize);resizer.addEventListener('pointercancel',endResize);
  resizer.addEventListener('lostpointercapture',endResize);
  resizer.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;event.preventDefault();
    preferredWidth=event.key==='Home'?180:event.key==='End'?560:Math.max(180,Math.min(560,preferredWidth+(event.key==='ArrowLeft'?20:-20)));
    savePreference(preferenceKeys.width,preferredWidth);sizeServices();
  });
  desktop?.onBrowserState(render);
  desktop?.onBrowserPresentation(value=>{if(value?.visible)present(true,requested || {});});
  desktop?.onBrowserLayout(schedule);
  if(desktop)void desktop.browserState().then(render).catch(()=>{});
  new MutationObserver(()=>{if(visible)publish();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open','hidden','data-sidebar-mode']});
  new ResizeObserver(schedule).observe($('browser-body'));
  new ResizeObserver(sizeServices).observe($('browser-work-area'));
  window.addEventListener('resize',schedule);
  window.addEventListener('workspace-navigation-state',()=>{if(visible)publish();schedule();});
  window.allfoldLayout?.subscribe(()=>{sizeBrowser();if(visible)publish();schedule();});
  sizeServices();
  return {show,showTaskPage,openService,showKeptBrowser:({mode:next='compact'}={})=>show({source:'kept',mode:next}),
    hideKeptBrowser:()=>{if(source==='kept')present(false);},hide:()=>present(false),visible:active,presentationChanging:()=>active() || returning};
})();
