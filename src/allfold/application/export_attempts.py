"""Transient import identity and guarded parent completion.

Existing export_attempt frontmatter is legacy user data. Never generate, clear
or repurpose it for new imports.
"""
from __future__ import annotations
import re

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import secrets
from uuid import UUID
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from allfold.application.workspace import PlannedImportPaper

from allfold.browser_diagnostics import format_browser_diagnostic
from allfold.application.decisions import _locate_paper, _read_paper_candidate
from allfold.persistence.markdown_state import PaperMarkdownState, parse_paper_state, serialize_document
from allfold.models import ExportAttempt, ExportAttemptState, WorkflowStatus
from allfold.persistence.safe_write import (
    ContentChangedError, CompareReadError, WorkspaceOperationLock,
    replace_regular_text_at_identity, workspace_operation_lock,
)


class PdfOutcome(str, Enum):
    VERIFIED_SUCCESS = "verified success"
    VERIFIED_FAILURE = "verified failure"
    UNVERIFIED = "unverified"

class ExportAttemptError(RuntimeError):
    """An import cannot safely use the selected Paper revision."""


@dataclass(frozen=True)
class ExportReservation:
    """An invocation-local identity fence; never a persisted Paper marker."""

    attempt: ExportAttempt
    file_identity: tuple[int, int]
    contents: str
    lock_identity: tuple[int, int]


@dataclass(frozen=True)
class _PaperRead:
    state: PaperMarkdownState
    directory_identity: tuple[int, int]
    file_identity: tuple[int, int]


@contextmanager
def export_operation_lock(output_dir: Path, operation_lock: WorkspaceOperationLock | None = None):
    if operation_lock is None:
        with workspace_operation_lock(output_dir) as lock:
            yield lock
    else:
        if Path(os.path.abspath(output_dir)) != operation_lock.path:
            raise ExportAttemptError("Workspace operation owner does not match")
        operation_lock.verify()
        yield operation_lock


def _read_target(lock: WorkspaceOperationLock, paper_id: UUID, path: Path | None = None) -> _PaperRead:
    """Read only the frozen path for batch work; standalone callers locate once."""
    lock.verify()
    directory = os.open("Papers", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=lock.directory)
    try:
        if path is None:
            located, failure = _locate_paper(lock.path, paper_id, WorkflowStatus.KEPT,
                                             require_safe_candidates=True, directory=directory,
                                             paper_reads={})
            if failure is not None:
                raise ExportAttemptError(failure.message)
            path = located
        assert path is not None
        if path.parent != lock.path / "Papers" or path.name in {".", ".."}:
            raise ExportAttemptError("Paper location changed")
        info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        if info.st_nlink != 1:
            raise ExportAttemptError("Paper has multiple hard-link locations")
        candidate = _read_paper_candidate(path, directory)
        state = parse_paper_state(path, candidate.contents)
        if (state is None or not state.updateable or state.paper_id != paper_id
                or state.status is not WorkflowStatus.KEPT or state.external_ids is None):
            raise ExportAttemptError("Import requires a safe kept Paper with valid DOI")
        lock.verify()
        return _PaperRead(state, candidate.directory_identity, candidate.file_identity)
    finally:
        os.close(directory)


def reserve_export_attempt(output_dir: Path, paper_id: UUID) -> ExportReservation:
    """Reserve an invocation-local identity for a standalone Import; makes no disk changes."""
    with workspace_operation_lock(output_dir) as lock:
        return _reserve_export_attempt_locked(lock, paper_id)


def _reserve_export_attempt_locked(lock: WorkspaceOperationLock, paper_id: UUID, *,
                                   expected_paper: PlannedImportPaper | None = None,
                                   expected_papers_identity: tuple[int, int] | None = None) -> ExportReservation:
    read = _read_target(lock, paper_id, expected_paper.path if expected_paper else None)
    if expected_papers_identity is not None and read.directory_identity != expected_papers_identity:
        raise ContentChangedError("Papers directory replaced after planning")
    if expected_paper is not None and (
        read.state.original != expected_paper.contents
        or read.file_identity != expected_paper.file_identity
        or read.state.external_ids.doi != expected_paper.doi
    ):
        raise ContentChangedError("Planned Paper changed before import")
    # 临时凭据只用于本次命令、回执及 Paper CAS；旧 export_attempt 不参与授权。
    attempt = ExportAttempt(
        state=ExportAttemptState.PENDING, attempt_id=secrets.token_hex(32),
        paper_id=paper_id, doi=read.state.external_ids.doi, expected_status="kept",
        workspace_path=str(lock.path), paper_path=str(read.state.path.relative_to(lock.path)),
        workspace_identity=lock.identity, papers_identity=read.directory_identity,
    )
    return ExportReservation(attempt, read.file_identity, read.state.original, lock.lock_identity)


