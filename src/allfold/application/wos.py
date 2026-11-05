"""Create-only WoS capture over the existing DOI/Markdown write boundary."""
from __future__ import annotations

from dataclasses import dataclass, field

from allfold.identifiers import paper_identifiers
from allfold.persistence.materialize import (
    read_workspace_identities,
    render_paper_markdown,
)
from allfold.persistence.naming import paper_filename
from allfold.persistence.inbox import render_default_inbox_base
from allfold.persistence.safe_write import (
    ContentChangedError, TextWriteCommittedError, WorkspaceTextDirectory, workspace_text_directory,
)


@dataclass
class WoSWrites:
    created_papers: int = 0
    skipped_existing_papers: int = 0
    conflicts: int = 0
    write_failures: int = 0
    issues: list[str] = field(default_factory=list)
    written_paths: list[str] = field(default_factory=list)


def persist_wos(papers, lock, *, check_current, cancelled, result=None):
    result = result or WoSWrites()
    with workspace_text_directory(lock, 'Papers') as directory:
        index = read_workspace_identities(lock)
        if not index.complete:
            raise ContentChangedError('Workspace Paper identity index is incomplete')
        result.issues.extend(issue.message for issue in index.issues)
        def before_write():
            if cancelled():
                raise InterruptedError('Run WoS canceled')
            check_current()
            lock.verify()

        saved_keys = {key: identity.path for key, identity in index.by_identifier.items()}
        used_ids = {identity.paper_id for identity in index.by_identifier.values()}

        for paper in papers:
            before_write()
            try:
                keys = paper_identifiers(paper)
                matches = {saved_keys[key] for key in keys if key in saved_keys}
                if (not keys or keys.intersection(index.blocked_identifiers) or len(matches) > 1
                        or paper.id in used_ids and not matches):
                    result.conflicts += 1
                    result.issues.append(f'{paper.id}: conflicting Paper identity/UUID')
                    continue
                if matches:
                    result.skipped_existing_papers += 1
                    continue
                contents = render_paper_markdown(paper)
                filename = paper_filename(paper.metadata.title, paper.id, used_ids)
                before_write()
                try:
                    directory.create(filename, contents)
                except TextWriteCommittedError as error:
                    # Creation committed; a sync warning must not invite retry.
                    result.write_failures += 1
                    result.issues.append(f'{paper.doi}: committed with filesystem warning: {error}')
                result.created_papers += 1
                result.written_paths.append(str(lock.path / 'Papers' / filename))
                saved_keys.update({key: lock.path / "Papers" / filename for key in keys})
                used_ids.add(paper.id)
            except InterruptedError:
                raise
            except ContentChangedError as error:
                check_current()
                lock.verify()
                result.conflicts += 1
                result.issues.append(f'{paper.doi}: {error}')
            except (ValueError, OSError) as error:
                result.write_failures += 1
                result.issues.append(f'{paper.doi}: {error}')
        if result.created_papers and not (lock.path / 'Inbox.base').exists():
            before_write()
            try:
                WorkspaceTextDirectory(lock, lock.directory, lock.identity).create('Inbox.base', render_default_inbox_base())
            except FileExistsError:
                pass
    return result
