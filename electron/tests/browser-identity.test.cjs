'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
const {configureBrowserIdentity} = require('../src/browser/browser-identity.cjs');
const chromiumVersion = '123.4.5.6';
const ua = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromiumVersion.split('.')[0]}.0.0.0 Safari/537.36`;

async function fixture(t) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'allfold-browser-identity-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  let hook, registration,registrations=0;
  const partition = {getUserAgent: () => ua,
    registerPreloadScript(value) {registration = value;return 'identity';},
    unregisterPreloadScript(id) {assert.equal(id, 'identity');registration = null;},
    webRequest: {onBeforeSendHeaders(filter, listener) {
      if(filter!==null)registrations++;hook = listener;
    }}};
  const sessionEvents=sharedSessionEvents(partition);
  t.after(()=>sessionEvents.dispose());
  const identity = await configureBrowserIdentity(partition, directory,{sessionEvents});
  return {identity,sessionEvents,get registrations(){return registrations;}, get registration() {return registration;}, get hook() {return hook;}};
}


test('identity uses the shared header entry and preserves native credentials while clearing retired and current markers',async t=>{
  const state=await fixture(t);assert.equal(state.registrations,1);
  const invoke=details=>new Promise(resolve=>state.hook(details,resolve));
  const result=await invoke({id:1,url:'https://fixture/',requestHeaders:{Cookie:'native=1',Authorization:'Basic native',
    'User-Agent':'obsolete','sec-ch-ua':'obsolete','X-Allfold-Http-Context':'retired','X-Allfold-Request-Context':'private'}});
  assert.equal(result.requestHeaders.Cookie,'native=1');assert.equal(result.requestHeaders.Authorization,'Basic native');
  assert.equal(result.requestHeaders['User-Agent'],undefined);
  for(const [name,value] of Object.entries(state.identity.headers))assert.equal(result.requestHeaders[name],value);
  assert.equal(Object.keys(result.requestHeaders).some(name=>name.toLowerCase().startsWith('x-allfold-')),false);
  state.identity.dispose();
  const after=await invoke({id:2,url:'https://fixture/',requestHeaders:{Cookie:'native=2','X-Allfold-Request-Context':'unknown'}});
  assert.deepEqual(after.requestHeaders,{Cookie:'native=2'});assert.equal(state.registrations,1);
});
test('HTTP retains Chromium headers and the synchronous frame preload is removed only by identity disposal',async t=>{
  const state=await fixture(t);
  const result=await new Promise(resolve=>state.hook({id:3,url:'http://fixture/',requestHeaders:{'User-Agent':'native'}},resolve));
  assert.equal(result.requestHeaders['User-Agent'],'native');
  assert.equal(state.registration.type,'frame');assert.ok(fs.existsSync(state.registration.filePath));
  const filename=state.registration.filePath;state.identity.dispose();
  assert.equal(state.registration,null);assert.equal(fs.existsSync(filename),false);
});