def _matching_read(lock: WorkspaceOperationLock, reservation: ExportReservation) -> _PaperRead:
    attempt = reservation.attempt
    if lock.lock_identity != reservation.lock_identity or attempt.workspace_identity != lock.identity:
        raise ExportAttemptError("Workspace lock identity changed")
    path = lock.path / attempt.paper_path
    read = _read_target(lock, attempt.paper_id, path)
    if (attempt.workspace_path != str(lock.path) or attempt.papers_identity != read.directory_identity
            or attempt.doi != read.state.external_ids.doi
            or read.state.original != reservation.contents or read.file_identity != reservation.file_identity):
        raise ContentChangedError("Import Paper identity or revision changed")
    return read


def validate_export_reservation(reservation: ExportReservation, *,
                                operation_lock: WorkspaceOperationLock | None = None) -> None:
    """Require the exact planned revision immediately before one native dispatch."""
    with export_operation_lock(Path(reservation.attempt.workspace_path), operation_lock) as lock:
        _matching_read(lock, reservation)


class ExportCompletionOutcome(str, Enum):
    EXPORTED = "EXPORTED"
    UNCERTAIN = "UNCERTAIN"
    NO_EFFECT = "NO_EFFECT"
    FAILED = "FAILED"


@dataclass(frozen=True)
class ExportCompletionResult:
    outcome: ExportCompletionOutcome
    message: str


def _commit_exported_locked(reservation: ExportReservation, lock: WorkspaceOperationLock) -> None:
    read = _matching_read(lock, reservation)
    frontmatter = dict(read.state.frontmatter)
    frontmatter["status"] = WorkflowStatus.EXPORTED.value
    # Old export_attempt is historical metadata; no implicit cleanup of user data.
    contents = serialize_document(frontmatter, read.state.body)
    replace_regular_text_at_identity(
        read.state.path, contents, expected_contents=read.state.original,
        expected_directory_identity=read.directory_identity,
        expected_file_identity=read.file_identity,
        expected_workspace_identity=lock.identity, operation_lock=lock,
        validate_before_replace=lambda: _matching_read(lock, reservation),
    )


def complete_electron_import(reservation: ExportReservation, result: dict, *,
                             operation_lock: WorkspaceOperationLock) -> ExportCompletionResult:
    """Consume the structured result of the one live bridge call under its original lock."""
    parent = result.get("parent", {})
    if not isinstance(parent, dict):
        parent = {}
    identity = parent.get("requested_id")
    confirmed = (result.get("settled") is True and parent.get("outcome") == "confirmed"
                 and type(parent.get("status")) is int and parent["status"] == 200
                 and parent.get("protocol") == "local-api-v3"
                 and isinstance(identity, str) and re.fullmatch(r"[23456789ABCDEFGHIJKLMNPQRSTUVWXYZ]{8}", identity) is not None
                 and parent.get("accepted_id") == identity)
    if confirmed:
        try:
            _commit_exported_locked(reservation, operation_lock)
            return ExportCompletionResult(ExportCompletionOutcome.EXPORTED,
                "Native parent exact key accepted by Local API; PDF remains unverified.")
        except (ExportAttemptError, ContentChangedError, CompareReadError, OSError) as error:
            return ExportCompletionResult(ExportCompletionOutcome.FAILED,
                f"Parent accepted but Paper write conflicted: {error}; inspect Zotero before retry.")
    if result.get("settled") is True and parent.get("outcome") == "no_effect":
        return ExportCompletionResult(ExportCompletionOutcome.NO_EFFECT,
            _electron_failure_message(result) + " Native parent was not created; Paper remains kept.")
    return ExportCompletionResult(ExportCompletionOutcome.UNCERTAIN,
        _electron_failure_message(result) + " Parent acceptance uncertain; Paper remains kept. Inspect Zotero before retrying.")


def _electron_failure_message(result: dict) -> str:
    """Import-only fallback; common protocol rendering belongs to browser_diagnostics."""
    diagnostic = result.get("diagnostic")
    if not isinstance(diagnostic, dict):
        return "Native save did not confirm a parent."
    return format_browser_diagnostic(diagnostic)
