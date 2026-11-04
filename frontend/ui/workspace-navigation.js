'use strict';
// Owns top-level presentation only; page controllers retain their business state.
window.workspaceNavigation = (() => {
  const $=id=>document.getElementById(id);
  const roots={workspace:$('selected-view'),run:$('run-page'),journals:$('journals-view'),kept:$('kept-workspace'),settings:$('settings-view')};
  const pages=new Map(),nav=document.querySelector('.view-nav');
  let current='workspace';
  const configuration=page=>['journals','run','settings'].includes(page);
  function allowed(to,options={}) {
    if(!pages.has(to) || $('run-view').open || $('kept-flow').open)return false;
    const context={from:current,to,...options};
    return [...pages.values()].every(page=>page.canNavigate?.(context)!==false) &&
      pages.get(current)?.canLeave?.(context)!==false && pages.get(to).canEnter?.(context)!==false;
  }
  function layout() {
    const buttons=[...nav.querySelectorAll(':scope>button')],inverse=[...nav.querySelectorAll('.nav-inverse>span')];
    buttons.forEach((button,i)=>Object.assign(inverse[i].style,{left:button.offsetLeft+'px',top:button.offsetTop+'px',width:button.offsetWidth+'px'}));
    const button=$(current+'-open'),x=button.offsetLeft,y=button.offsetTop;
    Object.assign($('view-nav-plate').style,{width:button.offsetWidth+'px',transform:`translate(${x}px,${y}px)`});
    nav.querySelector('.nav-inverse').style.transform=`translate(${-x}px,${-y}px)`;
  }
  function present() {
    for(const [name,root]of Object.entries(roots))root.inert=root.hidden=name!==current;
    const config=configuration(current);
    $('configuration-workspace').inert=$('configuration-workspace').hidden=!config;
    $('settings-shell').inert=$('settings-shell').hidden=!config;
    const footer=document.querySelector('footer');
    footer.inert=footer.hidden=false;
    if(config || current==='kept')$('mode-label').textContent=current.toUpperCase();
    if(config)document.body.dataset.settingsOpen='true';else delete document.body.dataset.settingsOpen;
  }
  function refresh() {
    for(const name of Object.keys(roots)){
      const button=$(name+'-open');
      button.disabled=!allowed(name);
      button.setAttribute('aria-current',name===current?'page':'false');
    }
    const search=pages.get(current)?.search?.() ?? (configuration(current)?null:current);
    if(search)workspaceSearch.show(search);else workspaceSearch.hide();
    layout();
    window.dispatchEvent(new Event('workspace-navigation-state'));
  }
  function go(to,options={}) {
    if(!Object.hasOwn(roots,to))return false;
    if(!allowed(to,options))return false;
    if(to===current)return true;
    const context={from:current,to,...options};
    pages.get(current)?.leave?.(context);
    current=to;present();
    pages.get(to).enter?.(context);
    refresh();return true;
  }
  nav.addEventListener('click',event=>{
    const button=event.target.closest('button');
    if(button && !button.disabled)go(button.id.replace('-open',''),{instant:event.detail===0});
  });
  for(const id of ['run-view','kept-flow']){
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
