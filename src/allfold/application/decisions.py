"""Immediate local Paper operations; cancellation always follows committed exclusion."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from allfold.application.workspace import PaperStatus, WorkspacePaper
from allfold.persistence.paper_repository import InvalidPaperState, PaperRecord, PaperRepository, StaleWriteError
from allfold.persistence.safe_write import workspace_operation_lock


@dataclass(frozen=True)
class DecisionResult:
    paper: PaperRecord
    revision: int


def apply_paper_action(workspace: Path, workspace_id: UUID, paper_id: UUID, action: str, *,
                       expected_status: PaperStatus | None = None, preprint_lookup=None,
                       workspace_registry=None, cancel=True) -> DecisionResult:
    if action == 'clear-metadata' and preprint_lookup is not None and preprint_lookup.cleaning_up(paper_id, workspace_id):
        raise InvalidPaperState('Paper work is still cleaning up; wait before clearing metadata')
    # This lock and every SQLite transaction end before cancellation acquires any
    # coordinator lock. Reject never waits for a network request to return.
    with workspace_registry.paper_gate() if workspace_registry else nullcontext():
        if action == 'clear-metadata' and workspace_registry and workspace_registry.busy(paper_id, workspace_id):
            raise InvalidPaperState('Paper work is still cleaning up; wait before clearing metadata')
        with workspace_operation_lock(workspace, create=False):
            with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as repository:
                paper = repository.get(paper_id)
                if expected_status is not None and WorkspacePaper(paper).status != expected_status:
                    raise StaleWriteError('Paper classification changed; refresh before continuing')
                if action == 'reject':
                    if paper.excluded or paper.metadata is None and paper.body is None:
                        raise InvalidPaperState('Reject requires a visible Candidate or Downloaded Paper')
                    paper = repository.exclude(paper.token)
                elif action in {'restore', 'unexclude'}:
                    if not paper.excluded:
                        raise InvalidPaperState('Paper is not in Trash')
                    paper = repository.restore(paper.token) if paper.metadata is not None else repository.unexclude(paper.token)
                elif action == 'clear-metadata':
                    paper = repository.clear_metadata(paper.token)
                else:
                    raise ValueError('Unknown Paper action')
                result = DecisionResult(paper, repository.revision)
    if action == 'reject' and cancel:
        if workspace_registry is not None:
            workspace_registry.cancel_paper(paper_id, workspace_id)
        if preprint_lookup is not None:
            preprint_lookup.cancel_paper(paper_id, workspace_id)
    return result


def reject_paper(workspace, paper_id, expected_status=None, *, workspace_id, preprint_lookup=None):
    return apply_paper_action(workspace, workspace_id, paper_id, 'reject',
                              expected_status=expected_status, preprint_lookup=preprint_lookup)
