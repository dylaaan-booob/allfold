'use strict';
const {app,session}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),net=require('node:net');
const {requestSessionHTTP}=require('../src/zotero/session-http.cjs');
const profile=process.argv[2];
if(!profile)throw Error('Referrer fixture requires a parent-owned profile');
app.setPath('userData',profile);
const servers=[];
async function listen(handler) {
 const server=http.createServer(handler);servers.push(server);
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 return `http://127.0.0.1:${server.address().port}`;
}
async function closeServers() {
 await Promise.all(servers.map(server=>new Promise(resolve=>{
  server.close(resolve);
  server.closeAllConnections();
 })));
}
app.whenReady().then(async()=>{
 const received=[];
 const record=(request,response)=>{received.push({url:request.url,headers:request.headers});response.end('%PDF-1.7\nfixture');};
 const other=await listen(record);
 const source=await listen((request,response)=>{
  if(request.url==='/redirect') {
   received.push({url:request.url,headers:request.headers});
   response.writeHead(302,{Location:other+'/redirected'});response.end();
  }else if(request.url==='/loop') {response.writeHead(302,{Location:'/loop'});response.end();}
  else if(request.url==='/pending-cleanup') {response.write('incomplete body');}
  else if(request.url.startsWith('/chain/') && Number(request.url.slice(7))<10) {
   response.writeHead(302,{Location:'/chain/'+(Number(request.url.slice(7))+1)});response.end();
  }else record(request,response);
 });
 const referrer=source+'/paper?institution=fixture&signature=private';
 const partition=session.fromPartition('allfold-referrer-fixture');
 const get=(url,extra={})=>requestSessionHTTP(partition,{method:'GET',url,referrer,referrerPolicy:'origin-when-cross-origin',timeout:5000,...extra});
 await get(source+'/same');
 await get(other+'/cross');
 await get(source+'/redirect');
 await get(other+'/openalex',{referrer:undefined});
 await get(other+'/translator-default',{referrerPolicy:undefined});
 assert.deepEqual(received.map(value=>[value.url,value.headers.referer]),[
  ['/same',referrer],['/cross',source+'/'],['/redirect',referrer],['/redirected',source+'/'],
  ['/openalex',undefined],['/translator-default',referrer],
 ]);
 assert.ok(received.every(value=>value.headers['zotero-api-key']===undefined));
 assert.equal((await get(source+'/chain/0')).status,200);
 await assert.rejects(get(source+'/loop'),error=>error.net_error==='ERR_TOO_MANY_REDIRECTS');
 // A still-open client must not hold the test's servers or Electron process open.
 const pendingClient=net.connect(new URL(source).port,'127.0.0.1');
 pendingClient.on('error',()=>{});
 await new Promise(resolve=>pendingClient.once('connect',resolve));
 const bodyStarted=new Promise(resolve=>pendingClient.once('data',resolve));
 pendingClient.write('GET /pending-cleanup HTTP/1.1\r\nHost: fixture\r\n\r\n');
 await bodyStarted;
}).then(async()=>{await closeServers();console.log('SESSION HTTP REFERRER PASS');app.quit();})
 .catch(async error=>{console.error(error);await closeServers();app.exit(1);});
