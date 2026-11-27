'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const http=require('node:http');
const runFixture=require('./fixture-process.cjs');

function storagePath(stdout) {
  const directory=stdout.match(/^BROWSER SESSION (.+)$/m)?.[1];
  assert.ok(directory);
  return directory;
}

test('Browser reopens its persistent Session, then resets storage without touching business files',{timeout:35000},async t=>{
  const profile=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'allfold-session-storage-')));
  t.after(()=>fs.rmSync(profile,{recursive:true,force:true}));
  const server=http.createServer((request,response)=>{
    const seed=request.url==='/seed';
    response.writeHead(200,{'content-type':'text/html','cache-control':'no-store',
      ...(seed && {'set-cookie':'run-state=seed; Max-Age=3600; Path=/'})});
    response.end('<p>'+(request.headers.cookie==='run-state=seed'?'cookie received':'no cookie')+'</p>'
      +(seed?'<script>localStorage.setItem("allfold-fixture","seed")</script>':''));
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  t.after(()=>{server.closeAllConnections();server.close();});
  const origin='http://127.0.0.1:'+server.address().port;
  const launch=mode=>runFixture(t,require('electron'),
    [path.join(__dirname,'browser-session-storage.fixture.cjs'),profile,origin,mode],
    {env:{...process.env,ELECTRON_RUN_AS_NODE:''}});

  const initial=storagePath((await launch('seed')).stdout);
  assert.equal(path.dirname(initial),profile);
  assert.equal(storagePath((await launch('reset')).stdout),initial);
  assert.equal(storagePath((await launch('empty')).stdout),initial);
});
