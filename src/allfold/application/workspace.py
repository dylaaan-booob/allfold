"""Read-only production projections of the single SQLite Paper library."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from uuid import UUID

from allfold.config import JournalConfig
from allfold.models import ExternalIds
from allfold.persistence.library_models import PaperRecord
from allfold.persistence.paper_repository import LibraryMissingError, PaperRepository


class PaperStatus(str, Enum):
    CANDIDATE = 'candidate'
    DOWNLOADED = 'downloaded'
    TRASH = 'trash'


@dataclass(frozen=True)
class WorkspacePaper:
    """A full or identity-only record; absent metadata is never fabricated."""
    record: PaperRecord

    @property
    def paper_id(self):
        return self.record.id

    @property
    def metadata_present(self):
        return self.record.metadata is not None

    @property
    def status(self):
        return (PaperStatus.TRASH if self.record.excluded else PaperStatus.DOWNLOADED
                if self.record.body is not None else PaperStatus.CANDIDATE if self.metadata_present else None)

    @property
    def external_ids(self):
        values = {}
        for identity in self.record.identities:
            values.setdefault(identity.namespace, identity.value)
        if primary := self.record.primary_identity:
            values[primary.namespace] = primary.value
        return ExternalIds(**values)

    @property
    def identity_label(self):
        primary = self.record.primary_identity
        identity = primary or self.record.identities[0]
        return f'{identity.namespace}:{identity.value}'

    @property
    def authors(self):
        return tuple(author.name for author in self.record.metadata.authors) if self.metadata_present else ()

    def __getattr__(self, name):
        metadata = self.record.metadata
        if metadata is not None and name in type(metadata).model_fields:
            return getattr(metadata, name)
        if name in {'sources', 'author_keywords', 'indexed_terms', 'journal_issns', 'ordinary_dates', 'preprints',
                    'preprint_evidence', 'preprint_relations'}:
            return ()
        if name in {'title', 'journal', 'conference', 'publication_type', 'publication_date', 'abstract',
                    'first_public_at', 'discovered_at'}:
            return None
        raise AttributeError(name)


class WorkspaceSectionKind(str, Enum):
    GROUP = 'group'
    UNGROUPED = 'ungrouped'
    UNMAPPED = 'unmapped'


@dataclass(frozen=True)
class WorkspaceSection:
    kind: WorkspaceSectionKind
    label: str
    papers: tuple[WorkspacePaper, ...]


@dataclass(frozen=True)
class WorkspaceIssue:
    path: Path
    message: str


@dataclass(frozen=True)
class WorkspaceSnapshot:
    papers: tuple[WorkspacePaper, ...]
    issues: tuple[WorkspaceIssue, ...] = ()
    journals: tuple[JournalConfig, ...] = ()
    workspace_id: UUID | None = None
    revision: int = 0
    initialized: bool = False

    def sections_for(self, status):
        groups = dict.fromkeys(journal.group for journal in self.journals if journal.group is not None)
        keys = (*((WorkspaceSectionKind.GROUP, group) for group in groups),
                (WorkspaceSectionKind.UNGROUPED, 'Ungrouped'), (WorkspaceSectionKind.UNMAPPED, 'Unmapped journals'))
        buckets = {}
        for paper in self.papers:
            if paper.status != status:
                continue
            journal = journal_for_paper(paper, self.journals)
            key = ((WorkspaceSectionKind.UNMAPPED, 'Unmapped journals') if journal is None else
                   (WorkspaceSectionKind.GROUP, journal.group) if journal.group is not None else
                   (WorkspaceSectionKind.UNGROUPED, 'Ungrouped'))
            buckets.setdefault(key, []).append(paper)
        return tuple(WorkspaceSection(kind, label, tuple(buckets[kind, label]))
                     for kind, label in keys if (kind, label) in buckets)

    def papers_for(self, status):
        return tuple(paper for section in self.sections_for(status) for paper in section.papers)

    @property
    def inbox(self):
        return self.papers_for(PaperStatus.CANDIDATE)

    @property
    def downloaded(self):
        return self.papers_for(PaperStatus.DOWNLOADED)

    @property
    def trash(self):
        return self.papers_for(PaperStatus.TRASH)


def journals_for_paper(paper, journals: Sequence[JournalConfig]):
    """Only saved ISSNs establish Journal ownership; cleared records are unassigned."""
    identities = set(paper.journal_issns)
    return tuple(journal for journal in journals if identities.intersection(journal.identifiers))


def journal_for_paper(paper, journals):
    matches = journals_for_paper(paper, journals)
    return matches[0] if len(matches) == 1 else None


def paper_service_assignment(paper, journals):
    choices = {journal.access_service_id for journal in journals_for_paper(paper, journals)}
    if len(choices) == 1 and None not in choices:
        return next(iter(choices)), 'assigned'
    return None, 'ambiguous' if len(choices) > 1 else 'unassigned'


def load_workspace(output_dir: Path, journals: Sequence[JournalConfig] = ()) -> WorkspaceSnapshot:
    """An absent library is a read-only empty state; invalid libraries raise."""
    try:
        with PaperRepository.open(output_dir) as repository:
            revision, records = repository.snapshot()
            papers = [WorkspacePaper(record) for record in records]
            papers.sort(key=lambda paper: paper.title or paper.identity_label)
            papers.sort(key=lambda paper: paper.publication_date or '', reverse=True)
            papers.sort(key=lambda paper: paper.discovered_at.isoformat() if paper.discovered_at else '', reverse=True)
            return WorkspaceSnapshot(tuple(papers), journals=tuple(journals), workspace_id=repository.workspace_id,
                                     revision=revision, initialized=True)
    except LibraryMissingError:
        return WorkspaceSnapshot((), journals=tuple(journals))
