'use strict';
const {randomBytes}=require('node:crypto');
const {log}=require('../shared/logging.cjs');
function createCloudflareSolver({getBrowser,operations,send,isBridgeReady}) {
return async function solveCloudflare(doc,{signal,deadline=Infinity}={}) {
  const browser=getBrowser();
  const owner=browser.operation,current=operations.get(owner?.association.request_id);
  const contents=browser.tabs.get(doc.pageId)?.view.webContents;
  const currentDocument=()=>browser.ownsPage(owner,doc.pageId) && browser.documentCurrent(doc)
    && contents?.getURL()===doc.url && !contents.isLoadingMainFrame();
  if(!current || current.controller.signal.aborted || !isBridgeReady() || !currentDocument()
    || signal?.aborted || Date.now()>=deadline)return;
  let targetId;
  try {targetId=contents.getOrCreateDevToolsTargetId();} catch (_) {return;}
  if(!/^[a-f0-9]{32}$/i.test(targetId))return;
  const challengeId=randomBytes(16).toString('hex');
  const context={request_id:current.id,action:current.action,page_id:doc.pageId};
  const signals=[...new Set([signal,current.controller.signal].filter(Boolean))];
  let timer,cancel;
  const changed=(event,_url,inPlace,main)=>{
    if(event.isMainFrame ?? main)cancel();
  };
  log('info','cloudflare_solver_started',context);
  try {
    const result=await new Promise(resolve=>{
      cancel=()=>{
        if(!current.challenges.delete(challengeId))return;
        try {send({type:'cancel_cloudflare',id:current.id,action:current.action,challenge_id:challengeId});}
        catch (_) {}
        resolve({outcome:'not_executed',reason:'canceled'});
      };
      current.challenges.set(challengeId,{resolve:data=>{
        if(!currentDocument() || signals.some(item=>item.aborted) || Date.now()>=deadline){cancel();return;}
        resolve(data);
      },cancel});
      for(const item of signals)item.addEventListener('abort',cancel,{once:true});
      contents.on('did-start-navigation',changed);
      contents.once('destroyed',cancel);contents.once('render-process-gone',cancel);
      if(Number.isFinite(deadline))timer=setTimeout(cancel,Math.max(0,deadline-Date.now()));
      if(signals.some(item=>item.aborted) || !currentDocument()){cancel();return;}
      try {send({type:'solve_cloudflare',id:current.id,action:current.action,
        challenge_id:challengeId,data:{url:doc.url,target_id:targetId,deadline_ms:Number.isFinite(deadline)?Math.floor(deadline):Date.now()+600000}});}
      catch (_) {resolve({outcome:'not_executed',reason:'bridge_unavailable'});}
    });
    // A returned solver is not proof that the challenge was cleared.
    log(result.outcome==='failed'?'warn':'info','cloudflare_solver_finished',{
      ...context,outcome:result.outcome,code:result.reason});
    return result;
  } finally {
    clearTimeout(timer);
    for(const item of signals)item.removeEventListener('abort',cancel);
    contents.removeListener('did-start-navigation',changed);
    contents.removeListener('destroyed',cancel);contents.removeListener('render-process-gone',cancel);
    current.challenges.delete(challengeId);
  }
};
}
module.exports={createCloudflareSolver};
