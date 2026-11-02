'use strict';
const levels={debug:10,info:20,warn:30,error:40};
const fields=new Set(['request_id','action','page_id','stage','step','outcome','parent','pdf',
  'metadata_source','attachment_phase','translator','translator_id','item_count','attachment_count','pdf_attachment_count',
  'error_kind','error_name','api_name','first_doi','content_type','response_bytes','challenge','transport_code','net_error',
  'duration_ms','waiting','host','resource_type','code','status','method','port','reason','exit_code','generation','attempt']);
function log(level,event,details={}) {
  const threshold=levels[(process.env.ALLFOLD_LOG_LEVEL || 'info').toLowerCase()] || levels.info;
  if(levels[level]<threshold)return;
  const record={time:new Date().toISOString(),level,event};
  for(const [key,value] of Object.entries(details))
    if(fields.has(key) && value!=null && ['string','number','boolean'].includes(typeof value))
      record[key]=typeof value==='string'?value.slice(0,200):value;
  process.stderr.write(JSON.stringify(record)+'\n');
}
function errorCode(error) {
  return String(error?.message || '').match(/\bERR_[A-Z0-9_]+\b/)?.[0]
    || (error?.name==='AbortError'?'canceled':/timed out|timeout/i.test(error?.message || '')?'timeout':'failed');
}
function hostname(url) {
  try {return new URL(url).hostname;} catch {return undefined;}
}
function attachmentCounts(items=[]) {
  const attachments=items.flatMap(item=>Array.isArray(item?.attachments)?item.attachments:[]);
  return {attachment_count:attachments.length,pdf_attachment_count:attachments.filter(attachment=>
    typeof attachment?.mimeType==='string' && attachment.mimeType.split(';')[0].trim().toLowerCase()==='application/pdf').length};
}
module.exports={log,errorCode,hostname,attachmentCounts};
