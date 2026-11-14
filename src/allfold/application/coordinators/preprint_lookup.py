"""Workspace-owned explicit Preprint requests over bounded Paper workers."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import secrets
import threading
from uuid import UUID

from allfold.application.preprint_lookup import PREPRINT_SERVERS, require_lookup_doi, save_preprint_evidence
from allfold.application.task_clients import IndependentClientFactory
from allfold.application.workspace_tasks import WorkspaceTaskHost
from allfold.config import ConfigurationError, load_config
from allfold.persistence.paper_repository import InvalidPaperState, LibraryError, PaperRepository


@dataclass(eq=False)
class LookupOperation:
    paper: object
    doi: str
    reservation: object
    request_id: str = field(default_factory=lambda: secrets.token_hex(16))
    state: dict = field(default_factory=dict)


class PreprintLookup:
    def __init__(self, config_path, task_lock, *, client_factory=None,
                 pacing_state=None, workspace_tasks=None):
        self.config_path, self.task_lock = config_path, task_lock
        self._owns_host = workspace_tasks is None
        self.workspace_tasks = workspace_tasks or WorkspaceTaskHost(config_path,
            browser_lock=task_lock, pacing_state=pacing_state)
        self.clients = (IndependentClientFactory(config_path, pacing_state=pacing_state,
            client_factory=client_factory) if client_factory is not None else self.workspace_tasks.factory)
        self._lock = threading.RLock()
        self._operations, self._latest = {}, {}
        self._closed = False

    @property
    def running(self):
        with self._lock:
            return any(not operation.reservation.future.done() for operation in self._operations.values())

    def cleaning_up(self, paper_id, workspace_id):
        return self.workspace_tasks.cleanup_pending(paper_id, workspace_id)

    def _operation(self, paper_id, request_id=None, workspace_id=None):
        paper_id = UUID(str(paper_id))
        if workspace_id is None:
            matches = [operation for (workspace, target), operation in self._latest.items() if target == paper_id]
            operation = matches[0] if len(matches) == 1 else None
            if operation is None:
                return None
            workspace_id = operation.paper.workspace_id
        key = UUID(str(workspace_id)), paper_id
        if request_id is None:
            return self._latest.get(key)
        return self._operations.get((*key, request_id))

    def state(self, paper_id, request_id=None, workspace_id=None):
        # The public route supplies Workspace identity. Reading never binds a
        # registry, creates a library, or adopts a request from another Workspace.
        revision = None
        try:
            workspace = load_config(self.config_path).output_dir
        except (ConfigurationError, LibraryError, OSError):
            if workspace_id is not None:
                raise
            workspace = None
        if workspace_id is not None:
            with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as repository:
                repository.get(paper_id)
                revision = repository.revision
        with self._lock:
            operation = self._operation(paper_id, request_id, workspace_id)
            if operation is None:
                return dict(phase='Idle', request_id=None, workspace_id=str(workspace_id) if workspace_id else None,
                            message='', saved_fields=[], cleaning_up=False, revision=revision)
            state = {**operation.state, 'saved_fields': list(operation.state['saved_fields'])}
            claim = operation.reservation
        # Release/revision share the Paper gate. A settled flag must not carry a
        # revision from before that projection change.
        try:
            with claim.registry.paper_gate():
                state['cleaning_up'] = not claim.released
                if workspace is not None:
                    with PaperRepository.open(workspace, expected_workspace_id=claim.workspace_id) as repository:
                        state['revision'] = repository.revision
        except (LibraryError, OSError):
            pass
        return state

    def start(self, paper_id, workspace_id=None):
        with self.workspace_tasks.settings_lock, self._lock:
            if self._closed:
                raise ValueError('Application is shutting down')
            registry = self.workspace_tasks.current()
            with PaperRepository.open(registry.workspace, expected_workspace_id=workspace_id) as repository:
                paper = repository.get(paper_id)
                doi = require_lookup_doi(paper)
            existing = self._latest.get((paper.workspace_id, paper.id))
            if existing is not None and not existing.reservation.released:
                return self.state(paper.id, existing.request_id, paper.workspace_id)
            claim = registry.reserve(paper.id, kind='legacy', expected_token=paper.token,
                                     providers=PREPRINT_SERVERS, deadline=registry._deadline(None))
            operation = LookupOperation(paper, doi, claim)
            claim.cancel = lambda: self._mark_cancelling(operation)
            try:
                owner = self.task_lock.acquire('preprint-lookup', shared=True)
                if owner is None:
                    raise InvalidPaperState('Another Browser control is active')
                claim.browser_owner = owner
                with registry.paper_gate(), registry._repository() as repository:
                    registry._require_live(claim)
                    operation.state = dict(phase='Running', request_id=operation.request_id,
                        workspace_id=str(paper.workspace_id), revision=repository.revision,
                        message='Looking up bioRxiv and medRxiv…', saved_fields=[], cleaning_up=True)
                    key = paper.workspace_id, paper.id
                    self._latest[key] = operation
                    self._operations[(*key, operation.request_id)] = operation
                    claim.scheduled = registry._scheduler.submit(None,
                        lambda: self._run(operation), cancel_event=claim.cancel_event,
                        deadline=claim.deadline, discarded=lambda reason: self._discard(operation, reason))
                    claim.scheduled.add_done_callback(lambda actual: self._settled(operation, actual))
                return dict(operation.state)
            except BaseException as error:
                operation.state.update(phase='Failed', message='Preprint work could not be submitted')
                try:
                    self._release_owner(claim)
                    if not claim.cleanup_failed:
                        registry.release(claim)
                except BaseException as failure:
                    error = failure
                finally:
                    if not claim.future.done():
                        claim.future.set_exception(error)
                raise

    @staticmethod
    @contextmanager
    def _resource(resource, claim, phase):
        value = resource.__enter__()
        try:
            yield value
        finally:
            try:
                resource.__exit__(None, None, None)
            except BaseException as error:
                claim.registry.fail_reservation(claim, phase=phase, error=error)
                raise

    def _run(self, operation):
        claim, paper = operation.reservation, operation.paper
        try:
            with self._resource(claim.registry._repository(), claim, 'preprint-repository-cleanup') as repository:
                claim.guard()
                records = []
                with self._resource(self.clients.open(cancel_event=claim.cancel_event,
                        request_guard=claim.guard, deadline=claim.deadline, providers=PREPRINT_SERVERS),
                        claim, 'preprint-client-cleanup') as clients:
                    for provider in PREPRINT_SERVERS:
                        records.extend(clients.provider(provider).lookup_published_preprints(operation.doi))
                claim.guard()
                with claim.registry.paper_gate():
                    claim.registry._require_live(claim)
                    claim.registry._require_reservation(claim, repository)
                    fields = []
                    if records:
                        _, fields = save_preprint_evidence(repository, paper, records)
                        phase = 'Completed'
                        message = 'Preprint evidence saved' if fields else 'Preprint evidence already saved'
                    else:
                        phase, message = 'NoMatch', 'No matching bioRxiv or medRxiv preprint'
                    revision = repository.revision
                with self._lock:
                    operation.state.update(phase=phase, message=message, saved_fields=fields, revision=revision)
        except Exception as error:
            with self._lock:
                cancelled = claim.cancel_event.is_set() and not claim.cleanup_failed
                operation.state.update(phase='Cancelled' if cancelled else 'Failed',
                    message='Preprint lookup cancelled' if cancelled else str(error) or 'Preprint lookup failed')
        finally:
            self._release_owner(claim)

    def _release_owner(self, claim):
        if claim.browser_owner is not None and not claim.cleanup_failed:
            try:
                self.task_lock.release(claim.browser_owner)
                claim.browser_owner = None
            except BaseException as error:
                claim.registry.fail_reservation(claim, phase='preprint-owner-cleanup', error=error)
                raise

    def _discard(self, operation, reason):
        with self._lock:
            failed = reason == 'submission_failed'
            operation.state.update(phase='Failed' if failed else 'Cancelled',
                                   message='Preprint work could not be submitted' if failed else 'Preprint lookup cancelled')
        self._release_owner(operation.reservation)

    def _settled(self, operation, actual):
        claim = operation.reservation
        error = None
        try:
            actual.result()
            if claim.cleanup_failed:
                raise RuntimeError('Preprint cleanup could not be confirmed')
            claim.registry.release(claim)
        except BaseException as failure:
            error = failure
            with self._lock:
                operation.state.update(phase='Failed', message='Preprint cleanup could not be confirmed')
        if error is None:
            claim.future.set_result(dict(operation.state))
        else:
            claim.future.set_exception(error)

    def _mark_cancelling(self, operation):
        with self._lock:
            if operation.state.get('phase') not in {'Running', 'Cancelling'}:
                return False
            operation.state.update(phase='Cancelling', message='Stopping preprint lookup…')
            return True

    def cancel(self, paper_id, request_id, workspace_id=None):
        with self._lock:
            operation = self._operation(paper_id, request_id, workspace_id)
            if (operation is None or request_id is None or operation.reservation.future.done()
                    or operation.state.get('phase') not in {'Running', 'Cancelling'}):
                return False
        return operation.reservation.registry._cancel_target(operation.reservation)

    def shutdown(self):
        with self._lock:
            self._closed = True
            operations = tuple(self._operations.values())
        for operation in operations:
            operation.reservation.registry._cancel_target(operation.reservation)
        if self._owns_host:
            self.workspace_tasks.shutdown()

    def join(self):
        with self._lock:
            operations = tuple(self._operations.values())
        for operation in operations:
            try:
                operation.reservation.future.result()
            except Exception:
                # The host reports conservative occupancy and recorded faults.
                pass
        if self._closed:
            if self.clients is not self.workspace_tasks.factory:
                self.clients.close()
            if self._owns_host:
                self.workspace_tasks.join()
