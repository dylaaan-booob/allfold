"""Bounded recovery observations shared by Native and Provider results."""
import json
from pathlib import Path
import re
import threading


SCHEMA = json.loads(Path(__file__).with_name('diagnostic_schema.json').read_text())
RECOVERY_ACTIONS = frozenset(SCHEMA['fields']['recovery_action']['enum'])
_EVIDENCE_FIELDS = ('stage', 'step', 'code', 'status', 'net_code', 'net_error', 'failure_kind',
                    'transport_error', 'dispatch_outcome', 'recovery_stop', 'page_id', 'source_page_id')
_OUTCOMES = {
    'recovery_scheduled': 'stopped',
    'recovery_succeeded': 'recovered',
    'recovery_exhausted': 'exhausted',
    'service_cooldown_started': 'stopped',
    'service_cooldown_ended': 'recovered',
}
_PROGRESS_MESSAGES = {
    'page_refresh': '正在刷新页面',
    'resource_reentry': '正在重新访问 CARSI 资源',
    'paper_reopen': '正在重新打开 Paper',
    'pdf_get': '正在重试 PDF 下载',
    'cooldown_wait': '正在等待服务冷却',
}


def field_valid(field, rule):
    kind = rule['type']
    if kind == 'integer':
        return type(field) is int and rule['minimum'] <= field <= rule['maximum']
    if kind == 'boolean':
        return type(field) is bool
    if not isinstance(field, str):
        return False
    if 'enum' in rule:
        return field in rule['enum']
    return len(field) <= 128 and re.fullmatch(rule['pattern'], field) is not None


def _evidence(value):
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in _EVIDENCE_FIELDS if field_valid(value.get(key), SCHEMA['fields'][key])}


def normalize_recovery_action(value):
    return value if isinstance(value, str) and value in RECOVERY_ACTIONS else None


def recovery_progress_message(value):
    return _PROGRESS_MESSAGES.get(normalize_recovery_action(value))


def normalize_recovery(value):
    if not isinstance(value, list):
        return []
    result = {}
    for entry in value[:len(RECOVERY_ACTIONS)]:
        if not isinstance(entry, dict):
            continue
        action, count, outcome = normalize_recovery_action(entry.get('recovery_action')), entry.get('count'), entry.get('outcome')
        if (action and type(count) is int and 0 <= count <= 1_000_000
                and isinstance(outcome, str) and outcome in _OUTCOMES.values()):
            result.setdefault(action, dict(recovery_action=action, count=count, outcome=outcome,
                first=_evidence(entry.get('first')), last=_evidence(entry.get('last'))))
    return list(result.values())


class RecoverySummary:
    """An operation's evidence, accumulated independently of the log writer."""

    def __init__(self):
        self._lock = threading.Lock()
        self._entries = {}

    def record(self, event, details):
        action = normalize_recovery_action(details.get('recovery_action'))
        outcome = _OUTCOMES.get(event)
        if not action or not outcome:
            return
        evidence = _evidence(details)
        with self._lock:
            previous = self._entries.get(action)
            count = min(1_000_000, (previous['count'] if previous else 0) + (outcome == 'stopped'))
            self._entries[action] = dict(recovery_action=action, count=count, outcome=outcome,
                first=previous['first'] if previous else evidence, last=evidence)

    def snapshot(self):
        with self._lock:
            return normalize_recovery(list(self._entries.values()))
