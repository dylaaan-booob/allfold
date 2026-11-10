'use strict';
const {AsyncLocalStorage}=require('node:async_hooks');
const schema=require('../../../src/allfold/diagnostic_schema.json');
const {DiagnosticWriter}=require('./diagnostic-writer.cjs');
const levels={debug:10,info:20,warn:30,error:40};
const context=new AsyncLocalStorage();
function normalizedLevel(value) {
  const level=typeof value==='string'?value.toLowerCase():'';
  return level==='warning'?'warn':levels[level]?level:'info';
}
function valid(value,definition) {
  if(definition.type==='integer')return Number.isSafeInteger(value) && value>=definition.minimum && value<=definition.maximum;
  if(definition.type==='boolean')return typeof value==='boolean';
  return typeof value==='string' && (definition.enum?definition.enum.includes(value):new RegExp(definition.pattern).test(value));
}
function recoveryEvidence(details) {
  const evidence={};
  for(const key of ['stage','step','code','status','net_code','net_error','failure_kind',
    'transport_error','dispatch_outcome','recovery_stop','page_id','source_page_id']) {
    if(valid(details[key],schema.fields[key]))evidence[key]=details[key];
  }
  return evidence;
}
function sanitize(record) {
  const result={};
  for(const [key,value] of Object.entries(record || {}))if(schema.fields[key] && valid(value,schema.fields[key]))result[key]=value;
  if(schema.required.some(key=>result[key]===undefined)
    || (schema.events_require[result.event] || []).some(key=>result[key]===undefined))return null;
  return result;
}
function createLogger({root,runtimeId='uninitialized',scopeId,level,stderr=line=>process.stderr.write(line),...limits}={}) {
  const writer=root?new DiagnosticWriter({root,scopeId,...limits}):null;
  let detailLevel=normalizedLevel(level);
  return {
    log(level,event,details={}) {
      const supplied={...context.getStore(),...details};
      if(scopeId && supplied.scope_id && supplied.scope_id!==scopeId){writer?.omit();return;}
      if(typeof supplied.code==='string' && /^ERR_[A-Z0-9_]{1,80}$/.test(supplied.code)) {
        supplied.net_error=supplied.code;supplied.code='network_error';
      }
      const record=sanitize({...supplied,schema_version:1,time:new Date().toISOString(),level,event,source:'electron',runtime_id:runtimeId,
        ...(scopeId?{scope_id:scopeId}:{})});
      if(!record)return;
      const threshold=levels[normalizedLevel(process.env.ALLFOLD_LOG_LEVEL || detailLevel)];
      if(schema.optional_detail_events.includes(event) && levels[level]<threshold)return;
      // A logging failure never changes the caller's result or save settlement.
      try {stderr(JSON.stringify(record)+'\n');}catch(_){}
      if(writer && !writer.append(record)) {
        try {stderr(JSON.stringify({schema_version:1,time:new Date().toISOString(),source:'electron',runtime_id:runtimeId,level:'warn',event:'diagnostic_write_failed'})+'\n');}catch(_){}
      }
    },
    setLevel(value){if(typeof value==='string')detailLevel=normalizedLevel(value);},
    status:()=>writer?writer.status():{available:false,incomplete:true},
    readEvents:()=>writer?.readEvents() || [],
    reset(data) {
      if(!writer || data?.scope_id!==scopeId)return {available:false,scope_id:scopeId,success:false,failed:1,status:this.status()};
      return data.operation==='preview'?writer.preview():data.operation==='reset'?writer.reset(data.expected):{success:false,failed:1,status:this.status()};
    },
  };
}
let logger=createLogger();
function initializeLogging(options){logger=createLogger(options);return logger.status();}
function withLogContext(value,run){return context.run(value || {},run);}
function associationLogContext(association,pageId,generation) {
  return {scope_id:association?.service_scope?.scope_id,config_revision:association?.service_scope?.config_revision,
    user_state_revision:association?.service_scope?.user_state_revision,workflow_id:association?.workflow_id,task_id:association?.task_id,
    parent_task_id:association?.parent_task_id,request_id:association?.request_id,service_id:association?.service_id,
    paper_id:association?.paper_id,page_id:pageId,role:association?.role,source_page_id:association?.source_page_id,generation};
}
function errorCode(error) {
  return String(error?.message || '').match(/\bERR_[A-Z0-9_]{1,80}\b/)?.[0]
    || (error?.name==='AbortError'?'canceled':/timed out|timeout/i.test(error?.message || '')?'timeout':'failed');
}
function hostname(url) {try{return new URL(url).hostname;}catch{return undefined;}}
function attachmentCounts(items=[]) {
  const attachments=items.flatMap(item=>Array.isArray(item?.attachments)?item.attachments:[]);
  return {attachment_count:attachments.length,pdf_attachment_count:attachments.filter(attachment=>
    typeof attachment?.mimeType==='string' && attachment.mimeType.split(';')[0].trim().toLowerCase()==='application/pdf').length};
}
module.exports={log:(...args)=>logger.log(...args),initializeLogging,createLogger,withLogContext,associationLogContext,
  diagnosticsStatus:()=>logger.status(),diagnosticsReset:data=>logger.reset(data),setLogLevel:level=>logger.setLevel(level),
  sanitize,errorCode,hostname,attachmentCounts,recoveryEvidence};
