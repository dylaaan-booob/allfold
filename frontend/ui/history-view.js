import {completionLabel,resultLabel} from './run-results.js';
import {importOutcomeMessage,preparationReason,providerNames} from './business-results.js';
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds={run:'Discover',login:'Login',prepare:'Service Preparation',import:'Batch Import',kept:'Import to Zotero',enrich:'网页 Enrich',covers:'Cover Search'};
const outcomes={running:'进行中',completed:'完成',partial:'部分完成',failed:'失败',cancelled:'已取消',
  interrupted:'已中断',uncertain:'结果未确认',needs_attention:'需要处理',opened:'已打开',no_effect:'未产生保存',confirmed:'父条目已确认'};
const metrics={integrated_candidates:'Discovery 候选',integrated_deduplicated:'去重 Paper',work_location_targets:'Work 定位 DOI',completion_targets:'补全 Paper',completion_requests:'补全 HTTP 请求',completion_date_facts_added:'新增日期事实',first_public_recorded:'首版日期已记录',first_public_no_association:'尚无预印本关联',first_public_known_unresolved:'已知首版未确定',first_public_conflict:'首版证据冲突',first_public_failed:'首版查询失败',first_public_cancelled:'首版查询取消',total:'总数',processed:'已处理',retrieved:'检索记录',created:'新增 Paper',updated:'更新',
  pmid_resolution_matched:'已验证 PMID',pmid_resolution_no_match:'无 PMID 匹配',
  pmid_resolution_conflicts:'PMID 冲突',pmid_resolution_failed:'PMID 查询失败',pmid_resolution_cancelled:'PMID 查询取消',
  confirmed:'父条目已确认',exported:'父条目已导入',no_effect:'未保存',uncertain:'结果未确认',failed:'失败',
  skipped:'跳过',cancelled:'取消',completed:'完成',opened:'已打开',needs_attention:'需要处理',eligible:'符合条件',
  matched:'已匹配',downloaded:'已获取',enriched:'已补充',unchanged:'未变更',candidates:'候选',papers:'Paper',
  services:'Service',warnings:'提示',errors:'问题',excluded:'排除',duplicates:'重复',materialized:'已写入',pdf_unverified:'PDF unverified'};
const fieldNames={abstract:'摘要',authors:'作者',publication_date:'出版日期',date_evidence:'日期事件',received:'Received',accepted:'Accepted'};
const reasons={runtime_interrupted:'上次运行未留下可确认的最终结果。',connection_lost:'连接中断，最终结果可能未确认。',
  cancelled:'任务已取消。',partial:'部分工作未完成，请展开查看结果。',failed:'任务未完成，请查看问题并导出诊断。',
  needs_attention:'需要人工处理后再继续。',result_unconfirmed:'保存结果未确认；请先检查 Zotero，勿直接重试。',
  pdf_unverified:'PDF 未验证，请在 Zotero 中检查附件。',no_effect:'本次未保存父条目。',
  configuration_changed:'配置已变化，任务已停止；请检查当前设置。',workspace_changed:'Workspace 已变化，请核对 Paper 与 Zotero。',
  service_unassigned:'尚未匹配到已保存的 Service。',no_candidates:'当前范围没有候选记录。',no_kept_papers:'没有可导入的 Kept Paper。',
  blocked:'任务被安全检查阻止，请检查当前状态。',browser_unavailable:'Electron 未连接，请重新启动应用后检查任务。',
  invalid_configuration:'配置需要修正，请检查 Settings。',write_failed:'本地写入未完成，请检查文件状态。',unknown:'任务需要进一步检查。'};
