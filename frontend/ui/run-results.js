// Shared result wording and rendering for LAST RUN and completion notices.
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const count=value=>Number.isInteger(value)?String(value):'未知';
const labels={
  completed:'完成',completed_with_notices:'完成，有提示',incomplete:'完成，检索或补全不完整',
  capture_issues:'完成，Paper 保存存在问题',failed:'运行失败',cancelled:'已取消',
  complete:'检索完整',empty:'当前范围无记录',partial:'检索不完整',
  unknown:'证据不足',observed:'已发现导出记录',
  hint:'本地来源清单提示',resolved:'已解析',not_found:'未找到',request_failed:'请求失败',
  local_not_listed:'未列入本地 WoS 来源清单，仍参与检索',
  completion_targets:'Completion targets',completion_requests:'Completion HTTP requests',
  completion_date_facts_added:'Added date facts',first_public_recorded:'First public recorded',
  first_public_no_association:'No preprint association',first_public_known_unresolved:'Unverified preprint',
  first_public_conflict:'First public conflicts',first_public_failed:'First public failed',first_public_cancelled:'First public cancelled',
  work_location_targets:'DOI Work targets',completion:'Run metadata completion',work_location:'Work location',
  integrated_candidates:'Candidates',integrated_deduplicated:'Distinct Papers',skipped:'未执行',
  returned_records:'Returned records',matched_journal_records:'Matched Journal records',issn_queries:'ISSN queries',
  unmatched_journal_records:'Unmatched Journal records',eligible_records:'Eligible records',
  no_doi:'Without DOI',conflicts:'Identity conflicts',write_failures:'Write failures',search_total:'Search results',
  missing_doi:'Missing DOI',existing_or_blocked_doi:'Existing or blocked DOI',
  unmapped_or_ambiguous_journal:'Unmapped or ambiguous Journal',missing_title:'Missing title',doi_conflict:'DOI conflict',
  discovery:'检索',retrieval:'检索',identity:'身份',paper_write:'Paper 保存',capture:'身份与保存',snapshot_write:'结果保存',
  notice:'提示',exclusion:'正常排除',configuration:'配置',runtime:'运行',
  PD_PY_year_conflict:'出版日期与出版年份不一致',unusable_PD:'出版日期无法解析',date_unavailable:'无法确定出版日期',
};
const label=value=>labels[value] || value;
export const resultLabel=label;
const identifierProblem=item=>!['resolved','complete','empty','unknown'].includes(item.status);
const journalProblem=journal=>!['complete','empty','observed','unknown'].includes(journal.status) || journal.identifiers.some(identifierProblem);

export function resultHeadline(result) {
  if(!result || result.availability!=='available')return '暂无已保存结果';
  return `${label(result.status)} · ${count(result.created_papers)} new papers · ${count(result.existing_papers)} already saved`;
}

export function resultMessages(result) {
  if(!result || result.availability!=='available')return [];
  const messages=[];
  if(['partial','failed'].includes(result.coverage_status))messages.push(`检索或补全不完整，详情见 ${result.journals.length?'Journal Coverage 与 ':''}Provider Details。`);
  const problems=result.journals.filter(journalProblem),hints=problems.filter(j=>j.status==='hint');
  if(problems.length>hints.length)messages.push(`${problems.length-hints.length} 本期刊有标识或检索提示。`);
  if(hints.length)messages.push(`${hints.length} 本期刊有本地 WoS 来源清单提示，仍参与检索。`);
  const categories=new Set(result.issues.filter(i=>i.severity==='error').map(i=>i.category));
  for(const category of ['identity','paper_write','capture'])if(categories.has(category))messages.push(`${label(category)}存在问题，请展开诊断。`);
  if(result.statistics.unmatched_journal_records>0)messages.push(`${count(result.statistics.unmatched_journal_records)} 条导出记录无法匹配已配置 Journal。`);
  for(const issue of result.issues)if(['configuration','runtime'].includes(issue.category))messages.push(issue.message);
  if(result.issues.some(i=>i.category==='snapshot_write'))messages.push('最近结果未保存；重启后无法恢复此次结果。');
  return messages;
}

function metrics(values,keepZero=[]) {
  const entries=Object.entries(values || {}).filter(([key,value])=>
    Number.isInteger(value) && (value!==0 || keepZero.includes(key)));
  return entries.length?`<dl class="s-run-metrics">${entries.map(([key,value])=>`<div><dt>${esc(label(key))}</dt><dd>${esc(count(value))}</dd></div>`).join('')}</dl>`:'';
}
function metricSection(title,values) {
  const content=metrics(values);
  return content?`<h4>${title}</h4>${content}`:'';
}
function wosDiagnostic(message) {
  const known={batch_count_mismatch:'导出记录数与预期不一致',duplicate_UT_in_query:'同一次检索中出现重复的 WoS UT',
    record_missing_ER:'导出记录缺少结束标记 ER',
    missing_EF:'导出文件缺少结束标记 EF',invalid_tagged_header:'导出文件头无效',
    content_after_EF:'文件结束标记后仍有内容',orphan_ER:'出现无对应记录的结束标记 ER'};
  let match=message.match(/^(\d+)-(\d+): (.+)$/);
  if(match)return `批次 ${match[1]}–${match[2]}：${wosDiagnostic(match[3])}`;
  match=message.match(/^record_(\d+)_unusable$/);
  if(match)return `第 ${match[1]} 条记录无法使用`;
  match=message.match(/^export_read_failed:(.+)$/);
  if(match)return `无法读取导出文件（${match[1]}）`;
  match=message.match(/^(orphan_continuation|invalid_line|field_outside_record):(\d+)$/);
  if(match)return `第 ${match[2]} 行：${{orphan_continuation:'续行没有对应字段',invalid_line:'导出格式无效',field_outside_record:'字段不在记录内'}[match[1]]}`;
  return known[message] || message;
}
function journalRow(journal,id) {
  return `<li><strong>${esc(journal.name)}</strong><span>${esc(label(journal.status))}${journal.records===null?'':` · ${count(journal.records)} records`}</span>
    ${journal.identifiers.length?`<details data-result-detail="${esc(id)}"><summary>ISSN / eISSN</summary><ul>${journal.identifiers.map(item=>`<li><span>${esc(item.issn)} · ${esc(label(item.status))}${item.records===null?'':` · ${count(item.records)} records`}${item.source_id?` · ${esc(item.source_id)}`:''}</span>${item.message?`<p>${esc(item.message)}</p>`:''}</li>`).join('')}</ul></details>`:''}</li>`;
}

