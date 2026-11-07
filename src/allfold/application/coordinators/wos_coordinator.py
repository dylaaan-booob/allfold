"""One transient WoS run, sharing CARSI and browser/Run ownership."""
from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from allfold.application.wos import WoSWrites, persist_wos
from allfold.application.history import observe, finish_run
from allfold.application.browser_runtime import ElectronDisconnected
from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.application.run_state import (
    WOS_RUN_SCHEMA_VERSION, RunProvider, RunFacts, RunIdentifierFact,
    RunJournalFact, RunIssueFact, validate_saved_facts,
)
from allfold.application.runtime_metadata import metadata_directory
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.config import ConfigurationError, load_config
from allfold.persistence.user_state import load_user_state, read_user_state
from allfold.persistence.journal_registry import local_candidates
from allfold.date_range import resolve_date_range
from allfold.persistence.safe_write import CompareReadError, ContentChangedError, read_text_exact, workspace_operation_lock, workspace_text_directory
from allfold.application.coordinators.preparation_coordinator import PreparationPhase
from allfold.providers.wos import WoSRecords, compile_wos_query, combined_query, match_journal, record_paper, parse_tagged, read_export


class WoSCoordinator:
    def __init__(self, config_path, preparation, run_slot, *, bridge, browser_lock, diagnostics=None):
        self.diagnostics = diagnostics
        self.path, self.preparation, self.run_slot = config_path, preparation, run_slot
        self.lock = threading.RLock()
        self.task = None
        self.last = None
        self.last_workspace = None
        self.bridge, self.browser_lock = bridge, browser_lock
        self._worker = None

    @property
    def running(self):
        with self.lock:
            return self.task is not None and self.task["status"] == "RUNNING"

    def _browser_available(self):
        return self.bridge.connected


    def _configuration(self):
        config = load_config(self.path)
        compiled = compile_wos_query(config.keyword_ast)
        snapshot = load_user_state(self.path, config.venue_whitelist)
        if snapshot.revision.digest != config.user_state_revision:
            raise ContentChangedError('User state changed while reading Run WoS configuration')
        services = snapshot.state.access_services
        matches = [s for s in services if s.name == 'Web of Science' and s.access_method == 'carsi']
        if len(matches) != 1:
            raise ValueError('Run WoS requires exactly one saved CARSI Service named Web of Science')
        service = matches[0]
        institution = config.institution
        if not (institution and (institution.name or (institution.use_shibboleth and institution.idp_entity_id))):
            raise ValueError('Select an Institution first; institution search requires its name, '
                             'or enable Shibboleth with a Public IdP Entity ID')
        dates = resolve_date_range(config.date_spec)
        return config, compiled, service, dates

    def _latest(self):
        try:
            config = load_config(self.path)
            if self.last_workspace == config.output_dir and self.last is not None:
                return self.last
            directory = metadata_directory(config.output_dir, create=False)
            target = directory / 'last-wos-run.json' if directory else None
            if target and (target.exists() or target.is_symlink()):
                if target.is_symlink() or not target.is_file():
                    raise ValueError('Latest WoS Run is not a regular file')
                value = json.loads(read_text_exact(target))
                if isinstance(value, dict) and type(value.get('schema_version')) is int and value['schema_version'] < WOS_RUN_SCHEMA_VERSION:
                    return dict(status='unsupported', error='旧版运行记录，请重新运行生成结果。')
                if not isinstance(value, dict) or value.get('schema_version') != WOS_RUN_SCHEMA_VERSION or value.get('provider') != 'wos' or not isinstance(value.get('result'), dict):
                    raise ValueError('Latest WoS Run has an invalid schema')
                validate_saved_facts(value['result'].get('facts'))
                self.last, self.last_workspace = value, config.output_dir
                return value
        except (ValueError, OSError) as error:
            # Reconstructible diagnostics never disable a new explicit Run.
            return dict(status='invalid', error=str(error))
        return None

    def state(self):
        with self.lock:
            task = self.task
            enabled, message = False, ''
            try:
                self._configuration()
                enabled = self._browser_available()
                if not enabled:
                    message = 'Browser runtime unavailable'
            except (ValueError, OSError) as error:
                message = str(error)
            result = task['result'] if task else None
            snapshot = dict(provider=RunProvider.WOS.value, status=task['status'] if task else 'IDLE', result=result,
                            resolved_date_range=dict(from_date=str(task['dates'].from_date), to_date=str(task['dates'].to_date)) if task else None,
                            task_id=task['id'] if task else None,
                            waiting_for_user=bool(task and task['status'] == 'RUNNING' and task.get('waiting_for_user')),
                            query={k: task['query'][k] for k in ('text', 'total', 'next_first', 'finished')} if task else None,
                            batches=[{k: b[k] for k in ('first', 'last', 'expected', 'exported', 'eligible', 'complete')}
                                     for b in task['batches'].values()] if task else [])
            elapsed = int(task.get('finished_clock', time.monotonic()) - task['started_clock']) if task else 0
            return dict(snapshot=snapshot, enabled=enabled, message=message, latest=self._latest(),
                progress=dict(stage_label=task['stage'] if task else 'Run WoS', elapsed_text=f'{elapsed // 60}:{elapsed % 60:02}',
                              announcement_message=task['message'] if task else message))

    def start(self):
        with self.lock:
            config, compiled, service, dates = self._configuration()
            if not self._browser_available():
                raise ValueError('Electron browser runtime is unavailable')
            workspace_identity = None
            if config.output_dir.exists() or config.output_dir.is_symlink():
                info = config.output_dir.lstat()
                if config.output_dir.is_symlink() or not config.output_dir.is_dir():
                    raise ValueError('Workspace is not a regular directory')
                workspace_identity = (info.st_dev, info.st_ino)
            query = combined_query(compiled, config.journals, dates.from_date, dates.to_date)
            not_listed, warnings = [], []
            try:
                for journal in config.journals:
                    candidates = local_candidates(config.venue_whitelist, journal.key)
                    sources = {source['source'] for candidate in candidates
                               if (candidate['issn'], candidate['eissn']) == (journal.issn, journal.eissn)
                               for source in candidate['sources']}
                    if not sources & {'SCIE', 'SSCI', 'ESCI', 'AHCI'}:
                        not_listed.append(dict(journal_key=journal.key, name=journal.name))
                if not_listed:
                    warnings.append('未列入当前本地 WoS 来源清单（非实时收录核查，仍参与检索）：' +
                                    '、'.join(j['name'] for j in not_listed))
            except ConfigurationError as error:
                not_listed = []
                warnings.append(f'无法核对本地 WoS 来源清单；仍使用保存的标识检索：{error}')
            config_text = read_text_exact(self.path)
            state_revision = read_user_state(self.path).revision
            if state_revision.digest != config.user_state_revision or load_config(self.path) != config:
                raise ContentChangedError('Configuration changed before Run WoS start')
            saved = BrowserServiceSnapshot.read(self.path)
            if saved.config_contents != config_text or saved.revision != state_revision:
                raise ContentChangedError('Configuration changed before Run WoS start')
            if not self.run_slot.acquire(blocking=False):
                raise ValueError('Another Run is already active')
            owner = self.browser_lock.acquire('wos')
            if owner is None:
                self.run_slot.release()
                raise ValueError('Another browser workflow is active')
            task = dict(id=secrets.token_hex(16), owner=owner, config=config,
                compiled=compiled, service=service, dates=dates,
                service_scope=saved.scope,
                config_text=config_text, state_revision=state_revision,
                workspace_identity=workspace_identity, status='RUNNING', stage='Access Check', message='Starting CARSI',
                started_at=datetime.now(timezone.utc).isoformat(), started_clock=time.monotonic(),
                cancelled=threading.Event(), records=WoSRecords(), query=dict(text=query, next_first=1, total=None, seen=set(), finished=False),
                identifiers={identifier: journal for journal in config.journals for identifier in journal.identifiers},
                not_listed=not_listed, batches={}, download_root=None, waiting_for_user=False, date_warnings=[],
                issues=[], warnings=warnings, raw_records=0, matched_journal_records=0, unmatched_journal_records=0, no_doi=0,
                eligible_records=0, journal_counts={}, writes=WoSWrites(), result=None, prep=None)
            observe(self.diagnostics, "begin", "run", task["id"], provider="wos")
            self.task = task
            worker = self._worker = threading.Thread(target=self._run, args=(task,), name='allfold-wos', daemon=False)
            try:
                worker.start()
            except BaseException:
                self._release_owner(owner)
                self.run_slot.release()
                task['status'] = 'FINISHED'
                observe(self.diagnostics, 'finish', task['id'], 'failed', details={'reason':'failed'})
                raise
            return self.state()

    def cancel(self, task_id):
        with self.lock:
            task = self.task
            if task is None or task['id'] != task_id or task['status'] != 'RUNNING':
                return False
            task['cancelled'].set()
            task['message'] = 'Canceling; waiting for in-flight browser calls to settle'
            prep = task['prep']
            if prep and self.preparation.snapshot().authorization_pending:
                self.preparation.cancel(prep.task_id, prep.generation)
            else:
                self.bridge.cancel_current()
            return True

    def _current(self, task):
        if read_text_exact(self.path) != task['config_text'] or read_user_state(self.path).revision != task['state_revision']:
            raise ContentChangedError('Saved configuration changed during Run WoS')
        path = task['config'].output_dir
        if task['workspace_identity'] is not None:
            info = path.lstat()
            if path.is_symlink() or (info.st_dev, info.st_ino) != task['workspace_identity']:
                raise ContentChangedError('Workspace identity changed during Run WoS')
        elif path.exists() or path.is_symlink():
            raise ContentChangedError('Workspace appeared during Run WoS; restart against its current identity')


    def _consume_export(self, task, batch, filename):
        query = task['query']
        issues = []
        try:
            text, root = read_export(filename, batch['relative_name'], task['download_root'])
            parsed = parse_tagged(text)
            task['download_root'] = root
            issues.extend(parsed.issues)
            batch['exported'] = len(parsed.records)
            task['raw_records'] += len(parsed.records)
            if len(parsed.records) > batch['expected']:
                issues.append('batch_count_mismatch')
            usable = parsed.records if len(parsed.records) <= batch['expected'] else []
            for position, raw in enumerate(usable, batch['first']):
                ut = ' '.join(raw.get('UT', [])).strip().upper()
                if ut and ut in query['seen']:
                    issues.append('duplicate_UT_in_query')
                if ut:
                    query['seen'].add(ut)
                journal = match_journal(raw, task['identifiers'])
                if journal is not None:
                    task['journal_counts'][journal.key] = task['journal_counts'].get(journal.key, 0) + 1
                if journal is None:
                    task['unmatched_journal_records'] += 1
                    continue
                task['matched_journal_records'] += 1
                try:
                    warnings = []
                    paper = record_paper(raw, journal, warnings)
                except (ValueError, TypeError) as failure:
                    if str(failure) == 'missing_doi':
                        task['no_doi'] += 1
                    else:
                        issues.append(f'record_{position}_unusable')
                    continue
                finally:
                    for warning in warnings:
                        warning['reasons'] = [reason for reason in warning['reasons']
                                              if reason not in {'EA_fallback', 'year_only'}]
                        if not warning['reasons']:
                            continue
                        warning['record_number'] = position
                        task['date_warnings'].append(warning)
                        task['warnings'].append(json.dumps(warning, ensure_ascii=False))
                task['eligible_records'] += 1
                batch['eligible'] += 1
                if not paper.sources:
                    task['warnings'].append(f'{paper.doi}: no valid WoS UT; no source identity invented')
                task['records'].add(paper)
            if batch['exported'] != batch['expected']:
                issues.append('batch_count_mismatch')
        except (ValueError, OSError) as failure:
            # Never echo a filesystem path or arbitrary downloaded content.
            issues.append('export_read_failed:' + type(failure).__name__)
        return issues


    def _release_owner(self, owner):
        self.browser_lock.release(owner)

    def _electron_call(self, task, action, data):
        with self.lock:
            self._current(task)
            if task['cancelled'].is_set():
                raise InterruptedError()
            self.browser_lock.require(task['owner'])
            pending = self.bridge.execute(action, {**data, 'task_id': task['id'], 'workflow_id':task['id'],
                'service_id': task['service'].id, 'service_scope': task['service_scope']},
                lambda value: self._electron_progress(task, value))
        result = pending.result()
        self._current(task)
        if task['cancelled'].is_set():
            raise InterruptedError()
        if 'diagnostic' in result:
            diagnostic = result['diagnostic']
            task['diagnostic'] = normalize_browser_diagnostic(diagnostic)
            if (isinstance(diagnostic, dict) and diagnostic.get('stage') == 'wos_dom'
                    and diagnostic.get('code') == 'server_unexpected_error'):
                raise ValueError('WoS 服务端异常（Server.unexpectedError），本次运行已终止，请稍后重试。')
            codes = {'control_not_unique', 'control_disabled', 'input_value_mismatch',
                'core_collection_unverified', 'stale_search_results', 'export_range_unverified',
                'download_observer_busy', 'action_expired', 'export_content_unverified', 'unknown_dom_step', 'dom_step_failed'}
            steps = {'ready', 'search', 'result', 'exportMenu', 'controlReady', 'plainText', 'dialog',
                'configure', 'contentReady', 'selectContent', 'arm', 'export', 'links'}
            if (isinstance(diagnostic, dict) and diagnostic.get('stage') == 'wos_dom'
                    and diagnostic.get('code') in codes and diagnostic.get('step') in steps):
                raise ValueError(f"WoS {action.removeprefix('wos_')} [{diagnostic['step']}]: {diagnostic['code']}.")
            if (isinstance(diagnostic, dict) and diagnostic.get('stage') == 'wos_download'
                    and diagnostic.get('code') in {'download_interrupted', 'download_cancelled',
                        'download_failed', 'download_ambiguous', 'download_not_attributable'}):
                raise ValueError(f"WoS export [download]: {diagnostic['code']}.")
            from allfold.browser_diagnostics import format_browser_diagnostic
            raise ValueError(format_browser_diagnostic(result.get('diagnostic')))
        return result

    def _electron_progress(self, task, value):
        with self.lock:
            if not task['cancelled'].is_set():
                task['waiting_for_user'] = value.get('waiting_for_user') is True
                task['message'] = 'Complete login or verification in BROWSER' if task['waiting_for_user'] else task['stage']

    def _run(self, task):
        import tempfile
        try:
            config = task['config']
            with self.lock:
                self._current(task)
                if task['cancelled'].is_set():
                    raise InterruptedError()
                prep = self.preparation.start(self.path, service=task['service'], browser_owner=task['owner'],
                    workflow_id=task['id'], parent_task_id=task['id'])
                task['prep'] = prep
            while self.preparation.snapshot().authorization_pending:
                snapshot = self.preparation.snapshot()
                task.update(message=snapshot.message, waiting_for_user=snapshot.waiting_for_user)
                if task['cancelled'].is_set():
                    self.preparation.cancel(prep.task_id, prep.generation)
                time.sleep(.1)
            if task['cancelled'].is_set():
                raise InterruptedError()
            preparation = self.preparation.snapshot()
            if (preparation.phase is PreparationPhase.BLOCKED and any(
                    result.reason in {'institution_credentials_rejected', 'carsi_session_expired', 'timeout'}
                    for result in preparation.results)):
                raise ValueError(preparation.message)
            page = self.preparation.wos_handoff(prep.task_id, prep.generation)
            if page is None:
                from allfold.browser_diagnostics import format_browser_diagnostic
                diagnostic = next((result.diagnostic for result in preparation.results if result.diagnostic), None)
                if diagnostic:
                    raise ValueError(format_browser_diagnostic(diagnostic))
                raise ValueError('CARSI did not open an attributable WoS target page')
            task.update(stage='WoS Query', waiting_for_user=False)
            query = self._electron_call(task, 'wos_query', {'page_id': page, 'query': task['query']['text']})
            total = query.get('total')
            if type(total) is not int or total < 0 or query.get('page_id') != page:
                raise ValueError('Unattributable WoS search result')
            task['query']['total'] = total
            task['query']['finished'] = total == 0
            limit = query.get('batch_limit')
            if type(limit) is not int or not 1 <= limit <= 1000:
                raise ValueError('Invalid native export batch limit')
            with tempfile.TemporaryDirectory(prefix='allfold-wos-') as temporary:
                root = Path(temporary).resolve()
                for first in range(1, total + 1, limit):
                    last = min(first + limit - 1, total)
                    token = secrets.token_hex(16)
                    relative = f"allfold-wos/{task['id']}/{token}.txt"
                    filename = root / relative
                    filename.parent.mkdir(parents=True, exist_ok=True)
                    batch = dict(first=first, last=last, expected=last-first+1, exported=0, eligible=0,
                                 complete=False, issues=[], relative_name=relative)
                    task['batches'][token] = batch
                    task.update(stage='Official Export', message=f'Exporting {first}–{last}/{total}')
                    result = self._electron_call(task, 'wos_export', dict(page_id=page,
                        first=first, last=last, download_root=str(root), filename=str(filename)))
                    if result.get('filename') != str(filename):
                        raise ValueError('Export path did not match the issued batch')
                    task['download_root'] = root
                    batch['issues'] = self._consume_export(task, batch, str(filename))
                    batch['complete'] = not batch['issues']
                    task['issues'].extend(f'{first}-{last}: {issue}' for issue in batch['issues'])
                    task['query']['next_first'] = last + 1
                    if batch['issues']:
                        break
                task['query']['finished'] = task['query']['next_first'] > total and not task['issues']
            task['writes'].conflicts = len(task['records'].conflicts)
            task['issues'].extend(f'{doi}: conflicting incoming WoS records' for doi in sorted(task['records'].conflicts))
            papers = [paper for doi, paper in task['records'].papers.items() if doi not in task['records'].conflicts]
            self._current(task)
            if task['cancelled'].is_set():
                raise InterruptedError()
            if papers:
                task['stage'] = 'Create New Papers'
                with workspace_operation_lock(config.output_dir, create=True) as lock:
                    if task['workspace_identity'] is None:
                        task['workspace_identity'] = lock.identity
                    self._current(task)
                    persist_wos(papers, lock, check_current=lambda: self._current(task),
                                cancelled=task['cancelled'].is_set, result=task['writes'])
        except InterruptedError:
            task['cancelled'].set()
        except Exception as error:
            task['history_interrupted'] = isinstance(error, ElectronDisconnected)
            task['issues'].append(str(error) if isinstance(error, (ValueError, OSError, ContentChangedError)) else 'WoS browser execution failed')
        finally:
            try:
                self.preparation.join()
                self._complete(task)
            finally:
                with self.lock:
                    task.update(status='FINISHED', waiting_for_user=False)
                    self._release_owner(task['owner'])
                    self.run_slot.release()
                    finish_run(self.diagnostics, task['id'], {'provider':'wos','result':task['result']}, provider='wos', diagnostic=task.get('diagnostic'), interrupted=task.get('history_interrupted', False))

    def shutdown(self):
        if self.task:
            self.cancel(self.task['id'])

    def join(self):
        if self._worker:
            self._worker.join()

    def _complete(self, task):
        writes = task['writes']
        problems = [*task['issues'], *writes.issues]
        outcome = ('Cancelled' if task['cancelled'].is_set() else
                   'Partial' if (problems or writes.conflicts or writes.write_failures) and (task['raw_records'] or task['query']['total'] == 0) else
                   'Failed' if problems else 'Completed')
        result = {**asdict(writes), 'outcome': outcome, 'returned_records': task['raw_records'],
            'search_total': task['query']['total'],
            'matched_journal_records': task['matched_journal_records'],
            'unmatched_journal_records': task['unmatched_journal_records'],
            'eligible_records': task['eligible_records'],
            'no_doi': task['no_doi'],
            'not_listed_in_local_wos': task['not_listed'],
            'issues': list(dict.fromkeys(problems)), 'warnings': list(dict.fromkeys(task['warnings']))}
        finished_at = datetime.now(timezone.utc)
        not_listed = {item['journal_key'] for item in task['not_listed']}
        identity_messages = {f'{doi}: conflicting incoming WoS records' for doi in task['records'].conflicts}
        batch_messages = {f"{b['first']}-{b['last']}: {message}"
                          for b in task['batches'].values() for message in b['issues']}
        facts = RunFacts(finished_at=finished_at, created_papers=writes.created_papers,
            existing_papers=writes.skipped_existing_papers,
            statistics={key: result[key] for key in ('returned_records', 'matched_journal_records',
                'unmatched_journal_records', 'eligible_records', 'no_doi', 'conflicts', 'write_failures')},
            journals=tuple(RunJournalFact(key=j.key, name=j.name,
                status='hint' if j.key in not_listed else 'observed',
                records=task['journal_counts'].get(j.key),
                identifiers=tuple(RunIdentifierFact(issn=i, status='local_not_listed')
                                  for i in j.identifiers) if j.key in not_listed else ())
                for j in task['config'].journals if j.key in not_listed or task['journal_counts'].get(j.key)),
            issues=tuple([RunIssueFact(category='identity' if m in identity_messages else 'retrieval',
                                      severity='error', message=m) for m in task['issues'] if m not in batch_messages] +
                         [RunIssueFact(category='capture', severity='error', message=m) for m in writes.issues] +
                         [RunIssueFact(category='notice', message=m) for m in task['warnings']
                          if not m.startswith('{') and not (not_listed and m.startswith('未列入当前本地 WoS 来源清单（'))]),
            details=dict(search_total=result['search_total'], query_finished=task['query']['finished'],
                batches=[{k: b[k] for k in ('first', 'last', 'expected', 'exported', 'eligible', 'complete', 'issues')}
                         for b in task['batches'].values()], date_warnings=task['date_warnings']))
        result['facts'] = facts.model_dump(mode='json')
        snapshot = dict(schema_version=WOS_RUN_SCHEMA_VERSION, provider=RunProvider.WOS.value, started_at=task['started_at'], finished_at=finished_at.isoformat(),
            mode='topic', input=task['config'].keyword_expression, compiled=task['compiled'],
            from_date=str(task['dates'].from_date), to_date=str(task['dates'].to_date), result=result,
            query={k: task['query'][k] for k in ('text', 'total', 'next_first', 'finished')},
            batches=[{k: b[k] for k in ('first', 'last', 'expected', 'exported', 'eligible', 'complete', 'issues')}
                     for b in task['batches'].values()], date_warnings=task['date_warnings'])
        try:
            self._current(task)
            with workspace_operation_lock(task['config'].output_dir, create=True) as lock:
                if task['workspace_identity'] is None:
                    task['workspace_identity'] = lock.identity
                self._current(task)
                metadata_directory(lock.path, create=True)
                with workspace_text_directory(lock, '.allfold') as directory:
                    target = directory.path / 'last-wos-run.json'
                    content = json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n'
                    if target.exists():
                        directory.replace(target.name, content, expected_contents=read_text_exact(target))
                    else:
                        directory.create(target.name, content)
        except (ValueError, OSError, ContentChangedError, CompareReadError) as error:
            result['warnings'].append(f'WoS snapshot was not saved: {error}')
            facts = facts.model_copy(update={'issues': (*facts.issues,
                RunIssueFact(category='snapshot_write', message=f'最近结果未保存：{error}'))})
            result['facts'] = facts.model_dump(mode='json')
        with self.lock:
            self.last = snapshot
            self.last_workspace = task['config'].output_dir
            task.update(stage=outcome, result=result, finished_clock=time.monotonic())
