"""Application-owned Workspace lifetimes and exact Paper operations.

Only work admission/initialization binds a library. Read projections use peek(),
so a GET never creates a database or normalizes a newly appeared library.
"""
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
import threading

from allfold.application.collection_runtime import WorkspaceRegistry
from allfold.application.task_authority import TaskAuthority
from allfold.application.task_clients import IndependentClientFactory, new_provider_pacing
from allfold.config import ConfigurationError, load_config
from allfold.persistence.paper_repository import InvalidPaperState, LibraryError


@dataclass(eq=False)
class WorkspaceChange:
    registry: object
    whole: bool
    services: frozenset = frozenset()
    providers: frozenset = frozenset()
    all_access: bool = False
    targets: tuple = ()
    drained: bool = False


@dataclass(frozen=True)
class _HostAuthority:
    host: object = field(repr=False)
    authority: object = field(repr=False)
    epochs: tuple = field(repr=False)
    providers: tuple

    @property
    def service_id(self):
        return self.authority.service_id

    @property
    def service_scope(self):
        return self.authority.service_scope

    def native_access(self):
        return self.authority.native_access()

    def admission_check(self):
        # Pure immutable snapshot only: safe inside the runtime Paper gate.
        self.host._verify_authority(self.service_id, self.providers, self.epochs)

    def verify(self):
        # Runtime invokes this before taking its Paper gate. Configuration and
        # UserState reads therefore see one short saved-settings boundary.
        with self.host.settings_lock:
            self.host._verify_authority(self.service_id, self.providers, self.epochs)
            self.authority.verify()
            self.host._verify_authority(self.service_id, self.providers, self.epochs)


