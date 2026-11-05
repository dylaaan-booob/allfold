'use strict';
const {app,session}=require('electron');
const assert=require('node:assert/strict'),http=require('node:http'),fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {requestSessionHTTP}=require('../src/zotero/session-http.cjs');
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'allfold-referrer-profile-'));
app.setPath('userData',profile);
const servers=[];
async function listen(handler) {
 const server=http.createServer(handler);servers.push(server);
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 return `http://127.0.0.1:${server.address().port}`;
}
app.whenReady().then(async()=>{
 const received=[];
 const record=(request,response)=>{received.push({url:request.url,headers:request.headers});response.end('%PDF-1.7\nfixture');};
 const other=await listen(record);
 const source=await listen((request,response)=>{
  if(request.url==='/redirect') {
   received.push({url:request.url,headers:request.headers});
   response.writeHead(302,{Location:other+'/redirected'});response.end();
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
 console.log('SESSION HTTP REFERRER PASS');
}).then(async()=>{await Promise.all(servers.map(server=>new Promise(resolve=>server.close(resolve))));app.quit();})
 .catch(error=>{console.error(error);app.exit(1);});
app.on('will-quit',()=>fs.rmSync(profile,{recursive:true,force:true}));
