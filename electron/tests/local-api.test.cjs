'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {LocalAPI}=require('../src/zotero/local-api.cjs');
const server='SERVERFIXTUR';
function fixture(handler,stored={server_id:server,key:'k'.repeat(32)}) {
  const calls=[];return {calls,client:new LocalAPI({store:{read:async()=>stored,write:async value=>{stored=value;}},
    transport:async(url,options)=>{calls.push({url,options});return handler(new URL(url),options);}})};
}
const response=(data,status=200,headers={})=>new Response(typeof data==='string'?data:JSON.stringify(data),{status,headers:{'Zotero-Server-ID':server,'X-Zotero-Version':'10.0.6',...headers}});
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
