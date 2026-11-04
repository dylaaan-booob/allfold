'use strict';
const {contextBridge}=require('electron');
// Empty synthetic presentation adapter: no pages, Session or external authority.
contextBridge.exposeInMainWorld('allfoldDesktop',{
  browserState:async()=>({tabs:[],selected:null}),showBrowser:async()=>({tabs:[],selected:null}),
  setBrowserPresentation:async()=>{},onBrowserState(){},onBrowserPresentation(){},onBrowserLayout(){},
});
