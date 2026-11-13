"""Cancellable single-Paper lookup; immutable authority crosses the worker boundary."""
import secrets
import threading

from allfold.application.preprint_lookup import PREPRINT_SERVERS, require_lookup_doi, save_preprint_evidence
from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.config import ConfigurationError, load_config
from allfold.persistence.paper_repository import LibraryError, PaperRepository, StaleWriteError
from allfold.providers.supplemental import SupplementalClient


class PreprintLookup:
    def __init__(self, config_path, task_lock, *, run_slot=None, client_factory=SupplementalClient):
        self.config_path, self.task_lock = config_path, task_lock
        self.run_slot = run_slot or threading.Lock()
        self.client_factory = client_factory
        self._lock = threading.RLock()
        self._worker = None
        self._paper_id = None
        self._workspace_id = None
        self._stop = threading.Event()
        self._state = {}
        self._closed = False

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def cleaning_up(self, paper_id, workspace_id):
        with self._lock:
            return self.running and self._paper_id == paper_id and self._workspace_id == workspace_id

    def state(self, paper_id, request_id=None):
        with self._lock:
            if paper_id != self._paper_id or request_id is not None and request_id != self._state.get('request_id'):
                return {'phase': 'Idle', 'request_id': None, 'message': '', 'saved_fields': []}
            state = {**self._state, 'saved_fields': list(self._state['saved_fields']), 'cleaning_up': self.running}
            workspace_id = self._workspace_id
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
            if self.running:
                raise ValueError('A preprint lookup is active or cleaning up')
            owner = self.task_lock.acquire('preprint-lookup')
            if owner is None:
                raise ValueError('Another workflow is active')
            snapshot, slot = None, False
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
                state = dict(phase='Running', request_id=secrets.token_hex(16),
                    workspace_id=str(paper.workspace_id), revision=revision,
                    message='Looking up bioRxiv and medRxiv…', saved_fields=[])
                worker = threading.Thread(target=self._run, args=(snapshot, owner, paper, doi),
                                          name='preprint-lookup', daemon=False)
                self._paper_id, self._workspace_id, self._state = paper_id, paper.workspace_id, state
                self._worker = worker
                try:
                    worker.start()
                except BaseException:
                    self._worker, self._paper_id, self._workspace_id, self._state = None, None, None, {}
                    raise
                return self.state(paper_id)
            except BaseException:
                if snapshot is not None:
                    snapshot.close()
                if slot:
                    self.run_slot.release()
                self.task_lock.release(owner)
                raise

    def _run(self, snapshot, owner, paper, doi):
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
            with snapshot:
                records, pacing = [], {}
                for provider in PREPRINT_SERVERS:
                    with self.client_factory(provider, cancel_event=self._stop, pacing_state=pacing) as client:
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
            self.run_slot.release()
            if self.task_lock.owner is owner:
                self.task_lock.release(owner)

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

    def shutdown(self):
        with self._lock:
            self._closed = True
            self.cancel(self._paper_id, self._state.get('request_id'))

    def join(self):
        with self._lock:
            worker = self._worker
        if worker and worker is not threading.current_thread():
            worker.join()
