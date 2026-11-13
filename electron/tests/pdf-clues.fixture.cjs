'use strict';
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {randomUUID}=require('node:crypto');
app.commandLine.appendSwitch('no-proxy-server');
const fixtureHosts=['www.nature.com','journals.lww.com','www.sciencedirect.com','opg.optica.org','ieeexplore.ieee.org','x.biomedcentral.com','pubs.rsc.org','journals.plos.org','www.mdpi.com','x.copernicus.org','pubs.acs.org','pubs.aip.org','jamanetwork.com','rupress.org','ashpublications.org','iovs.arvojournals.org','pubs.geoscienceworld.org','www.cambridge.org','www.bmj.com','www.degruyterbrill.com','www.emerald.com','brill.com','elifesciences.org','www.thieme-connect.com','www.microbiologyresearch.org','epubs.siam.org','onlinelibrary.wiley.com','hindawi.com'];
app.commandLine.appendSwitch('host-resolver-rules',fixtureHosts.map(host=>'MAP '+host+' 127.0.0.1').join(', '));
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
require('../src/shared/logging.cjs').initializeLogging({stderr(){}});
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
app.whenReady().then(async()=>{
  let page='',requests=[];
  const server=http.createServer((request,response)=>{requests.push({url:request.url,referer:request.headers.referer});
    if(request.url.includes('redirect-reader=1')){response.writeHead(302,{location:request.url.replace('redirect-reader=1','final=1')});response.end();return;}
    if(request.url.includes('internal-redirect=1')){response.writeHead(302,{location:'http://127.0.0.1:'+server.address().port+'/forbidden'});response.end();return;}
    if(request.url.includes('/reader-next/')){response.setHeader('content-type','text/plain');response.end('controlled reader carrier');return;}
    if(request.url==='/redirect'){response.writeHead(302,{location:'/actual/Article'});response.end();return;}
    response.setHeader('content-type','text/html');response.end(page);});
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const port=server.address().port,url='http://www.nature.com:'+port+'/redirect';
  const host=new BrowserWindow({show:false}),browser=new BrowserRuntime({hostWindow:host});
  const messages=[],native=vm.createContext({require:require('node:module').createRequire(require.resolve('../src/main.cjs')),browser,operations:new Map(),exiting:false,bridgeReady:true,AbortController,
    ...require('../src/shared/logging.cjs'),...require('../src/shared/recovery-summary.cjs'),...require('../src/workflows/recovery-authority.cjs'),...require('../src/browser/browser-errors.cjs'),operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    send:message=>messages.push(JSON.parse(JSON.stringify(message)))});
  const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
  vm.runInContext(main.slice(main.indexOf('const CONTROL_ACTIONS='),main.indexOf('async function startPython(')),native);
  const data={workspace_identity:'a'.repeat(64),paper_id:randomUUID(),identity:{confirmed_article_url:'http://www.nature.com:'+port+'/actual/Article'},wantAbstract:true};
  const invoke=async(action='extract_paper_metadata',extra={})=>{const id=randomUUID();requests=[];
    const payload={...data,...extra,deadline_ms:Date.now()+6000};if(action==='extract_paper_pdf_clues')delete payload.wantAbstract;
    await native.execute({id,action,data:payload});
    const result=messages.find(item=>item.type==='result' && item.id===id)?.data;
    assert.ok(result);assert.equal(browser.paperPages.size,0);assert.equal([...browser.tabs.values()].filter(tab=>tab.taskOwner).length,0);
    return result;};
  const article=(head='',body='')=>'<!doctype html><head>'+head+'</head><body><article><h1>Paper</h1><p>Published 2020-05-02</p><div class="abstract">A complete result.</div>'+body+'</article></body>';
  try {
    await browser.ready;
    browser.partition.protocol.handle('https',request=>{const target=new URL(request.url);assert.ok(fixtureHosts.includes(target.hostname));return fetch('http://127.0.0.1:'+port+target.pathname+target.search);});
    page=article('<meta name="fulltext_pdf_url" content="/Full.pdf"><meta name="citation_pdf_url" content="Case.PDF?sig=A%2FB&amp;k=2"><meta name="citation_pdf_url" content="Case.PDF?sig=A%2FB&amp;k=2">','<a data-track-action="download pdf" href="/platform.PDF">PDF</a>');
    const composite=await invoke('extract_paper_metadata',{});
    assert.equal(composite.outcome,'retrieved',JSON.stringify(composite));assert.equal(composite.metadata.abstract,'A complete result.');
    assert.equal(composite.pdf_clues.landing_url,'http://www.nature.com:'+port+'/actual/Article');
    assert.deepEqual(composite.pdf_clues.candidates.map(item=>[item.stage,item.rule_id,item.url]),[
      ['P3','R037','http://www.nature.com:'+port+'/actual/Case.PDF?sig=A%2FB&k=2'],['P3','R037','http://www.nature.com:'+port+'/Full.pdf'],['P4','R037','http://www.nature.com:'+port+'/platform.PDF']]);
    assert.equal(composite.pdf_clues.status,'complete');assert.ok(Date.parse(composite.pdf_clues.observed_at));
    assert.deepEqual(requests.map(item=>item.url),['/actual/Article'],'precollection does not request candidates');
    const read=browser.readDocument.bind(browser);let scans=[];
    browser.readDocument=async(...args)=>{scans.push(args[1]);return read(...args);};
    const only=await invoke('extract_paper_pdf_clues');
    assert.equal(only.outcome,'retrieved');assert.ok(!('metadata' in only));assert.ok(!scans.includes('extract'));assert.ok(scans.includes('pdf'));
    browser.readDocument=read;
    page=article('','<a href="/supplement.pdf">Supplementary PDF</a><a href="/one.pdf">PDF</a><a href="/two.pdf">PDF</a>');
    const empty=await invoke();assert.deepEqual(empty.pdf_clues.candidates,[]);assert.equal(empty.pdf_clues.status,'complete');
    page=article('<meta name="citation_pdf_url" content="'+('x'.repeat(4097))+'">');
    const partial=await invoke();assert.equal(partial.metadata.abstract,'A complete result.');assert.equal(partial.pdf_clues.status,'failed');assert.deepEqual(partial.pdf_clues.diagnostics,['pdf_budget_exceeded']);
    page=article('<meta name="citation_pdf_url" content="https://cdn.example/Paper.PDF">');
    let changed=false;browser.readDocument=async(...args)=>{const result=await read(...args);if(args[1]==='pdf'&&!changed){changed=true;await args[0].view.webContents.executeJavaScript('document.body.replaceWith(document.body.cloneNode(true))');}return result;};
    assert.equal((await invoke()).diagnostic.code,'document_changed');browser.readDocument=read;
    // Every enabled P3/P4 host mapping goes through the real Main/preload seam.
    const metaRules=[['x.biomedcentral.com','R038'],['pubs.rsc.org','R040'],['journals.plos.org','R041'],['www.mdpi.com','R042'],['x.copernicus.org','R043'],['www.cambridge.org','R051'],['www.bmj.com','R052'],['brill.com','R056'],['www.thieme-connect.com','R058']];
    const forHost=async(host,body,head='',route='/article')=>{page=article(head,body);return invoke('extract_paper_metadata',{identity:{confirmed_article_url:(host==='elifesciences.org'?'https':'http')+'://'+host+':'+port+route}});};
    for(const [host,rule] of metaRules){const out=await forHost(host,'','<meta name="citation_pdf_url" content="https://cdn.example/Body.PDF">');assert.equal(out.pdf_clues.candidates[0].rule_id,rule,host);}
    const selectors=[['pubs.acs.org','R044','<a class="article-pdfLink" href="/body">Download</a>'],['pubs.aip.org','R045','<a class="article-pdfLink" href="/body">Download</a>'],['jamanetwork.com','R046','<a id="pdf-link" data-article-url="/body">Download</a>'],['rupress.org','R047','<a class="article-pdfLink" href="/body">Download</a>'],['ashpublications.org','R048','<a class="article-pdfLink" href="/body">Download</a>'],['iovs.arvojournals.org','R049','<a class="article-pdfLink" href="/body">Download</a>'],['pubs.geoscienceworld.org','R050','<a class="article-pdfLink" href="/body">Download</a>'],['opg.optica.org','R053','<a id="link-pdf" href="/body">Download</a>'],['www.degruyterbrill.com','R054','<a class="downloadPdf" href="/body">Download</a>'],['www.emerald.com','R055','<a class="intent_pdf_link" href="/body">Download</a>'],['elifesciences.org','R057','<ul class="article-download-list"><li><a href="/body">PDF</a></li></ul>'],['www.microbiologyresearch.org','R059','<div class="download-pdf"><form class="ft-download-content__form--pdf" method="post" action="/body"></form></div>']];
    for(const [host,rule,body] of selectors){const out=await forHost(host,body);assert.equal(out.pdf_clues.candidates[0].rule_id,rule,host);if(rule==='R059')assert.equal(out.pdf_clues.candidates[0].action,'refresh_form');}
    for(const [host,rule] of [['onlinelibrary.wiley.com','R039'],['epubs.siam.org','R061']]){
      const out=await forHost(host,'<a href="/doi/epdf/10.5555/target">Read</a><a href="/doi/pdf/10.5555/other">Other</a>','<meta name="citation_doi" content="10.5555/target">','/doi/full/10.5555/target');
      assert.equal(out.pdf_clues.candidates.length,1);assert.equal(out.pdf_clues.candidates[0].rule_id,rule);assert.match(out.pdf_clues.candidates[0].url,/epdf/);
    }
    for(const host of ['www.cambridge.org','pubs.geoscienceworld.org'])assert.deepEqual((await forHost(host,'<a class="article-pdfLink" href="/chapter.pdf">PDF</a>','<meta name="citation_type" content="book chapter"><meta name="citation_pdf_url" content="https://cdn.example/chapter.pdf">','/chapter/one')).pdf_clues.candidates,[]);
    const history=await forHost('hindawi.com','','<meta name="citation_pdf_url" content="https://cdn.example/current.pdf">');assert.equal(history.pdf_clues.candidates[0].rule_id,'GENERIC','historical disabled conversions do not block independent Meta');
    const negative=await forHost('www.nature.com','<div class="related"><a type="application/pdf" href="/related.pdf">PDF</a></div><section id="references"><a type="application/pdf" href="/ref.pdf">PDF</a></section><a type="application/pdf" href="/supplement.pdf">PDF</a><a type="application/pdf" href="/other.pdf">Other article</a>');assert.deepEqual(negative.pdf_clues.candidates,[]);
    const acs=await forHost('pubs.acs.org','<a href="/Citation/Download?resourceId=12345&amp;resourceType=3">Cite</a>');assert.deepEqual(acs.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['resource_id','12345'],['resource_type','3']]);
    const sd=await forHost('www.sciencedirect.com','<script>var article={pdfDownload:{urlMetadata:"https://cdn.example/sd.PDF"}};</script>','','/science/article/pii/S1234567812345678');assert.equal(sd.pdf_clues.identifiers[0].kind,'pii');assert.equal(sd.pdf_clues.candidates[0].reader_kind,'sciencedirect');
    const overflow=await forHost('www.sciencedirect.com','<script>var article={pdfDownload:{urlMetadata:"'+('x'.repeat(4097))+'"}};</script>');assert.equal(overflow.pdf_clues.status,'failed');assert.deepEqual(overflow.pdf_clues.diagnostics,['pdf_budget_exceeded']);
    const ieee=await forHost('ieeexplore.ieee.org','','','/document/12345');assert.deepEqual(ieee.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['article_number','12345']]);
    page='<!doctype html><body><script>var pdfDownloadDetails={pdfUrl:"http://www.nature.com:'+port+'/Actual.PDF?signature=A%2FB&key=2"};</script></body>';
    const readerURL='http://journals.lww.com:'+port+'/journal/_layouts/15/oaks.journals/downloadpdf.aspx?an=12345678-123456789-12345';
    const reader={rule_id:'R060',platform:'lww',url:readerURL,identifier:'12345678-123456789-12345',target:data.identity,source_url:'https://journals.lww.com/journal/fulltext/2026/one.aspx',stage:'P4'};
    const lww=await invoke('extract_paper_pdf_clues',{reader});
    assert.equal(lww.outcome,'retrieved');assert.equal(lww.pdf_clues.candidates[0].url,'http://www.nature.com:'+port+'/Actual.PDF?signature=A%2FB&key=2');
    assert.equal(lww.pdf_clues.candidates[0].referer,readerURL);assert.deepEqual(requests.map(item=>item.url),['/journal/_layouts/15/oaks.journals/downloadpdf.aspx?an=12345678-123456789-12345']);
    // The caller's controlled next-hop fixture uses the exact returned Referer;
    // it is separate from precollection and sends no PDF bytes or save action.
    await browser.runTask(new AbortController().signal,{request_id:randomUUID()},async()=>{
      const next=lww.pdf_clues.candidates[0];
      const response=await browser.sessionEvents.fetch(next.url,{headers:{Referer:next.referer},referrerPolicy:'unsafe-url'},
        {owner:browser.operation,attemptId:'referer-fixture',deadline:Date.now()+4000});await response.response.text();
    });
    assert.equal(requests.at(-1).referer,readerURL);
    page='<!doctype html><body><div class="PdfEmbed"><object data="Relative.PDF?signature=A%2FB&amp;key=2"></object></div></body>';
    const pii='S1234567812345678',sdReaderURL='http://www.sciencedirect.com:'+port+'/science/article/pii/'+pii+'/pdfft?redirect-reader=1';
    const sdReader={target:data.identity,rule_id:'R024',platform:'sciencedirect',url:sdReaderURL,identifier:pii,source_url:'https://www.sciencedirect.com/science/article/pii/'+pii,stage:'P2'};
    const redirected=await invoke('extract_paper_pdf_clues',{reader:sdReader});assert.equal(redirected.outcome,'retrieved',JSON.stringify(redirected));assert.equal(redirected.pdf_clues.landing_url,sdReaderURL.replace('redirect-reader=1','final=1'));
    assert.equal(redirected.pdf_clues.candidates[0].stage,'P2');assert.equal(redirected.pdf_clues.candidates[0].url,'http://www.sciencedirect.com:'+port+'/science/article/pii/'+pii+'/Relative.PDF?signature=A%2FB&key=2');
    const unsafe=await invoke('extract_paper_pdf_clues',{reader:{...sdReader,url:sdReaderURL.replace('redirect-reader=1','internal-redirect=1')}});assert.ok(unsafe.diagnostic);assert.ok(!requests.some(item=>item.url==='/forbidden'),'internal redirect is blocked before its request');
    page='<!doctype html><body><iframe src="/reader-next/IEEE.PDF?signature=AbC"></iframe></body>';
    const ieeeReader={target:data.identity,rule_id:'R025',platform:'ieee',url:'http://ieeexplore.ieee.org:'+port+'/stamp/stamp.jsp?tp=&arnumber=12345',identifier:'12345',source_url:'https://ieeexplore.ieee.org/document/12345',stage:'P2'};
    const ieeeNext=await invoke('extract_paper_pdf_clues',{reader:ieeeReader});assert.equal(ieeeNext.pdf_clues.candidates[0].url,'http://ieeexplore.ieee.org:'+port+'/reader-next/IEEE.PDF?signature=AbC');assert.equal(ieeeNext.pdf_clues.candidates[0].stage,'P2');
    page='<!doctype html><frameset><frame src="/reader-next/first"><frame src="/reader-next/Second.PDF?sig=2"></frameset>';
    const opticaReader={target:data.identity,rule_id:'R053',platform:'optica',url:'http://opg.optica.org:'+port+'/viewmedia.cfm?uri=ao-10-1-1',identifier:'ao-10-1-1',source_url:'https://opg.optica.org/abstract.cfm?uri=ao-10-1-1',stage:'P3'};
    const optica=await invoke('extract_paper_pdf_clues',{reader:opticaReader});assert.equal(optica.pdf_clues.candidates.length,1);assert.equal(optica.pdf_clues.candidates[0].url,'http://opg.optica.org:'+port+'/reader-next/Second.PDF?sig=2');assert.equal(optica.pdf_clues.candidates[0].stage,'P3');
    page='<!doctype html><title>Just a moment</title><body><iframe src="/reader-next/fake.pdf"></iframe></body>';
    const refused=await invoke('extract_paper_pdf_clues',{reader,deadline_ms:Date.now()+500});assert.ok(refused.diagnostic);assert.ok(!refused.pdf_clues);
    assert.ok((await invoke('extract_paper_pdf_clues',{reader:{...reader,identifier:'wrong'}})).diagnostic);
    console.log('PDF CLUES PASS');
  } finally {await browser.close();host.destroy();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
