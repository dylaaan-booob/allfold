"""Read-only Electron translation followed by the existing narrow Paper writer."""
from datetime import datetime, timezone
import secrets
import threading

from allfold.application.paper_enrichment import (
    read_enrichment_target, save_enrichment, paper_fields, edit_paper_fields,
)
from allfold.identifiers import normalize_doi
from allfold.persistence.safe_write import ContentChangedError, TextWriteCommittedError
from allfold.url_safety import normalize_public_http_url
from allfold.browser_diagnostics import format_browser_diagnostic, normalize_browser_diagnostic
from allfold.application.history import observe
from allfold.application.browser_runtime import ElectronDisconnected


from allfold.models import EvidenceDateKind, parse_publication_date
from allfold.paper_dates import source_date


def publication_date_candidate(item):
    """Preserve the precision of parsed parts from Zotero's sandbox."""
    raw, parts = item.get('date'), item.get('date_parts')
    if not isinstance(raw, str) or not raw.strip() or not isinstance(parts, dict):
        return None
    if 'year' not in parts or set(parts) - {'year', 'month', 'day'}:
        return None
    if any(type(value) is not int for value in parts.values()) or ('day' in parts and 'month' not in parts):
        return None
    try:
        value = f"{parts['year']:04d}"
        for component in ('month', 'day'):
            if component in parts:
                value += f"-{parts[component]:02d}"
        return parse_publication_date(value)
    except (ValueError, OverflowError):
        return None

def authors_candidate(item):
    creators = item.get('creators')
    if not isinstance(creators, list):
        return None
    names = []
    for creator in creators:
        if not isinstance(creator, dict):
            return None
        if creator.get('creatorType') != 'author':
            continue
        mode = creator.get('fieldMode', 0)
        if type(mode) is not int or mode not in {0, 1}:
            return None
        parts = [creator.get('lastName', '')] if mode == 1 else [
            creator.get('firstName', ''), creator.get('lastName', '')]
        if any(not isinstance(part, str) for part in parts):
            return None
        name = ' '.join(part.strip() for part in parts if part.strip())
        if not name or any(character in name for character in ('\r', '\n', '\0')):
            return None
        names.append(name)
    return names or None


def translator_date_events(item, target, metadata_source, history, source_url):
    events = []
    if (target.missing_date or target.missing_abstract or target.missing_authors) and (value := publication_date_candidate(item)):
        event = source_date(value, kind=EvidenceDateKind.PUBLISHED, source_label='date',
            provider='translator-doi' if metadata_source == 'doi' else 'translator-web',
            record_id=target.doi, publication_type='preprint' if item.get('itemType') == 'preprint' else
                'conference' if item.get('itemType') == 'conferencePaper' else 'journal',
            url='https://doi.org/' + target.doi)
        if event:
            events.append(event.model_dump(mode='json', exclude_none=True))
    if metadata_source != 'web' or item.get('itemType') != 'journalArticle' or not target.history_kinds or not isinstance(history, list):
        return events
    if not isinstance(source_url, str):
        return events
    try:
        url = normalize_public_http_url(source_url)
    except ValueError:
        return events
    if not url:
        return events
    seen = set()
    for candidate in history:
        if not isinstance(candidate, dict) or candidate.get('record_id') != target.doi:
            continue
        kind, label = candidate.get('kind'), candidate.get('source_label')
        if kind not in ('received', 'accepted') or not isinstance(label, str) or not label.strip() or candidate.get('url') != url:
            continue
        value = candidate.get('value')
        event = source_date(value, kind=kind, source_label=label, provider='translator-web',
                            record_id=target.doi, publication_type='journal', url=url)
        if event and (key := (kind, value, url)) not in seen:
            seen.add(key)
            events.append(event.model_dump(mode='json', exclude_none=True))
    return events


