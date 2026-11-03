'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture({preferences={},tabs=[],services={scope:{scope_id:'scope-a'},services:[]}}={}) {
  const elements=new Map(),frames=[],observers=[],resizers=[],calls=[],storage=new Map(Object.entries(preferences));
  class Element extends EventTarget {
    constructor(id=''){super();this.id=id;this.hidden=false;this.inert=false;this.open=false;this.children=[];this.dataset={};this.attributes={};
      this.style={setProperty:(name,value)=>{this.style[name]=value;}};this.value='';this.isConnected=true;this.disabled=false;}
    setAttribute(name,value){this.attributes[name]=String(value);}
    getAttribute(name){return this.attributes[name];}
    replaceChildren(...children){this.children=children;}
    append(...children){this.children.push(...children);}
    focus(){document.activeElement=this;}
    getBoundingClientRect(){return this.id==='browser-body'?{x:0,y:160,left:0,top:160,width:720,height:600}:{x:0,y:0,left:0,top:0,width:1000,height:600};}
    querySelectorAll(){return [];}
    scrollIntoView(){}
  }
  const document={body:new Element('body'),documentElement:new Element('html'),activeElement:null,
    getElementById:id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);},
    createElement:()=>new Element(),
    querySelector:selector=>selector==='.masthead'?document.getElementById('masthead'):document.getElementById('footer'),
    querySelectorAll:selector=>selector==='dialog[open]'?[...elements.values()].filter(node=>node.open):[]};
  const window=new EventTarget();window.window=window;window.uiNext={notice:message=>calls.push({notice:message}),request:async()=>services};
  let state={selected:null,tabs,taskPageId:null};
  window.allfoldDesktop={browserState:async()=>state,showBrowser:async()=>state,
    browserCommand:async command=>{calls.push(command);if(command.action==='select')state={...state,selected:command.id};return state;},
    setBrowserPresentation:async value=>{calls.push(value);},
    onBrowserState:fn=>{window.receiveState=fn;},onBrowserPresentation:fn=>{window.receivePresentation=fn;},onBrowserLayout:fn=>{window.receiveLayout=fn;}};
  const context=vm.createContext({window,document,Event,URL,Map,Set,console,
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)},
    requestAnimationFrame:fn=>{frames.push(fn);return frames.length;},cancelAnimationFrame(){},
    ResizeObserver:class {constructor(fn){resizers.push(fn);}observe(){}},MutationObserver:class {constructor(fn){observers.push(fn);}observe(){}},
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/workbench.js'),'utf8'),context);
  const flush=()=>{while(frames.length)frames.shift()();};
  return {window,document,calls,storage,flush,resize:()=>{for(const fn of resizers)fn();},mutate:()=>{for(const fn of observers)fn();},setState:value=>{state=value;window.receiveState(value);}};
}
test('Browser presentation preserves business DOM and suspends native content for trusted dialogs',async()=>{
  const f=fixture(),page=f.document.getElementById('selected-view'),input=f.document.createElement('input');
  const reader=f.document.getElementById('paper-detail');reader.scrollTop=230;reader.scrollLeft=0;reader.dataset.paperId='paper-a';
  f.document.getElementById('allfold-pane').querySelectorAll=()=>[reader];
  page.append(input);input.value='unsaved';input.focus();await f.window.allfoldWorkbench.show();f.flush();
  assert.equal(f.document.body.dataset.workbench,'browser');assert.equal(page.children[0].value,'unsaved');
  assert.equal(f.calls.at(-1).visible,true);
  const history=f.document.getElementById('history-dialog');history.open=true;f.mutate();f.flush();
  assert.equal(f.calls.at(-1).suspended,true);
  history.open=false;f.mutate();f.flush();assert.equal(f.calls.at(-1).suspended,false);
  reader.scrollTop=80;f.window.allfoldWorkbench.hide();f.flush();assert.equal(f.calls.at(-1).visible,false);
  assert.equal(reader.scrollTop,230);
  assert.equal(input.value,'unsaved');assert.equal(f.document.activeElement,input);
});
test('task handoff selects its existing active Page and leaves fullscreen flow open for return',async()=>{
  const f=fixture(),flow=f.document.getElementById('kept-flow');flow.open=true;
  const association=(workflow_id,task_id,role,active)=>({workflow_id,task_id,role,active});
  f.setState({selected:4,taskPageId:8,tabs:[
    {id:4,association:null},{id:7,association:association('flow-a','prepare','service-resource',false)},
    {id:8,association:association('flow-a','import','import',true)},
    {id:9,association:association('flow-b','other','popup',true)}]});
  assert.equal(await f.window.allfoldWorkbench.showTaskPage({workflowId:'flow-a'}),true);f.flush();
  assert.equal(f.calls.find(call=>call.action==='select').id,8);
  assert.equal(f.calls.some(call=>call.action==='new'),false);
  assert.equal(flow.open,true);assert.equal(f.calls.at(-1).suspended,false);
  f.window.allfoldWorkbench.hide();f.flush();assert.equal(flow.open,true);
  assert.equal(await f.window.allfoldWorkbench.showTaskPage({workflowId:'missing'}),false);
});
test('tabs and Services expose the same Page IDs, isolate scope and update a reused ImportPage',async()=>{
  const f=fixture({services:{scope:{scope_id:'scope-a'},services:[{id:'service-a',name:'Library',access_method:'manual'}]}});
  await f.window.allfoldWorkbench.show();
  const page=(id,scope,service,role)=>({id,title:'Page '+id,url:'https://unrelated.test/',association:
    role?{role,service_scope:scope?{scope_id:scope}:null,service_id:service}:null});
  f.setState({selected:1,tabs:[page(1,'scope-a','service-a','import'),page(2,'scope-b','service-a','popup'),
    page(3,null,null,'carsi-portal'),page(4,null,null,null)]});
  const groups=f.document.getElementById('browser-service-pages').children;
  assert.equal(groups.length,4);
  assert.deepEqual(groups.map(group=>group.children[1].children.map(row=>Number(row.dataset.pageId))).flat(),[1,2,3,4]);
  assert.match(groups[0].children[0].textContent,/Library/);
  assert.doesNotMatch(groups[1].children[0].textContent,/Library/);
  f.setState({selected:1,tabs:[page(1,'scope-b','service-a','import')]});
  assert.equal(f.document.getElementById('browser-tabs').children[0].dataset.pageId,'1');
  assert.equal(f.document.getElementById('browser-service-pages').children.length,1);
});
test('Services preferences validate saved values and temporary shrinking never overwrites desired width',async()=>{
  const f=fixture({preferences:{'allfold.browser-services-width':'99999','allfold.browser-services-expanded':'wrong'}});
  f.flush();
  const area=f.document.getElementById('browser-work-area');
  assert.equal(area.style['--browser-services-width'],'288px');
  area.getBoundingClientRect=()=>({width:240});f.resize();f.flush();
  assert.equal(area.style['--browser-services-width'],'0px');
  assert.equal(f.storage.get('allfold.browser-services-width'),'99999');
  f.document.getElementById('browser-services-toggle').dispatchEvent(new Event('click'));
  assert.equal(f.storage.get('allfold.browser-services-expanded'),'false');
  assert.equal(f.calls.some(call=>call.action==='new'),false);
});
