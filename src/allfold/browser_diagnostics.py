"""Bounded browser diagnostics shared by workflows; no Import or Web dependencies."""
from __future__ import annotations

import re


_STAGES = frozenset({'navigation', 'authentication', 'preparation', 'translation', 'parent_save',
                     'wos_dom', 'wos_download', 'attachment'})
_STEPS = frozenset({'request', 'page_load', 'resource_ready', 'resource_filter', 'resource_search',
                    'visit_target', 'verification', 'ready', 'search', 'result', 'exportMenu',
                    'controlReady', 'plainText', 'dialog', 'configure', 'contentReady',
                    'openContent', 'customReady', 'configureCustom', 'verifyCustom', 'saveCustom',
                    'selectContent', 'export', 'arm', 'links', 'download', 'sandbox_load', 'sandbox_init',
                    'translator', 'document_operation', 'dom_observer', 'hidden_iframe', 'oa_resolver',
                    'note_save', 'attachment_create', 'attachment_save', 'recovery_authority', 'page_admission', 'child_page'})
_CODES = frozenset({'failed', 'canceled', 'timeout', 'site_restricted', 'verification_page',
    'content_access_blocked', 'http_error', 'load_failed', 'renderer_gone', 'page_closed',
    'page_probe_unconfirmed', 'article_identity_unconfirmed', 'article_identity_conflict',
    'document_changed', 'navigation_active', 'document_operation_failed', 'doi_mismatch',
    'translator_no_items', 'translator_multiple_items', 'translator_doi_missing', 'translator_invalid_item',
    'institution_credentials_rejected', 'carsi_session_expired', 'resource_not_found',
    'ambiguous_resource', 'unverified_official_page', 'unverified_results_page',
    'resource_request_failed', 'controls_unavailable', 'refresh_unconfirmed',
    'server_unexpected_error', 'control_not_unique', 'control_disabled', 'input_value_mismatch',
    'core_collection_unverified', 'stale_search_results', 'export_range_unverified',
    'download_observer_busy', 'action_expired', 'export_content_unverified', 'unknown_dom_step',
    'dom_step_failed', 'download_interrupted', 'download_cancelled', 'download_incomplete',
    'download_failed', 'download_ambiguous', 'download_not_attributable',
    'authorization_required', 'authorization_denied', 'always_allow_required', 'access_denied', 'server_id_mismatch', 'missing_server_id', 'unsupported_version', 'target_missing', 'target_list_incomplete', 'precondition_required', 'rate_limited', 'connection_lost', 'invalid_target', 'invalid_response', 'invalid_upload_destination', 'upload_failed', 'registration_failed', 'response_too_large', 'unsafe_url', 'object_rejected', 'unattributable_response', 'api_failure', 'key_store_unreadable', 'key_store_write_failed', 'encryption_unavailable', 'conflict', 'invalid_attachment', 'invalid_local_path',
    'openalex_no_pdf', 'openalex_not_found', 'openalex_lookup_failed', 'openalex_authorization_required',
    'openalex_quota', 'openalex_credential_unavailable',
    'no_resolver', 'mime_mismatch', 'empty_response', 'network_error', 'redirect_rejected', 'attachment_rejected',
    'cooldown_budget', 'page_capacity', 'page_capacity_changed'})


