"""Bind a Run's short write phase without holding a lock during retrieval."""
from __future__ import annotations

import os
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from allfold.config import LoadedConfig, load_config
from allfold.persistence.safe_write import (
    ContentChangedError, WorkspaceBusyError, WorkspaceOperationLock,
    workspace_operation_lock, workspace_text_directory,
)


@dataclass
class RunWorkspaceSnapshot:
    config_path: Path
    config: LoadedConfig
    configuration: bytes
    workspace_identity: tuple[int, int]
    papers_identity: tuple[int, int]
    lock_identity: tuple[int, int]
    _workspace_fd: int
    _papers_fd: int
    _closed: bool = False

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._papers_fd)
            os.close(self._workspace_fd)

    def __enter__(self) -> RunWorkspaceSnapshot:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def capture_run_workspace(
    config_path: Path, loaded_config: LoadedConfig | None = None, *, create: bool = True,
) -> RunWorkspaceSnapshot:
    """Only a new explicit Run may initialize its Workspace.

    Open directory descriptors retain inode identities after Reset, without
    retaining flock exclusion. No checkpoint or new persistent state is added.
    """
    path = config_path.resolve()
    configuration = path.read_bytes()
    config = loaded_config or load_config(path)
    with workspace_operation_lock(config.output_dir, create=create) as lock:
        if path.read_bytes() != configuration or load_config(path) != config:
            raise ContentChangedError("Run configuration changed before start")
        with workspace_text_directory(lock, "Papers", create=create) as papers:
            workspace_fd = os.dup(lock.directory)
            try:
                papers_fd = os.dup(papers.directory)
            except BaseException:
                os.close(workspace_fd)
                raise
            return RunWorkspaceSnapshot(
                path, config, configuration, lock.identity, papers.identity,
                lock.lock_identity, workspace_fd, papers_fd,
            )


def _verify_snapshot(snapshot: RunWorkspaceSnapshot, lock: WorkspaceOperationLock) -> None:
    if snapshot._closed:
        raise ContentChangedError("Run Workspace snapshot is closed")
    lock.verify()
    if lock.identity != snapshot.workspace_identity or lock.lock_identity != snapshot.lock_identity:
        raise ContentChangedError("Run Workspace was reset or replaced")
    if (snapshot.config_path.read_bytes() != snapshot.configuration
            or load_config(snapshot.config_path) != snapshot.config):
        raise ContentChangedError("Run configuration or source scope changed")
    # Verify rather than create: the original Papers directory must still exist.
    descriptor = os.open("Papers", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=lock.directory)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != snapshot.papers_identity:
            raise ContentChangedError("Run Papers directory was replaced")
    finally:
        os.close(descriptor)


@contextmanager
def commit_run_workspace(snapshot: RunWorkspaceSnapshot, *, cancel_event: Event | None = None):
    """Recheck identity and create atomically within one short cooperative lock."""
    if cancel_event is not None and cancel_event.is_set():
        raise ContentChangedError("Run cancelled before commit")
    try:
        with ExitStack() as stack:
            deadline = time.monotonic() + 5
            signal = cancel_event or Event()
            while True:
                if signal.is_set():
                    raise ContentChangedError("Run cancelled before commit")
                try:
                    lock = stack.enter_context(workspace_operation_lock(
                        snapshot.config.output_dir, create=False,
                        expected_identity=snapshot.workspace_identity,
                        expected_lock_identity=snapshot.lock_identity,
                    ))
                    break
                except WorkspaceBusyError:
                    if time.monotonic() >= deadline:
                        raise
                    signal.wait(0.02)
            _verify_snapshot(snapshot, lock)
            if cancel_event is not None and cancel_event.is_set():
                raise ContentChangedError("Run cancelled before commit")
            yield lock
    except OSError as error:
        raise ContentChangedError("Run Workspace or configuration location changed") from error
