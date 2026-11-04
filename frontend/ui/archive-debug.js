'use strict';
const ARCHIVE_DEBUG_ORIGIN={shelfCapacity:15,paneWidth:null,readerPaneWidth:null,height:null,
  liftEndMs:180,totalDurationMs:600,panelShift:12,
  positions:{count:null,ruler:null,group:null,inspectionHeading:null,inspectionBack:null,inspectionActions:null}};
function archiveDebugState(stored) {
  const result=structuredClone(ARCHIVE_DEBUG_ORIGIN);
  if(!stored || typeof stored!=='object')return result;
  if(Number.isSafeInteger(stored.shelfCapacity) && stored.shelfCapacity>=1)result.shelfCapacity=stored.shelfCapacity;
  for(const name of ['paneWidth','readerPaneWidth','height'])
    if(Number.isFinite(stored[name]) && stored[name]>0)result[name]=stored[name];
  for(const [name,min,max] of [['liftEndMs',50,1000],['totalDurationMs',51,3000],['panelShift',0,80]])
    if(Number.isSafeInteger(stored[name]) && stored[name]>=min && stored[name]<=max)result[name]=stored[name];
  result.totalDurationMs=Math.max(result.totalDurationMs,result.liftEndMs+1);
  for(const name of Object.keys(result.positions)) {
    const p=stored.positions?.[name];
    if(p && Number.isFinite(p.x) && Number.isFinite(p.y))
      result.positions[name]={x:Math.max(0,Math.min(1,p.x)),y:Math.max(0,Math.min(1,p.y))};
  }
  return result;
}
function archiveDebugDimensions(values,width,maxHeight,defaultPane,defaultReader) {
  const pane=value=>Math.max(1,Math.min(Math.max(1,width-1),value));
  return {paneWidth:pane(values.paneWidth??defaultPane),readerPaneWidth:pane(values.readerPaneWidth??defaultReader),
    height:Math.min(values.height??maxHeight,maxHeight)};
}
// 调试参数独立保存在本浏览器，不参与业务配置保存。
const archiveDebug=(()=>{
  const key='inbox-rhine.archive-debug', $=id=>document.getElementById(id);
  const stage=$('selected-view'), toggle=$('debug-resize'), status=$('debug-status');
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  let saved=archiveDebugState(), values, dragging=null;
  let view='none', enabled=false, editable=false;
  try{saved=archiveDebugState(JSON.parse(localStorage.getItem(key)));}catch{status.textContent='本地保存不可用';}
  values=structuredClone(saved);

  const dirty=()=>JSON.stringify(values)!==JSON.stringify(saved);
  function syncStatus(){status.textContent=dirty()?'UNSAVED':'SAVED';}
  function sync(){
    $('debug-shelf-capacity').value=values.shelfCapacity;
    for(const name of ['liftEndMs','totalDurationMs','panelShift'])$(`debug-${name}`).value=values[name];
    $('debug-totalDurationMs').min=values.liftEndMs+1;
    syncStatus();
  }
  function change(controlsOnly=false){
    syncStatus();
    window.dispatchEvent(new Event(controlsOnly?'archive-controls-change':'archive-debug-change'));
  }
  {
    const input=$('debug-shelf-capacity');
    input.addEventListener('input',()=>{
      if(!/^[0-9]+$/.test(input.value) || !Number.isSafeInteger(input.valueAsNumber) || input.valueAsNumber<1)return;
      if(values.shelfCapacity===input.valueAsNumber)return;
      values.shelfCapacity=input.valueAsNumber;change();
    });
    input.addEventListener('change',sync);
  }
  for(const name of ['liftEndMs','totalDurationMs','panelShift']){
    const input=$(`debug-${name}`);
    input.addEventListener('input',()=>{
      if(!enabled || !editable || input.value.trim()==='' || !Number.isSafeInteger(input.valueAsNumber))return;
      const min=name==='liftEndMs'?50:name==='totalDurationMs'?values.liftEndMs+1:0;
      const max=name==='liftEndMs'?1000:name==='totalDurationMs'?3000:80;
      const value=clamp(input.valueAsNumber,min,max);
      if(values[name]===value){sync();return;}
      values[name]=value;
      if(name==='liftEndMs')values.totalDurationMs=Math.max(values.totalDurationMs,value+1);
      sync();change();
    });
    input.addEventListener('change',sync);
    input.addEventListener('blur',sync);
  }
  toggle.addEventListener('change',()=>{stage.classList.toggle('debug-resize',toggle.checked);change();});
  $('debug-save').addEventListener('click',()=>{
    try{localStorage.setItem(key,JSON.stringify(values));saved=structuredClone(values);sync();}
    catch{status.textContent='保存失败';}
  });
  $('debug-reset').addEventListener('click',()=>{values=structuredClone(saved);sync();change();});
  $('debug-origin').addEventListener('click',()=>{values=archiveDebugState();sync();change();});
  function maxHeight(){return Math.max(1,stage.parentElement.clientHeight);}
  const canEdit=()=>toggle.checked && enabled && editable;
  function resizeTo(axis,target){
    if(view==='array')return;
    const name=axis==='x'?(view==='journal'?'readerPaneWidth':'paneWidth'):'height';
    values[name]=clamp(target,1,axis==='x'?Math.max(1,stage.clientWidth-1):maxHeight());
    change();
  }
  function bindDrag(handle,start,move){
    handle.addEventListener('pointerdown',event=>{
      if(event.button!==0 || !canEdit())return;
      event.preventDefault();dragging={handle,pointer:event.pointerId,...start(event)};
      handle.setPointerCapture(event.pointerId);stage.classList.add('debug-dragging');
    });
    handle.addEventListener('pointermove',event=>{
      if(canEdit() && dragging?.handle===handle && dragging.pointer===event.pointerId)move(event,dragging);
    });
    const finish=()=>{dragging=null;stage.classList.remove('debug-dragging');};
    handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
  }
  for(const [id,axis] of [['debug-split','x'],['debug-bottom','y']]){
    const handle=$(id);
    bindDrag(handle,()=>({}),(event)=>{
      const box=stage.getBoundingClientRect();resizeTo(axis,Math.round(axis==='x'?box.right-event.clientX:event.clientY-box.top));
    });
    handle.addEventListener('keydown',event=>{
      if(!canEdit() || (axis==='y' && view==='journal'))return;
      const direction=(axis==='x'?{ArrowLeft:1,ArrowRight:-1}:{ArrowUp:-1,ArrowDown:1})[event.key];
      if(!direction)return;event.preventDefault();
      const panel=document.querySelector(view==='journal'?'#journal-view .review-right':'.file-panel');
      resizeTo(axis,(axis==='x'?panel.offsetWidth:stage.clientHeight)+direction*(event.shiftKey?40:10));
    });
  }
  for(const handle of document.querySelectorAll('.archive-widget-handle')){
    const widget=handle.parentElement,name=handle.dataset.widget;
    const area=()=>widget.closest('.review-left') || document.querySelector('.collection');
    function place(x,y){
      const box=area().getBoundingClientRect(),rect=widget.getBoundingClientRect();
      const maxTop=Math.max(0,box.height-rect.height);
      const left=clamp(x,0,Math.max(0,box.width-rect.width)),top=clamp(y,0,maxTop);
      values.positions[name]={x:(left+rect.width/2)/Math.max(1,box.width),y:(top+rect.height/2)/Math.max(1,box.height)};
      change(true);
    }
    bindDrag(handle,event=>{const rect=widget.getBoundingClientRect();return {dx:event.clientX-rect.left,dy:event.clientY-rect.top};},(event,d)=>{
      const box=area().getBoundingClientRect();place(event.clientX-box.left-d.dx,event.clientY-box.top-d.dy);
    });
    handle.addEventListener('keydown',event=>{
      if(!canEdit())return;
      const delta={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[event.key];
      if(!delta)return;event.preventDefault();event.stopPropagation();
      const step=event.shiftKey?40:10;place(widget.offsetLeft+delta[0]*step,widget.offsetTop+delta[1]*step);
    });
  }
  function layout(defaultPane,defaultReader){
    const width=stage.clientWidth,dimensions=archiveDebugDimensions(values,width,maxHeight(),defaultPane,defaultReader);
    const height=dimensions.height,pane=view==='journal'?dimensions.readerPaneWidth:dimensions.paneWidth;
    stage.style.height=`${height}px`;
    for(const [id,value,max] of [['debug-split',width-pane,width],['debug-bottom',height,maxHeight()]]){
      $(id).setAttribute('aria-valuenow',Math.round(value));$(id).setAttribute('aria-valuemin','1');$(id).setAttribute('aria-valuemax',Math.round(max));
    }
    return dimensions;
  }
  sync();
  new ResizeObserver(()=>{
    document.documentElement.style.setProperty('--prototype-footer',`${document.querySelector('footer').offsetHeight}px`);
    window.dispatchEvent(new Event('archive-debug-change'));
  }).observe(document.querySelector('footer'));
  window.addEventListener('resize',()=>change());
  return {get values(){return values;},layout,setContext(nextView,visible,canAdjust){
    view=nextView;enabled=visible;editable=canAdjust;
    for(const id of ['debug-shelf-capacity','debug-liftEndMs','debug-totalDurationMs','debug-panelShift','debug-reset','debug-origin'])$(id).disabled=!editable;
    stage.dataset.debugView=view;stage.classList.toggle('debug-editable',enabled && editable);
    $('archive-debug').dataset.view=view;
  }};
})();
