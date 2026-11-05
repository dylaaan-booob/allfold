'use strict';
const {randomBytes}=require('node:crypto');
const {validateTarget,KEY}=require('./local-api.cjs');
// A narrow submessage of the active Import, never a standalone RPC or writer.
async function requestOpenAlexPDF(current,data,{send,connected,doi,target}) {
 const empty=code=>({candidates:[],diagnostic:{code}});
 if(!connected || current.action!=='import_paper' || current.controller.signal.aborted || current.openalexRequested)return empty('canceled');
 if(data.doi!==doi || JSON.stringify(validateTarget(data.target))!==JSON.stringify(validateTarget(target)) || !KEY.test(data.parent_key))throw Error('OpenAlex Import context mismatch');
 current.openalexRequested=true;
 const lookupId=randomBytes(16).toString('hex'),signal=current.controller.signal;
 let cancel;
 try {
   return await new Promise(resolve=>{
     cancel=()=>resolve(empty('canceled'));
     current.openalex={id:lookupId,resolve,cancel};
     signal.addEventListener('abort',cancel,{once:true});
     if(signal.aborted){cancel();return;}
     try {send({type:'openalex_pdf',id:current.id,action:current.action,lookup_id:lookupId,data:{doi,target:validateTarget(target),parent_key:data.parent_key}});}
     catch{resolve(empty('connection_lost'));}
   });
 } finally {
   signal.removeEventListener('abort',cancel);
   if(current.openalex?.id===lookupId)current.openalex=null;
 }
}
function settleOpenAlexPDF(current,message) {
 if(!current || current.controller.signal.aborted || current.action!=='import_paper' || current.id!==message.id
   || current.action!==message.action || !current.openalex || current.openalex.id!==message.lookup_id)return false;
 const data=message.data;
 if(!data || !Array.isArray(data.candidates) || data.candidates.length>4 || !data.candidates.every(url=>typeof url==='string'))throw Error('Invalid OpenAlex result');
 current.openalex.resolve(data);return true;
}
module.exports={requestOpenAlexPDF,settleOpenAlexPDF};