class WorkspaceTaskHost:
    def __init__(self, config_path, *, browser_lock=None, bridge=None, diagnostics=None,
                 login=None, factory=None, pacing_state=None, authority_capture=None, settings_lock=None):
        self.config_path = Path(config_path).resolve()
        self.browser_lock, self.bridge, self.diagnostics, self.login = browser_lock, bridge, diagnostics, login
        self.pacing_state = pacing_state if pacing_state is not None else new_provider_pacing()
        self.factory = factory or IndependentClientFactory(self.config_path, pacing_state=self.pacing_state)
        self.authority_capture = authority_capture or (
            lambda service_id, providers: TaskAuthority.capture(self.config_path, self.login, service_id, providers))
        self.settings_lock = settings_lock if settings_lock is not None else threading.RLock()
        self._lock = threading.RLock()
        self._registry = None
        self._change = None
        self._closed = False
        self._epoch, self._access_epoch = 0, 0
        self._service_epochs, self._provider_epochs = {}, {}
        self._publish_authority()

    def initialize(self):
        """Normalize an existing library once at application lifetime startup."""
        try:
            return self.current()
        except (ConfigurationError, LibraryError, OSError, ValueError):
            # Invalid configuration/library remains an ordinary visible read
            # error. Missing libraries are still initialized explicitly by Run.
            return None

    def peek(self):
        with self._lock:
            return self._registry

    @property
    def changing(self):
        with self._lock:
            return self._change is not None

    @property
    def active(self):
        registry = self.peek()
        return bool(registry and registry.active)

    @property
    def browser_owner_ids(self):
        registry = self.peek()
        return registry.browser_owner_ids if registry else frozenset()

    def current(self):
        with self.settings_lock:
            workspace = load_config(self.config_path).output_dir.absolute()
            with self._lock:
                if self._closed or self._change is not None and self._change.whole:
                    raise InvalidPaperState('Workspace task admission is closed for maintenance')
                registry = self._registry
                if registry is None:
                    registry = self._registry = WorkspaceRegistry(workspace, factory=self.factory,
                        browser_lock=self.browser_lock, bridge=self.bridge, diagnostics=self.diagnostics,
                        authority_capture=self._capture_authority, admission_capture=self._capture_admission)
            # Never wait on an existing Paper gate while holding the host mutex.
            if registry.workspace != workspace or registry.stopped:
                raise InvalidPaperState('Workspace lifetime changed; a fresh binding is required')
            return registry

    def _publish_authority(self):
        change = self._change
        # An immutable value is replaced atomically. admission_check must not
        # acquire settings/host locks while the registry owns its Paper gate.
        self._authority_state = (self._closed, self._epoch, self._access_epoch,
            tuple(self._service_epochs.items()), tuple(self._provider_epochs.items()),
            change.whole if change else False, change.services if change else frozenset(),
            change.providers if change else frozenset(), change.all_access if change else False)

    def _verify_authority(self, service_id, providers, epochs=None):
        closed, epoch, access, services, provider_epochs, whole, affected, changed_providers, all_access = self._authority_state
        captured = (epoch, access if service_id is not None else None,
            dict(services).get(service_id, 0), tuple((provider, dict(provider_epochs).get(provider, 0)) for provider in providers))
        if (closed or whole or service_id in affected or all_access and service_id is not None
                or changed_providers.intersection(providers) or epochs is not None and epochs != captured):
            raise InvalidPaperState('Captured Workspace/Service/Provider authority was revoked')
        return captured

    def _capture_admission(self, service_id, providers):
        """Bind process-local epochs before any external capture, without I/O/locks."""
        epochs = self._verify_authority(service_id, providers)
        return lambda: self._verify_authority(service_id, providers, epochs)

    def _capture_authority(self, service_id, providers):
        with self.settings_lock:
            epochs = self._verify_authority(service_id, providers)
            authority = self.authority_capture(service_id, providers)
            self._verify_authority(service_id, providers, epochs)
            return _HostAuthority(self, authority, epochs, tuple(providers))

    def cleanup_pending(self, paper_id, workspace_id):
        registry = self.peek()
        return bool(registry and registry.cleanup_pending(paper_id, workspace_id))

    def begin_change(self, *, whole=False, services=(), providers=(), all_access=False):
        """Short settings → Paper → host decision; no cancellation callbacks."""
        with self.settings_lock:
            registry = self.peek()
            with registry.paper_gate() if registry else nullcontext():
                with self._lock:
                    if self._closed or self._change is not None:
                        raise InvalidPaperState('Workspace maintenance is already in progress')
                    change = WorkspaceChange(registry, whole, frozenset(services), frozenset(providers), all_access)
                    self._change = change
                    if whole:
                        self._epoch += 1
                    else:
                        if all_access:
                            self._access_epoch += 1
                        for service in change.services:
                            self._service_epochs[service] = self._service_epochs.get(service, 0) + 1
                        for provider in change.providers:
                            self._provider_epochs[provider] = self._provider_epochs.get(provider, 0) + 1
                    self._publish_authority()
                if registry is not None:
                    if whole:
                        registry.close_admission()
                    else:
                        change.targets = registry.prepare_cancel_services(change.services,
                            all_access=all_access, providers=change.providers)
                return change

    @staticmethod
    def drain_change(change):
        registry = change.registry
        if registry is not None:
            if change.whole:
                registry.shutdown()
                registry.join()
            else:
                registry.signal_cancel_targets(change.targets)
                for target in change.targets:
                    target.future.result()
            if registry.active and registry.faults:
                raise RuntimeError('Workspace task resources or state could not be settled')
        change.drained = True

    def finish_change(self, change):
        """Rebind the actual saved path, including failed/partial saves."""
        with self._lock:
            if self._change is not change:
                raise InvalidPaperState('Cannot finish another Workspace maintenance boundary')
            if change.whole and change.drained:
                self._registry = None
            self._change = None
            self._publish_authority()
        if change.whole and change.drained and not self._closed:
            self.initialize()

    def close_admission(self):
        with self.settings_lock:
            registry = self.peek()
            with registry.paper_gate() if registry else nullcontext():
                with self._lock:
                    self._closed = True
                    self._publish_authority()
                if registry is not None:
                    registry.close_admission()

    def shutdown(self):
        self.close_admission()
        with self._lock:
            registries = (self._registry,) if self._registry else ()
        for registry in registries:
            registry.shutdown()

    def join(self):
        with self._lock:
            registries = (self._registry,) if self._registry else ()
        for registry in registries:
            registry.join()
        # Every operation Future follows its bounded worker's real settlement.
        self.factory.close()
        if any(registry.active and registry.faults for registry in registries):
            raise RuntimeError('Workspace task resources or state could not be settled')
