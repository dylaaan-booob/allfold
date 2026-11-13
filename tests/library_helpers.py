"""Isolated SQLite setup for existing application/provider regression fixtures."""
from allfold.persistence.paper_repository import LibraryMissingError, PaperRepository
from allfold.persistence.run_library import metadata_from_run


def capture_papers(papers, workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    try:
        repository = PaperRepository.open(workspace)
    except LibraryMissingError:
        repository = PaperRepository.create(workspace)
    with repository:
        return tuple(repository.create_or_match(repository.workspace_id,
            direct_ids=paper.external_ids, metadata=metadata_from_run(paper)).paper for paper in papers)


def read_papers(workspace):
    with PaperRepository.open(workspace) as repository:
        return repository.list_papers()


def read_paper(workspace, paper_id):
    with PaperRepository.open(workspace) as repository:
        return repository.get(paper_id)
