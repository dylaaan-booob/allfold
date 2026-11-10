'use strict';
const {setTimeout:delay}=require('node:timers/promises');
const {BrowserFailure}=require('./browser-errors.cjs');
const TASK_DEADLINE_MS=600000;
const PAGE_LOAD_MS=85000;

function checkCanceled(signal) {
  if(signal?.aborted)throw signal.reason instanceof BrowserFailure?signal.reason:new BrowserFailure('navigation','canceled');
}
function timeoutFailure(stage,step) {
  const error=new BrowserFailure(stage,'timeout');error.diagnostic.step=step;return error;
}
async function pause(signal,milliseconds=350) {
  checkCanceled(signal);
  try {await delay(milliseconds,undefined,{signal});}catch(error){checkCanceled(signal);throw error;}
}
// Bound individual native calls as well as polling; a late result cannot dispatch the next action.
async function waitFor(run,signal,deadline=Infinity,stage='navigation',step='page_load') {
  checkCanceled(signal);
  if(Date.now()>=deadline)throw timeoutFailure(stage,step);
  let timer,abort;
  try {
    const stopped=new Promise((_,reject)=>{
      abort=()=>{try {checkCanceled(signal);}catch(error){reject(error);}};
      signal?.addEventListener('abort',abort,{once:true});
      if(Number.isFinite(deadline))timer=setTimeout(()=>reject(timeoutFailure(stage,step)),Math.max(0,deadline-Date.now()));
    });
    const result=await Promise.race([run(),stopped]);
    checkCanceled(signal);
    if(Date.now()>=deadline)throw timeoutFailure(stage,step);
    return result;
  } finally {clearTimeout(timer);signal?.removeEventListener('abort',abort);}
}
async function withTaskDeadline(signal,stage,run) {
  const controller=new AbortController(),deadline=Date.now()+TASK_DEADLINE_MS;
  const bounded=AbortSignal.any([controller.signal,...(signal?[signal]:[])]);
  const timer=setTimeout(()=>controller.abort(timeoutFailure(stage,'request')),Math.max(0,deadline-Date.now()));
  try {
    checkCanceled(bounded);
    const result=await run(bounded,deadline);
    checkCanceled(bounded);
    if(Date.now()>=deadline)throw timeoutFailure(stage,'request');
    return result;
  }
  finally {clearTimeout(timer);controller.abort();}
}
async function waitForLoad(tab,signal,deadline=Infinity,checkState) {
  const limit=Math.min(deadline,Date.now()+PAGE_LOAD_MS);
  while(tab.view.webContents.isLoadingMainFrame()) {
    checkState?.();
    await waitFor(()=>pause(signal),signal,limit);
  }
  checkState?.();
}
module.exports={checkCanceled,timeoutFailure,pause,waitFor,withTaskDeadline,waitForLoad,TASK_DEADLINE_MS,PAGE_LOAD_MS};
