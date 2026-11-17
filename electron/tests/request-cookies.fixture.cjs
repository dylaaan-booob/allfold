'use strict';
const {app,BrowserWindow,session}=require('electron');
const http=require('node:http'),assert=require('node:assert/strict');
const {readPartitionCookies}=require('../src/browser/request-cookies.cjs');
const {sharedSessionEvents}=require('../src/browser/session-events.cjs');
app.setPath('userData',process.argv[2]);app.setPath('sessionData',process.argv[2]);
app.whenReady().then(async()=>{
  const requests=[];
  const server=http.createServer((req,res)=>{
    if(req.url==='/article') {
      res.setHeader('Set-Cookie',[
        '__Host-partition=correct; Secure; HttpOnly; SameSite=None; Path=/; Partitioned',
        'path_partition=path-value; Secure; HttpOnly; SameSite=None; Path=/pdf; Partitioned',
        'regular=kept; Secure; HttpOnly; SameSite=None; Path=/',
      ]);
      res.setHeader('Content-Type','text/html');res.end('<title>Isolated source</title>');return;
    }
    requests.push({url:req.url,cookie:req.headers.cookie || ''});
    if(req.url==='/pdf/redirect-path'){res.writeHead(302,{location:'/outside'});res.end();return;}
    if(req.url==='/pdf/redirect-host'){res.writeHead(302,{location:base.replace('127.0.0.1','localhost')+'/outside'});res.end();return;}
    res.statusCode=req.headers.cookie?.includes('__Host-partition=correct')?200:403;
    res.setHeader('Content-Type','application/pdf');res.end('%PDF-isolated');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}`,partition=session.fromPartition('cookie-fixture');
  const win=new BrowserWindow({show:false,webPreferences:{session:partition,nodeIntegration:false,contextIsolation:true,sandbox:true}});
  await win.webContents.loadURL(base+'/article');
  const contents=win.webContents,tab={id:contents.id,view:{webContents:contents}};
  contents.debugger.attach('1.3');
  await contents.debugger.sendCommand('Network.setCookie',{url:base+'/',name:'__Host-partition',value:'wrong-partition',
    path:'/',secure:true,httpOnly:true,sameSite:'None',partitionKey:{topLevelSite:'http://localhost',hasCrossSiteAncestor:false}});
  contents.debugger.detach();
  const cookies=await readPartitionCookies({partition,tabs:new Map([[tab.id,tab]])},base+'/pdf',base+'/article',{validate:()=>{}});
  assert.deepEqual(cookies.map(c=>c.name).sort(),['__Host-partition','path_partition']);
  assert.equal(cookies.some(c=>c.value==='wrong-partition'),false);
  const events=sharedSessionEvents(partition),context={owner:{workflow_id:'fixture'},attemptId:'fixture',deadline:Date.now()+5000,partitionCookies:cookies};
  const plain=await events.fetch(base+'/pdf',{credentials:'include'}, {...context,partitionCookies:undefined});
  assert.equal(plain.response.status,403);await plain.response.text();
  const scoped=await events.fetch(base+'/pdf',{credentials:'include'},context);
  assert.equal(scoped.response.status,200);assert.equal(await scoped.response.text(),'%PDF-isolated');
  assert.match(requests.at(-1).cookie,/regular=kept/);assert.match(requests.at(-1).cookie,/path_partition=path-value/);
  assert.doesNotMatch(requests.at(-1).cookie,/wrong-partition/);
  const otherPath=await events.fetch(base+'/outside',{credentials:'include'},context);await otherPath.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/path_partition=/);
  const pathRedirect=await events.fetch(base+'/pdf/redirect-path',{credentials:'include'},context);await pathRedirect.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/path_partition=/);
  const hostRedirect=await events.fetch(base+'/pdf/redirect-host',{credentials:'include'},context);await hostRedirect.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/partition=/);
  const otherHost=await events.fetch(base.replace('127.0.0.1','localhost')+'/pdf',{credentials:'include'},context);await otherHost.response.text();
  assert.doesNotMatch(requests.at(-1).cookie,/partition=/);
  events.dispose();win.destroy();await new Promise(resolve=>server.close(resolve));
  console.log('PARTITION COOKIE PASS');app.quit();
}).catch(error=>{console.error(error.stack);app.exit(1);});