export function renderRunResult(result,{compact=false,id='' }={}) {
  if(!result || result.availability==='not_found')return '<p class="s-help">尚无已保存的运行结果。</p>';
  if(result.availability==='unsupported')return '<p class="s-help">旧版运行记录，请重新运行生成结果。</p>';
  if(result.availability==='invalid')return `<p class="s-field-error">无法读取最近结果：${esc(result.error)}</p>`;
  const dates=result.resolved_date_range;
  const finished=result.finished_at?new Date(result.finished_at).toLocaleString():'完成时间未知';
  const header=`<p class="s-run-outcome" data-result-status="${esc(result.status)}"><span>${esc(label(result.status))}</span><span class="s-run-counts"><span>${esc(count(result.created_papers))} new papers</span><span>${esc(count(result.existing_papers))} already saved</span></span></p>
    <p class="s-help s-run-timing"><span>${esc(finished)}</span>${dates?`<span class="s-run-date-range"><span>${esc(dates.from_date)}</span><span>至 ${esc(dates.to_date)}</span></span>`:''}</p>`;
  const messages=resultMessages(result);
  const impact=messages.length?`<ul class="s-run-impact">${messages.map(message=>`<li>${esc(message)}</li>`).join('')}</ul>`:'';
  if(compact && result.provider!=='integrated')return header+impact;
  const problems=result.journals.filter(journalProblem),normal=result.journals.filter(j=>!journalProblem(j));
  const coverage=result.journals.length?`<div class="s-run-coverage"><h4>Journal Coverage</h4><p class="s-help">${esc(label(result.coverage_status))}</p>
    <ul class="s-run-journals">${problems.map(j=>journalRow(j,`${id}:journal:${j.key}`)).join('')}</ul>
    ${normal.length?`<details data-result-detail="${esc(id)}:normal"><summary>${normal.some(j=>j.status==='unknown')?'其他期刊证据':'正常覆盖 / 当前范围无记录'} (${normal.length})</summary><ul class="s-run-journals">${normal.map(j=>journalRow(j,`${id}:journal:${j.key}`)).join('')}</ul></details>`:''}</div>`:'';
  const details=result.details,stats={...result.statistics};
  if('search_total' in details)stats.search_total=details.search_total;
  const batches=(details.batches || []).map(batch=>`<li>Export ${count(batch.first)}–${count(batch.last)} · Expected ${count(batch.expected)} / Exported ${count(batch.exported)} / Eligible ${count(batch.eligible)} · ${batch.complete?'完整':'不完整'}${batch.issues?.length?`<p>${batch.issues.map(message=>esc(wosDiagnostic(message))).join(' · ')}</p>`:''}</li>`).join('');
  const warnings=(details.date_warnings || []).map(item=>({...item,reasons:(item.reasons || []).filter(reason=>!['EA_fallback','year_only'].includes(reason))}))
    .filter(item=>item.reasons.length).map(item=>`<li>Record ${count(item.record_number)} · ${esc(item.doi || item.ut || '')} · ${item.reasons.map(reason=>esc(label(reason))).join(' · ')}</li>`).join('');
  const issues=result.issues.filter(i=>i.category!=='exclusion').map(issue=>`<li><strong>${esc(label(issue.category))}</strong> · ${esc(result.provider==='wos'?wosDiagnostic(issue.message):issue.message)}${issue.issn?` · ${esc(issue.issn)}`:''}</li>`).join('');
  const providerRuns=(details.provider_runs || []).map(run=>`<li><strong>${esc(run.provider)} · ${esc(run.source)}</strong> · ${esc(label(run.status))} · ${count(run.candidates)} candidates / ${count(run.retained)} retained · ${count(run.created)} new / ${count(run.existing)} existing${run.limitations?.length?`<p>${run.limitations.map(esc).join(' · ')}</p>`:''}</li>`).join('');
  const phases=result.provider==='integrated'?`<p class="s-run-phases">Discovery · ${esc(label(details.discovery_status || 'unknown'))} / Run metadata completion · ${esc(({complete:'完成',empty:'无需补全',partial:'部分完成',failed:'失败',cancelled:'已取消'})[details.completion_status] || '未知')}</p>`:'';
  return header+impact+phases+coverage+`<details class="s-run-provider-details" data-result-detail="${esc(id)}:provider"><summary>Provider Details</summary>${metrics(stats,['integrated_candidates','integrated_deduplicated','returned_records','eligible_records','search_total','conflicts'])}
    ${providerRuns?`<ul>${providerRuns}</ul>`:''}
    ${metricSection('正常排除',details.skipped)}
    ${metricSection('记录诊断',details.exclusions)}
    ${batches?`<h4>Export batches</h4><ul>${batches}</ul>`:''}${warnings?`<h4>Publication date hints</h4><ul>${warnings}</ul>`:''}
    ${issues?`<h4>诊断与提示</h4><ul>${issues}</ul>`:''}</details>`;
}
