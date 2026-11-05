'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const {reconcileImport}=require('../src/zotero/last-import.cjs');
const target={server_id:'SERVERFIXTUR',library_type:'group',library_id:'12',collection_key:null};
const parent={key:'ABCDEFGH',library:{type:'group',id:12},data:{key:'ABCDEFGH',itemType:'journalArticle',DOI:'10.5555/fixture'}};
const child={key:'BCDEFGHI',library:{type:'group',id:12},data:{key:'BCDEFGHI',itemType:'attachment',parentItem:'ABCDEFGH',contentType:'application/pdf',linkMode:'imported_url',md5:'ignored',filename:'/never/read'}};
function result(registered=true,source='openalex'){return {parent:{outcome:'confirmed'},zotero:{target,parent_key:parent.key,attachment_keys:[child.key],note_keys:[]},pdf:{registered,source:registered?source:null,receipts:registered?[{key:child.key,registered:true,endpoint_completed:true,source}]:[]}};}
test('Last Import reconciles exact parent and registered PDF through object reads only',async()=>{
 const reads=[],api={read:async(t,path)=>{assert.deepEqual(t,target);reads.push(path);return path.endsWith('/children')?[child]:parent;}};
 const actual=await reconcileImport(result(),{api,doi:'10.5555/fixture'});
 assert.deepEqual(actual,{item_exists:true,pdf_attached:true,pdf_source:'openalex',fallback_used:true,query_diagnostic:null});
 assert.deepEqual(reads,['/items/ABCDEFGH','/items/ABCDEFGH/children']);
});
test('shells, foreign objects and query failures cannot become PDF Yes',async()=>{
 for(const [value,children,throws,expected] of [
   [result(false),[child],false,false], [result(),[{...child,library:{type:'group',id:13}}],false,null],
   [result(),[child],true,null], [result(),[],false,false]]) {
   const actual=await reconcileImport(value,{doi:'10.5555/fixture',api:{read:async(_t,path)=>{if(throws)throw Object.assign(Error(),{code:'connection_lost'});return path.endsWith('/children')?children:parent;}}});
   assert.equal(actual.pdf_attached,expected);assert.equal(actual.fallback_used,expected===null?null:false);
 }
});
test('ambiguous registration stays unknown even when its shell is present',async()=>{
 const value=result(false);value.pdf.receipts=[{key:child.key,registered:false}];
 const actual=await reconcileImport(value,{doi:'10.5555/fixture',api:{read:async(_t,path)=>path.endsWith('/children')?[child]:parent}});
 assert.equal(actual.item_exists,true);assert.equal(actual.pdf_attached,null);assert.equal(actual.fallback_used,null);
});
