"""Bounded browser diagnostics shared by workflows; no Import or Web dependencies."""
from __future__ import annotations

import re


_STAGES = frozenset({'navigation', 'authentication', 'preparation', 'translation', 'parent_save',
                     'wos_dom', 'wos_download', 'attachment'})
_STEPS = frozenset({'request', 'page_load', 'resource_ready', 'resource_filter', 'resource_search',
                    'visit_target', 'verification', 'ready', 'search', 'result', 'exportMenu',
                    'controlReady', 'plainText', 'dialog', 'configure', 'contentReady',
                    'selectContent', 'export', 'arm', 'links', 'download', 'sandbox_load', 'sandbox_init',
                    'translator', 'document_operation', 'dom_observer', 'hidden_iframe'})
_CODES = frozenset({'failed', 'canceled', 'timeout', 'site_restricted', 'verification_page',
    'content_access_blocked', 'http_error', 'load_failed', 'renderer_gone', 'page_closed',
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
    'no_resolver', 'mime_mismatch', 'empty_response', 'network_error', 'redirect_rejected', 'attachment_rejected'})


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
    return result or None


def first_attachment_diagnostic(value: object) -> dict[str, object] | None:
    """Retain one reviewed ItemSaver failure; native events retain the bounded sequence.

    A failed transfer is evidence of an attachment problem, not proof of PDF
    persistence or rejection of an already accepted parent.
    """
    if not isinstance(value, list):
        return None
    for failure in value[:20]:
        if not isinstance(failure, dict):
            continue
        diagnostic = normalize_browser_diagnostic({
            'stage':'attachment', 'code':failure.get('code'), 'status':failure.get('status')})
        if diagnostic and 'code' in diagnostic:
            return diagnostic
    return None


def format_browser_diagnostic(value: object) -> str:
    diagnostic = normalize_browser_diagnostic(value)
    if diagnostic is None:
        return 'Browser operation failed.'
    if diagnostic.get('stage') == 'attachment':
        reasons = {
            'no_resolver':'未找到可用的附件来源', 'mime_mismatch':'返回内容不是预期附件类型',
            'empty_response':'附件响应为空', 'network_error':'附件网络请求失败',
            'redirect_rejected':'附件重定向未被接受', 'attachment_rejected':'附件保存请求未被接受',
            'timeout':'附件操作超时', 'http_error':'附件请求失败',
            'document_changed':'附件来源页面已变化', 'page_closed':'附件来源页面已关闭',
            'canceled':'附件操作已取消',
        }
        message = reasons.get(diagnostic.get('code'), '附件操作未完成')
        if 'status' in diagnostic:
            message += f"（HTTP {diagnostic['status']}）"
        if 'net_error' in diagnostic:
            message += f"（{diagnostic['net_error']}）"
        return message + '；PDF 是否保存仍未验证。'
    translation_reasons = {
        'translator_no_items': '官方 Translator 未返回条目。',
        'translator_multiple_items': '官方 Translator 返回多个条目，无法确认唯一父条目。',
        'translator_doi_missing': '官方 Translator 返回的条目缺少有效 DOI。',
        'translator_invalid_item': '元数据缺少有效标题或条目类型。',
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
              'document_changed': 'source page changed',
              'doi_mismatch': 'parent DOI did not match'}
    reason = reasons.get(diagnostic.get('code'), 'operation failed')
    step = f" [{diagnostic['step']}]" if 'step' in diagnostic else ''
    code = f" [{diagnostic['code']}]" if 'code' in diagnostic and diagnostic['code'] not in reasons else ''
    suffix = f" (HTTP {diagnostic['status']})" if 'status' in diagnostic else ''
    if 'net_error' in diagnostic:
        suffix += f" ({diagnostic['net_error']})"
    return f'{stage}{step}: {reason}{code}{suffix}.'
