"""Workspace-owned collection attempts, Paper admission and real resource settlement.

The scheduler counts executing Paper jobs (including client/native cleanup), not
pages. Physical page admission remains the shared native Session's responsibility.
No production collector is installed here; callers supply a complete bounded plan.
"""
from __future__ import annotations

from concurrent.futures import Future
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
import re
import threading
import time
from uuid import UUID, uuid4

from allfold.application.dynamic_dispatch import DynamicScheduler, SettledFuture
from allfold.application.history import observe
from allfold.application.browser_services import browser_workspace_identity
from allfold.application.task_authority import NativeAccessBinding
from allfold.persistence.library_database import DATABASE_NAME
from allfold.persistence.paper_repository import (
    CollectionToken, InvalidPaperState, MetadataDelta, PaperRepository, StaleWriteError,
)
from allfold.providers.integrated import PROVIDERS


_INHERIT_SERVICE = object()


@dataclass(frozen=True)
class BranchSpec:
    name: str
    run: object = None
    skip_reason: str | None = None
    providers: tuple[str, ...] = ()
    # Omitted inherits the legacy plan Service; explicit None is independent API.
    service_id: object = _INHERIT_SERVICE
    mailto: str = ''


@dataclass(eq=False)
class TaskHandle:
    token: CollectionToken
    branches: tuple[BranchSpec, ...]
    authority: object
    deadline: float
    service_id: str | None = None
    source_run_id: str | None = None
    workflow_id: str = field(default_factory=lambda: uuid4().hex)
    task_id: str = field(default_factory=lambda: uuid4().hex)
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future = field(default_factory=SettledFuture)
    registered: bool = False
    scheduled: Future | None = None
    browser_owner: object = None
    cancel_pending: bool = False
    branch_tasks: tuple = ()
    waiting_on: object = None
    dispatch_ready: threading.Event = field(default_factory=threading.Event)

    @property
    def paper_id(self):
        return self.token.paper_id

    @property
    def workspace_id(self):
        return self.token.workspace_id

    @property
    def lifecycle_id(self):
        return self.token.lifecycle_id

    @property
    def providers(self):
        return tuple(sorted({provider for branch in self.branches for provider in branch.providers}))


@dataclass(eq=False)
class _BranchTask:
    parent: TaskHandle
    branch: BranchSpec
    authority_captured: bool = False
    admission_check: object = None
    admission_error: object = None
    authority: object = field(default_factory=lambda: _LocalAuthority())
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future = field(default_factory=SettledFuture)
    scheduled: Future | None = None
    browser_owner: object = None
    workflow_id: str = field(default_factory=lambda: uuid4().hex)
    task_id: str = field(default_factory=lambda: uuid4().hex)

    @property
    def token(self):
        return self.parent.token
    @property
    def paper_id(self):
        return self.parent.paper_id
    @property
    def workspace_id(self):
        return self.parent.workspace_id
    @property
    def lifecycle_id(self):
        return self.parent.lifecycle_id
    @property
    def deadline(self):
        return self.parent.deadline
    @property
    def service_id(self):
        return self.branch.service_id
    @property
    def providers(self):
        return self.branch.providers


@dataclass(eq=False)
class PaperReservation:
    registry: object
    token: object
    lifecycle_id: UUID
    kind: str
    cancel: object = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    workflow_id: str = field(default_factory=lambda: uuid4().hex)
    task_id: str = field(default_factory=lambda: uuid4().hex)
    released: bool = False
    cleanup_ended: bool = False
    cleanup_failed: bool = False
    # Defaults keep legacy/manual reservations independent of discovery clients.
    authority: object = field(default_factory=lambda: _LocalAuthority())
    service_id: str | None = None
    providers: tuple[str, ...] = ()
    deadline: float = float('inf')
    future: Future = field(default_factory=SettledFuture)
    scheduled: Future | None = None
    browser_owner: object = None
    download_token: object = None
    body_request: object = field(default=None, repr=False)

    def guard(self):
        """Verify this exact reservation without capturing a replacement token."""
        self.registry._guard(self)

    @property
    def paper_id(self):
        return self.token.paper_id

    @property
    def workspace_id(self):
        return self.token.workspace_id


class _LocalAuthority:
    service_id = service_scope = None

    def verify(self):
        pass

    def native_access(self):
        return NativeAccessBinding()


class _CleanupUnconfirmed(RuntimeError):
    """Execution stopped, but real resource disposal could not be established."""


