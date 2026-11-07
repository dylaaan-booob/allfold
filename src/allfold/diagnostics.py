"""Run observations and bounded local evidence; neither determines business outcomes."""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import threading
from uuid import UUID, uuid4
import zipfile

from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.persistence.safe_write import _open_directory_nofollow
from allfold.persistence.user_state import application_data_dir


# Durable diagnostics are deliberately independent of the Paper/Workspace state.
# Only coordinators may declare a terminal business outcome.

KINDS = frozenset({'run', 'prepare', 'import', 'kept', 'enrich', 'api_completion', 'covers'})
PROVIDERS = frozenset({'integrated', 'openalex', 'crossref', 'europe_pmc', 'arxiv', 'biorxiv', 'medrxiv', 'wos'})
OUTCOMES = frozenset({'completed', 'partial', 'failed', 'cancelled', 'interrupted', 'uncertain',
                      'needs_attention', 'opened', 'no_effect', 'confirmed'})
STATISTICS = frozenset({'retrieved', 'created', 'updated', 'total', 'processed', 'failed', 'skipped',
    'confirmed', 'exported', 'no_effect', 'uncertain', 'cancelled', 'completed', 'opened',
    'needs_attention', 'eligible', 'matched', 'downloaded', 'enriched', 'unchanged', 'candidates',
    'no_match', 'lookup_failed', 'identity_mismatch', 'evidence', 'papers', 'services', 'warnings', 'errors', 'excluded', 'duplicates', 'materialized', 'pdf_unverified'})
REASONS = frozenset({'runtime_interrupted', 'connection_lost', 'cancelled', 'partial', 'failed',
    'needs_attention', 'result_unconfirmed', 'pdf_unverified', 'no_effect', 'configuration_changed',
    'workspace_changed', 'service_unassigned', 'no_candidates', 'no_kept_papers', 'blocked',
    'browser_unavailable', 'invalid_configuration', 'write_failed', 'unknown',
    'target_opened', 'manual_action_required', 'ambiguous_resource', 'unverified_official_page',
    'resource_not_found', 'navigation_failed', 'timeout', 'institution_credentials_rejected', 'carsi_session_expired'})
IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
SCOPE = re.compile(r'[a-f0-9]{64}\Z')
LEVELS = frozenset({'debug', 'info', 'warn', 'error'})
_SCHEMA = json.loads(Path(__file__).with_name('diagnostic_schema.json').read_text())



def _now():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _identifier(value):
    return isinstance(value, str) and bool(IDENTIFIER.fullmatch(value))


def _enum(value, allowed):
    return isinstance(value, str) and value in allowed


def _counts(value):
    if not isinstance(value, dict):
        return {}
    return {k: v for k, v in value.items() if k in STATISTICS and type(v) is int and 0 <= v <= 1_000_000_000}


