"""Create-only WoS capture over the existing DOI/Markdown write boundary."""
from __future__ import annotations

from dataclasses import dataclass, field

from allfold.application.decisions import _read_paper_candidate
from allfold.persistence.markdown_state import parse_paper_state
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
        # Include saved source evidence when checking UT-to-DOI collisions.
        saved_uts = {}
        bad_uts = set()
        for doi, identity in index.saved.items():
            read = _read_paper_candidate(identity.path, directory.directory)
            state = parse_paper_state(identity.path, read.contents)
            if state:
                for source in state.sources:
                    if source.provider == 'wos':
                        if source.record_id in saved_uts and saved_uts[source.record_id] != doi:
                            bad_uts.add(source.record_id)
                        saved_uts[source.record_id] = doi

        def before_write():
            if cancelled():
                raise InterruptedError('Run WoS canceled')
            check_current()
            lock.verify()

        saved_dois = set(index.saved)
        used_ids = {identity.paper_id for identity in index.saved.values()}

        for paper in papers:
            before_write()
            try:
                if paper.doi in index.blocked or any(s.record_id in bad_uts or saved_uts.get(s.record_id, paper.doi) != paper.doi for s in paper.sources):
                    result.conflicts += 1
                    result.issues.append(f'{paper.doi}: conflicting DOI/UUID or WoS source identity')
                    continue
                if paper.doi in saved_dois:
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
                saved_dois.add(paper.doi)
                used_ids.add(paper.id)
                for source in paper.sources:
                    saved_uts[source.record_id] = paper.doi
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
