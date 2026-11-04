'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function model(){const window={};vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/workspace-layout-model.js'),'utf8'),{window});return window.allfoldLayoutModel;}
test('rails are allocated first; sidebar yields to the content minimum and overlays below its own minimum',()=>{
  const m=model(),targets=m.targets();
  assert.deepEqual({...m.measure(1200,targets,360,true)},{sidebarMode:'docked',sidebarEffectiveWidth:320,contentWidth:784,flyoutEffectiveWidth:280});
  assert.deepEqual({...m.measure(740,targets,360,true)},{sidebarMode:'docked',sidebarEffectiveWidth:284,contentWidth:360,flyoutEffectiveWidth:280});
  assert.deepEqual({...m.measure(715,targets,360,true)},{sidebarMode:'overlay',sidebarEffectiveWidth:320,contentWidth:619,flyoutEffectiveWidth:280});
  assert.equal(m.measure(400,targets,360,true).sidebarEffectiveWidth,304);
  assert.equal(m.measure(1200,targets,360,false).contentWidth,1104);
  assert.equal(m.measure(1200,targets,360,false).sidebarMode,'closed');
  assert.equal(m.measure(1200,targets,360,true).sidebarEffectiveWidth,320);
  assert.equal(targets.sidebarPreferredWidth,320);
});
test('corrupt targets fall back independently and obsolete journal columns/left widths are ignored',()=>{
  const m=model();
  assert.deepEqual({...m.targets({railWidth:0,sidebarPreferredWidth:'400',flyoutPreferredWidth:Infinity})},{railWidth:48,flyoutPreferredWidth:280,sidebarPreferredWidth:320,browserPreferredWidth:960,browserPreferredHeight:300});
  assert.deepEqual({...m.targets({railWidth:60,sidebarPreferredWidth:420,columns:2,left:900})},{railWidth:60,flyoutPreferredWidth:280,sidebarPreferredWidth:420,browserPreferredWidth:960,browserPreferredHeight:300});
  assert.deepEqual({...m.targets(null)},{railWidth:48,flyoutPreferredWidth:280,sidebarPreferredWidth:320,browserPreferredWidth:960,browserPreferredHeight:300});
});
test('Compact Browser targets survive constrained containers without storing effective dimensions',()=>{
  const m=model(),targets=m.targets({browserPreferredWidth:1100,browserPreferredHeight:420});
  assert.deepEqual({...m.browserSize(504,170,targets)},{width:504,height:170});
  assert.deepEqual({...m.browserSize(1600,700,targets)},{width:1100,height:420});
  assert.equal(targets.browserPreferredWidth,1100);assert.equal(targets.browserPreferredHeight,420);
  assert.equal(m.targets({browserPreferredWidth:0,browserPreferredHeight:'240'}).browserPreferredWidth,960);
  assert.equal(m.targets({browserPreferredWidth:0,browserPreferredHeight:'240'}).browserPreferredHeight,300);
});
function fixture(preferences={}) {
  const elements=new Map(),timers=new Map(),observers=[],storage=new Map(Object.entries(preferences)),previews=[];
  let timerId=0,width=1200,current='workspace';
  class Element {
    constructor(id=''){this.id=id;this.dataset={};this.hidden=false;this.isConnected=true;this.disabled=false;this.children=[];this.listeners=new Map();this.attributes={};this.style={setProperty:(k,v)=>this.style[k]=v};this.scrollTop=0;this.scrollLeft=0;}
    addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,[]);this.listeners.get(name).push(fn);}
    emit(name,props={}){const event={target:this,preventDefault(){this.defaultPrevented=true;},stopPropagation(){},...props};for(const fn of this.listeners.get(name)||[])fn(event);return event;}
    setAttribute(name,value){this.attributes[name]=String(value);}
    getAttribute(name){return this.attributes[name];}
    append(...nodes){for(const node of nodes){node.parent=this;this.children.push(node);}}
    contains(node){return this===node || this.children.some(child=>child.contains(node));}
    closest(selector){if(selector==='[hidden]')return this.hidden?this:this.parent?.closest(selector);if(selector==='[data-flyout]')return this.dataset.flyout?this:this.parent?.closest(selector);return null;}
    focus(){if(document.activeElement===this)return;const previous=document.activeElement;document.activeElement=this;this.emit('focusin',{relatedTarget:previous});}
    getBoundingClientRect(){return {width};}
    querySelector(selector){return this.queries?.[selector] || null;}
    querySelectorAll(selector){return this.queries?.[selector] || [];}
    setPointerCapture(){}
  }
  const get=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
  const window=new Element(),document=new Element();document.activeElement=null;document.getElementById=get;
  document.documentElement={classList:{contains:()=>true}};
  window.workspaceNavigation={current:()=>current};
  const context={window,document,localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
    setTimeout:fn=>{timers.set(++timerId,fn);return timerId;},clearTimeout:id=>timers.delete(id),
    ResizeObserver:class{constructor(fn){observers.push(fn);}observe(){}}};
  vm.createContext(context);
  for(const name of ['workspace-layout-model.js','workspace-layout.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui',name),'utf8'),context);
  const root=get('root'),flyout=get('flyout'),sidebar=get('sidebar'),resize=get('resize'),input=get('draft'),reader=get('reader'),main=get('main');flyout.hidden=true;
  const index=get('index');index.dataset.flyout='index';const access=get('access');access.dataset.flyout='access';
  const info=get('info');info.dataset.sidebarView='info';const record=get('record');record.dataset.sidebarView='record';
  const panel=get('panel');panel.dataset.functionalView='info';const other=get('other');other.dataset.functionalView='record';
  sidebar.queries={'[data-functional-view]':[panel,other]};sidebar.append(input,resize,panel,other);main.append(reader);root.append(flyout,sidebar,index,access,info,record,main);
  root.queries={'.navigation-flyout':flyout,'.functional-sidebar':sidebar,'.sidebar-resize':resize,'.workspace-content':main,
    '[data-flyout]':[index,access],'[data-sidebar-view]':[info,record],'[data-sidebar-close]':get('close'),'[data-flyout-close]':get('dismiss')};
  const host=window.allfoldLayout.create({root,workspace:'workspace',minContentWidth:360,preview:key=>previews.push(key)});
  const tick=()=>{const pending=[...timers.values()];timers.clear();for(const fn of pending)fn();};
  return {host,get,window,document,root,flyout,sidebar,resize,index,access,info,record,input,reader,main,previews,storage,tick,
    resizeTo:value=>{width=value;for(const fn of observers)fn();},navigate:page=>{current=page;window.emit('workspace-navigation-state');}};
}
test('hover/focus/touch flyouts preserve content and selection; crossing the boundary cancels delayed dismissal',()=>{
  const f=fixture();f.reader.scrollTop=240;f.input.value='unsaved';
  const before=f.host.geometry.contentWidth;
  f.index.emit('pointerenter',{pointerType:'mouse'});assert.equal(f.flyout.hidden,true);
  f.tick();assert.deepEqual(f.previews,['index']);
  f.index.emit('pointerleave');f.flyout.emit('pointerenter');f.tick();assert.equal(f.flyout.hidden,false);
  f.access.emit('pointerenter',{pointerType:'mouse'});f.tick();assert.deepEqual(f.previews,['index','access']);
  assert.equal(f.host.geometry.contentWidth,before);assert.equal(f.reader.scrollTop,240);assert.equal(f.input.value,'unsaved');
  f.flyout.emit('pointerleave');f.tick();assert.equal(f.flyout.hidden,true);
  f.index.emit('pointerenter',{pointerType:'touch'});f.tick();assert.equal(f.flyout.hidden,true);
  f.index.emit('click');assert.equal(f.flyout.hidden,false);
  f.flyout.focus();f.root.emit('keydown',{key:'Escape',target:f.flyout});assert.equal(f.flyout.hidden,true);assert.equal(f.document.activeElement,f.index);
  f.access.focus();assert.equal(f.flyout.hidden,false);f.host.closeFlyout();assert.equal(f.flyout.hidden,true);
});
test('tools toggle and switch views; resizing and workspace navigation keep drafts, scroll and sidebar state',()=>{
  const f=fixture();f.input.value='draft';f.reader.scrollTop=200;f.input.focus();
  f.info.emit('pointerenter');assert.equal(f.sidebar.hidden,true);
  f.info.emit('click');assert.equal(f.root.dataset.sidebarMode,'docked');
  f.input.focus();f.sidebar.scrollTop=130;
  f.resizeTo(700);assert.equal(f.root.dataset.sidebarMode,'overlay');assert.equal(f.host.geometry.contentWidth,604);
  assert.equal(f.document.activeElement,f.input);assert.equal(f.input.value,'draft');assert.equal(f.sidebar.scrollTop,130);assert.equal(f.reader.scrollTop,200);
  f.navigate('settings');f.navigate('workspace');assert.equal(f.sidebar.hidden,false);assert.equal(f.input.value,'draft');
  f.resizeTo(1200);assert.equal(f.host.geometry.sidebarEffectiveWidth,320);
  f.record.emit('click');assert.equal(f.sidebar.hidden,false);assert.equal(f.root.dataset.sidebarView,'record');assert.equal(f.get('panel').hidden,true);
  f.record.emit('click');assert.equal(f.sidebar.hidden,true);
});
test('SAVE/RESET/ORIGIN save only target sizes and shrinking never changes the baseline',()=>{
  const f=fixture({'allfold.workbench-layout':'{"railWidth":60,"sidebarPreferredWidth":400}','allfold.browser-services-width':'420','inbox-rhine.archive-debug':'{"height":600}'});
  assert.equal(f.get('layout-railWidth').value,60);f.info.emit('click');f.resizeTo(500);
  assert.equal(f.get('layout-sidebarPreferredWidth').value,400);assert.equal(f.host.geometry.sidebarEffectiveWidth,380);
  const input=f.get('layout-sidebarPreferredWidth');input.value='460';input.valueAsNumber=460;input.emit('input');
  f.get('layout-save').emit('click');assert.equal(JSON.parse(f.storage.get('allfold.workbench-layout')).sidebarPreferredWidth,460);
  f.get('layout-origin').emit('click');assert.equal(input.value,320);
  f.get('layout-reset').emit('click');assert.equal(input.value,460);
  f.resizeTo(1200);assert.equal(f.host.geometry.sidebarEffectiveWidth,460);
  assert.equal(f.storage.get('allfold.browser-services-width'),'420');assert.equal(f.storage.get('inbox-rhine.archive-debug'),'{"height":600}');
});
test('invalid storage is safe; only an in-range legacy right width seeds new preferences',()=>{
  for(const raw of ['broken','null','{"sidebarPreferredWidth":1,"railWidth":"60"}']){
    const f=fixture({'allfold.workbench-layout':raw});assert.equal(f.get('layout-sidebarPreferredWidth').value,320);
  }
  const f=fixture({'allfold.journal-layout':'{"right":420,"left":900,"columns":1}'});f.info.emit('click');assert.equal(f.host.geometry.sidebarEffectiveWidth,420);
  assert.equal(f.get('layout-flyoutPreferredWidth').value,280);
});
