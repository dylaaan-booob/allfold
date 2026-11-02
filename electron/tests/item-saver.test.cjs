'use strict';
const test=require('node:test');
const assert=require('node:assert/strict');
const {saveOnce:runSaveOnce,verifyParent}=require('../src/zotero/item-saver.cjs');
function importContext({pageURL,partition,...args}) {
  return {...args,doc:{url:pageURL,type:'text/html',pageId:7,processId:11,frameToken:'fixture',...args.doc},
    browser:args.browser || {partition,tabs:new Map([[7,{id:7}]]),documentCurrent:()=>true,cookieAdapter:{read:async()=>partition.cookieRows || []}}};
}
const saveOnce=args=>runSaveOnce(importContext(args));
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const hostRequire=require('node:module').createRequire(require.resolve('../src/zotero/item-saver.cjs'));
function attachmentSaver(requestSessionHTTP,observe=()=>{}) {
  let inner;const logs=[];
  const context=vm.createContext({module:{exports:{}},__dirname:path.dirname(require.resolve('../src/zotero/item-saver.cjs')),
    URL,Date,Promise,Buffer,ArrayBuffer,Uint8Array,TextEncoder,TextDecoder,AbortSignal,
    structuredClone,setTimeout,clearTimeout,
    require:name=>name==='../shared/logging.cjs'?{...hostRequire(name),log:(level,event,fields)=>logs.push({level,event,...fields})}:name==='./session-http.cjs'?{requestSessionHTTP}:name==='node:vm'?{...vm,createContext:globals=>{inner=vm.createContext(globals);return inner;}}:hostRequire(name)});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../src/zotero/item-saver.cjs'),'utf8'),context);
  return Object.assign(async args=>{const result=await context.module.exports.saveOnce(importContext(args));observe(inner);return result;},{logs});
}
const item={itemType:'journalArticle',title:'Fixture',DOI:'10.5555/fixture',attachments:[]};
function host(response, {fail=false,hold=null}={}) {
  const calls=[];
  return {calls,partition:{fetch:async(url,options)=>{
    calls.push(url);
    assert.equal(new URL(url).origin,'http://127.0.0.1:23119');
    assert.equal(options.redirect,'error');
    const method=url.split('/').at(-1);
    if(method === 'saveItems') {
      if(hold)await hold;
      if(fail)throw Object.assign(Error('offline'),{status:0});
      const request=JSON.parse(options.body);
      return new Response(response?JSON.stringify(response(request)):null,{status:201,
        headers:{'Content-Type':'application/json'}});
    }
    if(method === 'hasAttachmentResolvers')return new Response('false',{status:200,headers:{'Content-Type':'application/json'}});
    if(method === 'getSelectedCollection')return new Response('{"filesEditable":false}',{status:200});
    throw Error('Unexpected request');
  }}};
}
test('unmodified ItemSaver saves exactly one parent and leaves PDF unverified',async()=>{
  const local=host(request=>({items:[{id:request.items[0].id}]}));
  const result=await saveOnce({item,doi:item.DOI,pageURL:'https://example.org/paper',partition:local.partition});
  assert.equal(result.parent.outcome,'confirmed');assert.equal(result.pdf.outcome,'unverified');
  assert.equal(result.settled,true);assert.equal(local.calls.filter(u=>u.endsWith('/saveItems')).length,1);
});
test('network status zero is normalized and never invokes the upstream cloud fallback',async()=>{
  const local=host(null,{fail:true});
  const result=await saveOnce({item,doi:item.DOI,pageURL:'https://example.org/paper',partition:local.partition});
  assert.equal(result.parent.outcome,'uncertain');assert.equal(local.calls.length,1);
});
test('mismatched acceptance identity is uncertain and does not start attachments',async()=>{
  const local=host(()=>({items:[{id:'another-parent'}]}));
  const result=await saveOnce({item,doi:item.DOI,pageURL:'https://example.org/paper',partition:local.partition});
  assert.equal(result.parent.outcome,'uncertain');assert.equal(local.calls.length,1);
});
test('native operation does not settle before parent endpoint completes',async()=>{
  let finish;const hold=new Promise(resolve=>finish=resolve);
  const local=host(null,{hold});let settled=false;
  const pending=saveOnce({item,doi:item.DOI,pageURL:'https://example.org/paper',partition:local.partition}).then(r=>{settled=true;return r;});
  await new Promise(resolve=>setTimeout(resolve,10));assert.equal(settled,false);
  finish();assert.equal((await pending).parent.outcome,'confirmed');
});
test('a different DOI is rejected before accessing Zotero',async()=>{
  const local=host();
  await assert.rejects(saveOnce({item,doi:'10.5555/other',pageURL:'https://example.org',partition:local.partition}));
  assert.equal(local.calls.length,0);
});

test('attachment HTTP and network failures leave the accepted parent confirmed without replay',async t=>{
  for(const failure of ['http','network'])await t.test(failure,async()=>{
    const local=host(request=>({items:[{id:request.items[0].id}]}));
    const originalFetch=local.partition.fetch;
    local.partition.fetch=(url,options)=>url.endsWith('/getSelectedCollection')
      ?new Response('{"filesEditable":true}',{status:200,headers:{'Content-Type':'application/json'}}):originalFetch(url,options);
    let requests=0;
    const saveAttachment=attachmentSaver(async(session)=>{
      requests++;assert.equal(session,local.partition);
      if(failure==='network')throw Error('ERR_CONNECTION_RESET');
      return {status:403,url:'https://publisher.example/paper.pdf',
        headers:[['content-type','text/html']],body:Buffer.from('Forbidden')};
    });
    const result=await saveAttachment({item:{...item,attachments:[{mimeType:'application/pdf',
      title:'Full Text PDF',url:'https://publisher.example/paper.pdf'}]},doi:item.DOI,
      pageURL:'https://publisher.example/paper',partition:local.partition});
    assert.equal(result.parent.outcome,'confirmed');assert.equal(result.parent.status,201);
    assert.equal(result.pdf.outcome,'unverified');assert.equal(result.settled,true);
    assert.equal(requests,1);assert.equal(local.calls.filter(url=>url.endsWith('/saveItems')).length,1);
    assert.equal(local.calls.some(url=>url.includes('/saveAttachment?')),false);
    assert.equal(result.pdf.receipts.length,1);assert.equal(result.pdf.receipts[0].endpoint_completed,false);
  });
});



