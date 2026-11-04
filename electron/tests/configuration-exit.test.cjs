'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {confirmConfigurationExit,confirmBlockedUnload}=require('../src/shared/configuration-exit.cjs');
test('quitting with pending configuration requires explicit native confirmation',async()=>{
  const prompts=[],hostWindow={webContents:{executeJavaScript:async()=>true}};
  const dialog={showMessageBox:async(_window,options)=>{prompts.push(options);return {response:0};}};
  assert.equal(await confirmConfigurationExit(hostWindow,dialog),false);
  assert.equal(prompts[0].defaultId,0);assert.equal(prompts[0].cancelId,0);
  assert.match(prompts[0].detail,/凭据/);assert.match(prompts[0].detail,/Workspace/);
  dialog.showMessageBox=async()=>({response:1});
  assert.equal(await confirmConfigurationExit(hostWindow,dialog),true);
});
test('clean configuration exits directly; unavailable renderer requires confirmation',async()=>{
  let prompts=0;
  const dialog={showMessageBox:async()=>{prompts++;return {response:0};}};
  const hostWindow={webContents:{executeJavaScript:async()=>false}};
  assert.equal(await confirmConfigurationExit(hostWindow,dialog),true);assert.equal(prompts,0);
  hostWindow.webContents.executeJavaScript=async()=>{throw Error('renderer unavailable');};
  assert.equal(await confirmConfigurationExit(hostWindow,dialog),false);assert.equal(prompts,1);
});
test('blocked reload only proceeds after explicit confirmation',()=>{
  assert.equal(confirmBlockedUnload({}, {showMessageBoxSync:()=>0}),false);
  assert.equal(confirmBlockedUnload({}, {showMessageBoxSync:()=>1}),true);
});
