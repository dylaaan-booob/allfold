'use strict';
const {randomBytes}=require('node:crypto');
const {log}=require('../shared/logging.cjs');
const RESULTS=new Set(['waiting:checkbox_not_found','waiting:checkbox_not_interactable','waiting:checkbox_ambiguous',
  'waiting:cdp_unavailable','clicked:checkbox_clicked','not_executed:canceled','not_executed:target_closed',
  'not_executed:cdp_unavailable','failed:solver_failed']);

// Challenges belong to native pages, independently of business request lifetimes.
function createCloudflareSolver({getBrowser,send,isBridgeReady}) {
  const challenges=new Map();
  const matches=(entry,message)=>entry && message.page_id===entry.tab.id && message.target_id===entry.targetId;
  function live(entry) {
    const browser=getBrowser(),contents=entry.tab.view.webContents;
    return browser?.tabs.get(entry.tab.id)===entry.tab && !entry.tab.closing && !browser.destroying
      && contents.session===browser.partition && !contents.isDestroyed() && !contents.isCrashed()
      && contents.getOrCreateDevToolsTargetId()===entry.targetId;
  }
  async function solve(tab,{signal,onProgress=()=>{}}={}) {
    const contents=tab.view.webContents;
    const targetId=contents.getOrCreateDevToolsTargetId();
    const challengeId=randomBytes(16).toString('hex');
    const entry={tab,targetId};
    if(!/^[a-f0-9]{32}$/i.test(targetId) || !isBridgeReady() || signal?.aborted || !live(entry))
      return {outcome:'not_executed',reason:'cdp_unavailable'};
    if([...challenges.values()].some(item=>item.tab===tab))throw Error('Challenge already active');
    const envelope=type=>({type,page_id:tab.id,target_id:targetId,challenge_id:challengeId});
    let cancel;
    log('info','cloudflare_solver_started',{page_id:tab.id});
    try {
      const result=await new Promise(resolve=>{
        entry.resolve=resolve;entry.progress=onProgress;
        entry.cancel=cancel=()=>{
          if(entry.canceled)return;
          entry.canceled=true;
          // Only the terminal reply (or the child's confirmed drain/exit) releases work.
          if(isBridgeReady())try{send(envelope('cancel_cloudflare'));}catch(_){}
        };
        challenges.set(challengeId,entry);
        signal?.addEventListener('abort',cancel,{once:true});
        contents.once('destroyed',cancel);contents.once('render-process-gone',cancel);
        try {send(envelope('solve_cloudflare'));}
        catch(_){challenges.delete(challengeId);resolve({outcome:'not_executed',reason:'cdp_unavailable'});}
      });
      log(result.outcome==='failed'?'warn':'info','cloudflare_solver_finished',{
        page_id:tab.id,outcome:result.outcome,code:result.reason});
      return result;
    } finally {
      signal?.removeEventListener('abort',cancel);
      contents.removeListener('destroyed',cancel);contents.removeListener('render-process-gone',cancel);
      challenges.delete(challengeId);
    }
  }
  solve.receive=message=>{
    const entry=challenges.get(message.challenge_id);
    if(!matches(entry,message))return;
    const data=message.data;
    if(!data || !RESULTS.has(data.outcome+':'+data.reason))throw Error('Invalid challenge result');
    if(message.type==='solve_cloudflare_result')entry.resolve({outcome:data.outcome,reason:data.reason});
    else if(message.type==='cloudflare_progress' && !entry.canceled && live(entry)){
      log('info','page_access',{page_id:entry.tab.id,access_state:data.outcome==='clicked'?'handling':'waiting',challenge_type:'cloudflare',code:data.reason});
      entry.progress({outcome:data.outcome,reason:data.reason});
    }
  };
  solve.stop=()=>{for(const entry of challenges.values())entry.cancel();};
  solve.drained=()=>{
    for(const entry of challenges.values())entry.resolve({outcome:'not_executed',reason:'canceled'});
  };
  return solve;
}
module.exports={createCloudflareSolver};
