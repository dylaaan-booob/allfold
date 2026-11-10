'use strict';
// Sources expose current local records and delegate selection to their workspace.
window.workspaceSearch = (() => {
  const $=id=>document.getElementById(id);
  const dialog=$('workspace-search'),input=$('s-search'),results=$('workspace-search-results');
  const sources=new Map(),commands=new Map();
  let active=0,rows=[];
  const normalized=value=>String(value ?? '').normalize('NFKC').toLocaleLowerCase();
  function matches() {
    const value=input.value.trim(),commandMode=value.startsWith('>');
    const terms=normalized(commandMode?value.slice(1).trim():value).split(/\s+/);
    const groups=commandMode?[{label:'Command',items:()=>commands.values(),select:item=>item.run()}]:[...sources.values()];
    return groups.flatMap(source=>{
      const matches=[];
      for(const item of source.items()){
        const text=normalized([item.name,item.detail,item.keywords].filter(Boolean).join(' '));
        if(terms.every(term=>text.includes(term)))matches.push({item,source});
        if(matches.length===8)break;
      }
      return matches;
    });
  }
  function choose(index) {
    const row=rows[index];
    if(!row)return;
    const item=Array.from(row.source.items()).find(item=>item.id===row.item.id);
    if(!item){refresh();return;}
    dialog.close();
    Promise.resolve().then(()=>row.source.select(item)).then(result=>{
      if(result===false)window.uiNext.notice('当前操作进行中，暂时无法打开此结果。');
    }).catch(error=>window.uiNext.notice(error.message));
  }
  function refresh() {
    if(!dialog.open)return;
    rows=matches();
    active=Math.min(active,Math.max(0,rows.length-1));
    results.replaceChildren(...rows.map(({item,source},index)=>{
      const button=document.createElement('button'),title=document.createElement('strong'),detail=document.createElement('small');
      button.type='button';button.tabIndex=-1;button.id='workspace-search-option-'+index;
      button.setAttribute('role','option');button.setAttribute('aria-selected',String(index===active));
      title.textContent=item.name;detail.textContent=item.detail?`${source.label} · ${item.detail}`:source.label;
      button.append(title,detail);button.addEventListener('pointerdown',event=>event.preventDefault());
      button.addEventListener('click',()=>choose(index));return button;
    }));
    $('workspace-search-empty').hidden=Boolean(rows.length);
    input.setAttribute('aria-expanded',String(Boolean(rows.length)));
    if(rows.length){
      input.setAttribute('aria-activedescendant',results.children[active].id);
      results.children[active].scrollIntoView({block:'nearest'});
    }else input.removeAttribute('aria-activedescendant');
  }
  function open() {
    if(dialog.open)return;
    if(document.querySelector('dialog[open]:modal'))return;
    input.value='';active=0;
    dialog.showModal();refresh();
    window.dispatchEvent(new Event('quick-open-shown'));
  }
  input.addEventListener('input',()=>{active=0;refresh();});
  input.addEventListener('keydown',event=>{
    const count=results.children.length;if(!count || !['Enter','ArrowDown','ArrowUp'].includes(event.key))return;
    event.preventDefault();
    if(event.key==='Enter')choose(active);
    else {active=(active+(event.key==='ArrowDown'?1:-1)+count)%count;refresh();}
  });
  $('search-open').addEventListener('click',open);
  $('search-close').addEventListener('click',()=>dialog.close());
  document.addEventListener('keydown',event=>{
    if(event.defaultPrevented || !(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey || event.key.toLowerCase()!=='k')return;
    event.preventDefault();open();
  });
  return {
    register(name,source){sources.set(name,source);refresh();},
    registerCommand(name,command){commands.set(name,{...command,id:name});refresh();},
    refresh,
  };
})();
