'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {LocalAPI}=require('../src/zotero/local-api.cjs');
const {EventEmitter}=require('node:events'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const server='SERVERFIXTUR';
function fixture(handler,stored={server_id:server,key:'k'.repeat(32)}) {
  const calls=[];return {calls,client:new LocalAPI({store:{read:async()=>stored,write:async value=>{stored=value;}},
    transport:async(url,options)=>{calls.push({url,options});return handler(new URL(url),options);}})};
}
const response=(data,status=200,headers={})=>new Response(typeof data==='string'?data:JSON.stringify(data),{status,headers:{'Zotero-Server-ID':server,'X-Zotero-Version':'10.0.6',...headers}});
function nativeTransport(handler) {
 const timers=new Map(),calls=[];let stored=null;
 const context=vm.createContext({module:{exports:{}},Response,Buffer,URLSearchParams,
  require(name){if(name!=='node:http')return require(name);return {request(url,options,respond){
   const request=new EventEmitter();request.destroy=error=>request.emit('error',error);
   request.end=body=>queueMicrotask(()=>{calls.push({url,options,body});handler({url,options,respond,request});});return request;
  }};},
  setTimeout(callback,ms){const timer={callback,ms};timers.set(timer,callback);return timer;},clearTimeout(timer){timers.delete(timer);}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/zotero/local-api.cjs'),'utf8'),context);
 const reply=(respond,data)=>{
  const incoming=Object.assign(new EventEmitter(),{statusCode:200,headers:{'zotero-server-id':server,'x-zotero-version':'10.0.6'}});
  respond(incoming);incoming.emit('data',Buffer.from(JSON.stringify(data)));incoming.emit('end');
 };
 const client=new context.module.exports.LocalAPI({store:{read:async()=>stored,write:async value=>{stored=value;}}});
 return {client,timers,calls,reply,get stored(){return stored;}};
}

test('Local API complete lists remain available beyond 1000 entries',async()=>{
 const rows=Array.from({length:1001},(_,index)=>({data:{name:'Collection '+index,parentCollection:false}}));
 // Use valid native keys, including distinct entries past the former cutoff.
 const alphabet='23456789ABCDEFGHIJKLMNPQRSTUVWXYZ';
 for(const [index,row] of rows.entries())row.key='AAAAA'+alphabet[index>>10]+alphabet[(index>>5)&31]+alphabet[index&31];
 const {client}=fixture(url=>{
  if(url.pathname==='/api/')return response('Local API');
  const values=url.pathname.endsWith('/groups')?Array.from({length:1001},(_,id)=>({id:id+1,data:{name:'Group '+id}})):
    url.pathname.startsWith('/api/groups/')?[]:rows;
  const limit=Number(url.searchParams.get('limit')) || values.length;
  return response(values.slice(0,limit),200,{'Total-Results':String(values.length)});
 });
 const result=await client.targets();assert.equal(result.libraries.length,1002);assert.equal(result.libraries[0].collections.length,1001);
 assert.equal((await client.read({server_id:server,library_type:'user',library_id:'0'},'/items/ABCDEFGH/children')).length,1001);
});

test('ordinary Local API JSON responses can exceed 4 MiB',async()=>{
 const data=[{key:'ABCDEFGH',data:{note:'x'.repeat(4*1024*1024)}}];
 let f;f=nativeTransport(({respond})=>f.reply(respond,data));
 const rows=await f.client.read({server_id:server,library_type:'user',library_id:'0'},'/items/ABCDEFGH/children');
 assert.equal(rows[0].data.note.length,4*1024*1024);
});

test('a parent save completing after 45 seconds retains the prior local save window',async()=>{
 let f,complete;f=nativeTransport(({respond})=>{complete=respond;});
 f.client.store={read:async()=>({server_id:server,key:'k'.repeat(32)})};
 const pending=f.client.create({server_id:server,library_type:'user',library_id:'0'},
  {key:'ABCDEFGH',version:0,itemType:'journalArticle'});pending.catch(()=>{});
 while(!complete)await new Promise(resolve=>setImmediate(resolve));
 for(const timer of [...f.timers.keys()])if(timer.ms<=45000)timer.callback();
 f.reply(complete,{successful:{'0':{key:'ABCDEFGH',version:1}},failed:{}});
 assert.equal((await pending).key,'ABCDEFGH');assert.equal(f.calls.length,1);
});

test('human authorization can finish after two minutes and can be explicitly cancelled',async()=>{
 for(const cancel of [false,true]) {
  let f,approval;f=nativeTransport(({url,respond})=>{
   if(url.endsWith('/api/'))f.reply(respond,'Local API');else approval=respond;
  });
  const controller=new AbortController(),pending=f.client.authorize({signal:controller.signal});pending.catch(()=>{});
  while(!approval)await new Promise(resolve=>setImmediate(resolve));
  for(const timer of [...f.timers.keys()])if(timer.ms<=120001)timer.callback();
  if(cancel)controller.abort();else f.reply(approval,{key:'k'.repeat(32),remember:true});
  if(cancel){await assert.rejects(pending,{code:'canceled'});assert.equal(f.stored,null);}
  else {assert.equal((await pending).authorized,true);assert.equal(f.stored.key,'k'.repeat(32));}
  assert.equal(f.timers.size,0);
 }
});
test('discovers explicit personal and group library collections without claiming unknown group rights',async()=>{
  const {client,calls}=fixture((url)=>response(url.pathname==='/api/'?'Local API':url.pathname.endsWith('/groups')?[{id:12,data:{name:'Team'}}]:[{key:'ABCDEFGH',data:{key:'ABCDEFGH',name:'Parent',parentCollection:false}},{key:'JKLMNPQR',data:{key:'JKLMNPQR',name:'Child',parentCollection:'ABCDEFGH'}}]));
  const result=await client.targets();assert.equal(result.server_id,server);assert.equal(result.libraries[1].id,'12');
  assert.equal(result.libraries[1].editable,null);assert.equal(result.libraries[0].collections[1].path,'Parent / Child');
  assert.ok(calls.every(call=>call.options.headers['Zotero-Allowed-Request']==='1'));
});
test('version gate and server binding refuse before writing, authorization keys never enter result',async()=>{
  let old=true;const {client,calls}=fixture((url,options)=>old?response('',200,{'X-Zotero-Version':'10.0.5'}):response(options.method==='POST'?{key:'s'.repeat(32),remember:true}:'Local API'));
  await assert.rejects(client.targets(),{code:'unsupported_version'});old=false;
  const result=await client.authorize();assert.deepEqual(result,{ok:true,server_id:server,authorized:true});assert.ok(!JSON.stringify(result).includes('ssss'));
  assert.equal(JSON.parse(calls.at(-1).options.body).appName,'Allfold');
});
test('exact per-object receipt is required and a rejected write is never replayed',async()=>{
  let writes=0;const {client}=fixture((url,options)=>{if(options.method==='POST'){writes++;return response({successful:{'0':{key:'WRONGKEY'}},failed:{}});}return response('Local API');});
  await assert.rejects(client.create({server_id:server,library_type:'user',library_id:'0',collection_key:null},{key:'ABCDEFGH',version:0,itemType:'journalArticle'}),{code:'unattributable_response'});
  assert.equal(writes,1);
});
test('PDF protocol uses exact bytes/form/conditional headers, unkeyed controlled upload, and waits for registration',async()=>{
 const uploadKey='u'.repeat(32),bytes=Buffer.from('%PDF-1.7\nfixture');let md5;
 const {client,calls}=fixture((url,options)=>{
  if(url.pathname.includes('/uploads/')){assert.equal(options.headers['Zotero-API-Key'],undefined);assert.ok(options.body.includes(bytes));assert.ok(options.body.includes(Buffer.from('name="file"')));return response('',201);}
  const form=new URLSearchParams(options.body);assert.equal(options.headers['If-None-Match'],'*');
  if(form.has('upload')){assert.equal(form.get('upload'),uploadKey);return new Response(null,{status:204,headers:{'Zotero-Server-ID':server}});}
  md5=form.get('md5');assert.match(md5,/^[a-f0-9]{32}$/);assert.equal(form.get('filesize'),String(bytes.length));assert.equal(form.get('mtime'),'1700000000123');assert.equal(form.get('filename'),'paper file.pdf');
  return response({uploadKey,url:'http://127.0.0.1:23119/api/local/uploads/'+uploadKey,params:{key:md5}});
 });
 const result=await client.upload({server_id:server,library_type:'user',library_id:'0'},'ABCDEFGH',bytes,{filename:'paper file.pdf',contentType:'application/pdf',mtime:1700000000123});
 assert.deepEqual(result,{registered:true,md5});assert.equal(calls.length,3);
});
test('unsafe upload destination and stage failure never send bytes or replay authorization',async()=>{
 for(const url of ['https://remote.example/upload','http://localhost:23119/api/local/uploads/'+'u'.repeat(32),'http://127.0.0.1:23119/api/local/uploads/'+'v'.repeat(32)]){
  const {client,calls}=fixture((url_,options)=>response({uploadKey:'u'.repeat(32),url,params:{key:new URLSearchParams(options.body).get('md5')}}));
  await assert.rejects(client.upload({server_id:server,library_type:'user',library_id:'0'},'ABCDEFGH',Buffer.from('%PDF-'),{filename:'paper.pdf',contentType:'application/pdf'}),{code:'invalid_upload_destination'});assert.equal(calls.length,1);
 }
});
test('authorization denial, one-use approval, HTTP rejection and mismatched Server-ID are bounded without retries',async()=>{
 for(const [status,code] of [[401,'authorization_required'],[403,'access_denied'],[412,'server_id_mismatch'],[428,'precondition_required'],[429,'rate_limited']]){
  const {client,calls}=fixture(()=>response('',status));await assert.rejects(client.targets(),{code});assert.equal(calls.length,1);
 }
 const {client,calls}=fixture((url)=>response(url.pathname.endsWith('authorize')?{key:'k'.repeat(32),remember:false}:'Local API'));
 await assert.rejects(client.authorize(),{code:'always_allow_required'});assert.equal(calls.length,2);
 const mismatch=fixture(()=>response('',200,{'Zotero-Server-ID':'DIFFERENT'}));
 await assert.rejects(mismatch.client.create({server_id:server,library_type:'user',library_id:'0'},{key:'ABCDEFGH'}),{code:'server_id_mismatch'});
});
test('HTTP200 per-object failed response including required version is not confirmation',async()=>{
 const {client,calls}=fixture(()=>response({successful:{},failed:{'0':{key:'ABCDEFGH',code:428,message:'Version required'}}}));
 await assert.rejects(client.create({server_id:server,library_type:'user',library_id:'0'},{key:'ABCDEFGH'}),
  error=>error.code==='object_rejected' && error.status===428 && error.no_effect!==true);assert.equal(calls.length,1);
});
test('dispatched authorization and access rejections cannot claim that no write was dispatched',async()=>{
 for(const status of [401,403]) {
  const {client,calls}=fixture(()=>response('',status));
  await assert.rejects(client.create({server_id:server,library_type:'user',library_id:'0'},{key:'ABCDEFGH'}),
   error=>error.status===status && error.no_effect!==true);
  assert.equal(calls.length,1);assert.equal(calls[0].options.method,'POST');
 }
});
