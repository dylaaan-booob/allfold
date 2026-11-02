"""Application orchestration for monitor validation, canonicalization, and runs."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path

from allfold.application.candidate_eligibility import (
    filter_candidate_evidence,
    openalex_attribution,
    valid_doi,
)
from allfold.application.crossref_retrieval import discover_crossref_manifest
from allfold.application.run_state import (
    LAST_RUN_SCHEMA_VERSION,
    LastRunSnapshot,
    LastRunSnapshotWriteError,
    RecordedRunOutcome,
    RunProvider,
    RunFacts,
    RunIdentifierFact,
    RunJournalFact,
    RunIssueFact,
    discovery_provider,
    write_last_run_snapshot,
)
from allfold.canonicalize import (
    CanonicalizationIssue,
    canonicalize_records,
    consolidate_evidence,
)
from allfold.diagnostics import RunDiagnostic, RunDiagnosticKind, RunDiagnosticSummary, summarize_run_diagnostics
from allfold.config import (
    ConfigurationError,
    JournalConfig,
    LoadedConfig,
    LogLevel,
    load_config,
    resolve_runtime_date,
    validate_runtime_keyword,
)
from allfold.coverage import (
    CoverageSummary,
    CoverageUnit,
    summarize_coverage,
)
from allfold.providers.crossref import (
    CrossrefClient,
    CrossrefDiscoveryIssue,
    CrossrefIssueSeverity,
)
from allfold.date_range import (
    DateRangeError,
    ResolvedDateRange,
)
from allfold.keywords import (
    KeywordExpression,
    KeywordSyntaxError,
)
from allfold.persistence.safe_write import workspace_operation_lock, ContentChangedError, WorkspaceOperationLock
from allfold.persistence.materialize import (
    MaterializationIssue,
    MaterializationIssueSeverity,
    materialize_papers,
    read_workspace_identities,
    WorkspaceIdentityIndex,
)
from allfold.models import CanonicalPaper
from allfold.providers.pubmed import PubMedClient, PubMedQueryError, compile_pubmed_query, discover_pubmed
from allfold.integrations.pubmed_credentials import read_credential, PubMedCredentialError
from allfold.progress import (
    ProgressCallback,
    ProgressEvent,
    ProgressStage,
)
from allfold.providers.openalex import (
    DiscoveryIssue,
    IssueSeverity,
    OpenAlexClient,
    ResolvedSource,
    discover_resolved_sources,
    resolve_journal_sources_batched,
)
from allfold.search import (
    SearchBackendError,
    SearchExpressionError,
    build_searchable_projection,
    match_searchable_projections,
)


class MonitorIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class MonitorIssueComponent(str, Enum):
    CONFIGURATION = "configuration"
    SEARCH = "search"
    DATE_RANGE = "date_range"
    OPENALEX = "openalex"
    CROSSREF_DISCOVERY = "crossref_discovery"
    PUBMED_DISCOVERY = "pubmed_discovery"
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
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"


@dataclass(frozen=True)
class MonitorStatistics:
    openalex_records: int = 0
    crossref_discovery_records: int = 0
    pubmed_records: int = 0
    pubmed_search_total: int = 0
    pubmed_failed_batches: int = 0
    evidence_clusters: int = 0
    retained_clusters: int = 0
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


@dataclass(frozen=True)
class _PreparedInvocation:
    config: LoadedConfig
    keyword_ast: KeywordExpression
    resolved_date_range: ResolvedDateRange
    journals: tuple[JournalConfig, ...]


@dataclass(frozen=True)
class _CanonicalCoreResult:
    provider: RunProvider
    config: LoadedConfig | None
    resolved_date_range: ResolvedDateRange | None
    papers: tuple[CanonicalPaper, ...]
    resolved_sources: tuple[ResolvedSource, ...]
    warnings: tuple[MonitorIssue, ...]
    errors: tuple[MonitorIssue, ...]
    outcome: RunOutcome
    statistics: MonitorStatistics
    coverage: tuple[CoverageUnit, ...] = ()
    diagnostics: tuple[RunDiagnostic, ...] = ()
    saved_dois: frozenset[str] = frozenset()
    facts: RunFacts = field(default_factory=RunFacts)

    @property
    def coverage_summary(self) -> tuple[CoverageSummary, ...]:
        return summarize_coverage(self.coverage)

    @property
    def log_level(self) -> LogLevel | None:
        return self.config.log_level if self.config is not None else None


def _emit_progress(
    callback: ProgressCallback | None,
    stage: ProgressStage,
) -> None:
    if callback is not None:
        callback(ProgressEvent(stage=stage))


def _split_issues(
    issues: Sequence[MonitorIssue],
) -> tuple[tuple[MonitorIssue, ...], tuple[MonitorIssue, ...]]:
    warnings = tuple(
        issue for issue in issues if issue.severity is MonitorIssueSeverity.WARNING
    )
    errors = tuple(
        issue for issue in issues if issue.severity is MonitorIssueSeverity.ERROR
    )
    return warnings, errors


def _run_outcome(
    warnings: Sequence[MonitorIssue],
    errors: Sequence[MonitorIssue],
) -> RunOutcome:
    if errors:
        return RunOutcome.COMPLETED_WITH_ERRORS
    if warnings:
        return RunOutcome.COMPLETED_WITH_WARNINGS
    return RunOutcome.COMPLETED


def _issue_fact(issue: MonitorIssue) -> RunIssueFact:
    if issue.component is MonitorIssueComponent.COVERAGE_SNAPSHOT:
        category = "snapshot_write"
    elif issue.component is MonitorIssueComponent.MATERIALIZATION:
        category = "paper_write"
    elif issue.stage == "skipped":
        category = "exclusion"
    elif issue.component in (MonitorIssueComponent.CONFIGURATION, MonitorIssueComponent.SEARCH, MonitorIssueComponent.DATE_RANGE):
        category = "configuration"
    elif issue.stage == "doi_conflict" or issue.component in (MonitorIssueComponent.CONSOLIDATION, MonitorIssueComponent.CANONICALIZATION):
        category = "identity"
    else:
        category = "retrieval" if issue.severity is MonitorIssueSeverity.ERROR else "notice"
    return RunIssueFact(category=category, message=issue.message, severity=issue.severity.value,
                        journal=issue.journal, issn=issue.issn)


def _configuration_issue(
    error: ConfigurationError,
    config_path: Path,
) -> MonitorIssue:
    return MonitorIssue(
        severity=MonitorIssueSeverity.ERROR,
        component=MonitorIssueComponent.CONFIGURATION,
        stage="configuration",
        message=str(error),
        field=error.field,
        config_path=config_path,
    )


def _search_issue(
    error: SearchExpressionError | SearchBackendError | KeywordSyntaxError,
    *,
    config_path: Path,
    stage: str,
) -> MonitorIssue:
    return MonitorIssue(
        severity=MonitorIssueSeverity.ERROR,
        component=MonitorIssueComponent.SEARCH,
        stage=stage,
        message=str(error),
        field="keyword_expression",
        config_path=config_path,
    )


def _date_issue(
    error: DateRangeError,
    *,
    config_path: Path,
    stage: str,
) -> MonitorIssue:
    return MonitorIssue(
        severity=MonitorIssueSeverity.ERROR,
        component=MonitorIssueComponent.DATE_RANGE,
        stage=stage,
        message=str(error),
        field=error.field,
        config_path=config_path,
    )


def _openalex_issue(issue: DiscoveryIssue) -> MonitorIssue:
    return MonitorIssue(
        severity=(
            MonitorIssueSeverity.ERROR
            if issue.severity is IssueSeverity.ERROR
            else MonitorIssueSeverity.WARNING
        ),
        component=MonitorIssueComponent.OPENALEX,
        stage=issue.stage,
        message=issue.message,
        journal=issue.journal,
        issn=issue.issn,
        record_id=issue.record_id,
    )


def _crossref_discovery_issue(issue: CrossrefDiscoveryIssue) -> MonitorIssue:
    return MonitorIssue(
        severity=(
            MonitorIssueSeverity.ERROR
            if issue.severity is CrossrefIssueSeverity.ERROR
            else MonitorIssueSeverity.WARNING
        ),
        component=MonitorIssueComponent.CROSSREF_DISCOVERY,
        stage=issue.stage,
        message=issue.message,
        journal=issue.journal,
        issn=issue.issn,
        record_id=issue.record_id,
        doi=issue.doi,
    )


def _canonicalization_issue(
    issue: CanonicalizationIssue,
    *,
    component: MonitorIssueComponent,
) -> MonitorIssue:
    return MonitorIssue(
        severity=MonitorIssueSeverity.WARNING,
        component=component,
        stage=issue.stage,
        message=issue.message,
        record_ids=issue.record_ids,
    )


def _materialization_issue(issue: MaterializationIssue) -> MonitorIssue:
    return MonitorIssue(
        severity=(
            MonitorIssueSeverity.ERROR
            if issue.severity is MaterializationIssueSeverity.ERROR
            else MonitorIssueSeverity.WARNING
        ),
        component=MonitorIssueComponent.MATERIALIZATION,
        stage="write",
        message=issue.message,
        path=issue.path,
    )


def _coverage_snapshot_issue(error: LastRunSnapshotWriteError) -> MonitorIssue:
    return MonitorIssue(
        severity=MonitorIssueSeverity.WARNING,
        component=MonitorIssueComponent.COVERAGE_SNAPSHOT,
        stage="write",
        message=f"failed to persist latest-run coverage snapshot: {error}",
        path=error.path,
    )


def _prepare_invocation(
    config_path: Path, *, loaded_config: LoadedConfig, provider: RunProvider,
) -> tuple[_PreparedInvocation | None, LoadedConfig, MonitorIssue | None]:
    try:
        resolved = resolve_runtime_date(loaded_config, today=date.today())
        if provider is RunProvider.PUBMED:
            compile_pubmed_query(loaded_config.pubmed_query_mode, loaded_config.keyword_ast)
            read_credential(config_path)
        else:
            if provider is RunProvider.OPENALEX:
                read_credential(config_path, provider="openalex")
            validate_runtime_keyword(loaded_config)
    except (PubMedQueryError, PubMedCredentialError) as error:
        return None, loaded_config, _configuration_issue(
            ConfigurationError(str(error), field="keyword_expression" if isinstance(error, PubMedQueryError) else f"{provider.value}_api_key"), config_path)
    except DateRangeError as error:
        return None, loaded_config, _date_issue(error, config_path=config_path, stage="configured_date")
    except (SearchExpressionError, SearchBackendError) as error:
        return None, loaded_config, _search_issue(error, config_path=config_path, stage="configured_keyword")
    return _PreparedInvocation(loaded_config, loaded_config.keyword_ast, resolved, loaded_config.journals), loaded_config, None


def _invalid_core_result(
    provider: RunProvider,
    config: LoadedConfig | None,
    issue: MonitorIssue,
) -> _CanonicalCoreResult:
    return _CanonicalCoreResult(
        provider=provider, config=config,
        resolved_date_range=None,
        papers=(),
        resolved_sources=(),
        warnings=(),
        errors=(issue,),
        outcome=RunOutcome.INVALID_CONFIGURATION,
        statistics=MonitorStatistics(),
    )


def _execute_canonical_core(
    prepared: _PreparedInvocation, config_path: Path, *, provider: RunProvider,
    identity: WorkspaceIdentityIndex,
    progress_callback: ProgressCallback | None = None,
) -> _CanonicalCoreResult:
    _emit_progress(progress_callback, ProgressStage.DISCOVERING_PAPERS)
    saved: set[str] = set()
    issues = [_materialization_issue(issue) for issue in identity.issues]
    diagnostics = []

    def can_create(doi: str) -> bool:
        if doi in identity.saved:
            saved.add(doi)
            return False
        return identity.can_create(doi)

    sources = ()
    journal_facts = []
    detail_facts = {}
    openalex_records = crossref_records = pubmed_records = pubmed_total = pubmed_failed = 0
    if provider is RunProvider.OPENALEX:
        with OpenAlexClient(api_key=read_credential(config_path, provider="openalex")[0]) as client:
            resolutions = resolve_journal_sources_batched(client, prepared.journals,
                                                          progress_callback=progress_callback)
            discovery = discover_resolved_sources(client, resolutions,
                prepared.resolved_date_range.from_date, prepared.resolved_date_range.to_date,
                progress_callback=progress_callback)
        sources, coverage = discovery.sources, discovery.coverage
        for resolution, unit in zip(resolutions, discovery.units, strict=True):
            status = unit.coverage.status.value.lower()
            if resolution.source is None and resolution.status.value == "UNAVAILABLE":
                status = "unrecognized"
            elif status == "complete" and not unit.records:
                status = "empty"
            journal_facts.append(RunJournalFact(
                key=resolution.journal.key, name=resolution.journal.name, status=status,
                records=len(unit.records) if resolution.source is not None else None,
                identifiers=tuple(RunIdentifierFact(issn=item.requested_issn, status=item.status.value,
                    source_id=item.evidence.source_id if item.evidence else None, message=item.diagnostic)
                    for item in resolution.identifiers)))
        identifier_statuses = [item.status.value for resolution in resolutions for item in resolution.identifiers]
        detail_facts["source_resolution"] = {status: identifier_statuses.count(status) for status in sorted(set(identifier_statuses))}
        issues.extend(_openalex_issue(issue) for issue in discovery.issues)
        attribution = openalex_attribution(discovery, prepared.journals)
        candidates = {doi for doi in attribution if can_create(doi)}
        records = tuple(record.to_evidence() for record in discovery.records
                        if valid_doi(record.external_ids.doi) in candidates)
        openalex_records = len(discovery.records)
    elif provider is RunProvider.CROSSREF:
        with CrossrefClient(mailto=prepared.config.crossref_mailto or None) as client:
            discovery = discover_crossref_manifest(client, prepared.journals,
                prepared.resolved_date_range.from_date, prepared.resolved_date_range.to_date,
                progress_callback=progress_callback)
        coverage = discovery.coverage
        by_issn = {unit.issn: unit for unit in discovery.units}
        detail_facts["manifest"] = dict(issn_queries=len(discovery.units),
            complete=sum(unit.complete for unit in discovery.units),
            partial=sum(not unit.complete and bool(unit.members) for unit in discovery.units),
            failed=sum(not unit.complete and not unit.members for unit in discovery.units))
        for plan in discovery.plans:
            units = [by_issn[issn] for issn in plan.query_issns]
            complete = all(unit.complete for unit in units)
            members = {member.doi for unit in units for member in unit.members}
            journal_facts.append(RunJournalFact(key=plan.journal.key, name=plan.journal.name,
                status=("complete" if members else "empty") if complete else ("partial" if members else "failed"),
                records=len(members), identifiers=tuple(RunIdentifierFact(issn=unit.issn,
                    status=("complete" if unit.members else "empty") if unit.complete else ("partial" if unit.members else "failed"),
                    records=len(unit.members), message="; ".join(unit.issues) or None) for unit in units)))
        issues.extend(_crossref_discovery_issue(issue) for issue in discovery.issues)
        attribution = discovery.journal_issns
        excluded = discovery.excluded_dois
        candidates = {doi for doi, keys in attribution.items() if keys and can_create(doi)} - excluded
        records = tuple(record.to_evidence() for record in discovery.records
                        if valid_doi(record.doi) in candidates)
        crossref_records = len(discovery.members)
        for member in discovery.members:
            if member.doi in excluded:
                diagnostics.append(RunDiagnostic(RunDiagnosticKind.NON_CANDIDATE_EXCLUSION,
                                                 "Crossref journal-issue excluded", (member.doi,)))
            if member.type_conflict:
                diagnostics.append(RunDiagnostic(RunDiagnosticKind.SCOPE_DISPUTE,
                                                 "Conflicting Crossref types; no type exclusion", (member.doi,)))

    elif provider is RunProvider.PUBMED:
        try:
            api_key, _ = read_credential(config_path)
        except PubMedCredentialError as error:
            return _invalid_core_result(provider, prepared.config,
                _configuration_issue(ConfigurationError(str(error), field="pubmed_api_key"), config_path))
        compiled = compile_pubmed_query(prepared.config.pubmed_query_mode, prepared.config.keyword_ast)
        with PubMedClient(api_key=api_key, progress_callback=progress_callback) as client:
            discovery = discover_pubmed(client, prepared.journals, compiled,
                prepared.resolved_date_range.from_date, prepared.resolved_date_range.to_date,
                can_create=can_create)
        records, coverage = discovery.records, discovery.coverage
        detail_facts["skipped"] = discovery.skipped
        missing_phrases = {item.issn: item.message for item in discovery.issues
                           if item.stage == "phrase_not_found" and item.issn is not None}
        # ESearch has combined-query coverage only. Phrase evidence is identifier-local.
        for journal in prepared.journals:
            identifiers = tuple(RunIdentifierFact(issn=issn,
                status="not_found", message=missing_phrases[issn])
                for issn in journal.identifiers if issn in missing_phrases)
            if identifiers:
                journal_facts.append(RunJournalFact(key=journal.key, name=journal.name,
                    identifiers=identifiers, status="unrecognized" if all(issn in missing_phrases for issn in journal.identifiers) else "identifier_warning"))
        attribution = {}
        for item in records:
            doi = item.external_ids.doi
            attribution[doi] = tuple(sorted(set(attribution.get(doi, ())) | set(item.monitor_journal_issns)))
        issues.extend(MonitorIssue(MonitorIssueSeverity(item.severity), MonitorIssueComponent.PUBMED_DISCOVERY,
                                   item.stage, item.message, record_id=item.record_id,
                                   journal=next((j.name for j in prepared.journals if item.issn in j.identifiers), None),
                                   issn=item.issn)
                      for item in discovery.issues)
        pubmed_records, pubmed_total, pubmed_failed = discovery.fetched_records, discovery.search_total, discovery.failed_batches
    else:
        raise ValueError(f"Unsupported discovery Provider: {provider}")

    evidence = filter_candidate_evidence(records, attribution, prepared.journals)
    groups = {}
    for item in evidence:
        groups.setdefault(item.external_ids.doi, []).append(item)
    if provider is RunProvider.PUBMED:
        # ESearch already applied all keywords. Saved metadata dates are not discovery filters.
        matched = set(groups)
    else:
        _emit_progress(progress_callback, ProgressStage.MATCHING_LITERATURE)
        search_dois = sorted(groups)
        projections = [build_searchable_projection(groups[doi]) for doi in search_dois]
        try:
            hits = match_searchable_projections(prepared.keyword_ast, projections) if projections else ()
            matched = {doi for doi, hit in zip(search_dois, hits, strict=True) if hit}
        except (SearchExpressionError, SearchBackendError) as error:
            issues.append(_search_issue(error, config_path=config_path, stage="matching"))
            warnings, errors = _split_issues(issues)
            return _CanonicalCoreResult(provider, prepared.config, prepared.resolved_date_range, (), sources,
                warnings, errors, RunOutcome.INVALID_CONFIGURATION, MonitorStatistics(), coverage=coverage)
    _emit_progress(progress_callback, ProgressStage.PREPARING_PAPERS)
    evidence = tuple(item for item in evidence if item.external_ids.doi in matched)
    consolidation = consolidate_evidence(evidence)
    diagnostics.extend(consolidation.diagnostics)
    issues.extend(_canonicalization_issue(issue, component=MonitorIssueComponent.CONSOLIDATION)
                  for issue in consolidation.issues)
    retained = consolidation.clusters
    canonical = canonicalize_records(tuple(item for cluster in retained for item in cluster.evidence)) if retained else None
    issues.extend(_canonicalization_issue(issue, component=MonitorIssueComponent.CANONICALIZATION)
                  for issue in (canonical.issues if canonical else ()))
    warnings, errors = _split_issues(issues)
    return _CanonicalCoreResult(
        provider=provider, config=prepared.config, resolved_date_range=prepared.resolved_date_range,
        papers=canonical.papers if canonical else (), resolved_sources=sources,
        warnings=warnings, errors=errors, outcome=_run_outcome(warnings, errors),
        statistics=MonitorStatistics(openalex_records=openalex_records,
            crossref_discovery_records=crossref_records,
            pubmed_records=pubmed_records, pubmed_search_total=pubmed_total, pubmed_failed_batches=pubmed_failed,
            evidence_clusters=len(consolidation.clusters), retained_clusters=len(retained),
            consolidation_issues=len(consolidation.issues), canonicalization_issues=len(canonical.issues) if canonical else 0,
            provider_issues=len(discovery.issues)),
        coverage=coverage, diagnostics=tuple(diagnostics), saved_dois=frozenset(saved),
        facts=RunFacts(journals=tuple(journal_facts), details=detail_facts),
    )


def _materialize_canonical_result(
    core: _CanonicalCoreResult,
    output_dir: Path | None,
    *,
    progress_callback: ProgressCallback | None = None,
    operation_lock: WorkspaceOperationLock | None = None,
) -> RunResult:
    if core.outcome is RunOutcome.INVALID_CONFIGURATION:
        return RunResult(
            provider=core.provider,
            resolved_date_range=core.resolved_date_range,
            canonical_paper_count=len(core.papers),
            created_papers=0,
            matched_existing_papers=0,
            warnings=core.warnings,
            errors=core.errors,
            outcome=RunOutcome.INVALID_CONFIGURATION,
            statistics=core.statistics,
            coverage=core.coverage,
            diagnostics=core.diagnostics,
            resolved_sources=core.resolved_sources,
            log_level=core.log_level,
            facts=core.facts.model_copy(update=dict(finished_at=datetime.now(timezone.utc),
                created_papers=0, existing_papers=0,
                issues=tuple(_issue_fact(issue) for issue in (*core.warnings, *core.errors)))),
        )

    assert output_dir is not None
    _emit_progress(progress_callback, ProgressStage.UPDATING_WORKSPACE)
    # Direct materialization callers still acquire their own lock; Run reuses its
    # whole-operation ownership instead of recursively acquiring a second flock.
    if operation_lock is None:
        materialization = materialize_papers(core.papers, output_dir, progress_callback=progress_callback)
    else:
        materialization = materialize_papers(
            core.papers, output_dir, progress_callback=progress_callback, operation_lock=operation_lock,
        )
    materialization_issues = tuple(
        _materialization_issue(issue) for issue in materialization.issues
    )
    warnings, errors = _split_issues(
        (*core.warnings, *core.errors, *materialization_issues)
    )
    return RunResult(
        provider=core.provider,
        resolved_date_range=core.resolved_date_range,
        canonical_paper_count=len(core.papers),
        created_papers=len(materialization.created_papers),
        matched_existing_papers=len(materialization.existing_papers),
        warnings=warnings,
        errors=errors,
        outcome=_run_outcome(warnings, errors),
        statistics=replace(
            core.statistics,
            materialization_issues=len(materialization.issues),
        ),
        coverage=core.coverage,
        diagnostics=core.diagnostics,
        resolved_sources=core.resolved_sources,
        log_level=core.log_level,
        facts=core.facts,
    )


def run_monitor(
    config_path: Path,
    *,
    provider: RunProvider,
    progress_callback: ProgressCallback | None = None,
    operation_lock: WorkspaceOperationLock | None = None,
    loaded_config: LoadedConfig | None = None,
) -> RunResult:
    provider = discovery_provider(provider)
    try:
        configured = loaded_config if loaded_config is not None else load_config(config_path)
    except ConfigurationError as error:
        _emit_progress(progress_callback, ProgressStage.CHECKING_MONITOR)
        return _materialize_canonical_result(
            _invalid_core_result(provider, None, _configuration_issue(error, config_path)), None,
        )
    if operation_lock is not None:
        operation_lock.verify()
        if configured.output_dir != operation_lock.path:
            raise ContentChangedError("Run configuration differs from reserved Workspace")
        return _run_monitor_owned(config_path, provider=provider, progress_callback=progress_callback, operation_lock=operation_lock,
                                  loaded_config=configured)
    # Run 从网络发现开始排他，不能让 Reset 趁物化之前删除工作区。
    with workspace_operation_lock(configured.output_dir, create=True) as lock:
        return _run_monitor_owned(config_path, provider=provider, progress_callback=progress_callback, operation_lock=lock,
                                  loaded_config=configured)


def _run_monitor_owned(
    config_path: Path,
    *,
    provider: RunProvider,
    loaded_config: LoadedConfig,
    progress_callback: ProgressCallback | None = None,
    operation_lock: WorkspaceOperationLock,
) -> RunResult:
    _emit_progress(progress_callback, ProgressStage.CHECKING_MONITOR)
    prepared, config, preflight_issue = _prepare_invocation(
        config_path, loaded_config=loaded_config, provider=provider,
    )
    if preflight_issue is not None:
        core = _invalid_core_result(provider, config, preflight_issue)
        return _materialize_canonical_result(core, None)
    assert prepared is not None
    operation_lock.verify()
    if prepared.config.output_dir != operation_lock.path:
        raise ContentChangedError("Run configuration differs from owned Workspace")
    identity = read_workspace_identities(operation_lock)
    core = _execute_canonical_core(
        prepared, config_path, provider=provider, identity=identity, progress_callback=progress_callback,
    )
    output_dir = prepared.config.output_dir
    final_identity = read_workspace_identities(operation_lock)
    confirmed_saved = {doi for doi in core.saved_dois
                       if final_identity.complete and final_identity.saved.get(doi) == identity.saved.get(doi)
                       and doi in final_identity.saved}
    changed = core.saved_dois - confirmed_saved
    if changed:
        errors = (*core.errors, *(MonitorIssue(MonitorIssueSeverity.ERROR,
            MonitorIssueComponent.MATERIALIZATION, "identity_changed",
            "Saved Paper identity changed during Run", doi=doi) for doi in sorted(changed)))
        core = replace(core, errors=errors, outcome=_run_outcome(core.warnings, errors))
    result = _materialize_canonical_result(
        core,
        output_dir,
        progress_callback=progress_callback,
        operation_lock=operation_lock,
    )
    result = replace(result, matched_existing_papers=result.matched_existing_papers + len(confirmed_saved))
    result = replace(result, facts=result.facts.model_copy(update=dict(
        finished_at=datetime.now(timezone.utc), created_papers=result.created_papers,
        existing_papers=result.matched_existing_papers, statistics=asdict(result.statistics),
        issues=tuple(_issue_fact(issue) for issue in (*result.warnings, *result.errors) if issue.stage != "skipped"),
        details={**result.facts.details, "exclusions": {item.kind.value: item.logical_groups for item in result.diagnostic_summary}},
    )))
    if result.outcome is RunOutcome.INVALID_CONFIGURATION:
        return result

    assert output_dir is not None
    assert result.resolved_date_range is not None
    operation_lock.verify()
    snapshot = LastRunSnapshot(
        schema_version=LAST_RUN_SCHEMA_VERSION,
        resolved_date_range=result.resolved_date_range,
        outcome=RecordedRunOutcome(result.outcome.value),
        coverage=result.coverage,
        provider=provider,
        facts=result.facts,
    )
    try:
        operation_lock.verify()
        write_last_run_snapshot(output_dir, snapshot)
    except LastRunSnapshotWriteError as error:
        warning = _coverage_snapshot_issue(error)
        warnings = (*result.warnings, warning)
        return replace(
            result,
            warnings=warnings,
            outcome=_run_outcome(warnings, result.errors),
            facts=result.facts.model_copy(update={"issues": (*result.facts.issues, _issue_fact(warning))}),
        )
    return result
