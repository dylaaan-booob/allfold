'use strict';
const {validateTarget,KEY}=require('./local-api.cjs');
function sameLibrary(value,target) {
 return value?.type===target.library_type && (target.library_type==='user'? /^\d+$/.test(String(value.id)):String(value.id)===target.library_id);
}
function objectData(value,key,target) {
 if(!value || value.key!==key || value.data?.key!==key || !sameLibrary(value.library,target))throw Object.assign(Error(),{code:'invalid_response'});
 return value.data;
}
const normalize=value=>String(value || '').trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i,'').toLowerCase();
async function reconcileImport(result,{api,doi}) {
 const observed={item_exists:null,pdf_attached:null,pdf_source:null,fallback_used:null,query_diagnostic:null};
 const known=result.zotero,key=known?.parent_key;
 if(!KEY.test(key || '')) {
   if(result.parent?.outcome==='no_effect')Object.assign(observed,{item_exists:false,pdf_attached:false,pdf_source:'none',fallback_used:false});
   return observed;
 }
 try {
   const target=validateTarget(known.target);
   let parent;
   try {parent=objectData(await api.read(target,'/items/'+key),key,target);}
   catch(error){if(error.code==='target_missing' && result.parent?.outcome!=='uncertain'){Object.assign(observed,{item_exists:false,pdf_attached:false,pdf_source:'none',fallback_used:false});return observed;}throw error;}
   if(['attachment','note'].includes(parent.itemType) || normalize(parent.DOI)!==normalize(doi))throw Object.assign(Error(),{code:'invalid_response'});
   observed.item_exists=true;
   const children=await api.read(target,'/items/'+key+'/children');
   if(!Array.isArray(children))throw Object.assign(Error(),{code:'invalid_response'});
   const records=new Map();
   for(const child of children) {
     if(!KEY.test(child?.key || ''))throw Object.assign(Error(),{code:'invalid_response'});
     records.set(child.key,objectData(child,child.key,target));
   }
   const receipts=result.pdf?.receipts || [],registered=receipts.filter(receipt=>receipt.registered===true && receipt.endpoint_completed===true
     && known.attachment_keys.includes(receipt.key) && ['translator','openalex'].includes(receipt.source));
   if(result.pdf?.registered===true && !registered.length)throw Object.assign(Error(),{code:'invalid_response'});
   const attached=registered.find(receipt=>{const data=records.get(receipt.key);return data?.itemType==='attachment' && data.parentItem===key
     && data.contentType==='application/pdf' && ['imported_url','imported_file'].includes(data.linkMode);});
   if(attached)Object.assign(observed,{pdf_attached:true,pdf_source:attached.source,fallback_used:attached.source==='openalex'});
   else if(!receipts.some(receipt=>receipt.registered!==true || receipt.endpoint_completed!==true))Object.assign(observed,{pdf_attached:false,pdf_source:'none',fallback_used:false});
 } catch(error) {
   const codes=new Set(['connection_lost','timeout','server_id_mismatch','target_missing','access_denied','invalid_response']);
   observed.query_diagnostic={code:codes.has(error.code)?error.code:'api_failure',...(Number.isInteger(error.status)?{status:error.status}:{})};
 }
 return observed;
}
module.exports={reconcileImport};
