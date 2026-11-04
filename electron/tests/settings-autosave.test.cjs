'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../frontend/ui/settings-autosave.js'),'utf8');
const load=()=>import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
test('late autosave response preserves subsequent input and flush persists its newer value',async()=>{
  const {createAutosave}=await load(),requests=[],applied=[];
  let resolve;
  const autosave=createAutosave({write:body=>{requests.push(body);return new Promise(done=>{resolve=done;});},onSaved:(data,values)=>applied.push(values),delay:100000});
  autosave.initialize({base:{revision:'a'},values:{name:'Initial',log:'INFO'}});
  autosave.edit({name:'First',log:'INFO'});
  const first=autosave.flush();await Promise.resolve();
  autosave.edit({name:'Second',log:'DEBUG'});
  resolve({saved:true,base:{revision:'b'},values:{name:'First',log:'INFO'}});
  await new Promise(done=>setImmediate(done));
  assert.equal(applied[0].name,'Second');assert.equal(applied[0].log,'DEBUG');
  assert.deepEqual(requests[1],{base:{revision:'b'},changes:{name:'Second',log:'DEBUG'}});
  resolve({saved:true,base:{revision:'c'},values:{name:'Second',log:'DEBUG'}});
  assert.equal(await first,true);assert.equal(autosave.status,'Saved');assert.equal(autosave.dirty,false);
  autosave.dispose();
});
test('active-task rejection stays Pending and restored draft survives a new saved revision',async()=>{
  const {createAutosave}=await load(),store=new Map(),storage={getItem:key=>store.get(key)||null,setItem:(key,value)=>store.set(key,value),removeItem:key=>store.delete(key)};
  const first=createAutosave({write:async()=>({saved:false,outcome:'TASK_ACTIVE'}),storage,key:'config-a',delay:100000,retryDelay:100000});
  first.initialize({base:{revision:'a'},values:{name:'Initial'}});first.edit({name:'After task'});
  assert.equal(await first.flush(),false);assert.equal(first.status,'Pending');assert.equal(first.dirty,true);first.dispose();
  let restored;
  const reopened=createAutosave({write:async()=>({saved:true,base:{revision:'c'},values:{name:'After task'}}),storage,key:'config-a',onRestore:values=>{restored=values;},delay:100000});
  reopened.initialize({base:{revision:'b'},values:{name:'Changed elsewhere'}});
  assert.equal(restored.name,'After task');assert.equal(reopened.status,'Conflict');assert.equal(await reopened.flush(),false);
  reopened.rebase({base:{revision:'b'},values:{name:'Changed elsewhere'}});
  assert.equal(await reopened.flush(),true);assert.equal(store.size,0);reopened.dispose();
});
test('offline write keeps recovery draft and does not report Saved',async()=>{
  const {createAutosave}=await load(),states=[];
  const autosave=createAutosave({write:async()=>{throw Error('offline');},onState:state=>states.push(state),delay:100000});
  autosave.initialize({base:{revision:'a'},values:{name:'Initial'}});autosave.edit({name:'Retained'});
  assert.equal(await autosave.flush(),false);assert.equal(autosave.status,'Failed');assert.equal(autosave.dirty,true);
  assert.equal(states.at(-1).status,'Failed');autosave.dispose();
});
test('reverting a field during an in-flight write is Pending until the reversion is acknowledged',async()=>{
  const {createAutosave}=await load(),requests=[];let resolve;
  const autosave=createAutosave({write:body=>{requests.push(body);return new Promise(done=>{resolve=done;});},delay:100000});
  autosave.initialize({base:{revision:'a'},values:{name:'Initial'}});autosave.edit({name:'Temporary'});
  const flushing=autosave.flush();await Promise.resolve();autosave.edit({name:'Initial'});
  assert.notEqual(autosave.status,'Saved');
  resolve({saved:true,base:{revision:'b'},values:{name:'Temporary'}});await new Promise(done=>setImmediate(done));
  assert.equal(requests[1].changes.name,'Initial');resolve({saved:true,base:{revision:'c'},values:{name:'Initial'}});
  assert.equal(await flushing,true);autosave.dispose();
});
test('an uncertain write followed by reverting the input still needs revision verification',async()=>{
  const {createAutosave}=await load(),writes=[];let offline=true;
  const autosave=createAutosave({write:async body=>{writes.push(body);if(offline)throw Error('lost response');return {saved:true,base:{revision:'a'},values:{name:'Initial'}};},delay:100000});
  autosave.initialize({base:{revision:'a'},values:{name:'Initial'}});autosave.edit({name:'Temporary'});assert.equal(await autosave.flush(),false);
  autosave.edit({name:'Initial'});assert.equal(autosave.dirty,true);assert.notEqual(autosave.status,'Saved');
  offline=false;assert.equal(await autosave.flush(),true);assert.deepEqual(writes[1].changes,{});assert.equal(autosave.dirty,false);autosave.dispose();
});
