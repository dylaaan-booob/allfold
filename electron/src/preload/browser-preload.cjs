'use strict';
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('browserChrome', Object.freeze({
  command:command => ipcRenderer.invoke('browser:command', command),
  onState:callback => ipcRenderer.on('browser:state', (_event,state) => callback(state)),
}));
