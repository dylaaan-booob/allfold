// Shared business wording for live results and retained history.
export const providerNames={openalex:'OpenAlex',europe_pmc:'Europe PMC',crossref:'Crossref',arxiv:'arXiv',biorxiv:'bioRxiv',medrxiv:'medRxiv',wos:'Web of Science'};
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
    navigation_failed:'目标页面未能打开。',timeout:'页面操作超时，后续队列已停止。',
    institution_credentials_rejected:'机构认证失败，请在 Settings 检查凭据。',
    carsi_session_expired:'CARSI 会话已失效，请在 BROWSER 重新登录。'})[reason] || '';
}
