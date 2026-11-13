"""Scoped workflow admission; physical pages remain native-owned."""
from concurrent.futures import Future
from collections.abc import Callable
from typing import Protocol
from dataclasses import dataclass
import threading
from uuid import uuid4


@dataclass(frozen=True)
class BrowserOwner:
    kind: str
    id: str
    scopes: frozenset[str] = frozenset()
    exclusive: bool = False


class BrowserTaskLock:
    def __init__(self, *, admission_lock=None):
        self._admission = admission_lock or threading.RLock()
        self._mutex = threading.Lock()
        self._settled = threading.Condition(self._mutex)
        self._owners: dict[str, BrowserOwner] = {}
        self._closed = False

    @property
    def owners(self) -> tuple[BrowserOwner, ...]:
        with self._mutex:
            return tuple(self._owners.values())

    @property
    def owner(self) -> BrowserOwner | None:
        with self._mutex:
            return next(iter(self._owners.values()), None)

    def acquire(self, kind: str, *, scopes=()) -> BrowserOwner | None:
        # Only admission waits behind a configuration write. Completion and
        # require() must never wait on writers holding another coordinator lock.
        with self._admission, self._mutex:
            exclusive = kind in {'credentials', 'workspace-reset', 'logs-reset'}
            scopes = frozenset(scopes)
            if self._closed or any(exclusive or current.exclusive or scopes & current.scopes
                                   for current in self._owners.values()):
                return None
            owner = BrowserOwner(kind, uuid4().hex, scopes, exclusive)
            self._owners[owner.id] = owner
            return owner

    def conflicts(self, scopes) -> bool:
        scopes = frozenset(scopes)
        with self._mutex:
            return any(current.exclusive or current.scopes & scopes
                       for current in self._owners.values())

    def close_admission(self):
        with self._mutex:
            self._closed = True

    def wait_for_idle(self):
        with self._settled:
            self._settled.wait_for(lambda: not self._owners)

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
