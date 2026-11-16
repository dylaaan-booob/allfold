"""Bind a Run's short write phase without holding a lock during retrieval."""
from __future__ import annotations

import os
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import UUID

from allfold.persistence.paper_repository import PaperRecord, PaperRepository, LibraryMissingError
from allfold.persistence.library_database import DATABASE_NAME

from allfold.config import LoadedConfig, load_config
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.persistence.user_state import read_user_state
from allfold.persistence.safe_write import (
    ContentChangedError, TextWriteCommittedError, WorkspaceBusyError, WorkspaceOperationLock,
    workspace_operation_lock, read_text_exact,
)


@dataclass
class RunWorkspaceSnapshot:
    config_path: Path
    config: LoadedConfig
    wos_access: BrowserServiceSnapshot | None
    wos_only: bool
    workspace_identity: tuple[int, int]
    database_identity: tuple[int, int]
    workspace_id: UUID
    initial_papers: dict[UUID, PaperRecord]
    lock_identity: tuple[int, int]
    _workspace_fd: int
    _database_fd: int
    _closed: bool = False

    def verify_configuration(self) -> None:
        _verify_configuration(self.config_path, self.config, self.wos_access, self.wos_only)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            os.close(self._database_fd)
            os.close(self._workspace_fd)

    def __enter__(self) -> RunWorkspaceSnapshot:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def capture_run_workspace(
    config_path: Path, loaded_config: LoadedConfig | None = None, *, create: bool = True,
    wos_only: bool = False,
) -> RunWorkspaceSnapshot:
    """Only a new explicit Run may initialize its Workspace.

    Open directory descriptors retain inode identities after Reset, without
    retaining flock exclusion. No checkpoint or new persistent state is added.
    """
    path = config_path.resolve()
    config = loaded_config or load_config(path)
    wos_access = _wos_access(path, config, wos_only)
    with workspace_operation_lock(config.output_dir, create=create) as lock:
        _verify_configuration(path, config, wos_access, wos_only)
        try:
            repository = PaperRepository.open(config.output_dir)
        except LibraryMissingError:
            if not create:
                raise
            repository = PaperRepository.create(config.output_dir)
        with repository:
            initial_papers = {paper.id: paper for paper in repository.list_papers()}
            workspace_id = repository.workspace_id
        workspace_fd = os.dup(lock.directory)
        try:
            database_fd = os.open(DATABASE_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=lock.directory)
            info = os.fstat(database_fd)
        except BaseException:
            os.close(workspace_fd)
            raise
        return RunWorkspaceSnapshot(path, config, wos_access, wos_only, lock.identity,
            (info.st_dev, info.st_ino), workspace_id, initial_papers,
            lock.lock_identity, workspace_fd, database_fd)


def _journal_inputs(journals, wos_only: bool):
    # Names, Groups and Labels only present the captured result. Retrieval and
    # Journal matching use ISSNs; collection additionally consumes allocations.
    return tuple((journal.issn, journal.eissn,
        None if wos_only else journal.access_service_id) for journal in journals)


def _run_inputs(config: LoadedConfig, wos_only: bool):
    return (config.keyword_ast, config.date_spec, config.output_dir,
        _journal_inputs(config.journals, wos_only),
        () if wos_only else config.enabled_providers,
        '' if wos_only else config.crossref_mailto)


def _wos_access(path: Path, config: LoadedConfig, wos_only: bool):
    if not wos_only and 'wos' not in config.enabled_providers:
        return None
    saved = _wos_state(path, config, wos_only)
    # Revisions are diagnostic association data, never the access gate. Only the
    # selected WoS record/institution and prepared binding authorize this stage.
    return BrowserServiceSnapshot(path, read_text_exact(path), saved.revision,
        saved.state.journals, saved.state.access_services, config.institution)


def _wos_state(path: Path, config: LoadedConfig, wos_only: bool):
    saved = read_user_state(path)
    if _journal_inputs(saved.state.journals, wos_only) != _journal_inputs(config.journals, wos_only):
        raise ContentChangedError('Run Journal scope changed while reading WoS access')
    return saved


def _verify_configuration(path: Path, captured: LoadedConfig, wos_access, wos_only: bool):
    current = load_config(path)
    if _run_inputs(current, wos_only) != _run_inputs(captured, wos_only):
        raise ContentChangedError('Run configuration changed (including source scope)')
    if wos_access is not None:
        state = _wos_state(path, current, wos_only)
        selected = tuple(s for s in state.state.access_services if s.name == 'Web of Science')
        original = tuple(s for s in wos_access.services if s.name == 'Web of Science')
        if selected != original or (original and current.institution != captured.institution):
            raise ContentChangedError('Run WoS access changed')


def _verify_snapshot(snapshot: RunWorkspaceSnapshot, lock: WorkspaceOperationLock) -> None:
    if snapshot._closed:
        raise ContentChangedError("Run Workspace snapshot is closed")
    lock.verify()
    if lock.identity != snapshot.workspace_identity or lock.lock_identity != snapshot.lock_identity:
        raise ContentChangedError("Run Workspace was reset or replaced")
    snapshot.verify_configuration()
    # Verify rather than create: a missing/replaced database cannot revive the Run.
    descriptor = os.open(DATABASE_NAME, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=lock.directory)
    try:
        info = os.fstat(descriptor)
        if (info.st_dev, info.st_ino) != snapshot.database_identity:
            raise ContentChangedError("Run Paper library was replaced")
    finally:
        os.close(descriptor)
    with PaperRepository.open(snapshot.config.output_dir, expected_workspace_id=snapshot.workspace_id):
        pass


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
    except TextWriteCommittedError:
        # A body write has already committed; retain its positive-write result.
        raise
    except OSError as error:
        raise ContentChangedError("Run Workspace or configuration location changed") from error
