"""One selected-provider retrieval phase followed by one guarded creation phase."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, replace
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
    journals = tuple(SourceScope('journal',j.name,j.key,tuple(x for x in (j.issn,j.eissn) if x),getattr(j,'dblp_stream',None)) for j in config.journals)
    conferences = tuple(SourceScope('conference',c.name,c.id,stream=c.dblp_stream) for c in getattr(config,'conferences',()))
    return journals + conferences


def validate_selection(config):
    validate_runtime_keyword(config)
    scopes = source_scopes(config)
    if not scopes:
        raise ConfigurationError('Follow at least one Journal or Conference before running',field='sources')
    selected = set(config.enabled_providers) & set(DISCOVERY_PROVIDERS)
    if not selected:
        raise ConfigurationError('Select at least one Discovery Provider; metadata-only providers cannot discover Papers',field='enabled_providers')
    if not config.journals and 'dblp' not in selected:
        raise ConfigurationError('Conference-only Run requires DBLP',field='enabled_providers')
    if config.journals and selected == {'dblp'} and not any(s.stream for s in scopes):
        raise ConfigurationError('DBLP has no verified Stream mapping for the selected Journals',field='enabled_providers')
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
        if cancel.is_set():
            return tuple(DiscoveryResult(provider,s,'cancelled',limitations=('Run cancelled',)) for s in scopes)
        with ExitStack() as stack:
            try:
                if clients is not None:
                    client=clients[provider]
                else:
                    key=read_credential(config_path)[0] if provider=='openalex' else None
                    client=stack.enter_context(client_factory(provider,api_key=key,cancel_event=cancel))
                for source in scopes:
                    if cancel.is_set():
                        results.append(DiscoveryResult(provider,source,'cancelled',limitations=('Run cancelled',)))
                        continue
                    progress(provider,source,'running')
                    result=client.discover(source,config.keyword_ast,dates.from_date,dates.to_date)
                    results.append(result)
                    progress(provider,source,result.status,result.candidates)
            except Exception as error:
                # Host transport or credential failure is local to this provider.
                for source in scopes[len(results):]:
                    results.append(DiscoveryResult(provider,source,'failed',limitations=(f'{provider}: {type(error).__name__}',)))
        return tuple(results)
    selected=tuple(p for p in DISCOVERY_PROVIDERS if p in config.enabled_providers)
    with ThreadPoolExecutor(max_workers=min(4,len(selected))) as pool:
        # map preserves fixed Provider order independent of network completion.
        results=tuple(result for group in pool.map(execute,selected) for result in group)
    # Conferences not selected through DBLP are a real scope omission even when
    # every selected journal provider succeeds.
    if 'dblp' not in selected:
        results += tuple(DiscoveryResult('dblp',source,'skipped',limitations=('DBLP not selected; Conference was not run',)) for source in scopes if source.kind=='conference')
    return IntegratedDiscovery(tuple(record for result in results for record in result.records),results,discovery_status(results,cancel.is_set()))


def run_integrated(config_path, *, loaded_config=None, workspace_snapshot=None, cancel_event=None,
                   progress_callback=None, client_factory=DiscoveryClient, completion=None):
    from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
    from allfold.application.monitor import RunResult, RunOutcome, MonitorStatistics, MonitorIssue, MonitorIssueSeverity, MonitorIssueComponent
    from allfold.application.run_state import RunProvider, RunFacts, RunIssueFact, LastRunSnapshot, RecordedRunOutcome, LAST_RUN_SCHEMA_VERSION, write_last_run_snapshot
    from allfold.canonicalize import canonicalize_records, consolidate_evidence
    from allfold.identifiers import strong_identifiers
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
        # Initial identity scan is brief. Final materialization repeats it under
        # the commit lock, so concurrent Runs cannot create duplicate identities.
        with commit_run_workspace(snapshot) as lock:
            initial=read_workspace_identities(lock)
        pacing={}
        clients={}
        for provider in config.enabled_providers:
            key=read_credential(config_path)[0] if provider=='openalex' else None
            if provider in DISCOVERY_PROVIDERS:
                client=client_factory(provider,api_key=key,cancel_event=cancel,pacing_state=pacing)
            else:
                from allfold.providers.supplemental import SupplementalClient
                client=SupplementalClient(provider,cancel_event=cancel,pacing_state=pacing)
            clients[provider]=stack.enter_context(client)
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.DISCOVERING_PAPERS))
        discovery=discover_selected(config,config_path,clients=clients,cancel_event=cancel,progress_callback=progress_callback)
        records=discovery.records
        supplementation=()
        if not cancel.is_set():
            if progress_callback:
                progress_callback(ProgressEvent(stage=ProgressStage.PREPARING_PAPERS))
            if completion is None:
                from allfold.application.metadata_completion import complete_metadata
                completion=complete_metadata
            groups=consolidate_evidence(records).clusters
            known, fresh=[],[]
            for group in groups:
                keys={key for record in group.evidence for key in strong_identifiers(record.external_ids,record.related_dois)}
                (known if not initial.complete or any(key in initial.by_identifier or key in initial.blocked_identifiers for key in keys) else fresh).extend(group.evidence)
            completed=completion(tuple(fresh),config.enabled_providers,clients=clients,cancel_event=cancel)
            records=tuple(known)+tuple(completed.records)
            supplementation=completed.issues
        canonical=canonicalize_records(records)
        issues=[MonitorIssue(MonitorIssueSeverity.ERROR if r.status=='failed' else MonitorIssueSeverity.WARNING,
                    MonitorIssueComponent.OPENALEX,'discovery',f'{r.provider} / {r.source.name}: {message}')
                for r in discovery.providers for message in r.limitations]
        issues.extend(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.CANONICALIZATION,'supplement',
                                  f'{item.provider}: {item.message}') for item in supplementation)
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
                         'provider_runs':[r.fact() for r in discovery.providers],
                         'supplement_failures':[dict(provider=i.provider,identifier=i.identifier,message=i.message) for i in supplementation]})
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
                final=result()
                if not cancel.is_set():
                    write_last_run_snapshot(config.output_dir,LastRunSnapshot(schema_version=LAST_RUN_SCHEMA_VERSION,resolved_date_range=dates,
                        outcome=RecordedRunOutcome(final.outcome.value),coverage=(),provider=RunProvider.INTEGRATED,facts=final.facts))
                return final
        except ContentChangedError:
            if cancel.is_set():
                return result()
            raise
