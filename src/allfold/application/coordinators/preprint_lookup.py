"""Cancellable single-Paper lookup; immutable authority crosses the worker boundary."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import secrets
import threading

from allfold.application.preprint_lookup import PREPRINT_SERVERS, require_lookup_doi, save_preprint_evidence
from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.config import ConfigurationError, load_config
from allfold.persistence.paper_repository import LibraryError, PaperRepository, StaleWriteError
from allfold.providers.supplemental import SupplementalClient


@dataclass(frozen=True)
class LookupCancellation:
    paper_id: object
    workspace_id: object
    request_id: str
    stop: threading.Event


class PreprintLookup:
    def __init__(self, config_path, task_lock, *, run_slot=None, client_factory=SupplementalClient,
                 pacing_state=None, workspace_tasks=None):
        self.config_path, self.task_lock = config_path, task_lock
        self.run_slot = run_slot or threading.Lock()
        self.client_factory = client_factory
        self.pacing_state = pacing_state if pacing_state is not None else {}
        self.workspace_tasks = workspace_tasks
        self._claim = self._reaper = None
        self._lock = threading.RLock()
        self._worker = None
        self._paper_id = None
        self._workspace_id = None
        self._stop = threading.Event()
        self._cancellation_target = None
        self._state = {}
        self._closed = False

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def cleaning_up(self, paper_id, workspace_id):
        with self._lock:
            return ((self.running or self._claim is not None and not self._claim.released)
                    and self._paper_id == paper_id and self._workspace_id == workspace_id)

    def state(self, paper_id, request_id=None):
        with self._lock:
            if paper_id != self._paper_id or request_id is not None and request_id != self._state.get('request_id'):
                return {'phase': 'Idle', 'request_id': None, 'message': '', 'saved_fields': []}
            state = {**self._state, 'saved_fields': list(self._state['saved_fields']), 'cleaning_up': self.cleaning_up(paper_id, self._workspace_id)}
            workspace_id, claim = self._workspace_id, self._claim
        if claim is not None:
            # The reservation transition and library revision share the Paper
            # gate; a settled cleanup flag cannot carry an older revision.
            try:
                with claim.registry.paper_gate():
                    state['cleaning_up'] = claim.registry.cleanup_pending(paper_id, workspace_id)
                    with PaperRepository.open(claim.registry.workspace, expected_workspace_id=workspace_id) as repository:
                        state['revision'] = repository.revision
            except (LibraryError, OSError):
                pass
            return state
        # Status carries no Paper payload and grants no write authority. Attach
        # the latest revision only after checking the currently bound library so
        # Reject/local edits cannot hide subsequent cancellation or cleanup.
        try:
            workspace = load_config(self.config_path).output_dir
            with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as repository:
                state['revision'] = repository.revision
        except (ConfigurationError, LibraryError, OSError):
            # A switched/reset/invalid library never adopts this old task.
            pass
        return state

    def start(self, paper_id, workspace_id=None):
        with self._lock:
            if self._closed:
                raise ValueError('Application is shutting down')
            if self.running or self._claim is not None and not self._claim.released:
                raise ValueError('A preprint lookup is active or cleaning up')
            owner = self.task_lock.acquire('preprint-lookup')
            if owner is None:
                raise ValueError('Another workflow is active')
            snapshot, slot, claim, reaper, started = None, False, None, None, threading.Event()
            settlement = {}
            try:
                slot = self.run_slot.acquire(blocking=False)
                if not slot:
                    raise ValueError('A Run is active')
                snapshot = capture_run_workspace(self.config_path, create=False)
                with commit_run_workspace(snapshot):
                    with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=workspace_id) as repository:
                        paper = repository.get(paper_id)
                        doi = require_lookup_doi(paper)
                        revision = repository.revision
                self._stop = threading.Event()
                if self.workspace_tasks is not None:
                    claim = self.workspace_tasks.claim_legacy(paper, cancel=self._stop.set)
                    with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=workspace_id) as repository:
                        revision = repository.revision
                state = dict(phase='Running', request_id=secrets.token_hex(16),
                    workspace_id=str(paper.workspace_id), revision=revision,
                    message='Looking up bioRxiv and medRxiv…', saved_fields=[])
                worker = threading.Thread(target=self._run, args=(snapshot, owner, paper, doi, settlement),
                                          name='preprint-lookup', daemon=False)
                self._paper_id, self._workspace_id, self._state = paper_id, paper.workspace_id, state
                self._worker, self._claim = worker, claim
                self._cancellation_target = LookupCancellation(paper_id, paper.workspace_id,
                    state['request_id'], self._stop)
                if claim is not None:
                    self._reaper = reaper = self.workspace_tasks.watch_legacy(worker, claim, started, settlement)
                try:
                    worker.start()
                    started.set()
                except BaseException:
                    self._worker, self._paper_id, self._workspace_id, self._state = None, None, None, {}
                    self._cancellation_target = None
                    raise
                return {**state, 'cleaning_up': True}
            except BaseException:
                try:
                    cleanups = []
                    if snapshot is not None:
                        cleanups.append(('legacy-snapshot-cleanup', snapshot.close))
                    if slot:
                        cleanups.append(('legacy-owner-cleanup', self.run_slot.release))
                    cleanups.append(('legacy-owner-cleanup', lambda: self.task_lock.release(owner)))
                    for phase, cleanup in cleanups:
                        try:
                            cleanup()
                        except Exception as error:
                            settlement.setdefault('failure', (phase, error))
                    if claim is not None and reaper is None:
                        failure = settlement.get('failure')
                        if failure is None:
                            self.workspace_tasks.release_legacy(claim)
                        else:
                            phase, error = failure
                            claim.registry.fail_reservation(claim, phase=phase, error=error)
                finally:
                    # A never-started worker's reaper must not release the claim
                    # before its snapshot/slot/browser rollback has completed.
                    started.set()
                raise

    @staticmethod
    @contextmanager
    def _resource(resource, settlement, phase):
        stack = ExitStack()
        try:
            yield stack.enter_context(resource)
        finally:
            try:
                stack.close()
            except Exception as error:
                settlement['failure'] = (phase, error)
                raise

    def _run(self, snapshot, owner, paper, doi, settlement):
        def require_target(repository):
            self.task_lock.require(owner)
            current = repository.get(paper.id)
            # Do not compare abstract generation: a local edit invalidates that
            # field's candidates while independent Preprint proof remains valid.
            if (current.excluded or current.metadata is None
                    or current.metadata_generation != paper.metadata_generation
                    or current.operation_generation != paper.operation_generation):
                raise StaleWriteError('Paper qualification changed during preprint lookup')

        def request_guard():
            with commit_run_workspace(snapshot, cancel_event=self._stop):
                with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=paper.workspace_id) as repository:
                    require_target(repository)

        try:
            with self._resource(snapshot, settlement, 'legacy-snapshot-cleanup'):
                records, pacing = [], self.pacing_state
                for provider in PREPRINT_SERVERS:
                    resource = self.client_factory(provider, cancel_event=self._stop, pacing_state=pacing)
                    with self._resource(resource, settlement, 'legacy-client-cleanup') as client:
                        client.request_guard = request_guard
                        records.extend(client.lookup_published_preprints(doi))
                with commit_run_workspace(snapshot, cancel_event=self._stop):
                    with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=paper.workspace_id) as repository:
                        require_target(repository)
                        fields = []
                        if records:
                            _, fields = save_preprint_evidence(repository, paper, records)
                            phase = 'Completed'
                            message = 'Preprint evidence saved' if fields else 'Preprint evidence already saved'
                        else:
                            phase, message = 'NoMatch', 'No matching bioRxiv or medRxiv preprint'
                        revision = repository.revision
                with self._lock:
                    self._state.update(phase=phase, message=message, saved_fields=fields, revision=revision)
        except Exception as error:
            with self._lock:
                self._state.update(phase='Cancelled' if self._stop.is_set() else 'Failed',
                    message='Preprint lookup cancelled' if self._stop.is_set() else str(error) or 'Preprint lookup failed')
        finally:
            try:
                self.run_slot.release()
                self.task_lock.release(owner)
            except Exception as error:
                settlement['failure'] = ('legacy-owner-cleanup', error)
                with self._lock:
                    self._state.update(phase='Failed', message='Preprint cleanup could not be confirmed')

    def cancel(self, paper_id, request_id, workspace_id=None):
        with self._lock:
            if (paper_id != self._paper_id or request_id != self._state.get('request_id')
                    or workspace_id is not None and workspace_id != self._workspace_id
                    or not self.running or self._state.get('phase') not in {'Running', 'Cancelling'}):
                return False
            self._stop.set()
            self._state.update(phase='Cancelling', message='Stopping preprint lookup…')
            return True

    def cancel_paper(self, paper_id, workspace_id):
        with self._lock:
            if paper_id != self._paper_id or workspace_id != self._workspace_id or not self.running:
                return False
            return self.cancel(paper_id, self._state.get('request_id'), workspace_id)

    def prepare_cancel_paper(self, paper_id, workspace_id):
        # start takes the coordinator lock before the Paper gate. This immutable
        # published request needs no coordinator lock or callback under that gate.
        target = self._cancellation_target
        if target is None or target.paper_id != paper_id or target.workspace_id != workspace_id:
            return None
        target.stop.set()
        return target

    def signal_cancel_target(self, target):
        with self._lock:
            if (target is not self._cancellation_target or not self.running
                    or self._state.get('phase') not in {'Running', 'Cancelling'}):
                return False
            target.stop.set()
            self._state.update(phase='Cancelling', message='Stopping preprint lookup…')
            return True

    def shutdown(self):
        with self._lock:
            self._closed = True
            self.cancel(self._paper_id, self._state.get('request_id'))

    def join(self):
        with self._lock:
            worker, reaper = self._worker, self._reaper
        if worker and worker is not threading.current_thread():
            worker.join()
        if reaper and reaper is not threading.current_thread():
            reaper.join()
