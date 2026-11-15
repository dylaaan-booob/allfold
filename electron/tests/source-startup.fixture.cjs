'use strict';
// Opt-in smoke of the actual Main entry, including its Python bootstrap and quit.
// Run only in a disposable source copy; profile/config must be explicitly supplied.
const {app,webContents}=require('electron');
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),http=require('node:http');
const root=path.resolve(__dirname,'../..'),profile=fs.realpathSync(process.argv[2]);
const configFlag=process.argv.indexOf('--config'),config=process.argv[configFlag+1];
assert.ok(configFlag>2 && path.isAbsolute(config),'Pass an absolute --config');
assert.ok(fs.realpathSync(config).startsWith(root+path.sep),'Configuration must belong to this source copy');
assert.ok(profile.startsWith(root+path.sep),'Profile must belong to this source copy');
app.setPath('userData',profile);app.setPath('sessionData',profile);app.setAppLogsPath(path.join(profile,'logs'));
process.env.ALLFOLD_DIAGNOSTICS_ROOT=path.join(profile,'diagnostics');
const errors=[];
let checked=false,failed=false,server,serverClosed;
function closeServer() {
  serverClosed ??= server?new Promise(resolve=>server.close(resolve)):Promise.resolve();
  return serverClosed;
}
function fail(error) {
  if(failed)return;
  failed=true;console.error(error);clearTimeout(deadline);
  // Main must drain/receive Python's terminal before will-quit sets failure status.
  void closeServer().then(()=>app.quit());
}
const startupTimedOut=()=>fail(Error('SOURCE STARTUP TIMEOUT'));
const deadline=setTimeout(startupTimedOut,45000);
async function until(read,accept) {
  for(let i=0;i<200;i++) {
    const value=await read();if(accept(value))return value;
    await new Promise(resolve=>setTimeout(resolve,50));
  }
  throw Error('Startup observation did not settle');
}
app.on('web-contents-created',(_event,contents)=>{
  contents.on('console-message',details=>{if(details.level==='error')errors.push(details.message);});
});
app.on('browser-window-created',(_event,window)=>{
  window.webContents.once('did-finish-load',()=>{void (async()=>{
    assert.equal(window.webContents.getURL(),'http://127.0.0.1:18767/');
    const health=await (await fetch('http://127.0.0.1:18767/api/electron/health')).json();
    assert.deepEqual(health,{runtime:'electron',connected:true});
    // Fixture-only fault injection verifies both failure exits after Python starts.
    if(process.argv.includes('--fail-after-ready'))throw Error('Intentional WF11 startup failure');
    if(process.argv.includes('--timeout-after-ready')){
      clearTimeout(deadline);setTimeout(startupTimedOut,0);return;
    }
    const evaluate=source=>window.webContents.executeJavaScript(source);
    await until(()=>evaluate('Boolean(window.allfoldWorkbench && window.allfoldDesktop && document.querySelector("#array-index"))'),Boolean);
    await evaluate('document.fonts.ready.then(()=>true)');
    const workspace=await evaluate('fetch("/api/ui-next/workspace").then(r=>{if(!r.ok)throw Error(r.status);return r.json();})');
    assert.equal(workspace.initialized,false);
    assert.deepEqual(workspace.counts,{candidates:0,downloaded:0,trash:0,active_journals:0});
    const state=await evaluate('window.allfoldDesktop.browserState()');
    assert.equal(state.tabs.length,0);
    server=http.createServer((_request,response)=>{response.writeHead(200,{'content-type':'text/html'});response.end('<!doctype html><title>WF11 isolated Browser</title><h1>Local page</h1>');});
    await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
    const url='http://127.0.0.1:'+server.address().port+'/article';
    const created=await evaluate('window.allfoldDesktop.browserCommand({action:"new"})');
    assert.equal(created.tabs.length,1);
    const id=created.selected;
    await evaluate(`window.allfoldDesktop.browserCommand(${JSON.stringify({action:'navigate',id,url})})`);
    const page=webContents.getAllWebContents().find(contents=>contents.getURL()===url);
    assert.ok(page,'The real BrowserRuntime must navigate its native page');
    assert.equal(await page.executeJavaScript('document.querySelector("h1").textContent'),'Local page');
    await evaluate(`window.allfoldDesktop.browserCommand(${JSON.stringify({action:'close',id})})`);
    await until(()=>evaluate('window.allfoldDesktop.browserState()'),value=>value.tabs.length===0);
    assert.equal(page.isDestroyed(),true);
    assert.equal((await evaluate('fetch("/api/ui-next/workspace").then(r=>r.json())')).initialized,false);
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(profile,'main.png'),(await window.webContents.capturePage()).toPNG());
    await closeServer();
    checked=true;app.quit();
  })().catch(fail);});
});
app.on('will-quit',event=>{
  clearTimeout(deadline);
  if(failed || !checked){
    event.preventDefault();
    void closeServer().then(()=>app.exit(1));
    return;
  }
  assert.ok(!server.listening);
  console.log('SOURCE STARTUP PASS: Main → Python health → authenticated bridge → built UI → BrowserRuntime → normal quit');
});
require('../src/main.cjs');
