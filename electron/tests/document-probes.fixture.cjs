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
  const browser=new BrowserRuntime({hostWindow:host,solveCloudflare:async(_tab,{signal,onProgress})=>{solved++;onProgress({outcome:'clicked',reason:'checkbox_clicked'});
    await new Promise(resolve=>signal.addEventListener('abort',resolve,{once:true}));return {outcome:'not_executed',reason:'canceled'};}});
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
    // Normal content can include optional authentication and verification resources.
    for(const extra of ['<iframe hidden src="https://newassets.hcaptcha.com/captcha/v1"></iframe>',
      '<input type="password"><p>access denied, hcaptcha and g-recaptcha are ordinary text</p>',
      '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script><div class="cf-turnstile"></div>',
      '<script>window._cf_chl_opt = {};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>']) {
      const doc=await open(html('<article><h1>Normal content</h1><p>Abstract</p></article>'+extra));
      assert.equal(doc.status,200);
    }
    await assert.rejects(open(html('<main><h1>Welcome back</h1><form><input name="username"><input type="password"><button>Sign in</button></form></main>','<title>Publisher</title>'),
      '10.5555/target',{deadline:Date.now()+300}),error=>error.diagnostic?.code==='timeout');
    // Run supplies the Paper identity; page metadata is not a second admission gate.
    for(const body of [article(),article(meta('10.5555/other')),article(meta('10.5555/target')+meta('10.5555/other')),
      html('<article></article><article></article>',meta('10.5555/target')),article(meta('10.5555/target').repeat(33))]) {
      const doc=await open(body);
      assert.equal(doc.identity.doi,'10.5555/target');assert.equal(doc.html,undefined);
    }
    for(const body of [html('<p>CPE00001</p><p>There was a problem providing the content you requested</p>'),
      html('<div><span>CPE00001</span><div>There was a problem providing the content you requested</div></div>'),
      html('<p>'+('x'.repeat(3000))+' CPE00001 There was a problem providing the content you requested</p>')])
      await assert.rejects(open(body),error=>error.diagnostic?.code==='content_access_blocked');
    for(const body of [html('<form><input type="password"></form>','<title>Login required</title>'+meta('10.5555/target')),html('<h1>Are you a robot?</h1><p>Please confirm you are a human by completing the captcha challenge</p>',meta('10.5555/target'))])
      await assert.rejects(open(body,'10.5555/target',{deadline:Date.now()+200}),error=>error.diagnostic?.code==='timeout');
    destination='https://article.invalid/path/10.5555/target';routes.set(destination,{body:article()});
    await task(async()=>{
    const data={workspace_identity:'a'.repeat(64),paper_id:randomUUID()};
    const doc=await task(()=>browser.openPaperPage(data,'https://dx.doi.org/10.5555/TARGET',{signal}));
    assert.equal(doc.identity.doi,'https://dx.doi.org/10.5555/TARGET');
    const tab=browser.tabs.get(doc.pageId),wc=tab.view.webContents;
    assert.ok(tab.view.getBounds().width>0 && tab.view.getBounds().height>0);
    assert.equal(browser.selected,null);assert.equal(browser.presentation.visible,false);
    const duplicate=browser.createTab({present:false,user:true});await duplicate.view.webContents.loadURL(doc.url);
    const other=await browser.runInOperation(null,()=>browser.documentBinding(duplicate));
    assert.notEqual(other.documentId,doc.documentId);assert.notEqual(other.pageId,doc.pageId);
    // Reuse of a Paper page does not reauthenticate its metadata.
    await wc.executeJavaScript('document.head.insertAdjacentHTML("beforeend",\'<meta name="citation_doi" content="10.5555/other">\')');
    assert.equal((await task(()=>browser.openPaperPage(data,'10.5555/target',{signal}))).pageId,doc.pageId);
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
    assert.equal(noDOI.identity.confirmed_article_url,destination);
    await browser.closePage(browser.tabs.get(noDOI.pageId));
    await assert.rejects(task(()=>browser.openPaperPage(data,{}, {signal})),/document_operation_failed/);
    const fragmentTarget='https://article.invalid/#/article/one';
    const fragment=await task(()=>browser.openPaperPage({...data,paper_id:randomUUID()},{confirmed_article_url:fragmentTarget},{signal}));
    assert.equal(fragment.url,fragmentTarget);
    await task(async()=>{
      const page=browser.tabs.get(fragment.pageId);browser.bindTaskPage(page,signal);
      await page.view.webContents.executeJavaScript('history.replaceState({},"","/#/article/two")');
      const current=await browser.documentBinding(page);
      assert.equal(current.url,'https://article.invalid/#/article/two');
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
      assert.equal(normal.status,200);
    });
    // Page-level interaction remains pending until actual access evidence changes.
    routes.set(destination,{body:challenge});await wc.loadURL(destination);
    await task(async()=>{
      browser.beginPageLoad(tab,signal,Date.now()+2000);
      await require('../src/browser/browser-task.cjs').waitForLoad(tab,signal,Date.now()+2000);
      assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
      assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
      assert.ok(solved>0);
      await wc.executeJavaScript('document.body.innerHTML="<article></article>"');
      const ready=await browser.waitForPage(tab,{signal,deadline:Date.now()+1000});
      assert.equal(ready.status,200);
    });
    // Publisher-owned robot copy can wrap a genuine Turnstile in a closed shadow root.
    const frameURL='https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/fixture';
    routes.set(frameURL,{body:html('<input type="checkbox">')});
    routes.set(destination,{body:html('<h1>Are you a robot?</h1><p>Please confirm you are a human by completing the captcha challenge</p>'
      +'<div id="widget"></div><script>document.getElementById("widget").attachShadow({mode:"closed"}).innerHTML='
      +JSON.stringify('<iframe src="'+frameURL+'"></iframe>')+'</script>',meta('10.5555/target'))});
    await wc.loadURL(destination);
    assert.equal((await browser.accessState(tab)).cloudflareFrame,true);
    assert.equal((await browser.inspectPage(tab,{signal})).waiting,true);
    await wc.executeJavaScript('document.querySelector("h1").remove();document.querySelector("p").remove()');
    assert.equal((await browser.inspectPage(tab,{signal})).waiting,false);
    assert.equal((await browser.accessState(tab)).markers.robot,false,'unrelated frame evidence does not keep access blocked');
    });
    assert.equal(browser.paperPages.size,0);assert.equal(browser.tabs.size,1,'only explicit user duplicate remains');
    assert.equal(browser.documents.pending.size,0);
    // Only the actual main request's response can establish a header challenge.
    const server=require('node:http').createServer((request,response)=>{
      const challenged=request.url==='/challenge' || request.url==='/aux';
      response.writeHead(200,{'content-type':'text/html',...(challenged?{'cf-mitigated':'challenge'}:{})});
      response.end(request.url==='/normal'?'<article><h1>Normal</h1></article><iframe hidden src="/aux"></iframe>':'<p>Waiting</p>');
    });
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    try {
      const headerPage=browser.createTab({user:true,present:false}),url='http://127.0.0.1:'+server.address().port;
      await headerPage.view.webContents.loadURL(url+'/challenge');
      const challenged=await browser.accessState(headerPage);
      assert.equal(challenged.cfMitigated,true);
      assert.throws(()=>checkPage(challenged.status,challenged),/verification_page/);
      await headerPage.view.webContents.loadURL(url+'/normal');
      const normal=await browser.waitForPage(headerPage,{deadline:Date.now()+1500});
      assert.equal(normal.cfMitigated,false,'unrelated subframe response cannot challenge the main page');
      await browser.closePage(headerPage);
    } finally {await new Promise(resolve=>server.close(resolve));}
    console.log('DOCUMENT PROBES PASS');
  }finally {await browser.close();host.destroy();}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
