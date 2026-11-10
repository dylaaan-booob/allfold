'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs/promises'),path=require('node:path');
const {execFile}=require('node:child_process'),{promisify}=require('node:util');
const assert=require('node:assert/strict');
const {BrowserRuntime}=require('../src/browser/browser-runtime.cjs');
const {PROJECT_ROOT}=require('../src/shared/paths.cjs');
const profile=process.argv[2];
app.setPath('userData',profile);app.setPath('sessionData',profile);
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
app.commandLine.appendSwitch('remote-debugging-port','0');

app.whenReady().then(async()=>{
  const host=new BrowserWindow({show:false,width:800,height:600});
  const browser=new BrowserRuntime({hostWindow:host});
  try {
    await browser.ready;
    const frameURL='https://challenges.cloudflare.com/fixture';
    const pages=['https://fixture.invalid/challenge','https://challenges.cloudflare.com/challenge'];
    browser.partition.protocol.handle('https',request=>{
      const html=pages.includes(request.url)
        ?`<!doctype html><iframe width="400" height="240" src="${frameURL}"></iframe>`
        :request.url===frameURL?'<input type="checkbox" style="width:60px;height:60px">':'';
      return new Response(html,{status:html?200:404,headers:{'Content-Type':'text/html'}});
    });
    const tabs=[browser.createTab({present:false}),browser.createTab({present:false})];
    const [port,browserPath]=(await fs.readFile(path.join(profile,'DevToolsActivePort'),'utf8')).trim().split(/\r?\n/);
    const python=process.env.ALLFOLD_SOLVER_TEST_PYTHON || path.join(PROJECT_ROOT,'.venv','bin','python');
    const script=[
      'import json,sys',
      'from threading import Event,Timer',
      'from allfold.integrations.cloudflare_solver import solve_cloudflare',
      'stop=Event()',
      'timer=Timer(5,stop.set)',
      'timer.start()',
      'try: print(json.dumps(solve_cloudflare(sys.argv[1],sys.argv[2],stop,target_id=sys.argv[3])))',
      'finally: timer.cancel()',
    ].join('\n');
    for(const page of pages) {
      await Promise.all(tabs.map(tab=>tab.view.webContents.loadURL(page)));
      const target=tabs[1].view.webContents.getOrCreateDevToolsTargetId();
      const {stdout}=await promisify(execFile)(python,['-c',script,'ws://127.0.0.1:'+port+browserPath,page,target],
        {timeout:6500,env:{...process.env,PYTHONPATH:path.join(PROJECT_ROOT,'src')}});
      assert.deepEqual(JSON.parse(stdout),{outcome:'clicked',reason:'checkbox_clicked'});
      const checked=await Promise.all(tabs.map(tab=>{
        const frame=tab.view.webContents.mainFrame.framesInSubtree.find(item=>item.url===frameURL);
        return frame.executeJavaScript('document.querySelector("input").checked');
      }));
      assert.deepEqual(checked,[false,true]);
    }
    console.log('CLOUDFLARE TARGET ISOLATION PASS');
  } finally {browser.close();host.destroy();}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
