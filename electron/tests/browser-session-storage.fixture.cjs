'use strict';
const {app}=require('electron');
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');

const [profile,origin,mode]=process.argv.slice(2);
app.setPath('userData',profile);
app.setPath('sessionData',profile);

app.whenReady().then(async()=>{
  const browser=new BrowserRuntime();
  const check=async expected=>{
    const tab=await browser.openURL(origin+'/read');
    assert.deepEqual(await tab.view.webContents.executeJavaScript(
      '[document.querySelector("p").textContent,localStorage.getItem("allfold-fixture")]'),expected);
    return tab;
  };
  if(mode==='seed')await browser.openURL(origin+'/seed');
  const tab=await check(mode==='empty'?['no cookie',null]:['cookie received','seed']);
  const contents=tab.view.webContents,partition=contents.session;
  assert.ok(partition.storagePath);
  if(mode==='reset') {
    const keep=path.join(profile,'workspace','paper.pdf');
    await fs.mkdir(path.dirname(keep));
    await fs.writeFile(keep,'fixture paper');
    assert.equal((await browser.resetSession()).ok,true);
    assert.equal(browser.tabs.size,0);
    assert.equal(contents.isDestroyed(),true);
    assert.equal(await fs.readFile(keep,'utf8'),'fixture paper');
    await check(['no cookie',null]);
  }
  console.log('BROWSER SESSION '+partition.storagePath);
  await browser.close();
  app.quit();
}).catch(error=>{console.error(error);app.exit(1);});
