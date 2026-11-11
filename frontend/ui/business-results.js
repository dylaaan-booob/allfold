// Shared business wording for live results and retained history.
export const providerNames={pubmed:'PubMed',openalex:'OpenAlex',europe_pmc:'Europe PMC',crossref:'Crossref',arxiv:'arXiv',biorxiv:'bioRxiv',medrxiv:'medRxiv',wos:'Web of Science'};
const recoveryLabels=new Map(Object.entries({
  page_refresh:'刷新页面',resource_reentry:'重新访问 CARSI 资源',paper_reopen:'重新打开 Paper',
  pdf_get:'重试 PDF 下载',cooldown_wait:'等待服务冷却',provider_retry:'重试 Provider 请求',completion_recheck:'最终补查',
}));
export function recoveryLabel(action) {return recoveryLabels.get(action) || '';}
export function importOutcomeMessage(outcome,pdf='unverified') {
  if(['exported','confirmed'].includes(outcome))return pdf==='verified failure'
    ? '父条目已导入，PDF 未保存，请在 Zotero 中检查。'
    : '父条目已导入；PDF 未验证，请在 Zotero 中检查。';
  if(outcome==='uncertain')return '保存结果未确认；请先检查 Zotero，勿直接重试。';
  if(outcome==='no_effect')return '本次未保存父条目。';
  if(outcome==='skipped')return '本次跳过。';
  return '导入已停止，请检查任务结果。';
}
export function preparationReason(reason) {
  return ({target_opened:'已观察到目标页面打开，不代表订阅或下载已验证。',
    manual_action_required:'需要在 BROWSER 中手动处理。',ambiguous_resource:'匹配到多个资源，需要人工确认。',
    unverified_official_page:'尚未确认官方资源页面。',resource_not_found:'未找到对应资源。',
    navigation_failed:'目标页面未能打开。',timeout:'页面操作超时。',
    institution_credentials_rejected:'机构认证失败，请在 Login 检查凭据。',
    carsi_session_expired:'CARSI 会话已失效，请重新运行 Login。'})[reason] || '';
}

export function zoteroKeyDetails(keys) {
  if(!keys)return '';
  return [
    keys.parent_key && `Parent ${keys.parent_key}`,
    keys.attachment_keys?.length && `Attachments ${keys.attachment_keys.join(', ')}`,
    keys.note_keys?.length && `Notes ${keys.note_keys.join(', ')}`,
  ].filter(Boolean).join(' · ');
}
