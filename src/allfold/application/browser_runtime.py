"""Scoped workflow admission; physical pages remain native-owned."""
from concurrent.futures import Future
from collections.abc import Callable
from typing import Protocol
from dataclasses import dataclass, field
import threading
from uuid import uuid4


@dataclass(frozen=True)
class BrowserOwner:
    kind: str
    id: str
    scopes: frozenset[str] = frozenset()
    exclusive: bool = False
    shared: bool = False
    pages: frozenset[int] = frozenset()


@dataclass(frozen=True)
class BrowserControlReservation:
    kind: str
    id: str
    scopes: frozenset[str]
    exclusive: bool
    authority: object = field(repr=False)
    released: bool = False


class BrowserTaskLock:
    def __init__(self, *, admission_lock=None):
        self._admission = admission_lock or threading.RLock()
        self._mutex = threading.Lock()
        self._settled = threading.Condition(self._mutex)
        self._owners: dict[str, BrowserOwner] = {}
        self._controls: dict[str, BrowserControlReservation] = {}
        self._control_authority = object()
        self._closed = False

    @property
    def owners(self) -> tuple[BrowserOwner, ...]:
        with self._mutex:
            return tuple(self._owners.values())

    @property
    def owner(self) -> BrowserOwner | None:
        with self._mutex:
            return next(iter(self._owners.values()), None)

    def acquire(self, kind: str, *, scopes=(), shared=False, pages=(), control=None) -> BrowserOwner | None:
        # Only admission waits behind a configuration write. Completion and
        # require() must never wait on writers holding another coordinator lock.
        with self._admission, self._mutex:
            exclusive = kind in {'credentials', 'workspace-reset', 'logs-reset'}
            scopes = frozenset(scopes)
            pages = frozenset(pages)
            if control is not None:
                self._require_control(control)
                if kind != control.kind or scopes != control.scopes:
                    raise ValueError('Control admission must match its captured reservation')
            if shared and kind in {'login', 'access-cleanup', 'credentials', 'workspace-reset', 'logs-reset'}:
                raise ValueError('Browser controls require exclusive admission')
            if self._closed or any(exclusive or current.exclusive or scopes & current.scopes
                                   for current in self._controls.values() if current is not control) or any(exclusive or current.exclusive or pages & current.pages
                                   or scopes & current.scopes and not (shared and current.shared)
                                   for current in self._owners.values()):
                return None
            owner = BrowserOwner(kind, uuid4().hex, scopes, exclusive, shared, pages)
            self._owners[owner.id] = owner
            return owner

    def conflicts(self, scopes, *, control=None) -> bool:
        scopes = frozenset(scopes)
        with self._mutex:
            if control is not None:
                self._require_control(control)
            return any(current.exclusive or current.scopes & scopes
                       for current in (*self._owners.values(), *self._controls.values()) if current is not control)

    def reserve_control(self, kind, *, scopes=()):
        """Block replacement admission, allowing captured users to drain lock-free.

        This reservation grants no execution or page authority. The control must
        still acquire its normal owner after affected resources truly settle.
        """
        if kind not in {'credentials', 'workspace-reset', 'logs-reset', 'access-cleanup'}:
            raise ValueError('Unknown Browser control reservation')
        with self._admission, self._mutex:
            scopes = frozenset(scopes)
            exclusive = kind in {'credentials', 'workspace-reset', 'logs-reset'}
            if self._closed or any(exclusive or current.exclusive or scopes & current.scopes
                                   for current in self._controls.values()):
                return None
            control = BrowserControlReservation(kind, uuid4().hex, scopes, exclusive, self._control_authority)
            self._controls[control.id] = control
            return control

    def _require_control(self, control):
        if not isinstance(control, BrowserControlReservation) or self._controls.get(control.id) is not control:
            raise RuntimeError('Browser control reservation is no longer owned')

    def release_control(self, control):
        # Completion must not reacquire configuration admission during drain.
        with self._settled:
            if not isinstance(control, BrowserControlReservation) or control.authority is not self._control_authority:
                raise RuntimeError('Cannot release another Browser control reservation')
            if control.released:
                return
            self._require_control(control)
            del self._controls[control.id]
            object.__setattr__(control, 'released', True)
            self._settled.notify_all()

    def close_admission(self):
        with self._mutex:
            self._closed = True

    def wait_for_idle(self):
        with self._settled:
            self._settled.wait_for(lambda: not self._owners and not self._controls)

    def require(self, owner: BrowserOwner) -> None:
        with self._mutex:
            if self._owners.get(owner.id) is not owner:
                raise RuntimeError("Browser workflow no longer owns the runtime")

    def release(self, owner: BrowserOwner) -> None:
        with self._mutex:
            if self._owners.get(owner.id) is not owner:
                raise RuntimeError("Cannot release another browser workflow")
            del self._owners[owner.id]
            self._settled.notify_all()


class ElectronDisconnected(RuntimeError):
    pass


class BrowserGateway(Protocol):
    @property
    def connected(self) -> bool: ...

    def execute(self, action: str, data: dict,
                progress: Callable | None = None, *,
                verify_recovery: Callable[[], None] | None = None) -> Future[dict]: ...

    def cancel_workflow(self, workflow_id: str) -> Future[bool] | None: ...

    def cancel_task(self, workflow_id: str, task_id: str) -> Future[bool] | None: ...
