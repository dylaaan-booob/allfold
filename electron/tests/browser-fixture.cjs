'use strict';
// These workflow-only fixtures expose verification and business-stage transitions.
// NavigationRecovery and Session hooks are exercised through BrowserRuntime.runTask.
const {inspectPage,waitForPage}=require('../src/browser/browser-navigation.cjs');
function attachBrowserMechanisms(browser) {
  const solverDocuments=new Map();
  browser.retainAccessPage=tab=>{tab.resourceOwner={kind:'access'};};
  browser.loanWorkflowPage=(tab,document)=>{tab.workflowLoan=document;};
  browser.bindTaskPage=function(tab,signal){this.taskTab=tab;this.taskActive=true;tab.taskSignal=signal;};
  browser.associatePage=(tab,association)=>{tab.association={...tab.association,...association};};
  browser.pageAssociation=id=>browser.tabs?.get(id)?.association;
  browser.beginPageLoad=function(tab,signal) {
    this.taskTab=tab;this.taskActive=true;tab.taskSignal=signal;tab.loadAllowed=true;
    tab.recoveryActive=true;tab.reloads ??= 0;
  };
  browser.finishPageLoad=tab=>{tab.recoveryActive=false;tab.loadAllowed=false;};
  browser.enterBusiness=()=>{for(const tab of browser.tabs?.values() || [])browser.finishPageLoad(tab);};
  browser.inspectPage=async(tab,options={})=>{
    if(tab.view.webContents.isLoadingMainFrame())return {loading:true};
    return inspectPage({...options,solverDocuments,
      probe:async()=>({...await browser.documentBinding(tab),markers:{},...await browser.accessState?.(tab)}),current:doc=>browser.documentCurrent(doc),
      authentication:()=>browser.checkAuthentication?.(tab) || false,
      inspectAuthentication:()=>browser.inspectAuthentication?.(tab) || {waiting:false},
      solveCloudflare:browser.solveCloudflare});
  };
  browser.waitForPage=async(tab,options)=>{
    try{return await waitForPage(()=>browser.inspectPage(tab,options),options);}
    finally{browser.finishPageLoad(tab);}
  };
  return browser;
}
module.exports={attachBrowserMechanisms};