def _details(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    if _enum(value.get('batch_scope'), {'all', 'service'}):
        result['batch_scope'] = value['batch_scope']
    service = value.get('service_id')
    if isinstance(service, str) and re.fullmatch(r'svc_[a-f0-9]{32}', service):
        result['service_id'] = service
    for key in ('config_revision', 'user_state_revision'):
        if isinstance(value.get(key), str) and re.fullmatch(r'[a-f0-9]{64}', value[key]):
            result[key] = value[key]
    for key in ('submitted', 'result_known', 'pdf_verified', 'requires_attention', 'blocked', 'sync_warning'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    if _enum(value.get('reason'), REASONS):
        result['reason'] = value['reason']
    if _enum(value.get('parent_outcome'), {'confirmed', 'no_effect', 'uncertain'}):
        result['parent_outcome'] = value['parent_outcome']
    if _enum(value.get('pdf_outcome'), {'confirmed', 'failed', 'unverified', 'not_requested', 'uncertain'}):
        result['pdf_outcome'] = value['pdf_outcome']
    for key, allowed in (('result_status', {'completed', 'completed_with_notices', 'incomplete', 'capture_issues', 'failed', 'cancelled'}),
                         ('coverage_status', {'complete', 'empty', 'partial', 'failed', 'unavailable', 'unknown'}),
                         ('batch_phase', {'idle', 'running', 'completed', 'stopped', 'paused', 'blocked'}),
                         ('mode', {'full', 'import_only'})):
        if _enum(value.get(key), allowed):
            result[key] = value[key]
    source_runs = value.get('run_sources')
    if isinstance(source_runs, list):
        sources = []
        for item in source_runs:
            if not isinstance(item, dict) or not _enum(item.get('provider'), {'wos','openalex','europe_pmc'}):
                continue
            if not _enum(item.get('status'), {'complete','empty','partial','failed','cancelled','skipped'}):
                continue
            safe = {key:item[key] for key in ('provider','status')}
            safe.update({key:item[key] for key in ('candidates','created','existing','problems')
                if type(item.get(key)) is int and 0 <= item[key] <= 1_000_000_000})
            if not any(source['provider']==safe['provider'] for source in sources):
                sources.append(safe)
        result['run_sources'] = sources
    checks = value.get('wos_checks')
    if isinstance(checks, dict):
        result['wos_checks'] = {key:checks[key] for key in ('batches','completed_batches','journal_hints','date_hints','unmatched_records')
            if type(checks.get(key)) is int and 0 <= checks[key] <= 1_000_000_000}
    for key in ('saved_fields', 'requested_fields'):
        fields = value.get(key)
        if isinstance(fields, list):
            result[key] = sorted({field for field in fields if _enum(field, {'abstract', 'authors', 'publication_date', 'date_evidence', 'first_public_at', 'sources', 'author_keywords', 'journal', 'conference', 'conference_id', 'publication_type'})})
    service_statistics = value.get('service_statistics')
    if isinstance(service_statistics, list):
        summaries = []
        for item in service_statistics[:100]:
            if not isinstance(item, dict):
                continue
            service = item.get('service_id')
            if isinstance(service, str) and re.fullmatch(r'svc_[a-f0-9]{32}', service):
                safe = {'service_id': service}
            elif _enum(item.get('service_assignment'), {'unassigned', 'ambiguous'}):
                safe = {'service_assignment': item['service_assignment']}
            else:
                continue
            summaries.append({**safe, **_counts(item)})
        result['service_statistics'] = summaries
        omitted = value.get('omitted_services', 0)
        omitted = omitted if type(omitted) is int and 0 <= omitted <= 1_000_000_000 else 0
        result['omitted_services'] = min(1_000_000_000, omitted + max(0, len(service_statistics) - 100))
    items = value.get('results')
    if isinstance(items, list):
        results = []
        for item in items[:100]:
            if not isinstance(item, dict) or not _enum(item.get('outcome'), OUTCOMES):
                continue
            safe = {'outcome': item['outcome']}
            service = item.get('service_id')
            if isinstance(service, str) and re.fullmatch(r'svc_[a-f0-9]{32}', service):
                safe['service_id'] = service
            if _enum(item.get('service_assignment'), {'assigned', 'unassigned', 'ambiguous'}):
                safe['service_assignment'] = item['service_assignment']
            paper = item.get('paper_id')
            if isinstance(paper, str) and re.fullmatch(r'[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}', paper):
                safe['paper_id'] = paper.lower()
            for key in ('parent_outcome', 'pdf_outcome', 'reason'):
                allowed = {'parent_outcome': {'confirmed', 'no_effect', 'uncertain'},
                    'pdf_outcome': {'confirmed', 'failed', 'unverified', 'not_requested', 'uncertain'},
                    'reason': REASONS}[key]
                if _enum(item.get(key), allowed):
                    safe[key] = item[key]
            diagnostic = normalize_browser_diagnostic(item.get('diagnostic'))
            if diagnostic:
                safe['diagnostic'] = diagnostic
            results.append(safe)
        result['results'] = results
        omitted = value.get('omitted_results', 0)
        omitted = omitted if type(omitted) is int and 0 <= omitted <= 1_000_000_000 else 0
        result['omitted_results'] = min(1_000_000_000, omitted + max(0, len(items) - 100))
    return result


def _time(value):
    if not isinstance(value, str) or len(value) > 32:
        return False
    try:
        return value.endswith('Z') and datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is not None
    except ValueError:
        return False


def validate_event(value):
    """Independent data-schema validation for each persisted/exported field."""
    if not isinstance(value, dict):
        return None
    result = {}
    for key, rule in _SCHEMA['fields'].items():
        field = value.get(key)
        kind = rule['type']
        valid = ((kind == 'integer' and type(field) is int)
                 or (kind == 'boolean' and type(field) is bool)
                 or (kind == 'string' and isinstance(field, str)))
        if not valid:
            continue
        if 'enum' in rule and field not in rule['enum']:
            continue
        if 'pattern' in rule and (len(field) > 128 or re.fullmatch(rule['pattern'], field) is None):
            continue
        if kind == 'integer' and not rule['minimum'] <= field <= rule['maximum']:
            continue
        result[key] = field
    if any(key not in result for key in _SCHEMA['required']):
        return None
    if not _time(result['time']):
        return None
    if any(key not in result for key in _SCHEMA['events_require'].get(result['event'], ())):
        return None
    return result


class DiagnosticRefused(RuntimeError):
    """The managed diagnostic target cannot be safely established."""


class DiagnosticStore:
    """One configuration's bounded, privacy-filtered evidence, never retry authority."""

    def __init__(self, config_path, *, root=None, runtime_id=None, max_file_bytes=1024 * 1024,
                 max_files=4, max_history=200, max_history_bytes=1024 * 1024,
                 max_export_bytes=4 * 1024 * 1024, level='info'):
        self.config_path = Path(config_path).resolve()
        self.scope_id = hashlib.sha256(str(self.config_path).encode()).hexdigest()
        supplied_runtime = runtime_id or os.environ.get('ALLFOLD_RUNTIME_ID')
        self.runtime_id = supplied_runtime if _identifier(supplied_runtime) else uuid4().hex
        self.root = Path(root or os.environ.get('ALLFOLD_DIAGNOSTICS_ROOT') or
                         application_data_dir(self.config_path) / 'diagnostics').absolute()
        self.max_file_bytes = max(1024, min(int(max_file_bytes), 1024 * 1024))
        self.max_files = max(1, min(int(max_files), 4))
        self.max_history = max(1, min(int(max_history), 200))
        self.max_history_bytes = max(2048, min(int(max_history_bytes), 1024 * 1024))
        self.max_export_bytes = max(1024, min(int(max_export_bytes), 4 * 1024 * 1024))
        from allfold.logging_setup import effective_log_level
        self.level = effective_log_level(level).lower().replace('warning', 'warn')
        self._lock = threading.RLock()
        self._identities = None
        self._files = {}
        self._records = []
        self._generation = 0
        self._integrity = {'write_failed': False, 'rotated_files': 0, 'omitted_events': 0,
                           'evicted_history': 0, 'invalid_records': 0, 'history_recovered': False,
                           'metadata_missing': False}
        self._reset_nonce = None
        self._native_integrity = {'available': False, 'incomplete': True, 'status_known': False}
        try:
            self._initialize()
            self._recover()
        except (OSError, ValueError, DiagnosticRefused):
            self._failure()
        self.event('app_started')

    def _failure(self):
        self._integrity['write_failed'] = True
        print('Allfold diagnostics: local recording incomplete; diagnostic write/read failed.', file=sys.stderr)

    @contextmanager
    def _directory(self):
        descriptors = []
        try:
            names = (None, 'scopes', self.scope_id, 'python')
            identities = []
            for index, name in enumerate(names):
                descriptor = (_open_directory_nofollow(self.root) if name is None else
                    os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptors[-1]))
                descriptors.append(descriptor)
                info = os.fstat(descriptor)
                identity = info.st_dev, info.st_ino
                identities.append(identity)
                if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
                    raise DiagnosticRefused('Diagnostic directory is not private')
                if self._identities is not None and identity != self._identities[index]:
                    raise DiagnosticRefused('Diagnostic directory identity changed')
            if self._identities is None:
                self._identities = identities
            yield descriptors[-1]
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    def _initialize(self):
        for path in (self.root, self.root / 'scopes', self.root / 'scopes' / self.scope_id,
                     self.root / 'scopes' / self.scope_id / 'python'):
            descriptor = _open_directory_nofollow(path, create=True)
            try:
                if os.fstat(descriptor).st_uid != os.getuid():
                    raise DiagnosticRefused('Diagnostic directory has another owner')
                os.fchmod(descriptor, 0o700)
            finally:
                os.close(descriptor)
        with self._directory() as directory:
            for name in ('history.json', 'integrity.json', 'events.jsonl',
                         'events.1.jsonl', 'events.2.jsonl', 'events.3.jsonl'):
                try:
                    self._files[name] = self._file_identity(directory, name)
                except FileNotFoundError:
                    pass

    @staticmethod
    def _read(directory, name, limit):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                    or info.st_size > limit):
                raise DiagnosticRefused('Unsafe or oversized diagnostic file')
            with os.fdopen(descriptor, 'rb', closefd=False) as stream:
                return stream.read(limit + 1)
        finally:
            os.close(descriptor)

    @staticmethod
    def _file_identity(directory, name):
        info = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
            raise DiagnosticRefused('Unsafe diagnostic file')
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

    def _atomic(self, directory, name, payload):
        try:
            expected = self._file_identity(directory, name)
        except FileNotFoundError:
            expected = None
        if self._files.get(name) != expected:
            raise DiagnosticRefused('Managed diagnostic file was replaced')
        temporary = '.write-' + secrets.token_hex(12)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            with os.fdopen(descriptor, 'wb', closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                actual = self._file_identity(directory, name)
            except FileNotFoundError:
                actual = None
            if expected != actual:
                raise DiagnosticRefused('Diagnostic file changed')
            os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
            self._files[name] = self._file_identity(directory, name)
            os.fsync(directory)
        finally:
            os.close(descriptor)
            try:
                os.unlink(temporary, dir_fd=directory)
            except FileNotFoundError:
                pass

    def _append(self, directory, line):
        expected = self._files.get('events.jsonl')
        descriptor = os.open('events.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW,
                             0o600, dir_fd=directory)
        try:
            info = os.fstat(descriptor)
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid()
                    or (expected is not None and actual != expected)
                    or (expected is None and info.st_size != 0)):
                raise DiagnosticRefused('Diagnostic file identity changed')
            os.fchmod(descriptor, 0o600)
            remaining = line
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError('Incomplete diagnostic write')
                remaining = remaining[written:]
            os.fsync(descriptor)
            info = os.fstat(descriptor)
            actual = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
            if self._file_identity(directory, 'events.jsonl') != actual:
                raise DiagnosticRefused('Diagnostic file changed during append')
            self._files['events.jsonl'] = actual
        finally:
            os.close(descriptor)

    def _record(self, value):
        if (not isinstance(value, dict) or not _enum(value.get('kind'), KINDS)
                or not _identifier(value.get('task_id')) or not _identifier(value.get('workflow_id'))
                or not _identifier(value.get('runtime_id')) or not _time(value.get('started_at'))
                or not _enum(value.get('outcome'), OUTCOMES | {'running'})
                or type(value.get('workspace_generation')) is not int
                or not 0 <= value['workspace_generation'] <= 1_000_000_000):
            return None
        result = {k: value[k] for k in ('kind', 'task_id', 'workflow_id', 'runtime_id',
                  'started_at', 'outcome', 'workspace_generation')}
        if _enum(value.get('provider'), PROVIDERS):
            result['provider'] = value['provider']
        if _identifier(value.get('parent_task_id')):
            result['parent_task_id'] = value['parent_task_id']
        if _time(value.get('ended_at')):
            result['ended_at'] = value['ended_at']
        if _time(value.get('recovered_at')):
            result['recovered_at'] = value['recovered_at']
        result['statistics'] = _counts(value.get('statistics'))
        result['details'] = _details(value.get('details'))
        diagnostic = normalize_browser_diagnostic(value.get('diagnostic'))
        if diagnostic:
            result['diagnostic'] = diagnostic
        return result

    def _recover(self):
        with self._directory() as directory:
            try:
                meta = json.loads(self._read(directory, 'integrity.json', 4096))
                if isinstance(meta, dict):
                    for key, default in self._integrity.items():
                        item = meta.get(key)
                        if type(item) is type(default) and (type(item) is bool or 0 <= item <= 1_000_000_000):
                            self._integrity[key] = item
            except FileNotFoundError:
                if any(name.startswith('events') for name in self._files):
                    self._integrity['metadata_missing'] = True
            try:
                value = json.loads(self._read(directory, 'history.json', self.max_history_bytes))
            except FileNotFoundError:
                return
            if (not isinstance(value, dict) or value.get('schema_version') != 1
                    or value.get('scope_id') != self.scope_id or not isinstance(value.get('records'), list)
                    or type(value.get('workspace_generation')) is not int
                    or not 0 <= value['workspace_generation'] <= 1_000_000_000):
                raise DiagnosticRefused('Invalid diagnostic history')
            self._generation = value['workspace_generation']
            integrity = value.get('integrity', {})
            if isinstance(integrity, dict):
                for key, default in self._integrity.items():
                    item = integrity.get(key)
                    if type(item) is type(default) and (type(item) is bool or 0 <= item <= 1_000_000_000):
                        self._integrity[key] = max(self._integrity[key], item)
            for raw in value['records'][-self.max_history:]:
                record = self._record(raw)
                if record is None:
                    self._integrity['invalid_records'] += 1
                    continue
                if record['outcome'] == 'running' and record['runtime_id'] != self.runtime_id:
                    record['outcome'] = 'uncertain' if record['kind'] in {'import', 'kept'} else 'interrupted'
                    record['recovered_at'] = _now()
                    record['details'] = {**record['details'], 'reason': 'runtime_interrupted', 'result_known': False}
                    self._integrity['history_recovered'] = True
                self._records.append(record)
            self._save()

    def _history_payload(self):
        return {'schema_version': 1, 'scope_id': self.scope_id, 'workspace_generation': self._generation,
                'records': self._records, 'integrity': self._integrity}

    def _save(self):
        try:
            self._records = self._records[-self.max_history:]
            payload = json.dumps(self._history_payload(), separators=(',', ':')).encode()
            while len(payload) > self.max_history_bytes and self._records:
                self._records.pop(0)
                self._integrity['evicted_history'] += 1
                payload = json.dumps(self._history_payload(), separators=(',', ':')).encode()
            with self._directory() as directory:
                self._atomic(directory, 'history.json', payload)
            return True
        except (OSError, ValueError, DiagnosticRefused):
            self._failure()
            return False

    def begin(self, kind, task_id, *, workflow_id=None, parent_task_id=None, provider=None, details=None):
        with self._lock:
            if not _enum(kind, KINDS) or not _identifier(task_id) or not _identifier(workflow_id or task_id):
                return False
            if any(r['task_id'] == task_id for r in self._records):
                return False
            record = dict(kind=kind, task_id=task_id, workflow_id=workflow_id or task_id,
                runtime_id=self.runtime_id, started_at=_now(), outcome='running',
                workspace_generation=self._generation, statistics={}, details=_details(details))
            if _identifier(parent_task_id):
                record['parent_task_id'] = parent_task_id
            if _enum(provider, PROVIDERS):
                record['provider'] = provider
            self._records.append(record)
            if len(self._records) > self.max_history:
                self._integrity['evicted_history'] += len(self._records) - self.max_history
            self.event('workflow_started', record)
            return self._save()

    def finish(self, task_id, outcome, *, statistics=None, diagnostic=None, details=None):
        with self._lock:
            record = next((r for r in self._records if r['task_id'] == task_id), None)
            if record is None or record['outcome'] != 'running' or not _enum(outcome, OUTCOMES):
                return False
            record.update(outcome=outcome, ended_at=_now(), statistics=_counts(statistics), details={**record['details'], **_details(details)})
            normalized = normalize_browser_diagnostic(diagnostic)
            if normalized:
                record['diagnostic'] = normalized
            self.event('workflow_finished', {**record, **(normalized or {}), 'counts': record['statistics']})
            return self._save()

    def event(self, event, details=None, *, level='info'):
        with self._lock:
            value = dict(details) if isinstance(details, dict) else {}
            value.update(schema_version=1, time=_now(), source='python', scope_id=self.scope_id,
                         runtime_id=self.runtime_id, event=event, level=level)
            value = validate_event(value)
            if value is None:
                self._integrity['omitted_events'] += 1
                return False
            ranks = {'debug': 10, 'info': 20, 'warn': 30, 'error': 40}
            if event in _SCHEMA['optional_detail_events'] and ranks[level] < ranks[self.level]:
                return False
            line = (json.dumps(value, separators=(',', ':')) + '\n').encode()
            try:
                with self._directory() as directory:
                    if len(line) > self.max_file_bytes:
                        self._integrity['omitted_events'] += 1
                        self._atomic(directory, 'integrity.json', json.dumps(self._integrity).encode())
                        return False
                    try:
                        current = self._file_identity(directory, 'events.jsonl')
                    except FileNotFoundError:
                        current = None
                    if self._files.get('events.jsonl') != current:
                        raise DiagnosticRefused('Managed diagnostic file was replaced')
                    if (current[2] if current else 0) + len(line) > self.max_file_bytes:
                        oldest = f'events.{self.max_files - 1}.jsonl' if self.max_files > 1 else 'events.jsonl'
                        try:
                            self._file_identity(directory, oldest)
                            if self._files.get(oldest) != self._file_identity(directory, oldest):
                                raise DiagnosticRefused('Rotated file was replaced')
                            os.unlink(oldest, dir_fd=directory)
                            self._files.pop(oldest, None)
                        except FileNotFoundError:
                            pass
                        for index in range(self.max_files - 2, -1, -1):
                            source = f'events.{index}.jsonl' if index else 'events.jsonl'
                            target = f'events.{index + 1}.jsonl'
                            try:
                                if self._files.get(source) != self._file_identity(directory, source):
                                    raise DiagnosticRefused('Rotated file was replaced')
                                try:
                                    target_identity = self._file_identity(directory, target)
                                except FileNotFoundError:
                                    target_identity = None
                                if self._files.get(target) != target_identity:
                                    raise DiagnosticRefused('Rotation target was replaced')
                                os.rename(source, target, src_dir_fd=directory, dst_dir_fd=directory)
                                self._files[target] = self._files.pop(source)
                            except FileNotFoundError:
                                pass
                        self._integrity['rotated_files'] += 1
                    self._append(directory, line)
                    self._atomic(directory, 'integrity.json', json.dumps(self._integrity).encode())
                return True
            except (OSError, ValueError, DiagnosticRefused):
                self._failure()
                return False

    def history(self):
        with self._lock:
            self._read_native_status()
            records = []
            for record in reversed(self._records):
                safe = self._record(record)
                if safe:
                    safe['before_workspace_reset'] = safe['workspace_generation'] != self._generation
                    records.append(safe)
            return deepcopy(dict(records=records, workspace_generation=self._generation,
                                 integrity={**self._integrity, 'native': self._native_integrity}))

    def workspace_reset(self):
        with self._lock:
            self._generation += 1
            self.event('workspace_reset', {'generation': self._generation})
            return self._save()

    def export(self, task_id=None):
        with self._lock:
            exported_at = _now()
            export_time = datetime.fromisoformat(exported_at.replace('Z', '+00:00'))
            range_start = export_time - timedelta(days=7)
            def in_recent_range(value):
                return range_start <= datetime.fromisoformat(value.replace('Z', '+00:00')) <= export_time
            records = self.history()['records']
            excluded_history = 0
            if task_id is not None:
                selected = next((r for r in records if r['task_id'] == task_id), None)
                if selected is None:
                    raise DiagnosticRefused('Task history is no longer retained')
                records = [r for r in records if r['workflow_id'] == selected['workflow_id']]
            else:
                recent = [r for r in records if in_recent_range(max(
                    (r[key] for key in ('started_at', 'ended_at', 'recovered_at') if key in r),
                    key=lambda value: datetime.fromisoformat(value.replace('Z', '+00:00'))))]
                excluded_history = len(records) - len(recent)
                records = recent
            events = []
            roots_valid = True
            try:
                with self._directory():
                    pass
            except (OSError, DiagnosticRefused):
                roots_valid = False
                self._failure()
            integrity = deepcopy(self.history()['integrity'])
            self._read_native_status()
            integrity['native'] = deepcopy(self._native_integrity)
            for producer in (('python', 'electron') if roots_valid else ()):
                path = self.root / 'scopes' / self.scope_id / producer
                try:
                    directory = _open_directory_nofollow(path)
                except FileNotFoundError:
                    continue
                except OSError:
                    integrity['write_failed'] = True
                    continue
                try:
                    for index in reversed(range(4)):
                        name = f'events.{index}.jsonl' if producer == 'electron' or index else 'events.jsonl'
                        try:
                            raw = self._read(directory, name, 1024 * 1024)
                        except FileNotFoundError:
                            continue
                        for line in raw.splitlines():
                            try:
                                value = validate_event(json.loads(line))
                            except (ValueError, TypeError):
                                value = None
                            if value is None:
                                integrity['invalid_records'] += 1
                                continue
                            if value.get('scope_id') != self.scope_id:
                                continue
                            events.append(value)
                except (OSError, ValueError, DiagnosticRefused):
                    integrity['write_failed'] = True
                finally:
                    os.close(directory)
            if task_id is not None:
                task_ids = {record['task_id'] for record in records}
                linked = lambda value: (value['workflow_id'] == selected['workflow_id']
                    if 'workflow_id' in value else value.get('task_id') in task_ids)
                request_ids = {value['request_id'] for value in events
                               if linked(value) and 'request_id' in value}
                events = [value for value in events if linked(value)
                          or ('workflow_id' not in value and value.get('request_id') in request_ids)]
            else:
                recent = [value for value in events if in_recent_range(value['time'])]
                integrity['range_excluded_history'] = excluded_history
                integrity['range_excluded_events'] = len(events) - len(recent)
                events = recent
            events.sort(key=lambda value: datetime.fromisoformat(value['time'].replace('Z', '+00:00')))
            lines = []
            included_events = []
            total = 0
            for value in reversed(events):
                line = json.dumps(value, separators=(',', ':')) + '\n'
                size = len(line.encode())
                if total + size > self.max_export_bytes:
                    integrity['omitted_events'] += 1
                    continue
                lines.append(line)
                included_events.append(value)
                total += size
            manifest = dict(format_version=1, schema_version=1, application='Allfold', application_version='0.1.0',
                exported_at=exported_at, scope_id=self.scope_id, runtime_id=self.runtime_id,
                collection='workflow' if task_id is not None else 'recent_scope', integrity=integrity,
                collection_range=None if task_id is not None else {
                    'from': range_start.isoformat(timespec='milliseconds').replace('+00:00', 'Z'),
                    'to': exported_at, 'days': 7, 'intentionally_limited': True},
                time_range={'from': included_events[-1]['time'] if included_events else None,
                            'to': included_events[0]['time'] if included_events else None},
                retained_runtime_ids=sorted({e['runtime_id'] for e in included_events}),
                scope_description=('Retained exact-workflow evidence across application starts; bounded by size and rotation.'
                    if task_id is not None else 'Current-configuration evidence in the last seven UTC days across application starts; bounded by size and rotation.'),
                limits=dict(event_bytes=self.max_export_bytes, history_records=self.max_history,
                    file_bytes=self.max_file_bytes, producer_files=self.max_files),
                environment={'platform': sys.platform, 'python': f'{sys.version_info.major}.{sys.version_info.minor}'})
            summary = dict(records=records, known_outcomes=[r['outcome'] for r in records],
                key_errors=[{k: e[k] for k in ('task_id', 'stage', 'code', 'status') if k in e}
                            for e in reversed(included_events) if e.get('level') == 'error'][:100],
                uncertain=any(r['outcome'] in {'running', 'uncertain', 'interrupted'} for r in records))
            output = io.BytesIO()
            with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, indent=2))
                archive.writestr('summary.json', json.dumps(summary, indent=2))
                archive.writestr('events.jsonl', ''.join(reversed(lines)))
                archive.writestr('README.md', '# Allfold local diagnostics\n\n'
                    'Contains only validated structured events and lightweight task history for the named scope. '
                    'No Workspace, credentials, page bodies, raw exceptions or complete URLs are collected. '
                    'Missing, rotated or failed records are evidence limits, not proof of success or safe retry. '
                    'A confirmed parent item does not prove attachment persistence. '
                    'This file is generated locally and is never uploaded automatically.\n\n'
                    'Fields: schema_version versions the validated event vocabulary; time is UTC. '
                    'runtime_id identifies an application start; workflow_id groups the complete business workflow; '
                    'task_id identifies a business task; request_id identifies one native invocation. '
                    'page_id, source_page_id, role and generation describe the captured page relationship; '
                    'scope_id and service_id describe verified configuration metadata, never permission or task authority. '
                    'source distinguishes Python/Electron; event, stage, step, code, status and net_error are fixed technical facts. '
                    'History outcome is coordinator-confirmed business state; a native event outcome describes only that operation. '
                    'parent and pdf distinguish parent-item evidence from unverified attachment persistence. '
                    'recent_scope includes only the last seven UTC days across startups, using one export time. '
                    'History uses its latest recorded start, finish or recovery time. '
                    'collection_range is the intentional collection window; time_range is the included event range. '
                    'range_excluded_history/events count intentionally excluded older or future-dated evidence; '
                    'rotation, omissions and write failures separately limit completeness. '
                    'A workflow export keeps all retained exact-workflow evidence regardless of age.\n')
            return output.getvalue()

    def _configuration_identity(self):
        try:
            parent = _open_directory_nofollow(self.config_path.parent)
            try:
                identity = self._file_identity(parent, self.config_path.name)
                raw = self._read(parent, self.config_path.name, 2 * 1024 * 1024)
                if self._file_identity(parent, self.config_path.name) != identity:
                    raise DiagnosticRefused('Configuration changed')
                return identity, hashlib.sha256(raw).hexdigest()
            finally:
                os.close(parent)
        except FileNotFoundError:
            return None

    def _managed_snapshot(self, directory):
        allowed = {'history.json', 'integrity.json', 'events.jsonl'} | {
            f'events.{i}.jsonl' for i in range(1, 4)}
        files = {}
        for name in os.listdir(directory):
            if name not in allowed:
                raise DiagnosticRefused('Unexpected file in managed diagnostic directory')
            files[name] = self._file_identity(directory, name)
        return files

    def preview_reset(self):
        with self._lock:
            self._reset_nonce = None
            with self._directory() as directory:
                plan = dict(scope_id=self.scope_id, token=secrets.token_urlsafe(32),
                    configuration=self._configuration_identity(), identities=tuple(self._identities),
                    files=self._managed_snapshot(directory))
            self._reset_nonce = plan
            return deepcopy(plan)

    def validate_reset(self, expected):
        """Check the saved plan before coordinating any destructive native step."""
        with self._lock:
            if (self._reset_nonce is None or expected != self._reset_nonce
                    or expected['configuration'] != self._configuration_identity()):
                raise DiagnosticRefused('Logs target changed or confirmation is no longer current')
            with self._directory() as directory:
                if self._managed_snapshot(directory) != expected['files']:
                    raise DiagnosticRefused('Diagnostic files changed since preview')

    def reset(self, expected):
        """Delete only identity-verified owned files; all attempts consume the preview."""
        with self._lock:
            plan, self._reset_nonce = self._reset_nonce, None
            if plan is None or expected != plan:
                raise DiagnosticRefused('Logs confirmation is stale or already used')
            if plan['configuration'] != self._configuration_identity():
                raise DiagnosticRefused('Configuration changed since Logs preview')
            with self._directory() as directory:
                if self._managed_snapshot(directory) != plan['files']:
                    raise DiagnosticRefused('Diagnostic files changed since preview')
                deleted = failed = 0
                for name, identity in plan['files'].items():
                    try:
                        if self._file_identity(directory, name) != identity:
                            raise DiagnosticRefused('Diagnostic file identity changed')
                        os.unlink(name, dir_fd=directory)
                        self._files.pop(name, None)
                        deleted += 1
                    except (OSError, DiagnosticRefused):
                        failed += 1
                if failed:
                    self._failure()
                    return dict(success=False, partial=deleted > 0, deleted=deleted, failed=failed)
                self._records = []
                self._integrity = {'write_failed': False, 'rotated_files': 0, 'omitted_events': 0,
                    'evicted_history': 0, 'invalid_records': 0, 'history_recovered': False,
                           'metadata_missing': False}
                success = self._save()
                return dict(success=success, partial=not success and deleted > 0,
                            deleted=deleted, failed=0 if success else 1)

    def set_level(self, saved):
        from allfold.logging_setup import effective_log_level
        with self._lock:
            self.level = effective_log_level(saved).lower().replace('warning', 'warn')

    def native_status(self, status):
        """Bridge-reported sink health is evidence only, never a business result."""
        if not isinstance(status, dict):
            return
        with self._lock:
            safe = {'status_known': True}
            for key in ('available', 'incomplete'):
                if type(status.get(key)) is bool:
                    safe[key] = status[key]
            for key in ('rotations', 'write_failures', 'omitted'):
                value = status.get(key)
                if type(value) is int and 0 <= value <= 2147483647:
                    safe[key] = value
            self._native_integrity.update(safe)

    def _read_native_status(self):
        try:
            directory = _open_directory_nofollow(self.root / 'scopes' / self.scope_id / 'electron')
            try:
                status = json.loads(self._read(directory, 'integrity.json', 4096))
            finally:
                os.close(directory)
            if isinstance(status, dict):
                # Missing or unwritable disk health never clears a live failure.
                known = self._native_integrity
                merged = dict(status)
                for key in ('incomplete', 'write_failures', 'rotations', 'omitted'):
                    if known.get('status_known') and key in known and key in merged and type(known[key]) is type(merged[key]):
                        merged[key] = max(known[key], merged[key])
                self.native_status(merged)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, DiagnosticRefused):
            self.native_status({'available': False, 'incomplete': True})

    @contextmanager
    def reset_guard(self):
        """Exclude all Python writers while coordinating the native reset."""
        with self._lock:
            yield
