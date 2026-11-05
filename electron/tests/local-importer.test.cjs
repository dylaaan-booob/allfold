'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {saveOnce}=require('../src/zotero/local-importer.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'group',library_id:'12',collection_key:'ABCDEFGH'};
const item={itemType:'journalArticle',title:'Fixture',DOI:'10.5555/fixture',attachments:[]};
function fixture(options={}) {
 const created=[],uploaded=[];let calls=0;
 const api={validate:async()=>target,create:async(t,value)=>{created.push(value);if(options.failParent && created.length===1)throw Object.assign(Error(),{code:'connection_lost'});return {key:value.key,status:200};},upload:async(t,key,bytes,metadata)=>{uploaded.push({key,bytes,metadata});if(options.failUpload)throw Error('upload failed');return {registered:true};}};
 return {created,uploaded,run:overrides=>saveOnce({item,doi:item.DOI,target,api,doc:{pageId:7,url:'https://publisher.example/paper'},browser:{partition:{},documentCurrent:()=>true,cookieAdapter:{},bypassAttachment:async()=>{}},requestHTTP:async()=>{calls++;return {status:200,url:'https://publisher.example/full.pdf',headers:[['content-type','application/pdf']],body:Buffer.from('%PDF-1.7\nfixture')};},...overrides}),get downloads(){return calls;}};
}
test('native import preallocates parent identity and uses the explicit collection',async()=>{
 const f=fixture(),result=await f.run();assert.equal(result.parent.outcome,'confirmed');assert.equal(f.created.length,1);
 assert.equal(f.created[0].version,0);assert.deepEqual(f.created[0].collections,['ABCDEFGH']);assert.equal(result.zotero.parent_key,f.created[0].key);
});
test('uncertain parent keeps known key, settles, and never starts attachments or replays',async()=>{
 const f=fixture({failParent:true}),result=await f.run({item:{...item,attachments:[{mimeType:'application/pdf',url:'https://publisher.example/full.pdf'}]}});
 assert.equal(result.parent.outcome,'uncertain');assert.equal(f.created.length,1);assert.equal(f.downloads,0);assert.ok(result.zotero.parent_key);assert.equal(result.settled,true);
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
});