class BranchContext:
    """One branch's captured writes and execution-owned clients/native requests.

    emit sequences are explicit, positive and local to this branch/attempt.
    Repeated delivery of the same sequence remains a repository no-op. Native
    Futures must be registered here, including when a branch returns early.
    """

    def __init__(self, registry, handle, repository, clients, branch, native):
        self._registry, self._handle, self._repository = registry, handle, repository
        self._clients, self._branch, self._native = clients, branch, native
        self._branch_native = []
        self._sequence = 0
        self.cancel_event, self.deadline = handle.cancel_event, handle.deadline
        self.token = handle.token
        self.workflow_id, self.task_id = handle.workflow_id, handle.task_id

    def guard(self):
        self._registry._guard(self._handle, self._repository)

    def provider(self, name):
        if name not in self._branch.providers:
            raise InvalidPaperState('Provider was not declared in this branch plan')
        self.guard()
        return self._clients.provider(name)

    def read_paper(self):
        """Read the current projection without renewing captured field eligibility."""
        self.guard()
        with self._registry.paper_gate():
            self._registry._require_live(self._handle)
            return self._repository.require_collection(self.token)

    def native_payload(self):
        """Project captured access/Workspace identity within the remaining parent budget."""
        self.guard()
        access = self._handle.authority.native_access()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Collection parent deadline expired')
        return access.payload() | dict(
            workspace_identity=browser_workspace_identity(self._registry.workspace, self._registry._identity[0]),
            paper_id=str(self.token.paper_id), deadline_ms=int((time.time() + remaining) * 1000))

    def emit(self, delta, *, sequence, direct_ids=None):
        self.guard()
        with self._registry.paper_gate():
            self._registry._require_live(self._handle)
            result = self._repository.commit_collection_branch(self.token, self._branch.name,
                sequence=sequence, delta=delta, direct_ids=direct_ids)
            self._sequence = max(self._sequence, sequence)
            return result

    def track_native(self, future):
        if not isinstance(future, Future):
            raise TypeError('Native operations require a real Future')
        self._native.append(future)
        self._branch_native.append(future)
        protected = SettledFuture()

        def terminal(actual):
            try:
                protected.set_result(actual.result())
            except BaseException as error:
                protected.set_exception(error)

        future.add_done_callback(terminal)
        return protected

    def execute_native(self, action, data, *, progress=None):
        self.guard()
        if self._registry.bridge is None:
            raise RuntimeError('No native bridge is available')
        if action == 'release_workflow_pages':
            raise ValueError('Workflow cleanup is owned by the registry')
        self._registry._ensure_browser_owner(self._handle)
        with self._registry.paper_gate():
            self._registry._require_live(self._handle)
            self._repository.require_collection(self.token)
            future = self._registry.bridge.execute(action,
                dict(data) | {'workflow_id': self.workflow_id, 'task_id': self.task_id},
                progress, verify_recovery=lambda: self._registry._guard(self._handle))
            return self.track_native(future)

    def _finish(self, outcome, *, reason=None, delta=None):
        # Failure/cancellation settlement uses the captured attempt even after
        # Reject/authority invalidation; no metadata is written on that path.
        self._sequence += 1
        if outcome in {'completed', 'skipped'}:
            for future in self._branch_native:
                if future.cancelled():
                    raise _CleanupUnconfirmed('Native Future cancellation is not branch settlement')
                future.result()
            self.guard()
        with self._registry.paper_gate():
            if outcome in {'completed', 'skipped'}:
                self._registry._require_live(self._handle)
            return self._repository.commit_collection_branch(self.token, self._branch.name,
                sequence=self._sequence, delta=delta, outcome=outcome, reason=reason)


