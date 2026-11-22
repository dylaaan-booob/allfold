'use strict';
const {app,session}=require('electron');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const path=require('node:path');
const {log}=require('../shared/logging.cjs');
const {PROJECT_ROOT}=require('../shared/paths.cjs');

let browserSession;

function reportCleanup(error) {
  log('warn','browser_session_cleanup_failed',{code:['EACCES','EPERM'].includes(error?.code)?'access_denied':'failed'});
}

function reclaimOldSessions(root,expected) {
  let fd;
  try {
    fd=fs.openSync(root,fs.constants.O_RDONLY|fs.constants.O_DIRECTORY|fs.constants.O_NOFOLLOW);
    const opened=fs.fstatSync(fd,{bigint:true});
    if(opened.dev!==expected.dev || opened.ino!==expected.ino)throw Error('Browser Session directory changed');
    // Python's standard library provides directory-relative, symlink-safe
    // removal. The one-off worker inherits the directory, not its pathname.
    const worker=spawn(path.join(PROJECT_ROOT,'.venv/bin/python'),
      [path.join(PROJECT_ROOT,'src/allfold/browser_session_cleanup.py')],
      {stdio:['ignore','ignore','ignore',fd]});
    worker.once('error',reportCleanup);
    worker.once('exit',code=>{if(code!==0)reportCleanup();});
    worker.unref();
  }catch(error){reportCleanup(error);}
  finally {
    if(fd!==undefined)try{fs.closeSync(fd);}catch(error){reportCleanup(error);}
  }
}

function sharedBrowserSession() {
  if(browserSession)return browserSession;
  const root=path.join(app.getPath('sessionData'),'allfold-browser-sessions');
  fs.mkdirSync(root,{recursive:true,mode:0o700});
  const rootInfo=fs.lstatSync(root,{bigint:true});
  if(!rootInfo.isDirectory())throw Error('Invalid Allfold Browser Session directory');
  const directory=fs.mkdtempSync(path.join(root,`run-${process.pid}-`));
  browserSession=session.fromPath(directory);
  // Main starts BrowserRuntime after claiming the app port. On quit the port
  // can be released before Chromium closes the Session, so also check the PID.
  // Electron owns native shutdown. Reclaim directories on a later launch.
  reclaimOldSessions(root,rootInfo);
  return browserSession;
}

module.exports={sharedBrowserSession};
