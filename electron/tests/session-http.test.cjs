'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {EventEmitter}=require('node:events');

function fixture() {
  const request=new EventEmitter(),timers=new Map(),cleared=[];
  request.writes=[];request.followed=0;request.aborted=0;
  request.write=body=>request.writes.push(body);
  request.end=()=>{request.ended=true;};
  request.abort=()=>{request.aborted++;};
  request.followRedirect=()=>{request.followed++;};
  let options;
  const context=vm.createContext({module:{exports:{}},Buffer,URL,ArrayBuffer,
    require(name) {assert.equal(name,'electron');return {net:{request(spec){options=spec;return request;}}};},
    setTimeout(callback,ms) {const timer={callback,ms};timers.set(timer,callback);return timer;},
    clearTimeout(timer) {if(timer){cleared.push(timer);timers.delete(timer);}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/zotero/session-http.cjs'),'utf8'),context);
  const session={name:'browser-session'};
  const start=(spec,requestContext)=>context.module.exports.requestSessionHTTP(session,
    {method:'GET',url:'https://publisher.example/start',timeout:15000,...spec},requestContext);
  const incoming=(status=200,headers={})=>{
    const response=Object.assign(new EventEmitter(),{statusCode:status,statusMessage:'Fixture status',headers});
    request.emit('response',response);return response;
  };
  return {request,timers,cleared,session,start,incoming,get options(){return options;},
    requestSessionHTTP:context.module.exports.requestSessionHTTP};
}






test('Authorization redirects continue and pass each hop to the header context',async()=>{
  const f=fixture(),hops=[];
  const pending=f.start({headers:{authorization:'Bearer fixture'}},{cookieAdapter:{register:()=>({headers:{},
    redirect:target=>hops.push(target),release(){}})}});
  for(const target of ['https://publisher.example/same','http://publisher.example:444/cross'])
    f.request.emit('redirect',302,'GET',target);
  f.incoming().emit('end');await pending;
  assert.equal(f.request.followed,2);assert.equal(hops.length,2);assert.equal(f.request.aborted,0);
});

test('timeout covers redirects and body reading; late events cannot resume the request',async()=>{
  const f=fixture(),pending=f.start({timeout:10});
  const timer=[...f.timers.keys()][0];assert.equal(timer.ms,10);
  f.request.emit('redirect',302,'GET','https://publisher.example/next');
  const response=f.incoming();response.emit('data',Buffer.from('partial'));
  timer.callback();
  await assert.rejects(pending,/timed out/);
  assert.equal(f.timers.size,0);assert.equal(f.request.aborted,1);
  response.emit('end');f.request.emit('redirect',302,'GET','https://publisher.example/late');
  assert.equal(f.request.followed,1);
});




test('redirect policy rejects each unsafe hop before following; typed errors are preserved',async()=>{
  const f=fixture(),checked=[];
  const pending=f.start({}, {validateRedirect:url=>{checked.push(url);if(new URL(url).hostname==='private.example')throw Error('blocked');}});
  f.request.emit('redirect',302,'GET','https://publisher.example/next');
  f.request.emit('redirect',302,'GET','https://private.example/secret');
  await assert.rejects(pending,error=>error.kind==='transport' && error.code==='redirect_rejected');
  assert.equal(f.request.followed,1);assert.equal(checked.length,3);
});
test('Cookie Header is extracted into request context, never sent directly, and context is released',async()=>{
  const f=fixture();let registered,released=0,redirected=0;
  const pending=f.start({headers:{Cookie:'partitioned=old'}},{doc:{pageId:7},kind:'item-saver',
    cookieAdapter:{register:context=>{registered=context;return {headers:{'X-ALLFOLD-HTTP-Context':'token'},release(){released++;},redirect(){redirected++;}};}}});
  assert.equal(f.options.headers.Cookie,undefined);assert.equal(registered.candidateCookieHeader,'partitioned=old');
  f.request.emit('redirect',302,'GET','https://publisher.example/next');f.incoming().emit('end');await pending;
  assert.equal(released,1);assert.equal(redirected,1);
});

test('Translator URL policy permits HTTP, private hosts and arbitrary ports but rejects credentials',async()=>{
  const {validateTranslatorURL}=require('../src/zotero/translator.cjs');
  for(const target of ['http://publisher.example/next','https://127.0.0.1/private','https://10.0.0.1/private',
    'http://host.local:8080/private','https://publisher.example:444/next']) {
    const f=fixture(),pending=f.start({}, {validateRedirect:validateTranslatorURL});
    f.request.emit('redirect',302,'GET',target);f.incoming().emit('end');await pending;
    assert.equal(f.request.followed,1);
  }
  for(const target of ['https://user:pass@publisher.example/next','file:///tmp/private'])
    assert.throws(()=>validateTranslatorURL(target));
});
test('bounded attachment responses abort before buffering beyond the cap and cap redirect chains',async()=>{
 const f=fixture(),pending=f.start({}, {maxBytes:5,maxRedirects:1});
 const response=f.incoming();response.emit('data',Buffer.from('1234'));response.emit('data',Buffer.from('56'));
 await assert.rejects(pending,error=>error.code==='response_too_large');assert.equal(f.request.aborted,1);
 const g=fixture(),redirects=g.start({}, {maxRedirects:1});g.request.emit('redirect',302,'GET','https://publisher.example/one');g.request.emit('redirect',302,'GET','https://publisher.example/two');
 await assert.rejects(redirects,error=>error.code==='redirect_rejected');assert.equal(g.request.followed,1);
});
