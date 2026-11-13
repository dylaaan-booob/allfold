'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
test('ARRAY retains Reader selection and identity-only Downloaded and Trash entries without starting Import polling',async()=>{
 const f=await taskUI('kept.js',{page:'workspace',request:async()=>{throw Error('ARRAY has no workflow polling');}});
 const journal={key:'unassigned',name:'Unassigned'};
 f.window.inboxKept.entries=status=>[{paper:{id:status+'-identity',title:null,identity_label:'doi: 10.5555/identity'},journal}];
 await f.get('array-downloaded').emit('click');
 assert.equal(f.get('kept-view').dataset.status,'downloaded');
 assert.equal(f.get('array-index').children[0].textContent,'00doi: 10.5555/identity');
 await f.get('array-trash').emit('click');
 assert.equal(f.get('kept-view').dataset.status,'trash');
 assert.equal(f.get('array-index').children[0].dataset.indexId,'trash-identity');
 await f.tick();assert.equal(f.calls.length,0);
});
test('an unchanged ARRAY Paper update preserves filter, selection and Reader scroll',async()=>{
 const f=await taskUI('kept.js',{page:'workspace',request:async()=>({})});
 f.get('paper-detail').scrollTop=240;
 await f.window.emit('workspace-data-changed');
 assert.equal(f.get('array-index').children[0].dataset.indexId,'journal-1');
 assert.equal(f.get('paper-detail').scrollTop,240);
 assert.equal(f.get('kept-reader').hidden,false);
});
