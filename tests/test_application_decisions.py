"""Trash operations exercise the production application seam with real SQLite."""
import pytest
from allfold.application.decisions import apply_paper_action
from allfold.application.workspace import load_workspace
from allfold.persistence.library_models import BodyReference
from allfold.persistence.paper_repository import PaperRepository, StaleWriteError
from library_application_helpers import create_paper, read_paper


def test_reject_restore_clear_and_unexclude_preserve_uuid_identities_and_pdf(tmp_path):
    _, workspace, paper = create_paper(tmp_path, abstract='Human abstract', notes='Private note')
    body = workspace / 'Documents' / 'retained.pdf'
    body.parent.mkdir()
    body.write_bytes(b'%PDF-isolated-body')
    with PaperRepository.open(workspace) as repository:
        paper = repository.complete_body(paper.token, BodyReference(relative_path='Documents/retained.pdf'))
    original_token = paper.token
    rejected = apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject')
    assert load_workspace(workspace).trash[0].paper_id == paper.id
    restored = apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore')
    assert load_workspace(workspace).downloaded[0].abstract == 'Human abstract'
    with PaperRepository.open(workspace) as repository:
        with pytest.raises(StaleWriteError):
            repository.merge_metadata(original_token, {'abstract': 'Late worker'})
    apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject')
    cleared = apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata')
    assert cleared.paper.metadata is None and cleared.paper.excluded
    assert cleared.paper.id == paper.id and cleared.paper.identities == paper.identities
    assert body.read_bytes() == b'%PDF-isolated-body'
    apply_paper_action(workspace, paper.workspace_id, paper.id, 'unexclude')
    snapshot = load_workspace(workspace)
    assert len(snapshot.downloaded) == 1 and snapshot.downloaded[0].title is None
    assert not snapshot.inbox and not snapshot.trash
    assert rejected.revision < restored.revision < cleared.revision < snapshot.revision


def test_cleared_released_identity_without_body_is_hidden_not_deleted(tmp_path):
    _, workspace, paper = create_paper(tmp_path)
    for action in ('reject', 'clear-metadata', 'unexclude'):
        apply_paper_action(workspace, paper.workspace_id, paper.id, action)
    snapshot = load_workspace(workspace)
    assert not snapshot.inbox and not snapshot.downloaded and not snapshot.trash
    assert read_paper(workspace, paper.id).metadata is None
