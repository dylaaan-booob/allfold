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
from allfold.persistence.library_database import DATABASE_NAME
from allfold.persistence.paper_repository import (
    CollectionToken, InvalidPaperState, MetadataDelta, PaperRepository, StaleWriteError,
)
from allfold.providers.integrated import PROVIDERS


@dataclass(frozen=True)
class BranchSpec:
    name: str
    run: object = None
    skip_reason: str | None = None
    providers: tuple[str, ...] = ()


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
            self.guard()
        with self._registry.paper_gate():
            return self._repository.commit_collection_branch(self.token, self._branch.name,
                sequence=self._sequence, delta=delta, outcome=outcome, reason=reason)


class WorkspaceRegistry:
    def __init__(self, workspace, *, factory, browser_lock=None, bridge=None,
                 diagnostics=None, admission_lock=None, authority_capture=None,
                 limit=4, group_limit=2):
        self.workspace = Path(workspace).absolute()
        self.factory, self.browser_lock, self.bridge = factory, browser_lock, bridge
        self.diagnostics = diagnostics
        self._gate = admission_lock if admission_lock is not None else threading.RLock()
        self._authority_capture = authority_capture
        self.lifecycle_id = uuid4()
        self._stopped = False
        self._shutdown_started = False
        self._tasks, self._reservations, self._faults = {}, {}, []
        self._settled_condition = threading.Condition(self._gate)
        with PaperRepository.open(self.workspace) as repository:
            self.workspace_id = repository.workspace_id
            self._identity = self._path_identity()
            repository.interrupt_collections(self.lifecycle_id)
        self._scheduler = DynamicScheduler(limit=limit, group_limit=group_limit)

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
            return frozenset(task.browser_owner.id for task in self._tasks.values()
                             if task.browser_owner is not None)

    def busy(self, paper_id, workspace_id=None):
        if workspace_id is not None and UUID(str(workspace_id)) != self.workspace_id:
            return False
        with self._gate:
            return UUID(str(paper_id)) in self._tasks or UUID(str(paper_id)) in self._reservations

    cleanup_pending = busy

    @staticmethod
    def _plan(branches, no_applicable=False):
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
                                tuple(sorted(set(branch.providers)))) for branch in plan)

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

    def _require_live(self, handle):
        self._require_open()
        if (self._tasks.get(handle.paper_id) is not handle or handle.lifecycle_id != self.lifecycle_id
                or handle.cancel_event.is_set()):
            raise StaleWriteError('Captured collection owner is no longer valid')
        if time.monotonic() >= handle.deadline:
            raise TimeoutError('Collection parent deadline expired')

    def _guard(self, handle, repository=None):
        try:
            handle.authority.verify()
        except Exception as error:
            raise StaleWriteError('Captured access authority was revoked') from error
        with self._gate:
            self._require_live(handle)
            if repository is not None:
                repository.require_collection(handle.token)
            else:
                with self._repository() as current:
                    current.require_collection(handle.token)

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
                    return
        except BaseException:
            self.browser_lock.release(owner)
            raise
        self.browser_lock.release(owner)

    def admit(self, *, direct_ids, metadata, branches, service_id=None,
              source_run_id=None, deadline=None, no_applicable=False):
        plan = self._plan(branches, no_applicable)
        deadline = self._deadline(deadline)
        with self._gate:
            self._require_open()
            with self._repository() as repository:
                reusable = self._reuse(repository, direct_ids)
                if reusable is not None:
                    return reusable
        authority = self._authority(service_id, plan)
        with self._gate:
            self._require_open()
            with self._repository() as repository:
                reusable = self._reuse(repository, direct_ids)
                if reusable is not None:
                    return reusable
                admission = repository.admit_collection(self.workspace_id, lifecycle_id=self.lifecycle_id,
                    branches=tuple(branch.name for branch in plan), direct_ids=direct_ids, metadata=metadata)
                if not admission.admitted:
                    return admission.paper
                handle = TaskHandle(admission.token, plan, authority, deadline, service_id, source_run_id)
                self._tasks[handle.paper_id] = handle
        self._observe(handle, 'queued', 'workflow_started')
        return handle

    def _reuse(self, repository, direct_ids):
        paper = repository.match(direct_ids)
        if paper is None or paper.excluded:
            return paper
        if paper.id in self._tasks:
            return self._tasks[paper.id]
        if paper.id in self._reservations:
            raise InvalidPaperState('Another operation owns this Paper')
        return paper if paper.collection is not None else None

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
                    deadline=handle.deadline, discarded=lambda reason: self._discard(handle, reason))
                handle.scheduled = scheduled
                scheduled.add_done_callback(lambda done: self._settled(handle, done))
        except Exception as error:
            if not handle.registered:
                self._settle_unscheduled(handle, 'revoked' if isinstance(error, (StaleWriteError, TimeoutError))
                                         or self.stopped else 'registration_failed')
            elif handle.scheduled is None:
                self._settle_unscheduled(handle, 'submission_failed')
        return handle

    def retry(self, paper_id, *, branches, service_id=None, deadline=None):
        # Empty retry is legal only when the persisted complete plan was empty;
        # retry_collection refuses discarding any previously captured branch.
        plan = self._plan(branches, no_applicable=True)
        deadline = self._deadline(deadline)
        paper_id = UUID(str(paper_id))
        with self._gate:
            self._require_open()
            if paper_id in self._tasks or paper_id in self._reservations:
                raise InvalidPaperState('Previous Paper resources have not settled')
            with self._repository() as repository:
                paper = repository.get(paper_id)
            successful = {branch.name for branch in paper.collection.branches
                          if branch.state in {'completed', 'skipped'}} if paper.collection else set()
            pending = tuple(branch for branch in plan if branch.name not in successful)
        authority = self._authority(service_id, pending)
        with self._gate:
            self._require_open()
            if paper_id in self._tasks or paper_id in self._reservations:
                raise InvalidPaperState('Previous Paper resources have not settled')
            with self._repository() as repository:
                admission = repository.retry_collection(paper.token, lifecycle_id=self.lifecycle_id,
                    branches=tuple(branch.name for branch in plan))
            handle = TaskHandle(admission.token, pending, authority, deadline, service_id)
            self._tasks[paper_id] = handle
        self._observe(handle, 'queued', 'workflow_started')
        return self.register(handle)

    def reserve(self, paper_id, *, kind='download', expected_token=None, cancel=None):
        if kind not in {'download', 'legacy'}:
            raise ValueError('Only download and legacy reservations are supported')
        paper_id = UUID(str(paper_id))
        with self._gate:
            self._require_open()
            existing = self._reservations.get(paper_id)
            if existing is not None and kind == existing.kind == 'download':
                return existing
            if existing is not None or paper_id in self._tasks:
                raise InvalidPaperState('Another operation owns this Paper')
            with self._repository() as repository:
                paper = repository.get(paper_id)
                if paper.excluded or paper.metadata is None or paper.collection is not None and paper.collection.active:
                    raise InvalidPaperState('Paper is not eligible while excluded, empty or collecting')
                if expected_token is not None and paper.token != expected_token:
                    raise StaleWriteError('Captured Paper authority changed')
                repository.touch_projection(paper_id)
            reservation = PaperReservation(self, paper.token, self.lifecycle_id, kind, cancel)
            self._reservations[paper_id] = reservation
            return reservation

    def release(self, reservation):
        with self._gate:
            if reservation.registry is not self:
                raise InvalidPaperState('Reservation belongs to another Workspace registry')
            if self._reservations.get(reservation.paper_id) is reservation:
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

    def _run(self, handle):
        failed, native, owner, cleanup_fault = False, [], None, False
        timer = threading.Timer(max(0, handle.deadline - time.monotonic()),
                                lambda: self._cancel_target(handle, 'expired'))
        timer.daemon = True
        timer.start()
        try:
            self._guard(handle)
            if handle.authority.service_scope is not None:
                self._ensure_browser_owner(handle)
            self._guard(handle)
            with self._repository() as repository:
                with self._gate:
                    repository.mark_collection_running(handle.token)
                if self.factory is None or not callable(getattr(self.factory, 'open', None)):
                    raise RuntimeError('Collection client factory is unavailable')
                with self._clients(handle, repository) as clients:
                    for branch in handle.branches:
                        context = BranchContext(self, handle, repository, clients, branch, native)
                        try:
                            context.guard()
                            if branch.skip_reason is not None:
                                context._finish('skipped', reason=branch.skip_reason)
                            else:
                                if branch.run is None:
                                    raise RuntimeError('Collection branch implementation is missing')
                                result = branch.run(context)
                                if result is not None and not isinstance(result, MetadataDelta):
                                    raise TypeError('A collection branch returns MetadataDelta or None')
                                context._finish('completed', delta=result)
                        except Exception as error:
                            cancelled = handle.cancel_event.is_set() or isinstance(error, (StaleWriteError, TimeoutError)) or self.stopped
                            failed = failed or not cancelled
                            if cancelled:
                                self._invalidate(handle, 'revoked')
                            context._finish('cancelled' if cancelled else 'failed', reason=type(error).__name__)
        except Exception as error:
            if isinstance(error, _CleanupUnconfirmed):
                cleanup_fault = True
                self._fault(handle, 'client-cleanup', error)
                raise
            failed = True
            try:
                self._discard(handle, 'revoked' if handle.cancel_event.is_set() or self.stopped
                              or isinstance(error, (StaleWriteError, TimeoutError)) else 'execution_failed')
            except Exception as settlement_error:
                self._fault(handle, 'branch-settlement', settlement_error)
                raise
        finally:
            try:
                native_cancelled = False
                for future in native:
                    try:
                        future.result()  # cancel()/timeout does not prove native terminal.
                    except BaseException:
                        failed = True
                        native_cancelled = native_cancelled or future.cancelled()
                if native_cancelled:
                    raise _CleanupUnconfirmed('Native Future cancellation is not resource settlement')
                timer.cancel()
                timer.join()
                if native and self.bridge is not None:
                    self.bridge.execute('release_workflow_pages', {
                        'workflow_id': handle.workflow_id, 'task_id': handle.task_id}).result()
            except Exception as error:
                # A cleanup failure has no evidence that physical pages exited.
                self._fault(handle, 'native-cleanup', error)
                raise
            finally:
                timer.cancel()
                timer.join()
                owner = handle.browser_owner
                if owner is not None and not cleanup_fault and not any(fault['phase'] == 'native-cleanup'
                        and fault['paper_id'] == str(handle.paper_id) for fault in self.faults):
                    self.browser_lock.release(owner)
                    with self._gate:
                        handle.browser_owner = None
        return failed

    @contextmanager
    def _clients(self, handle, repository):
        resources = ExitStack()
        try:
            clients = resources.enter_context(self.factory.open(cancel_event=handle.cancel_event,
                request_guard=lambda: self._guard(handle, repository), deadline=handle.deadline,
                providers=handle.providers))
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
                if self._tasks.get(handle.paper_id) is handle:
                    del self._tasks[handle.paper_id]
                    self._settled_condition.notify_all()
            self._observe(handle, paper.collection_status, 'workflow_finished')
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
            if self.bridge is not None:
                self.bridge.cancel_task(target.workflow_id, target.task_id)
        finally:
            self._scheduler.wake()

    def _prepare_cancel_target(self, target, reason='cancelled'):
        with self._gate:
            current = self._tasks.get(target.paper_id) if isinstance(target, TaskHandle) else self._reservations.get(target.paper_id)
            if current is not target:
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
                if isinstance(target, TaskHandle):
                    self._fault(target, 'cancel-signal', error)
            with self._gate:
                pending = isinstance(target, TaskHandle) and target.cancel_pending
                if pending:
                    target.cancel_pending = False
            if pending:
                self._settle_unscheduled(target, 'cancelled')

    def _cancel_target(self, target, reason='cancelled'):
        if not self._prepare_cancel_target(target, reason):
            return False
        self.signal_cancel_targets((target,))
        return True

    def cancel_paper(self, paper_id, workspace_id=None):
        if workspace_id is not None and UUID(str(workspace_id)) != self.workspace_id:
            return False
        with self._gate:
            target = self._tasks.get(UUID(str(paper_id))) or self._reservations.get(UUID(str(paper_id)))
            if target is None:
                return False
        return self._cancel_target(target)

    def prepare_cancel_services(self, service_ids, *, all_access=False, providers=()):
        selected = frozenset(service_ids)
        providers = frozenset(providers)
        with self._gate:
            targets = tuple(task for task in self._tasks.values()
                            if all_access and task.service_id is not None
                            or task.service_id in selected or providers.intersection(task.providers))
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
        with self._settled_condition:
            self._settled_condition.wait_for(lambda: all(reservation.cleanup_ended
                                                       for reservation in self._reservations.values()))
