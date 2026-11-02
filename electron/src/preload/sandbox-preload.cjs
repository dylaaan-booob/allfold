'use strict';
const {contextBridge, ipcRenderer} = require('electron');
contextBridge.exposeInMainWorld('translatorHost', Object.freeze({
  request: spec => ipcRenderer.invoke('translator:request', spec),
}));
