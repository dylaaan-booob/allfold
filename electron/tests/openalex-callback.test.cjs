'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {requestOpenAlexPDF,settleOpenAlexPDF}=require('../src/zotero/openalex-callback.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'user',library_id:'0',collection_key:null};
test('OA callback receives only its exact pending Import response and cancellation settles without candidates',async()=>{
 const current={id:'import1',action:'import_paper',controller:new AbortController()},sent=[];
 const data={doi:'10.5555/fixture',target,parent_key:'ABCDEFGH'};
 const pending=requestOpenAlexPDF(current,data,{send:value=>sent.push(value),connected:true,doi:data.doi,target});
 assert.equal(sent.length,1);assert.deepEqual(sent[0].data,data);
 assert.equal(settleOpenAlexPDF(current,{...sent[0],id:'stale',data:{candidates:['https://oa.example/a.pdf']}}),false);
 current.controller.abort();assert.deepEqual(await pending,{candidates:[],diagnostic:{code:'canceled'}});
 assert.equal(settleOpenAlexPDF(current,{...sent[0],data:{candidates:['https://oa.example/a.pdf']}}),false);
});
