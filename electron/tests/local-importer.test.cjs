'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {saveOnce}=require('../src/zotero/local-importer.cjs');
const {LocalAPI}=require('../src/zotero/local-api.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'group',library_id:'12',collection_key:'ABCDEFGH'};
const pdfFixture='%PDF-1.7\nfixture\n%%EOF\n';
const item={itemType:'journalArticle',title:'Fixture',DOI:'10.5555/fixture',attachments:[]};
function fixture(options={}) {
 const created=[],uploaded=[];let calls=0;
 const api={validate:async()=>target,create:async(t,value)=>{created.push(value);if(options.failParent && created.length===1)throw Object.assign(Error(),{code:'connection_lost'});return {key:value.key,status:200};},upload:async(t,key,bytes,metadata)=>{uploaded.push({key,bytes,metadata});if(options.failUpload)throw Error('upload failed');return {registered:true};}};
 return {created,uploaded,run:overrides=>saveOnce({item,doi:item.DOI,target,api,doc:{pageId:7,url:'https://publisher.example/paper'},browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34',family:'ipv4'}]})},documentCurrent:()=>true,cookieAdapter:{},bypassAttachment:async()=>{}},requestHTTP:async()=>{calls++;return {status:200,url:'https://publisher.example/full.pdf',headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};},...overrides}),get downloads(){return calls;}};
}
const deferred=()=>{let resolve;const promise=new Promise(yes=>{resolve=yes;});return {promise,resolve};};
function nativeWriter({holdRead,holdWrite,rejectParent=false,missingCreateKey=false}={}) {
 const entered=deferred(),release=deferred(),writes=[],objects=[];let reads=0,md5;
 const response=(data,status=200)=>new Response(status===204?null:typeof data==='string'?data:JSON.stringify(data),
  {status,headers:{'Zotero-Server-ID':target.server_id,'X-Zotero-Version':'10.0.6'}});
 const write=async stage=>{writes.push(stage);if(stage===holdWrite){entered.resolve();await release.promise;}};
 const api=new LocalAPI({store:{read:async()=>{
  reads++;if(reads===holdRead){entered.resolve();await release.promise;}
  return missingCreateKey && reads===2?null:{server_id:target.server_id,key:'k'.repeat(32)};
 }},transport:async(raw,options)=>{
  const url=new URL(raw),path=url.pathname;
  if(options.method==='POST' && path.endsWith('/items')) {
   const object=JSON.parse(options.body)[0];await write(object.parentItem?'child':'parent');
   if(rejectParent && !object.parentItem)return response({successful:{},failed:{'0':{key:object.key,code:403}}});
   objects.push(object);return response({successful:{'0':{key:object.key,version:1}},failed:{}});
  }
  if(options.method==='POST' && path.includes('/uploads/')){await write('binary');return response('',201);}
  if(options.method==='POST' && path.endsWith('/file')) {
   const form=new URLSearchParams(options.body);
   if(form.has('upload')){await write('register');return response(null,204);}
   await write('authorize');md5=form.get('md5');
   return response({uploadKey:'u'.repeat(32),url:'http://127.0.0.1:23119/api/local/uploads/'+'u'.repeat(32),params:{key:md5}});
  }
  if(path.includes('/items/')) {
   const record=data=>({key:data.key,library:{type:'group',id:12},data});
   if(path.endsWith('/children'))return response(objects.filter(value=>value.parentItem).map(record));
   const object=objects.find(value=>value.key===path.split('/').at(-1));return object?response(record(object)):response('',404);
  }
  return response(path==='/api/'?'Local API':{});
 }});
 return {api,entered,release,writes};
}
test('native import preallocates parent identity and uses the explicit collection',async()=>{
 const f=fixture(),result=await f.run();assert.equal(result.parent.outcome,'confirmed');assert.equal(f.created.length,1);
 assert.equal(f.created[0].version,0);assert.deepEqual(f.created[0].collections,['ABCDEFGH']);assert.equal(result.zotero.parent_key,f.created[0].key);
});
test('uncertain parent keeps known key, settles, and never starts attachments or replays',async()=>{
 const f=fixture({failParent:true}),result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]}});
 assert.equal(result.parent.outcome,'uncertain');assert.equal(f.created.length,1);assert.equal(f.downloads,0);assert.ok(result.zotero.parent_key);assert.equal(result.settled,true);
});
test('cancel and document changes during parent credential reading prevent actual POST dispatch',async()=>{
 for(const cancel of [true,false]) {
  const f=fixture(),native=nativeWriter({holdRead:2}),controller=new AbortController();let current=true;
  const pending=f.run({api:native.api,signal:controller.signal,browser:{documentCurrent:()=>current}});
  await native.entered.promise;if(cancel)controller.abort();else current=false;native.release.resolve();
  const result=await pending;
  assert.deepEqual(native.writes,[]);assert.equal(result.parent.outcome,'no_effect');assert.ok(result.zotero.parent_key);
  assert.equal(result.diagnostic.code,cancel?'canceled':'document_changed');
 }
});
test('a missing key before creation is no effect but a dispatched per-object rejection remains uncertain',async()=>{
 for(const rejectParent of [false,true]) {
  const f=fixture(),native=nativeWriter({rejectParent,missingCreateKey:!rejectParent}),result=await f.run({api:native.api});
  assert.equal(result.parent.outcome,rejectParent?'uncertain':'no_effect');
  assert.deepEqual(native.writes,rejectParent?['parent']:[]);assert.equal(result.stop_batch,true);assert.ok(result.zotero.parent_key);
 }
});
test('cancel and document changes during child and upload credential reads stop further writes',async()=>{
 for(const holdRead of [3,4])for(const cancel of [true,false]) {
  const f=fixture(),native=nativeWriter({holdRead}),controller=new AbortController();let current=true;
  const pending=f.run({api:native.api,signal:controller.signal,item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>current}});
  await native.entered.promise;if(cancel)controller.abort();else current=false;native.release.resolve();
  const result=await pending;
  assert.deepEqual(native.writes,holdRead===3?['parent']:['parent','child']);
  assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.registered,false);assert.equal(result.stop_batch,true);
  assert.equal(result.pdf.failures[0].code,cancel?'canceled':'document_changed');
 }
});
test('cancellation after parent dispatch waits for its one result without replay',async()=>{
 const f=fixture(),native=nativeWriter({holdWrite:'parent'}),controller=new AbortController();let settled=false;
 const pending=f.run({api:native.api,signal:controller.signal}).then(value=>{settled=true;return value;});
 await native.entered.promise;controller.abort();await Promise.resolve();
 assert.equal(settled,false);assert.deepEqual(native.writes,['parent']);native.release.resolve();
 const result=await pending;assert.equal(result.parent.outcome,'confirmed');assert.deepEqual(native.writes,['parent']);
});
test('cancel and document changes await each issued upload request and stop before the next POST',async()=>{
 const stages=['parent','child','authorize','binary','register'];
 for(const holdWrite of ['authorize','binary','register'])for(const cancel of [true,false]) {
  const f=fixture(),native=nativeWriter({holdWrite}),controller=new AbortController();let current=true,settled=false;
  const pending=f.run({api:native.api,signal:controller.signal,item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>current}})
   .then(value=>{settled=true;return value;});
  await native.entered.promise;if(cancel)controller.abort();else current=false;await Promise.resolve();
  assert.equal(settled,false);native.release.resolve();const result=await pending;
  assert.deepEqual(native.writes,stages.slice(0,stages.indexOf(holdWrite)+1));
  assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.registered,holdWrite==='register');
 }
});
test('PDF is only registered after attachment create and complete upload; failure preserves parent and shell key',async()=>{
 for(const failUpload of [false,true]){const f=fixture({failUpload}),result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]}});
 assert.equal(result.parent.outcome,'confirmed');assert.equal(f.created[1].parentItem,f.created[0].key);assert.equal(result.zotero.attachment_keys[0],f.created[1].key);
 assert.equal(result.pdf.registered,!failUpload);assert.equal(f.uploaded.length,1);assert.equal(result.pdf.source,failUpload?null:'translator');}
});
test('translator metadata notes and explicit links survive without fetching snapshots',async()=>{
 const f=fixture();await f.run({item:{...item,creators:[{creatorType:'author',fieldMode:1,lastName:'Organization'}],notes:[{note:'Note',tags:['tag']}],attachments:[{title:'Link',url:'https://publisher.example/link',mimeType:'text/html',snapshot:false},{url:'https://publisher.example/snapshot',mimeType:'text/html'}]}});
 assert.deepEqual(f.created[0].creators,[{creatorType:'author',name:'Organization'}]);assert.equal(f.created[1].itemType,'note');assert.deepEqual(f.created[1].tags,[{tag:'tag',type:1}]);
 assert.equal(f.created[2].linkMode,'linked_url');assert.equal(f.downloads,0);
});
test('an escaped child failure stops all further note, link, PDF and fallback writes',async()=>{
 const f=fixture();let fallback=0;
 const api={validate:async()=>target,create:async(t,value)=>{f.created.push(value);if(f.created.length===2)throw Object.assign(Error(),{code:'connection_lost'});return {key:value.key,status:200};}};
 const result=await f.run({api,item:{...item,notes:['First','Second'],attachments:[{snapshot:false,url:'https://publisher.example/link'},{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},fallbackPDF:async()=>{fallback++;return {candidates:[]};}});
 assert.equal(result.parent.outcome,'confirmed');assert.equal(f.created.length,2);assert.equal(fallback,0);assert.equal(f.downloads,0);
});
test('actual PDF pages replace Translator PDF candidates and retain bounded Session context without credentials',async()=>{
 const f=fixture(),requests=[];await f.run({doc:{url:'https://publisher.example/current.pdf',type:'application/pdf'},item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/stale.pdf'}]},
 requestHTTP:async(session,spec,context)=>{requests.push({spec,context});return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};}});
 assert.equal(requests.length,1);assert.equal(requests[0].spec.url,'https://publisher.example/current.pdf');assert.deepEqual(requests[0].spec.headers,{});assert.equal(typeof requests[0].context.validateRedirect,'function');assert.ok(requests[0].context.maxBytes);
 assert.equal(requests[0].spec.referrerPolicy,'origin-when-cross-origin');
});
test('Translator success never looks up OA; failed downloads try bounded unique OA candidates until registration',async()=>{
 for(const translatorOK of [true,false]) {
  const f=fixture(),downloads=[],lookup=[];
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   fallbackPDF:async data=>{lookup.push(data);return {candidates:['https://oa.example/bad.pdf','https://oa.example/bad.pdf','https://oa.example/good.pdf','https://oa.example/unused.pdf']};},
   requestHTTP:async(_session,spec)=>{downloads.push(spec);return {status:translatorOK || spec.url.includes('good')?200:404,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};}});
  assert.equal(result.pdf.source,translatorOK?'translator':'openalex');assert.equal(result.pdf.registered,true);
  assert.equal(lookup.length,translatorOK?0:1);
  assert.deepEqual(downloads.map(value=>value.url),translatorOK?['https://publisher.example/full.pdf']:['https://publisher.example/full.pdf','https://oa.example/bad.pdf','https://oa.example/good.pdf']);
  assert.ok(downloads.every(value=>!Object.keys(value.headers).length));
  if(!translatorOK)assert.equal(downloads.at(-1).referrer,undefined);
 }
});
test('download DNS and redirect resolution reject private hosts before transport can follow them',async()=>{
 const f=fixture(),browser={partition:{resolveHost:async()=>({endpoints:[{address:'127.0.0.1',family:'ipv4'}]})},documentCurrent:()=>true};
 const result=await f.run({browser,item:{...item,attachments:[{mimeType:'application/pdf',url:'https://private.example/full.pdf'}]}});
 assert.equal(f.downloads,0);assert.equal(result.pdf.registered,false);assert.equal(result.pdf.failures[0].code,'unsafe_url');
});
test('attachment challenge recovery downloads and registers the helper captured PDF URL',async()=>{
 const f=fixture(),downloads=[],helpers=[];
 const captured='https://cdn.example/tokenized.pdf?signature=fixture';
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/challenge'}]},
  browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
   bypassAttachment:async(url,doc,{visible})=>{helpers.push(visible);return captured;}},
  requestHTTP:async(_session,spec)=>{downloads.push(spec.url);return spec.url===captured
   ?{status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)}
   :{status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};}});
 assert.equal(result.pdf.registered,true);assert.deepEqual(helpers,[false]);
 assert.deepEqual(downloads,['https://publisher.example/challenge',captured]);
 assert.equal(f.created.length,2);assert.equal(f.uploaded.length,1);assert.equal(f.uploaded[0].bytes.toString(),pdfFixture);
});
test('known attachment sites recover HTTP 200 HTML challenges, including attributed proper URLs',async()=>{
 const sites=[
  {url:'https://www.sciencedirect.com/science/article/pii/fixture/pdf'},
  {url:'https://pdf.sciencedirectassets.com/fixture.pdf'},
  {url:'https://pmc.ncbi.nlm.nih.gov/articles/fixture/pdf'},
  {url:'https://institution.example/proxy/full.pdf',_allfoldProperURL:'https://www.sciencedirect.com/fixture.pdf'},
 ];
 for(const site of sites) {
  const f=fixture(),helpers=[],downloads=[],captured='https://cdn.example/captured.pdf';let fallback=0;
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',...site}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
    bypassAttachment:async(url,doc,{visible})=>{helpers.push({url,visible});return captured;}},
   fallbackPDF:async()=>{fallback++;return {candidates:[]};},
   requestHTTP:async(_session,spec)=>{downloads.push(spec.url);return {status:200,headers:[['content-type',spec.url===captured?'application/pdf':'text/html']],
    body:Buffer.from(spec.url===captured?pdfFixture:'<html>Verify access</html>')};}});
  assert.equal(result.pdf.registered,true,site.url);assert.equal(result.pdf.source,'translator');assert.equal(fallback,0);
  assert.deepEqual(helpers,[{url:site.url,visible:false}]);assert.deepEqual(downloads,[site.url,captured]);
 }
});
test('ordinary HTML and known HTTP 404 responses do not open attachment helpers',async()=>{
 for(const attachment of [
  {url:'https://publisher.example/full.pdf'},
  {url:'https://sciencedirect.com.attacker.example/full.pdf'},
  {url:'https://publisher.example/full.pdf',_allfoldProperURL:'https://user:password@sciencedirect.com/full.pdf'},
  {url:'https://www.sciencedirect.com/missing.pdf',status:404},
 ]) {
  const f=fixture();let helpers=0,downloads=0;
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',...attachment}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
    bypassAttachment:async()=>{helpers++;throw Error('Unexpected helper');}},
   requestHTTP:async()=>{downloads++;return {status:attachment.status || 200,headers:[['content-type','text/html'],...(attachment.status?[['cf-mitigated','challenge']]:[])],body:Buffer.from('<html>Not a PDF</html>')};}});
  assert.equal(result.pdf.registered,false);assert.equal(helpers,0,attachment.url);assert.equal(downloads,1);
  assert.equal(f.created.length,1);assert.equal(f.uploaded.length,0);
 }
});
test('hidden attachment helper failure advances to visible capture without replaying writes',async()=>{
 const f=fixture(),downloads=[],helpers=[],captured='https://cdn.example/visible.pdf';
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/challenge'}]},
  browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
   bypassAttachment:async(url,doc,{visible})=>{helpers.push(visible);if(!visible)throw Object.assign(Error('Hidden timeout'),{code:'timeout'});return captured;}},
  requestHTTP:async(_session,spec)=>{downloads.push(spec.url);return spec.url===captured
   ?{status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)}
   :{status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};}});
 assert.equal(result.pdf.registered,true);assert.deepEqual(helpers,[false,true]);
 assert.deepEqual(downloads,['https://publisher.example/challenge',captured]);
 assert.equal(f.created.length,2);assert.equal(f.uploaded.length,1);
});
test('failed hidden captured downloads recover visibly from the original challenge URL',async()=>{
 for(const failure of ['network_error','timeout','mime_mismatch']) {
  const f=fixture(),downloads=[],helpers=[],original='https://publisher.example/challenge';
  const hidden='https://cdn.example/hidden.pdf',visible='https://cdn.example/visible.pdf';
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:original}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
    bypassAttachment:async(url,doc,options)=>{helpers.push({url,visible:options.visible});return options.visible?visible:hidden;}},
   recoveryTiming:{wait:async()=>{},random:()=>0},
   requestHTTP:async(_session,spec)=>{
    downloads.push(spec.url);
    if(spec.url===original)return {status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};
    if(spec.url===hidden && failure!=='mime_mismatch')throw Object.assign(Error('Hidden download failed'),{code:failure,net_error:'ERR_CONNECTION_CLOSED'});
    return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(spec.url===hidden?'invalid PDF':pdfFixture)};
   }});
  assert.equal(result.pdf.registered,true,failure);
  assert.deepEqual(helpers,[{url:original,visible:false},{url:original,visible:true}],failure);
  assert.deepEqual(downloads,failure==='mime_mismatch'?[original,hidden,visible]:[original,hidden,hidden,hidden,visible],failure);
  assert.equal(f.created.length,2);assert.equal(f.uploaded.length,1);assert.equal(f.uploaded[0].bytes.toString(),pdfFixture);
 }
});
test('a closed PDF connection retries only the GET and preserves each Zotero write boundary',async()=>{
 const f=fixture(),native=nativeWriter(),requests=[],waits=[],recovery=[];
 const original='https://publisher.example/full.pdf';
 const result=await f.run({api:native.api,item:{...item,attachments:[{mimeType:'application/pdf',url:original}]},
  recoveryTiming:{wait:async ms=>waits.push(ms),random:()=>0.4},
  recordRecovery:(event,details)=>recovery.push({event,...details}),
  requestHTTP:async(_session,spec,{doc})=>{
   requests.push({spec,doc});
   if(requests.length===1)throw Object.assign(Error('private network details'),{code:'network_error',net_error:'ERR_CONNECTION_CLOSED'});
   return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};
  }});
 assert.equal(result.pdf.registered,true);
 assert.deepEqual(native.writes,['parent','child','authorize','binary','register']);
 assert.deepEqual(requests.map(({spec})=>spec.url),[original,original]);
 assert.equal(requests[0].doc,requests[1].doc);
 assert.deepEqual(waits,[600]);
 assert.deepEqual(recovery.map(({event,attempt,attempt_limit,code,net_error})=>[event,attempt,attempt_limit,code,net_error]),[
  ['recovery_scheduled',2,3,'network_error','ERR_CONNECTION_CLOSED'],
  ['recovery_succeeded',2,3,'network_error','ERR_CONNECTION_CLOSED'],
 ]);
 assert.doesNotMatch(JSON.stringify(recovery),/private network details|publisher/);
});
test('certificate, unknown network, and invalid PDF response errors never retry the GET',async()=>{
 const pdf={status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};
 const cases=[
  {error:{code:'network_error',net_error:'ERR_CERT_AUTHORITY_INVALID'},code:'network_error'},
  {error:{code:'network_error'},code:'network_error'},
  {response:{...pdf,body:Buffer.alloc(0)},code:'empty_response'},
  {response:{...pdf,body:Buffer.from('%PDF-1.7\ntruncated')},code:'invalid_response'},
  {response:{...pdf,status:206},code:'invalid_response'},
  {response:{...pdf,headers:[...pdf.headers,['content-length','999']]},code:'invalid_response'},
  {response:{...pdf,headers:[['content-type','text/html']]},code:'mime_mismatch'},
 ];
 for(const {error,response,code} of cases) {
  const f=fixture();let requests=0;
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   recoveryTiming:{wait:async()=>{}},requestHTTP:async()=>{
    requests++;
    if(error)throw Object.assign(Error('download failed'),error);
    return response;
   }});
  assert.equal(requests,1,code);assert.equal(result.pdf.failures[0].code,code);
  assert.equal(result.pdf.registered,false);assert.equal(f.created.length,1);assert.deepEqual(f.uploaded,[]);
 }
});
test('a PDF failure publishes Retry-After and a cooldown budget stop keeps the known HTTP response',async()=>{
 const f=fixture(),original='https://publisher.example/full.pdf',observed=[],requests=[],events=[];
 const cooldown={
  observe(url,status,retryAfter){observed.push({url,status,retryAfter});},
  async wait(url,{validate,authorize}){
   validate();
   if(observed.some(response=>response.url===url))throw Object.assign(Error('Wait exceeds budget'),{
    cooldownBudget:true,diagnostic:{stage:'attachment',code:'http_error',status:503},
   });
   await authorize(false);
  },
 };
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:original}]},
  recoveryTiming:{wait:async()=>{},random:()=>0},
  browser:{cooldown,partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true},
  recordRecovery:(event,details)=>events.push({event,...details}),
  requestHTTP:async(_session,{url})=>{
   requests.push(url);return {status:503,headers:[['retry-after','120']],body:Buffer.alloc(0)};
  }});
 assert.deepEqual(observed,[{url:original,status:503,retryAfter:'120'}]);assert.deepEqual(requests,[original]);
 assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.registered,false);assert.equal(f.created.length,1);
 assert.deepEqual(result.pdf.failures,[{phase:'initial_fetch',code:'http_error',status:503}]);
 assert.equal(events.at(-1).dispatch_outcome,'not_dispatched');
 assert.equal(events.at(-1).recovery_stop,'budget');
});
test('a shared cooldown wake revalidates Import authority and DNS before sending a PDF request',async()=>{
 for(const revoked of ['authority','dns']) {
  const f=fixture();let waited=false,requests=0;
  const cooldown={async wait(_url,{authorize}){waited=true;await authorize(true);return waited;}};
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   browser:{cooldown,partition:{resolveHost:async()=>({endpoints:[{address:waited && revoked==='dns'?'127.0.0.1':'93.184.216.34'}]})},documentCurrent:()=>true},
   validateRecovery:async()=>{if(waited && revoked==='authority')throw Object.assign(Error(),{code:'document_changed'});},
   requestHTTP:async()=>{requests++;throw Error('Unexpected dispatch');}});
  assert.equal(result.pdf.failures[0].code,revoked==='authority'?'document_changed':'unsafe_url');
  assert.equal(result.parent.outcome,'confirmed');assert.equal(requests,0);assert.equal(f.created.length,1);
 }
});
test('a PDF in cooldown leaves the shared download slot available to another origin',{timeout:2000},async t=>{
 const {ImportResources}=require('../src/zotero/import-resources.cjs');
 const resources=new ImportResources({pdfLimit:1,writerLimit:1});
 const f=fixture(),other=fixture(),entered=deferred(),release=deferred(),requests=[];
 const blocked='https://publisher.example/full.pdf',independent='https://other.example/full.pdf';
 let ready=false;
 t.after(()=>release.resolve());
 const cooldown={
  observe(){},
  async wait(url,{deadline,authorize}){
   if(url===blocked && !ready) {
    if(deadline<=Date.now())throw Object.assign(Error(),{cooldownBudget:true});
    entered.resolve();await release.promise;
   }
   await authorize?.();
  },
 };
 const run=(fixture,url)=>fixture.run({item:{...item,attachments:[{mimeType:'application/pdf',url}]},resources,
  browser:{cooldown,partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true},
  requestHTTP:async(_session,{url})=>{requests.push(url);return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};}});
 const blockedResult=run(f,blocked);
 await entered.promise;
 assert.equal((await run(other,independent)).pdf.registered,true);
 assert.deepEqual(requests,[independent]);
 ready=true;release.resolve();
 assert.equal((await blockedResult).pdf.registered,true);
 assert.deepEqual(requests,[independent,blocked]);
});
test('hidden and visible captures of the same normalized URL share the three-attempt PDF limit',async()=>{
 const f=fixture(),original='https://publisher.example/challenge',helpers=[],requests=[];
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:original}]},
  recoveryTiming:{wait:async()=>{},random:()=>0},
  browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
   bypassAttachment:async(url,_doc,{visible})=>{helpers.push({url,visible});return original+'#capture';}},
  requestHTTP:async(_session,{url})=>{
   requests.push(url);
   if(requests.length>1)throw Object.assign(Error(),{code:'timeout'});
   return {status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};
  }});
 assert.deepEqual(requests,[original,original,original]);
 assert.deepEqual(helpers,[{url:original,visible:false},{url:original,visible:true}]);
 assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.registered,false);assert.equal(f.created.length,1);
});
test('a shorter caller deadline bounds hidden, visible and OpenAlex reads in the same PDF recovery window',async()=>{
 const f=fixture(),requests=[],helpers=[];
 let clock=Date.now(),fallbacks=0;
 const deadline=clock+120000,original='https://publisher.example/challenge';
 const hidden='https://cdn.example/hidden.pdf',visible='https://cdn.example/visible.pdf';
 const candidate='https://oa.example/first.pdf';
 const result=await f.run({deadline,recoveryTiming:{now:()=>clock},
  item:{...item,attachments:[{mimeType:'application/pdf',url:original}]},
  browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
   bypassAttachment:async(url,_doc,options)=>{helpers.push({url,...options});clock+=options.visible?40000:30000;return options.visible?visible:hidden;}},
  requestHTTP:async(_session,{url,timeout})=>{
   requests.push([url,timeout]);clock+=url===visible?7000:url===candidate?3000:20000;
   return {status:url===original?403:404,headers:[['content-type','text/html']],body:Buffer.from('error')};
  },
  fallbackPDF:async({signal})=>{fallbacks++;assert.equal(signal.aborted,false);clock+=1000;return {candidates:[candidate,'https://oa.example/unused.pdf']};}});
 assert.deepEqual(requests,[[original,60000],[hidden,60000],[visible,10000],[candidate,2000]]);
 assert.deepEqual(helpers.map(({url,visible,deadline})=>[url,visible,deadline]),[[original,false,deadline],[original,true,deadline]]);
 assert.equal(fallbacks,1);assert.equal(result.pdf.registered,false);
 assert.equal(result.pdf.failures.at(-1).status,404);assert.equal(f.created.length,1);assert.deepEqual(f.uploaded,[]);
});
test('PDF retry waiting stops on cancellation or original Document invalidation',async()=>{
 for(const canceled of [true,false]) {
  const f=fixture(),controller=new AbortController(),waiting=deferred(),release=deferred();
  let current=true,requests=0,fallbacks=0;
  const pending=f.run({signal:controller.signal,item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>current},
   recoveryTiming:{wait:async()=>{waiting.resolve();await release.promise;}},
   requestHTTP:async()=>{requests++;throw Object.assign(Error(),{code:'timeout'});},
   fallbackPDF:async()=>{fallbacks++;return {candidates:[]};}});
  await waiting.promise;if(canceled)controller.abort();else current=false;release.resolve();
  const result=await pending;
  assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.failures[0].code,canceled?'canceled':'document_changed');
  assert.equal(requests,1);assert.equal(fallbacks,0);assert.equal(f.created.length,1);assert.deepEqual(f.uploaded,[]);
 }
});
test('remote Import authority is rechecked after PDF verification and before the attachment POST',async()=>{
 const f=fixture();let downloaded=false,lookups=0;
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'},
  {snapshot:false,url:'https://publisher.example/link'}]},
  validateRecovery:async()=>{if(downloaded)throw Object.assign(Error(),{code:'document_changed'});},
  fallbackPDF:async()=>{lookups++;return {candidates:[]};},
  requestHTTP:async()=>{downloaded=true;return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(pdfFixture)};}});
 assert.equal(result.parent.outcome,'confirmed');
 assert.equal(result.pdf.failures[0].code,'document_changed');assert.equal(result.pdf.registered,false);
 assert.equal(f.created.length,1);assert.equal(lookups,0);assert.deepEqual(f.uploaded,[]);
});
test('authority lost during DNS stops the PDF before dispatch',async()=>{
 const f=fixture();let authorized=true;
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
  browser:{partition:{resolveHost:async()=>{authorized=false;return {endpoints:[{address:'93.184.216.34'}]};}},
   documentCurrent:()=>true},
  validateRecovery:async()=>{if(!authorized)throw Object.assign(Error(),{code:'document_changed'});}});
 assert.equal(result.parent.outcome,'confirmed');
 assert.equal(result.pdf.failures[0].code,'document_changed');
 assert.equal(f.downloads,0);
 assert.equal(f.created.length,1);
});
test('attachment writes recheck authority after native credentials are read',async()=>{
 const {ImportResources}=require('../src/zotero/import-resources.cjs');
 for(const [holdRead,expected] of [[3,['parent']],[4,['parent','child']]]) {
  const f=fixture(),writer=nativeWriter({holdRead});
  let authorized=true;
  const pending=f.run({api:writer.api,resources:new ImportResources({pdfLimit:1,writerLimit:1}),
   item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   validateRecovery:async()=>{if(!authorized)throw Object.assign(Error(),{code:'document_changed'});}});
  await writer.entered.promise;
  authorized=false;
  writer.release.resolve();
  const result=await pending;
  assert.equal(result.parent.outcome,'confirmed');
  assert.equal(result.pdf.registered,false);
  assert.equal(result.pdf.failures[0].code,'document_changed');
  assert.deepEqual(writer.writes,expected);
  assert.equal(result.uncertain_write,undefined);
 }
});
test('cancellation and source changes during hidden recovery block visible helpers and new writes',async()=>{
 for(const duringDownload of [false,true])for(const canceled of [true,false]) {
  const f=fixture(),controller=new AbortController(),helpers=[];let current=true,downloads=0,fallback=0;
  const invalidate=()=>{if(canceled)controller.abort();else current=false;};
  const result=await f.run({signal:controller.signal,item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/challenge'}]},
   browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>current,
    bypassAttachment:async(url,doc,{visible})=>{helpers.push(visible);if(duringDownload)return 'https://cdn.example/captured.pdf';invalidate();throw Error('Hidden helper ended');}},
   fallbackPDF:async()=>{fallback++;return {candidates:[]};},
   requestHTTP:async(_session,spec)=>{downloads++;if(spec.url==='https://cdn.example/captured.pdf'){invalidate();throw Object.assign(Error('Download ended'),{code:'network_error'});}
    return {status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};}});
  assert.equal(result.pdf.registered,false);assert.deepEqual(helpers,[false]);
  assert.equal(downloads,duringDownload?2:1);assert.equal(fallback,0);assert.equal(f.created.length,1);assert.equal(f.uploaded.length,0);
  assert.equal(result.pdf.failures[0].code,canceled?'canceled':'document_changed');
 }
});
test('a helper captured private URL never reaches transport or creates a PDF shell',async()=>{
 const f=fixture();let downloads=0;
 const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/challenge'}]},
  browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34'}]})},documentCurrent:()=>true,
   bypassAttachment:async()=> 'http://127.0.0.1/private.pdf'},
  requestHTTP:async()=>{downloads++;return {status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};}});
 assert.equal(result.pdf.registered,false);assert.equal(downloads,1);assert.equal(f.created.length,1);assert.equal(f.uploaded.length,0);
 assert.equal(result.pdf.failures[0].code,'unsafe_url');
});

