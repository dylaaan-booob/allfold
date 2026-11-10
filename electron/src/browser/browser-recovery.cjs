'use strict';
const {BrowserFailure}=require('./browser-errors.cjs');
const {checkCanceled,pause}=require('./browser-task.cjs');

const PAGE_RECOVERY_MS=180000;
const REFRESH_LIMIT=2;
const REFRESH_DELAY_MS=350;
const MAX_COOLDOWN_WAIT_MS=30000;
const RATE_LIMIT_DELAY_MS=1000;
const TRANSIENT_NETWORK=new Map([
  [-7,'ERR_TIMED_OUT'],
  [-100,'ERR_CONNECTION_CLOSED'],
  [-101,'ERR_CONNECTION_RESET'],
  [-118,'ERR_CONNECTION_TIMED_OUT'],
  [-324,'ERR_EMPTY_RESPONSE'],
]);

function loadFailure(value,netCode) {
  const error=new BrowserFailure('navigation','load_failed');
  const netError=String(value || '').match(/\bERR_[A-Z0-9_]{1,80}\b/)?.[0];
  netCode ??= [...TRANSIENT_NETWORK].find(([,description])=>description===netError)?.[0];
  if(Number.isInteger(netCode) && netCode>=-99999 && netCode<=0)error.diagnostic.net_code=netCode;
  if(netError)error.diagnostic.net_error=netError;
  return error;
}
function transientLoad(error) {
  const {code,net_code:netCode,net_error:netError}=error.diagnostic || {};
  return code==='load_failed' && TRANSIENT_NETWORK.has(netCode)
    && (!netError || TRANSIENT_NETWORK.get(netCode)===netError);
}
function reportRecovery(report,event,details) {
  try {report?.(event,details);} catch (_) { /* Diagnostics do not own navigation. */ }
}
function recoveryStop(error,signal) {
  const code=error?.diagnostic?.code;
  if(code==='timeout' || error?.cooldownBudget) return 'budget';
  if(signal?.aborted || code==='canceled')return 'canceled';
  if(['document_changed','configuration_changed','carsi_session_expired','page_closed'].includes(code))return 'authority';
  return 'failed';
}
function pageRecoveryDetails(error,action,fields) {
  return {step:'page_load',...error?.diagnostic,recovery_action:action,...fields,
    failure_kind:transientLoad(error)?'transport':error?.diagnostic?.code==='http_error'?'remote_service':
      error?.diagnostic?.code==='timeout'?'runtime':undefined};
}
function origin(value) {
  try {
    const url=new URL(value);
    if(['http:','https:'].includes(url.protocol) && !url.username && !url.password)return url.origin;
  } catch (_) { /* Non-HTTP pages have no cooldown. */ }
  return null;
}
function retryAfterTime(value,now) {
  const text=typeof value==='string'?value.trim():'';
  if(/^\d+$/.test(text))return now+Number(text)*1000;
  if(!/^(?:[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT|[A-Z][a-z]+, \d{2}-[A-Z][a-z]{2}-\d{2} \d{2}:\d{2}:\d{2} GMT|[A-Z][a-z]{2} [A-Z][a-z]{2} [ \d]\d \d{2}:\d{2}:\d{2} \d{4})$/.test(text))
    return undefined;
  const date=Date.parse(text);
  return Number.isFinite(date)?Math.max(now,date):undefined;
}

// One gate per Browser Session. The key is the actual entry origin in that Session.
class BrowserCooldown {
  constructor({now=Date.now,pause:wait=pause}={}) {
    this.now=now;
    this.pause=wait;
    this.origins=new Map();
  }
  observe(url,status,retryAfter) {
    const key=origin(url);
    if(!key || ![429,503].includes(status))return;
    const now=this.now();
    const until=retryAfterTime(retryAfter,now) ?? (status===429?now+RATE_LIMIT_DELAY_MS:now);
    for(const [entry,state] of this.origins)if(state.until<=now)this.origins.delete(entry);
    if(until>(this.origins.get(key)?.until ?? now))this.origins.set(key,{until,status});
  }
  async wait(url,{signal,deadline=Infinity,validate=()=>{},authorize,report,stage='navigation',step,pageId}={}) {
    const keys=[...new Set([].concat(url).map(origin).filter(Boolean))];
    const limit=Math.min(deadline,this.now()+MAX_COOLDOWN_WAIT_MS);
    let waited=false,last,authorized=!authorize;
    try {
      while(true) {
        checkCanceled(signal);
        validate();
        const now=this.now();
        let state;
        for(const key of keys) {
          const candidate=this.origins.get(key);
          if(!candidate)continue;
          if(candidate.until<=now)this.origins.delete(key);
          else if(!state || state.until<candidate.until)state=candidate;
        }
        if(!state) {
          if(!authorized) {
            await authorize(waited);
            authorized=true;
            continue;
          }
          if(waited)reportRecovery(report,'service_cooldown_ended',{...last,waiting:false});
          return waited;
        }
        const wait=state.until-now;
        last={stage,step,code:'http_error',status:state.status,page_id:pageId,recovery_action:'cooldown_wait',
          wait_ms:Math.min(wait,2147483647),failure_kind:'remote_service',dispatch_outcome:'not_dispatched'};
        if(wait>=limit-now) {
          reportRecovery(report,'recovery_exhausted',{...last,recovery_stop:'budget'});
          const error=new BrowserFailure(stage,'http_error',state.status);
          if(step)error.diagnostic.step=step;
          error.cooldownBudget=true;
          throw error;
        }
        reportRecovery(report,'service_cooldown_started',{...last,waiting:true});
        waited=true;authorized=!authorize;
        try {await this.pause(signal,wait);}
        catch(error){checkCanceled(signal);throw error;}
      }
    } catch(error) {
      if(waited && !error.cooldownBudget)
        reportRecovery(report,'recovery_exhausted',{...last,recovery_stop:recoveryStop(error,signal)});
      throw error;
    }
  }
}
module.exports={BrowserCooldown,PAGE_RECOVERY_MS,REFRESH_LIMIT,REFRESH_DELAY_MS,loadFailure,transientLoad,
  reportRecovery,recoveryStop,pageRecoveryDetails,origin};
