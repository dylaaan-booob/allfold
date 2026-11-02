'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function fixture(level) {
  const output=[];
  const context=vm.createContext({module:{exports:{}},Date,URL,
    process:{env:level?{ALLFOLD_LOG_LEVEL:level}:{},stderr:{write:line=>output.push(JSON.parse(line))}}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/shared/logging.cjs'),'utf8'),context);
  return {...context.module.exports,output};
}

test('safe Translator and HTTP summaries survive while Cookie, marker and payload never do',()=>{
  const f=fixture('debug');
  const summary={metadata_source:'doi',attachment_phase:'refetch',translator:'Fixture',translator_id:'official-id',item_count:0,first_doi:'10.5555/first',
    content_type:'application/x-research-info-systems',response_bytes:12,challenge:'cf-mitigated',transport_code:'timeout',attachment_count:2,pdf_attachment_count:1,
    error_kind:'host_api_missing',error_name:'TypeError',api_name:'HTTP.processDocuments'};
  f.log('warn','translation_failed',{...summary,Cookie:'SECRET',token:'SECRET',headers:{Authorization:'SECRET'},body:'SECRET',error:Error('SECRET')});
  for(const [key,value] of Object.entries(summary))assert.equal(f.output[0][key],value);
  assert.doesNotMatch(JSON.stringify(f.output),/SECRET|Cookie|Authorization/);
  const counts=f.attachmentCounts([{attachments:[{mimeType:'application/pdf'},{mimeType:'text/html'}]}]);
  assert.equal(counts.attachment_count,2);assert.equal(counts.pdf_attachment_count,1);
  assert.equal(f.attachmentCounts([{attachments:[]}]).pdf_attachment_count,0);
});