class PaperEnrichment:
    def __init__(self, bridge, browser_lock, *, diagnostics=None, current_workspace=None):
        self.bridge, self.browser_lock = bridge, browser_lock
        self.diagnostics = diagnostics
        self.current_workspace = current_workspace
        self._lock = threading.RLock()
        self._task = None
        self._worker = None
        self._latest = {}

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def state(self, paper_id, request_id=None):
        with self._lock:
            state = dict(phase='Idle', supported=self.bridge.connected, message='', request_id=None)
            diagnostic = self._latest.get(paper_id)
            if diagnostic and (request_id is None or diagnostic['request_id'] == request_id):
                state['diagnostic'] = diagnostic
            task = self._task
            if task and task['target'].paper_id == paper_id and (request_id is None or request_id == task['request_id']):
                state.update({k: task[k] for k in ('phase', 'message', 'request_id', 'saved', 'waiting_for_user')})
                target = task['target']
                state.update(missing_abstract=target.missing_abstract and 'abstract' not in task['saved'],
                    missing_authors=target.missing_authors and 'authors' not in task['saved'],
                    missing_date=target.missing_date and 'publication_date' not in task['saved'])
            return state

    def start(self, workspace, paper_id):
        target = read_enrichment_target(workspace, paper_id)
        with self._lock:
            if self.running:
                raise ValueError('Enrichment is still running')
            if not self.bridge.connected:
                raise ValueError('Electron runtime unavailable')
            owner = self.browser_lock.acquire('enrichment')
            if owner is None:
                raise ValueError('Another browser workflow is active')
            task = dict(target=target, owner=owner, request_id=secrets.token_hex(16), phase='Retrieving',
                message='Retrieving missing fields…', saved={}, waiting_for_user=False,
                stop=threading.Event(), started_at=datetime.now(timezone.utc).isoformat())
            observe(self.diagnostics, 'begin', 'enrich', task['request_id'])
            self._task = task
            self._worker = threading.Thread(target=self._run, args=(task,), name='electron-enrichment', daemon=False)
            try:
                self._worker.start()
            except BaseException:
                observe(self.diagnostics, "finish", task["request_id"], "failed", details={"reason":"failed"})
                self.browser_lock.release(owner)
                self._task = None
                raise
            return self.state(paper_id)

    def _run(self, task):
        target = task['target']
        try:
            with self._lock:
                if task['stop'].is_set():
                    raise InterruptedError()
                pending = self.bridge.execute('enrich_paper', {'doi': target.doi,
                    'history_kinds': list(target.history_kinds),
                    'task_id':task['request_id'], 'workflow_id':task['request_id'], 'paper_id':str(target.paper_id)}, lambda data: self._progress(task, data))
            result = pending.result()
            task['diagnostic'] = normalize_browser_diagnostic(result.get('diagnostic'))
            with self._lock:
                if task['stop'].is_set():
                    raise InterruptedError()
                if not self.bridge.connected:
                    raise ElectronDisconnected('Electron disconnected before enrichment save')
                item = result.get('item')
                if not isinstance(item, dict):
                    raise ValueError(format_browser_diagnostic(result.get('diagnostic')))
                if item.get('itemType') in {None, '', 'multiple', 'webpage', 'attachment', 'note'}:
                    raise ValueError('Translator did not return a literature Item')
                if normalize_doi(item.get('DOI')) != target.doi:
                    raise ValueError('Translator DOI does not match this Paper')
                candidate = {}
                if target.missing_abstract and isinstance(item.get('abstractNote'), str) and item['abstractNote'].strip():
                    candidate['abstract'] = item['abstractNote']
                if target.missing_authors and (authors := authors_candidate(item)):
                    candidate['authors'] = authors
                if target.missing_date and (date := publication_date_candidate(item)):
                    if target.publication_date is None or len(date) == 10:
                        candidate['publication_date'] = date
                events = translator_date_events(item, target, result.get('metadata_source'),
                                                result.get('date_candidates'), result.get('source_url'))
                if events:
                    candidate['date_evidence'] = events
                if self.current_workspace and self.current_workspace().resolve() != target.workspace:
                    raise ContentChangedError('Workspace changed during Enrich')
                task['phase'] = 'Saving'
                try:
                    candidate = save_enrichment(target, candidate.get('abstract'), candidate.get('publication_date'),
                                    authors=candidate.get('authors'), date_evidence=candidate.get('date_evidence', ()))
                    task['message'] = 'Enrichment saved' if candidate else 'No new usable fields or date evidence found'
                except TextWriteCommittedError:
                    task["sync_warning"] = True
                    task['message'] = 'Enrichment saved; filesystem sync failed'
                task.update(phase='Completed', saved=candidate)
        except InterruptedError:
            task.update(phase='Cancelled', message='Enrichment cancelled')
        except Exception as error:
            if isinstance(error, ElectronDisconnected):
                task["history_interrupted"] = True
            task.update(phase='Failed', message=str(error) if isinstance(error, (ValueError, OSError, ContentChangedError)) else 'Enrichment failed')
        finally:
            with self._lock:
                task['waiting_for_user'] = False
                self._latest[target.paper_id] = dict(request_id=task['request_id'], phase=task['phase'],
                    message=task['message'], started_at=task['started_at'], finished_at=datetime.now(timezone.utc).isoformat(),
                    requirements=dict(abstract=target.missing_abstract, authors=target.missing_authors, history=list(target.history_kinds),
                        publication_date='any' if target.missing_date else 'none'), saved_fields=list(task['saved']), attempts=[])
                self.browser_lock.release(task['owner'])
                observe(self.diagnostics, 'finish', task['request_id'], 'interrupted' if task.get('history_interrupted') else task['phase'].lower(),
                    statistics={'enriched':int(bool(task['saved'])), 'updated':len(task['saved'])},
                    diagnostic=task.get('diagnostic'), details={'saved_fields':list(task['saved']),
                        'requested_fields':list(target.missing_fields),
                        'sync_warning':task.get('sync_warning',False),
                        'reason':'connection_lost' if task.get('history_interrupted') else 'cancelled' if task['phase'] == 'Cancelled' else 'failed' if task['phase'] == 'Failed' else None})

    def _progress(self, task, data):
        with self._lock:
            if not task['stop'].is_set():
                task.update(waiting_for_user=data.get('waiting_for_user') is True,
                    message='Complete verification in BROWSER' if data.get('waiting_for_user') else 'Retrieving missing fields…')

    def cancel(self, paper_id, request_id):
        with self._lock:
            task = self._task
            if not task or task['target'].paper_id != paper_id or task['request_id'] != request_id or task['phase'] != 'Retrieving' or not self.running:
                return False
            task['stop'].set()
            self.bridge.cancel_current()
            task['message'] = 'Stopping; waiting for translation to settle'
            return True

    def shutdown(self):
        if self._task:
            self.cancel(self._task['target'].paper_id, self._task['request_id'])

    def join(self):
        if self._worker:
            self._worker.join()

    def fields(self, workspace, paper_id):
        return paper_fields(workspace, paper_id)

    def edit_fields(self, workspace, paper_id, revision, **changes):
        with self._lock:
            if self.running:
                raise ValueError('Enrichment is active')
            edit_paper_fields(workspace, paper_id, revision, **changes)
