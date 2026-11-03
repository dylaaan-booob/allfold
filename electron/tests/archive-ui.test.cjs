'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {taskUI}=require('./task-ui-fixture.cjs');
const idle={phase:'idle',active:false,can_continue:false,can_cancel:false};
const request=async url=>url.includes('/assets/kept/')?{}:idle;

test('Archive disabled starts in Array and cannot be selected until the preference is reversed',async()=>{
  const f=await taskUI('kept.js',{request,archiveDisabled:true,layout:'archive',page:'workspace'});
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  assert.equal(f.get('selected-view').hidden,false);
  assert.equal(f.get('kept-view').hidden,false);
  assert.equal(f.get('workspace-archive').hidden,true);
  await f.get('workspace-archive').emit('click');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  f.setArchiveDisabled(false);
  await f.window.emit('ui-preferences-changed',{name:'archiveDisabled',value:false});
  assert.equal(f.get('workspace-archive').hidden,false);
  await f.get('workspace-archive').emit('click');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'archive');
});

test('disabling Archive waits for a busy reader and preserves the Workspace parent',async()=>{
  const f=await taskUI('kept.js',{request,layout:'archive',page:'workspace'});
  let busy=true;f.window.inboxKept.busy=()=>busy;
  f.setArchiveDisabled(true);
  await f.window.emit('ui-preferences-changed',{name:'archiveDisabled',value:true});
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'archive');
  assert.equal(f.get('workspace-archive').hidden,true);
  busy=false;
  await f.window.emit('enrich-state');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  assert.equal(f.get('selected-view').hidden,false);
  assert.equal(f.get('kept-view').hidden,false);
});

test('disabled Archive waits outside Workspace and applies on returning to Workspace',async()=>{
  const f=await taskUI('kept.js',{request,layout:'archive',page:'settings'});
  f.setArchiveDisabled(true);
  await f.window.emit('ui-preferences-changed',{name:'archiveDisabled',value:true});
  assert.equal(f.page(),'settings');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'archive');
  f.setPage('workspace');
  await f.window.emit('workspace-navigation-state');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
});

test('legacy Paper navigation locates the current Candidate or Kept entry and rejects missing Papers',async()=>{
  const f=await taskUI('kept.js',{request,archiveDisabled:true,page:'workspace'});
  const journal={key:'journal-1',name:'Test Journal'};
  f.window.inboxKept.candidates=()=>[{paper:{id:'candidate-1',title:'Candidate'},journal}];
  f.window.inboxKept.papers=()=>[{paper:{id:'kept-1',title:'Kept'},journal}];
  assert.equal(f.window.workspaceArray.openPaper('candidate-1'),true);
  assert.equal(f.get('kept-view').dataset.status,'candidates');
  assert.equal(f.get('array-index').children[0].getAttribute('aria-current'),'true');
  assert.equal(f.window.workspaceArray.openPaper('kept-1'),true);
  assert.equal(f.get('kept-view').dataset.status,'kept');
  assert.equal(f.get('array-index').children[0].dataset.indexId,'kept-1');
  assert.equal(f.get('array-index').children[0].getAttribute('aria-current'),'true');
  assert.equal(f.window.workspaceArray.openPaper('missing-1'),false);
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  assert.equal(f.get('kept-view').hidden,false);
});

test('startup waits for Inbox readiness before applying the disabled Archive layout',async()=>{
  const f=await taskUI('kept.js',{request,archiveDisabled:true,layout:'archive',page:'workspace',bridgeReady:false});
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'archive');
  assert.equal(f.window.workspaceArray.openPaper('paper-1'),false);
  f.setBridgeReady(true);
  await f.window.emit('inbox-ready');
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  assert.equal(f.get('kept-view').hidden,false);
});

test('a missing legacy Inbox Paper leaves a usable Array page and an explicit notice',async()=>{
  const f=await taskUI('kept.js',{request,archiveDisabled:true,layout:'archive',page:'workspace',
    initialLink:{view:'inbox',paper:'missing-1'}});
  assert.equal(f.get('selected-view').dataset.workspaceLayout,'array');
  assert.equal(f.get('selected-view').hidden,false);
  assert.equal(f.get('kept-view').hidden,false);
  assert.equal(f.calls.filter(call=>call[0]==='notice').length,1);
  assert.match(f.calls.find(call=>call[0]==='notice')[1],/Paper.*不在当前/);
});
