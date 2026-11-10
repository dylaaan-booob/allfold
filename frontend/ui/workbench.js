'use strict';
// Browser presentation uses the shared workspace rail. Native pages keep their own authority.
window.allfoldWorkbench=(()=>{
  const $=id=>document.getElementById(id),desktop=window.allfoldDesktop;
  const pane=$('browser-pane'),tabList=$('browser-tabs');
  let visible=false,returning=false,returnFocus=null,sequence=0,frame=null,state={tabs:[],selected:null};
  let scrollSnapshot=[],workspaceAtShow=null;
  let savedServices={scope:null,services:[]},serviceRead=0;

  function suspended(rect){
    if([...document.querySelectorAll('dialog[open]')].some(dialog=>dialog.id!=='run-view'))return true;
    return [...document.querySelectorAll('.navigation-flyout:not([hidden]),[data-sidebar-mode="overlay"] .functional-sidebar:not([hidden]),:popover-open')].some(overlay=>{
      if(overlay.closest('[hidden],[inert]'))return false;
      const box=overlay.getBoundingClientRect();
      return box.width>0 && box.height>0 && box.left<rect.right && box.right>rect.left
        && box.top<rect.bottom && box.bottom>rect.top;
    });
  }
  function publish() {
    if(!desktop)return;
    const rect=$('browser-body').getBoundingClientRect();
    void desktop.setBrowserPresentation({sequence:++sequence,visible,suspended:visible && suspended(rect),
      bounds:visible?{x:rect.left,y:rect.top,width:rect.width,height:rect.height}:null}).catch(()=>{
      $('browser-message').textContent='Browser 显示未能更新，请重新打开 Browser。';
    });
  }
  function schedule(){if(frame!==null)return;frame=requestAnimationFrame(()=>{frame=null;publish();});}

  const layout=window.allfoldLayout.create({root:pane,minContentWidth:320,visible:()=>visible});
  function present(value) {
    if(visible===value)return;
    if(value){
      returnFocus=document.activeElement;workspaceAtShow=window.workspaceNavigation.current();
      scrollSnapshot=[...$('allfold-pane').querySelectorAll('*')].filter(node=>node.scrollTop || node.scrollLeft).map(node=>({
        node,top:node.scrollTop,left:node.scrollLeft,firstChild:node.firstChild,paper:node.dataset.paperId,
      }));
    }
    visible=value;document.body.dataset.workbench=value?'browser':'allfold';
    $('allfold-pane').inert=value;pane.hidden=!value;
    $('browser-open').setAttribute('aria-pressed',String(value));
    layout.sync();
    if(!value){
      $('app-notice-popover')?.hidePopover?.();
      returning=true;
      const target=returnFocus?.isConnected && !returnFocus.disabled && !returnFocus.closest('[hidden]')?returnFocus:$('browser-open');
      target.focus({preventScroll:true});
      requestAnimationFrame(()=>{
        if(!visible && window.workspaceNavigation.current()===workspaceAtShow){
          for(const saved of scrollSnapshot)if(saved.node.isConnected && saved.node.firstChild===saved.firstChild && saved.node.dataset.paperId===saved.paper){
            saved.node.scrollTop=saved.top;saved.node.scrollLeft=saved.left;
          }
          scrollSnapshot=[];
        }
        returning=false;
      });
    }
    publish();schedule();
    if(value)void refreshServices();
  }
  async function show() {
    if(!desktop){window.uiNext.notice('请在 Electron 桌面应用中使用 Browser');return false;}
    try {render(await desktop.showBrowser());present(true);return true;}
    catch(error){window.uiNext.notice(error.message);return false;}
  }
  async function showTaskPage({workflowId,taskId,parentTaskId,pageId}={}) {
    if(!desktop || !(workflowId || taskId || parentTaskId || pageId))return false;
    try {
      const snapshot=await desktop.browserState(),pages=snapshot.tabs.filter(page=>{
        if(pageId && page.id!==pageId)return false;
        const association=page.association;
        return (!workflowId || association?.workflow_id===workflowId)
          && (!taskId || association?.task_id===taskId)
          && (!parentTaskId || association?.parent_task_id===parentTaskId);
      });
      const score=page=>(page.association?.active?100:0)+(page.id===snapshot.taskPageId?20:0)
        +({attachment:40,popup:30}[page.association?.role] || 0);
      pages.sort((a,b)=>score(b)-score(a) || b.id-a.id);
      if(!pages.length){window.uiNext.notice('当前任务尚无可查看的网页，或页面已关闭。');return false;}
      // Selecting a Page controls presentation only.
      await selectPage(pages[0].id);return true;
    }catch(error){window.uiNext.notice(error.message);return false;}
  }
  async function selectPage(id) {
    layout.closeFlyout();
    render(await desktop.browserCommand({action:'select',id}));
    present(true);
  }
  async function command(action,extra={}) {
    if(!desktop)return;
    try {
      $('browser-message').textContent='';
      if(action==='select')await selectPage(extra.id);else render(await desktop.browserCommand({action,...extra}));
    }catch(_){$('browser-message').textContent='操作未完成，请检查页面或任务状态。';}
  }
  async function refreshServices() {
    const read=++serviceRead;
    let snapshot={scope:null,services:[]};
    try {snapshot=await window.uiNext.request('/api/ui-next/browser-services');}
    catch(_){/* Retry on the next Search open or settings save. */}
    if(read===serviceRead){savedServices=snapshot;render(state);}
    return snapshot;
  }
  function syncChildren(parent,children) {
    const wanted=new Set(children);
    for(const child of [...parent.children])if(!wanted.has(child))child.remove();
    children.forEach((child,index)=>{
      const current=parent.children[index] || null;
      if(child!==current)parent.insertBefore(child,current);
    });
  }
  function tabRow(page) {
    const row=document.createElement('div');row.className='browser-tab';row.dataset.pageId=String(page.id);
    const select=document.createElement('button'),close=document.createElement('button');
    select.type=close.type='button';close.textContent='×';
    select.addEventListener('click',()=>void command('select',{id:page.id}));
    close.addEventListener('click',()=>void command('close',{id:page.id}));
    row.append(select,close);return row;
  }
  function groupPages(tabs) {
    const groups=new Map(),byId=new Map(tabs.map(page=>[page.id,page]));
    function groupFor(page) {
      // Only recorded associations and explicit provenance determine group identity.
      const seen=new Set();
      for(let entry=page;entry && !seen.has(entry.id);entry=byId.get(entry.association?.source_page_id || entry.openerId)){
        seen.add(entry.id);
        const association=entry.association,scope=association?.service_scope?.scope_id,id=association?.service_id;
        if(scope && id){
          const saved=scope===savedServices.scope?.scope_id?savedServices.services.find(service=>service.id===id):null;
          return {key:scope+':'+id,name:saved?.name || 'Service '+id,scope,id};
        }
        if(association?.role==='carsi-portal')return {key:'carsi',name:'CARSI'};
        if(association?.paper_id)return {key:'other',name:'Other'};
      }
      return {key:'other',name:'Other'};
    }
    for(const page of tabs){
      const group=groupFor(page);
      if(!groups.has(group.key))groups.set(group.key,{...group,pages:[]});
      groups.get(group.key).pages.push(page);
    }
    const rank=group=>group.key==='carsi'?0:group.key==='other'?2:1;
    return [...groups.values()].sort((a,b)=>rank(a)-rank(b) || a.name.localeCompare(b.name));
  }
  function renderGroups(tabs) {
    const focused=document.activeElement;
    const sections=new Map([...tabList.children].map(section=>[section.dataset.groupKey,section]));
    const rows=new Map([...sections.values()].flatMap(section=>[...section.children[1].children].map(row=>[row.dataset.pageId,row])));
    const groups=groupPages(tabs);
    syncChildren(tabList,groups.map(group=>{
      let section=sections.get(group.key);
      if(!section){
        section=document.createElement('details');section.dataset.groupKey=group.key;section.open=true;
        section.append(document.createElement('summary'),document.createElement('div'));
      }
      const [heading,list]=section.children;
      heading.textContent=group.name;section.dataset.scope=group.scope || '';section.dataset.serviceId=group.id || '';
      if(group.scope)heading.title=`Scope ${group.scope} · ${group.id}`;
      syncChildren(list,group.pages.map(page=>{
        const row=rows.get(String(page.id)) || tabRow(page);
        const [select,close]=row.children,title=page.title || 'New page';
        row.dataset.selected=String(page.id===state.selected);
        select.textContent=(page.error?'! ':page.loading?'… ':'')+title;
        select.title=title;select.setAttribute('aria-pressed',row.dataset.selected);
        close.hidden=Boolean(page.managed);close.disabled=Boolean(page.busy);
        close.setAttribute('aria-label','关闭 '+title);
        return row;
      }));
      return section;
    }));
    // Moving a focused row between groups can detach it temporarily.
    if(focused?.isConnected && document.activeElement!==focused && !focused.disabled && tabList.contains(focused))
      focused.focus({preventScroll:true});
  }
  function render(value) {
    state=value || state;
    const tabs=state.tabs || [],selected=tabs.find(page=>page.id===state.selected);
    renderGroups(tabs);
    const url=$('browser-url'),locked=Boolean(selected?.managed || selected?.busy);
    if(document.activeElement!==url || locked)url.value=selected?.url || '';
    url.readOnly=locked;url.disabled=!selected;
    $('browser-go').disabled=!selected || locked;
    $('browser-back').disabled=locked || !selected?.back;$('browser-forward').disabled=locked || !selected?.forward;
    $('browser-reload').disabled=!selected || Boolean(selected.busy);
    $('browser-message').textContent=selected?.error?.kind==='load'?`页面加载失败（${selected.error.code || 'load_failed'}），请刷新。`:
      selected?.error?.kind==='renderer'?'页面渲染进程已退出，请刷新。':selected?.loading?'正在加载…':'';
    $('browser-empty').hidden=Boolean(selected);
    $('browser-status').textContent=`BROWSER · ${tabs.length} PAGES`;
    window.workspaceSearch.refresh();
    schedule();
  }

  $('browser-open').addEventListener('click',()=>{if(visible)present(false);else void show();});
  $('browser-return').addEventListener('click',()=>present(false));
  $('browser-new').addEventListener('click',()=>void command('new'));
  for(const action of ['back','forward','reload'])
    $('browser-'+action).addEventListener('click',()=>void command(action,{id:state.selected}));
  $('browser-address').addEventListener('submit',event=>{
    event.preventDefault();if(!$('browser-go').disabled)void command('navigate',{id:state.selected,url:$('browser-url').value.trim()});
  });
  desktop?.onBrowserState(render);
  desktop?.onBrowserPresentation(value=>{if(value?.visible)present(true);});
  desktop?.onBrowserLayout(schedule);
  if(desktop)void desktop.browserState().then(render).catch(()=>{});
  new MutationObserver(()=>{if(visible)publish();}).observe(document.body,{subtree:true,attributes:true,attributeFilter:['open','hidden','data-sidebar-mode']});
  const layoutObserver=new ResizeObserver(schedule);
  for(const element of [$('browser-body'),document.querySelector('.browser-controls'),document.querySelector('.masthead')])layoutObserver.observe(element);
  window.addEventListener('resize',schedule);
  document.addEventListener('toggle',()=>{if(visible)publish();schedule();},true);
  window.allfoldLayout.subscribe(schedule);
  for(const event of ['settings-saved','quick-open-shown'])window.addEventListener(event,()=>void refreshServices());

  window.workspaceSearch.register('services',{
    label:'Service',
    items:()=>savedServices.services.map(service=>({id:service.id,name:service.name,keywords:service.access_url})),
    select:item=>{
      if(!window.workspaceNavigation.go('login',{instant:true}))return false;
      window.dispatchEvent(new CustomEvent('workflow-service-selected',{detail:{serviceId:item.id}}));
      return true;
    },
  });
  window.workspaceSearch.register('browser-tabs',{
    label:'Browser Tab',
    items:()=>state.tabs.map(page=>({id:page.id,name:page.title || 'New page',detail:page.url})),
    select:item=>selectPage(item.id),
  });
  window.workspaceSearch.registerCommand('browser',{name:'Browser',run:show});
  return {show,showTaskPage,hide:()=>present(false),visible:()=>visible,presentationChanging:()=>visible || returning};
})();
