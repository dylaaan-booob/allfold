'use strict';
const {app,session,protocol}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-translator-profile-'));app.setPath('userData',profile);
protocol.registerSchemesAsPrivileged([{scheme:'allfold-zotero',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
const {TranslatorSandbox}=require('../src/zotero/translator.cjs');
const doi='10.5555/offline-runtime',url='https://offline.invalid/article';
const html='<!doctype html><html><head><title>Offline Web Translation</title>'
  +'<meta name="citation_title" content="Offline Web Translation"><meta name="citation_doi" content="'+doi+'">'
  +'<meta name="citation_author" content="Smith, Alex"><meta name="citation_date" content="2026-03-14">'
  +'<meta name="citation_journal_title" content="Offline Journal"><meta name="citation_pdf_url" content="https://offline.invalid/article.pdf">'
  +'</head><body>Offline document</body></html>';
let sandbox;
app.whenReady().then(async()=>{
  const partition=session.fromPartition('allfold-offline-source'),requests=[];
  // This synthetic protocol is the only publisher/DOI transport; no Zotero or network endpoint is contacted.
  await partition.protocol.handle('https',request=>{
    requests.push({url:request.url,method:request.method,accept:request.headers.get('Accept')});
    assert.equal(request.method,'GET');assert.equal(new URL(request.url).hostname,'doi.org');
    return new Response(JSON.stringify({type:'article-journal',DOI:doi,title:'Offline DOI Translation',
      'container-title':'Offline Journal',author:[{family:'Smith',given:'Alex'}],issued:{'date-parts':[[2026,3,14]]}}),
      {status:200,headers:{'Content-Type':'application/vnd.citationstyles.csl+json'}});
  });
  const doc={pageId:7,url,html,frameToken:'offline-document'};
  const browser={partition,tabs:new Map(),documentCurrent:value=>value.frameToken===doc.frameToken,
    translationDocuments:async()=>[doc],pageCookie:async()=>''};
  sandbox=new TranslatorSandbox();await sandbox.init(browser);
  const result=await sandbox.translate(doc,doi);
  assert.equal(result.metadataSource,'web');assert.equal(result.item.title,'Offline Web Translation');assert.equal(result.apiItem.DOI,doi);
  assert.ok(result.item.attachments.some(item=>item.mimeType==='application/pdf'));
  const enriched=await sandbox.translate(doc,doi,{forEnrichment:true});
  assert.deepEqual(enriched.item.date_parts,{year:2026,month:3,day:14});assert.equal(enriched.apiItem,undefined);
  const blank={...doc,html:'<!doctype html><html><head><title>No metadata</title></head><body>Empty</body></html>'};
  browser.translationDocuments=async()=>[blank];
  const negotiated=await sandbox.translate(blank,doi);
  assert.equal(negotiated.metadataSource,'doi');assert.equal(negotiated.item.title,'Offline DOI Translation');assert.equal(negotiated.apiItem.DOI,doi);
  assert.equal(requests.length,1);assert.match(requests[0].accept,/csl\+json/);
  const operation=await sandbox.openOperation(doc);
  try {
    const capabilities=await sandbox.window.webContents.executeJavaScript('({count:window.allfoldTranslator.count,writer:typeof Zotero.ItemSaver,connector:typeof Zotero.Connector,botBypass:typeof Zotero.BotBypass,virtualSaver:typeof Zotero.Translate.ItemSaver})');
    assert.deepEqual(capabilities,{count:752,writer:'undefined',connector:'undefined',botBypass:'undefined',virtualSaver:'function'});
  }finally{await sandbox.endOperation(operation);}
  console.log('OFFICIAL TRANSLATOR RUNTIME PASS');sandbox.close();app.quit();
}).catch(error=>{console.error(error);sandbox?.close();app.exit(1);});
app.on('will-quit',()=>fs.rmSync(profile,{recursive:true,force:true}));
