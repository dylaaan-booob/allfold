// Browser-local layout: the saved Context width is shared and fixed; only the Journal index is resizable.
const origin={left:null,right:null,columns:0};
function journalLayoutState(stored) {
  const values={...origin};
  for(const side of ['left','right'])if(Number.isFinite(stored?.[side]) && stored[side]>0)values[side]=stored[side];
  if(Number.isSafeInteger(stored?.columns) && stored.columns>=0 && stored.columns<=12)values.columns=stored.columns;
  return values;
}
export function createJournalLayout(context) {
  const $=id=>document.getElementById(id),stage=$('s-journals-page'),toggle=$('s-journal-resize');
  const input=$('s-journal-columns'),status=$('s-journal-layout-status'),key='allfold.journal-layout';
  const handle=$('s-journal-resize-left');
  let saved={...origin},values,drag=null,geometry=null;
  try{saved=journalLayoutState(JSON.parse(localStorage.getItem(key)));}catch{}
  values={...saved};
  const fixedRight=saved.right;
  if(fixedRight)document.documentElement.style.setProperty('--workspace-context',
    `min(${fixedRight}px, max(0px, calc(100vw - 2 * var(--workspace-gutter) - var(--workspace-index) - 240px - 2 * var(--workspace-gap))))`);
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const editable=()=>{const state=context();return state.visible && state.editable;};
  const canResize=()=>editable() && toggle.checked && innerWidth>600;
  function finish() {
    const current=drag;drag=null;stage.classList.remove('debug-dragging');
    if(current && handle.hasPointerCapture(current.pointer))handle.releasePointerCapture(current.pointer);
  }
  function layout() {
    if(!stage.clientWidth)return;
    const defaults=getComputedStyle(document.documentElement),gap=parseFloat(getComputedStyle(stage).columnGap) || 0;
    const width=stage.clientWidth,folded=innerWidth<=1000;
    const right=folded?0:stage.querySelector('.s-context').getBoundingClientRect().width;
    const max=Math.max(212,Math.floor(width-right-240-gap*(folded?1:2)));
    const left=clamp(values.left??parseFloat(defaults.getPropertyValue('--workspace-index')),212,max);
    geometry={left,max};
    stage.style.setProperty('--workspace-index',`${left}px`);
    handle.setAttribute('aria-valuemin','212');
    handle.setAttribute('aria-valuemax',max);
    handle.setAttribute('aria-valuenow',Math.round(left));
  }
  function sync() {
    const state=context(),allowed=editable();
    input.value=values.columns;input.disabled=!allowed || !state.grid;
    toggle.disabled=!allowed || innerWidth<=600;
    for(const action of ['save','reset','origin'])$('s-journal-layout-'+action).disabled=!allowed;
    stage.dataset.journalResize=String(allowed && toggle.checked);
    handle.hidden=!canResize();
    if(drag && !canResize())finish();
    const grid=$('s-journals');
    if(values.columns){grid.dataset.columns=String(values.columns);grid.style.setProperty('--journal-grid-columns',values.columns);}
    else{delete grid.dataset.columns;grid.style.removeProperty('--journal-grid-columns');}
    status.textContent=JSON.stringify(values)===JSON.stringify(saved)?'SAVED':'UNSAVED';
    layout();
  }
  function setWidth(target) {
    if(!canResize() || !geometry)return;
    values.left=clamp(Math.round(target),212,geometry.max);
    sync();
  }
  handle.addEventListener('pointerdown',event=>{
    if(event.button!==0 || !canResize())return;
    event.preventDefault();finish();layout();
    drag={pointer:event.pointerId,x:event.clientX,width:geometry.left};
    handle.setPointerCapture(event.pointerId);stage.classList.add('debug-dragging');
  });
  handle.addEventListener('pointermove',event=>{
    if(drag?.pointer!==event.pointerId || !canResize())return;
    setWidth(drag.width+event.clientX-drag.x);
  });
  const end=event=>{if(drag?.pointer===event.pointerId)finish();};
  handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);handle.addEventListener('lostpointercapture',end);
  handle.addEventListener('keydown',event=>{
    if(!canResize() || !['ArrowLeft','ArrowRight'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();layout();
    setWidth(geometry.left+(event.key==='ArrowRight'?1:-1)*(event.shiftKey?40:10));
  });
  toggle.addEventListener('change',sync);
  input.addEventListener('input',()=>{
    if(!editable() || !context().grid || !/^\d+$/.test(input.value) || !Number.isSafeInteger(input.valueAsNumber) || input.valueAsNumber>12)return;
    values.columns=input.valueAsNumber;sync();
  });
  input.addEventListener('change',sync);input.addEventListener('blur',sync);
  $('s-journal-layout-save').addEventListener('click',()=>{
    if(!editable())return;
    try{localStorage.setItem(key,JSON.stringify(values));saved={...values};sync();}
    catch{status.textContent='保存失败';}
  });
  for(const action of ['reset','origin'])$('s-journal-layout-'+action).addEventListener('click',()=>{
    if(!editable())return;
    finish();values={...(action==='reset'?saved:origin),right:fixedRight};sync();
  });
  for(const event of ['workspace-navigation-state','developer-mode-change','resize'])window.addEventListener(event,sync);
  new ResizeObserver(layout).observe(stage);
  sync();
  return {sync};
}
