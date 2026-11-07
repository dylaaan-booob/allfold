"""One selected-provider retrieval phase followed by one guarded creation phase."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from threading import Event

from allfold.config import ConfigurationError, resolve_runtime_date, validate_runtime_keyword
from allfold.providers.integrated import DiscoveryClient, DiscoveryResult, SourceScope, DISCOVERY_PROVIDERS, RUN_PROVIDERS
from allfold.integrations.openalex_credentials import read_credential
from allfold.progress import ProgressEvent, ProgressStage, ActivityUpdate, ActivityKind


@dataclass(frozen=True)
class IntegratedDiscovery:
    records: tuple
    providers: tuple[DiscoveryResult, ...]
    status: str
    details: dict = field(default_factory=dict)
    journals: tuple = ()
    statistics: dict = field(default_factory=dict)


def source_scopes(config):
    return tuple(SourceScope('journal', j.name, j.key, tuple(x for x in (j.issn, j.eissn) if x)) for j in config.journals)


def validate_selection(config):
    validate_runtime_keyword(config)
    scopes = source_scopes(config)
    if not scopes:
        raise ConfigurationError('Follow at least one Journal before running', field='sources')
    if not config.enabled_providers or set(config.enabled_providers) - set(RUN_PROVIDERS):
        raise ConfigurationError('Select WoS, OpenAlex and/or Europe PMC for journal discovery', field='enabled_providers')
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


def discover_selected(config, config_path, *, client_factory=DiscoveryClient, clients=None, cancel_event=None, progress_callback=None, lightweight=False):
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
                    discover = getattr(client, 'discover_candidates', client.discover) if lightweight else client.discover
                    result=discover(source,config.keyword_ast,dates.from_date,dates.to_date)
                    results.append(result)
                    progress(provider,source,result.status,result.candidates)
            except Exception as error:
                # Host transport or credential failure is local to this provider.
                for source in applicable[len(results):]:
                    results.append(DiscoveryResult(provider,source,'failed',limitations=(f'{provider}: {type(error).__name__}',)))
        return tuple(results)
    selected=tuple(p for p in DISCOVERY_PROVIDERS if p in config.enabled_providers)
    if not selected:
        return IntegratedDiscovery((), (), 'empty')
    with ThreadPoolExecutor(max_workers=min(4,len(selected))) as pool:
        # map preserves fixed Provider order independent of network completion.
        results=tuple(result for group in pool.map(execute,selected) for result in group)
    return IntegratedDiscovery(tuple(record for result in results for record in result.records),results,discovery_status(results,cancel.is_set()))


def creation_details(discovery, clients, identities, cancel):
    """Gather all lightweight identities before selecting one creation source per work."""
    from allfold.canonicalize import consolidate_evidence
    from allfold.identifiers import evidence_identifiers, normalize_external_id
    if cancel.is_set():
        return discovery
    needed={provider: [] for provider in DISCOVERY_PROVIDERS}
    candidates={}
    for cluster in consolidate_evidence(discovery.records).clusters:
        keys={key for record in cluster.evidence for key in evidence_identifiers(record)}
        if (not identities.complete or keys & identities.blocked_identifiers or
                any(key in identities.by_identifier for key in keys) or
                any(record.provenance.provider=='wos' or record.title for record in cluster.evidence)):
            continue
        ordered=sorted((record for record in cluster.evidence if record.provenance.provider in DISCOVERY_PROVIDERS),
            key=lambda record:(record.publication_type!='journal',DISCOVERY_PROVIDERS.index(record.provenance.provider)))
        for choice in ordered:
            provider=choice.provenance.provider
            native=normalize_external_id(provider,getattr(choice.external_ids,provider))
            if native:
                needed[provider].append(native)
                candidates[(provider,native)]=cluster.evidence
                break
    runs=list(discovery.providers)
    for provider, identifiers in needed.items():
        if not identifiers or cancel.is_set(): continue
        client=clients[provider]
        try:
            detail=client.lookup_many(provider,identifiers)
        except Exception as error:
            detail=DiscoveryResult(provider, SourceScope('journal',''), 'failed', limitations=(f'Creation details: {type(error).__name__}',))
        for index, run in enumerate(runs):
            if run.provider!=provider: continue
            additions=[]
            run_keys={key for record in run.records for key in evidence_identifiers(record)}
            for record in detail.records:
                native=normalize_external_id(provider,getattr(record.external_ids,provider))
                cluster=candidates.get((provider,native),())
                cluster_keys={key for item in cluster for key in evidence_identifiers(item)}
                if not cluster_keys & run_keys: continue
                additions.append(record.model_copy(update={
                    'journal':record.journal or run.source.name,
                    'monitor_journal_issns':tuple(sorted(set(record.monitor_journal_issns+run.source.issns))),
                    'provenance':record.provenance.model_copy(update={'role':'discovery'})}))
            limits=tuple(dict.fromkeys((*run.limitations,*detail.limitations)))
            status='cancelled' if cancel.is_set() else 'partial' if limits else run.status
            runs[index]=replace(run,records=(*run.records,*additions),limitations=limits,status=status)
    return replace(discovery, records=tuple(record for run in runs for record in run.records),
        providers=tuple(runs), status=discovery_status(runs,cancel.is_set()))


def run_integrated(config_path, *, loaded_config=None, workspace_snapshot=None, cancel_event=None,
                   progress_callback=None, client_factory=DiscoveryClient, wos_stage=None, workflow_id=None):
    from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
    from allfold.application.monitor import RunResult, RunOutcome, MonitorIssue, MonitorIssueSeverity, MonitorIssueComponent
    from allfold.application.run_state import RunProvider, RunFacts, RunIssueFact, LastRunSnapshot, RecordedRunOutcome, INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshotWriteError, write_last_run_snapshot
    from allfold.canonicalize import canonicalize_records, consolidate_evidence
    from allfold.identifiers import evidence_identifiers
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
        with commit_run_workspace(snapshot) as lock:
            initial_identities = read_workspace_identities(lock)
        browser = IntegratedDiscovery((), (), 'empty')
        if 'wos' in config.enabled_providers and not cancel.is_set():
            try:
                if wos_stage is None:
                    raise ValueError('WoS browser stage is unavailable')
                browser = wos_stage(snapshot, cancel_event=cancel, workflow_id=workflow_id, progress_callback=progress_callback)
            except (ValueError, OSError, ContentChangedError) as error:
                source = SourceScope('journal', 'Web of Science')
                browser = IntegratedDiscovery((), (DiscoveryResult('wos', source, 'failed', limitations=(str(error),)),), 'failed')
        for provider in DISCOVERY_PROVIDERS:
            if provider not in config.enabled_providers or cancel.is_set():
                continue
            try:
                key=read_credential(config_path)[0] if provider=='openalex' else None
                client=client_factory(provider,api_key=key,cancel_event=cancel,pacing_state=pacing,progress_callback=progress_callback)
                def guard():
                    with commit_run_workspace(snapshot,cancel_event=cancel):
                        pass
                client.request_guard=guard
                clients[provider]=stack.enter_context(client)
            except (ValueError,OSError) as error:
                clients[provider]=UnavailableClient(provider,str(error))
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.DISCOVERING_PAPERS))
        api=discover_selected(config,config_path,clients=clients,cancel_event=cancel,progress_callback=progress_callback,lightweight=True)
        discovery=IntegratedDiscovery((*browser.records, *api.records), (*browser.providers, *api.providers),
            discovery_status((*browser.providers, *api.providers),cancel.is_set()), browser.details, browser.journals, browser.statistics)
        discovery = creation_details(discovery, clients, initial_identities, cancel)
        records=discovery.records
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.PREPARING_PAPERS))
        groups=consolidate_evidence(records).clusters
        issues=[MonitorIssue(MonitorIssueSeverity.ERROR if r.status=='failed' else MonitorIssueSeverity.WARNING,
                    MonitorIssueComponent.DISCOVERY,'discovery',f'{r.provider} / {r.source.name}: {message}')
                for r in discovery.providers for message in r.limitations]
        created=existing=conflicts=0
        provider_totals=None
        def result():
            warnings=tuple(i for i in issues if i.severity is MonitorIssueSeverity.WARNING)
            errors=tuple(i for i in issues if i.severity is MonitorIssueSeverity.ERROR)
            outcome=(RunOutcome.CANCELLED if cancel.is_set() else RunOutcome.FAILED if discovery.status=='failed' else
                     RunOutcome.COMPLETED_WITH_ERRORS if errors else RunOutcome.COMPLETED_WITH_WARNINGS if warnings or discovery.status=='partial' else RunOutcome.COMPLETED)
            facts=RunFacts(finished_at=datetime.now(timezone.utc),created_papers=created,existing_papers=existing,
                statistics={**discovery.statistics,'integrated_candidates':sum(r.candidates for r in discovery.providers),'integrated_deduplicated':created+existing,'conflicts':discovery.statistics.get('conflicts',0)+conflicts},
                journals=discovery.journals,
                issues=tuple(RunIssueFact(category=i.stage,message=i.message,severity=i.severity.value) for i in issues),
                details={**discovery.details,**({'provider_totals':provider_totals} if provider_totals is not None else {}),'discovery_status':'cancelled' if cancel.is_set() else discovery.status,
                         'provider_runs':[r.fact() for r in discovery.providers]})
            return RunResult(provider=RunProvider.INTEGRATED, resolved_date_range=dates,
                             warnings=warnings, errors=errors, outcome=outcome, facts=facts)
        if cancel.is_set():
            return result()
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.UPDATING_WORKSPACE))
        try:
            with commit_run_workspace(snapshot,cancel_event=cancel) as lock:
                # Classify the complete direct identifiers again under the commit
                # lock, including IDs that cannot all fit one external_ids slot.
                current=read_workspace_identities(lock)
                incoming=[]
                eligible=[]
                for group in groups:
                    keys={key for record in group.evidence for key in evidence_identifiers(record)}
                    owners={item.paper_id for key in keys if (item:=current.by_identifier.get(key)) and item.paper_id}
                    if len(owners)>1 or keys & current.blocked_identifiers:
                        conflicts += 1
                        involved={item.paper_id for key in keys for item in
                            [current.by_identifier.get(key)] if item and item.paper_id}
                        # Invalid or multiply-owned IDs are retained in index issues.
                        issues.append(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,
                            'identity',f'Ambiguous discovery identifiers {sorted(keys)}; Paper UUIDs {sorted(map(str,involved))}; '
                            + '; '.join(item.message for item in current.issues)))
                        continue
                    eligible.append(group)
                    if not owners:
                        incoming.extend(group.evidence)
                canonical=canonicalize_records(incoming)
                issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,item.stage,item.message)
                    for item in canonical.issues)
                saved=materialize_papers(canonical.papers,config.output_dir,operation_lock=lock,cancel_event=cancel,progress_callback=progress_callback)
                created=len(saved.created_papers)
                issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.MATERIALIZATION,'write',i.message) for i in saved.issues)
                identities=read_workspace_identities(lock)
                matched_owners=set()
                matched_record_ids=set()
                for group in eligible:
                    keys={key for record in group.evidence for key in evidence_identifiers(record)}
                    owners={item.paper_id for key in keys if (item:=identities.by_identifier.get(key)) and item.paper_id}
                    if len(owners)==1 and not keys & identities.blocked_identifiers and identities.complete:
                        matched_owners.update(owners)
                        matched_record_ids.update(map(id,group.evidence))
                created_ids={item.paper_id for item in identities.by_identifier.values() if item.path in saved.created_papers}
                existing=len(matched_owners-created_ids)
                updated_runs=[]
                for run in discovery.providers:
                    owners={item.paper_id for record in run.records if id(record) in matched_record_ids for key in evidence_identifiers(record)
                        if (item:=identities.by_identifier.get(key)) and item.paper_id in matched_owners}
                    updated_runs.append(replace(run,created=len(owners & created_ids),existing=len(owners-created_ids)))
                discovery=replace(discovery,providers=tuple(updated_runs))
                provider_totals=[]
                for provider in RUN_PROVIDERS:
                    runs=[run for run in discovery.providers if run.provider==provider]
                    if not runs: continue
                    owners={item.paper_id for run in runs for record in run.records if id(record) in matched_record_ids for key in evidence_identifiers(record)
                        if (item:=identities.by_identifier.get(key)) and item.paper_id in matched_owners}
                    provider_totals.append(dict(provider=provider,status=discovery_status(runs,cancel.is_set()),
                        candidates=sum(run.candidates for run in runs),created=len(owners & created_ids),existing=len(owners-created_ids),
                        limitations=list(dict.fromkeys(message for run in runs for message in run.limitations))))
                final=result()
                if not cancel.is_set():
                    try:
                        write_last_run_snapshot(config.output_dir,LastRunSnapshot(schema_version=INTEGRATED_RUN_SCHEMA_VERSION,resolved_date_range=dates,
                            outcome=RecordedRunOutcome(final.outcome.value),provider=RunProvider.INTEGRATED,facts=final.facts),operation_lock=lock)
                    except LastRunSnapshotWriteError as error:
                        issues.append(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.SNAPSHOT,
                            'snapshot_write',f'Latest Run result could not be saved: {error}'))
                        final=result()
                return final
        except ContentChangedError:
            if cancel.is_set():
                return result()
            raise
