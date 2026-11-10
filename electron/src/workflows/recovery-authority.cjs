'use strict';
const {randomBytes}=require('node:crypto');
const {BrowserFailure}=require('../browser/browser-errors.cjs');
const {checkCanceled,timeoutFailure,waitFor}=require('../browser/browser-task.cjs');

const AUTHORITY_TIMEOUT_MS=5000;

async function validateRecovery(current,send,{signal,deadline=Infinity,stage='navigation'}={}) {
  const invocation=current.controller.signal;
  const signals=[invocation,signal].filter(Boolean);
  const stop=AbortSignal.any(signals);
  const limit=Math.min(deadline,Date.now()+AUTHORITY_TIMEOUT_MS);
  checkCanceled(stop,stage);
  if(current.authority)throw new BrowserFailure(stage,'document_changed');
  const checkId=randomBytes(16).toString('hex');
  try {
    const allowed=await waitFor(()=>new Promise(resolve=>{
      current.authority={checkId,resolve};
      try {send({type:'verify_recovery_authority',id:current.id,action:current.action,
        check_id:checkId,data:{}});}
      catch (_) {resolve(false);}
    }),stop,limit,stage,'recovery_authority');
    checkCanceled(stop,stage);
    if(Date.now()>=limit)throw timeoutFailure(stage,'recovery_authority');
    if(!allowed)throw new BrowserFailure(stage,'document_changed');
  } finally {
    current.authority=null;
  }
}

function settleRecoveryAuthority(current,message) {
  const pending=current?.authority;
  if(pending?.checkId===message.check_id)pending.resolve(message.data?.allowed===true);
}

module.exports={validateRecovery,settleRecoveryAuthority};
