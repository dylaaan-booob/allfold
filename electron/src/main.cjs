'use strict';
const {app,BrowserWindow,ipcMain,dialog} = require('electron');
const {spawn,spawnSync} = require('node:child_process');
const {randomBytes,createHash} = require('node:crypto');
const path = require('node:path');
const fs = require('node:fs');
const {BrowserRuntime} = require('./browser/browser-runtime.cjs');
const {installBrowserIPC}=require('./browser/browser-ipc.cjs');
const {validateRecovery,settleRecoveryAuthority}=require('./workflows/recovery-authority.cjs');
const {invocationRecovery}=require('./shared/recovery-summary.cjs');
const {BrowserFailure,diagnosticFor}=require('./browser/browser-errors.cjs');
const {log,errorCode,initializeLogging,withLogContext,associationLogContext,diagnosticsReset,diagnosticsStatus,setLogLevel} = require('./shared/logging.cjs');
const {operationAssociation}=require('./browser/page-association.cjs');
const {loginInstitution,prepareLoggedInService,visitManualService,searchJournalCover}=require('./workflows/browser-operations.cjs');
const {wosQuery,wosExport}=require('./workflows/wos-operations.cjs');
const {readCASCredentials,casStatus,saveCASCredentials,clearCASCredentials,casErrorCode}=require('./auth/cas-credentials.cjs');
const {confirmConfigurationExit,confirmBlockedUnload}=require('./shared/configuration-exit.cjs');
const {ELECTRON_ROOT,PROJECT_ROOT:ROOT,PRELOAD_DIR}=require('./shared/paths.cjs');
const cdpStartedAt=Date.now();
// Finish the asynchronous port probe before Electron initializes its CDP server.
const cdpPort=spawnSync(process.execPath,[path.join(ELECTRON_ROOT,'scripts/select-cdp-port.cjs')],{
  env:{...process.env,ELECTRON_RUN_AS_NODE:'1'},encoding:'utf8',
});
app.commandLine.appendSwitch('remote-debugging-address','127.0.0.1');
if(cdpPort.status===0)app.commandLine.appendSwitch('remote-debugging-port',cdpPort.stdout.trim());
let python,window,browser,socket,base;
let exiting=false,readyToExit=false,bridgeReady=false;
let exitApproved=false,exitCheck=null;
const operations=new Map();
const token=randomBytes(32).toString('hex');
function trusted(event) {
  return window && event.sender === window.webContents && event.senderFrame === event.sender.mainFrame
    && new URL(event.senderFrame.url).origin === base;
}
function send(message) {
  if (socket?.readyState !== WebSocket.OPEN) throw Error('Electron bridge disconnected');
  socket.send(JSON.stringify(message));
}
const CONTROL_ACTIONS=new Set(['cas_credentials','diagnostics_reset']);
function pendingOperation(message) {
  const current=operations.get(message.id);
  return current?.action===message.action?current:null;
}
function stopOperations() {
  for(const current of operations.values())current.controller.abort();
}
function waitForOperations() {
  return Promise.allSettled([...operations.values()].map(current=>current.settlement));
}
let pythonShutdownReady=false,disconnectedDrain;
function drainDisconnectedPython() {
  // Socket loss may happen after an orderly quit has already sent shutdown.
  // Only request Python teardown once every active native operation has settled.
  disconnectedDrain ??= waitForOperations().then(()=>{
    if(python && python.exitCode===null && python.signalCode===null)python.kill('SIGUSR1');
    else {readyToExit=true;app.quit();}
  });
}
const {createCloudflareSolver}=require('./browser/cloudflare-dispatch.cjs');
const dispatchCloudflare=createCloudflareSolver({getBrowser:()=>browser,operations,send,isBridgeReady:()=>bridgeReady});

