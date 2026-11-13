'use strict';
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict');
const {randomUUID}=require('node:crypto');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {checkPage}=require('../src/browser/browser-errors.cjs');
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
app.whenReady().then(async()=>{
  const host=new BrowserWindow({show:false,width:800,height:600});
  let solved=0;
  const browser=new BrowserRuntime({hostWindow:host,solveCloudflare:async()=>{solved++;return {outcome:'clicked'};}});
  const routes=new Map();let destination;
  const html=(body,meta='')=>'<!doctype html><html><head>'+meta+'</head><body>'+body+'</body></html>';
  const article=(meta='')=>html('<article><h1>Target article</h1></article>',meta);
  const meta=(doi,key='citation_doi')=>'<meta name="'+key+'" content="'+doi+'">';
  const signal=new AbortController().signal;
  const task=run=>browser.operation?run():browser.runTask(signal,{request_id:randomUUID()},run);
  const open=async(body,doi='10.5555/target',options={})=>{
    destination='https://article.invalid/current';routes.set(destination,{body});
    return task(()=>browser.openPaperPage({workspace_identity:'a'.repeat(64),paper_id:randomUUID()},doi,{signal,deadline:Date.now()+2000,...options}));
  };
  try {
    await browser.ready;
    browser.partition.protocol.handle('https',request=>{
      if(request.url.startsWith('https://doi.org/'))return new Response('<script>location.replace('+JSON.stringify(destination)+')</script>',{headers:{'content-type':'text/html'}});
      const route=routes.get(request.url.split('#')[0]);
      return new Response(route?.body || article(),{status:route?.status || 200,headers:{'content-type':'text/html'}});
    });
    // No author/date/abstract or extraction runtime exists on these article pages.
    for(const key of ['citation_doi','bepress_citation_doi','prism.doi','dc.identifier','dc.identifier.doi','dcterms.identifier']) {
      const doc=await open(article(meta(' DOI: 10.5555/TARGET ',key)));
      assert.equal(doc.identity.outcome,'confirmed');assert.equal(doc.identity.doi,'10.5555/target');
      assert.equal(doc.html,undefined);assert.equal(typeof doc.documentId,'string');
    }
    for(const [body,code] of [
      [article(meta('10.5555/other')),'article_identity_conflict'],
      [article(meta('10.5555/target')+meta('10.5555/other')),'article_identity_conflict'],
      [html('<article></article><article></article>',meta('10.5555/target')),'article_identity_unconfirmed'],
      [article(meta('ISSN 1234-5678','dc.identifier')),'article_identity_unconfirmed'],
      [html('<article><section id="references">10.5555/target</section><iframe src="https://frame.invalid/"></iframe></article>'),'article_identity_unconfirmed'],
      [article(meta('10.5555/target').repeat(33)),'article_identity_unconfirmed'],
      [article(),'article_identity_unconfirmed'],
      [html('<p>CPE00001</p><p>There was a problem providing the content you requested</p>',meta('10.5555/target')),'content_access_blocked'],
      [html('<div><span>CPE00001</span><div>There was a problem providing the content you requested</div></div>',meta('10.5555/target')),'content_access_blocked'],
      [html('<p>'+('x'.repeat(3000))+' CPE00001 There was a problem providing the content you requested</p>',meta('10.5555/target')),'content_access_blocked'],
    ])await assert.rejects(open(body),error=>error.diagnostic?.code===code);
    for(const body of [html('<input type="password">',meta('10.5555/target')),html('<h1>Are you a robot?</h1><p>Please confirm you are a human by completing the captcha challenge</p>',meta('10.5555/target'))])
      await assert.rejects(open(body,'10.5555/target',{deadline:Date.now()+200}),error=>error.diagnostic?.code==='timeout');
    destination='https://article.invalid/doi/10.1214/aos/1176342506';routes.set(destination,{body:article()});
    const multiDOI=await task(()=>browser.openPaperPage({workspace_identity:'a'.repeat(64),paper_id:randomUUID()},'10.1214/aos/1176342506',{signal}));
    assert.equal(multiDOI.identity.outcome,'confirmed');
    destination='https://iopscience.iop.org/article/10.1088/0022-3727/34/10/311/meta';
    routes.set(destination,{body:article(meta('10.1088/0022-3727/34/10/311'))});
    const iop=await task(()=>browser.openPaperPage({workspace_identity:'a'.repeat(64),paper_id:randomUUID()},'10.1088/0022-3727/34/10/311',{signal}));
    assert.equal(iop.identity.outcome,'confirmed');
    // A resolver URL (the requested DOI) never proves the redirected article.
    destination='https://article.invalid/path/10.5555/target';routes.set(destination,{body:article()});
    for(const [url,body] of [
      ['https://projecteuclid.org/journals/example/10.5555/target.full',article()],
      ['https://www.scielo.br/j/example/a/fixture',html('<article><a class="_doi" href="https://doi.org/10.5555/target">DOI</a></article>')],
      ['https://journals.plos.org/plosone/article?doi=10.5555%2Ftarget',article()],
    ]) {
      destination=url;routes.set(url,{body});
      const located=await task(()=>browser.openPaperPage({workspace_identity:'a'.repeat(64),paper_id:randomUUID()},'10.5555/target',{signal}));
      assert.equal(located.identity.outcome,'confirmed');
    }
    for(const [url,body,code] of [
      ['https://article.invalid/article?doi=10.5555%2Ftarget&id=10.5555%2Fother',article(),'article_identity_conflict'],
      ['https://article.invalid/?doi=10.5555%2Ftarget',html('<p>Generic redirect</p>'),'article_identity_unconfirmed'],
      ['https://article.invalid/search?doi=10.5555%2Ftarget',html('<main><h1>Search results</h1></main>'),'article_identity_unconfirmed'],
      ['https://article.invalid/search?doi=10.5555%2Ftarget',html('<main><article>Recommended target</article></main>'),'article_identity_unconfirmed'],
      ['https://article.invalid/10.5555/other/part',html('<div>Article</div>',meta('10.5555/target')),'article_identity_conflict'],
      ['https://article.invalid/10.5555/other',html('<div>Article</div>',meta('10.5555/target')),'article_identity_conflict'],
      ['https://article.invalid/native',html('<a class="_doi" href="https://doi.org/10.5555/target">DOI</a>'),'article_identity_unconfirmed'],
    ]) {
      destination=url;routes.set(url,{body});
      await assert.rejects(task(()=>browser.openPaperPage({workspace_identity:'a'.repeat(64),paper_id:randomUUID()},'10.5555/target',{signal})),error=>error.diagnostic?.code===code);
    }
    destination='https://article.invalid/path/10.5555/target';routes.set(destination,{body:article()});
    await task(async()=>{
    const data={workspace_identity:'a'.repeat(64),paper_id:randomUUID()};
    const doc=await task(()=>browser.openPaperPage(data,'https://dx.doi.org/10.5555/TARGET',{signal}));
    assert.equal(doc.identity.reason,'doi');
    const tab=browser.tabs.get(doc.pageId),wc=tab.view.webContents;
    assert.ok(tab.view.getBounds().width>0 && tab.view.getBounds().height>0);
    assert.equal(browser.selected,null);assert.equal(browser.presentation.visible,false);
    const duplicate=browser.createTab({present:false,user:true});await duplicate.view.webContents.loadURL(doc.url);
    const other=await browser.runInOperation(null,()=>browser.documentBinding(duplicate));
    assert.notEqual(other.documentId,doc.documentId);assert.notEqual(other.pageId,doc.pageId);
    // Same native Document, changed primary object: the cached input cannot bypass confirmation.
    await wc.executeJavaScript('document.head.insertAdjacentHTML("beforeend",\'<meta name="citation_doi" content="10.5555/other">\')');
    await assert.rejects(task(()=>browser.openPaperPage(data,'10.5555/target',{signal})),error=>error.diagnostic?.code==='article_identity_conflict');
    await wc.executeJavaScript('history.pushState({},"","/changed")');
    assert.equal(browser.documentCurrent(doc),false);
    const before=await browser.documentBinding(tab);
    assert.equal(before.documentId,doc.documentId,'same-document routes retain native Document identity');
    assert.notEqual(before.navigationGeneration,doc.navigationGeneration,'URL facts still invalidate the prior binding');
    await wc.loadURL('https://article.invalid/replacement');assert.equal(browser.documentCurrent(before),false);
    const doomed=await browser.runInOperation(null,()=>browser.documentBinding(duplicate));
    const crashed=new Promise(resolve=>duplicate.view.webContents.once('render-process-gone',resolve));
    duplicate.view.webContents.forcefullyCrashRenderer();await crashed;
    assert.equal(browser.documentCurrent(doomed),false);
    // Explicit upstream article relation is necessary for DOI-free access.
    destination='https://article.invalid/native/42';routes.set(destination,{body:article()});
    const noDOI=await task(()=>browser.openPaperPage({...data,paper_id:randomUUID()},{confirmed_article_url:destination},{signal}));
    assert.equal(noDOI.identity.reason,'established_article_url');
    await browser.closePage(browser.tabs.get(noDOI.pageId));
    await assert.rejects(task(()=>browser.openPaperPage(data,{}, {signal})),/article_identity_unconfirmed/);
    const fragmentTarget='https://article.invalid/#/article/one';
    const fragment=await task(()=>browser.openPaperPage({...data,paper_id:randomUUID()},{confirmed_article_url:fragmentTarget},{signal}));
    assert.equal(fragment.url,fragmentTarget);
    await task(async()=>{
      const page=browser.tabs.get(fragment.pageId);browser.bindTaskPage(page,signal);
      await page.view.webContents.executeJavaScript('history.replaceState({},"","/#/article/two")');
      const current=await browser.documentBinding(page);
      await assert.rejects(browser.confirmArticlePage({confirmed_article_url:fragmentTarget},current,{signal}),/article_identity_unconfirmed/);
    });
    await browser.closePage(browser.tabs.get(fragment.pageId));
    // Large unrelated DOM never leaves the preload. Resource-only CAPTCHA/CDN is not a challenge.
    destination='https://article.invalid/bounded';routes.set(destination,{body:article(meta('10.5555/target'))});
    await wc.loadURL(destination);
    const small=await browser.accessState(tab);
    await wc.executeJavaScript('document.body.insertAdjacentHTML("beforeend",'+JSON.stringify('<div>'+('unrelated '.repeat(100000))+'</div><script src="/cdn-cgi/ordinary.js"></script><div class="cf-turnstile"></div>')+')');
    const large=await browser.accessState(tab);
    assert.ok(JSON.stringify(large).length<1200);checkPage(200,large);
    assert.equal(JSON.stringify(small.markers),JSON.stringify(large.markers));
    const challenge=html('<script>window._cf_chl_opt = {};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>',meta('10.5555/target'));
    for(const [body,status,code,diagnostic] of [
      [challenge,200,'verification_page'],
      [html('<script>'+('/* unrelated */'.repeat(2000))+'window._cf_chl_opt = {};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>'),200,'verification_page'],
      [html(('<iframe loading="lazy" src="about:blank"></iframe>'.repeat(256))+'<iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe>'),200,'verification_page'],
      [html('','<title>Just a moment...</title>'),503,'verification_page'],
      [html('','<title>Unusual Traffic Detected (Error 418)</title>'),200,'site_restricted'],
      [article(meta('10.5555/target')),418,'site_restricted'],
      [article(meta('10.5555/target')),403,'http_error'],
      [html('<iframe src="/_Incapsula_Resource?edet=15&incident_id=123-456&secret=private">Request unsuccessful. Incapsula incident ID: 123-456</iframe>'),200,'site_restricted',{imperva_edet:15,imperva_incident_id:'123-456'}],
      [html('<iframe src="/_Incapsula_Resource?edet=15&edet=16&incident_id=111-222">Request unsuccessful. Incapsula incident ID: 333-444</iframe>'),200,'site_restricted'],
      [html('<iframe src="/_Incapsula_Resource?edet=12&incident_id=123-456">Request unsuccessful. Incapsula incident ID: 123-456</iframe>'),200,'verification_page',{imperva_edet:12,imperva_incident_id:'123-456'}],
      [html('<iframe src="https://newassets.hcaptcha.com/captcha/v1"></iframe>'),200,'verification_page'],
    ]) {
      routes.set(destination,{body,status});await wc.loadURL(destination);
      const probe=await browser.accessState(tab);
      assert.throws(()=>checkPage(status,probe),error=>error.diagnostic.code===code && (!diagnostic || Object.entries(diagnostic).every(([key,value])=>error.diagnostic[key]===value)));
      assert.ok(!JSON.stringify(probe).includes('private'));
    }
    routes.set(destination,{body:html('<article>Normal target</article><iframe style="display:none" src="https://newassets.hcaptcha.com/captcha/v1"></iframe>',meta('10.5555/target'))});
    await wc.loadURL(destination);
    await task(async()=>{
      browser.bindTaskPage(tab,signal);
      const normal=await browser.waitForPage(tab,{signal,deadline:Date.now()+1000});
      assert.equal((await browser.confirmArticlePage({doi:'10.5555/target'},normal,{signal})).identity.outcome,'confirmed');
    });
    assert.equal(solved,0);
    // Click is not completion; same-operation repeats cannot replenish the attempt budget.
    routes.set(destination,{body:challenge});await wc.loadURL(destination);
    await task(async()=>{
      browser.beginPageLoad(tab,signal,Date.now()+2000);
      await require('../src/browser/browser-task.cjs').waitForLoad(tab,signal,Date.now()+2000);
      assert.equal((await browser.inspectPage(tab,{signal})).recheck,true);
      assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
      assert.equal(solved,1);
      await wc.executeJavaScript('document.body.innerHTML="<article></article>"');
      const ready=await browser.waitForPage(tab,{signal,deadline:Date.now()+1000});
      assert.equal(ready.status,200);
      const confirmed=await browser.confirmArticlePage({doi:'10.5555/target'},ready,{signal});
      assert.equal(confirmed.identity.outcome,'confirmed');
    });
    });
    assert.equal(browser.paperPages.size,0);assert.equal(browser.tabs.size,1,'only explicit user duplicate remains');
    assert.equal(browser.documents.pending.size,0);
    console.log('DOCUMENT PROBES PASS');
  }finally {await browser.close();host.destroy();}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
