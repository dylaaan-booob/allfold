'use strict';
const {app,session,protocol}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-translator-profile-'));app.setPath('userData',profile);
protocol.registerSchemesAsPrivileged([{scheme:'allfold-zotero',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
const {TranslatorSandbox}=require('../src/zotero/translator.cjs');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {newTaskPage}=require('../src/workflows/browser-operations.cjs');
const doi='10.5555/offline-runtime',url='https://offline.invalid/article';
const html='<!doctype html><html><head><title>Offline Web Translation</title>'
  +'<meta name="citation_title" content="Offline Web Translation"><meta name="citation_doi" content="'+doi+'">'
  +'<meta name="citation_author" content="Smith, Alex"><meta name="citation_date" content="2026-03-14">'
  +'<meta name="citation_journal_title" content="Offline Journal"><meta name="citation_pdf_url" content="https://offline.invalid/article.pdf">'
  +'</head><body><section class="publication-history"><ul class="rlist">'
  +'<li>Manuscript received: 29 February 2024</li><li>Manuscript accepted: 2024-03</li>'
  +'</ul></section></body></html>';
let sandbox;
const historyKinds=['received','accepted'];
const received='<li>Manuscript received: 29 February 2024</li>';
const accepted='<li>Manuscript accepted: 2024-03</li>';
const history=(rows='')=>'<section class="publication-history"><ul class="rlist">'+rows+'</ul></section>';
const article=(body,metadata=html.split('</head>')[0])=>metadata+'</head><body>'+body+'</body></html>';
const later=script=>'<script>setTimeout(()=>{'+script+'},1500)</script>';

async function browserHistory() {
  const browser=new BrowserRuntime();
  // Reuse the official sandbox. All live document traffic stays in the synthetic partition.
  sandbox.browser=browser;
  const fixturePages={
    '/late': article(history(received)+later('document.querySelector("ul").insertAdjacentHTML("beforeend",'+JSON.stringify(accepted)+')')),
    '/cancel': article(history(received)),
    '/replaced': article(history(received)+later('location.replace("/replacement")')),
    '/replacement': article(history(received+accepted)),
    '/doi-change': article(history(received)+later('document.querySelector("meta[name=citation_doi]").content="10.5555/other"')),
    // The frame shares the root URL without a recursive frame request. This
    // lets the official registry run Embedded Metadata on the child document.
    '/child': article(history(received)+'<script>window.history.replaceState(null,"","/child-replaced")</script>'),
    '/child-replaced': '<title>Frame host</title><iframe src="/child"></iframe>'
      +later('document.querySelector("iframe").replaceWith(Object.assign(document.createElement("iframe"),{src:"/replacement"}))'),
    '/isolated-frames': article(history(received)+'<iframe src="/accepted-only"></iframe>'),
    '/accepted-only': article(history(accepted)),
    '/accepted-rdf': article(history(accepted),html.split('</head>')[0]
      +'<meta name="dcterms.dateAccepted" content="2024-03"><meta name="dcterms.dateSubmitted" content="2024-02-29">'),
    '/no-history': article(later('setTimeout(()=>document.body.insertAdjacentHTML("beforeend",'
      +JSON.stringify(history(received+accepted))+'),30000)')),
    '/templates': article(
      '<li class="c-bibliographic-information__list-item"><p>Received<span class="u-hide"> on</span> '
      +'<span class="c-bibliographic-information__value"><time datetime="2023-01-02">2 January 2023</time></span></p></li>'
      +'<li class="c-bibliographic-information__list-item"><p>Accepted '
      +'<span class="c-bibliographic-information__value"><time datetime="2023-01-03">4 January 2023</time></span></p></li>'
      +'<div class="Summary__dates"><div><p class="h5">Received</p><p>2019</p></div>'
      +'<div><p class="h5">Accepted</p><p>Feb 29, 2023</p></div></div>'
      +'<div id="artText"><div class="articleinfo"><p><strong>Received:</strong> 5 April 2022; '
      +'<strong>Revised Received:</strong> 1 May 2022; <strong>Accepted:</strong> April 2022;</p></div></div>'
      +'<section class="article-section"><h3 class="article-section__header_text">Publication history</h3>'
      +'<div class="article-section__body"><ol class="list list--bullet">'
      +'<li>Accepted: <time datetime="March 2, 2020">March 2, 2020</time></li>'
      +'<li>Accepted Manuscript Published: <time datetime="2020-03-03">March 3, 2020</time></li>'
      +'</ol></div></section>'
      +'<li data-testid="publication-history-item">Accepted: <span data-testid="publication-date-label">2021-10-31</span></li>'
      +'<li data-testid="publication-history-item">Accepted: <span data-testid="publication-date-label">2021-10-31</span></li>'
      +history(received+'<li>Revised: 2024-01-01</li><li>Submitted: 2020</li><li>Accepted: March 4</li>')
      +'<div class="pub-history-wrap"><div class="history-entry"><div class="wi-state">Received:</div>'
      +'<div class="wi-date">01 March 2024</div></div></div>'
      +'<div class="itemPageRangeHistory"><span>Received 10 Mar 2026</span><span>Accepted author version posted online: 10 Jun 2026</span></div>'
      +'<ul class="article-chapter-history-list"><li><span>Accepted:</span>March 17, 2026</li></ul>'
      +'<section class="core-history"><div><b>Accepted</b>: 11 April 2025</div></section>'
      +'<div id="article-dates"><div class="article-dates"><nobr>Received: 21 Jan 2025</nobr></div></div>'
      +'<div id="article-information"><dl class="article-dates"><dt>Received</dt><dd><time datetime="2024-12-01">December 1, 2024</time></dd>'
      +'<dt>Accepted</dt><dd>January 14, 2025</dd></dl></div>'
      +'<p>Received: 1999</p><aside><p>Accepted: 1998</p></aside><section id="references"><p>Accepted: 1997</p></section>'),
  };
  await browser.ready;
  await browser.partition.protocol.handle('https',request=>{
    const url=new URL(request.url);
    const text=url.hostname==='offline.invalid' && fixturePages[url.pathname];
    return new Response(text || 'Unknown isolated fixture',{status:text?200:404,headers:{'Content-Type':'text/html'}});
  });
  async function translate(name,kinds=historyKinds,{cancel=false,deadline}={}) {
    const controller=new AbortController(),{signal}=controller;
    browser.beginOperation(signal);browser.operation.action='enrich_paper';
    const tab=await newTaskPage(browser,signal);
    try {
      const doc=await browser.navigate('https://offline.invalid/'+name,{signal,deadline:Date.now()+5000});
      browser.enterBusiness();
      const started=Date.now();
      const timer=cancel?setTimeout(()=>controller.abort(),350):null;
      try {
        const result=await sandbox.translate(doc,doi,{forEnrichment:true,historyKinds:kinds,signal,deadline});
        return {result,elapsed:Date.now()-started};
      } finally {clearTimeout(timer);}
    } finally {browser.endTask();tab.view.webContents.close();}
  }
  const facts=result=>result.dateCandidates.map(({kind,value})=>[kind,value]);
  try {
    const immediate=await translate('templates');
    assert.ok(immediate.elapsed<1500,'complete history should return without polling');
    assert.deepEqual(facts(immediate.result).sort(),[
      ['received','2023-01-02'],['received','2019'],['received','2022-04-05'],['accepted','2022-04'],
      ['accepted','2020-03-02'],['accepted','2021-10-31'],['received','2024-02-29'],
      ['received','2024-03-01'],['received','2026-03-10'],['accepted','2026-03-17'],
      ['accepted','2025-04-11'],['received','2025-01-21'],
      ['received','2024-12-01'],['accepted','2025-01-14'],
    ].sort());
    assert.ok(immediate.result.dateCandidates.every(item=>item.url==='https://offline.invalid/templates' && item.record_id===doi));
    const late=await translate('late');
    assert.deepEqual(facts(late.result),[['received','2024-02-29'],['accepted','2024-03']]);
    assert.ok(late.elapsed>=1250);
    const already=await translate('isolated-frames',['received']);
    assert.deepEqual(facts(already.result),[['received','2024-02-29']]);
    const rdf=await translate('accepted-rdf',['accepted']);
    assert.equal(rdf.result.item.accepted,'2024-03');
    assert.deepEqual(rdf.result.dateCandidates,[{
      kind:'accepted',value:'2024-03',source_label:'Manuscript accepted:',
      url:'https://offline.invalid/accepted-rdf',record_id:doi,
    }]);
    await assert.rejects(translate('cancel',historyKinds,{cancel:true}),{message:'canceled'});
    for(const name of ['replaced','child-replaced','doi-change'])
      await assert.rejects(translate(name),{message:'document_changed'},name);
    const bounded=await translate('no-history');
    assert.ok(bounded.elapsed>=29500 && bounded.elapsed<32000,'optional date work should end after 30 seconds');
    assert.equal(bounded.result.metadataSource,'web');
    assert.deepEqual(facts(bounded.result),[]);
  } finally {browser.close();}
}
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
  assert.equal(result.dateCandidates,undefined);
  assert.equal(result.item.received,undefined);
  assert.equal(result.apiItem.accepted,undefined);
  const enriched=await sandbox.translate(doc,doi,{forEnrichment:true,historyKinds:['received','accepted']});
  assert.deepEqual(enriched.item.date_parts,{year:2026,month:3,day:14});assert.equal(enriched.apiItem,undefined);
  assert.deepEqual(enriched.dateCandidates.map(({kind,value,url})=>[kind,value,url]),[
    ['received','2024-02-29',url],['accepted','2024-03',url],
  ]);
  const blank={...doc,html:'<!doctype html><html><head><title>No metadata</title></head><body>Empty</body></html>'};
  browser.translationDocuments=async()=>[blank];
  const negotiated=await sandbox.translate(blank,doi);
  assert.equal(negotiated.metadataSource,'doi');assert.equal(negotiated.item.title,'Offline DOI Translation');assert.equal(negotiated.apiItem.DOI,doi);
  assert.equal(requests.length,1);assert.match(requests[0].accept,/csl\+json/);
  browser.translationDocuments=async()=>[{...doc,html:html.replace(doi,'10.5555/other')}];
  const doiOnly=await sandbox.translate(doc,doi,{forEnrichment:true,historyKinds});
  assert.equal(doiOnly.metadataSource,'doi');assert.equal(doiOnly.dateCandidates,undefined);
  const operation=await sandbox.openOperation(doc);
  try {
    const capabilities=await sandbox.window.webContents.executeJavaScript('({count:window.allfoldTranslator.count,writer:typeof Zotero.ItemSaver,connector:typeof Zotero.Connector,botBypass:typeof Zotero.BotBypass,virtualSaver:typeof Zotero.Translate.ItemSaver})');
    assert.deepEqual(capabilities,{count:752,writer:'undefined',connector:'undefined',botBypass:'undefined',virtualSaver:'function'});
  }finally{await sandbox.endOperation(operation);}
  await browserHistory();
  console.log('OFFICIAL TRANSLATOR RUNTIME PASS');sandbox.close();app.quit();
}).catch(error=>{console.error(error);sandbox?.close();app.exit(1);});
app.on('will-quit',()=>fs.rmSync(profile,{recursive:true,force:true}));
