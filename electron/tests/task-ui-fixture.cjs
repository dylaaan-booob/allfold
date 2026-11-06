'use strict';
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
class Target {
  constructor(){this.listeners=new Map();}
  addEventListener(name,fn){if(!this.listeners.has(name))this.listeners.set(name,[]);this.listeners.get(name).push(fn);}
  dispatchEvent(event){for(const fn of this.listeners.get(event.type)||[])fn(event);return true;}
  async emit(name,detail){await Promise.all((this.listeners.get(name)||[]).map(fn=>fn({type:name,detail,preventDefault(){}})));await settle();}
}
class Element extends Target {
  constructor(tag='div'){super();this.tagName=tag.toUpperCase();this.children=[];this.dataset={};this.hidden=false;this.inert=false;this.disabled=false;this.open=false;this.textContent='';this.attributes={};this.style={setProperty(){},removeProperty(){}};this.classList={add(){},remove(){},toggle(){}};this.isConnected=true;}
  get textContent(){return this._text+this.children.map(node=>node.textContent).join('');}
  set textContent(value){this._text=String(value);for(const child of this.children)child.parentElement=null;this.children=[];}
  append(...nodes){for(const node of nodes){if(node.parentElement)node.parentElement.children=node.parentElement.children.filter(child=>child!==node);node.parentElement=this;this.children.push(node);}}
  prepend(...nodes){this.append(...nodes);this.children=[...nodes,...this.children.filter(node=>!nodes.includes(node))];}
  replaceChildren(...nodes){for(const node of this.children)node.parentElement=null;this.children=[];this.append(...nodes);}
  setAttribute(name,value){this.attributes[name]=String(value);}
  getAttribute(name){return this.attributes[name];}
  removeAttribute(name){delete this.attributes[name];}
  closest(selector){for(let node=this;node;node=node.parentElement)if(selector.split(',').some(value=>value==='[inert]'?node.inert:value.toUpperCase()===node.tagName))return node;return null;}
  contains(node){return this.children.includes(node);}
  querySelector(selector){return this.children.find(node=>selector.startsWith('.')?node.className===selector.slice(1):node.id===selector.slice(1)) || new Element();}
  querySelectorAll(){return [];}
  show(){this.open=true;}
  close(){const was=this.open;this.open=false;if(was)this.dispatchEvent({type:'close'});}
  focus(){}
  scrollIntoView(){}
}
async function settle(){for(let i=0;i<35;i++)await Promise.resolve();}
async function taskUI(script,{inline=true,request,ready=false,reduced=false,archiveDisabled=false,layout='array',page='run',initialLink=null,bridgeReady=true}={}){
  const elements=new Map(),get=id=>{const find=node=>node.id===id?node:node.children.map(find).find(Boolean);for(const node of elements.values()){const found=find(node);if(found)return found;}if(!elements.has(id)){const node=new Element();node.id=id;elements.set(id,node);}return elements.get(id);};
  get('allfold-pane').append(get('selected-view'));get('selected-view').append(get('kept-view'));
  for(const id of ['array-journal-issn','array-journal-eissn','array-source-stream']){const row=new Element();row.append(get(id));get('array-journal-profile').append(row);}
  get('kept-view').hidden=get('kept-view').inert=layout!=='array';get('kept-view').append(get('array-import-profile'));
  get('selected-view').dataset.workspaceLayout=layout;get('workspace-layout').parentElement=get('array-layout-controls');
  get('s-run').append(Object.assign(new Element(),{className:'s-run-body'}));get('run-view').querySelector=selector=>selector==='.run-status-area'?get('run-status-area'):new Element();get('run-stage-layer').append(get('run-title'));get('run-stage-layer').append(get('run-status-area'));get('run-view').append(get('run-stage-layer'));get('run-status-area').append(get('run-elapsed'),get('run-stage'),get('run-description'),get('run-wos-cancel'));
  get('kept-flow').append(get('kept-flow-actions'));get('kept-flow-actions').append(get('kept-flow-gate'),get('kept-leave'),get('kept-skip-slot'));get('kept-flow-gate').append(get('kept-gate-message'),get('kept-manual-services'),get('kept-continue'));
  const window=new Target(),document=new Target(),timers=new Map(),calls=[],presentations=[];
  document.getElementById=get;document.createElement=tag=>new Element(tag);document.querySelector=()=>null;document.querySelectorAll=()=>[];document.baseURI='http://allfold.test/static/ui_next/';document.activeElement=null;document.hidden=false;
  let nextTimer=1,currentPage=page,prepares=0,refreshes=0,opens=0,visuals=0;
  const entries=[{paper:{id:'paper-1',title:'A synthetic paper'},journal:{key:'journal-1',name:'Test Journal'}}];
  const data={journals:[entries[0].journal],titles:{'paper-1':'A synthetic paper'}};
  window.allfoldUIPreferences={fullscreenDisabled:()=>inline,archiveDisabled:()=>archiveDisabled};window.uiWorkspace={ready:()=>ready,refresh:async()=>{refreshes++;}};
  window.uiRunPage={selectedProviders:()=>['openalex'],providerName:id=>id,open:()=>{opens++;currentPage='run';return true;},report:(...args)=>calls.push(['report',...args]),canRun:()=>true,updateButtons(){},refresh:async()=>{refreshes++;}};
  window.inboxRun={available:()=>true,selection:()=>({}),prepare:async()=>{prepares++;}};
  window.uiNextInitialLink=initialLink;window.inboxKept={available:()=>bridgeReady,busy:()=>false,papers:()=>entries,candidates:()=>entries,data:()=>data,openReader:()=>true,closeReader:()=>true,openArchivePaper:id=>window.workspaceArray?.openPaper(id)||false,setLayout:value=>{get('selected-view').dataset.workspaceLayout=value;get('kept-view').hidden=get('kept-view').inert=value!=='array';return true;},suspend(){},exported(){}};
  window.workspaceNavigation={current:()=>currentPage,go:page=>{currentPage=page;return true;},register(){},refresh(){}};
  window.allfoldWorkbench={showTaskPage:async identity=>{presentations.push(identity);return true;}};
  window.allfoldLayoutModel={minOperationalSize:{array:360}};
  window.allfoldLayout={create:()=>({sync(){},closeFlyout(){}})};
  const uiNext={data:{import_token:'token'},notice:message=>calls.push(['notice',message]),request:async(url,body)=>{calls.push([String(url),body]);return request(String(url),body);}};
  const context={window,document,uiNext,workspaceSearch:{register(){},refresh(){}},URL,Date,Map,Set,Math,Promise,console,
    CustomEvent:class{constructor(type,options){this.type=type;this.detail=options?.detail;}},Event:class{constructor(type){this.type=type;}},
    matchMedia:()=>Object.assign(new Target(),{matches:reduced}),localStorage:{getItem:()=>null,setItem(){}},
    setTimeout:fn=>{const id=nextTimer++;timers.set(id,fn);return id;},clearTimeout:id=>timers.delete(id),setInterval:()=>0,clearInterval(){},
    SurfaceTransition:class{finish(){}},RunVisual:class{constructor(){visuals++;}stop(){}start(){}},KeptPlayer:class{constructor(){visuals++;}stop(){}play(){}draw(){}resize(){}setReduced(){}resume(){}},
    sceneReady:async()=>{},shots:{access:{duration:1},welcome:{holdAt:1}},
  };
  Object.assign(context,await import('../../frontend/ui/run-results.js'),await import('../../frontend/ui/business-results.js'));
  vm.createContext(context);
  const source=fs.readFileSync(path.resolve(__dirname,'../../frontend/ui',script),'utf8').replace(/^import .*;\n/gm,'');
  vm.runInContext(source,context,{filename:script});await settle();
  return {window,document,get,calls,presentations,entries,setInline:value=>{inline=value;},setArchiveDisabled:value=>{archiveDisabled=value;},setBridgeReady:value=>{bridgeReady=value;},setPage:page=>{currentPage=page;},page:()=>currentPage,
    stats:()=>({prepares,refreshes,opens,visuals}),async tick(){const pending=[...timers.values()];timers.clear();for(const fn of pending)fn();await settle();},settle};
}
module.exports={taskUI,settle};
