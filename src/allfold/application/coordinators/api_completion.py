"""Explicit, process-local API task with shared admission and guarded writes."""
from contextlib import ExitStack
from dataclasses import asdict
import secrets
import threading
from uuid import UUID

from allfold.application.api_completion import saved_paper_evidence, save_api_completion
from allfold.application.history import observe
from allfold.application.metadata_completion import complete_metadata
from allfold.application.paper_enrichment import read_paper_target
from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.integrations.openalex_credentials import read_credential
from allfold.models import WorkflowStatus
from allfold.persistence.discovery_evidence import read_discovery_evidence, append_discovery_evidence
from allfold.persistence.markdown_state import parse_paper_state
from allfold.persistence.safe_write import ContentChangedError, TextWriteCommittedError
from allfold.providers.integrated import DiscoveryClient, DISCOVERY_PROVIDERS
from allfold.providers.supplemental import SupplementalClient


def completion_client(provider, **kwargs):
    if provider in DISCOVERY_PROVIDERS:
        kwargs.pop('mailto', None)
        return DiscoveryClient(provider, **kwargs)
    kwargs.pop('api_key', None)
    return SupplementalClient(provider, **kwargs)


class ApiCompletion:
    def __init__(self, config_path, task_lock, *, run_slot=None, diagnostics=None, client_factory=completion_client):
        self.config_path, self.task_lock = config_path, task_lock
        self.run_slot = run_slot or threading.Lock()
        self.diagnostics, self.client_factory = diagnostics, client_factory
        self._lock = threading.RLock()
        self._worker = None
        self._stop = threading.Event()
        self._state = dict(phase='Idle', request_id=None, total=0, processed=0, results=[], activity=None)

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def state(self):
        import copy
        with self._lock:
            return copy.deepcopy(self._state)

    def start(self, paper_ids):
        ids = tuple(dict.fromkeys(UUID(str(value)) for value in paper_ids))
        if not ids:
            raise ValueError('Select one or more Papers')
        with self._lock:
            if self.running:
                raise ValueError('API completion is active')
            owner = self.task_lock.acquire('api-completion')
            if owner is None:
                raise ValueError('Another workflow is active')
            snapshot = None
            slot = False
            try:
                slot = self.run_slot.acquire(blocking=False)
                if not slot:
                    raise ValueError('A Run is active')
                snapshot = capture_run_workspace(self.config_path, create=False)
                if not snapshot.config.completion_providers:
                    raise ValueError('Select at least one API completion Provider')
                targets = tuple(read_paper_target(snapshot.config.output_dir, paper_id) for paper_id in ids)
                self._stop = threading.Event()
                self._state = dict(phase='Running', request_id=secrets.token_hex(16), total=len(ids),
                    processed=0, results=[], activity=None)
                observe(self.diagnostics, 'begin', 'api_completion', self._state['request_id'])
                self._worker = threading.Thread(target=self._run, args=(snapshot, owner, targets), name='api-completion', daemon=False)
                self._worker.start()
                return self.state()
            except BaseException:
                if snapshot:
                    snapshot.close()
                if slot:
                    self.run_slot.release()
                self.task_lock.release(owner)
                raise

    def _progress(self, event):
        with self._lock:
            if event.activity:
                self._state['activity'] = asdict(event.activity)

    def _run(self, snapshot, owner, targets):
        config = snapshot.config
        cache, pacing, clients = {}, {}, {}
        try:
            with snapshot, ExitStack() as stack:
                for provider in config.completion_providers:
                    if self._stop.is_set():
                        break
                    try:
                        key = read_credential(self.config_path)[0] if provider == 'openalex' else None
                        clients[provider] = stack.enter_context(self.client_factory(provider, api_key=key,
                            mailto=config.crossref_mailto, cancel_event=self._stop, pacing_state=pacing, progress_callback=self._progress))
                    except (ValueError, OSError):
                        pass  # Traversal reports the unavailable adapter per requested lookup.
                for target in targets:
                    result = dict(paper_id=str(target.paper_id), status='unchanged', saved_fields=[], lookups=[], issues=[])
                    try:
                        if self._stop.is_set():
                            result['status'] = 'cancelled'
                            continue
                        current = read_paper_target(target.workspace, target.paper_id)
                        state = parse_paper_state(current.path, current.original)
                        if state.status is WorkflowStatus.REJECTED:
                            result['status'] = 'excluded'
                            continue
                        if current != target:
                            raise ContentChangedError('Paper changed before API completion')
                        with commit_run_workspace(snapshot) as lock:
                            handoff = read_discovery_evidence(target.workspace, target.paper_id, operation_lock=lock)
                        completed = complete_metadata((saved_paper_evidence(target), *handoff.records),
                            config.completion_providers, clients=clients, cancel_event=self._stop, request_cache=cache)
                        result.update(lookups=[asdict(item) for item in completed.lookups], issues=[asdict(item) for item in completed.issues])
                        if completed.cancelled or self._stop.is_set():
                            result['status'] = 'cancelled'
                            continue
                        # Cancellation and the short commit share this task lock;
                        # an already-started atomic save settles before Cancel returns.
                        with self._lock, commit_run_workspace(snapshot, cancel_event=self._stop) as lock:
                            if read_paper_target(target.workspace, target.paper_id, operation_lock=lock) != target:
                                raise ContentChangedError('Paper changed; API completion was not saved')
                            fields = save_api_completion(target, completed.records, operation_lock=lock)
                            result.update(status='updated' if fields else 'unchanged', saved_fields=fields)
                            append_discovery_evidence(lock, target.paper_id,
                                (record for record in completed.records if record.provenance.provider != 'workspace'))
                    except TextWriteCommittedError:
                        result.update(status='updated', warning='Paper saved; filesystem sync failed')
                    except Exception as error:
                        if self._stop.is_set():
                            result['status'] = 'cancelled'
                        else:
                            result.update(status='failed', message=str(error) if isinstance(error, (ValueError, OSError, RuntimeError)) else 'API completion failed for this Paper')
                    finally:
                        with self._lock:
                            self._state['results'].append(result)
                            self._state['processed'] += 1
        except Exception:
            with self._lock:
                self._state.update(phase='Failed', message='API completion could not finish')
        finally:
            with self._lock:
                results = self._state['results']
                if self._state['phase'] != 'Failed':
                    self._state['phase'] = ('Cancelled' if self._stop.is_set() or any(item['status']=='cancelled' for item in results) else
                        'Partial' if any(item['status'] == 'failed' or item['issues'] for item in results) else 'Completed')
                self._state['activity'] = None
                lookups={(item['provider'],item['namespace'],item['identifier']):item['status'] for result in results for item in result['lookups']}
                observe(self.diagnostics, 'finish', self._state['request_id'], self._state['phase'].lower(),
                    statistics=dict(total=len(targets), processed=len(results), updated=sum(item['status'] == 'updated' for item in results),
                        unchanged=sum(item['status'] == 'unchanged' for item in results), failed=sum(item['status'] == 'failed' for item in results),
                        cancelled=sum(item['status'] == 'cancelled' for item in results), excluded=sum(item['status'] == 'excluded' for item in results),
                        no_match=sum(status=='no_match' for status in lookups.values()), lookup_failed=sum(status=='failed' for status in lookups.values()),
                        identity_mismatch=sum(status=='identity_mismatch' for status in lookups.values()), evidence=sum(status=='evidence' for status in lookups.values())),
                    details={'saved_fields':sorted({field for item in results for field in item['saved_fields']})})
                self.run_slot.release()
                self.task_lock.release(owner)

    def cancel(self, request_id):
        with self._lock:
            if not self.running or request_id != self._state['request_id']:
                return False
            self._stop.set()
            self._state['phase'] = 'Cancelling'
            return True

    def shutdown(self):
        self.cancel(self._state['request_id'])

    def join(self):
        if self._worker:
            self._worker.join()
