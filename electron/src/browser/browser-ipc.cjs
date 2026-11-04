'use strict';
function installBrowserIPC({ipcMain,hostWindow,origin,browser}) {
  function trusted(event) {
    if(event.sender!==hostWindow.webContents || event.senderFrame!==event.sender.mainFrame)return false;
    try {const url=new URL(event.senderFrame.url);return url.origin===origin && url.pathname==='/' && !url.username && !url.password;}
    catch(_){return false;}
  }
  const commands={
    'browser:show':()=>browser.show(),
    'browser:state':()=>browser.state(),
    'browser:command':value=>browser.command(value),
    'browser:presentation':value=>browser.setPresentation(value),
  };
  for(const [channel,handler]of Object.entries(commands))ipcMain.handle(channel,(event,value)=>{
    if(!trusted(event))throw Error('Untrusted Browser sender');
    return handler(value);
  });
  return ()=>{for(const channel of Object.keys(commands))ipcMain.removeHandler(channel);};
}
module.exports={installBrowserIPC};
