'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
const idle={phase:'idle',active:false,can_continue:false,can_cancel:false};
function keydown(document,target,key) {
  const event={type:'keydown',target,key,defaultPrevented:false,preventDefault(){this.defaultPrevented=true;}};
  document.dispatchEvent(event);return event;
}
for(const status of ['candidates','kept'])test(`Browser controls leave the hidden ${status} selection and keyboard defaults unchanged`,async()=>{
  const f=await taskUI('kept.js',{page:'workspace',request:async url=>url.includes('/assets/kept/')?{}:idle});
  const journal={key:'journal-2',name:'Second Journal'};
  f.entries.push({paper:{id:'paper-2',title:'Second paper'},journal});
  f.window.inboxKept.data().journals.push(journal);
  await f.window.emit('workspace-data-changed');
  if(status==='kept')await f.get('array-kept').emit('click');
  const selected=()=>f.get('array-index').children.find(row=>row.getAttribute('aria-current')==='true')?.dataset.indexId;
  const first='journal-1',second='journal-2';
  assert.equal(selected(),first);

  // Workbench makes the Allfold ancestor inert while trusted Browser controls remain active.
  f.get('allfold-pane').inert=true;
  for(const id of ['browser-tab','browser-service','browser-open']){
    const event=keydown(f.document,f.get(id),'ArrowDown');
    assert.equal(selected(),first,`${id} must preserve the hidden selection`);
    assert.equal(event.defaultPrevented,false,`${id} must retain its own keyboard behavior`);
  }

  f.get('allfold-pane').inert=false;
  const event=keydown(f.document,f.get('array-index'),'ArrowDown');
  assert.equal(selected(),status==='candidates'?second:first);
  assert.equal(event.defaultPrevented,status==='candidates');
});
