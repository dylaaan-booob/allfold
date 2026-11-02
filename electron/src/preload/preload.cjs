'use strict';
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('allfoldDesktop', Object.freeze({
  showBrowser: () => ipcRenderer.invoke('browser:show'),
  browserState: () => ipcRenderer.invoke('browser:state'),
  casStatus: () => ipcRenderer.invoke('cas:status'),
  saveCASCredentials: value => ipcRenderer.invoke('cas:save',value),
  clearCASCredentials: () => ipcRenderer.invoke('cas:clear'),
}));
