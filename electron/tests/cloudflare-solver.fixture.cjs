'use strict';
const {app,BrowserWindow}=require('electron');
const fs=require('node:fs/promises'),path=require('node:path');
const {execFile,spawn}=require('node:child_process'),{promisify}=require('node:util');
const assert=require('node:assert/strict');
const {createCloudflareSolver}=require('../src/browser/cloudflare-dispatch.cjs');
const {createInterface}=require('node:readline');
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
    let integrated=false;
    browser.partition.protocol.handle('https',request=>{
      const html=pages.includes(request.url.split("#",1)[0])
        ?`<!doctype html>${integrated?'<meta name="citation_doi" content="10.5555/fixture"><script>window._cf_chl_opt = {};</script><script src="/cdn-cgi/challenge-platform/h/g/orchestrate/chl_page/v1"></script>':''}<iframe width="400" height="240" src="${frameURL}"></iframe>`
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
      const pageURL=page+'#verification';
      await Promise.all(tabs.map(tab=>tab.view.webContents.loadURL(pageURL)));
      const target=tabs[1].view.webContents.getOrCreateDevToolsTargetId();
      const {stdout}=await promisify(execFile)(python,['-c',script,'ws://127.0.0.1:'+port+browserPath,pageURL,target],
        {timeout:6500,env:{...process.env,PYTHONPATH:path.join(PROJECT_ROOT,'src')}});
      assert.deepEqual(JSON.parse(stdout),{outcome:'clicked',reason:'checkbox_clicked'});
      const checked=await Promise.all(tabs.map(tab=>{
        const frame=tab.view.webContents.mainFrame.framesInSubtree.find(item=>item.url===frameURL);
        return frame.executeJavaScript('document.querySelector("input").checked');
      }));
      assert.deepEqual(checked,[false,true]);
    }
    // The real probe -> production Main dispatch -> Bridge -> Pydoll/CDP -> probe chain.
    integrated=true;
    await tabs[0].view.webContents.loadURL(pages[0]);
    const operations=new Map(),replies=[];
    const worker=spawn(python,[path.join(PROJECT_ROOT,'tests/electron_solver_bridge_fixture.py'),'ws://127.0.0.1:'+port+browserPath],
      {env:{...process.env,PYTHONPATH:path.join(PROJECT_ROOT,'src')},stdio:['pipe','pipe','pipe']});
    const lines=createInterface({input:worker.stdout});let stderr='';worker.stderr.on('data',data=>{stderr+=data;});
    const send=message=>worker.stdin.write(JSON.stringify(message)+'\n');
    browser.solveCloudflare=createCloudflareSolver({getBrowser:()=>browser,operations,send,isBridgeReady:()=>true});
    let finished,failed;
    const completion=new Promise((yes,no)=>{finished=yes;failed=no;});
    lines.on('line',line=>{
      const message=JSON.parse(line);
      if(message.type==='execute') {
        const controller=new AbortController(),current={id:message.id,action:message.action,controller,challenges:new Map()};
        operations.set(current.id,current);
        void browser.runTask(controller.signal,{request_id:current.id},async()=>{
          const tab=tabs[1];browser.bindTaskPage(tab,controller.signal);
          await tab.view.webContents.loadURL(pages[0]);
          browser.beginPageLoad(tab,controller.signal,Date.now()+6000);
          const doc=await browser.waitForPage(tab,{signal:controller.signal,deadline:Date.now()+6000});
          assert.equal(replies.length,1);assert.equal(replies[0].outcome,'clicked');
          const article=await browser.confirmArticlePage({doi:'10.5555/fixture'},doc,{signal:controller.signal,deadline:Date.now()+1000});
          assert.equal(article.identity.outcome,'confirmed');
          assert.equal(await tabs[0].view.webContents.mainFrame.framesInSubtree.find(frame=>frame.url===frameURL)
            .executeJavaScript('document.querySelector("input").checked'),false);
          send({type:'result',id:current.id,action:current.action,data:{outcome:'Opened'}});
        }).catch(failed);
      } else if(message.type==='solve_cloudflare_result') {
        replies.push(message.data);
        const current=operations.get(message.id);
        current.challenges.get(message.challenge_id)?.resolve(message.data);
        // A click leaves the page challenged first; a subsequent DOM change establishes readiness.
        void browser.accessState(tabs[1]).then(probe=>{
          assert.equal(probe.markers.cloudflareOptions,true);
          setTimeout(()=>{void tabs[1].view.webContents.executeJavaScript('document.querySelectorAll("script").forEach(node=>node.remove())').catch(failed);},100);
        }).catch(failed);
      } else if(message.type==='fixture_complete') {worker.stdin.end();finished();}
    });
    worker.once('error',failed);
    const exited=new Promise((resolve,reject)=>worker.once('exit',code=>code===0?resolve():reject(Error('Bridge fixture failed: '+stderr))));
    exited.catch(failed);
    try {send({token:'fixture-only'});await completion;await exited;}
    finally {lines.close();if(worker.exitCode===null)worker.kill();}
    console.log('CLOUDFLARE TARGET ISOLATION PASS');
  } finally {await browser.close();host.destroy();}
}).then(()=>app.exit(0),error=>{console.error(error);app.exit(1);});
