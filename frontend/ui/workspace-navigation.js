'use strict';
// Owns top-level presentation only; page controllers retain their business state.
window.workspaceNavigation = (() => {
  const $=id=>document.getElementById(id);
  const roots={workspace:$('selected-view'),login:$('login-page'),run:$('run-page'),journals:$('journals-view'),kept:$('kept-workspace'),settings:$('settings-view')};
  const pages=new Map([['login',{}]]),nav=document.querySelector('.view-nav'),workflowNav=$('workflow-nav');
  const isWorkflow=page=>['login','run','kept'].includes(page);
  const primary=page=>isWorkflow(page)?'workflows':page;
  let current='workspace',workflow='login';
  const configuration=page=>['journals','run','settings'].includes(page);
  function allowed(to,options={}) {
    if(!pages.has(to) || $('run-view').open || $('kept-confirm').open)return false;
    const context={from:current,to,...options};
    return [...pages.values()].every(page=>page.canNavigate?.(context)!==false) &&
      pages.get(current)?.canLeave?.(context)!==false && pages.get(to).canEnter?.(context)!==false;
  }
  function layout() {
    const buttons=[...nav.querySelectorAll(':scope>button')],inverse=[...nav.querySelectorAll('.nav-inverse>span')];
    buttons.forEach((button,i)=>Object.assign(inverse[i].style,{left:button.offsetLeft+'px',top:button.offsetTop+'px',width:button.offsetWidth+'px'}));
    const button=$(primary(current)+'-open'),x=button.offsetLeft,y=button.offsetTop;
    Object.assign($('view-nav-plate').style,{width:button.offsetWidth+'px',transform:`translate(${x}px,${y}px)`});
    nav.querySelector('.nav-inverse').style.transform=`translate(${-x}px,${-y}px)`;
  }
  function present() {
    for(const [name,root]of Object.entries(roots))root.inert=root.hidden=name!==current;
    const config=configuration(current);
    $('configuration-workspace').inert=$('configuration-workspace').hidden=!config;
    $('settings-shell').inert=$('settings-shell').hidden=!config;
    workflowNav.hidden=!isWorkflow(current);
    const footer=document.querySelector('footer');
    footer.inert=footer.hidden=false;
    if(config || isWorkflow(current))$('mode-label').textContent=({run:'DISCOVER',kept:'IMPORT TO ZOTERO'})[current] || current.toUpperCase();
    if(config)document.body.dataset.settingsOpen='true';else delete document.body.dataset.settingsOpen;
  }
  function refresh() {
    for(const button of nav.querySelectorAll(':scope>button')){
      const name=button.id.replace('-open','');
      button.disabled=!allowed(name==='workflows'?workflow:name);
      button.setAttribute('aria-current',name===primary(current)?'page':'false');
    }
    for(const button of workflowNav.querySelectorAll('button')){
      button.disabled=!allowed(button.dataset.workflow);
      button.setAttribute('aria-current',button.dataset.workflow===current?'page':'false');
    }
    layout();
    window.dispatchEvent(new Event('workspace-navigation-state'));
  }
  function go(to,options={}) {
    if(to==='workflows')to=workflow;
    if(!Object.hasOwn(roots,to) || !allowed(to,options))return false;
    if(window.allfoldWorkbench?.visible())window.allfoldWorkbench.hide();
    if(to===current)return true;
    const context={from:current,to,...options};
    pages.get(current)?.leave?.(context);
    current=to;if(isWorkflow(to))workflow=to;
    present();
    pages.get(to).enter?.(context);
    refresh();return true;
  }
  nav.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(button && !button.disabled)go(button.id.replace('-open',''),{instant:event.detail===0});
  });
  workflowNav.addEventListener('click',event=>{
    const button=event.target.closest('[data-workflow]');
    if(button && !button.disabled)go(button.dataset.workflow,{instant:event.detail===0});
  });
  for(const [id,name] of [['workspace-open','Workspace'],['journals-open','Journals'],['settings-open','Settings']]){
    workspaceSearch.registerCommand(id,{name,run:()=>go(id.replace('-open',''),{instant:true})});
  }
  for(const button of workflowNav.querySelectorAll('button')){
    const page=button.dataset.workflow;
    workspaceSearch.registerCommand(page,{name:button.textContent,run:()=>go(page,{instant:true})});
  }
  for(const id of ['run-view','kept-confirm']){
    const dialog=$(id);
    new MutationObserver(refresh).observe(dialog,{attributes:true,attributeFilter:['open']});
    dialog.addEventListener('close',refresh);
  }
  document.fonts.ready.then(layout);
  new ResizeObserver(()=>{
    document.documentElement.style.setProperty('--prototype-header',document.querySelector('.masthead').getBoundingClientRect().height+'px');
    layout();
  }).observe(document.querySelector('.masthead'));
  present();refresh();
  return {
    register(name,page){pages.set(name,page);refresh();},
    go,current:()=>current,refresh,
  };
})();
