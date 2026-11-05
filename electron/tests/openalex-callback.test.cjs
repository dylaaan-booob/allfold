'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {requestOpenAlexPDF,settleOpenAlexPDF}=require('../src/zotero/openalex-callback.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'user',library_id:'0',collection_key:null};
test('a valid provider response is not discarded by a separate bridge deadline',async()=>{
 const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),timers=new Map();
 const context=vm.createContext({module:{exports:{}},require:name=>name==='node:crypto'?require(name):require('../src/zotero/local-api.cjs'),
  setTimeout(callback,ms){const timer={callback,ms};timers.set(timer,callback);return timer;},clearTimeout(timer){timers.delete(timer);}});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/zotero/openalex-callback.cjs'),'utf8'),context);
 const current={id:'slow',action:'import_paper',controller:new AbortController()},sent=[],data={doi:'10.5555/slow',target,parent_key:'ABCDEFGH'};
 const pending=context.module.exports.requestOpenAlexPDF(current,data,{send:value=>sent.push(value),connected:true,doi:data.doi,target});
 for(const timer of [...timers.keys()])if(timer.ms<=100001)timer.callback();
 await Promise.resolve();
 assert.equal(context.module.exports.settleOpenAlexPDF(current,{...sent[0],data:{candidates:['https://oa.example/full.pdf']}}),true);
 assert.equal((await pending).candidates[0],'https://oa.example/full.pdf');
});
test('OA callback receives only its exact pending Import response and cancellation settles without candidates',async()=>{
 const current={id:'import1',action:'import_paper',controller:new AbortController()},sent=[];
 const data={doi:'10.5555/fixture',target,parent_key:'ABCDEFGH'};
 const pending=requestOpenAlexPDF(current,data,{send:value=>sent.push(value),connected:true,doi:data.doi,target});
 assert.equal(sent.length,1);assert.deepEqual(sent[0].data,data);
 assert.equal(settleOpenAlexPDF(current,{...sent[0],id:'stale',data:{candidates:['https://oa.example/a.pdf']}}),false);
 current.controller.abort();assert.deepEqual(await pending,{candidates:[],diagnostic:{code:'canceled'}});
 assert.equal(settleOpenAlexPDF(current,{...sent[0],data:{candidates:['https://oa.example/a.pdf']}}),false);
});