class WorkspaceRegistry:
    def __init__(self, workspace, *, factory, browser_lock=None, bridge=None,
                 diagnostics=None, admission_lock=None, authority_capture=None, admission_capture=None,
                 limit=4, group_limit=2):
        self.workspace = Path(workspace).absolute()
        self.factory, self.browser_lock, self.bridge = factory, browser_lock, bridge
        self.diagnostics = diagnostics
        self._gate = admission_lock if admission_lock is not None else threading.RLock()
        self._authority_capture = authority_capture
        self._admission_capture = admission_capture
        self.lifecycle_id = uuid4()
        self._stopped = False
        self._shutdown_started = False
        self._tasks, self._reservations, self._faults = {}, {}, []
        self._settled_condition = threading.Condition(self._gate)
        with PaperRepository.open(self.workspace) as repository:
            self.workspace_id = repository.workspace_id
            self._identity = self._path_identity()
            repository.interrupt_collections(self.lifecycle_id)
            repository.interrupt_downloads(self.lifecycle_id)
        self._scheduler = DynamicScheduler(limit=limit, group_limit=group_limit)
        # Parent workers may wait for these bounded children, never their own pool.
        self._branch_scheduler = DynamicScheduler(limit=max(2, limit), group_limit=group_limit)

    def _path_identity(self):
        return tuple((info.st_dev, info.st_ino) for info in
                     (self.workspace.stat(), (self.workspace / DATABASE_NAME).stat()))

    @contextmanager
    def _repository(self):
        if self._identity != self._path_identity():
            raise StaleWriteError('Workspace path or database was replaced')
        with PaperRepository.open(self.workspace, expected_workspace_id=self.workspace_id) as repository:
            if self._identity != self._path_identity():
                raise StaleWriteError('Workspace path or database was replaced')
            yield repository

    def paper_gate(self):
        return self._gate

    @property
    def stopped(self):
        with self._gate:
            return self._stopped

    @property
    def faults(self):
        with self._gate:
            return tuple(dict(fault) for fault in self._faults)

    @property
    def active(self):
        with self._gate:
            return bool(self._tasks or self._reservations)

    @property
    def browser_owner_ids(self):
        with self._gate:
            return frozenset(task.browser_owner.id for task in (*self._branch_tasks(), *self._reservations.values())
                             if task.browser_owner is not None)

    def _branch_tasks(self):
        return tuple(branch for task in self._tasks.values() for branch in task.branch_tasks)

    def busy(self, paper_id, workspace_id=None):
        if workspace_id is not None and UUID(str(workspace_id)) != self.workspace_id:
            return False
        with self._gate:
            return UUID(str(paper_id)) in self._tasks or UUID(str(paper_id)) in self._reservations

    cleanup_pending = busy

    @staticmethod
    def _plan(branches, no_applicable=False, service_id=None):
        plan = tuple(branches)
        if not plan and not no_applicable:
            raise ValueError('An empty plan requires explicit no_applicable=True')
        if len(plan) > 16:
            raise ValueError('Collection plans have at most 16 branches')
        names = set()
        for branch in plan:
            if (not isinstance(branch, BranchSpec) or not isinstance(branch.name, str)
                    or re.fullmatch(r'[a-zA-Z0-9_.-]{1,64}', branch.name) is None or branch.name in names):
                raise ValueError('Collection branches require unique bounded names')
            names.add(branch.name)
            if (branch.skip_reason is not None and (not isinstance(branch.skip_reason, str)
                    or not branch.skip_reason or len(branch.skip_reason) > 240 or branch.run is not None)):
                raise ValueError('A skipped branch needs only a bounded applicability reason')
            if branch.run is not None and not callable(branch.run):
                raise ValueError('Branch execution must be callable')
            if any(provider not in PROVIDERS for provider in branch.providers):
                raise ValueError('Unknown declared Provider')
        return tuple(BranchSpec(branch.name, branch.run, branch.skip_reason,
                                tuple(sorted(set(branch.providers))),
                                service_id if branch.service_id is _INHERIT_SERVICE else branch.service_id,
                                branch.mailto) for branch in plan)

    def _authority(self, service_id, plan):
        providers = tuple(sorted({provider for branch in plan for provider in branch.providers}))
        if self._authority_capture is None:
            if service_id is not None or providers:
                raise InvalidPaperState('Service/Provider work requires captured authority')
            authority = _LocalAuthority()
        else:
            authority = self._authority_capture(service_id, providers)
        if (authority is None or authority.service_id != service_id
                or service_id is not None and not authority.service_scope):
            raise InvalidPaperState('Service work requires a trustworthy scoped authority')
        authority.verify()  # Never call configuration/credential code under Paper gate.
        return authority

    @staticmethod
    def _deadline(deadline):
        value = time.monotonic() + 600 if deadline is None else float(deadline)
        if not 0 < value < float('inf'):
            raise ValueError('A finite absolute parent deadline is required')
        return value

    def _require_open(self):
        if self._stopped:
            raise InvalidPaperState('Workspace task admission is closed')

    @staticmethod
    def _check_admission(authority):
        # Host epoch/latch checks are process-local and must perform no I/O or
        # acquire configuration/Login locks while the Paper gate is held.
        check = getattr(authority, 'admission_check', None)
        if check is not None:
            check()

    def _require_live(self, handle):
        self._require_open()
        self._check_admission(handle.authority)
        if isinstance(handle, _BranchTask) and handle.admission_check is not None:
            handle.admission_check()
        parent = handle.parent if isinstance(handle, _BranchTask) else handle
        owners = self._reservations if isinstance(handle, PaperReservation) else self._tasks
        if (owners.get(handle.paper_id) is not parent or handle.lifecycle_id != self.lifecycle_id
                or handle.cancel_event.is_set() or parent.cancel_event.is_set()):
            raise StaleWriteError('Captured Paper task owner is no longer valid')
        if time.monotonic() >= handle.deadline:
            raise TimeoutError('Paper task parent deadline expired')

    def _guard(self, handle, repository=None):
        try:
            handle.authority.verify()
        except Exception as error:
            raise StaleWriteError('Captured access authority was revoked') from error
        with self._gate:
            self._require_live(handle)
            if isinstance(handle, PaperReservation):
                if self._identity != self._path_identity():
                    raise StaleWriteError('Workspace path or database was replaced')
                if repository is None:
                    with self._repository() as current:
                        self._require_reservation(handle, current)
                else:
                    self._require_reservation(handle, repository)
                return
            if repository is not None:
                repository.require_collection(handle.token)
            else:
                with self._repository() as current:
                    current.require_collection(handle.token)

    def _require_reservation(self, handle, repository):
        paper = repository.get(handle.paper_id)
        deferred = self._tasks.get(handle.paper_id)
        waiting = deferred is not None and deferred.waiting_on is handle
        if handle.kind == 'body':
            return repository.require_download(handle.download_token)
        if (handle.kind == 'download' and paper.token != handle.token
                or paper.metadata_generation != handle.token.metadata_generation
                or paper.operation_generation != handle.token.operation_generation
                or paper.excluded or paper.metadata is None
                or paper.collection is not None and paper.collection.active and not waiting):
            raise StaleWriteError('Captured Paper authority changed')
        return paper

    def _ensure_browser_owner(self, handle):
        if self.browser_lock is None:
            return
        with self._gate:
            self._require_live(handle)
            if handle.browser_owner is not None:
                return
        scope = handle.authority.service_scope
        owner = self.browser_lock.acquire('collection', scopes=(scope,) if scope else (), shared=True)
        if owner is None:
            raise InvalidPaperState('Browser authority is currently controlled')
        try:
            with self._gate:
                self._require_live(handle)
                if handle.browser_owner is None:
                    handle.browser_owner = owner
                    if isinstance(handle, _BranchTask) and len(handle.parent.branch_tasks) == 1:
                        handle.parent.browser_owner = owner
                    return
        except BaseException:
            self.browser_lock.release(owner)
            raise
        self.browser_lock.release(owner)

    def _new_handle(self, admission, plan, deadline, service_id=None, source_run_id=None):
        handle = TaskHandle(admission.token, plan, _LocalAuthority(), deadline, service_id, source_run_id)
        handle.branch_tasks = tuple(_BranchTask(handle, branch) for branch in plan)
        if self._admission_capture is not None:
            for child in handle.branch_tasks:
                if child.branch.skip_reason is not None:
                    continue
                try:
                    child.admission_check = self._admission_capture(child.service_id, child.providers)
                except Exception as error:
                    child.admission_error = error
        if len(handle.branch_tasks) == 1:
            child = handle.branch_tasks[0]
            child.workflow_id, child.task_id = handle.workflow_id, handle.task_id
        handle.dispatch_ready.set()
        self._tasks[handle.paper_id] = handle
        return handle

    def admit(self, *, direct_ids, metadata, branches, service_id=None,
              source_run_id=None, deadline=None, no_applicable=False,
              additional_identities=(), expected_token=None, allow_rebuild=False):
        plan = self._plan(branches, no_applicable, service_id)
        deadline = self._deadline(deadline)
        with self._gate:
            self._require_open()
            with self._repository() as repository:
                paper = repository.match(direct_ids, additional_identities=additional_identities)
                reservation = self._reservations.get(paper.id) if paper else None
                if reservation is not None and reservation.kind == 'body':
                    # A reliable match that is busy stays that same Paper. No
                    # collection intent may mutate the active body's authority.
                    return paper
                if reservation is not None and (reservation.kind != 'legacy' or paper.collection is not None) and not (
                        paper.id in self._tasks and self._tasks[paper.id].waiting_on is reservation):
                    raise InvalidPaperState('Another operation owns this Paper')
                admission = repository.admit_collection(self.workspace_id, lifecycle_id=self.lifecycle_id,
                    branches=tuple(branch.name for branch in plan), direct_ids=direct_ids, metadata=metadata,
                    additional_identities=additional_identities, expected_token=expected_token,
                    allow_rebuild=allow_rebuild)
                if not admission.admitted:
                    return self._tasks.get(admission.paper.id, admission.paper)
                handle = self._new_handle(admission, plan, deadline, service_id, source_run_id)
                handle.waiting_on = reservation
                if reservation is not None:
                    handle.dispatch_ready.clear()
        self._observe(handle, 'queued', 'workflow_started')
        return handle

    def submit(self, **kwargs):
        handle = self.admit(**kwargs)
        return self.register(handle) if isinstance(handle, TaskHandle) else handle

    def register(self, handle):
        if not isinstance(handle, TaskHandle):
            raise TypeError('Registration requires the captured TaskHandle')
        with self._gate:
            if self._tasks.get(handle.paper_id) is not handle:
                if handle.future.done() and handle.lifecycle_id == self.lifecycle_id:
                    return handle
                raise InvalidPaperState('Registration requires this registry\'s current captured owner')
            if handle.registered:
                return handle
        try:
            self._guard(handle)
            with self._gate:
                self._require_live(handle)
                if handle.registered:
                    return handle
                handle.registered = True
                scheduled = self._scheduler.submit(handle.service_id,
                    lambda: self._run(handle), cancel_event=handle.cancel_event,
                    deadline=handle.deadline, discarded=lambda reason: self._discard(handle, reason),
                    ready_event=handle.dispatch_ready)
                handle.scheduled = scheduled
                scheduled.add_done_callback(lambda done: self._settled(handle, done))
        except Exception as error:
            if not handle.registered:
                self._settle_unscheduled(handle, 'revoked' if isinstance(error, (StaleWriteError, TimeoutError))
                                         or self.stopped else 'registration_failed')
            elif handle.scheduled is None:
                self._settle_unscheduled(handle, 'submission_failed')
        return handle

    def _retry_qualification(self, paper_id, branches, service_id, expected_token, expected_attempt, expected_revision=None):
        plan = self._plan(branches, no_applicable=True, service_id=service_id)
        paper_id = UUID(str(paper_id))
        with self._gate:
            self._require_open()
            if paper_id in self._tasks or paper_id in self._reservations:
                raise InvalidPaperState('Previous Paper resources have not settled')
            with self._repository() as repository:
                paper = repository.get(paper_id)
            if paper.excluded or paper.metadata is None or paper.collection_status not in {'failed', 'cancelled'}:
                raise InvalidPaperState('Retry requires a settled failed or cancelled full Paper')
            if expected_token is not None and paper.token != expected_token:
                raise StaleWriteError('Captured Paper authority changed')
            if expected_attempt is not None and paper.collection.attempt != expected_attempt:
                raise StaleWriteError('Captured collection attempt changed')
            if expected_revision is not None and paper.revision != expected_revision:
                raise StaleWriteError('Captured Paper revision changed')
            if {branch.name for branch in paper.collection.branches} != {branch.name for branch in plan}:
                raise InvalidPaperState('Retry must preserve the complete captured branch plan')
            successful = {branch.name for branch in paper.collection.branches if branch.state in {'completed', 'skipped'}}
            pending = tuple(branch for branch in plan if branch.name not in successful)
        # Access qualification is read-only and outside every Workspace/SQLite lock.
        authorities = {branch.name: self._authority(branch.service_id, (branch,))
                       for branch in pending if branch.skip_reason is None}
        return paper, plan, pending, authorities

    def check_retry(self, paper_id, *, branches, service_id=None, expected_token=None, expected_attempt=None, expected_revision=None):
        """Read-only public retry eligibility, including only pending access dependencies."""
        paper, _, _, _ = self._retry_qualification(paper_id, branches, service_id, expected_token, expected_attempt, expected_revision)
        return paper

    def retry(self, paper_id, *, branches, service_id=None, deadline=None,
              expected_token=None, expected_attempt=None, expected_revision=None):
        deadline = self._deadline(deadline)
        paper, plan, pending, authorities = self._retry_qualification(
            paper_id, branches, service_id, expected_token, expected_attempt, expected_revision)
        with self._gate:
            self._require_open()
            for authority in authorities.values():
                self._check_admission(authority)
            if paper.id in self._tasks or paper.id in self._reservations:
                raise InvalidPaperState('Previous Paper resources have not settled')
            with self._repository() as repository:
                current = repository.get(paper.id)
                if current.collection != paper.collection or current.revision != paper.revision:
                    raise StaleWriteError('Captured Paper or collection attempt changed')
                admission = repository.retry_collection(paper.token, lifecycle_id=self.lifecycle_id,
                    branches=tuple(branch.name for branch in plan))
            handle = self._new_handle(admission, pending, deadline, service_id)
            for child in handle.branch_tasks:
                if child.branch.name in authorities:
                    child.authority = authorities[child.branch.name]
                    child.authority_captured = True
        self._observe(handle, 'queued', 'workflow_started')
        return self.register(handle)

    def reserve(self, paper_id, *, kind='download', expected_token=None, cancel=None,
                service_id=None, providers=(), deadline=None, body_request=None):
        if kind not in {'download', 'legacy', 'body'}:
            raise ValueError('Unknown Paper reservation kind')
        if kind == 'body' and body_request is None:
            raise ValueError('A captured body request is required')
        paper_id = UUID(str(paper_id))
        providers = tuple(sorted(set(providers)))
        if not set(providers) <= set(PROVIDERS):
            raise ValueError('Unknown reservation Provider')
        authority = (self._authority(service_id, (BranchSpec('pdf-discovery', providers=providers),))
                     if service_id is not None or providers or kind == 'body' else _LocalAuthority())
        reservation_deadline = self._deadline(deadline) if deadline is not None else float('inf')
        with self._gate:
            self._require_open()
            self._check_admission(authority)
            existing = self._reservations.get(paper_id)
            if existing is not None and kind == existing.kind and kind in {'download', 'body'}:
                return existing
            if existing is not None or paper_id in self._tasks:
                raise InvalidPaperState('Another operation owns this Paper')
            with self._repository() as repository:
                paper = repository.get(paper_id)
                if paper.excluded or paper.metadata is None or paper.collection is not None and paper.collection.active:
                    raise InvalidPaperState('Paper is not eligible while excluded, empty or collecting')
                if kind == 'body' and paper.body is not None:
                    return paper
                if expected_token is not None and (repository._body_key(paper.token) != repository._body_key(expected_token)
                        if kind == 'body' else paper.token != expected_token):
                    raise StaleWriteError('Captured Paper authority changed')
                download_token = None
                if kind == 'body':
                    if paper.primary_identity != body_request.primary:
                        raise StaleWriteError('Captured primary Paper identity changed')
                    if paper.download is not None and paper.download.output is not None:
                        from allfold.persistence.body_files import ManagedBodyFiles
                        with ManagedBodyFiles(self.workspace, paper.id, paper.download.token.attempt,
                                expected_workspace=self._identity[0]) as files:
                            files.cleanup(paper.download.output)
                        repository.record_download_output(paper.download.token, None)
                    download_token = repository.begin_download(paper.token, lifecycle_id=self.lifecycle_id)
                else:
                    repository.touch_projection(paper_id)
            reservation = PaperReservation(self, paper.token, self.lifecycle_id, kind, cancel)
            reservation.download_token = download_token
            reservation.body_request = body_request
            reservation.authority, reservation.service_id = authority, service_id
            reservation.providers = providers
            reservation.deadline = reservation_deadline
            self._reservations[paper_id] = reservation
            return reservation

    def release(self, reservation):
        with self._gate:
            if reservation.registry is not self:
                raise InvalidPaperState('Reservation belongs to another Workspace registry')
            if self._reservations.get(reservation.paper_id) is reservation:
                if reservation.cleanup_failed:
                    raise InvalidPaperState('Reservation cleanup could not be confirmed')
                reservation.cleanup_ended = True
                try:
                    with self._repository() as repository:
                        repository.touch_projection(reservation.paper_id)
                except Exception as error:
                    self._fault(reservation, 'reservation-release', error)
                    self._settled_condition.notify_all()
                    raise
                del self._reservations[reservation.paper_id]
                reservation.released = True
                deferred = self._tasks.get(reservation.paper_id)
                if deferred is not None and deferred.waiting_on is reservation:
                    deferred.waiting_on = None
                    deferred.dispatch_ready.set()
                    self._scheduler.wake()
                self._settled_condition.notify_all()

    def fail_reservation(self, reservation, *, phase, error):
        """A reservation worker exited without proving its captured resource close."""
        if phase not in {'preprint-client-cleanup', 'preprint-repository-cleanup', 'preprint-owner-cleanup',
                         'discovery-client-cleanup', 'discovery-native-cleanup', 'discovery-owner-cleanup',
                         'body-native-cleanup', 'body-file-cleanup', 'body-owner-cleanup', 'body-terminal-write'}:
            raise ValueError('Unknown reservation cleanup phase')
        with self._gate:
            if reservation.registry is not self:
                raise InvalidPaperState('Reservation belongs to another Workspace registry')
            if self._reservations.get(reservation.paper_id) is reservation and not reservation.cleanup_failed:
                reservation.cleanup_ended = reservation.cleanup_failed = True
                self._fault(reservation, phase, error)
                self._settled_condition.notify_all()

    def _fault(self, handle, phase, error):
        with self._gate:
            self._faults.append({'paper_id': str(handle.paper_id), 'attempt': getattr(handle.token, 'attempt', None),
                                 'phase': phase, 'reason': type(error).__name__})
            del self._faults[:-64]

    def _observe(self, handle, status, event):
        details = dict(kind='collection', stage='collection', workflow_id=handle.workflow_id,
            task_id=handle.task_id, workspace_id=str(handle.workspace_id),
            paper_id=str(handle.paper_id), attempt=handle.token.attempt, collection_status=status)
        if handle.service_id is not None:
            details['service_id'] = handle.service_id
        if handle.source_run_id is not None:
            details['parent_task_id'] = handle.source_run_id
        observe(self.diagnostics, 'event', event, details)

    def _settle_unscheduled(self, handle, reason):
        with self._gate:
            handle.registered = True
        try:
            self._discard(handle, reason)
        except Exception as error:
            self._fault(handle, 'branch-settlement', error)
            if not handle.future.done():
                handle.future.set_exception(error)
        else:
            self._settled(handle, None)

    def _discard(self, handle, reason):
        cancelled = reason in {'closed', 'cancelled', 'expired', 'revoked'} or handle.cancel_event.is_set()
        if cancelled:
            handle.cancel_event.set()
        with self._gate, self._repository() as repository:
            if cancelled:
                repository.request_collection_cancel(handle.token, reason=reason)
            paper = repository.get(handle.paper_id)
            for branch in paper.collection.branches:
                if branch.state in {'queued', 'running'}:
                    repository.commit_collection_branch(handle.token, branch.name, sequence=branch.last_sequence + 1,
                        outcome='cancelled' if cancelled else 'failed', reason=reason)
        return bool(not cancelled)

    def _discard_branch(self, child, reason):
        cancelled = child.cancel_event.is_set() or child.parent.cancel_event.is_set() or reason in {
            'closed', 'cancelled', 'expired', 'revoked'}
        with self._gate, self._repository() as repository:
            paper = repository.get(child.paper_id)
            saved = next(branch for branch in paper.collection.branches if branch.name == child.branch.name)
            if saved.state in {'queued', 'running'}:
                repository.commit_collection_branch(child.token, child.branch.name, sequence=saved.last_sequence + 1,
                    outcome='cancelled' if cancelled else 'failed', reason=reason)
        return not cancelled

    def _branch_settled(self, child, done):
        try:
            result = done.result()
        except BaseException as error:
            child.future.set_exception(error)
        else:
            child.future.set_result(result)

    def _run(self, handle):
        timer = threading.Timer(max(0, handle.deadline - time.monotonic()),
                                lambda: self._cancel_target(handle, 'expired'))
        timer.daemon = True
        timer.start()
        try:
            self._guard(handle)
            with self._gate, self._repository() as repository:
                repository.mark_collection_running(handle.token)
            for child in handle.branch_tasks:
                with self._gate:
                    if child.future.done():
                        continue
                    try:
                        child.scheduled = self._branch_scheduler.submit(child.service_id,
                            lambda child=child: self._run_branch(child), cancel_event=child.cancel_event,
                            deadline=child.deadline,
                            discarded=lambda reason, child=child: self._discard_branch(child, reason))
                    except Exception:
                        child.future.set_result(self._discard_branch(child, 'submission_failed'))
                    else:
                        child.scheduled.add_done_callback(lambda done, child=child: self._branch_settled(child, done))
            failed, errors = False, []
            # Join every child even when another cleanup faults.
            for child in handle.branch_tasks:
                try:
                    failed = bool(child.future.result()) or failed
                except BaseException as error:
                    errors.append(error)
            if errors:
                raise errors[0]
            return failed
        except Exception as error:
            if any(child.future.done() and child.future.exception() is not None for child in handle.branch_tasks):
                raise
            self._discard(handle, 'revoked' if handle.cancel_event.is_set() or self.stopped
                          or isinstance(error, (StaleWriteError, TimeoutError)) else 'execution_failed')
            return True
        finally:
            timer.cancel()
            timer.join()

    def _run_branch(self, child):
        native, cleanup_fault = [], False
        try:
            # External access/credential work occurs only after durable queued + host ownership.
            if child.admission_error is not None:
                raise child.admission_error
            if child.admission_check is not None:
                child.admission_check()
            if child.branch.skip_reason is None and not child.authority_captured:
                child.authority = self._authority(child.service_id, (child.branch,))
            self._guard(child)
            if child.authority.service_scope is not None:
                self._ensure_browser_owner(child)
            with self._repository() as repository:
                context = BranchContext(self, child, repository, None, child.branch, native)
                try:
                    if child.branch.skip_reason is not None:
                        context._finish('skipped', reason=child.branch.skip_reason)
                    else:
                        if self.factory is None or not callable(getattr(self.factory, 'open', None)):
                            raise RuntimeError('Collection client factory is unavailable')
                        with self._clients(child, repository) as clients:
                            context._clients = clients
                            if child.branch.run is None:
                                raise RuntimeError('Collection branch implementation is missing')
                            result = child.branch.run(context)
                            if result is not None and not isinstance(result, MetadataDelta):
                                raise TypeError('A collection branch returns MetadataDelta or None')
                            context._finish('completed', delta=result)
                except _CleanupUnconfirmed:
                    raise
                except Exception as error:
                    cancelled = (child.cancel_event.is_set() or child.parent.cancel_event.is_set()
                                 or self.stopped or isinstance(error, (StaleWriteError, TimeoutError)))
                    context._finish('cancelled' if cancelled else 'failed', reason=type(error).__name__)
                    return not cancelled
            return False
        except _CleanupUnconfirmed as error:
            cleanup_fault = True
            self._fault(child, 'client-cleanup', error)
            raise
        except Exception as error:
            return self._discard_branch(child, 'revoked' if child.cancel_event.is_set()
                or child.parent.cancel_event.is_set() or self.stopped
                or isinstance(error, (StaleWriteError, TimeoutError)) else type(error).__name__)
        finally:
            try:
                native_cancelled = False
                for future in native:
                    try:
                        future.result()
                    except BaseException:
                        native_cancelled = native_cancelled or future.cancelled()
                if native_cancelled:
                    raise _CleanupUnconfirmed('Native Future cancellation is not resource settlement')
                if native and self.bridge is not None:
                    self.bridge.execute('release_workflow_pages', {
                        'workflow_id': child.workflow_id, 'task_id': child.task_id}).result()
            except Exception as error:
                cleanup_fault = True
                self._fault(child, 'native-cleanup', error)
                raise
            finally:
                if child.browser_owner is not None and not cleanup_fault:
                    self.browser_lock.release(child.browser_owner)
                    with self._gate:
                        child.browser_owner = None
                        if len(child.parent.branch_tasks) == 1:
                            child.parent.browser_owner = None

    @contextmanager
    def _clients(self, handle, repository):
        resources = ExitStack()
        try:
            branch = getattr(handle, 'branch', None)
            options = {'mailto': branch.mailto} if branch is not None and branch.mailto else {}
            clients = resources.enter_context(self.factory.open(cancel_event=handle.cancel_event,
                request_guard=lambda: self._guard(handle, repository), deadline=handle.deadline,
                providers=handle.providers, **options))
            yield clients
        finally:
            try:
                resources.close()
            except Exception as error:
                raise _CleanupUnconfirmed('Client disposal could not be confirmed') from error

    def _settled(self, handle, done):
        try:
            failed = bool(done.result()) if done is not None else True
        except BaseException as error:
            self._fault(handle, 'execution-settlement', error)
            if not handle.future.done():
                handle.future.set_exception(error)
            return
        try:
            with self._gate, self._repository() as repository:
                paper = repository.finish_collection(handle.token, failed=failed)
            # Logs Reset must not observe this job idle while its final event
            # is still waiting on the shared diagnostic writer.
            self._observe(handle, paper.collection_status, 'workflow_finished')
            with self._gate, self._repository() as repository:
                if self._tasks.get(handle.paper_id) is handle:
                    paper = repository.touch_projection(handle.paper_id)
                    del self._tasks[handle.paper_id]
                    self._settled_condition.notify_all()
            if not handle.future.done():
                handle.future.set_result(paper)
        except BaseException as error:
            self._fault(handle, 'terminal-write', error)
            if not handle.future.done():
                handle.future.set_exception(error)

    def _invalidate(self, handle, reason):
        with self._gate, self._repository() as repository:
            repository.request_collection_cancel(handle.token, reason=reason)

    def _signal(self, target):
        target.cancel_event.set()
        try:
            if isinstance(target, PaperReservation) and target.cancel is not None:
                target.cancel()
            if isinstance(target, TaskHandle):
                for child in target.branch_tasks:
                    child.cancel_event.set()
                    if self.bridge is not None:
                        self.bridge.cancel_task(child.workflow_id, child.task_id)
            elif self.bridge is not None:
                self.bridge.cancel_task(target.workflow_id, target.task_id)
        finally:
            self._scheduler.wake()
            self._branch_scheduler.wake()

    def _prepare_cancel_target(self, target, reason='cancelled'):
        with self._gate:
            current = self._tasks.get(target.paper_id) if isinstance(target, (TaskHandle, _BranchTask)) else self._reservations.get(target.paper_id)
            if current is not (target.parent if isinstance(target, _BranchTask) else target):
                return False
            if isinstance(target, TaskHandle):
                try:
                    self._invalidate(target, reason)
                except Exception as error:
                    self._fault(target, 'cancel-write', error)
            target.cancel_event.set()
            if isinstance(target, TaskHandle) and not target.registered:
                target.registered = True
                target.cancel_pending = True
        return True

    def signal_cancel_targets(self, targets):
        """Use captured resources outside host/configuration/Paper write locks."""
        for target in targets:
            try:
                self._signal(target)
            except Exception as error:
                self._fault(target, 'cancel-signal', error)
            with self._gate:
                pending = isinstance(target, TaskHandle) and target.cancel_pending
                if pending:
                    target.cancel_pending = False
            if pending:
                self._settle_unscheduled(target, 'cancelled')
            elif isinstance(target, _BranchTask):
                with self._gate:
                    if target.scheduled is None and not target.future.done():
                        try:
                            target.future.set_result(self._discard_branch(target, 'cancelled'))
                        except Exception as error:
                            target.future.set_exception(error)

    def _cancel_target(self, target, reason='cancelled'):
        if not self._prepare_cancel_target(target, reason):
            return False
        self.signal_cancel_targets((target,))
        return True

    def prepare_cancel_paper(self, paper_id, workspace_id=None):
        """Capture and revoke only the owner present in this Paper transaction."""
        if workspace_id is not None and UUID(str(workspace_id)) != self.workspace_id:
            return ()
        with self._gate:
            paper_id = UUID(str(paper_id))
            targets = (self._tasks.get(paper_id), self._reservations.get(paper_id))
            return tuple(target for target in targets if target is not None and self._prepare_cancel_target(target))

    def cancel_paper(self, paper_id, workspace_id=None):
        targets = self.prepare_cancel_paper(paper_id, workspace_id)
        self.signal_cancel_targets(targets)
        return bool(targets)

    def prepare_cancel_services(self, service_ids, *, all_access=False, providers=()):
        selected = frozenset(service_ids)
        providers = frozenset(providers)
        with self._gate:
            def affected(task):
                return (all_access and task.service_id is not None or task.service_id in selected
                        or bool(providers.intersection(task.providers)))
            targets = [reservation for reservation in self._reservations.values() if affected(reservation)]
            for task in self._tasks.values():
                children = tuple(child for child in task.branch_tasks if child.branch.skip_reason is None
                                 and affected(child) and not child.future.done())
                if children and len(children) == len(task.branch_tasks):
                    targets.append(task)
                else:
                    targets.extend(children)
            return tuple(target for target in targets if self._prepare_cancel_target(target))

    def cancel_services(self, service_ids, *, all_access=False, providers=()):
        targets = self.prepare_cancel_services(service_ids, all_access=all_access, providers=providers)
        self.signal_cancel_targets(targets)
        return targets

    def close_admission(self):
        """Revoke dispatch under a short host lock; cancellation runs separately."""
        with self._gate:
            self._stopped = True

    def shutdown(self):
        with self._gate:
            if self._shutdown_started:
                return
            self._shutdown_started = True
            self._stopped = True
            tasks, reservations = tuple(self._tasks.values()), tuple(self._reservations.values())
        for target in (*tasks, *reservations):
            self._cancel_target(target)
        for task in tasks:
            with self._gate:
                if task.registered:
                    continue
                task.registered = True
            self._settle_unscheduled(task, 'closed')
        self._scheduler.close()

    def join(self):
        self._scheduler.join()
        self._branch_scheduler.close()
        self._branch_scheduler.join()
        with self._settled_condition:
            self._settled_condition.wait_for(lambda: all(reservation.cleanup_ended
                                                       for reservation in self._reservations.values()))
