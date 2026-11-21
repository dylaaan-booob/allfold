'use strict';
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),https=require('node:https'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {randomUUID,X509Certificate}=require('node:crypto');
app.commandLine.appendSwitch('no-proxy-server');
const fixtureHosts=['oce.ovid.com','assets.ovid.com','www.nature.com','journals.lww.com','www.sciencedirect.com','opg.optica.org','ieeexplore.ieee.org','x.biomedcentral.com','pubs.rsc.org','journals.plos.org','www.mdpi.com','x.copernicus.org','pubs.acs.org','academic.oup.com','pubs.aip.org','jamanetwork.com','rupress.org','ashpublications.org','iovs.arvojournals.org','pubs.geoscienceworld.org','www.cambridge.org','www.bmj.com','www.degruyterbrill.com','www.emerald.com','brill.com','elifesciences.org','www.thieme-connect.com','www.microbiologyresearch.org','epubs.siam.org','onlinelibrary.wiley.com','hindawi.com'];
const readerAsset='https://pdf.sciencedirectassets.com/1-s2.0-S1234567812345678/main.pdf';
fixtureHosts.push(new URL(readerAsset).hostname);
const ebscoHosts=['search.ebscohost.com','research.ebsco.com','content.ebscohost.com'];
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
require('../src/shared/logging.cjs').initializeLogging({stderr(){}});
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
(async()=>{
  let page='',requests=[],delayedPDF,challengeResponse=false,ebscoDOI='10.5555/fixture',ebscoMode='viewer';
  const ebscoProfile='https://research.ebsco.com/c/test-profile';
  const ebscoPdf='https://content.ebscohost.com/files/licensed?Signature=A%2FB';
  const resultsPath='/c/test-profile/search/results';
  const recordPath='/c/test-profile/search/details/record';
  const viewerPath='/c/test-profile/viewer/pdf/record',viewerQuery='?intent=download%20now';
  const recordDetails='/api/viewer/v6/details/record',downloadLink='/record-access/record';
  const requestPDF='<script>fetch('+JSON.stringify(ebscoPdf)+').catch(()=>{});</script>';
  const previews=['/cds/retrieve?Signature=preview-first','/cds/retrieve?Signature=preview-second'].map(path=>
    new URL(path,ebscoPdf).href);
  const serve=(request,response)=>{requests.push({url:request.url,referer:request.headers.referer,method:request.method});
    const current=new URL(request.url,'http://fixture.invalid');
    const ebscoHub='<a href="'+ebscoProfile+'/search">Search the collection</a>';
    const subframePost=ebscoMode==='profile-postback-subframe';
    const multiProfile=ebscoMode==='profile-postback-several';
    const ebPostback='<form method="post" action="/webauth/Community.aspx">'
      +(multiProfile?'<a href="javascript:WebForm_DoPostBackWithOptions(1)">Publication Finder</a>':'')
      +'<a href="javascript:WebForm_DoPostBackWithOptions()">'+(multiProfile?'EBSCO 一站式检索':'Search the collection')+'</a></form>'
      +(subframePost?'<iframe name="follow-up" hidden></iframe>':'')
      +'<script>function WebForm_DoPostBackWithOptions(other){const form=document.querySelector("form");'
      +'if(other)form.action="/publication-finder";'
      +(ebscoMode==='profile-postback-other-origin'||subframePost?'form.action="https://research.ebsco.com/webauth/Community.aspx";':'')
      +(subframePost?'form.target="follow-up";':'')
      +'form.submit();}</script>';
    if(request.headers.host==='content.ebscohost.com') {
      response.writeHead(200,{'content-type':'application/pdf','cache-control':'no-store'});
      response.end('%PDF-fixture');return;
    }
    const recordMetadata='<aside aria-label="References"><a href="https://doi.org/10.9876/reference">Reference</a></aside>'
      +'<h3>DOI</h3><p>'+ebscoDOI+'</p>'
      +'<a href="/c/test-profile/viewer/pdf/related">Related PDF</a>'
      +'<a aria-label="Access now (PDF) Licensed fixture" href="'+viewerPath+viewerQuery+'">View PDF</a>';
    const signIn='<title>Sign in</title><main><h1>Sign in</h1><form><label>Password <input type="password"></label><button>Sign in</button></form></main>';
    const resultLink='<h2><a href="'+recordPath+'">Licensed fixture</a></h2>';
    const pendingImage='<img src="/ebsco-pending-image">';
    let results='<main><h1>Search results</h1>'+resultLink+'</main>';
    if(ebscoMode==='expired-search')results=signIn+pendingImage;
    if(ebscoMode==='pending-asset')results='<main aria-busy="true"><h1>Search results</h1></main>'
      +'<script>setTimeout(()=>{history.replaceState(null,"",location.href+"&db=licensed");'
      +'const main=document.querySelector("main");main.setAttribute("aria-busy","false");'
      +'main.insertAdjacentHTML("beforeend",'+JSON.stringify(
        '<h2><a href="/c/foreign/search/details/first">Licensed fixture</a></h2>'
        +'<h2><a href="/c/foreign/search/details/second">Licensed fixture</a></h2>'
        +'<article><h2><a href="'+recordPath+'">Updated title</a></h2><p>DOI: 10.5555/fixture</p></article>'+resultLink+resultLink)
      +');},800);</script>';
    if(ebscoMode==='ambiguous')results='<main><h1>Search results</h1>'+resultLink
      +resultLink.replace(recordPath,recordPath+'-other')+'</main>';
    if(ebscoMode==='record-in-app')results+='<script>document.querySelector("h2 a").addEventListener("click",event=>{'
      +'event.preventDefault();history.pushState(null,"",event.currentTarget.href+"?db=licensed");'
      +'document.querySelector("main").innerHTML='+JSON.stringify('<h1>Licensed fixture</h1>'+recordMetadata)+';});</script>';
    if(ebscoMode==='replace-search' && !current.searchParams.has('replacement'))
      results='<main><h1>Search results</h1></main>'+pendingImage
        +'<script>setTimeout(()=>location.replace(location.href+"&replacement=1"),800);</script>';
    if(current.pathname==='/ebsco-pending-image')return;
    if(ebscoMode.startsWith('profile-postback') && current.pathname==='/webauth/Community.aspx') {
      if(ebscoMode==='profile-postback-redirect-post' && !current.search) {
        response.writeHead(307,{location:'/webauth/Community.aspx?second=1'});response.end();return;
      }
      response.writeHead(303,{location:ebscoProfile+'/search'});response.end();return;
    }
    if(current.pathname===recordPath && ebscoMode==='record-in-app')return;
    if(ebscoMode==='direct-link' && current.pathname===recordDetails) {
      response.writeHead(200,{'content-type':'text/plain','cache-control':'no-store'});
      const row={result:{metadata:'x'.repeat(1100000),recordId:'record',links:{'v2-downloadLinks':[
        {type:'pdf',url:downloadLink},{type:'pdf',url:ebscoPdf}]}}};
      response.end(JSON.stringify([row,row]));return;
    }
    if(current.pathname.startsWith(recordPath+'-')) {
      response.writeHead(404,{'content-type':'text/html'});
      response.end('<main><h1>Record unavailable</h1></main>');return;
    }
    if(current.pathname===recordPath && ebscoMode==='unsafe') {
      response.writeHead(302,{location:'http://127.0.0.1:'+server.address().port+'/ebsco-forbidden'});response.end();return;
    }
    const ebscoPages={
      '/Community.aspx':'<main><h1>Institution library</h1>'+(ebscoMode.startsWith('profile-postback')?ebPostback:ebscoHub+ebscoHub)+'</main>',
      '/c/test-profile/search':'<main><h1>Search the library</h1><p>All databases</p></main>',
      [resultsPath]:results,
      [recordPath]:ebscoMode==='expired'
        ? signIn
        : '<main><h1>Licensed content title</h1>'+(ebscoMode==='delayed'||ebscoMode==='preview'?''
          :ebscoMode==='html-only'?'<h3>DOI</h3><p>'+ebscoDOI+'</p><a href="'+viewerPath.replace('/pdf/','/html/')+'">HTML full text</a>'
            :recordMetadata)+'</main>'
          +(ebscoMode==='preview'?'<script>Promise.allSettled('+JSON.stringify(previews)
            +'.map(url=>fetch(url))).then(()=>document.querySelector("main").insertAdjacentHTML("beforeend",'+JSON.stringify(recordMetadata)+'));</script>':ebscoMode==='delayed'
            ?'<script>setTimeout(()=>document.querySelector("main").insertAdjacentHTML("beforeend",'+JSON.stringify(recordMetadata)+'),900);</script>':''),
      [viewerPath]:'<main><h1>Full text</h1><p>Institution viewer</p></main>'+(current.search===viewerQuery?requestPDF:'')
        +(ebscoMode==='record-in-app'?pendingImage:''),
    };
    if(Object.hasOwn(ebscoPages,current.pathname)) {
      response.writeHead(200,{'content-type':'text/html; charset=utf-8','cache-control':'no-store'});
      response.end('<!doctype html>'+ebscoPages[current.pathname]);return;
    }
    const handoff=current.searchParams.get('verify-reader');
    if(handoff==='same' || handoff==='different') {
      response.setHeader('content-type','text/html');
      response.end('<!doctype html><script>location.replace('+JSON.stringify(readerAsset+'?case='+handoff)+')</script>');
      return;
    }
    if(current.pathname===new URL(readerAsset).pathname) {
      response.setHeader('content-type','text/html');
      if(current.searchParams.get('case')==='replacement') {
        response.end('<!doctype html><h1>Replacement Document</h1>');return;
      }
      const action=current.searchParams.get('case')==='different'?current.pathname+'?case=changed':current.pathname+current.search;
      response.end(request.method==='GET'
        ?'<!doctype html><form method="post" action="'+action+'"></form><script>document.forms[0].submit()</script>'
        :'<!doctype html><h1>Verified reader</h1>');
      return;
    }
    if(request.url==='/snapshot-resource'){response.writeHead(200,{'content-type':'text/plain','cache-control':'no-store'});response.end('resource');return;}
    if(request.url==='/snapshot-script'){response.end('');return;}
    if(request.url==='/hydrated-pdf'){delayedPDF=response;return;}
    if(request.url.includes('redirect-reader=1')){response.writeHead(302,{location:request.url.replace('redirect-reader=1','final=1')});response.end();return;}
    if(request.url.includes('internal-redirect=1')){response.writeHead(302,{location:'http://127.0.0.1:'+server.address().port+'/forbidden'});response.end();return;}
    if(request.url.startsWith('/pdfviewer/web/viewer.html')||request.url.startsWith('/arbitrary?')){response.setHeader('content-type','text/html');response.end('<body>Fixed viewer fixture</body>');return;}
    if(request.url.includes('/reader-next/')){response.setHeader('content-type','text/plain');response.end('controlled reader carrier');return;}
    if(request.url==='/redirect'){response.writeHead(302,{location:'/actual/Article'});response.end();return;}
    response.setHeader('content-type','text/html');if(challengeResponse)response.setHeader('cf-mitigated','challenge');response.end(page);};
  const fixture=path.resolve(__dirname,'../../tests/fixtures/http');
  const cert=fs.readFileSync(path.join(fixture,'localhost-cert.pem'));
  const fingerprint=new X509Certificate(cert).fingerprint256;
  const server=http.createServer(serve);
  const secureServer=https.createServer({cert,key:fs.readFileSync(path.join(fixture,'localhost-key.pem'))},serve);
  await Promise.all([server,secureServer].map(listener=>new Promise(resolve=>listener.listen(0,'127.0.0.1',resolve))));
  app.commandLine.appendSwitch('host-resolver-rules',[
    ...fixtureHosts.map(host=>'MAP '+host+' 127.0.0.1'),
    ...ebscoHosts.map(host=>'MAP '+host+' 127.0.0.1:'+secureServer.address().port),
  ].join(', '));
  await app.whenReady();
  const port=server.address().port,url='http://www.nature.com:'+port+'/redirect';
  const host=new BrowserWindow({show:false}),browser=new BrowserRuntime({hostWindow:host});
  const messages=[],native=vm.createContext({require:require('node:module').createRequire(require.resolve('../src/main.cjs')),browser,operations:new Map(),exiting:false,bridgeReady:true,AbortController,
    readerDiagnosticFields:require('../src/browser/pdf-clues.cjs').readerDiagnosticFields,
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
    browser.partition.protocol.handle('https',request=>{const target=new URL(request.url);assert.ok(fixtureHosts.includes(target.hostname));return fetch('http://127.0.0.1:'+port+target.pathname+target.search,{method:request.method});});
    page=article('<meta name="fulltext_pdf_url" content="/Full.pdf"><meta name="citation_pdf_url" content="Case.PDF?sig=A%2FB&amp;k=2"><meta name="citation_pdf_url" content="Case.PDF?sig=A%2FB&amp;k=2">','<a data-track-action="download pdf" href="/platform.PDF">PDF</a>');
    const composite=await invoke('extract_paper_metadata',{});
    assert.equal(composite.outcome,'retrieved',JSON.stringify(composite));assert.equal(composite.metadata.abstract,'A complete result.');
    assert.equal(composite.pdf_clues.landing_url,'http://www.nature.com:'+port+'/actual/Article');
    assert.deepEqual(composite.pdf_clues.candidates.map(item=>[item.stage,item.rule_id,item.url]),[
      ['P3','R037','http://www.nature.com:'+port+'/actual/Case.PDF?sig=A%2FB&k=2'],['P3','R037','http://www.nature.com:'+port+'/Full.pdf'],['P4','R037','http://www.nature.com:'+port+'/platform.PDF']]);
    assert.equal(composite.pdf_clues.status,'complete');assert.ok(Date.parse(composite.pdf_clues.observed_at));
    assert.deepEqual(requests.map(item=>item.url),['/actual/Article'],'precollection does not request candidates');
    page=article('<base href="../assets/"><meta name="citation_pdf_url" content="Body.PDF">',
      '<script>fetch("/snapshot-script");document.querySelector(".abstract").textContent="Rendered abstract.";</script>'+
      '<iframe src="/snapshot-resource"></iframe><img src="/snapshot-resource">');
    const rendered=await invoke();
    assert.equal(rendered.metadata.abstract,'Rendered abstract.');assert.equal(rendered.pdf_clues.landing_url,'http://www.nature.com:'+port+'/actual/Article');
    assert.equal(rendered.pdf_clues.candidates[0].url,'http://www.nature.com:'+port+'/assets/Body.PDF');
    assert.equal(requests.filter(item=>item.url==='/snapshot-script').length,1,'snapshot scripts are inert');
    assert.equal(requests.filter(item=>item.url==='/snapshot-resource').length,2,'snapshot never loads image/frame resources again');
    const read=browser.readDocument.bind(browser);let scans=[];
    browser.readDocument=async(...args)=>{scans.push(args[1]);return read(...args);};
    const only=await invoke('extract_paper_pdf_clues');
    assert.equal(only.outcome,'retrieved');assert.ok(!('metadata' in only));assert.ok(!scans.includes('extract'));assert.ok(scans.includes('pdf'));
    browser.readDocument=read;
    page=article('','<a href="/supplement.pdf">Supplementary PDF</a><a href="/one.pdf">PDF</a><a href="/two.pdf">PDF</a>');
    const empty=await invoke();assert.deepEqual(empty.pdf_clues.candidates,[]);assert.equal(empty.pdf_clues.status,'complete');
    const longLink='https://cdn.example/Body.PDF?sig='+('x'.repeat(9000))+'%2FB';
    page=article('<meta name="citation_pdf_url" content="'+longLink+'"><meta name="citation_pdf_url" content="https://cdn.example/next.pdf">');
    const afterField=await invoke();assert.equal(afterField.pdf_clues.status,'complete');
    assert.deepEqual(afterField.pdf_clues.candidates.map(item=>item.url),[longLink,'https://cdn.example/next.pdf']);
    page=article(Array.from({length:40},(_,i)=>'<meta name="citation_pdf_url" content="https://cdn.example/body-'+i+'.pdf">').join(''));
    const manyCandidates=await invoke();assert.equal(manyCandidates.pdf_clues.status,'complete');assert.equal(manyCandidates.pdf_clues.candidates.length,40);
    page=article(Array.from({length:33},(_,i)=>'<meta name="citation_pdf_url" content="https://cdn.example/Body'+i+'/'+('a'.repeat(1900))+'.pdf">').join(''));
    const aggregate=await invoke('extract_paper_metadata',{identity:{confirmed_article_url:'http://www.nature.com:'+port+'/actual/'+('L'.repeat(3900))}});assert.equal(aggregate.outcome,'retrieved',JSON.stringify(aggregate));assert.equal(aggregate.metadata.abstract,'A complete result.');
    assert.equal(aggregate.pdf_clues.candidates.length,33);assert.equal(aggregate.pdf_clues.status,'complete');
    if(process.argv[3])fs.writeFileSync(process.argv[3],JSON.stringify(aggregate));
    page=article('<meta name="citation_pdf_url" content="https://cdn.example/Paper.PDF">');
    let changed=false;browser.readDocument=async(...args)=>{const result=await read(...args);if(args[1]==='extract'&&!changed){changed=true;await args[0].view.webContents.executeJavaScript('document.body.replaceWith(document.body.cloneNode(true));history.replaceState({},"","?changed=1")');}return result;};
    const captured=await invoke();assert.equal(captured.outcome,'retrieved');assert.equal(captured.metadata.abstract,'A complete result.');
    assert.equal(captured.pdf_clues.candidates[0].url,'https://cdn.example/Paper.PDF');browser.readDocument=read;
    // Every enabled P3/P4 host mapping goes through the real Main/preload seam.
    const metaRules=[['x.biomedcentral.com','R038'],['pubs.rsc.org','R040'],['journals.plos.org','R041'],['www.mdpi.com','R042'],['x.copernicus.org','R043'],['www.cambridge.org','R051'],['www.bmj.com','R052'],['brill.com','R056'],['www.thieme-connect.com','R058']];
    const forHost=async(host,body,head='',route='/article')=>{page=article(head,body);return invoke('extract_paper_metadata',{identity:{confirmed_article_url:(host==='elifesciences.org'?'https':'http')+'://'+host+':'+port+route}});};
    for(const [host,rule] of metaRules){const out=await forHost(host,'','<meta name="citation_pdf_url" content="https://cdn.example/Body.PDF">');assert.equal(out.pdf_clues.candidates[0].rule_id,rule,host);}
    const selectors=[['pubs.acs.org','R044','<a class="article-pdfLink" href="/body">Download</a>'],['pubs.aip.org','R045','<a class="article-pdfLink" href="/body">Download</a>'],['jamanetwork.com','R046','<a id="pdf-link" data-article-url="/body">Download</a>'],['rupress.org','R047','<a class="article-pdfLink" href="/body">Download</a>'],['ashpublications.org','R048','<a class="article-pdfLink" href="/body">Download</a>'],['iovs.arvojournals.org','R049','<a class="article-pdfLink" href="/body">Download</a>'],['pubs.geoscienceworld.org','R050','<a class="article-pdfLink" href="/body">Download</a>'],['opg.optica.org','R053','<a id="link-pdf" href="/body">Download</a>'],['www.degruyterbrill.com','R054','<a class="downloadPdf" href="/body">Download</a>'],['www.emerald.com','R055','<a class="intent_pdf_link" href="/body">Download</a>'],['elifesciences.org','R057','<ul class="article-download-list"><li><a href="/body">PDF</a></li></ul>'],['www.microbiologyresearch.org','R059','<div class="download-pdf"><form class="ft-download-content__form--pdf" method="post" action="/body"></form></div>']];
    for(const [host,rule,body] of selectors){const out=await forHost(host,body);assert.equal(out.pdf_clues.candidates[0].rule_id,rule,host);if(rule==='R059')assert.equal(out.pdf_clues.candidates[0].action,'refresh_form');}
    const form=selectors.find(([,rule])=>rule==='R059')[2];
    const toolbarForm=await forHost('www.microbiologyresearch.org','<nav aria-label="Article navigation">'+form+'</nav>');
    assert.equal(toolbarForm.pdf_clues.candidates[0]?.action,'refresh_form','fixed article-toolbar form remains a body entry');
    const relatedForm=await forHost('www.microbiologyresearch.org','<nav><div class="related">'+form+'</div></nav>');
    assert.deepEqual(relatedForm.pdf_clues.candidates,[],'related forms remain excluded');
    for(const [host,,body] of selectors) {
      const excluded=body.replaceAll('/body','/Supplements.pdf').replaceAll('Download','Supplementary information PDF').replaceAll('>PDF<','>Supplementary PDF<');
      assert.deepEqual((await forHost(host,excluded)).pdf_clues.candidates,[],host+' excludes supplements even with an explicit selector');
    }
    assert.deepEqual((await forHost('pubs.acs.org','<a class="article-pdfLink" href="/doi/pdf/10.5555/other">PDF</a>','<meta name="citation_doi" content="10.5555/target">')).pdf_clues.candidates,[]);
    const duplicateDoi=await forHost('pubs.acs.org','<a class="article-pdfLink" href="/doi/pdf/10.5555/target">PDF</a>','<meta name="citation_doi" content="10.5555/target"><meta name="prism.doi" content="https://doi.org/10.5555/TARGET">');
    assert.equal(duplicateDoi.pdf_clues.candidates[0]?.rule_id,'R044','duplicate equivalent DOI fields retain the current article entry');
    const conflictingDoi=await forHost('pubs.acs.org','<a class="article-pdfLink" href="/doi/pdf/10.5555/target">PDF</a>','<meta name="citation_doi" content="10.5555/target"><meta name="prism.doi" content="10.5555/other">');
    assert.equal(conflictingDoi.outcome,'retrieved');assert.equal(conflictingDoi.metadata.abstract,'A complete result.');
    assert.deepEqual(conflictingDoi.pdf_clues.candidates,[],'ambiguous DOI-scoped candidate alone is excluded');
    for(const [host,rule] of [['onlinelibrary.wiley.com','R039'],['epubs.siam.org','R061']]){
      const out=await forHost(host,'<a href="/doi/epdf/10.5555/target">Read</a><a href="/doi/pdf/10.5555/other">Other</a>','<meta name="citation_doi" content="10.5555/target">','/doi/full/10.5555/target');
      assert.equal(out.pdf_clues.candidates.length,1);assert.equal(out.pdf_clues.candidates[0].rule_id,rule);assert.match(out.pdf_clues.candidates[0].url,/epdf/);
    }
    for(const host of ['www.cambridge.org','pubs.geoscienceworld.org'])assert.deepEqual((await forHost(host,'<a class="article-pdfLink" href="/chapter.pdf">PDF</a>','<meta name="citation_type" content="book chapter"><meta name="citation_pdf_url" content="https://cdn.example/chapter.pdf">','/chapter/one')).pdf_clues.candidates,[]);
    const history=await forHost('hindawi.com','','<meta name="citation_pdf_url" content="https://cdn.example/current.pdf">');assert.equal(history.pdf_clues.candidates[0].rule_id,'GENERIC','historical disabled conversions do not block independent Meta');
    const negative=await forHost('www.nature.com','<div class="related"><a type="application/pdf" href="/related.pdf">PDF</a></div><section id="references"><a type="application/pdf" href="/ref.pdf">PDF</a></section><a type="application/pdf" href="/supplement.pdf">PDF</a><a type="application/pdf" href="/other.pdf">Other article</a>');assert.deepEqual(negative.pdf_clues.candidates,[]);
    const acs=await forHost('pubs.acs.org','<a href="/Citation/Download?resourceId=12345&amp;resourceType=3">Cite</a>');assert.deepEqual(acs.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['resource_id','12345'],['resource_type','3']]);
    for(const host of ['pubs.acs.org','academic.oup.com']) {
      const citation='<div class="related"><a href="/Citation/Download?resourceId=99991&amp;resourceType=3">Related cite</a></div><section id="references"><a href="/Citation/Download?resourceId=99992&amp;resourceType=3">Reference cite</a></section><a href="/Citation/Download?resourceId=99993&amp;resourceType=2">Book cite</a><a href="/Citation/Download?resourceId=12345&amp;resourceType=3">Article cite</a>';
      const scoped=await forHost(host,citation);assert.deepEqual(scoped.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['resource_id','12345'],['resource_type','3']],host+' uses only current article type-3 citation');
      const nonArticle=await forHost(host,'<a href="/Citation/Download?resourceId=99993&amp;resourceType=2">Book cite</a><a href="/Citation/Download?resourceId=12345">Unknown type</a>');assert.deepEqual(nonArticle.pdf_clues.identifiers,[]);
    }
    const sd=await forHost('www.sciencedirect.com','<script>var article={pdfDownload:{urlMetadata:"https://cdn.example/sd.PDF"}};</script>','','/science/article/pii/S1234567812345678');assert.equal(sd.pdf_clues.identifiers[0].kind,'pii');assert.equal(sd.pdf_clues.candidates[0].reader_kind,'sciencedirect');
    const stateFault=await forHost('www.sciencedirect.com','<script>Object.defineProperty(window,"article",{get(){throw Error("unavailable state")}})</script>',
      '<meta name="citation_pdf_url" content="https://cdn.example/Kept.PDF">');
    assert.equal(stateFault.metadata.abstract,'A complete result.');assert.equal(stateFault.pdf_clues.status,'partial');
    assert.equal(stateFault.pdf_clues.candidates[0].url,'https://cdn.example/Kept.PDF');
    const currentPii='S0047259X2400006X',currentPDF='/science/article/pii/'+currentPii+'/pdfft?md5=synthetic';
    const toolbar=await forHost('www.sciencedirect.com','<nav><a href="'+currentPDF+'">View PDF</a><a href="https://pdf.sciencedirectassets.com/1-s2.0-'+currentPii+'/main.pdf?token=synthetic">View PDF</a><a href="https://pdf.sciencedirectassets.com/1-s2.0-S1234567812345678/main.pdf">View PDF</a><a href="/science/article/pii/S1234567812345678/pdfft">View PDF</a><a href="'+currentPDF+'&amp;supplement=1">Supplement PDF</a></nav><aside><a href="'+currentPDF+'&amp;related=1">View PDF</a></aside>','','/science/article/pii/'+currentPii);
    assert.equal(toolbar.pdf_clues.candidates.length,2,'only current PII toolbar entrances are body clues');
    assert.equal(toolbar.pdf_clues.candidates[0].url,'http://www.sciencedirect.com:'+port+currentPDF);
    assert.equal(toolbar.pdf_clues.candidates[0].reader_kind,'sciencedirect');
    page=article('','<nav id="accessbar" aria-busy="true"></nav><script>fetch("/hydrated-pdf").then(r=>r.text()).then(markup=>document.querySelector("#accessbar").outerHTML=markup);</script>');
    browser.readDocument=async(...args)=>{
      const result=await read(...args);
      if(args[1]==='pdf' && !result.clues.candidates.length && delayedPDF) {
        const response=delayedPDF;delayedPDF=null;
        setTimeout(()=>response.end('<nav id="accessbar"><a href="'+currentPDF+'">View PDF</a></nav>'),2300);
      }
      return result;
    };
    const hydrated=await invoke('extract_paper_pdf_clues',{identity:{confirmed_article_url:'http://www.sciencedirect.com:'+port+'/science/article/pii/'+currentPii}});
    browser.readDocument=read;
    assert.equal(hydrated.outcome,'retrieved');
    assert.deepEqual(hydrated.pdf_clues.candidates.map(item=>item.url),['http://www.sciencedirect.com:'+port+currentPDF],
      'a current article toolbar hydrated after the initial empty PDF observation is retained');
    const readerRuntime=await forHost('www.sciencedirect.com','<script>var article={pdfDownload:{urlMetadata:'+JSON.stringify(longLink)+'}};</script>');
    assert.equal(readerRuntime.pdf_clues.candidates[0].url,longLink);
    const ieee=await forHost('ieeexplore.ieee.org','','','/document/12345');assert.deepEqual(ieee.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['article_number','12345']]);
    const an='22222222-222222222-22222',otherAn='11111111-111111111-11111';
    const lwwArticle=await forHost('journals.lww.com','<div class="related"><button onclick="PDFDownloadInit(\''+otherAn+'\')">Related PDF</button></div><button onclick="PDFDownloadInit(\''+an+'\')">PDF</button>','','/journal/fulltext/2026/paper.aspx');
    assert.deepEqual(lwwArticle.pdf_clues.identifiers.map(item=>item.value),[an]);
    for(const entry of ['<button onclick="PDFDownloadInit(\''+an+'\')">Supplementary PDF</button>',
      '<button data-doi="10.5555/other" onclick="PDFDownloadInit(\''+an+'\')">PDF</button>']) {
      const nonBody=await forHost('journals.lww.com',entry,'<meta name="citation_doi" content="10.5555/target">','/journal/fulltext/2026/paper.aspx');
      assert.equal(nonBody.pdf_clues.status,'complete');assert.deepEqual(nonBody.pdf_clues.identifiers,[],'AN controls retain body-entry label and identity qualification');
    }
    const ownAn=await forHost('journals.lww.com','<button data-doi="10.5555/target" onclick="PDFDownloadInit(\''+an+'\')">PDF</button>','<meta name="citation_doi" content="10.5555/target">','/journal/fulltext/2026/paper.aspx');
    assert.deepEqual(ownAn.pdf_clues.identifiers.map(item=>item.value),[an]);
    for(const key of ['bepress_citation_doi','dc.identifier','dcterms.identifier']) {
      const head='<meta name="'+key+'" content="https://doi.org/10.5555/TARGET"><meta name="'+key+'" content="10.5555/target">';
      const body='<button data-doi="10.5555/target" onclick="PDFDownloadInit(\''+an+'\')">PDF</button>';
      const aliasAn=await forHost('journals.lww.com',body,head,'/journal/fulltext/2026/paper.aspx');
      assert.deepEqual(aliasAn.pdf_clues.identifiers.map(item=>item.value),[an],key+' qualifies its own AN');
      const foreignAn=await forHost('journals.lww.com',body.replace('data-doi="10.5555/target"','data-doi="10.5555/other"'),head,'/journal/fulltext/2026/paper.aspx');
      assert.deepEqual(foreignAn.pdf_clues.identifiers,[],key+' still rejects a foreign AN control');
    }
    for(const [raw,folded] of [['Straße','strasse'],['Σς','σσ'],['ﬃ','ffi'],['Ꭰꭰ','ᎠᎠ']]) {
      const head='<meta charset="utf-8"><meta name="citation_doi" content="10.5555/'+raw+'"><meta name="dc.identifier" content="https://doi.org/10.5555/'+folded+'">';
      const body='<button data-doi="10.5555/'+raw+'" onclick="PDFDownloadInit(\''+an+'\')">PDF</button>';
      const equivalent=await forHost('journals.lww.com',body,head,'/journal/fulltext/2026/paper.aspx');
      assert.equal(equivalent.outcome,'retrieved',JSON.stringify(equivalent));
      assert.deepEqual(equivalent.pdf_clues.identifiers.map(item=>item.value),[an],raw+' equivalent DOI fields retain their own AN');
      const foreign=await forHost('journals.lww.com',body.replace('data-doi="10.5555/'+raw+'"','data-doi="10.5555/other"'),head,'/journal/fulltext/2026/paper.aspx');
      assert.deepEqual(foreign.pdf_clues.identifiers,[],raw+' still rejects a genuinely foreign DOI');
      const supplement=await forHost('journals.lww.com',body.replace('>PDF<','>Supplementary PDF<'),head,'/journal/fulltext/2026/paper.aspx');
      assert.deepEqual(supplement.pdf_clues.identifiers,[],raw+' still rejects supplementary material');
    }
    const unicodeLink=await forHost('onlinelibrary.wiley.com','<a data-doi="10.5555/Σς" href="/doi/pdf/10.5555/Σς">PDF</a>',
      '<meta charset="utf-8"><meta name="citation_doi" content="10.5555/σσ">');
    assert.deepEqual(unicodeLink.pdf_clues.candidates.map(item=>item.url),['http://onlinelibrary.wiley.com:'+port+'/doi/pdf/10.5555/%CE%A3%CF%82']);
    const unicodePath=await forHost('onlinelibrary.wiley.com','<a data-doi="10.5555/strasse" href="/doi/pdf/10.5555/STRASSE">PDF</a>',
      '<meta charset="utf-8">','/doi/abs/10.5555/Straße');
    assert.deepEqual(unicodePath.pdf_clues.candidates.map(item=>item.url),['http://onlinelibrary.wiley.com:'+port+'/doi/pdf/10.5555/STRASSE']);
    const conflictingUnicode=await forHost('journals.lww.com','<button data-doi="10.5555/Straße" onclick="PDFDownloadInit(\''+an+'\')">PDF</button>',
      '<meta charset="utf-8"><meta name="citation_doi" content="10.5555/Straße"><meta name="dc.identifier" content="10.5555/other">','/journal/fulltext/2026/paper.aspx');
    assert.equal(conflictingUnicode.outcome,'retrieved');assert.deepEqual(conflictingUnicode.pdf_clues.identifiers,[]);
    const peripheralAn=await forHost('journals.lww.com','<section id="relatedContent"><button onclick="PDFDownloadInit(\''+otherAn+'\')">PDF</button></section><section id="supplementary-files"><button onclick="PDFDownloadInit(\''+otherAn+'\')">PDF</button></section><button onclick="PDFDownloadInit(\''+an+'\')">PDF</button>','','/journal/fulltext/2026/paper.aspx');
    assert.deepEqual(peripheralAn.pdf_clues.identifiers.map(item=>item.value),[an]);
    const ambiguousAn=await forHost('journals.lww.com','<button onclick="PDFDownloadInit(\''+otherAn+'\')">PDF</button><button onclick="PDFDownloadInit(\''+an+'\')">PDF</button>','','/journal/fulltext/2026/paper.aspx');
    assert.deepEqual(ambiguousAn.pdf_clues.identifiers,[]);
    const manyAn=await forHost('journals.lww.com',Array.from({length:17},(_,i)=>'<button onclick="PDFDownloadInit(\'12345678-123456789-'+String(10000+i)+'\')">PDF</button>').join(''),'','/journal/fulltext/2026/paper.aspx');
    assert.equal(manyAn.outcome,'retrieved');assert.equal(manyAn.metadata.abstract,'A complete result.');assert.deepEqual(manyAn.pdf_clues.identifiers,[],'ambiguous IDs are not a DTO overflow');
    for(const route of ['/document/12345wrong','/document/12345/other','/article?arnumber=not-a-number','/article?arnumber=12345wrong','/article?arnumber=12345&arnumber=67890']) {
      const invalidId=await forHost('ieeexplore.ieee.org','','',route);assert.deepEqual(invalidId.pdf_clues.identifiers,[],route);
    }
    const numericQuery=await forHost('ieeexplore.ieee.org','','','/article?arnumber=67890');assert.deepEqual(numericQuery.pdf_clues.identifiers.map(item=>[item.kind,item.value]),[['article_number','67890']]);
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
    const readerIdentity={confirmed_article_url:sdReader.source_url};
    const verifiedReader=mode=>invoke('extract_paper_pdf_clues',{identity:readerIdentity,
      reader:{...sdReader,target:readerIdentity,url:sdReaderURL.replace('redirect-reader=1','verify-reader='+mode)}});
    const verified=await verifiedReader('same');
    assert.equal(verified.outcome,'retrieved',JSON.stringify(verified));
    assert.equal(verified.pdf_clues.landing_url,readerAsset+'?case=same');
    assert.deepEqual(verified.pdf_clues.candidates,[]);
    const assetPath=new URL(readerAsset).pathname;
    assert.deepEqual(requests.filter(request=>request.url.startsWith(assetPath)).map(request=>request.method),['GET','POST']);
    assert.equal(verified.reader_result?.url,readerAsset+'?case=same','the exact earlier asset GET survives verification');
    assert.equal(verified.reader_result.referer,null,'no unobserved Referer is added to the earlier GET');
    const changedAsset=await verifiedReader('different');
    assert.equal(changedAsset.outcome,'retrieved',JSON.stringify(changedAsset));
    assert.equal(changedAsset.pdf_clues.landing_url,readerAsset+'?case=changed');
    assert.equal(changedAsset.reader_result,undefined,'a verified landing with a different query cannot reuse the old GET');
    const cookieContext=browser.sessionEvents.cookieContext;
    let cookieReads=0,replacedReader;
    browser.sessionEvents.cookieContext=async entry=>{
      if(++cookieReads===2)await browser.taskTab.view.webContents.loadURL(readerAsset+'?case=replacement');
      return cookieContext.call(browser.sessionEvents,entry);
    };
    try {replacedReader=await verifiedReader('same');}
    finally {browser.sessionEvents.cookieContext=cookieContext;}
    assert.equal(cookieReads,2);
    assert.equal(replacedReader.pdf_clues.landing_url,readerAsset+'?case=same');
    assert.equal(replacedReader.reader_result,undefined,'a new navigation during the cookie read has no verified handoff');
    const unsafe=await invoke('extract_paper_pdf_clues',{reader:{...sdReader,url:sdReaderURL.replace('redirect-reader=1','internal-redirect=1')}});assert.ok(unsafe.diagnostic);assert.ok(!requests.some(item=>item.url==='/forbidden'),'internal redirect is blocked before its request');
    page='<!doctype html><body><iframe src="/reader-next/IEEE.PDF?signature=AbC"></iframe></body>';
    const ieeeReader={target:data.identity,rule_id:'R025',platform:'ieee',url:'http://ieeexplore.ieee.org:'+port+'/stamp/stamp.jsp?tp=&arnumber=12345',identifier:'12345',source_url:'https://ieeexplore.ieee.org/document/12345',stage:'P2'};
    const ieeeNext=await invoke('extract_paper_pdf_clues',{reader:ieeeReader});assert.equal(ieeeNext.pdf_clues.candidates[0].url,'http://ieeexplore.ieee.org:'+port+'/reader-next/IEEE.PDF?signature=AbC');assert.equal(ieeeNext.pdf_clues.candidates[0].stage,'P2');
    page='<!doctype html><frameset><frame src="/reader-next/first"><frame src="/reader-next/Second.PDF?sig=2"></frameset>';
    const opticaReader={target:data.identity,rule_id:'R053',platform:'optica',url:'http://opg.optica.org:'+port+'/viewmedia.cfm?uri=ao-10-1-1',identifier:'ao-10-1-1',source_url:'https://opg.optica.org/abstract.cfm?uri=ao-10-1-1',stage:'P3'};
    const optica=await invoke('extract_paper_pdf_clues',{reader:opticaReader});assert.equal(optica.pdf_clues.candidates.length,1);assert.equal(optica.pdf_clues.candidates[0].url,'http://opg.optica.org:'+port+'/reader-next/Second.PDF?sig=2');assert.equal(optica.pdf_clues.candidates[0].stage,'P3');
    challengeResponse=true;page='<!doctype html><title>Just a moment</title><body><iframe src="/reader-next/fake.pdf"></iframe></body>';
    const refused=await invoke('extract_paper_pdf_clues',{reader,deadline_ms:Date.now()+500});assert.ok(refused.diagnostic);assert.ok(!refused.pdf_clues);challengeResponse=false;
    assert.ok((await invoke('extract_paper_pdf_clues',{reader:{...reader,identifier:'wrong'}})).diagnostic);
    // OCE uses its own prepared retained target, including when preparation
    // originally entered through CARSI. Capability reads never navigate.
    const scoped={service_scope:{scope_id:'b'.repeat(64),config_revision:'c'.repeat(64),user_state_revision:'d'.repeat(64)},service_id:'svc_'+'e'.repeat(32),preparation_key:'f'.repeat(64)};
    const capability=await invoke('extract_paper_pdf_clues',{reader_access_only:true});
    assert.deepEqual(capability.reader_access,{oce:false});assert.deepEqual(requests,[]);
    let retained;page=article();
    await browser.runTask(new AbortController().signal,{...scoped,request_id:randomUUID()},async()=>{
      retained=await browser.newTaskPage({deadline:Date.now()+4000,managed:true});browser.bindTaskPage(retained);
      await browser.navigate('http://oce.ovid.com:'+port+'/',{tab:retained,deadline:Date.now()+4000});browser.retainAccessPage(retained,scoped);
    });
    const own={...scoped,target_page_id:retained.id};
    assert.deepEqual((await invoke('extract_paper_pdf_clues',{...own,reader_access_only:true})).reader_access,{oce:true});assert.deepEqual(requests,[]);
    assert.ok((await invoke('extract_paper_pdf_clues',{...own,preparation_key:'0'.repeat(64),reader_access_only:true})).diagnostic,'revoked preparation cannot grant a capability');assert.deepEqual(requests,[]);
    const oceURL='https://oce.ovid.com/article/'+an+'/HTML',signed='https://assets.ovid.com/Body.PDF?Signature=A%2FB&key=Keep';
    const oceReader={rule_id:'R060',platform:'oce',url:oceURL,identifier:an,target:data.identity,source_url:oceURL,stage:'P4'};
    page='<!doctype html><body><iframe src="/pdfviewer/web/viewer.html?file='+encodeURIComponent(signed)+'"></iframe><iframe src="/arbitrary?file=https://bad.example/other.pdf"></iframe></body>';
    const oce=await invoke('extract_paper_pdf_clues',{...own,reader:oceReader});
    assert.equal(oce.outcome,'retrieved',JSON.stringify(oce));assert.equal(oce.pdf_clues.landing_url,oceURL);
    assert.deepEqual(oce.pdf_clues.candidates.map(item=>[item.url,item.rule_id,item.stage]),[[signed,'R060','P4']]);assert.ok(!requests.some(item=>item.url.includes('/Body.PDF')));
    assert.ok((await invoke('extract_paper_pdf_clues',{reader:oceReader})).diagnostic,'LWW/public context never grants OCE access');
    assert.ok((await invoke('extract_paper_pdf_clues',{...own,reader:{...oceReader,identifier:otherAn}})).diagnostic);
    page=article();await retained.view.webContents.loadURL('http://journals.lww.com:'+port+'/');
    assert.deepEqual((await invoke('extract_paper_pdf_clues',{...own,reader_access_only:true})).reader_access,{oce:false});
    assert.ok((await invoke('extract_paper_pdf_clues',{...own,reader:oceReader})).diagnostic,'retained non-OCE context is refused');
    await browser.closePage(retained);
    assert.ok((await invoke('extract_paper_pdf_clues',{...own,reader_access_only:true})).diagnostic,'closed preparation cannot be renewed');
    // Use real Session webRequest callbacks for the viewer subresource.
    browser.partition.protocol.unhandle('https');
    browser.partition.setCertificateVerifyProc((request,callback)=>callback(ebscoHosts.includes(request.hostname)
      && new X509Certificate(request.certificate.data).fingerprint256===fingerprint?0:-3));
    const prepareEbsco=async()=>{
      if(retained)await browser.closePage(retained);
      await browser.runTask(new AbortController().signal,{...scoped,request_id:randomUUID()},async()=>{
        retained=await browser.newTaskPage({deadline:Date.now()+4000,managed:true});
        await browser.navigate('https://search.ebscohost.com/Community.aspx',{tab:retained,deadline:Date.now()+4000});
        browser.retainAccessPage(retained,scoped);
      });
    };
    await prepareEbsco();
    let licensed={...scoped,target_page_id:retained.id,prepared_source:'ebsco',
      identity:{doi:'10.5555/fixture'},target_title:'Licensed fixture'};
    const freshProfile=async()=>{await prepareEbsco();licensed={...licensed,target_page_id:retained.id};};
    const found=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(found.outcome,'retrieved',JSON.stringify({found,requests}));
    assert.equal(found.pdf_clues.landing_url,ebscoProfile+'/search/details/record');
    assert.equal(found.pdf_clues.candidates[0].url,ebscoPdf);
    assert.equal(found.pdf_clues.candidates[0].rule_id,'R073');
    assert.ok(requests.some(request=>request.url==='/c/test-profile/search/results?q=10.5555%2Ffixture'));
    assert.ok(requests.some(request=>request.url===viewerPath+viewerQuery),'keep the actual viewer action and query');
    assert.ok(!requests.some(request=>request.url.includes('/viewer/pdf/related')));
    assert.equal(requests.filter(request=>request.url.startsWith('/files/licensed')).length,1,'Viewer supplies the observed PDF GET');
    assert.equal(retained.view.webContents.getURL(),'https://search.ebscohost.com/Community.aspx');
    ebscoMode='profile-postback';await freshProfile();
    const community=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(community.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify(community));
    assert.deepEqual(requests.filter(request=>request.url==='/webauth/Community.aspx').map(request=>request.method),['POST']);
    assert.equal(retained.view.webContents.getURL(),'https://search.ebscohost.com/Community.aspx');
    ebscoMode='profile-postback-several';await freshProfile();
    const severalProfiles=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(severalProfiles.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify(severalProfiles));
    assert.deepEqual(requests.filter(request=>request.method==='POST').map(request=>request.url),['/webauth/Community.aspx']);
    ebscoMode='profile-postback-other-origin';await freshProfile();
    const wrongPost=await invoke('extract_paper_pdf_clues',licensed);
    assert.ok(wrongPost.diagnostic && !wrongPost.pdf_clues);
    assert.equal(requests.filter(request=>request.method==='POST').length,0,'the submitted destination is checked before any POST');
    ebscoMode='profile-postback-subframe';await freshProfile();
    const wrongFrame=await invoke('extract_paper_pdf_clues',licensed);
    assert.ok(wrongFrame.diagnostic && !wrongFrame.pdf_clues);
    assert.equal(requests.filter(request=>request.method==='POST').length,0,'a changed form target cannot POST in a child frame');
    ebscoMode='profile-postback-redirect-post';await freshProfile();
    const replayPost=await invoke('extract_paper_pdf_clues',licensed);
    assert.ok(replayPost.diagnostic && !replayPost.pdf_clues);
    assert.equal(requests.filter(request=>request.method==='POST').length,1,'a 307 does not replay the managed form');
    ebscoMode='direct-link';await freshProfile();
    const direct=await invoke('extract_paper_pdf_clues',licensed);
    assert.deepEqual(direct.pdf_clues?.candidates?.map(item=>item.url),
      ['https://research.ebsco.com'+downloadLink,ebscoPdf]);
    assert.ok(requests.some(request=>new URL(request.url,ebscoProfile).searchParams.get('opid')==='test-profile'));
    assert.ok(!requests.some(request=>request.url.startsWith(viewerPath) || request.url.startsWith('/files/licensed')));
    ebscoMode='viewer';
    const fixedViewer={...licensed,prepared_source:'ebsco-viewer',prepared_viewer:direct.ebsco_viewer_url};
    const wrongRecord=await invoke('extract_paper_pdf_clues',{...fixedViewer,prepared_record:'https://research.ebsco.com'+recordPath+'-other'});
    assert.ok(wrongRecord.diagnostic && !wrongRecord.pdf_clues);
    assert.ok(!requests.some(request=>request.url.startsWith(viewerPath)),'another record cannot supply the direct entry fallback');
    const sameRecord=await invoke('extract_paper_pdf_clues',{...fixedViewer,prepared_record:'https://research.ebsco.com'+recordPath});
    assert.equal(sameRecord.pdf_clues?.candidates[0]?.url,ebscoPdf);
    assert.ok(!requests.some(request=>request.url==='/Community.aspx' || request.url.startsWith(resultsPath)
      || request.url===recordPath),'fallback uses the captured Viewer without repeating preparation or search');
    ebscoMode='pending-asset';
    const pendingAsset=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(pendingAsset.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify({pendingAsset,requests}));
    assert.ok(!requests.some(request=>request.url==='/Community.aspx'),'prepared profile is reused across downloads');
    ebscoMode='ambiguous';
    const ambiguous=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(ambiguous.diagnostic?.step,'result');
    assert.ok(!requests.some(request=>request.url.startsWith(recordPath)));
    ebscoMode='record-in-app';
    const inAppRecord=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(inAppRecord.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify({inAppRecord,requests}));
    assert.equal(inAppRecord.pdf_clues.landing_url,'https://research.ebsco.com'+recordPath+'?db=licensed');
    assert.ok(!requests.some(request=>request.url===recordPath),'the working record route keeps the search document');
    assert.ok(requests.some(request=>request.url==='/ebsco-pending-image'),'the verified Viewer can provide the PDF while an unrelated asset is pending');
    ebscoMode='viewer';
    const documentCall=browser.documents.call.bind(browser.documents);
    let readRaced=false;
    browser.documents.call=async (binding,action,args,options)=>{
      if(!readRaced && action==='ebsco' && args.mode==='results') {
        readRaced=true;
        const contents=browser.tabs.get(binding.pageId).view.webContents;
        await contents.executeJavaScript('history.replaceState(null,"",location.href+"&db=licensed")');
      }
      return documentCall(binding,action,args,options);
    };
    try {
      const raced=await invoke('extract_paper_pdf_clues',licensed);
      assert.ok(readRaced);
      assert.equal(raced.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify(raced));
      assert.equal(requests.filter(request=>request.url.startsWith(resultsPath)).length,1,'only the local document read is retried');
    } finally {browser.documents.call=documentCall;}
    ebscoMode='replace-search';
    let replacementStarted=false;
    browser.events.once('tab-created',(_event,tab)=>{
      tab.view.webContents.on('did-start-navigation',(event,url,inPlace,main)=>{
        if((event.isMainFrame ?? main) && !(event.isSameDocument ?? inPlace) && (event.url ?? url).endsWith('&replacement=1'))
          replacementStarted=true;
      });
    });
    const replacedSearch=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(replacedSearch.pdf_clues?.candidates[0]?.url,ebscoPdf,JSON.stringify(replacedSearch));
    assert.ok(replacementStarted,'a full replacement triggers a fresh observation of the same search');
    ebscoMode='expired-search';await freshProfile();
    const expiredSearch=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(expiredSearch.diagnostic?.code,'content_access_blocked',JSON.stringify(expiredSearch));
    assert.ok(!requests.some(request=>request.url===recordPath));
    ebscoMode='delayed';
    const delayed=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(delayed.pdf_clues?.candidates[0]?.url,ebscoPdf,'title-only intermediate state must not stop extraction');
    ebscoMode='html-only';
    const htmlOnly=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(htmlOnly.outcome,'retrieved');
    assert.deepEqual(htmlOnly.pdf_clues.candidates,[],'a ready HTML-only record releases this source for fallback');
    ebscoMode='preview';
    const preview=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(preview.outcome,'retrieved',JSON.stringify({preview,requests}));
    assert.equal(preview.pdf_clues.candidates[0].url,ebscoPdf,'distinct automatic previews cannot qualify the body');
    assert.ok(requests.some(request=>request.url===viewerPath+viewerQuery));
    assert.equal(requests.filter(request=>request.url.startsWith('/files/licensed')).length,1);
    ebscoDOI='10.5555/different';
    const wrong=await invoke('extract_paper_pdf_clues',licensed);
    assert.ok(wrong.diagnostic && !wrong.pdf_clues,'the actual licensed record must match the Paper DOI');
    assert.ok(!requests.some(request=>request.url.includes('/viewer/pdf/')));
    ebscoMode='expired';
    const expired=await invoke('extract_paper_pdf_clues',licensed);
    assert.equal(expired.diagnostic?.code,'content_access_blocked',JSON.stringify(expired));
    assert.ok(!requests.some(request=>request.url.includes('/viewer/pdf/')));
    ebscoMode='unsafe';
    const unsafeEbsco=await invoke('extract_paper_pdf_clues',licensed);
    assert.ok(unsafeEbsco.diagnostic && !unsafeEbsco.pdf_clues);
    assert.ok(!requests.some(request=>request.url==='/ebsco-forbidden'),'private redirect is refused before sending');
    await browser.closePage(retained);
    console.log('PDF CLUES PASS');
  } finally {await browser.close();host.destroy();await Promise.all([server,secureServer].map(listener=>new Promise(resolve=>listener.close(resolve))));}
})().then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
