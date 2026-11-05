'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {saveOnce}=require('../src/zotero/local-importer.cjs');
const {LocalAPI}=require('../src/zotero/local-api.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'group',library_id:'12',collection_key:'ABCDEFGH'};
const item={itemType:'journalArticle',title:'Fixture',DOI:'10.5555/fixture',attachments:[]};
function fixture(options={}) {
 const created=[],uploaded=[];let calls=0;
 const api={validate:async()=>target,create:async(t,value)=>{created.push(value);if(options.failParent && created.length===1)throw Object.assign(Error(),{code:'connection_lost'});return {key:value.key,status:200};},upload:async(t,key,bytes,metadata)=>{uploaded.push({key,bytes,metadata});if(options.failUpload)throw Error('upload failed');return {registered:true};}};
 return {created,uploaded,run:overrides=>saveOnce({item,doi:item.DOI,target,api,doc:{pageId:7,url:'https://publisher.example/paper'},browser:{partition:{resolveHost:async()=>({endpoints:[{address:'93.184.216.34',family:'ipv4'}]})},documentCurrent:()=>true,cookieAdapter:{},bypassAttachment:async()=>{}},requestHTTP:async()=>{calls++;return {status:200,url:'https://publisher.example/full.pdf',headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')};},...overrides}),get downloads(){return calls;}};
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
 requestHTTP:async(session,spec,context)=>{requests.push({spec,context});return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')};}});
 assert.equal(requests.length,1);assert.equal(requests[0].spec.url,'https://publisher.example/current.pdf');assert.deepEqual(requests[0].spec.headers,{});assert.equal(requests[0].context.maxRedirects,8);assert.ok(requests[0].context.maxBytes);
 assert.equal(requests[0].spec.referrerPolicy,'origin-when-cross-origin');
});
test('Translator success never looks up OA; failed downloads try bounded unique OA candidates until registration',async()=>{
 for(const translatorOK of [true,false]) {
  const f=fixture(),downloads=[],lookup=[];
  const result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]},
   fallbackPDF:async data=>{lookup.push(data);return {candidates:['https://oa.example/bad.pdf','https://oa.example/bad.pdf','https://oa.example/good.pdf','https://oa.example/unused.pdf']};},
   requestHTTP:async(_session,spec)=>{downloads.push(spec);return {status:translatorOK || spec.url.includes('good')?200:404,headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')};}});
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
   ?{status:200,headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')}
   :{status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};}});
 assert.equal(result.pdf.registered,true);assert.deepEqual(helpers,[false]);
 assert.deepEqual(downloads,['https://publisher.example/challenge',captured]);
 assert.equal(f.created.length,2);assert.equal(f.uploaded.length,1);assert.equal(f.uploaded[0].bytes.toString(),'%PDF-1.7\nfixture');
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
    body:Buffer.from(spec.url===captured?'%PDF-1.7\nfixture':'<html>Verify access</html>')};}});
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
   ?{status:200,headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')}
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
   requestHTTP:async(_session,spec)=>{
    downloads.push(spec.url);
    if(spec.url===original)return {status:403,headers:[['content-type','text/html']],body:Buffer.from('challenge')};
    if(spec.url===hidden && failure!=='mime_mismatch')throw Object.assign(Error('Hidden download failed'),{code:failure});
    return {status:200,headers:[['content-type','application/pdf']],body:Buffer.from(spec.url===hidden?'invalid PDF':'%PDF-1.7\nfixture')};
   }});
  assert.equal(result.pdf.registered,true,failure);
  assert.deepEqual(helpers,[{url:original,visible:false},{url:original,visible:true}],failure);
  assert.deepEqual(downloads,[original,hidden,visible],failure);
  assert.equal(f.created.length,2);assert.equal(f.uploaded.length,1);assert.equal(f.uploaded[0].bytes.toString(),'%PDF-1.7\nfixture');
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
