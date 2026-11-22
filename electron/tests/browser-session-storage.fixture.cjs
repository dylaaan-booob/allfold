'use strict';
const {app}=require('electron');
const assert=require('node:assert/strict');
const {access}=require('node:fs/promises');
const {setTimeout:delay}=require('node:timers/promises');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');

const [profile,origin,mode,...retired]=process.argv.slice(2);
app.setPath('userData',profile);
app.setPath('sessionData',profile);

app.whenReady().then(async()=>{
  const browser=new BrowserRuntime();
  const seed=mode==='hold';
  if(seed)await browser.openURL(origin+'/seed');
  const tab=await browser.openURL(origin+'/read');
  const contents=tab.view.webContents;
  assert.deepEqual(await contents.executeJavaScript(
    '[document.querySelector("p").textContent,localStorage.getItem("allfold-fixture")]'),
  seed?['cookie received','seed']:['no cookie',null]);
  const partition=contents.session;
  assert.ok(partition.storagePath,'Browser pages use a disk Session');
  await partition.cookies.flushStore();
  partition.flushStorageData();
  for(const directory of retired) {
    for(let i=0;i<100;i++) {
      if(!await access(directory).then(()=>true,error=>error.code!=='ENOENT'))break;
      await delay(50);
    }
    await assert.rejects(access(directory),{code:'ENOENT'});
  }
  console.log('BROWSER SESSION '+partition.storagePath);
  if(seed) {
    // Leave the normal BrowserRuntime drain uncalled, as on an interrupted run.
    process.stdin.resume();
    process.stdin.once('end',()=>app.exit(0));
    return;
  }
  await browser.close();
  app.quit();
}).catch(error=>{console.error(error);app.exit(1);});
