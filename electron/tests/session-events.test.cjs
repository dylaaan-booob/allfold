'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {EventEmitter}=require('node:events');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
function fixture() {
  const session=new EventEmitter(),hooks={};
  session.webRequest=Object.fromEntries(['onBeforeRequest','onBeforeSendHeaders','onHeadersReceived',
    'onBeforeRedirect','onCompleted','onErrorOccurred'].map(name=>[name,(filter,fn)=>{hooks[name]=filter===null?null:fn;}]));
  return {session,hooks,events:sharedSessionEvents(session)};
}
test('scoped header handlers compose once and ending one leaves the shared native entry live',()=>{
  const {session,hooks,events}=fixture();
  assert.equal(sharedSessionEvents(session),events);
  const a=events.subscribe('beforeSendHeaders',(_details,{requestHeaders})=>({requestHeaders:{...requestHeaders,First:'one'}}));
  const b=events.subscribe('beforeSendHeaders',(_details,{requestHeaders})=>({requestHeaders:{...requestHeaders,Second:'two'}}));
  let count=0,output;
  hooks.onBeforeSendHeaders({id:1,url:'https://fixture/',requestHeaders:{Cookie:'native=1'}},value=>{count++;output=value;});
  assert.equal(count,1);assert.deepEqual(output.requestHeaders,{Cookie:'native=1',First:'one',Second:'two'});
  a.dispose();
  hooks.onBeforeSendHeaders({id:2,url:'https://fixture/',requestHeaders:{}},value=>{output=value;});
  assert.deepEqual(output.requestHeaders,{Second:'two'});
  b.dispose();assert.equal(session.listenerCount('will-download'),1);
  const failing=events.subscribe('beforeSendHeaders',()=>{throw Error('failed consumer');});
  const following=events.subscribe('beforeSendHeaders',()=>({cancel:false}));
  hooks.onBeforeSendHeaders({id:3,url:'https://fixture/',requestHeaders:{}},value=>{count++;assert.equal(value.cancel,true);});
  assert.equal(count,2);failing.dispose();following.dispose();events.dispose();
  assert.equal(session.listenerCount('will-download'),0);assert.equal(hooks.onBeforeSendHeaders,null);
});
test('controlled same-URL host requests use request IDs, remove markers and retain actual redirects and shared cooldown',async()=>{
  const {session,hooks,events}=fixture();let sequence=0;
  const seen=[];
  session.fetch=async(url,options)=>{
    const id=++sequence;
    hooks.onBeforeRequest({id,url,method:'POST',resourceType:'other'},()=>{});
    hooks.onBeforeSendHeaders({id,url,method:'POST',requestHeaders:Object.fromEntries(new Headers(options.headers))},value=>{
      seen.push(value.requestHeaders);assert.equal(Object.keys(value.requestHeaders).some(name=>name.startsWith('x-allfold-')),false);
    });
    await Promise.resolve();
    hooks.onBeforeRedirect({id,url,redirectURL:'https://actual.example/final',statusCode:307});
    hooks.onHeadersReceived({id,url:'https://actual.example/final',statusCode:429,responseHeaders:{'Retry-After':['1']}},()=>{});
    hooks.onCompleted({id,url:'https://actual.example/final',statusCode:429});
    return {ok:false};
  };
  const [a,b]=await Promise.all(['a','b'].map(owner=>events.fetch('https://same.example/once',{method:'POST'},
    {owner:{workflow_id:owner,task_id:owner},attemptId:owner,deadline:Date.now()+2000})));
  assert.equal(a.requests[0].identity.workflow_id,'a');assert.equal(b.requests[0].identity.workflow_id,'b');
  assert.notEqual(a.requests[0].id,b.requests[0].id);
  assert.deepEqual(a.requests[0].redirects,[{url:'https://same.example/once',redirectURL:'https://actual.example/final',statusCode:307}]);
  assert.equal(a.requests[0].responses[0].url,'https://actual.example/final');
  assert.equal(events.cooldown.origins.has('https://actual.example'),true);
  assert.equal(events.cooldown.origins.has('https://same.example'),false);
  const abort=new AbortController();abort.abort();
  await assert.rejects(events.fetch('https://actual.example/next',{},
    {owner:{workflow_id:'c'},attemptId:'c',signal:abort.signal,deadline:Date.now()+2000}),error=>error.diagnostic.code==='canceled');
  assert.equal(seen.length,2);assert.equal(sharedSessionEvents(session).cooldown,events.cooldown);
  events.dispose();
});
test('download routing keeps same-URL owners separate, waits for actual done and rejects only attributable late items',async()=>{
  const {session,events}=fixture();const a=new EventEmitter(),b=new EventEmitter();
  const frameA={processId:1,frameToken:'a'},frameB={processId:2,frameToken:'b'};
  const make=()=>{const item=new EventEmitter();item.setSavePath=value=>item.filename=value;item.cancel=()=>{item.canceled=true;};return item;};
  let first,second;
  const controller=new AbortController();
  const register=(contents,frame,filename,onItem,signal)=>events.registerDownload({owner:{task_id:filename},attemptId:filename,
    contents,frame,document:{documentId:filename},filename,onItem,signal,deadline:Date.now()+1000,validate:()=>true});
  const left=register(a,frameA,'/tmp/a',value=>{first=value;},controller.signal);
  const right=register(b,frameB,'/tmp/b',value=>{second=value;});
  const ia=make(),ib=make(),unknown=make();
  session.emit('will-download',{},unknown,null,null);assert.equal(unknown.canceled,undefined);
  session.emit('will-download',{},ia,a,frameA);session.emit('will-download',{},ib,b,frameB);
  assert.equal(ia.filename,'/tmp/a');assert.equal(ib.filename,'/tmp/b');
  let drained=false;const draining=events.waitForDownloads(a).then(()=>{drained=true;});
  controller.abort();assert.equal(ia.canceled,true);await Promise.resolve();assert.equal(drained,false);
  ia.emit('done',{},'cancelled');assert.equal(await first.terminal,'cancelled');await draining;assert.equal(drained,true);
  assert.equal(ib.canceled,undefined);ib.emit('done',{},'completed');assert.equal(await second.terminal,'completed');
  left.dispose();right.dispose();
  const lateOwner=new EventEmitter(),lateFrame={processId:3,frameToken:'late'};
  const late=register(lateOwner,lateFrame,'/tmp/late',()=>{throw Error('retired callback');});late.dispose({dispatched:true});
  const lateItem=make();session.emit('will-download',{},lateItem,lateOwner,lateFrame);assert.equal(lateItem.canceled,true);
  const wrongFrame=make();session.emit('will-download',{},wrongFrame,lateOwner,{processId:4,frameToken:'other'});
  assert.equal(wrongFrame.canceled,undefined);events.dispose();
});
test('a missing frame cannot renew an attempt and unexpected downloads are denied only for an explicitly owned task page',async()=>{
  const {session,events}=fixture(),contents=new EventEmitter(),other=new EventEmitter();let accepted=0,rejected=0;
  const frame={processId:1,frameToken:'frame'};
  const registration=events.registerDownload({owner:{task_id:'task'},attemptId:'attempt',contents,frame,document:{documentId:'doc'},
    filename:'/tmp/safe',deadline:Date.now()+1000,validate:()=>true,onItem:()=>{accepted++;},onRejected:()=>{rejected++;}});
  const item=()=>{const value=new EventEmitter();value.setSavePath=()=>{};value.cancel=()=>{value.canceled=true;value.emit('done',{},'cancelled');};return value;};
  const uncertain=item();session.emit('will-download',{},uncertain,contents,null);
  assert.equal(accepted,0);assert.equal(rejected,1);assert.equal(uncertain.canceled,true);
  registration.dispose();
  const scope=events.registerTaskPage({owner:{task_id:'task'},contents,validate:()=>true});
  const unexpected=item(),unrelated=item();session.emit('will-download',{},unexpected,contents,frame);session.emit('will-download',{},unrelated,other,frame);
  assert.equal(unexpected.canceled,true);assert.equal(unrelated.canceled,undefined);
  scope.dispose();events.dispose();
});