def normalize_browser_diagnostic(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    result: dict[str, object] = {}
    for key, allowed in (('stage', _STAGES), ('step', _STEPS), ('code', _CODES)):
        field = value.get(key)
        if isinstance(field, str) and field in allowed:
            result[key] = field
    status = value.get('status')
    if type(status) is int and 100 <= status <= 599:
        result['status'] = status
    net_error = value.get('net_error')
    if isinstance(net_error, str) and re.fullmatch(r'ERR_[A-Z0-9_]{1,80}', net_error):
        result['net_error'] = net_error
    net_code = value.get('net_code')
    if type(net_code) is int and -99999 <= net_code < 0:
        result['net_code'] = net_code
    if result.get('stage') == 'navigation' and result.get('code') == 'site_restricted':
        edet = value.get('imperva_edet')
        if type(edet) is int and 0 <= edet <= 999:
            result['imperva_edet'] = edet
        incident_id = value.get('imperva_incident_id')
        if isinstance(incident_id, str) and re.fullmatch(r'[0-9]{1,32}-[0-9]{1,32}', incident_id):
            result['imperva_incident_id'] = incident_id
    return result or None


def first_attachment_diagnostic(value: object) -> dict[str, object] | None:
    """Prefer a terminal native-write failure; native events retain the bounded sequence.

    A failed transfer is evidence of an attachment problem, not proof of PDF
    persistence or rejection of an already accepted parent.
    """
    if not isinstance(value, list):
        return None
    writes = ('note_save', 'attachment_create', 'attachment_save')
    failures = [failure for failure in value[:20] if isinstance(failure, dict)]
    ordered = [failure for failure in failures if failure.get('phase') in writes]
    ordered.extend(failure for failure in failures if failure.get('phase') not in writes)
    for failure in ordered:
        phase = failure.get('phase')
        diagnostic = normalize_browser_diagnostic({
            'stage':'attachment', 'step':phase if phase in (*writes, 'oa_resolver') else None,
            'code':failure.get('code'), 'status':failure.get('status')})
        if diagnostic and 'code' in diagnostic:
            return diagnostic
    return None


def format_browser_diagnostic(value: object, *, include_pdf_uncertainty: bool = True) -> str:
    diagnostic = normalize_browser_diagnostic(value)
    if diagnostic is None:
        return 'Browser operation failed.'
    if diagnostic.get('stage') == 'attachment':
        reasons = {
            'openalex_no_pdf':'OpenAlex 没有可用的直接公开 PDF',
            'openalex_not_found':'OpenAlex 未收录此 DOI',
            'openalex_lookup_failed':'OpenAlex 查询失败',
            'openalex_authorization_required':'OpenAlex 凭据未被接受',
            'openalex_quota':'OpenAlex 查询额度已用尽',
            'openalex_credential_unavailable':'OpenAlex 本地凭据无法读取',
            'no_resolver':'未找到可用的附件来源', 'mime_mismatch':'返回内容不是预期附件类型',
            'empty_response':'附件响应为空', 'network_error':'附件网络请求失败',
            'redirect_rejected':'附件重定向未被接受', 'attachment_rejected':'附件保存请求未被接受',
            'timeout':'附件操作超时', 'http_error':'附件请求失败',
            'document_changed':'附件来源页面已变化', 'page_closed':'附件来源页面已关闭',
            'canceled':'附件操作已取消', 'unsafe_url':'附件地址未通过安全检查',
            'response_too_large':'附件超过 64 MiB 限制', 'upload_failed':'附件上传未完成',
            'registration_failed':'附件注册未完成', 'invalid_upload_destination':'Zotero 返回的上传地址未通过校验',
            'authorization_required':'Zotero 授权已失效', 'access_denied':'Zotero 拒绝附件写入',
            'server_id_mismatch':'Zotero 实例已变化', 'object_rejected':'Zotero 拒绝附件对象',
            'connection_lost':'Zotero 连接中断',
        }
        message = reasons.get(diagnostic.get('code'), '附件操作未完成')
        if 'status' in diagnostic:
            message += f"（HTTP {diagnostic['status']}）"
        if 'net_error' in diagnostic:
            message += f"（{diagnostic['net_error']}）"
        return message + ('；PDF 是否保存仍未验证。' if include_pdf_uncertainty else '。')
    translation_reasons = {
        'translator_no_items': '官方 Translator 未返回条目。',
        'translator_multiple_items': '官方 Translator 返回多个条目，无法确认唯一父条目。',
        'translator_doi_missing': '官方 Translator 返回的条目缺少有效 DOI。',
        'translator_invalid_item': '元数据缺少有效标题或条目类型。',
        'page_probe_unconfirmed': '网页检查证据不完整，请检查 BROWSER 后重试。',
        'article_identity_unconfirmed': '无法确认当前网页对应目标文章。',
        'article_identity_conflict': '当前网页的文章身份与目标冲突。',
        'document_operation_failed': '无法读取当前网页文档，请检查 BROWSER 后重试。',
    }
    if diagnostic.get('stage') == 'translation' and diagnostic.get('code') in translation_reasons:
        return translation_reasons[diagnostic['code']]
    if diagnostic.get('stage') == 'authentication':
        if diagnostic.get('code') == 'institution_credentials_rejected':
            return '机构认证失败：用户名或密码错误，请在 Settings 检查后重新启动任务。[institution_credentials_rejected]'
        if diagnostic.get('code') == 'carsi_session_expired':
            return 'CARSI 资源访问会话已失效，任务已终止。请在 BROWSER 重新登录后重新运行任务。[carsi_session_expired]'
    stage = {'navigation': 'Page navigation', 'authentication': 'Institution authentication',
             'preparation': 'Service preparation', 'wos_dom': 'WoS page operation',
             'wos_download': 'WoS download', 'translation': 'Official Translator',
             'attachment': 'Attachment', 'parent_save': 'Native parent save'}.get(diagnostic.get('stage'), 'Browser operation')
    reasons = {'canceled': 'operation canceled', 'timeout': 'operation timed out',
              'site_restricted': 'site restricted access', 'verification_page': 'site verification page',
              'content_access_blocked': 'ScienceDirect content access blocked (CPE00001)',
              'http_error': 'HTTP request failed', 'load_failed': 'page load failed',
              'cooldown_budget': 'server cooldown exceeds remaining operation time',
              'page_capacity': 'managed page capacity is unavailable',
              'page_capacity_changed': 'managed page limits changed before creation',
              'document_changed': 'source page changed',
              'doi_mismatch': 'parent DOI did not match',
              'authorization_required': 'Zotero authorization required; choose Always Allow',
              'access_denied': 'Zotero Local API access or Library write denied',
              'server_id_mismatch': 'Zotero instance changed; select the target again',
              'target_missing': 'Zotero Library or Collection is missing',
              'unsupported_version': 'Zotero 10.0.6 or later is required',
              'object_rejected': 'Zotero rejected the exact requested object',
              'unattributable_response': 'Zotero response did not confirm the requested key',
              'connection_lost': 'Zotero connection lost', 'rate_limited': 'Zotero rate limit reached'}
    reason = reasons.get(diagnostic.get('code'), 'operation failed')
    step = f" [{diagnostic['step']}]" if 'step' in diagnostic else ''
    code = f" [{diagnostic['code']}]" if 'code' in diagnostic and diagnostic['code'] not in reasons else ''
    suffix = f" (HTTP {diagnostic['status']})" if 'status' in diagnostic else ''
    if 'net_error' in diagnostic:
        suffix += f" ({diagnostic['net_error']})"
    elif 'net_code' in diagnostic:
        suffix += f" ({diagnostic['net_code']})"
    return f'{stage}{step}: {reason}{code}{suffix}.'
