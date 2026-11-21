'use strict';
const {app,BrowserWindow,session}=require('electron');
const https=require('node:https'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const {readPartitionCookies}=require('../src/browser/request-cookies.cjs');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
app.setPath('userData',process.argv[2]);app.setPath('sessionData',process.argv[2]);
app.commandLine.appendSwitch('no-proxy-server');
app.commandLine.appendSwitch('host-resolver-rules','MAP *.publisher.example 127.0.0.1');
app.whenReady().then(async()=>{
  const requests=[];
  const fixture=path.join(__dirname,'../../tests/fixtures/http');
  const server=https.createServer({cert:fs.readFileSync(path.join(fixture,'localhost-cert.pem')),
    key:fs.readFileSync(path.join(fixture,'localhost-key.pem'))},(req,res)=>{
    if(req.url==='/article') {
      res.setHeader('Set-Cookie',[
        '__Host-partition=correct; Secure; HttpOnly; SameSite=None; Path=/; Partitioned',
        'path_partition=path-value; Secure; HttpOnly; SameSite=None; Path=/pdf; Partitioned',
        'regular=kept; Secure; HttpOnly; SameSite=None; Path=/',
        'sid=pdf; Secure; HttpOnly; SameSite=None; Path=/pdf',
        'sid=root; Secure; HttpOnly; SameSite=None; Path=/; Partitioned',
        'inverse=root; Secure; HttpOnly; SameSite=None; Path=/',
        'inverse=pdf; Secure; HttpOnly; SameSite=None; Path=/pdf; Partitioned',
      ]);
      res.setHeader('Content-Type','text/html');res.end('<title>Isolated source</title>');return;
    }
    requests.push({url:req.url,cookie:req.headers.cookie || '',referer:req.headers.referer,origin:req.headers.origin,
      site:req.headers['sec-fetch-site']});
    if(req.url==='/pdf/redirect-path'){res.writeHead(302,{location:'/outside'});res.end();return;}
    if(req.url==='/pdf/redirect-host'){res.writeHead(302,{location:base.replace('127.0.0.1','localhost')+'/outside'});res.end();return;}
    res.statusCode=req.headers.cookie?.includes('__Host-partition=correct')?200:403;
    res.setHeader('Content-Type','application/pdf');res.end('%PDF-isolated');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`https://127.0.0.1:${server.address().port}`,partition=session.fromPartition('cookie-fixture');
  partition.setCertificateVerifyProc((request,done)=>done(
    ['127.0.0.1','localhost','article.publisher.example','cdn.publisher.example'].includes(request.hostname)?0:-2));
  const win=new BrowserWindow({show:false,webPreferences:{session:partition,nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await win.webContents.loadURL(base+'/article');
  const contents=win.webContents,tab={id:contents.id,view:{webContents:contents}};
  contents.debugger.attach('1.3');
  await contents.debugger.sendCommand('Network.setCookie',{url:base+'/',name:'__Host-partition',value:'wrong-partition',
    path:'/',secure:true,httpOnly:true,sameSite:'None',partitionKey:{topLevelSite:'https://localhost',hasCrossSiteAncestor:false}});
  const other=base.replace('127.0.0.1','localhost');
  for(const sameSite of ['Strict','Lax','None'])for(const ancestor of [false,true]) {
    const set=await contents.debugger.sendCommand('Network.setCookie',{url:other+'/pdf',name:'cross_'+sameSite+'_'+ancestor,
      value:'isolated',path:'/',secure:true,httpOnly:true,sameSite,
      partitionKey:{topLevelSite:'https://127.0.0.1',hasCrossSiteAncestor:ancestor}});
    assert.equal(set.success,true);
  }
  assert.equal((await contents.debugger.sendCommand('Network.setCookie',{url:other+'/pdf/private',name:'sid',value:'base',
    path:'/',secure:true,httpOnly:true,sameSite:'None'})).success,true);
  for(const ancestor of [false,true])for(const [value,path,sameSite] of [
    ['base','/pdf/private','Strict'],['auth','/pdf','None']]) {
    assert.equal((await contents.debugger.sendCommand('Network.setCookie',{url:other+'/pdf/private',name:'sid',value,
      path,secure:true,httpOnly:true,sameSite,partitionKey:{topLevelSite:'https://127.0.0.1',hasCrossSiteAncestor:ancestor}})).success,true);
  }
  const inclusive=await contents.debugger.sendCommand('Network.getCookies',{urls:[other+'/pdf']});
  assert.ok(inclusive.cookies.some(cookie=>cookie.sameSite==='Strict'),'CDP reads Strict cookies even in this cross-site context');
  contents.debugger.detach();
  const cookies=await readPartitionCookies({partition,tabs:new Map([[tab.id,tab]])},base+'/pdf',base+'/article',{validate:()=>{}});
  assert.deepEqual(cookies.cookies.map(c=>c.name).sort(),['__Host-partition','inverse','path_partition','sid']);
  assert.equal(cookies.cookies.some(c=>c.value==='wrong-partition'),false);
  const cross=await readPartitionCookies({partition,tabs:new Map([[tab.id,tab]])},other+'/pdf',base+'/article',{validate:()=>{}});
  assert.ok(cross.cookies.length>0);
  await contents.executeJavaScript('fetch('+JSON.stringify(other+'/pdf?browser-samesite')+',{credentials:"include",mode:"no-cors"}).then(()=>true)');
  assert.match(requests.at(-1).cookie,/cross_None_/);assert.doesNotMatch(requests.at(-1).cookie,/cross_(Strict|Lax)_/);
  const events=sharedSessionEvents(partition),context={owner:{workflow_id:'fixture'},attemptId:'fixture',deadline:Date.now()+5000,partitionCookies:cookies};
  const plain=await events.fetch(base+'/pdf',{credentials:'include'}, {...context,partitionCookies:undefined});
  assert.equal(plain.response.status,403);await plain.response.text();
  const scoped=await events.fetch(base+'/pdf',{credentials:'include'},context);
  assert.equal(scoped.response.status,200);assert.equal(await scoped.response.text(),'%PDF-isolated');
  assert.match(requests.at(-1).cookie,/regular=kept/);assert.match(requests.at(-1).cookie,/path_partition=path-value/);
  assert.ok(requests.at(-1).cookie.indexOf('sid=pdf')<requests.at(-1).cookie.indexOf('sid=root'),
    'An ordinary longer-path cookie must precede a partitioned root cookie');
  assert.ok(requests.at(-1).cookie.indexOf('inverse=pdf')<requests.at(-1).cookie.indexOf('inverse=root'),
    'A partitioned longer-path cookie must precede an ordinary root cookie');
  assert.doesNotMatch(requests.at(-1).cookie,/wrong-partition/);
  const otherPath=await events.fetch(base+'/outside',{credentials:'include'},context);await otherPath.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/path_partition=/);
  const pathRedirect=await events.fetch(base+'/pdf/redirect-path',{credentials:'include'},context);await pathRedirect.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/path_partition=/);
  const hostRedirect=await events.fetch(base+'/pdf/redirect-host',{credentials:'include'},context);await hostRedirect.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/partition=/);
  const otherHost=await events.fetch(base.replace('127.0.0.1','localhost')+'/pdf',{credentials:'include'},context);await otherHost.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/partition=/);
  const crossRequest=await events.fetch(other+'/pdf',{credentials:'include'},{...context,partitionCookies:cross});await crossRequest.response.text();
  assert.match(requests.at(-1).cookie,/cross_None_/);assert.doesNotMatch(requests.at(-1).cookie,/cross_(Strict|Lax)_/);
  const overlap=await readPartitionCookies({partition,tabs:new Map([[tab.id,tab]])},other+'/pdf/private',base+'/article',{validate:()=>{}});
  const overlapRequest=await events.fetch(other+'/pdf/private',{credentials:'include'},{...context,partitionCookies:overlap});await overlapRequest.response.text();
  assert.ok(requests.at(-1).cookie.indexOf('sid=auth')<requests.at(-1).cookie.indexOf('sid=base'),
    'A filtered Strict partition must not inflate the ordinary cookie path rank');
  const article=base.replace('127.0.0.1','article.publisher.example'),cdn=base.replace('127.0.0.1','cdn.publisher.example');
  await contents.loadURL(article+'/article');
  contents.debugger.attach('1.3');
  for(const [site,value] of [['https://publisher.example','correct-site'],['https://other.example','foreign-site']])
    assert.equal((await contents.debugger.sendCommand('Network.setCookie',{url:cdn+'/pdf',name:'licensed',value,
      path:'/',secure:true,httpOnly:true,sameSite:'Strict',partitionKey:{topLevelSite:site,hasCrossSiteAncestor:false}})).success,true);
  contents.debugger.detach();
  await contents.executeJavaScript('history.pushState(null,"","/new-article?x=1#part")');
  const sameSite=await readPartitionCookies({partition,tabs:new Map([[tab.id,tab]])},cdn+'/pdf',null,{page:tab});
  const scopedSibling=await events.fetch(cdn+'/pdf',{credentials:'include',referrerPolicy:'no-referrer'},
    {...context,partitionCookies:sameSite});await scopedSibling.response.text();
  assert.equal(requests.at(-1).site,'same-site');
  assert.match(requests.at(-1).cookie,/licensed=correct-site/);assert.doesNotMatch(requests.at(-1).cookie,/foreign-site/);
  assert.equal(requests.at(-1).referer,undefined);assert.equal(requests.at(-1).origin,undefined);
  events.dispose();win.destroy();await new Promise(resolve=>server.close(resolve));
  console.log('PARTITION COOKIE PASS');app.quit();
}).catch(error=>{console.error(error.stack);app.exit(1);});
