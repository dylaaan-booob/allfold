"""Process-local ownership of one complete browser workflow, without leases."""
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


class BrowserTaskLock:
    def __init__(self):
        self._mutex = threading.Lock()
        self._owner: BrowserOwner | None = None

    @property
    def owner(self) -> BrowserOwner | None:
        with self._mutex:
            return self._owner

    def acquire(self, kind: str) -> BrowserOwner | None:
        with self._mutex:
            if self._owner is not None:
                return None
            self._owner = BrowserOwner(kind, uuid4().hex)
            return self._owner

    def require(self, owner: BrowserOwner) -> None:
        with self._mutex:
            if owner is not self._owner:
                raise RuntimeError("Browser workflow no longer owns the runtime")

    def release(self, owner: BrowserOwner) -> None:
        with self._mutex:
            if owner is not self._owner:
                raise RuntimeError("Cannot release another browser workflow")
            self._owner = None


class ElectronDisconnected(RuntimeError):
    pass


class BrowserGateway(Protocol):
    @property
    def connected(self) -> bool: ...

    def execute(self, action: str, data: dict,
                progress: Callable | None = None) -> Future[dict]: ...

    def cancel_current(self) -> Future[bool] | None: ...
