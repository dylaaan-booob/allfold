'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {readPartitionCookies,withPartitionCookies}=require('../src/browser/request-cookies.cjs');
const runFixture=require('./fixture-process.cjs');
function fixture() {
  const partition={},client=new EventEmitter();let attached=false;
  const calls=[];
  client.isAttached=()=>attached;
  client.attach=()=>{assert.equal(attached,false);attached=true;calls.push('attach');};
  client.detach=()=>{attached=false;calls.push('detach');client.emit('detach');};
  client.sendCommand=async(method,params)=>{calls.push([method,params]);
    if(method==='Page.getFrameTree')return {frameTree:{frame:{securityOrigin:contents.mainFrame.origin,
      domainAndRegistry:new URL(contents.mainFrame.origin).hostname}}};
    return {cookies:[
    {name:'regular',value:'native'},
    {name:'partition',value:'private-value',partitionKey:{topLevelSite:'https://publisher.example'}},
    {name:'opaque',value:'never',partitionKeyOpaque:true},
    {name:'nonce',value:'never',partitionKeyOpaque:false},
  ]};};
  const contents={session:partition,debugger:client,mainFrame:{processId:7,frameToken:'frame',origin:'https://publisher.example'},
    getURL:()=>'https://publisher.example/article',isDestroyed:()=>false,isCrashed:()=>false,isLoadingMainFrame:()=>false};
  const tab={id:7,documentGeneration:1,view:{webContents:contents}};
  return {browser:{partition,tabs:new Map([[7,tab]])},contents,client,tab,calls};
}
test('cookie context reads only the qualified native page partition and releases its client',async()=>{
  const f=fixture();
  const cookies=await readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',{validate:()=>{}});
  assert.deepEqual(cookies.cookies.map(c=>c.name),['partition']);
  assert.deepEqual(cookies.metadata.map(c=>c.name),['regular']);
  assert.deepEqual(f.calls,['attach',['Page.getFrameTree',undefined],['Network.getCookies',{urls:['https://publisher.example/pdf']}],
    ['Page.getFrameTree',undefined],'detach']);
  assert.equal(f.client.isAttached(),false);
});
test('missing, foreign and already attached contexts keep the existing Session path',async()=>{
  const f=fixture(),options={validate:()=>{}};
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf',null,options),null);
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf','https://other.example/article',options),null);
  f.contents.session={};
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',options),null);
  f.contents.session=f.browser.partition;f.client.attach();f.calls.length=0;
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',options),null);
  assert.deepEqual(f.calls,[]);assert.equal(f.client.isAttached(),true);f.client.detach();
  f.contents.mainFrame.origin='null';f.calls.length=0;
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',options),null);
  assert.deepEqual(f.calls,[]);
});
test('an ordinary same-name value changed since the metadata query keeps its priority',()=>{
  const url='https://publisher.example/pdf',headers={Cookie:'sid=current'};
  const cookie={name:'sid',value:'partition',domain:'publisher.example',path:'/',expires:-1,partitionKey:{},sameSite:'None'};
  assert.deepEqual(withPartitionCookies(headers,url,url,{cookies:[cookie],metadata:[cookie]}),headers);
  const ordinary={...cookie,value:'current',partitionKey:undefined};
  assert.deepEqual(withPartitionCookies(headers,url,url,{cookies:[cookie],metadata:[ordinary,{...ordinary,path:'/pdf'}]}),headers);
});
test('same-site page changes preserve the cookie result and a site change revokes it',async()=>{
  const f=fixture(),send=f.client.sendCommand;
  f.client.sendCommand=async(...args)=>{const result=await send(...args);if(args[0]==='Network.getCookies') {
    f.tab.documentGeneration++;f.contents.mainFrame.frameToken='new-document';
    f.contents.getURL=()=>'https://publisher.example/new?query=1#anchor';f.contents.isLoadingMainFrame=()=>true;
  }return result;};
  const result=await readPartitionCookies(f.browser,'https://publisher.example/pdf',null,{page:f.tab});
  assert.deepEqual(result.cookies.map(c=>c.name),['partition']);
  f.client.sendCommand=async(...args)=>{const result=await send(...args);
    if(args[0]==='Network.getCookies')f.contents.mainFrame.origin='https://other.example';return result;};
  assert.equal(await readPartitionCookies(f.browser,'https://publisher.example/pdf',null,{page:f.tab}),null);
  f.contents.mainFrame.origin='https://publisher.example';
  f.client.sendCommand=send;f.calls.length=0;
  await Promise.all([1,2].map(()=>readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',{validate:()=>{}})));
  assert.equal(f.calls.filter(c=>c==='attach').length,2);assert.equal(f.calls.filter(c=>c==='detach').length,2);
});
test('cancel detaches its pending native query and waits for rejection before returning',async()=>{
  const f=fixture(),controller=new AbortController();let started,settled=false;
  const querying=new Promise(resolve=>{started=resolve;});
  f.client.sendCommand=()=>new Promise((_resolve,reject)=>{
    started();f.client.once('detach',()=>{settled=true;reject(Error('detached'));});
  });
  const result=readPartitionCookies(f.browser,'https://publisher.example/pdf','https://publisher.example/article',
    {signal:controller.signal,validate:()=>controller.signal.throwIfAborted()});
  await querying;controller.abort();await assert.rejects(result,error=>error.name==='AbortError');
  assert.equal(settled,true);assert.equal(f.client.isAttached(),false);
});
test('actual Chromium partition cookies reach only the controlled URL with its native jar',{timeout:20000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-request-cookies-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const {stdout,stderr}=await runFixture(t,require('electron'),[path.join(__dirname,'request-cookies.fixture.cjs'),profile],
    {timeout:15000,env:{...process.env,ELECTRON_RUN_AS_NODE:''}});
  assert.match(stdout,/PARTITION COOKIE PASS/);assert.doesNotMatch(stderr,/Check failed/);
});
