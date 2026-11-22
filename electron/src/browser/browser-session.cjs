'use strict';
const {app,session}=require('electron');
const fs=require('node:fs');
const path=require('node:path');
const {log}=require('../shared/logging.cjs');

const runDirectory=/^run-([1-9]\d{0,9})-[a-zA-Z0-9]{6}$/;
let browserSession;

function processExited(pid) {
  // Permission errors and reused PIDs conservatively leave the directory alone.
  try {process.kill(pid,0);return false;}
  catch(error){return error.code==='ESRCH';}
}

function reportCleanup(error) {
  log('warn','browser_session_cleanup_failed',{code:['EACCES','EPERM'].includes(error.code)?'access_denied':'failed'});
}

async function reclaimOldSessions(root) {
  const entries=await fs.promises.readdir(root,{withFileTypes:true});
  for(const entry of entries) {
    const pid=Number(runDirectory.exec(entry.name)?.[1]);
    if(!entry.isDirectory() || !Number.isInteger(pid) || pid>0x7fffffff || !processExited(pid))continue;
    await fs.promises.rm(path.join(root,entry.name),{recursive:true,force:true}).catch(reportCleanup);
  }
}

function sharedBrowserSession() {
  if(browserSession)return browserSession;
  const root=path.join(app.getPath('sessionData'),'allfold-browser-sessions');
  fs.mkdirSync(root,{recursive:true,mode:0o700});
  if(!fs.lstatSync(root).isDirectory())throw Error('Invalid Allfold Browser Session directory');
  const directory=fs.mkdtempSync(path.join(root,`run-${process.pid}-`));
  browserSession=session.fromPath(directory);
  // Main starts BrowserRuntime after claiming the app port. On quit the port
  // can be released before Chromium closes the Session, so also check the PID.
  // Electron owns native shutdown. Reclaim directories on a later launch.
  void reclaimOldSessions(root).catch(reportCleanup);
  return browserSession;
}

module.exports={sharedBrowserSession};
