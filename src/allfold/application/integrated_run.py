"""One selected-provider retrieval phase followed by one guarded creation phase."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import date, datetime, timezone
from threading import Event

from allfold.config import ConfigurationError, resolve_runtime_date, validate_runtime_keyword
from allfold.providers.integrated import DiscoveryClient, DiscoveryResult, SourceScope, DISCOVERY_PROVIDERS
from allfold.integrations.openalex_credentials import read_credential
from allfold.progress import ProgressEvent, ProgressStage, ActivityUpdate, ActivityKind


@dataclass(frozen=True)
class IntegratedDiscovery:
    records: tuple
    providers: tuple[DiscoveryResult, ...]
    status: str


def source_scopes(config):
    return tuple(SourceScope('journal', j.name, j.key, tuple(x for x in (j.issn, j.eissn) if x)) for j in config.journals)


def validate_selection(config):
    validate_runtime_keyword(config)
    scopes = source_scopes(config)
    if not scopes:
        raise ConfigurationError('Follow at least one Journal before running', field='sources')
    if not config.enabled_providers or set(config.enabled_providers) - set(DISCOVERY_PROVIDERS):
        raise ConfigurationError('Select OpenAlex and/or Europe PMC for journal discovery', field='enabled_providers')
    return scopes


def discovery_status(results, cancelled=False):
    statuses = {result.status for result in results}
    if cancelled or 'cancelled' in statuses:
        return 'cancelled'
    if statuses <= {'complete','empty'}:
        return 'complete' if 'complete' in statuses else 'empty'
    if any(result.records or result.status in {'complete','empty'} for result in results):
        return 'partial'
    return 'failed'


def discover_selected(config, config_path, *, client_factory=DiscoveryClient, clients=None, cancel_event=None, progress_callback=None):
    scopes = validate_selection(config)
    dates = resolve_runtime_date(config,today=date.today())
    cancel = cancel_event or Event()
    def progress(provider, source, status, count=0):
        if progress_callback:
            progress_callback(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                operation='discovery:' + source.key, label=provider + ': ' + status,source=provider,
                detail=source.name,current=count,unit='work')))
    def execute(provider):
        results=[]
        applicable=scopes
        if cancel.is_set():
            return tuple(DiscoveryResult(provider,s,'cancelled',limitations=('Run cancelled',)) for s in applicable)
        with ExitStack() as stack:
            try:
                if clients is not None:
                    client=clients[provider]
                else:
                    key=read_credential(config_path)[0] if provider=='openalex' else None
                    client=stack.enter_context(client_factory(provider,api_key=key,cancel_event=cancel,progress_callback=progress_callback))
                for source in applicable:
                    if cancel.is_set():
                        results.append(DiscoveryResult(provider,source,'cancelled',limitations=('Run cancelled',)))
                        continue
                    progress(provider,source,'running')
                    result=client.discover(source,config.keyword_ast,dates.from_date,dates.to_date)
                    results.append(result)
                    progress(provider,source,result.status,result.candidates)
            except Exception as error:
                # Host transport or credential failure is local to this provider.
                for source in applicable[len(results):]:
                    results.append(DiscoveryResult(provider,source,'failed',limitations=(f'{provider}: {type(error).__name__}',)))
        return tuple(results)
    selected=tuple(p for p in DISCOVERY_PROVIDERS if p in config.enabled_providers)
    with ThreadPoolExecutor(max_workers=min(4,len(selected))) as pool:
        # map preserves fixed Provider order independent of network completion.
        results=tuple(result for group in pool.map(execute,selected) for result in group)
    return IntegratedDiscovery(tuple(record for result in results for record in result.records),results,discovery_status(results,cancel.is_set()))


def run_integrated(config_path, *, loaded_config=None, workspace_snapshot=None, cancel_event=None,
                   progress_callback=None, client_factory=DiscoveryClient):
    from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
    from allfold.application.monitor import RunResult, RunOutcome, MonitorStatistics, MonitorIssue, MonitorIssueSeverity, MonitorIssueComponent
    from allfold.application.run_state import RunProvider, RunFacts, RunIssueFact, LastRunSnapshot, RecordedRunOutcome, LAST_RUN_SCHEMA_VERSION, LastRunSnapshotWriteError, write_last_run_snapshot
    from allfold.canonicalize import canonicalize_records, consolidate_evidence
    from allfold.identifiers import evidence_identifiers
    from allfold.persistence.discovery_evidence import append_discovery_evidence, DiscoveryScope
    from allfold.persistence.materialize import materialize_papers, read_workspace_identities
    from allfold.persistence.safe_write import ContentChangedError
    cancel=cancel_event or Event()
    if progress_callback:
        progress_callback(ProgressEvent(stage=ProgressStage.CHECKING_MONITOR))
    with ExitStack() as stack:
        snapshot=workspace_snapshot or stack.enter_context(capture_run_workspace(config_path,loaded_config))
        config=snapshot.config
        validate_selection(config)
        dates=resolve_runtime_date(config,today=date.today())
        pacing={}
        clients={}
        class UnavailableClient:
            def __init__(self,provider,message):
                self.provider,self.message=provider,message
            def discover(self,source,*args):
                return DiscoveryResult(self.provider,source,'failed',limitations=(self.message,))
            def lookup(self,*args):
                from allfold.providers.integrated import DiscoveryError
                raise DiscoveryError(self.message)
        for provider in config.enabled_providers:
            try:
                key=read_credential(config_path)[0] if provider=='openalex' else None
                client=client_factory(provider,api_key=key,cancel_event=cancel,pacing_state=pacing,progress_callback=progress_callback)
                clients[provider]=stack.enter_context(client)
            except (ValueError,OSError) as error:
                clients[provider]=UnavailableClient(provider,str(error))
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.DISCOVERING_PAPERS))
        discovery=discover_selected(config,config_path,clients=clients,cancel_event=cancel,progress_callback=progress_callback)
        records=discovery.records
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.PREPARING_PAPERS))
        canonical=canonicalize_records(records)
        issues=[MonitorIssue(MonitorIssueSeverity.ERROR if r.status=='failed' else MonitorIssueSeverity.WARNING,
                    MonitorIssueComponent.OPENALEX,'discovery',f'{r.provider} / {r.source.name}: {message}')
                for r in discovery.providers for message in r.limitations]
        issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,item.stage,item.message) for item in canonical.issues)
        created=existing=0
        def result():
            warnings=tuple(i for i in issues if i.severity is MonitorIssueSeverity.WARNING)
            errors=tuple(i for i in issues if i.severity is MonitorIssueSeverity.ERROR)
            outcome=(RunOutcome.CANCELLED if cancel.is_set() else RunOutcome.FAILED if discovery.status=='failed' else
                     RunOutcome.COMPLETED_WITH_ERRORS if errors else RunOutcome.COMPLETED_WITH_WARNINGS if warnings or discovery.status=='partial' else RunOutcome.COMPLETED)
            facts=RunFacts(finished_at=datetime.now(timezone.utc),created_papers=created,existing_papers=existing,
                statistics={'integrated_candidates':sum(r.candidates for r in discovery.providers),'integrated_deduplicated':len(canonical.papers)},
                issues=tuple(RunIssueFact(category=i.stage,message=i.message,severity=i.severity.value) for i in issues),
                details={'discovery_status':'cancelled' if cancel.is_set() else discovery.status,
                         'provider_runs':[r.fact() for r in discovery.providers]})
            return RunResult(RunProvider.INTEGRATED,dates,len(canonical.papers),created,existing,warnings,errors,outcome,
                             MonitorStatistics(),log_level=config.log_level,facts=facts)
        if cancel.is_set():
            return result()
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.UPDATING_WORKSPACE))
        try:
            with commit_run_workspace(snapshot,cancel_event=cancel) as lock:
                saved=materialize_papers(canonical.papers,config.output_dir,operation_lock=lock,cancel_event=cancel,progress_callback=progress_callback)
                created,existing=len(saved.created_papers),len(saved.existing_papers)
                issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.MATERIALIZATION,'write',i.message) for i in saved.issues)
                identities=read_workspace_identities(lock)
                for group in consolidate_evidence(records).clusters:
                    if cancel.is_set():
                        break
                    keys={key for record in group.evidence for key in evidence_identifiers(record)}
                    owners={item.paper_id for key in keys if (item:=identities.by_identifier.get(key)) and item.paper_id}
                    scopes=tuple(DiscoveryScope(provider=run.provider,journal=run.source.name,key=run.source.key,
                        issns=run.source.issns,from_date=dates.from_date.isoformat(),to_date=dates.to_date.isoformat())
                        for run in discovery.providers if any(record in group.evidence for record in run.records))
                    for paper_id in owners:
                        try:
                            append_discovery_evidence(lock,paper_id,group.evidence,scopes)
                        except (ValueError,OSError,ContentChangedError) as error:
                            issues.append(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.MATERIALIZATION,
                                'evidence_write',f'Discovery evidence could not be saved: {error}'))
                final=result()
                if not cancel.is_set():
                    try:
                        write_last_run_snapshot(config.output_dir,LastRunSnapshot(schema_version=LAST_RUN_SCHEMA_VERSION,resolved_date_range=dates,
                            outcome=RecordedRunOutcome(final.outcome.value),coverage=(),provider=RunProvider.INTEGRATED,facts=final.facts),operation_lock=lock)
                    except LastRunSnapshotWriteError as error:
                        issues.append(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.COVERAGE_SNAPSHOT,
                            'snapshot_write',f'Latest Run result could not be saved: {error}'))
                        final=result()
                return final
        except ContentChangedError:
            if cancel.is_set():
                return result()
            raise
