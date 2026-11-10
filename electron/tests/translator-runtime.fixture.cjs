'use strict';
const {app,session,protocol}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {AsyncLocalStorage}=require('node:async_hooks');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-translator-profile-'));app.setPath('userData',profile);
// Unlike the desktop app, the fixture has no host window to keep it alive
// when the last offscreen worker is discarded after cancellation.
app.on('window-all-closed',()=>{});
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
const euclidArticle='journals/fixture/'+doi+'.full';

async function browserHistory() {
  const browser=new BrowserRuntime();
  // Reuse the official sandbox. All live document traffic stays in the synthetic partition.
  sandbox.browser=browser;
  const fixturePages={
    // The Euclid full article presents its history in a semicolon-delimited row.
    ['/'+euclidArticle]: article(
      '<div><span>Received: 1 September 2020</span>; <span>Revised: 1 December 2021</span>; '
      +'<span>Published: June 2022</span></div>'
      +'<p><span>Accepted: 1999</span></p>'
      +'<div class="related-articles"><div><span>Received: 1998</span>; <span>Published: 1999</span></div></div>'),
    '/late': article(history(received)+later('document.querySelector("ul").insertAdjacentHTML("beforeend",'+JSON.stringify(accepted)+')')),
    '/scielo-late': article('<a class="_doi" href="https://doi.org/'+doi+'">'+doi+'</a>'
      +'<div class="articleSection--history"><ul class="articleTimeline"><li><strong>Received</strong><br>29 February 2024</li></ul></div>'
      +later('document.querySelector("ul").insertAdjacentHTML("beforeend","<li><strong>Accepted</strong><br>2024-03</li>")'),
      html.split('</head>')[0].replace(/<meta name="citation_doi"[^>]*>/,'')),
    '/cancel': article(history(received)),
    '/replaced': article(history(received)+later('location.replace("/replacement")')),
    '/replacement': article(history(received+accepted)),
    '/doi-change': article(history(received)+later('document.querySelector("meta[name=citation_doi]").content="10.5555/other"')),
    '/doi-change-complete': article(history(received+accepted)),
    // The frame shares the root URL without a recursive frame request. This
    // lets the official registry run Embedded Metadata on the child document.
    '/child': article(history(received)+'<script>window.history.replaceState(null,"","/child-replaced")</script>'),
    '/child-replaced': '<title>Frame host</title><iframe src="/child"></iframe>'
      +later('document.querySelector("iframe").replaceWith(Object.assign(document.createElement("iframe"),{src:"/replacement"}))'),
    '/isolated-frames': article(history(received)+'<iframe src="/accepted-only"></iframe>'),
    '/accepted-only': article(history(accepted)),
    '/accepted-rdf': article(history(accepted),html.split('</head>')[0]
      +'<meta name="dcterms.dateAccepted" content="2024-03"><meta name="dcterms.dateSubmitted" content="2024-02-29">'),
    '/accepted-timestamp': article('',html.split('</head>')[0]
      +'<meta name="dcterms.dateAccepted" content="2024-03-02T00:45:00+02:00">'),
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
      +'<aside><div data-testid="publication-history-section"><ul>'
      +'<li data-testid="publication-history-item">Accepted: <span data-testid="publication-date-label">2021-10-31</span></li>'
      +'<li data-testid="publication-history-item">Accepted: <span data-testid="publication-date-label">2021-10-31</span></li></ul></div></aside>'
      +history(received+'<li>Revised: 2024-01-01</li><li>Submitted: 2020</li><li>Accepted: March 4</li>')
      +history('<li><label>Editorial history: </label>Manuscript received&nbsp;October, 2010; final revision received&nbsp;March, 2012.</li>')
      +'<div class="pub-history-wrap"><div class="history-entry"><div class="wi-state">Received:</div>'
      +'<div class="wi-date">01 March 2024</div></div></div>'
      +'<div class="itemPageRangeHistory"><span>Received 10 Mar 2026</span><span>Accepted author version posted online: 10 Jun 2026</span></div>'
      +'<ul class="article-chapter-history-list"><li><span>Accepted:</span>March 17, 2026</li></ul>'
      +'<section class="core-history"><div><b>Accepted</b>: 11 April 2025</div></section>'
      +'<div id="article-dates"><div class="article-dates"><nobr>Received: 21 Jan 2025</nobr></div></div>'
      +'<div id="article-information"><dl class="article-dates"><dt>Received</dt><dd><time datetime="2024-12-01">December 1, 2024</time></dd>'
      +'<dt>Accepted</dt><dd>January 14, 2025</dd></dl></div>'
      +'<div class="foot-notes"><div class="history"><p>Received: October 13, 2024; Accepted: February 06, 2025</p></div></div>'
      +'<p>Received: 1999</p><aside>'+history('<li>Accepted: 1998</li>')+'</aside>'
      +'<section id="references">'+history('<li>Accepted: 1997</li>')+'</section>'
      +'<div class="related-articles"><div class="itemPageRangeHistory"><span>Received 1996</span></div></div>'),
  };
  await browser.ready;
  await browser.partition.protocol.handle('https',request=>{
    const url=new URL(request.url);
    const text=['offline.invalid','www.scielo.br','projecteuclid.org'].includes(url.hostname) && fixturePages[url.pathname];
    return new Response(text || 'Unknown isolated fixture',{status:text?200:404,headers:{'Content-Type':'text/html'}});
  });
  async function translate(name,kinds=historyKinds,{cancel=false,deadline}={}) {
    const controller=new AbortController(),{signal}=controller;
    browser.beginOperation(signal);browser.operation.action='enrich_paper';
    const tab=await newTaskPage(browser,signal);
    try {
      const origin=name===euclidArticle?'https://projecteuclid.org':
        name==='scielo-late'?'https://www.scielo.br':'https://offline.invalid';
      const doc=await browser.navigate(origin+'/'+name,{signal,deadline:Date.now()+5000});
      browser.enterBusiness();
      const started=Date.now();
      const timer=cancel?setTimeout(()=>controller.abort(),350):null;
      const run=sandbox.run;
      if(name==='doi-change-complete')sandbox.run=async function(doc,method,...args) {
        const translated=await run.call(this,doc,method,...args);
        if(method==='translate' && translated.ok)await tab.view.webContents.executeJavaScript(
          'document.querySelector("meta[name=citation_doi]").content="10.5555/other"');
        return translated;
      };
      try {
        const result=await sandbox.translate(doc,doi,{forEnrichment:true,historyKinds:kinds,signal,deadline});
        return {result,elapsed:Date.now()-started};
      } finally {clearTimeout(timer);sandbox.run=run;}
    } finally {browser.endTask();tab.view.webContents.close();}
  }
  const facts=result=>result.dateCandidates.map(({kind,value})=>[kind,value]);
  try {
    const euclid=await translate(euclidArticle,['received'],{deadline:Date.now()+5000});
    assert.equal(euclid.result.translator,'Euclid');
    assert.deepEqual(euclid.result.dateCandidates,[{
      kind:'received',value:'2020-09-01',source_label:'Received:',
      url:'https://projecteuclid.org/'+euclidArticle,record_id:doi,
    }]);
    const immediate=await translate('templates');
    assert.ok(immediate.elapsed<1500,'complete history should return without polling');
    assert.deepEqual(facts(immediate.result).sort(),[
      ['received','2023-01-02'],['received','2019'],['received','2022-04-05'],['accepted','2022-04'],
      ['accepted','2020-03-02'],['accepted','2021-10-31'],['received','2024-02-29'],
      ['received','2024-03-01'],['received','2026-03-10'],['accepted','2026-03-17'],
      ['accepted','2025-04-11'],['received','2025-01-21'],
      ['received','2024-12-01'],['accepted','2025-01-14'],
      ['received','2010-10'],
      ['received','2024-10-13'],['accepted','2025-02-06'],
    ].sort());
    assert.ok(immediate.result.dateCandidates.every(item=>item.url==='https://offline.invalid/templates' && item.record_id===doi));
    const late=await translate('late');
    assert.deepEqual(facts(late.result),[['received','2024-02-29'],['accepted','2024-03']]);
    assert.ok(late.elapsed>=1250);
    const scielo=await translate('scielo-late');
    assert.equal(scielo.result.translator,'SciELO');
    assert.deepEqual(facts(scielo.result),[['received','2024-02-29'],['accepted','2024-03']]);
    const already=await translate('isolated-frames',['received']);
    assert.deepEqual(facts(already.result),[['received','2024-02-29']]);
    const rdf=await translate('accepted-rdf',['accepted']);
    assert.equal(rdf.result.item.accepted,'2024-03');
    assert.deepEqual(rdf.result.dateCandidates,[{
      kind:'accepted',value:'2024-03',source_label:'Manuscript accepted:',
      url:'https://offline.invalid/accepted-rdf',record_id:doi,
    }]);
    const timestamp=await translate('accepted-timestamp',['accepted']);
    assert.deepEqual(facts(timestamp.result),[['accepted','2024-03-02']]);
    await assert.rejects(translate('cancel',historyKinds,{cancel:true}),{message:'canceled'});
    for(const name of ['replaced','child-replaced','doi-change','doi-change-complete'])
      await assert.rejects(translate(name),{message:'document_changed'},name);
    const bounded=await translate('no-history');
    assert.ok(bounded.elapsed>=29500 && bounded.elapsed<32000,'optional date work should end after 30 seconds');
    assert.equal(bounded.result.metadataSource,'web');
    assert.deepEqual(facts(bounded.result),[]);
  } finally {browser.close();}
}
app.whenReady().then(async()=>{
  const partition=session.fromPartition('allfold-offline-source'),requests=[];
  const simultaneous=new Set(),bothArrived=Promise.withResolvers();
  const canceledHTTP=Promise.withResolvers(),canceledResponse=Promise.withResolvers(),releasedHTTP=new Set();
  const drainingHTTP=Promise.withResolvers(),drainingResponse=Promise.withResolvers();
  // This synthetic protocol is the only publisher/DOI transport; no Zotero or network endpoint is contacted.
  await partition.protocol.handle('https',async request=>{
    requests.push({url:request.url,method:request.method,accept:request.headers.get('Accept')});
    assert.equal(request.method,'GET');assert.equal(new URL(request.url).hostname,'doi.org');
    const requestDOI=decodeURIComponent(new URL(request.url).pathname.slice(1));
    if(['10.5555/worker-a','10.5555/worker-b'].includes(requestDOI)) {
      simultaneous.add(requestDOI);
      if(simultaneous.size===2)bothArrived.resolve();
      await bothArrived.promise;
    }
    if(requestDOI==='10.5555/cancel-active') {
      canceledHTTP.resolve();
      await canceledResponse.promise;
    }
    if(requestDOI==='10.5555/drain-worker') {
      drainingHTTP.resolve();
      await drainingResponse.promise;
    }
    return new Response(JSON.stringify({type:'article-journal',DOI:requestDOI,title:requestDOI===doi?'Offline DOI Translation':requestDOI,
      'container-title':'Offline Journal',author:[{family:'Smith',given:'Alex'}],issued:{'date-parts':[[2026,3,14]]}}),
      {status:200,headers:{'Content-Type':'application/vnd.citationstyles.csl+json'}});
  });
  const doc={pageId:7,url,html,frameToken:'offline-document',documentId:'synthetic-document'};
  const browser={partition,tabs:new Map(),documentCurrent:value=>value.frameToken===doc.frameToken,
    translationDocuments:async()=>[doc],snapshot:async()=>doc,pageCookie:async()=>''};
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
  const owners=new AsyncLocalStorage();
  const concurrentBrowser={partition,tabs:new Map(),get operation(){return owners.getStore();},
    runInOperation:(owner,run)=>owners.run(owner,run),
    ownsPage:(owner,pageId)=>owner?.pageId===pageId,
    documentCurrent:value=>value.frameToken===owners.getStore()?.frameToken,
    translationDocuments:async value=>[value],
    cookieAdapter:{register:({doc})=>({release:()=>releasedHTTP.add(doc.frameToken)})}};
  sandbox.browser=concurrentBrowser;
  const workSource=(workDOI,pageId)=>({...blank,pageId,frameToken:workDOI,documentId:workDOI});
  const concurrent=await Promise.all(['10.5555/worker-a','10.5555/worker-b'].map((workDOI,index)=>{
    const source=workSource(workDOI,index+8);
    return owners.run(source,()=>sandbox.translate(source,workDOI,{deadline:Date.now()+5000}));
  }));
  assert.deepEqual(concurrent.map(result=>[result.metadataSource,result.item.DOI,result.item.title]),[
    ['doi','10.5555/worker-a','10.5555/worker-a'],['doi','10.5555/worker-b','10.5555/worker-b'],
  ]);
  assert.deepEqual(simultaneous,new Set(['10.5555/worker-a','10.5555/worker-b']));
  const canceledSource=workSource('10.5555/cancel-active',10),otherSource=workSource('10.5555/other-active',11);
  const queuedSource=workSource('10.5555/cancel-queued',12),activeController=new AbortController();
  const open=(source,options)=>owners.run(source,()=>sandbox.openOperation(source,{deadline:Date.now()+5000,...options}));
  const [first,second]=await Promise.all([open(canceledSource,{signal:activeController.signal}),open(otherSource)]);
  const request=(operation,token)=>operation.window.webContents.executeJavaScript('window.translatorHost.request('+JSON.stringify({
    operationId:token,method:'GET',url:'https://doi.org/forged',
  })+')');
  try {
    assert.notEqual(first.window.webContents.id,second.window.webContents.id);
    const countBeforeForgery=requests.length;
    await assert.rejects(request(second,first.id),/Expired or untrusted Translator operation/);
    otherSource.frameToken='replaced-document';
    await assert.rejects(request(second,second.id),/document_changed/);
    otherSource.frameToken=otherSource.documentId;
    assert.equal(requests.length,countBeforeForgery);
    await assert.rejects(open(queuedSource,{deadline:Date.now()+50}),{diagnostic:{stage:'translation',step:'sandbox_queue',code:'timeout'}});
    const queuedController=new AbortController(),queued=open(queuedSource,{signal:queuedController.signal});
    queuedController.abort();
    await assert.rejects(queued,{message:'canceled'});
    const invoke=(source,operation)=>owners.run(source,()=>sandbox.invoke(operation,'searchDOI',
      {doi:source.documentId,url:source.url},Date.now()+5000));
    const canceled=assert.rejects(invoke(canceledSource,first).finally(()=>sandbox.endOperation(first)),{message:'canceled'});
    await Promise.race([canceledHTTP.promise,canceled]);
    activeController.abort();
    await canceled;
    assert.ok(releasedHTTP.has(canceledSource.frameToken),'canceled renderer transport must settle before its slot is released');
    const unaffected=await invoke(otherSource,second);
    assert.equal(unaffected.items[0].DOI,otherSource.documentId);
    const reused=await open(queuedSource);
    try {
      await assert.rejects(request(reused,first.id),/Expired or untrusted Translator operation/);
    } finally {await sandbox.endOperation(reused);}
  }finally {
    canceledResponse.resolve();
    await Promise.all([sandbox.endOperation(first),sandbox.endOperation(second)]);
  }
  sandbox.browser=browser;
  const operation=await sandbox.openOperation(doc);
  try {
    const capabilities=await operation.window.webContents.executeJavaScript('({count:window.allfoldTranslator.count,writer:typeof Zotero.ItemSaver,connector:typeof Zotero.Connector,botBypass:typeof Zotero.BotBypass,virtualSaver:typeof Zotero.Translate.ItemSaver})');
    assert.deepEqual(capabilities,{count:752,writer:'undefined',connector:'undefined',botBypass:'undefined',virtualSaver:'function'});
  }finally{await sandbox.endOperation(operation);}
  await browserHistory();
  sandbox.browser=concurrentBrowser;
  const drainSource=workSource('10.5555/drain-worker',13);
  const drained=assert.rejects(owners.run(drainSource,()=>sandbox.translate(drainSource,drainSource.documentId,
    {deadline:Date.now()+5000})),{message:'canceled'});
  await Promise.race([drainingHTTP.promise,drained]);
  try {
    await sandbox.close();
    assert.ok(releasedHTTP.has(drainSource.frameToken));
    await drained;
    await assert.rejects(open(queuedSource),{message:'canceled'});
  }finally{drainingResponse.resolve();}
  console.log('OFFICIAL TRANSLATOR RUNTIME PASS');app.quit();
}).catch(async error=>{console.error(error);await sandbox?.close();app.exit(1);});
app.on('will-quit',()=>fs.rmSync(profile,{recursive:true,force:true}));