const time=value=>{const date=new Date(value);return value && Number.isFinite(date.getTime())?date.toLocaleString():'—';};
function reasonText(reason){return preparationReason(reason) || reasons[reason] || '';}
function resultText(result){
  if(result.parent_outcome==='confirmed' && result.reason==='write_failed')
    return 'Zotero 已接受父条目，Paper 状态写入失败；请核对 Workspace 与 Zotero，勿直接重试。';
  if(result.parent_outcome || ['confirmed','no_effect','uncertain','exported'].includes(result.outcome))
    return [...new Set([importOutcomeMessage(result.parent_outcome || result.outcome,result.pdf_outcome),reasonText(result.reason)].filter(Boolean))].join(' ');
  return [outcomes[result.outcome] || '需要检查',reasonText(result.reason)].filter(Boolean).join(' · ');
}
export function historyIntegrityMessage(integrity={}) {
  if(integrity.write_failed || integrity.metadata_missing || integrity.rotated_files || integrity.omitted_events ||
    integrity.evicted_history || integrity.invalid_records || integrity.native?.incomplete || integrity.native?.available===false)
    return '诊断记录可能不完整（容量轮转、记录省略、采集状态未确认或写入失败）；导出包会标明证据限制。';
  return '';
}
export function renderHistoryRecord(record) {
  const details=record.details || {},stats=record.statistics || {};
  const status=record.kind==='run' && details.result_status && !['interrupted','uncertain','cancelled'].includes(record.outcome)
      ? resultLabel(details.result_status):outcomes[record.outcome] || '需要检查';
  const title=record.kind==='run'?`Run ${providerNames[record.provider] || ''}`:kinds[record.kind] || '任务';
  const counts=Object.entries(stats).filter(([key,value])=>metrics[key] && Number.isInteger(value) && (value>0 || ['total','created','confirmed'].includes(key)))
    .map(([key,value])=>`${metrics[key]} ${value}`);
  const messages=[reasonText(details.reason)];
  if(details.batch_scope)messages.push(`执行范围：${details.batch_scope==='service'?details.service_id:'All Services'}`);
  if(record.outcome==='opened')messages.push(preparationReason('target_opened'));
  if(details.pdf_outcome==='unverified')messages.push(reasons.pdf_unverified);
  if(['uncertain','interrupted'].includes(record.outcome) && ['import','kept'].includes(record.kind))messages.push(reasons.result_unconfirmed);
  if(details.sync_warning)messages.push('业务写入已完成，但文件系统同步未确认，请保留备份。');
  const saved=(details.saved_fields || []).filter(field=>fieldNames[field]).map(field=>fieldNames[field]);
  const requested=(details.requested_fields || []).filter(field=>fieldNames[field]).map(field=>fieldNames[field]);
  const rows=(details.results || []).map((item,index)=>`<li><span>${esc(item.paper_id?`Paper ${index+1}`:item.service_id?`Service ${index+1}`:`结果 ${index+1}`)}</span> · ${esc(resultText(item))}<p class="s-help">${esc(item.paper_id || '')}${item.service_id || item.service_assignment?` · ${esc(item.service_id || item.service_assignment)}`:''}</p>${item.diagnostic_message?`<p>${esc(item.diagnostic_message)}</p>`:''}</li>`).join('');
  const serviceCounts=(details.service_statistics || []).map(service=>`<p>${esc(service.service_id || service.service_assignment)} · ${Object.entries(service).filter(([key,value])=>metrics[key] && Number.isInteger(value)).map(([key,value])=>`${esc(metrics[key])} ${value}`).join(' · ')}</p>`).join('');
  const sourceRows=(details.run_sources || []).map(source=>`<li>${esc(providerNames[source.provider] || source.provider)} · ${esc(resultLabel(source.status))} · ${esc(source.candidates ?? '—')} candidates · ${esc(source.created ?? '—')} new / ${esc(source.existing ?? '—')} existing${source.problems?` · ${esc(source.problems)} 来源提示`:''}</li>`).join('');
  const checks=details.wos_checks || {};
  const wosChecks=Number.isInteger(checks.batches)?`<p>WoS Export ${esc(checks.completed_batches ?? 0)}/${esc(checks.batches)} 批次 · ${esc(checks.journal_hints ?? 0)} 期刊清单提示 · ${esc(checks.date_hints ?? 0)} 日期提示 · ${esc(checks.unmatched_records ?? 0)} 未匹配记录</p>`:'';
  return `<article class="history-record" data-history-task="${esc(record.task_id)}">
    <div class="history-record-title"><h3>${esc(title)}</h3><strong>${esc(status)}</strong></div>
    <p class="s-help">${esc(time(record.started_at))} → ${esc(time(record.ended_at))}${record.before_workspace_reset?' · Workspace 重置前的历史任务':''}</p>
    ${counts.length?`<p class="history-counts">${counts.map(esc).join(' · ')}</p>`:''}
    ${[...new Set(messages.filter(Boolean))].map(message=>`<p class="history-impact">${esc(message)}</p>`).join('')}
    <details><summary>业务详情</summary>
      ${requested.length?`<p>请求补充：${requested.map(esc).join('、')}</p>`:''}
      ${saved.length?`<p>已补充：${saved.map(esc).join('、')}</p>`:''}
      ${record.diagnostic_message?`<p>${esc(record.diagnostic_message)}</p>`:''}
      ${record.kind==='run' && details.completion_status?`<p>Discovery · ${esc(resultLabel(details.discovery_status || 'unknown'))} / Run metadata completion · ${esc(completionLabel(details.completion_status,stats.completion_targets))}</p>`:''}
      ${sourceRows?`<ul>${sourceRows}</ul>`:''}${wosChecks}
      ${serviceCounts}${details.omitted_services?'<p>更多 Service 汇总已省略。</p>':''}
      ${rows?`<ol>${rows}</ol>`:''}${details.omitted_results?'<p>更多结果已省略；请结合诊断包中的保留证据。</p>':''}
      <p class="s-help">任务标识 ${esc(record.task_id)}</p>
    </details><button type="button" class="s-button" data-history-export="${esc(record.task_id)}">导出本次诊断</button>
  </article>`;
}
export function filterHistoryRecords(records,serviceId) {
  return !serviceId?records:records.filter(record=>record.details?.service_id===serviceId ||
    [...(record.details?.service_statistics || []),...(record.details?.results || [])].some(item=>item.service_id===serviceId));
}
export async function requestDiagnosticBundle(taskId,csrf,fetcher=fetch) {
  const response=await fetcher('/api/diagnostics/export',{method:'POST',cache:'no-store',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({csrf_token:csrf,...(taskId?{task_id:taskId}:{})})});
  if(!response.ok || !response.headers.get('Content-Type')?.startsWith('application/zip')) {
    let data;try {data=await response.json();}catch {data={};}
    throw new Error(data.message || `诊断导出失败 (${response.status})`);
  }
  return response.blob();
}
export function resetImpact(scope,plan={}) {
  return scope==='logs'
    ? `将清除当前配置的 ${plan.history_records ?? 0} 条运行历史及技术诊断。Workspace、配置、Journals/Services、Zotero、浏览器登录与已下载的诊断包保留。活动任务期间无法清除。`
    : `将永久删除 ${plan.workspace || '已保存 Workspace'} 内的 Paper、Author、索引和最近 Run 快照。独立日志保留，旧任务将标记为重置前历史；配置、Zotero 与浏览器登录保留。`;
}
