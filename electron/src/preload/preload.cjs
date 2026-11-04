'use strict';
const {contextBridge, ipcRenderer} = require('electron');
const subscribe=(channel,callback)=>{
  const listener=(_event,value)=>callback(value);
  ipcRenderer.on(channel,listener);return ()=>ipcRenderer.removeListener(channel,listener);
};
contextBridge.exposeInMainWorld('allfoldDesktop', Object.freeze({
  showBrowser: () => ipcRenderer.invoke('browser:show'),
  browserState: () => ipcRenderer.invoke('browser:state'),
  browserCommand: value => ipcRenderer.invoke('browser:command',value),
  setBrowserPresentation: value => ipcRenderer.invoke('browser:presentation',value),
  onBrowserState: callback => subscribe('browser:state',callback),
  onBrowserPresentation: callback => subscribe('browser:presentation',callback),
  onBrowserLayout: callback => subscribe('browser:layout',callback),
  casStatus: () => ipcRenderer.invoke('cas:status'),
  saveCASCredentials: value => ipcRenderer.invoke('cas:save',value),
  clearCASCredentials: () => ipcRenderer.invoke('cas:clear'),
}));
