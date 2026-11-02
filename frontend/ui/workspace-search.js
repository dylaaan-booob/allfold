'use strict';
// One native search field, with each page owning its existing selection/filter.
window.workspaceSearch = (() => {
  const root=document.getElementById('workspace-search'),input=document.getElementById('s-search');
  const results=document.getElementById('workspace-search-results'),sources=new Map(),queries=new Map();
  const headerHost=root.parentElement;
  let key=null,opened=false,active=0;
  const source=()=>sources.get(key);
  const query=()=>source()?.value?.() ?? queries.get(key) ?? '';
  function close() {opened=false;results.hidden=true;input.setAttribute('aria-expanded','false');input.removeAttribute('aria-activedescendant');}
  function matches() {
    const q=input.value.trim().toLocaleLowerCase();
    return q ? (source()?.items?.() || []).filter(item=>item.name.toLocaleLowerCase().includes(q)) : [];
  }
  function choose(id) {
    if(input.disabled)return;
    // Resolve against current data, not an old result index after a Paper write.
    const item=source()?.items?.().find(item=>item.id===id);
    close();if(item)source().select(item);
  }
  function draw() {
    if(!opened || input.disabled || !input.value.trim() || !source()?.items){close();return;}
    const items=matches();active=Math.min(active,Math.max(0,items.length-1));
    results.replaceChildren();results.hidden=false;input.setAttribute('aria-expanded','true');
    if(!items.length){const empty=document.createElement('p');empty.textContent=source()?.emptyMessage || '没有匹配的期刊';results.append(empty);input.removeAttribute('aria-activedescendant');return;}
    items.forEach((item,i)=>{
      const button=document.createElement('button');button.type='button';button.tabIndex=-1;
      button.id=`workspace-search-option-${i}`;button.setAttribute('role','option');button.setAttribute('aria-selected',String(i===active));
      const title=document.createElement('strong'),detail=document.createElement('small');title.textContent=item.name;detail.textContent=item.detail || '';
      button.append(title,detail);button.title=item.name;
      button.addEventListener('pointerdown',event=>event.preventDefault());
      button.addEventListener('click',()=>choose(item.id));results.append(button);
    });
    input.setAttribute('aria-activedescendant',`workspace-search-option-${active}`);
    results.children[active]?.scrollIntoView({block:'nearest'});
  }
  function refresh() {
    const s=source();root.hidden=!s;if(!s){close();return;}
    const host=s.host || headerHost;
    if(root.parentElement!==host)host.append(root);
    input.disabled=Boolean(s.disabled?.());input.placeholder=s.label;input.setAttribute('aria-label',s.label);
    input.setAttribute('role',s.items?'combobox':'searchbox');
    input.value=query();if(s.items)input.setAttribute('aria-controls',results.id);else input.removeAttribute('aria-controls');
    if(opened)draw();
  }
  function edit() {
    if(input.disabled || !source())return;
    queries.set(key,input.value);source().input?.(input.value);active=0;opened=Boolean(source().items);draw();
  }
  input.addEventListener('input',edit);
  input.addEventListener('focus',()=>{opened=Boolean(source()?.items && input.value.trim());draw();});
  input.addEventListener('keydown',event=>{
    if(input.disabled)return;
    if(event.key==='Escape'){
      if(opened)close();else {input.value='';edit();}
      event.preventDefault();event.stopPropagation();
    } else if(source()?.items && ['ArrowDown','ArrowUp','Enter'].includes(event.key)) {
      const items=matches();if(!items.length)return;
      if(event.key==='Enter')choose(items[Math.min(active,items.length-1)].id);
      else {active=opened?(active+(event.key==='ArrowDown'?1:-1)+items.length)%items.length:0;opened=true;draw();}
      event.preventDefault();
    }
  });
  root.addEventListener('focusout',event=>{if(!root.contains(event.relatedTarget))close();});
  document.addEventListener('pointerdown',event=>{if(!root.contains(event.target))close();});
  return {
    register(name,adapter){sources.set(name,adapter);if(key===name)refresh();},
    show(name){if(key!==name){close();key=name;}refresh();},
    hide(){key=null;root.hidden=true;close();},
    refresh,
  };
})();
