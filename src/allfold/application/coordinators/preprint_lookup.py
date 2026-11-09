"""Cancellable single-Paper lookup with shared workflow admission."""
import secrets
import threading

from allfold.application.paper_enrichment import read_paper_target
from allfold.application.preprint_lookup import PREPRINT_SERVERS, require_lookup_doi, save_preprint_evidence
from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
from allfold.persistence.safe_write import ContentChangedError, TextWriteCommittedError
from allfold.providers.supplemental import SupplementalClient


class PreprintLookup:
    def __init__(self, config_path, task_lock, *, run_slot=None, client_factory=SupplementalClient):
        self.config_path, self.task_lock = config_path, task_lock
        self.run_slot = run_slot or threading.Lock()
        self.client_factory = client_factory
        self._lock = threading.RLock()
        self._worker = None
        self._paper_id = None
        self._stop = threading.Event()
        self._state = {}

    @property
    def running(self):
        return self._worker is not None and self._worker.is_alive()

    def state(self, paper_id, request_id=None):
        with self._lock:
            if paper_id != self._paper_id or request_id is not None and request_id != self._state.get('request_id'):
                return {'phase': 'Idle', 'request_id': None, 'message': '', 'saved_fields': []}
            return {**self._state, 'saved_fields': list(self._state['saved_fields'])}

    def start(self, paper_id):
        with self._lock:
            if self.running:
                raise ValueError('A preprint lookup is active')
            owner = self.task_lock.acquire('preprint-lookup')
            if owner is None:
                raise ValueError('Another workflow is active')
            snapshot = None
            slot = False
            try:
                slot = self.run_slot.acquire(blocking=False)
                if not slot:
                    raise ValueError('A Run is active')
                snapshot = capture_run_workspace(self.config_path, create=False)
                with commit_run_workspace(snapshot) as lock:
                    target = read_paper_target(snapshot.config.output_dir, paper_id, operation_lock=lock)
                    doi = require_lookup_doi(target)
                self._stop = threading.Event()
                state = dict(phase='Running', request_id=secrets.token_hex(16),
                    message='Looking up bioRxiv and medRxiv…', saved_fields=[])
                worker = threading.Thread(target=self._run, args=(snapshot, owner, target, doi),
                                          name='preprint-lookup', daemon=False)
                worker.start()
                self._worker, self._paper_id, self._state = worker, paper_id, state
                return self.state(paper_id)
            except BaseException:
                if snapshot is not None:
                    snapshot.close()
                if slot:
                    self.run_slot.release()
                self.task_lock.release(owner)
                raise

    def _run(self, snapshot, owner, target, doi):
        def require_target(lock):
            self.task_lock.require(owner)
            if read_paper_target(target.workspace, target.paper_id, operation_lock=lock) != target:
                raise ContentChangedError('Paper changed during preprint lookup')

        def request_guard():
            with commit_run_workspace(snapshot, cancel_event=self._stop) as lock:
                require_target(lock)

        fields = []
        try:
            with snapshot:
                records, pacing = [], {}
                for provider in PREPRINT_SERVERS:
                    with self.client_factory(provider, cancel_event=self._stop, pacing_state=pacing) as client:
                        client.request_guard = request_guard
                        records.extend(client.lookup_published_preprints(doi))
                # Once an atomic commit begins, it settles before cancellation
                # can report success. No Workspace lock is held during HTTP.
                with self._lock:
                    try:
                        with commit_run_workspace(snapshot, cancel_event=self._stop) as lock:
                            require_target(lock)
                            if records:
                                fields = save_preprint_evidence(target, records, operation_lock=lock)
                                phase = 'Completed'
                                message = 'Preprint evidence saved' if fields else 'Preprint evidence already saved'
                            else:
                                phase, message = 'NoMatch', 'No matching bioRxiv or medRxiv preprint'
                    except TextWriteCommittedError as error:
                        phase, message = 'Completed', 'Preprint evidence saved; filesystem sync failed'
                        fields = error.saved_fields
                    self._state.update(phase=phase, message=message, saved_fields=fields)
        except Exception as error:
            with self._lock:
                if self._stop.is_set():
                    self._state.update(phase='Cancelled', message='Preprint lookup cancelled')
                else:
                    self._state.update(phase='Failed', message=str(error) or 'Preprint lookup failed')
        finally:
            with self._lock:
                self.run_slot.release()
                if self.task_lock.owner is owner:
                    self.task_lock.release(owner)

    def cancel(self, paper_id, request_id):
        with self._lock:
            if (paper_id != self._paper_id or request_id != self._state.get('request_id')
                    or self._state.get('phase') != 'Running'):
                return False
            self._stop.set()
            self._state.update(phase='Cancelling', message='Stopping preprint lookup…')
            return True

    def shutdown(self):
        with self._lock:
            self.cancel(self._paper_id, self._state.get('request_id'))

    def join(self):
        with self._lock:
            worker = self._worker
        if worker:
            worker.join()