function solveCloudflare(doc,options) {return dispatchCloudflare(doc,options);}
async function executeControl(message,signal) {
  const value=message.data;
  if(message.action==='diagnostics_reset')return diagnosticsReset(value);
  if(message.action==='cas_credentials') {
    try {
      if(!value || !['save','clear'].includes(value.operation))throw Error('Invalid credential operation');
      return await (value.operation==='save'?saveCASCredentials(value):clearCASCredentials(value));
    }catch(error){return {ok:false,error:casErrorCode(error)};}
  }
  return {ok:false,error:'unsupported_operation'};
}
async function execute(message) {
  if(!CONTROL_ACTIONS.has(message.action) && !['login_carsi','prepare_service','visit_manual_service','search_journal_cover','wos_query','wos_export'].includes(message.action)){
    send({type:'result',id:message.id,action:message.action,data:{diagnostic:{stage:'navigation',code:'unsupported_operation'}}});return;
  }
  const control=CONTROL_ACTIONS.has(message.action);
  if(exiting) {
    // A request sent just before Python sees shutdown still needs a terminal response.
    const error=new BrowserFailure('navigation','canceled');
    const data=control?{ok:false,error:'canceled'}:{diagnostic:error.diagnostic};
    send({type:'result',id:message.id,action:message.action,data});
    return;
  }
  if(operations.has(message.id))throw Error('Duplicate native Request ID');
  if(operations.size && (control || [...operations.values()].some(value=>CONTROL_ACTIONS.has(value.action))))
    throw Error('Concurrent dispatch conflicts with an active native control operation');
  const current={id:message.id,action:message.action,controller:new AbortController(),challenges:new Map()};
  operations.set(current.id,current);
  current.settlement=Promise.resolve().then(async()=>{
    if(control) {
      const data=await executeControl(message,current.controller.signal);
      send({type:'result',id:message.id,action:message.action,data});
      return;
    }
    let association;
    try {association=operationAssociation({...message.data,request_id:message.id});}catch(_){association=null;}
    setLogLevel(message.data?.log_level);
    return withLogContext({...associationLogContext(association),action:message.action},()=>executeOperation(message,current));
  });
  try {await current.settlement;}
  finally {
    operations.delete(current.id);
    if(!control)browser.publish();
  }
}
async function executeOperation(message,current) {
  const {controller}=current;
  const started=Date.now(),context={request_id:message.id,action:message.action};
  log('debug','task_started',context);
  let stage='navigation';
  let data,resultPageId;
  const recovery=invocationRecovery();
  const verifyRecovery=options=>validateRecovery(current,send,options);
  try {
    data=await browser.runTask(controller.signal,{...message.data,request_id:message.id},async()=>{
      browser.operation.action=message.action;
      try {
        if(controller.signal.aborted)throw new BrowserFailure('navigation','canceled');
        let lastProgress,waiting=false;
        const progress=(data,progressStage=stage,diagnostic)=>{
          const signature=JSON.stringify([progressStage,data.message,data.waiting_for_user,data.recovery_action]);
          if(signature!==lastProgress) {
            lastProgress=signature;
            log('debug','task_progress',{...context,page_id:browser.taskTab?.id,stage:progressStage});
          }
          if(typeof data.waiting_for_user==='boolean' && data.waiting_for_user!==waiting) {
            waiting=data.waiting_for_user;
            log('info','manual_wait',{...diagnostic,...context,page_id:browser.taskTab?.id,waiting});
          }
          send({type:'progress',id:message.id,action:message.action,data:{...data,page_id:browser.taskTab?.id}});
        };
        const {page_id,source_page_id,generation,...associationContext}=associationLogContext(browser.operation.association);
        const recoveryContext={...associationContext,...context};
        let recoveryAction;
        const recordRecovery=(event,details)=>{
          recovery.record(event,{...details,...recoveryContext});
          const started=event==='recovery_scheduled' || event==='service_cooldown_started' && details.waiting===true;
          const ended=['recovery_succeeded','recovery_exhausted','service_cooldown_ended'].includes(event);
          if(!started && !(ended && recoveryAction===details.recovery_action))return;
          recoveryAction=started?details.recovery_action:undefined;
          try {progress({recovery_action:recoveryAction},details.stage);}
          catch (_) {}
        };
        browser.operation.recordRecovery=recordRecovery;
        if(message.action==='prepare_service')
          browser.operation.validateRecovery=verifyRecovery;
        if(message.action === 'login_carsi') {
          stage='authentication';
          return await loginInstitution(browser,message.data,{signal:controller.signal,progress});
        } else if(message.action === 'prepare_service' || message.action === 'visit_manual_service') {
          stage='preparation';
          const prepare=message.action==='visit_manual_service'?visitManualService:prepareLoggedInService;
          return await prepare(browser,message.data,{signal:controller.signal,progress});
        } else if(message.action === 'search_journal_cover') {
          return await searchJournalCover(browser,message.data,{signal:controller.signal,progress});
        } else if(message.action === 'wos_query' || message.action === 'wos_export') {
          stage=message.action==='wos_query'?'wos_dom':'wos_download';
          return await (message.action==='wos_query'?wosQuery:wosExport)(browser,message.data,{signal:controller.signal,progress});
        } else throw Error('Unsupported Electron operation');
      } finally {
        for(const challenge of current.challenges.values())challenge.cancel();
        resultPageId=browser.taskTab?.id;
      }
    });
  } catch (error) {
    data={diagnostic:diagnosticFor(error,stage)};
  }
  const diagnostic=data.diagnostic || {};
  const outcome=data.outcome || (data.filename?'downloaded':Number.isInteger(data.total)?'queried':data.source_url?'retrieved':'no_result');
  const canceled=controller.signal.aborted || diagnostic.code==='canceled';
  const failed=!!data.diagnostic || !!data.error || data.outcome==='Needs attention' || outcome==='no_result';
  log(canceled?'info':failed?'warn':'info','task_finished',{...context,page_id:resultPageId,
    duration_ms:Date.now()-started,outcome:canceled?'canceled':outcome,
    stage:diagnostic.stage || stage,
    step:diagnostic.step,code:diagnostic.code || data.reason,net_error:diagnostic.net_error,net_code:diagnostic.net_code,status:diagnostic.status,
    imperva_edet:diagnostic.imperva_edet,imperva_incident_id:diagnostic.imperva_incident_id});
  const summary=recovery.summary();
  send({type:'result',id:message.id,action:message.action,data:{...data,...(summary.length?{recovery:summary}:{}),diagnostics_status:diagnosticsStatus()}});
}
async function startPython(config,cdpURL) {
  if(!fs.existsSync(path.join(ROOT,'.venv/bin/python'))) throw Error('Run uv sync --locked --group dev in the project copy first');
  python=spawn(path.join(ROOT,'.venv/bin/python'),['-u','-m','allfold.web.electron_server',config],{
    cwd:ROOT,stdio:['ignore','pipe','pipe'],env:{...process.env,ALLFOLD_ELECTRON_TOKEN:token,ALLFOLD_ELECTRON_CDP_URL:cdpURL},
  });
  let portUnavailable=false;
  python.stderr.on('data',bytes=>{
    if(bytes.toString().includes('Electron UI port 18767 is unavailable'))portUnavailable=true;
    process.stderr.write(bytes);
  });
  python.on('error',()=>{dialog.showErrorBox('Allfold','Python could not start');app.quit();});
  python.on('exit',(code,signal)=>{
    stopOperations();
    if (!exiting) log('error','python_exited',{exit_code:code});
    if (!exiting && base) dialog.showErrorBox('Allfold','Python exited. Inspect the terminal output before restarting.');
    readyToExit=true;
    if(base || exiting)app.quit();
  });
  const port=await new Promise((resolve,reject)=>{
    let output='';
    const timer=setTimeout(()=>reject(Error('Python startup timed out')),30000);
    python.once('exit',()=>{clearTimeout(timer);reject(Error(portUnavailable
      ? 'Electron UI port 18767 is unavailable; close the other instance before restarting'
      : 'Python exited during startup'));});
    python.stdout.on('data',bytes=>{
      output+=bytes.toString('utf8');
      const match=output.match(/^ELECTRON_PORT=(\d+)\n/);
      if(match){clearTimeout(timer);resolve(Number(match[1]));}
      if(output.length>128){clearTimeout(timer);reject(Error('Invalid Python bootstrap'));}
    });
  });
  base='http://127.0.0.1:'+port;
  for(let i=0;i<200;i++) {
    if(python.exitCode !== null) throw Error('Python exited during startup');
    try {if((await fetch(base+'/api/electron/health')).ok)return;} catch (_) {}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw Error('FastAPI did not become ready');
}
async function connect() {
  socket=new WebSocket(base.replace('http:','ws:')+'/api/electron/ws');
  await new Promise((resolve,reject)=>{
    socket.addEventListener('open',()=>send({type:'hello',token,diagnostics_status:diagnosticsStatus()}),{once:true});
    socket.addEventListener('error',()=>reject(Error('Electron bridge connection failed')),{once:true});
    socket.addEventListener('message',event=>{
      try {
        const message=JSON.parse(event.data);
        if(message.type === 'ready') {setLogLevel(message.log_level);bridgeReady=true;resolve();}
        else if(message.type === 'cancel') {
          pendingOperation(message)?.controller.abort();
        }
        else if(message.type === 'solve_cloudflare_result') {
          const current=pendingOperation(message),challenge=current?.challenges.get(message.challenge_id);
          if(!challenge || current.controller.signal.aborted)return;
          if(!message.data || typeof message.data!=='object')throw Error('Invalid challenge result');
          challenge.resolve(message.data);
        }
        else if(message.type === 'verify_recovery_authority_result')settleRecoveryAuthority(pendingOperation(message),message);
        else if(message.type === 'shutdown_ready') {
          // Python has processed the final result and can now exit gracefully.
          pythonShutdownReady=true;
          socket.close();
        } else if(message.type === 'execute' && typeof message.id === 'string') {
          void execute(message).catch(()=>socket.close());
        } else socket.close();
      } catch (_) {socket.close();}
    });
    socket.addEventListener('close',()=>{
      bridgeReady=false;
      stopOperations();
      if(!exiting) {
        log('error','bridge_disconnected');
        dialog.showErrorBox('Allfold','Electron connection lost. 当前操作已停止，请重新启动应用。');
        app.quit();
      } else if(!pythonShutdownReady)drainDisconnectedPython();
    });
  });
}
async function main() {
  const configFlag=process.argv.indexOf('--config');
  const config=path.resolve(configFlag>=0?process.argv[configFlag+1]:path.join(ROOT,'config.example.yaml'));
  const logRoot=path.resolve(process.env.ALLFOLD_DIAGNOSTICS_ROOT || path.join(app.getPath('logs'),'diagnostics'));
  // Both producers share one startup identity and the canonical configuration scope.
  process.env.ALLFOLD_DIAGNOSTICS_ROOT=logRoot;
  process.env.ALLFOLD_RUNTIME_ID=randomBytes(16).toString('hex');
  let canonicalConfig;try {canonicalConfig=fs.realpathSync(config);}catch(_){canonicalConfig=config;}
  initializeLogging({root:logRoot,runtimeId:process.env.ALLFOLD_RUNTIME_ID,
    scopeId:createHash('sha256').update(canonicalConfig).digest('hex')});
  log('info','app_started');
  let cdpURL='';
  const filename=path.join(app.getPath('sessionData'),'DevToolsActivePort');
  // Chromium writes this file asynchronously; never reuse a previous run's endpoint.
  for(let i=0;cdpPort.status===0 && i<20;i++) {
    try {
      const stat=await fs.promises.stat(filename);
      if(stat.mtimeMs<cdpStartedAt)throw Error('Stale DevTools port');
      const [port,browserPath]=(await fs.promises.readFile(filename,'utf8')).trim().split(/\r?\n/);
      if(!/^\d+$/.test(port) || Number(port)<1 || Number(port)>65535
        || !/^\/devtools\/browser\/[a-f0-9-]+$/.test(browserPath))throw Error('Invalid DevTools port');
      cdpURL='ws://127.0.0.1:'+port+browserPath;
      break;
    } catch (_) {}
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  if(!cdpURL)log('warn','cloudflare_solver_unavailable',{code:'cdp_unavailable'});
  await startPython(config,cdpURL);
  // The rendered layout fixture verifies ARRAY, Journals and Browser at this size.
  window=new BrowserWindow({width:1440,height:920,minWidth:600,minHeight:480,title:'Allfold',
    webPreferences:{preload:path.join(PRELOAD_DIR,'preload.cjs'),sandbox:true,
      contextIsolation:true,nodeIntegration:false,webSecurity:true}});
  window.webContents.setWindowOpenHandler(({url})=>{
    // Explicit user links (including Manual Services) open in the same native Session.
    if(browser && new URL(window.webContents.getURL()).origin===base)
      void browser.openURL(url).catch(()=>{});
    return {action:'deny'};
  });
  window.webContents.on('will-navigate',(event,url)=>{if(new URL(url).origin !== base)event.preventDefault();});
  // Keep the window alive while native operations and Python Paper writes settle.
  window.on('close',event=>{if(!readyToExit){event.preventDefault();app.quit();}});
  window.webContents.on('will-prevent-unload',event=>{
    if(exitApproved || confirmBlockedUnload(window,dialog))event.preventDefault();
  });
  browser=new BrowserRuntime({hostWindow:window,solveCloudflare,isTaskRunning:()=>operations.size>0,readCASCredentials:async()=>{
    if(exiting)return null;
    const credentials=await readCASCredentials();
    return exiting?null:credentials;
  }});
  await browser.ready;
  const removeBrowserIPC=installBrowserIPC({ipcMain,hostWindow:window,origin:base,browser});
  window.once('closed',removeBrowserIPC);
  window.webContents.on('did-finish-load',()=>browser.publish());
  // Credential mutations use the authenticated bridge after Python task admission.
  for(const [channel,handler] of Object.entries({'cas:status':casStatus})) {
    ipcMain.handle(channel,async(event,value)=>{
      if(!trusted(event))throw Error('Untrusted CAS sender');
      try {return await handler(value);}
      catch(error) {return {ok:false,error:casErrorCode(error)};}
    });
  }
  await connect();
  await window.loadURL(base+'/');
  log('info','app_ready',{port:18767});
}
app.whenReady().then(main).catch(error=>{
  log('error','startup_failed',{code:errorCode(error)});
  dialog.showErrorBox('Allfold',error.message);
  app.quit();
});
app.on('before-quit',event=>{
  if(!readyToExit && !exitApproved && window && !window.isDestroyed()) {
    event.preventDefault();
    if(!exitCheck)exitCheck=confirmConfigurationExit(window,dialog).then(approved=>{
      exitCheck=null;if(approved){exitApproved=true;app.quit();}
    }).catch(()=>{exitCheck=null;});
    return;
  }
  if(readyToExit && operations.size) {
    event.preventDefault();
    exiting=true;
    stopOperations();
    void waitForOperations().then(()=>app.quit());
    return;
  }
  if(readyToExit){browser?.close();return;}
  event.preventDefault();
  if(exiting)return;
  exiting=true;
  stopOperations();
  log('info','app_exiting');
  if(bridgeReady) {
    // Sent immediately: Python stops the next dispatch while this request settles.
    try {send({type:'shutdown'});}
    catch (_) {drainDisconnectedPython();}
  } else drainDisconnectedPython();
});
app.on('window-all-closed',()=>app.quit());