test('parallel Local API writes settle independently and uncertainty stops queued writes',async()=>{
 const {ImportResources}=require('../src/zotero/import-resources.cjs');
 const resources=new ImportResources({pdfLimit:1,writerLimit:2});
 const both=deferred(),fail=deferred(),confirm=deferred(),queued=deferred(),writes=[];
 const local=new LocalAPI({store:{read:async()=>({server_id:target.server_id,key:'k'.repeat(32)})},
  transport:async(raw,options)=>{
   const path=new URL(raw).pathname;
   const headers={'Zotero-Server-ID':target.server_id,'X-Zotero-Version':'10.0.6'};
   if(options.method!=='POST')return new Response(path==='/api/'?'Local API':'{}',{headers});
   const object=JSON.parse(options.body)[0];writes.push(object);
   if(writes.length===2)both.resolve();
   if(object.title==='Uncertain'){await fail.promise;throw Error('Lost response');}
   await confirm.promise;
   return new Response(JSON.stringify({successful:{0:{key:object.key,version:1}}}),{headers});
  }});
 const options={resources,api:local};
 const f=fixture(),a=f.run({...options,item:{...item,title:'Uncertain'}});
 const b=f.run({...options,item:{...item,title:'Confirmed'}});
 await both.promise;
 const c=f.run({...options,item:{...item,title:'Queued'},api:{
   validate:async()=>{queued.resolve();return target;},create:(...args)=>local.create(...args),
 }});
 await queued.promise;
 fail.resolve();
 const uncertain=await a;
 const untouched=await c;
 assert.equal(uncertain.parent.outcome,'uncertain');
 assert.equal(uncertain.zotero.parent_key,writes[0].key);
 assert.equal(untouched.parent.outcome,'no_effect');
 assert.deepEqual(writes.map(object=>object.title),['Uncertain','Confirmed']);
 confirm.resolve();
 const confirmed=await b;
 assert.equal(confirmed.parent.outcome,'confirmed');
 assert.equal(confirmed.zotero.parent_key,writes[1].key);
});
