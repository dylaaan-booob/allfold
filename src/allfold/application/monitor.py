"""Integrated Run public result contract and application entry point."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from allfold.application.run_state import RunProvider, RunFacts, discovery_provider
from allfold.config import LoadedConfig, LogLevel
from allfold.coverage import CoverageSummary, CoverageUnit, summarize_coverage
from allfold.date_range import ResolvedDateRange
from allfold.diagnostics import RunDiagnostic, RunDiagnosticSummary, summarize_run_diagnostics
from allfold.providers.openalex import ResolvedSource
from allfold.progress import ProgressCallback

class MonitorIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class MonitorIssueComponent(str, Enum):
    CONFIGURATION = "configuration"
    SEARCH = "search"
    DATE_RANGE = "date_range"
    OPENALEX = "openalex"
    CONSOLIDATION = "consolidation"
    CANONICALIZATION = "canonicalization"
    MATERIALIZATION = "materialization"
    COVERAGE_SNAPSHOT = "coverage_snapshot"


@dataclass(frozen=True)
class MonitorIssue:
    severity: MonitorIssueSeverity
    component: MonitorIssueComponent
    stage: str
    message: str
    journal: str | None = None
    issn: str | None = None
    record_id: str | None = None
    doi: str | None = None
    record_ids: tuple[str, ...] = ()
    path: Path | None = None
    field: str | None = None
    config_path: Path | None = None


class RunOutcome(str, Enum):
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"


@dataclass(frozen=True)
class MonitorStatistics:
    openalex_records: int = 0
    consolidation_issues: int = 0
    canonicalization_issues: int = 0
    provider_issues: int = 0
    materialization_issues: int = 0


@dataclass(frozen=True)
class RunResult:
    provider: RunProvider
    resolved_date_range: ResolvedDateRange | None
    canonical_paper_count: int
    created_papers: int
    matched_existing_papers: int
    warnings: tuple[MonitorIssue, ...]
    errors: tuple[MonitorIssue, ...]
    outcome: RunOutcome
    statistics: MonitorStatistics
    coverage: tuple[CoverageUnit, ...] = ()
    resolved_sources: tuple[ResolvedSource, ...] = ()
    log_level: LogLevel | None = None
    diagnostics: tuple[RunDiagnostic, ...] = ()
    facts: RunFacts = field(default_factory=RunFacts)

    @property
    def coverage_summary(self) -> tuple[CoverageSummary, ...]:
        return summarize_coverage(self.coverage)

    @property
    def diagnostic_summary(self) -> tuple[RunDiagnosticSummary, ...]:
        return summarize_run_diagnostics(self.diagnostics)



def run_monitor(config_path: Path, *, provider: RunProvider = RunProvider.INTEGRATED,
                loaded_config: LoadedConfig | None = None, workspace_snapshot=None,
                cancel_event=None, progress_callback: ProgressCallback | None = None) -> RunResult:
    discovery_provider(provider)
    from allfold.application.integrated_run import run_integrated
    return run_integrated(config_path, loaded_config=loaded_config, workspace_snapshot=workspace_snapshot,
                          cancel_event=cancel_event, progress_callback=progress_callback)
