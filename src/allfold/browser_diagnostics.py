"""Bounded browser diagnostics shared by workflows; no Import or Web dependencies."""
from __future__ import annotations

import re


_STAGES = frozenset({'navigation', 'authentication', 'preparation',
                     'wos_dom', 'wos_download', 'attachment'})
_STEPS = frozenset({'request', 'page_load', 'resource_ready', 'resource_filter', 'resource_search',
                    'visit_target', 'verification', 'ready', 'search', 'result', 'exportMenu',
                    'controlReady', 'plainText', 'dialog', 'configure', 'contentReady',
                    'openContent', 'customReady', 'configureCustom', 'verifyCustom', 'saveCustom',
                    'selectContent', 'export', 'arm', 'links', 'download',
                    'document_operation', 'dom_observer',
                    'recovery_authority', 'page_admission', 'child_page'})
_CODES = frozenset({'failed', 'canceled', 'timeout', 'site_restricted', 'verification_page',
    'content_access_blocked', 'http_error', 'load_failed', 'renderer_gone', 'page_closed',
    'page_probe_unconfirmed', 'article_identity_unconfirmed', 'article_identity_conflict',
    'document_changed', 'navigation_active', 'document_operation_failed', 'doi_mismatch',
    'institution_credentials_rejected', 'carsi_session_expired', 'resource_not_found',
    'ambiguous_resource', 'unverified_official_page', 'unverified_results_page',
    'resource_request_failed', 'controls_unavailable', 'refresh_unconfirmed',
    'server_unexpected_error', 'control_not_unique', 'control_disabled', 'input_value_mismatch',
    'core_collection_unverified', 'stale_search_results', 'export_range_unverified',
    'download_observer_busy', 'action_expired', 'export_content_unverified', 'unknown_dom_step',
    'dom_step_failed', 'download_interrupted', 'download_cancelled', 'download_incomplete',
    'download_failed', 'download_ambiguous', 'download_not_attributable',
    'authorization_required', 'authorization_denied', 'access_denied', 'rate_limited', 'connection_lost',
    'invalid_target', 'invalid_response', 'response_too_large', 'unsafe_url', 'conflict',
    'network_error', 'redirect_rejected',
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


def format_browser_diagnostic(value: object) -> str:
    diagnostic = normalize_browser_diagnostic(value)
    if diagnostic is None:
        return 'Browser operation failed.'
    if diagnostic.get('stage') == 'attachment':
        reasons = {
            'network_error':'附件网络请求失败', 'redirect_rejected':'附件重定向未被接受',
            'timeout':'附件操作超时', 'http_error':'附件请求失败',
            'document_changed':'附件来源页面已变化', 'page_closed':'附件来源页面已关闭',
            'canceled':'附件操作已取消', 'unsafe_url':'附件地址未通过安全检查',
            'response_too_large':'附件响应超过限制',
            'authorization_required':'附件操作需要访问授权', 'access_denied':'附件访问被拒绝',
            'connection_lost':'附件连接中断',
        }
        message = reasons.get(diagnostic.get('code'), '附件操作未完成')
        if 'status' in diagnostic:
            message += f"（HTTP {diagnostic['status']}）"
        if 'net_error' in diagnostic:
            message += f"（{diagnostic['net_error']}）"
        return message + '。'
    if diagnostic.get('stage') == 'authentication':
        if diagnostic.get('code') == 'institution_credentials_rejected':
            return '机构认证失败：用户名或密码错误，请在 Settings 检查后重新启动任务。[institution_credentials_rejected]'
        if diagnostic.get('code') == 'carsi_session_expired':
            return 'CARSI 资源访问会话已失效，任务已终止。请在 BROWSER 重新登录后重新运行任务。[carsi_session_expired]'
    stage = {'navigation': 'Page navigation', 'authentication': 'Institution authentication',
             'preparation': 'Service preparation', 'wos_dom': 'WoS page operation',
             'wos_download': 'WoS download', 'attachment': 'Attachment'}.get(diagnostic.get('stage'), 'Browser operation')
    reasons = {'canceled': 'operation canceled', 'timeout': 'operation timed out',
              'site_restricted': 'site restricted access', 'verification_page': 'site verification page',
              'content_access_blocked': 'ScienceDirect content access blocked (CPE00001)',
              'http_error': 'HTTP request failed', 'load_failed': 'page load failed',
              'cooldown_budget': 'server cooldown exceeds remaining operation time',
              'page_capacity': 'managed page capacity is unavailable',
              'page_capacity_changed': 'managed page limits changed before creation',
              'document_changed': 'source page changed',
              'doi_mismatch': 'article DOI did not match',
              'authorization_required': 'access authorization required',
              'access_denied': 'access denied',
              'connection_lost': 'connection lost', 'rate_limited': 'request rate limit reached'}
    reason = reasons.get(diagnostic.get('code'), 'operation failed')
    step = f" [{diagnostic['step']}]" if 'step' in diagnostic else ''
    code = f" [{diagnostic['code']}]" if 'code' in diagnostic and diagnostic['code'] not in reasons else ''
    suffix = f" (HTTP {diagnostic['status']})" if 'status' in diagnostic else ''
    if 'net_error' in diagnostic:
        suffix += f" ({diagnostic['net_error']})"
    elif 'net_code' in diagnostic:
        suffix += f" ({diagnostic['net_code']})"
    return f'{stage}{step}: {reason}{code}{suffix}.'
