'use strict';
// Presentation only. Workspace Controllers own selections, drafts and Reader lifecycle.
window.allfoldLayout=(()=>{
  const model=window.allfoldLayoutModel,$=id=>document.getElementById(id),key='allfold.workbench-layout';
  const hosts=new Set(),subscribers=new Set();let active=null,saved=model.targets(),values,storageError='';
  try {
    const raw=localStorage.getItem(key);
    if(raw!==null)saved=model.targets(JSON.parse(raw));
  }catch {storageError='本地保存不可用';}
  values={...saved};
  function debug() {
    const panel=$('layout-debug');
    panel.hidden=!document.documentElement.classList.contains('developer-mode');
    for(const name of Object.keys(model.defaults)){
      const input=$('layout-'+name);if(document.activeElement!==input)input.value=values[name];
    }
    for(const name of ['sidebarEffectiveWidth','contentWidth','sidebarMode'])
      $('layout-'+name).textContent=active?.geometry?.[name]??'—';
    $('layout-status').textContent=storageError || (JSON.stringify(values)===JSON.stringify(saved)?'SAVED':'UNSAVED');
  }
  function notify() {for(const callback of subscribers)callback();}
  function sync() {for(const host of hosts)host.sync();debug();notify();}
  function persist(next) {
    try {localStorage.setItem(key,JSON.stringify(next));saved={...next};storageError='';}
    catch {storageError='保存失败';}
    debug();
  }
  function target(name,value) {
    const [min,max]=model.limits[name];
    if(!Number.isFinite(value) || value<min || value>max)return;
    values[name]=Math.round(value);storageError='';sync();
  }
  function create({root,workspace,minContentWidth,preview=()=>{},visible=()=>window.workspaceNavigation.current()===workspace}) {
    const flyout=root.querySelector('.navigation-flyout'),sidebar=root.querySelector('.functional-sidebar');
    const resize=root.querySelector('.sidebar-resize');
    const triggers=[...root.querySelectorAll('[data-flyout]')],tools=[...root.querySelectorAll('[data-sidebar-view]')];
    const flyoutScroll=new Map();
    let expanded=false,view=tools[0]?.dataset.sidebarView,flyoutKey=null,trigger=null,openTimer=null,closeTimer=null,drag=null,restoringFocus=false,changingPreview=false;
    const shown=()=>!root.closest('[hidden]') && !root.closest('[inert]') && visible();
    const focusable='button:not(:disabled):not([hidden]),summary,[tabindex="0"]';
    const flyoutItems=()=>[...(flyout.querySelector('[data-flyout-list]')?.querySelectorAll(focusable) || [])]
      .filter(node=>!node.closest('[hidden]') && (node.tagName==='SUMMARY' || !node.closest('details:not([open])')));
    const cancelTimers=()=>{clearTimeout(openTimer);clearTimeout(closeTimer);};
    function saveFlyoutScroll() {
      const list=flyout.querySelector('[data-flyout-list]');
      if(!flyout.hidden && !root.closest('[hidden]') && flyoutKey!==null && list)flyoutScroll.set(flyoutKey,{top:list.scrollTop,left:list.scrollLeft});
    }
    function closeFlyout({restoreFocus=true}={}) {
      cancelTimers();if(flyout.hidden)return;
      saveFlyoutScroll();
      flyout.hidden=true;flyoutKey=null;
      for(const button of triggers)button.setAttribute('aria-expanded','false');
      if(restoreFocus && trigger?.isConnected && !trigger.disabled){restoringFocus=true;trigger.focus({preventScroll:true});restoringFocus=false;}
      notify();
    }
    function openFlyout(button) {
      cancelTimers();if(button.disabled || !shown())return;
      trigger=button;
      const next=button.dataset.flyout;
      if(next!==flyoutKey){
        const focused=flyout.contains(document.activeElement);
        saveFlyoutScroll();flyout.hidden=false;changingPreview=true;
        try{preview(next);}finally{changingPreview=false;}
        flyoutKey=next;
        const list=flyout.querySelector('[data-flyout-list]'),position=flyoutScroll.get(next);
        if(list){list.scrollTop=position?.top || 0;list.scrollLeft=position?.left || 0;}
        if(focused && !flyout.contains(document.activeElement))flyout.focus({preventScroll:true});
      }else flyout.hidden=false;
      for(const entry of triggers)entry.setAttribute('aria-expanded',String(entry===button));
      notify();
    }
    function focusTool() {tools.find(button=>button.dataset.sidebarView===view)?.focus({preventScroll:true});}
    function closeSidebar() {
      if(sidebar?.contains(document.activeElement))focusTool();
      expanded=false;host.sync();
    }
    function openSidebar(next=view) {
      if(!tools.some(button=>button.dataset.sidebarView===next))return;
      view=next;expanded=true;host.sync();
    }
    const host={geometry:null,sync(){
      if(!shown()){closeFlyout({restoreFocus:false});if(active===host)active=null;return;}
      const width=root.getBoundingClientRect().width;if(!width)return;
      active=host;host.geometry=model.measure(width,values,minContentWidth,expanded);
      const g=host.geometry;root.dataset.sidebarMode=g.sidebarMode;root.dataset.sidebarView=view;
      root.style.setProperty('--rail-width',values.railWidth+'px');
      root.style.setProperty('--sidebar-width',g.sidebarEffectiveWidth+'px');
      root.style.setProperty('--flyout-width',g.flyoutEffectiveWidth+'px');
      if(sidebar)sidebar.hidden=!expanded;
      for(const panel of sidebar?.querySelectorAll('[data-functional-view]') || [])panel.hidden=panel.dataset.functionalView!==view;
      for(const button of tools){
        button.setAttribute('aria-expanded',String(expanded && button.dataset.sidebarView===view));
        button.setAttribute('aria-pressed',String(expanded && button.dataset.sidebarView===view));
      }
      resize?.setAttribute('aria-valuenow',String(values.sidebarPreferredWidth));debug();notify();
    },openSidebar,closeSidebar,closeFlyout};
    for(const button of triggers){
      button.setAttribute('aria-controls',flyout.id);button.setAttribute('aria-expanded','false');
      button.addEventListener('pointerenter',event=>{
        if(event.pointerType==='touch')return;
        cancelTimers();openTimer=setTimeout(()=>openFlyout(button),160);
      });
      button.addEventListener('pointerleave',()=>{cancelTimers();closeTimer=setTimeout(()=>closeFlyout({restoreFocus:flyout.contains(document.activeElement)}),280);});
      button.addEventListener('focusin',()=>{if(!restoringFocus)openFlyout(button);});
      button.addEventListener('click',()=>openFlyout(button));
      button.addEventListener('dragenter',()=>{cancelTimers();openTimer=setTimeout(()=>openFlyout(button),160);});
      button.addEventListener('dragover',event=>{event.preventDefault();clearTimeout(closeTimer);});
      button.addEventListener('dragleave',()=>{cancelTimers();closeTimer=setTimeout(()=>closeFlyout({restoreFocus:false}),280);});
      button.addEventListener('keydown',event=>{
        if(!['ArrowRight','ArrowDown'].includes(event.key))return;
        event.preventDefault();event.stopPropagation();openFlyout(button);
        (flyoutItems()[0] || flyout).focus({preventScroll:true});
      });
    }
    flyout.addEventListener('pointerenter',cancelTimers);
    flyout.addEventListener('pointerleave',()=>{cancelTimers();closeTimer=setTimeout(()=>closeFlyout({restoreFocus:flyout.contains(document.activeElement)}),280);});
    flyout.addEventListener('dragenter',cancelTimers);flyout.addEventListener('dragover',cancelTimers);
    flyout.addEventListener('dragleave',event=>{if(!flyout.contains(event.relatedTarget)){cancelTimers();closeTimer=setTimeout(()=>closeFlyout({restoreFocus:false}),280);}});
    for(const event of ['drop','dragend'])document.addEventListener(event,()=>closeFlyout({restoreFocus:false}));
    flyout.addEventListener('keydown',event=>{
      if(!['ArrowUp','ArrowDown'].includes(event.key))return;
      const list=flyout.querySelector('[data-flyout-list]');if(!list?.contains(event.target))return;
      const rows=flyoutItems();if(!rows.length)return;
      event.preventDefault();event.stopPropagation();
      const index=rows.indexOf(document.activeElement),delta=event.key==='ArrowDown'?1:-1;
      const next=rows[(index+delta+rows.length)%rows.length];next.focus({preventScroll:true});next.scrollIntoView({block:'nearest'});
    });
    root.addEventListener('focusout',event=>{
      if(!changingPreview && !flyout.hidden && !flyout.contains(event.relatedTarget) && !triggers.includes(event.relatedTarget))closeFlyout({restoreFocus:false});
    });
    document.addEventListener('pointerdown',event=>{
      if(!flyout.hidden && !flyout.contains(event.target) && !triggers.includes(event.target.closest('[data-flyout]')))closeFlyout({restoreFocus:false});
    });
    root.addEventListener('keydown',event=>{
      if(event.key!=='Escape' || event.defaultPrevented)return;
      if(!flyout.hidden){event.preventDefault();event.stopPropagation();closeFlyout();}
      else if(expanded && sidebar.contains(event.target)){event.preventDefault();event.stopPropagation();closeSidebar();}
    });
    for(const button of tools)button.addEventListener('click',()=>{
      if(expanded && view===button.dataset.sidebarView)closeSidebar();else openSidebar(button.dataset.sidebarView);
    });
    root.querySelector('[data-sidebar-close]')?.addEventListener('click',closeSidebar);
    root.querySelector('[data-flyout-close]').addEventListener('click',()=>closeFlyout());
    resize?.setAttribute('aria-valuemin',model.limits.sidebarPreferredWidth[0]);
    resize?.setAttribute('aria-valuemax',model.limits.sidebarPreferredWidth[1]);
    resize?.addEventListener('pointerdown',event=>{
      if(event.button!==0)return;event.preventDefault();
      drag={pointer:event.pointerId,x:event.clientX,width:host.geometry.sidebarEffectiveWidth};
      resize.setPointerCapture(event.pointerId);
    });
    resize?.addEventListener('pointermove',event=>{
      if(!drag || drag.pointer!==event.pointerId)return;
      const [min,max]=model.limits.sidebarPreferredWidth;
      target('sidebarPreferredWidth',Math.max(min,Math.min(max,drag.width+drag.x-event.clientX)));
    });
    function finish() {if(!drag)return;drag=null;persist({...saved,sidebarPreferredWidth:values.sidebarPreferredWidth});}
    for(const event of ['pointerup','pointercancel','lostpointercapture'])resize?.addEventListener(event,finish);
    resize?.addEventListener('keydown',event=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
      event.preventDefault();event.stopPropagation();const [min,max]=model.limits.sidebarPreferredWidth;
      target('sidebarPreferredWidth',event.key==='Home'?min:event.key==='End'?max:
        Math.max(min,Math.min(max,values.sidebarPreferredWidth+(event.key==='ArrowLeft'?20:-20))));
      persist({...saved,sidebarPreferredWidth:values.sidebarPreferredWidth});
    });
    new ResizeObserver(()=>host.sync()).observe(root);hosts.add(host);host.sync();return host;
  }
  for(const name of Object.keys(model.defaults)){
    const input=$('layout-'+name),[min,max]=model.limits[name];input.min=min;input.max=max;
    input.addEventListener('input',()=>{if(input.value.trim())target(name,input.valueAsNumber);});
    input.addEventListener('change',()=>{input.value=values[name];});
  }
  $('layout-save').addEventListener('click',()=>persist(values));
  $('layout-reset').addEventListener('click',()=>{values={...saved};storageError='';sync();});
  $('layout-origin').addEventListener('click',()=>{values=model.targets();storageError='';sync();});
  for(const event of ['workspace-navigation-state','developer-mode-change'])window.addEventListener(event,sync);
  debug();return Object.freeze({create,targets:()=>({...values}),subscribe(callback){subscribers.add(callback);return ()=>subscribers.delete(callback);}});
})();
