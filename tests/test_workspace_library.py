from allfold.application.workspace import load_workspace
from allfold.persistence.paper_repository import PaperRepository
from allfold.persistence.library_models import PaperMetadata, BodyReference
from allfold.models import ExternalIds


def test_workspace_reads_only_sqlite_and_keeps_identity_only_body(tmp_path):
    workspace = tmp_path / 'workspace'
    assert not load_workspace(workspace).initialized
    assert not workspace.exists()
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/paper'),
            metadata=PaperMetadata(title='A real paper', abstract='Saved')).paper
        paper = repository.complete_body(paper.token, BodyReference(relative_path='Documents/retained.pdf'))
        paper = repository.exclude(paper.token)
        paper = repository.clear_metadata(paper.token)
        repository.unexclude(paper.token)
    snapshot = load_workspace(workspace)
    assert snapshot.initialized
    assert not snapshot.inbox
    assert len(snapshot.downloaded) == 1
    projected = snapshot.downloaded[0]
    assert projected.paper_id == paper.id
    assert projected.title is None and not projected.metadata_present
    assert projected.identity_label == 'doi:10.5555/paper'
    assert not (workspace / 'Papers').exists()
