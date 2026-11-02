"""Independent Crossref Manifest discovery; no DOI requests or persistent state."""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
import re

from allfold.config import JournalConfig
from allfold.coverage import CoverageComponent, CoverageStatus, CoverageUnit
from allfold.providers.crossref import (
    CrossrefClient,
    CrossrefDiscoveryIssue,
    CrossrefIssueSeverity,
    CrossrefJournalQuery,
    CrossrefManifestMember,
    CrossrefManifestUnit,
    CrossrefWorkRecord,
    _merge_manifest_members,
    plan_crossref_queries,
    retrieve_crossref_manifests,
)
from allfold.progress import ProgressCallback


def is_optional_metadata_warning(message: str) -> bool:
    """Only known, harmless normalization messages are omitted from Run results."""
    return message in {
        "invalid author list was treated as missing",
        "invalid abstract was treated as missing",
    } or re.fullmatch(
        r"(?:invalid author entry \d+ was ignored|"
        r"author entry \d+ without a usable name was ignored|"
        r"invalid ORCID for author entry \d+ was ignored|"
        r"invalid (?:published|published-online|published-print|issued) "
        r"(?:date|date-parts entry \d+) was ignored)", message
    ) is not None


@dataclass(frozen=True)
class CrossrefManifestResult:
    plans: tuple[CrossrefJournalQuery, ...]
    units: tuple[CrossrefManifestUnit, ...]
    members: tuple[CrossrefManifestMember, ...]
    coverage: tuple[CoverageUnit, ...]
    issues: tuple[CrossrefDiscoveryIssue, ...]

    @property
    def journal_issns(self) -> dict[str, tuple[str, ...]]:
        return {
            member.doi: tuple(plan.journal.key for plan in self.plans
                              if set(member.issns).intersection(plan.query_issns))
            for member in self.members
        }

    @property
    def records(self) -> tuple[CrossrefWorkRecord, ...]:
        return tuple(record for member in self.members for record in member.records)

    @property
    def excluded_dois(self) -> set[str]:
        return {member.doi for member in self.members
                if member.work_type == "journal-issue" and not member.type_conflict}


def discover_crossref_manifest(
    client: CrossrefClient, journals: Sequence[JournalConfig], from_date: date, to_date: date, *,
    retrieved_at: datetime | None = None, progress_callback: ProgressCallback | None = None,
) -> CrossrefManifestResult:
    plans = plan_crossref_queries(journals)
    ordered = tuple(dict.fromkeys(issn for plan in plans for issn in plan.query_issns))
    units = retrieve_crossref_manifests(client, ordered, from_date, to_date,
                                      retrieved_at=retrieved_at, progress_callback=progress_callback)
    units = tuple(replace(unit, issues=tuple(message for message in unit.issues
                                           if not is_optional_metadata_warning(message)))
                  for unit in units)
    members, _ = _merge_manifest_members(tuple(member for unit in units for member in unit.members))
    by_issn = {unit.issn: unit for unit in units}
    coverage, issues = [], []
    for plan in plans:
        for issn in plan.query_issns:
            raw = by_issn[issn]
            status = CoverageStatus.COMPLETE if raw.complete else (
                CoverageStatus.PARTIAL if raw.members else CoverageStatus.FAILED)
            coverage.append(CoverageUnit("crossref", CoverageComponent.CROSSREF_DISCOVERY, status,
                                         journal=plan.journal.key, issn=issn))
            severity = CrossrefIssueSeverity.WARNING if raw.members else CrossrefIssueSeverity.ERROR
            issues.extend(CrossrefDiscoveryIssue(severity, "manifest", plan.journal.name, issn, message)
                          for message in raw.issues)
    return CrossrefManifestResult(plans, units, members, tuple(coverage), tuple(issues))
