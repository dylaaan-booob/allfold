"""Direct WoS capture over the same guarded SQLite Paper boundary as Run."""
from __future__ import annotations

from dataclasses import dataclass, field

from allfold.identifiers import paper_identifiers
from allfold.persistence.paper_repository import (
    IdentityConflict, LibraryError, LibraryMissingError, PaperRepository,
)
from allfold.persistence.run_library import RunIdentityIndex, metadata_from_run


@dataclass
class WoSWrites:
    created_papers: int = 0
    skipped_existing_papers: int = 0
    rebuilt_papers: int = 0
    conflicts: int = 0
    write_failures: int = 0
    issues: list[str] = field(default_factory=list)
    written_paper_ids: list[str] = field(default_factory=list)


def persist_wos(papers, lock, *, check_current, cancelled, result=None, workspace_snapshot=None):
    result = result or WoSWrites()
    check_current()
    lock.verify()
    try:
        repository = PaperRepository.open(lock.path, expected_workspace_id=(
            workspace_snapshot.workspace_id if workspace_snapshot else None))
    except LibraryMissingError:
        if workspace_snapshot is not None:
            raise
        # Only this explicit direct capture entry may initialize a new library.
        repository = PaperRepository.create(lock.path)
    with repository:
        initial = workspace_snapshot.initial_papers if workspace_snapshot else {
            paper.id: paper for paper in repository.list_papers()}
        for paper in papers:
            if cancelled():
                raise InterruptedError('Run WoS canceled')
            check_current()
            lock.verify()
            try:
                keys = paper_identifiers(paper)
                index = RunIdentityIndex.read(repository)
                owners = index.owners(keys)
                if len(owners) > 1:
                    raise IdentityConflict('Direct identities have different saved Paper owners')
                owner = repository.get(next(iter(owners))) if owners else None
                if owner is not None and owner.excluded:
                    continue
                if owner is not None and owner.metadata is not None:
                    result.skipped_existing_papers += 1
                    continue
                metadata = metadata_from_run(paper)
                if owner is not None:
                    if not index.target(keys, initial):
                        continue
                    saved = repository.rebuild_from_run(initial[owner.id].token,
                        direct_ids=paper.external_ids, metadata=metadata)
                    result.rebuilt_papers += 1
                    result.skipped_existing_papers += 1
                else:
                    created = repository.create_or_match(repository.workspace_id,
                        direct_ids=paper.external_ids, metadata=metadata)
                    saved = created.paper
                    if created.created:
                        result.created_papers += 1
                    elif not saved.excluded and saved.metadata is not None:
                        result.skipped_existing_papers += 1
                    else:
                        continue
                result.written_paper_ids.append(str(saved.id))
            except IdentityConflict as error:
                result.conflicts += 1
                result.issues.append(str(error))
            except (LibraryError, ValueError) as error:
                result.write_failures += 1
                result.issues.append(str(error))
    return result
