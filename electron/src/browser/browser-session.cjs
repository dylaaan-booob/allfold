'use strict';
const {app,session}=require('electron');
const fs=require('node:fs');
const path=require('node:path');

function sharedBrowserSession() {
  const directory=path.join(app.getPath('sessionData'),'allfold-browser-session');
  fs.mkdirSync(directory,{recursive:true,mode:0o700});
  if(!fs.lstatSync(directory).isDirectory())throw Error('Invalid Allfold Browser Session directory');
  return session.fromPath(directory);
}

module.exports={sharedBrowserSession};
