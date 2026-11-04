'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');

function preferences(saved={},storageError=false) {
  const storage=new Map(Object.entries(saved)),events=[];
  const window={dispatchEvent:event=>events.push(event)};
  const context=vm.createContext({window,CustomEvent:class {constructor(type,options){this.type=type;this.detail=options.detail;}},
    localStorage:{getItem:key=>storage.get(key)??null,setItem(key,value){if(storageError)throw Error('Storage unavailable');storage.set(key,value);}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../frontend/ui/ui-preferences.js'),'utf8'),context);
  return {api:window.allfoldUIPreferences,storage,events};
}

test('fresh UI defaults to Array and fullscreen tasks independently of the old animation setting',()=>{
  for(const oldValue of ['true','false']){
    const {api}=preferences({'allfold.run-animation-disabled':oldValue});
    assert.equal(api.archiveDisabled(),true);
    assert.equal(api.fullscreenDisabled(),false);
  }
});

test('local UI preferences persist independently and announce only the changed preference',()=>{
  const {api,storage,events}=preferences();
  api.setArchiveDisabled(false);
  api.setFullscreenDisabled(true);
  api.setFullscreenDisabled(true);
  assert.equal(api.archiveDisabled(),false);
  assert.equal(api.fullscreenDisabled(),true);
  assert.deepEqual(events.map(event=>({type:event.type,...event.detail})),[
    {type:'ui-preferences-changed',name:'archiveDisabled',value:false},
    {type:'ui-preferences-changed',name:'fullscreenDisabled',value:true},
  ]);
  const reopened=preferences(Object.fromEntries(storage)).api;
  assert.equal(reopened.archiveDisabled(),false);
  assert.equal(reopened.fullscreenDisabled(),true);
});

test('invalid local values fall back to defaults and rejected writes keep a usable session preference',()=>{
  const {api,events}=preferences({'allfold.ui.archive-disabled':'0','allfold.ui.fullscreen-disabled':'yes'},true);
  assert.equal(api.archiveDisabled(),true);
  assert.equal(api.fullscreenDisabled(),false);
  assert.throws(()=>api.setArchiveDisabled(false),/Storage unavailable/);
  assert.equal(api.archiveDisabled(),false);
  assert.equal(events[0].detail.value,false);
  assert.throws(()=>api.setFullscreenDisabled('true'),/boolean/);
  assert.equal(api.fullscreenDisabled(),false);
});
