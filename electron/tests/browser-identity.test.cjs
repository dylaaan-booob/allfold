'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const {configureBrowserIdentity} = require('../src/browser/browser-identity.cjs');
const chromiumVersion = '123.4.5.6';
const ua = `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${chromiumVersion.split('.')[0]}.0.0.0 Safari/537.36`;

async function fixture(t,cookieAdapter) {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'allfold-browser-identity-test-'));
  t.after(() => fs.rmSync(directory, {recursive: true, force: true}));
  let hook, registration,registrations=0;
  const partition = {getUserAgent: () => ua,
    registerPreloadScript(value) {registration = value;return 'identity';},
    unregisterPreloadScript(id) {assert.equal(id, 'identity');registration = null;},
    webRequest: {onBeforeSendHeaders(filter, listener) {
      if (filter !== null) assert.deepEqual(filter, {urls: ['http://*/*','https://*/*']});
      if(filter!==null)registrations++;hook = listener;
    }}};
  const identity = await configureBrowserIdentity(partition, directory,{cookieAdapter});
  return {identity,get registrations(){return registrations;}, get registration() {return registration;}, get hook() {return hook;}};
}



const {PartitionedCookieAdapter,mergeCookies,MARKER}=require('../src/browser/partitioned-cookies.cjs');
test('one listener correlates concurrent same-URL requests without webContents and strips all markers',async t=>{
  const session={},doc={pageId:1,processId:2,frameToken:'current'};
  const adapter=new PartitionedCookieAdapter({session,cdpURL:'',getPage:()=>({session}),documentCurrent:()=>true});
  adapter.read=async(source,url,kind)=>[{name:'part',value:source.frameToken,partitionKey:{}}];
  const state=await fixture(t,adapter);assert.equal(state.registrations,1);
  const first=adapter.register({session,doc,kind:'item-saver',candidateCookieHeader:'part=OLD'});
  const second=adapter.register({session,doc:{...doc,frameToken:'second'},kind:'item-saver'});
  const invoke=details=>new Promise(resolve=>state.hook(details,resolve));
  const [a,b]=await Promise.all([invoke({id:1,url:'https://fixture/identical',requestHeaders:{Cookie:'ordinary=1',...first.headers}}),
    invoke({id:2,url:'https://fixture/identical',requestHeaders:{Cookie:'ordinary=1',...second.headers}})]);
  assert.equal(a.requestHeaders.Cookie,'ordinary=1; part=current');assert.equal(b.requestHeaders.Cookie,'ordinary=1; part=second');
  assert.equal(a.requestHeaders[MARKER],undefined);assert.equal(adapter.tokens.size,2);
  const next=await invoke({id:1,url:'https://other/redirect',requestHeaders:{Cookie:'new=2'}});
  assert.equal(next.requestHeaders.Cookie,'new=2; part=current');
  const unknown=await invoke({id:9,url:'https://fixture/identical',requestHeaders:{[MARKER]:'unknown'}});
  assert.equal(unknown.requestHeaders[MARKER],undefined);assert.equal(unknown.requestHeaders.Cookie,undefined);
  first.release();second.release();assert.equal(adapter.tokens.size,0);assert.equal(adapter.ids.size,0);state.identity.dispose();
});
test('released contexts and documents changed during Cookie lookup cannot inject late results',async()=>{
  const session={},doc={pageId:1,processId:2,frameToken:'current'};let current=true,finish;
  const adapter=new PartitionedCookieAdapter({session,cdpURL:'',getPage:()=>({session}),documentCurrent:()=>current});
  adapter.read=()=>new Promise(resolve=>finish=resolve);
  for(const release of [true,false]) {
    current=true;const registration=adapter.register({session,doc,kind:'translator'});
    const pending=adapter.merge({id:7,url:'https://fixture'},registration.headers);
    if(release)registration.release();else current=false;
    finish([{name:'cf_clearance',value:'SECRET',partitionKey:{}}]);
    const headers=await pending;assert.equal(headers.Cookie,undefined);assert.equal(headers[MARKER],undefined);
    registration.release();
  }
  adapter.dispose();assert.equal(adapter.tokens.size,0);
});

test('explicit Translator Cookie and Authorization survive same origin and are stripped permanently across origins',async()=>{
  const session={},doc={pageId:1,processId:2,frameToken:'current'};
  const adapter=new PartitionedCookieAdapter({session,getPage:()=>({session}),documentCurrent:()=>true});
  adapter.read=async()=>[{name:'part',value:'fresh'}];
  const native=adapter.register({session,doc,kind:'translator',url:'http://one.test/a'});
  const nativeHeaders=await adapter.merge({id:2,url:'http://one.test/a'},{Authorization:'Basic native',...native.headers});
  assert.equal(nativeHeaders.Authorization,'Basic native');native.release();
  const registration=adapter.register({session,doc,kind:'translator',url:'http://one.test/a',
    candidateCookieHeader:'explicit=1',authorization:'Bearer fixture'});
  let headers=await adapter.merge({id:1,url:'http://one.test/a'},{Cookie:'ordinary=1',...registration.headers});
  assert.equal(headers.Cookie,'ordinary=1; explicit=1; part=fresh');
  registration.redirect('http://one.test/b');
  headers=await adapter.merge({id:1,url:'http://one.test/b'},{Cookie:'ordinary=1'});
  assert.match(headers.Cookie,/explicit=1/);assert.equal(headers.Authorization,'Bearer fixture');
  registration.redirect('https://two.test/a');
  headers=await adapter.merge({id:1,url:'https://two.test/a'},{Cookie:'target=2',Authorization:'Bearer fixture'});
  assert.equal(headers.Cookie,'target=2; part=fresh');assert.equal(headers.Authorization,undefined);
  registration.redirect('http://one.test/c');
  headers=await adapter.merge({id:1,url:'http://one.test/c'},{Authorization:'Bearer fixture'});
  assert.equal(headers.Cookie,'part=fresh');assert.equal(headers.Authorization,undefined);
  registration.release();
});
