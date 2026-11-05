"""Refine year-only discovery against dates of the same publication version."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from collections.abc import Sequence

from allfold.canonicalize import consolidate_evidence
from allfold.identifiers import strong_identifiers
from allfold.models import EvidenceDateKind, ProviderWorkEvidence


@dataclass(frozen=True)
class SourceDateResult:
    records: tuple[ProviderWorkEvidence, ...]
    excluded: int


def _version_ids(record: ProviderWorkEvidence):
    # Work/arXiv identity can span versions. Related DOI evidence is expressly
    # excluded: a preprint's date cannot constrain its formal source's Run.
    return {key for key in strong_identifiers(record.external_ids)
            if key[0] not in {"openalex", "arxiv"}}


def _publication_months(record: ProviderWorkEvidence):
    if record.provenance.provider == "openalex" or record.publication_type == "preprint":
        return set()
    if not (record.journal or record.conference or record.publication_type in {"journal", "conference"}):
        return set()
    months = {(item.year, item.month) for item in record.dates if item.month is not None and item.kind in {
        EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE,
        EvidenceDateKind.PUBLISHED_PRINT, EvidenceDateKind.EARLY_ACCESS, EvidenceDateKind.ISSUED,
    }}
    if record.publication_date and len(record.publication_date) >= 7:
        months.add((int(record.publication_date[:4]), int(record.publication_date[5:7])))
    return months


def filter_source_dates(records: Sequence[ProviderWorkEvidence], start: date, end: date) -> SourceDateResult:
    """Retain unknown precision, but discard confirmed out-of-range source hits.

    Multiple discovery hits for one work are an OR: a valid or still-unresolved
    original source hit keeps the group. This never uses aggregate first-public
    or acceptance dates and never touches an existing Paper.
    """
    retained, excluded = [], 0
    lower, upper = (start.year, start.month), (end.year, end.month)
    for group in consolidate_evidence(records).clusters:
        kept, has_discovery = [], False
        for record in group.evidence:
            discovery = record.provenance.role != "supplement"
            year_only = record.publication_date is not None and len(record.publication_date) == 4
            if discovery and year_only:
                ids = _version_ids(record)
                months = {month for other in group.evidence if ids & _version_ids(other)
                          for month in _publication_months(other)}
                if months and not any(lower <= month <= upper for month in months):
                    excluded += 1
                    continue
            kept.append(record)
            has_discovery = has_discovery or discovery
        if has_discovery:
            retained.extend(kept)
    return SourceDateResult(tuple(retained), excluded)
