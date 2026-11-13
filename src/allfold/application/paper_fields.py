"""Existing local Abstract input and selected field clearing, independent of collectors."""
import hashlib
import json
from uuid import UUID

from allfold.persistence.paper_repository import InvalidPaperState, PaperRepository, StaleWriteError
from allfold.persistence.safe_write import workspace_operation_lock


def field_revision(paper):
    metadata = paper.metadata
    values = dict(workspace_id=str(paper.workspace_id), paper_id=str(paper.id),
        metadata_generation=paper.metadata_generation, operation_generation=paper.operation_generation,
        abstract_generation=paper.abstract_generation,
        fields={name: metadata.model_dump(mode='json')[name] for name in ('abstract', 'authors', 'publication_date')})
    return hashlib.sha256(json.dumps(values, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def fields_payload(paper, revision):
    if paper.excluded or paper.metadata is None:
        raise InvalidPaperState('Local field operations require active, complete Paper metadata')
    metadata = paper.metadata
    return dict(workspace_id=str(paper.workspace_id), snapshot_revision=revision,
        revision=field_revision(paper), abstract=metadata.abstract,
        authors=[author.name for author in metadata.authors], publication_date=metadata.publication_date)


def read_paper_fields(workspace, paper_id: UUID, *, workspace_id: UUID | None = None):
    with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as repository:
        return fields_payload(repository.get(paper_id), repository.revision)


def edit_paper_fields(workspace, workspace_id, paper_id, revision, *, reset_fields=None, abstract=None):
    with workspace_operation_lock(workspace, create=False):
        with PaperRepository.open(workspace, expected_workspace_id=workspace_id) as repository:
            paper = repository.get(paper_id)
            fields_payload(paper, repository.revision)
            if field_revision(paper) != revision:
                raise StaleWriteError('Paper fields changed; refresh before editing')
            if reset_fields is not None:
                if not reset_fields or set(reset_fields) - {'abstract', 'authors', 'publication_date'}:
                    raise ValueError('Select Abstract, Authors or Date to clear')
                changes = {name: () if name == 'authors' else None for name in reset_fields}
            else:
                if not isinstance(abstract, str) or not abstract.strip():
                    raise ValueError('Enter a nonempty Abstract')
                changes = {'abstract': abstract}
            paper = repository.edit_metadata(paper.token, changes)
            return paper, repository.revision, fields_payload(paper, repository.revision)
