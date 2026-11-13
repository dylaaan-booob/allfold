'use strict';
const {app,BrowserWindow}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {randomUUID}=require('node:crypto');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
require('../src/shared/logging.cjs').initializeLogging({stderr(){}});
const profile=process.argv[2];app.setPath('userData',profile);app.setPath('sessionData',profile);
app.whenReady().then(async()=>{
  const server=http.createServer((_request,response)=>{response.setHeader('content-type','text/html; charset=utf-8');response.end(page);});
  let page='';await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const url='http://127.0.0.1:'+server.address().port+'/article';
  const host=new BrowserWindow({show:false,width:800,height:600}),browser=new BrowserRuntime({hostWindow:host});
  const html=(body,meta='')=>'<!doctype html><head>'+meta+'</head><body>'+body+'</body>';
  const article=(body,meta='')=>html('<article><h1>Fixture paper</h1>'+body+'</article>',meta);
  const controller=new AbortController(),signal=controller.signal;
  const data={workspace_identity:'a'.repeat(64),paper_id:randomUUID(),identity:{confirmed_article_url:url},wantAbstract:true};
  const nativeMessages=[],native=vm.createContext({require:require('node:module').createRequire(require.resolve('../src/main.cjs')),browser,operations:new Map(),exiting:false,bridgeReady:true,AbortController,
    ...require('../src/shared/logging.cjs'),...require('../src/shared/recovery-summary.cjs'),...require('../src/workflows/recovery-authority.cjs'),
    ...require('../src/browser/browser-errors.cjs'),operationAssociation:require('../src/browser/page-association.cjs').operationAssociation,
    send:message=>nativeMessages.push(JSON.parse(JSON.stringify(message)))});
  const main=fs.readFileSync(path.join(__dirname,'../src/main.cjs'),'utf8');
  vm.runInContext(main.slice(main.indexOf('const CONTROL_ACTIONS='),main.indexOf('async function startPython(')),native);
  const extract=async(body,wantAbstract=true)=>{
    page=body;const id=randomUUID();
    await native.execute({id,action:'extract_paper_metadata',data:{...data,wantAbstract,deadline_ms:Date.now()+4000}});
    const result=nativeMessages.find(message=>message.type==='result' && message.id===id)?.data;
    assert.ok(result,'Main must settle the fixed action');
    if(result.diagnostic){const error=Error(result.diagnostic.code);error.diagnostic=result.diagnostic;throw error;}
    assert.equal(browser.paperPages.size,0,'Main sends its result only after actual native owner cleanup');
    return result;
  };
  try {
    await browser.ready;
    const actual=await extract(article('<p>Published 2020-05-02</p><section id="abstract"><h2>Abstract</h2><h3>Background</h3><p>β &lt; 0.05 and x².</p><h3>Methods</h3><p>Measured H<sub>2</sub>O.</p><h3>Results</h3><p>Short complete finding.</p></section>'));
    assert.deepEqual(actual.metadata,{dates:[{value:'2020-05-02',precision:'day'}],abstract:'Background\nβ < 0.05 and x².\nMethods\nMeasured H2O.\nResults\nShort complete finding.'});
    assert.equal(actual.outcome,'retrieved');assert.equal(browser.paperPages.size,0);
    if(process.argv[4]==='--sample-only') {
      assert.ok(process.argv[3]);fs.writeFileSync(process.argv[3],JSON.stringify(actual));
      console.log('DOCUMENT EXTRACTION PASS');return;
    }
    const dates=async(name,body,expected,meta='')=>{
      const result=await extract(article(body,meta),false);
      assert.deepEqual(result.metadata,{dates:expected.map(value=>({value,precision:value.length===7?'month':'day'})),abstract:null},name);
    };
    await dates('all explicit grammars','<p>2020/2/29</p><p>2021-03</p><p>2021/4</p><p>2 May 2020</p><p>June 3, 2020</p><p>Jul. 2020</p><p>2020 August</p><p>2020年9月4日</p><p>2020年10月</p><p>2020-11-05T00:30:00+14:00</p><p>13/02/2020</p><p>02/14/2020</p>',
      ['2020-02-13','2020-02-14','2020-02-29','2020-05-02','2020-06-03','2020-07','2020-08','2020-09-04','2020-10','2020-11-05','2021-03','2021-04']);
    await dates('invalid full candidates never degrade','<p>2020-02-30 2020-04-00 2021-02-29 31 April 2020 April 31, 2020 04/02/2020</p><p>2020-04junk SS-2025-0362 1023-1042 https://x.invalid/2020-05-02 10.5555/2020-06-02</p>',[]);
    await dates('future, duplicate and precision union','<p>2099-04 2099-04-02 2099-04-03 2099-04-02</p>',['2099-04-02','2099-04-03']);
    await dates('inline continuity and adjacent links','<p>20<span>26</span>-04-02</p><li><a>Issue 1</a><a>January 2026</a></li>',['2026-01','2026-04-02']);
    await dates('150 Unicode code points accepted','<p>'+('😀'.repeat(139))+' 2020-01-02</p>',['2020-01-02']);
    await dates('151 Unicode code points rejected','<p>'+('😀'.repeat(140))+' 2020-01-02</p>',[]);
    await dates('full li/tr cannot be bypassed','<li>'+('x'.repeat(151))+'<p>2020-01-02</p></li><table><tr><td>'+('x'.repeat(151))+'</td><td>2020-02-02</td></tr></table>',[]);
    await dates('ordinary div separates independent short blocks','<div>'+('x'.repeat(151))+'<p>2020-03-02</p></div><p>'+('x'.repeat(151))+' 2020-04-02</p><p>2020-04-02</p>',['2020-03-02','2020-04-02']);
    await dates('explicit exclusions and internal footer','<nav>2020-01-01</nav><p hidden>2020-02-01</p><p aria-hidden="true">2020-03-01</p><p style="display:none">2020-04-01</p><script>2020-05-01</script><footer><p>2020-06-01</p></footer>',['2020-06-01']);
    const root=await extract(html('<p>2020-01-01</p><article><h1>Paper</h1><p>'+('x'.repeat(151))+' 2020-01-01</p><p>2020-02-01</p></article><footer>2020-03-01</footer>'),false);
    assert.deepEqual(root.metadata.dates,[{value:'2020-02-01',precision:'day'}],'out-of-root short occurrence cannot qualify long in-root date');
    await dates('time uses complete record for display and datetime','<p><time datetime="2020-04-02T23:00:00-12:00">April 2020</time></p><p><time datetime="2020-05-02">2020-05-03</time></p><li>'+('x'.repeat(151))+'<time datetime="2020-06-02">Jun 2020</time></li><time datetime="PT5M">12:00</time>',
      ['2020-04-02','2020-05-02','2020-05-03']);
    for(const [key,value] of [['citation_publication_date','2020-01'],['citation_online_date','2020-02-02'],['citation_cover_date','2020-03-03'],['dc.date','2020-04'],['prism.publicationDate','2020-05'],['citation_date','2020-06']])
      await dates('scholarly Meta '+key,'',[value],'<meta property="'+key.toUpperCase()+'" content="'+value+'">');
    await dates('OG article condition','',[], '<meta property="article:published_time" content="2020-07-02"><meta name="dcterms.created" content="2020-08-02"><meta name="citation_year" content="2020">');
    await dates('OG article accepted','',['2020-07-02'],'<meta property="OG:TYPE" content="article"><meta property="ARTICLE:PUBLISHED_TIME" content="2020-07-02">');
    await dates('filter before precision merge','<p>'+('x'.repeat(151))+' 2020-04-02</p>',['2020-04'],'<meta name="citation_date" content="2020-04"><meta name="citation_online_date" content="Published 2020-05-02">');
    const ld=value=>'<script type="application/ld+json">'+JSON.stringify(value)+'</script>';
    const scholarly={'@context':'https://schema.org','@type':'ScholarlyArticle','@id':'urn:paper:one',datePublished:'2020-04',dateModified:'2020-04-02',abstract:'Structured abstract.'};
    for(const [name,value] of [
      ['top object',scholarly],['top array',[scholarly]],['graph',{'@context':'https://schema.org','@graph':[{'@type':'WebSite',datePublished:'2010-01-01'},scholarly]}],
      ['mainEntity',{'@context':'https://schema.org','@type':'WebPage',datePublished:'2011-01-01',mainEntity:{...scholarly,'@context':undefined}}],
      ['array type',{...scholarly,'@type':['Thing','Article']}],['full URI type',{...scholarly,'@context':undefined,'@type':'https://schema.org/Article'}],
      ['same repeated',[scholarly,scholarly]],
    ])await dates('unique LD '+name,'',['2020-04-02'],ld(value));
    for(const [name,value] of [
      ['no context',{...scholarly,'@context':undefined}],['wrong context',{...scholarly,'@context':'https://other.invalid'}],
      ['multiple',[scholarly,{...scholarly,'@id':'urn:paper:two'}]],['conflicting same id',[scholarly,{...scholarly,dateModified:'2020-04-03'}]],
      ['recommendation',{'@context':'https://schema.org','@type':'WebPage',recommendation:scholarly}],
      ['complex reference',{'@context':'https://schema.org','@type':'WebPage',mainEntity:{'@id':'urn:paper:one'},'@graph':[scholarly]}],
    ])await dates('unqualified LD '+name,'',[],ld(value));
    const broken=await extract(article('<p>2020-05-02</p>','<script type="application/ld+json">{broken</script>'+ld(scholarly)),false);
    assert.deepEqual(broken.metadata.dates,[{value:'2020-04-02',precision:'day'},{value:'2020-05-02',precision:'day'}]);
    assert.deepEqual(broken.extraction_diagnostics,['json_ld_invalid']);
    // Algorithm-only layer deliberately bypasses the host article identity gate.
    const raw=async body=>{page=body;return browser.runTask(signal,{request_id:randomUUID()},async()=>{
      const tab=await browser.newTaskPage({signal,deadline:Date.now()+4000,managed:true});browser.bindTaskPage(tab,signal);
      await browser.navigate(url,{tab,signal,deadline:Date.now()+4000});
      return browser.readDocument(tab,'extract',{signal,args:{wantAbstract:true}});
    });};
    assert.deepEqual((await raw(html('<article><p>2020-01-02</p></article><article><p>2020-02-02</p></article>'))).metadata.dates,
      [{value:'2020-01-02',precision:'day'},{value:'2020-02-02',precision:'day'}],'multiple article algorithm falls back to body');
    await assert.rejects(extract(html('<article><p>2020-01-02</p></article><article><p>2020-02-02</p></article>')),/article_identity_unconfirmed/);
    assert.deepEqual((await raw(html('<h1>Outside</h1><p>2020-01-02</p><article><h1>Inside</h1><p>2020-02-02</p></article>'))).metadata.dates,
      [{value:'2020-01-02',precision:'day'},{value:'2020-02-02',precision:'day'}],'first h1 outside article forces body');
    const summary=async(name,body,expected,meta='')=>{
      const result=await extract(article(body,meta));assert.equal(result.metadata.abstract,expected,name);return result;
    };
    const structured='<h3>Background</h3><p>β &lt; 0.05 and x².</p><h3>Methods</h3><p>We measured H<sub>2</sub>O.</p><h3>Results</h3><p>Clear findings.</p>';
    const structuredText='Background\nβ < 0.05 and x².\nMethods\nWe measured H2O.\nResults\nClear findings.';
    for(const attrs of ['id="ABSTRACT"','id="Abstracts"','class="other abstract"','class="abstract-content"','class="abstractInFull"','aria-label="Abstract"','aria-labelledby="abs-title"'])
      await summary('A1 '+attrs,'<section '+attrs+'><h2 id="abs-title">Abstract</h2>'+structured+'</section>',structuredText);
    await summary('A1 nested duplicate containers','<div class="abstract"><section id="abstract"><h2>Abstract</h2><p>One complete result.</p></section></div>','One complete result.');
    await summary('exact tokens only','<div id="abstract-title">Wrong title.</div><div class="abstract-link">Wrong link.</div><div class="abstractish">Wrong content.</div>',null);
    await summary('explicit unwanted candidates','<section class="abstract"><h2>Graphical Abstract</h2><p>Wrong image summary.</p></section><aside class="recommended-articles"><section id="abstract"><p>Wrong recommendation.</p></section></aside><button class="abstract">Abstract</button>',null);
    await summary('only title and button not abstract','<section id="abstract"><h2>Abstract</h2><button>Download</button></section>',null);
    await summary('peripheral UI removed','<section class="abstract"><h2>Abstract</h2><p>Complete <em>scientific</em> result.</p><button>Download</button><a role="button">Copy</a><ul class="keywords"><li>word</li></ul><figcaption>Figure 1</figcaption></section>','Complete scientific result.');
    await summary('short complete abstract accepted','<div class="abstract">Yes.</div>','Yes.');
    await summary('A2 explicit section','<section><h2>Abstract:</h2>'+structured+'</section><section><h2>Introduction</h2><p>Body.</p></section>',structuredText);
    await summary('A2 sibling bounded','<h2>Abstract</h2><p>First paragraph.</p><h3>Methods</h3><p>Second references ordinary words.</p><h2>Introduction</h2><p>Excluded body.</p>','First paragraph.\nMethods\nSecond references ordinary words.');
    await summary('A2 irregular keywords ends','<h2>Abstract</h2><p>Complete result.</p><h4>Keywords</h4><p>Not abstract.</p><h2>Introduction</h2>','Complete result.');
    await summary('A2 unbounded refuses body','<h2>Abstract</h2><p>No reliable end.</p>',null);
    await summary('A2 bounded Summary','<h2>Summary</h2><p>Current paper summary.</p><h2>Introduction</h2>','Current paper summary.');
    await summary('A2 Summary blocked by Abstract heading','<section><h2>Summary</h2><p>Do not pick this.</p></section><h2>Abstract</h2><button>Download</button>',null);
    await summary('A1 conflicting falls through structured source','<section class="abstract"><p>First different value.</p></section><section class="abstract"><p>Second different value.</p></section>','Meta resolved.','<meta name="citation_abstract" content="Meta resolved.">');
    await summary('equal candidates merge','<section class="abstract"><p>Same value.</p></section><section class="abstract"><p>Same value.</p></section>','Same value.');
    for(const key of ['citation_abstract','dcterms.abstract','dc.description.abstract'])
      await summary('B academic Meta '+key,'','Safe meta.','<meta property="'+key.toUpperCase()+'" content="Safe meta.">');
    await summary('B ordered fields and conflict fallback','','Second field.','<meta name="citation_abstract" content="One."><meta name="citation_abstract" content="Two."><meta name="dcterms.abstract" content="Second field."><meta name="dc.description.abstract" content="Third field.">');
    await summary('weak descriptions excluded','',null,['description','og:description','twitter:description','dc.description'].map(key=>'<meta name="'+key+'" content="Wrong weak description.">').join('')+ld({...scholarly,abstract:undefined,description:'Wrong JSON description.'}));
    await summary('C direct unique LD abstract','','Structured abstract.',ld(scholarly));
    await summary('C safe HTML text','','First paragraph.\nSecond scientific β < 0.05.',ld({...scholarly,abstract:'<p>First paragraph.</p><p>Second scientific β &lt; 0.05.</p>'}));
    await summary('preview falls back without expansion','<section class="abstract"><p>Truncated text…</p><button aria-expanded="false">Read more</button></section>','Full meta text.','<meta name="citation_abstract" content="Full meta text.">');
    await summary('ellipsis-only rejected','<div class="abstract">…</div>',null);
    const skipped=await extract(article('<p>2020-01-02</p><section class="abstract"><p>'+('x'.repeat(65537))+'</p></section>'),false);
    assert.deepEqual(skipped.metadata,{dates:[{value:'2020-01-02',precision:'day'}],abstract:null});assert.deepEqual(skipped.extraction_diagnostics,[],'wantAbstract false never runs candidate budget/scanning');
    const oversized=await summary('large abstract no truncation','<p>2020-01-02</p><section class="abstract"><p>'+('x'.repeat(65537))+'</p></section>',null);
    assert.deepEqual(oversized.metadata.dates,[{value:'2020-01-02',precision:'day'}]);assert.deepEqual(oversized.extraction_diagnostics,['abstract_budget_exceeded']);
    await summary('A2 nested heading wrapper','<section><header><h2>Abstract</h2></header><div><p>Nested first.</p></div><div><h3>Methods</h3><p>Nested second.</p></div><div><h2>Introduction</h2><p>Wrong body.</p></div></section>','Nested first.\nMethods\nNested second.');
    await summary('A2 nested current and ending headings','<section><div><h2>Abstract</h2><p>Valid in same wrapper.</p></div><div><h3>Methods</h3><p>Valid method.</p></div><div><h2>Discussion</h2><p>Wrong body.</p></div></section>','Valid in same wrapper.\nMethods\nValid method.');
    await summary('A1 Keywords heading trims standalone list','<section id="abstract"><p>Complete finding.</p><h3>Keywords</h3><ul><li>Not abstract.</li></ul></section>','Complete finding.');
    await summary('Preview text does not become abstract','<div class="abstract preview"><p>Short preview.</p></div>','Full independent abstract.','<meta name="citation_abstract" content="Full independent abstract.">');
    await summary('duplicate Meta value permitted','','Repeated text.','<meta name="citation_abstract" content=" Repeated   text. "><meta name="citation_abstract" content="Repeated text.">');
    await summary('DOM beats academic Meta','<div class="abstract">DOM full text.</div>','DOM full text.','<meta name="citation_abstract" content="Other full text.">');
    await summary('standalone Keywords paragraph ends A2','<h2>Abstract</h2><p>Complete finding.</p><p>Keywords</p><ul><li>Not abstract.</li></ul><h2>Introduction</h2>','Complete finding.');
    await summary('graphical subsection excluded','<section id="abstract"><p>Complete finding.</p><h3>Graphical Abstract</h3><p>Wrong graphical label.</p></section>','Complete finding.');
    const giant=await extract(article('<div>'+('Unrelated '.repeat(100000))+'</div><p>2020-09-02</p><div class="abstract">One result.</div>'));
    assert.ok(JSON.stringify(giant).length<1500);assert.deepEqual(giant.metadata,{dates:[{value:'2020-09-02',precision:'day'}],abstract:'One result.'});
    // Interleave real DOM changes exactly between native seams; no result is
    // synthesized, and each call still goes through Main and actual cleanup.
    const originalRead=browser.readDocument.bind(browser);
    const changedRead=async(actionToChange,mutate,body=article('<p>2020-05-02</p><div class="abstract">Verified text.</div>'),wantAbstract=true)=>{
      let changed=false;
      browser.readDocument=async(tab,action,options)=>{
        const result=await originalRead(tab,action,options);
        if(action===actionToChange && !changed){changed=true;await mutate(tab,result);}
        return result;
      };
      try{return await extract(body,wantAbstract);}finally{browser.readDocument=originalRead;}
    };
    await assert.rejects(changedRead('article',tab=>tab.view.webContents.executeJavaScript('location.reload()')),/document_changed|page_probe_unconfirmed|load_failed/);
    await assert.rejects(changedRead('extract',tab=>tab.view.webContents.executeJavaScript('document.body.replaceWith(document.body.cloneNode(true))')),/document_changed/);
    await assert.rejects(changedRead('extract',tab=>tab.view.webContents.loadURL(url)),/document_changed/,'same URL replacement is a different Document');
    await assert.rejects(changedRead('extract',async()=>{for(const operation of native.operations.values())operation.controller.abort();}),/canceled/);
    const localFault=await changedRead('article',tab=>tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{code:'Object.defineProperty(Element.prototype,"classList",{get(){throw Error("local fixture fault");}});undefined'}]));
    assert.deepEqual(localFault.metadata,{dates:[{value:'2020-05-02',precision:'day'}],abstract:null});
    assert.deepEqual(localFault.extraction_diagnostics,['abstract_candidate_failed'],'local abstract failure preserves dates');
    const noAbstractFault=await changedRead('article',tab=>tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{code:'Object.defineProperty(Element.prototype,"classList",{get(){throw Error("must not scan");}});undefined'}]),article('<p>2020-05-02</p>'),false);
    assert.deepEqual(noAbstractFault.metadata,{dates:[{value:'2020-05-02',precision:'day'}],abstract:null});
    assert.deepEqual(noAbstractFault.extraction_diagnostics,[],'false avoids even the failing abstract scanner');
    await assert.rejects(changedRead('article',tab=>tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{code:'Document.prototype.querySelectorAll=()=>{throw Error("whole read fixture fault")};undefined'}])),/document_operation_failed/);
    await assert.rejects(changedRead('article',tab=>tab.view.webContents.executeJavaScriptInIsolatedWorld(999,[{code:'Date.now=(()=>{let n=0;return ()=>n++?6000:0;})();undefined'}])),/document_operation_failed/,'whole scan budget exhaustion is not empty success');
    const empty=await extract(article(''),false);assert.deepEqual(empty.metadata,{dates:[],abstract:null});
    const publicPage=browser.createTab({present:false,user:true});await publicPage.view.webContents.loadURL(url);
    await extract(article('<p>2020-01-02</p>'),false);
    assert.equal(browser.tabs.get(publicPage.id),publicPage,'normal cleanup preserves unrelated user page');
    await browser.closePage(publicPage);
    const scoped={service_scope:{scope_id:'b'.repeat(64),config_revision:'c'.repeat(64),user_state_revision:'d'.repeat(64)},service_id:'svc_'+'e'.repeat(32),preparation_key:'f'.repeat(64)};
    let retained;
    page=article('<p>Prepared target</p>');
    await browser.runTask(signal,{...scoped,request_id:randomUUID()},async()=>{
      retained=await browser.newTaskPage({signal,deadline:Date.now()+4000,managed:true});browser.bindTaskPage(retained,signal);
      await browser.navigate(url,{tab:retained,signal,deadline:Date.now()+4000});
      browser.retainAccessPage(retained,scoped);
    });
    const oldExtract=browser.extractPaperMetadata.bind(browser);let sawPin=false;
    browser.extractPaperMetadata=async(payload,options)=>{
      const read=browser.readDocument.bind(browser);
      browser.readDocument=async(...args)=>{
        if(args[1]==='extract')sawPin=retained.resourceOwner.pins.has(browser.operation);
        return read(...args);
      };
      try{return await oldExtract(payload,options);}finally{browser.readDocument=originalRead;}
    };
    const invokeScoped=async fields=>{
      const id=randomUUID();page=article('<p>2020-01-02</p>');
      await native.execute({id,action:'extract_paper_metadata',data:{...data,...scoped,target_page_id:retained.id,...fields,deadline_ms:Date.now()+4000}});
      return nativeMessages.find(message=>message.type==='result' && message.id===id).data;
    };
    assert.equal((await invokeScoped({})).outcome,'retrieved');assert.equal(sawPin,true,'retained preparation is pinned while separate work page reads');
    assert.equal(browser.tabs.get(retained.id),retained);assert.equal(retained.resourceOwner.pins.size,0,'pin releases only after work-page cleanup');
    assert.equal((await invokeScoped({preparation_key:'0'.repeat(64)})).diagnostic.code,'document_changed');
    browser.extractPaperMetadata=oldExtract;
    await browser.closePage(retained);
    if(process.argv[3])fs.writeFileSync(process.argv[3],JSON.stringify(actual));
    console.log('DOCUMENT EXTRACTION PASS');
  }finally {await browser.close();host.destroy();await new Promise(resolve=>server.close(resolve));}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
