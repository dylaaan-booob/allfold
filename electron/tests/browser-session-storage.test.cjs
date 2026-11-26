'use strict';
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const http=require('node:http'),readline=require('node:readline');
const runFixture=require('./fixture-process.cjs');

function storagePath(stdout) {
  const directory=stdout.match(/^BROWSER SESSION (.+)$/m)?.[1];
  assert.ok(directory);
  return directory;
}

test('Browser shares site state during the run and reclaims only retired Session directories',{timeout:35000},async t=>{
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
  const launch=(mode,...retired)=>runFixture(t,require('electron'),
    [path.join(__dirname,'browser-session-storage.fixture.cjs'),profile,origin,mode,...retired],
    {env:{...process.env,ELECTRON_RUN_AS_NODE:''}});

  const held=launch('hold'),lines=readline.createInterface({input:held.child.stdout});
  const stopped=held.then(()=>null,error=>error);
  let active,normal;
  try {
    for await(const line of lines)if(line.startsWith('BROWSER SESSION ')){active=storagePath(line);break;}
    if(!active)throw Error((await stopped)?.stderr || 'Session writer did not start');
    const unrelated=path.join(path.dirname(active),'other-data');
    fs.mkdirSync(unrelated);fs.writeFileSync(path.join(unrelated,'keep'),'keep');
    fs.symlinkSync(unrelated,path.join(active,'external-data'),'dir');
    normal=storagePath((await launch('check')).stdout);
    assert.notEqual(normal,active);
    assert.ok(fs.statSync(active).isDirectory(),'an active process retains its Session directory');
  }finally {
    held.child.stdin.end();
    await held;
  }
  const next=storagePath((await launch('check',active,normal)).stdout);
  assert.notEqual(next,normal);
  assert.equal(fs.readFileSync(path.join(path.dirname(active),'other-data','keep'),'utf8'),'keep');
  assert.ok(fs.statSync(next).isDirectory());
});
