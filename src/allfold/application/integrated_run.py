"""One concurrent Discovery/Work phase and one Completion-before-create phase."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from threading import Event, Condition, Lock

from allfold.config import ConfigurationError, resolve_runtime_date, validate_runtime_keyword
from allfold.integrations.openalex_credentials import read_credential
from allfold.progress import ProgressEvent, ProgressStage, ActivityUpdate, ActivityKind
from allfold.application.metadata_completion import formal_records
from allfold.identifiers import evidence_identifiers, strong_identifiers
from allfold.providers.integrated import (
    Cancelled, DISCOVERY_PROVIDERS, RUN_PROVIDERS, DiscoveryClient, DiscoveryError, DiscoveryResult,
    IdentityMismatch, SourceScope,
)


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
        raise ConfigurationError('Select PubMed, WoS and/or OpenAlex for journal discovery', field='enabled_providers')
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


def discover_selected(config, config_path, *, client_factory=DiscoveryClient, clients=None,
                      cancel_event=None, progress_callback=None, records_callback=None):
    """Execute only selected journal producers, retaining native complete evidence."""
    scopes = validate_selection(config)
    dates = resolve_runtime_date(config, today=date.today())
    cancel = cancel_event or Event()
    def execute(provider):
        with ExitStack() as stack:
            try:
                if cancel.is_set():
                    return tuple(DiscoveryResult(provider,s,'cancelled') for s in scopes)
                if clients is None:
                    key = read_credential(config_path, provider=provider)[0]
                    client = stack.enter_context(client_factory(provider, api_key=key,
                        cancel_event=cancel, progress_callback=progress_callback))
                else:
                    client = clients[provider]
                if progress_callback:
                    progress_callback(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                        operation='discovery', label=provider + ' journal discovery', source=provider)))
                results = client.discover_many(scopes, config.keyword_ast, dates.from_date, dates.to_date,
                    records_callback=records_callback)
                # The final handoff also covers producers with no page callback.
                if records_callback:
                    records_callback(tuple(record for result in results for record in result.records))
            except Exception as error:
                results = tuple(DiscoveryResult(provider,s,'cancelled' if cancel.is_set() else 'failed',
                    limitations=(f'{provider}: {type(error).__name__}',)) for s in scopes)
            if progress_callback:
                count = sum(len(result.records) for result in results)
                status = discovery_status(results, cancel.is_set())
                progress_callback(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                    operation='discovery', label=f'{provider} journal discovery: {status}', source=provider,
                    current=count, total=count, unit='work')))
            return results
    selected = tuple(p for p in DISCOVERY_PROVIDERS if p in config.enabled_providers)
    if not selected:
        return IntegratedDiscovery((), (), 'empty')
    with ThreadPoolExecutor(max_workers=len(selected), thread_name_prefix='run-discovery') as pool:
        results = tuple(result for group in pool.map(execute, selected) for result in group)
    return IntegratedDiscovery(tuple(record for result in results for record in result.records),
        results, discovery_status(results, cancel.is_set()))


RUN_COMPLETION_PROVIDERS = ('pubmed', 'openalex', 'europe_pmc', 'crossref', 'arxiv', 'biorxiv', 'medrxiv')


class _WorkQueue:
    """Operation-local bounded batches; the producer callback never performs I/O."""
    def __init__(self, client, cancel, guard, progress_callback):
        self.client, self.cancel, self.guard, self.progress = client, cancel, guard, progress_callback
        self.condition = Condition()
        self.pending, self.seen, self.finished = [], set(), False
        self.responses, self.problems = {}, []

    def submit(self, records):
        values = {value for record in records if record.provenance.provider != 'openalex'
            for namespace, value in strong_identifiers(record.external_ids) if namespace == 'doi'}
        with self.condition:
            for value in sorted(values - self.seen):
                self.seen.add(value)
                self.pending.append(value)
            self.condition.notify_all()

    def finish(self):
        with self.condition:
            self.finished = True
            self.condition.notify_all()

    def run(self):
        from allfold.application.metadata_completion import _batch_lookup
        while True:
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.finished or self.cancel.is_set(), timeout=.1)
                if self.cancel.is_set() or not self.pending and self.finished:
                    return
                if not self.pending:
                    continue
                # Briefly coalesce page/native callbacks without waiting for any
                # producer to finish. Network/cache work happens outside this lock.
                if len(self.pending) < 50 and not self.finished:
                    self.condition.wait(timeout=.025)
                batch, self.pending = self.pending[:50], self.pending[50:]
            if self.cancel.is_set():
                return
            self.guard()
            if self.progress:
                self.progress(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                    operation='work-location', label='OpenAlex Work location', source='openalex_work',
                    current=len(self.responses), unit='work')))
            # lookup_many reuses the adapter's full/in-flight cache and returns
            # explicit requested-DOI bindings for different top-level identities.
            cached = _batch_lookup(self.client,'openalex','doi',batch,None,self.cancel)
            self.responses.update(cached)
            self.problems.extend(f'OpenAlex Work location: {type(value).__name__}'
                for value in cached.values() if isinstance(value,Exception))


def _pubmed_identity_targets(prepared, ordinary_roots):
    targets = {}
    for index, records in prepared.items():
        formal_ids = {identity for record in formal_records(records, ordinary_roots[index])
            for identity in strong_identifiers(record.external_ids)}
        dois = {value for namespace, value in formal_ids if namespace == 'doi'}
        if len(dois) == 1 and not any(namespace == 'pmid' for namespace, _ in formal_ids):
            doi, = dois
            targets[doi] = index
    return targets


def _bind_pubmed_identities(prepared, doi_targets, matches, groups, saved_index):
    enriched, resolutions = dict(prepared), {}
    owners = {}
    for index, group in enumerate(groups):
        for record in group.evidence:
            for identity in evidence_identifiers(record):
                owners.setdefault(identity, set()).add(index)
    for doi, index in doi_targets.items():
        match = matches.get(doi, ())
        if match and not isinstance(match, Exception):
            for identity in evidence_identifiers(match[0]):
                owners.setdefault(identity, set()).add(index)
    for doi, index in doi_targets.items():
        if doi not in matches:
            continue
        match = matches[doi]
        if match and not isinstance(match, Exception):
            record, = match
            identities = evidence_identifiers(record)
            saved_dois = {value for identity in identities if (saved := saved_index.by_identifier.get(identity))
                for namespace, value in saved.identifiers if namespace == 'doi'}
            preprint_pmid = any(ref.provider in {'pubmed', 'pmid'} and ref.relation == 'preprint'
                and ref.record_id == record.external_ids.pmid for source in prepared[index] for ref in source.related_ids)
            if any(owners[identity] != {index} for identity in identities):
                match = IdentityMismatch('Direct PubMed identity overlaps another discovery candidate')
            elif saved_dois - {doi}:
                match = IdentityMismatch('Direct PubMed identity overlaps a saved Paper with a different DOI')
            elif preprint_pmid:
                match = IdentityMismatch('Direct PubMed identity conflicts with a known preprint relation')
            else:
                record = record.model_copy(update={'provenance': record.provenance.model_copy(update={'role': 'supplement'})})
                enriched[index] = (*prepared[index], record)
        resolutions[index] = doi, match
    return enriched, resolutions


def run_integrated(config_path, *, loaded_config=None, workspace_snapshot=None, cancel_event=None,
                   progress_callback=None, client_factory=DiscoveryClient, completion_factory=None,
                   wos_stage=None, workflow_id=None):
    from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
    from allfold.application.monitor import RunResult, RunOutcome, MonitorIssue, MonitorIssueSeverity, MonitorIssueComponent
    from allfold.application.run_state import RunProvider, RunFacts, RunIssueFact, LastRunSnapshot, RecordedRunOutcome, INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshotWriteError, write_last_run_snapshot
    from allfold.application.metadata_completion import (
        CompletionSettlement, bind_records, complete_metadata_many, completion_client, prime_record_cache,
    )
    from allfold.canonicalize import canonicalize_records, consolidate_evidence, completion_metadata
    from allfold.persistence.materialize import materialize_papers, read_workspace_identities
    from allfold.persistence.safe_write import ContentChangedError
    cancel = cancel_event or Event()
    completion_factory = completion_factory or completion_client
    if progress_callback:
        progress_callback(ProgressEvent(stage=ProgressStage.CHECKING_MONITOR))
    with ExitStack() as stack:
        snapshot = workspace_snapshot or stack.enter_context(capture_run_workspace(config_path,loaded_config))
        config = snapshot.config
        validate_selection(config)
        dates = resolve_runtime_date(config,today=date.today())
        pacing, clients, request_cache = {}, {}, {}
        guard_errors, guard_lock = [], Lock()
        def guard():
            native_owner = getattr(wos_stage, '__self__', None)
            if native_owner is not None and hasattr(native_owner, 'check_dispatch_authority'):
                native_owner.check_dispatch_authority(cancel)
            try:
                with commit_run_workspace(snapshot,cancel_event=cancel):
                    pass
            except ContentChangedError as error:
                with guard_lock:
                    if not cancel.is_set():
                        guard_errors.append(error)
                    cancel.set()  # Revocation is global, even when an adapter catches its exception.
                raise
        class UnavailableClient:
            def __init__(self, provider, message): self.provider,self.message=provider,message
            def discover_many(self, scopes, *args, **kwargs):
                return tuple(DiscoveryResult(self.provider, source, 'failed', limitations=(self.message,)) for source in scopes)
            def lookup_many(self, namespace, ids, **kwargs):
                raise ValueError(self.message)
            def lookup(self, *args): raise ValueError(self.message)
            def resolve_pubmed_dois(self, identifiers):
                return dict.fromkeys(identifiers, DiscoveryError(self.message))
        # Fixed completion helpers are independent of the selected Discovery sources.
        for provider in RUN_COMPLETION_PROVIDERS:
            try:
                key = read_credential(config_path,provider=provider)[0] if provider in DISCOVERY_PROVIDERS else None
                kwargs = dict(api_key=key,cancel_event=cancel,pacing_state=pacing,progress_callback=progress_callback)
                factory = client_factory if provider in config.enabled_providers else completion_factory
                if factory is completion_factory:
                    kwargs['mailto'] = config.crossref_mailto
                client = factory(provider,**kwargs)
                client.request_guard = guard
                clients[provider] = stack.enter_context(client)
            except (ValueError,OSError) as error:
                clients[provider] = UnavailableClient(provider,str(error))
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.DISCOVERING_PAPERS))
        work = _WorkQueue(clients['openalex'],cancel,guard,progress_callback)
        def native():
            if cancel.is_set():
                return IntegratedDiscovery((),(), 'cancelled')
            try:
                if wos_stage is None:
                    raise ValueError('WoS browser stage is unavailable')
                result = wos_stage(snapshot,cancel_event=cancel,workflow_id=workflow_id,
                    progress_callback=progress_callback,records_callback=work.submit)
                work.submit(result.records)
                return result
            except Exception as error:
                source=SourceScope('journal','Web of Science')
                return IntegratedDiscovery((),(DiscoveryResult('wos',source,'cancelled' if cancel.is_set() else 'failed',
                    limitations=(str(error),)),),'cancelled' if cancel.is_set() else 'failed')
        with ThreadPoolExecutor(max_workers=3,thread_name_prefix='integrated-run') as pool:
            locating = pool.submit(work.run)
            browser_future = pool.submit(native) if 'wos' in config.enabled_providers else None
            try:
                api = discover_selected(config,config_path,clients=clients,cancel_event=cancel,
                    progress_callback=progress_callback,records_callback=work.submit)
                browser = browser_future.result() if browser_future else IntegratedDiscovery((),(), 'empty')
            finally:
                work.finish()
            try:
                locating.result()
            except ContentChangedError:
                # All producers, including the native Future and Browser owner,
                # have settled above. A cancelled Work guard is a parent outcome;
                # genuine ownership invalidation remains latched in guard_errors.
                if not cancel.is_set():
                    raise
        if guard_errors:
            raise guard_errors[0]
        discovery = IntegratedDiscovery((*browser.records,*api.records),(*browser.providers,*api.providers),
            discovery_status((*browser.providers,*api.providers),cancel.is_set()),browser.details,browser.journals,browser.statistics)
        if work.problems and discovery.status in {'complete','empty'}:
            discovery = replace(discovery,status='partial')
        # Work lookup may add direct Work identities to a discovered formal
        # DOI. Association-only anchors retain their related Work separately.
        all_work=tuple(record for value in work.responses.values() if not isinstance(value,Exception) for record in value)
        located_formal=[]
        for group in consolidate_evidence(discovery.records).clusters:
            keys={key for record in group.evidence for key in strong_identifiers(record.external_ids)}
            located_formal.extend(record.model_copy(update={'provenance':record.provenance.model_copy(update={'role':'supplement'})})
                for record in formal_records(all_work,keys))
        consolidated = consolidate_evidence((*discovery.records,*located_formal))
        groups = consolidated.clusters
        issues=[MonitorIssue(MonitorIssueSeverity.ERROR if r.status=='failed' else MonitorIssueSeverity.WARNING,
            MonitorIssueComponent.DISCOVERY,'discovery',f'{r.provider} / {r.source.name}: {message}')
            for r in discovery.providers for message in r.limitations]
        issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,item.stage,item.message)
            for item in consolidated.issues)
        issues.extend(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.DISCOVERY,'work_location',message)
            for message in dict.fromkeys(work.problems))
        created=existing=conflicts=0
        provider_totals=None
        completion_status='empty'
        phase_statistics=dict(completion_targets=0,completion_requests=0,completion_date_facts_added=0,
            first_public_recorded=0,work_location_targets=len(work.seen))
        def result():
            warnings=tuple(i for i in issues if i.severity is MonitorIssueSeverity.WARNING)
            errors=tuple(i for i in issues if i.severity is MonitorIssueSeverity.ERROR)
            outcome=(RunOutcome.CANCELLED if cancel.is_set() else RunOutcome.FAILED if discovery.status=='failed' else
                RunOutcome.COMPLETED_WITH_ERRORS if errors else RunOutcome.COMPLETED_WITH_WARNINGS
                if warnings or discovery.status=='partial' or completion_status in {'partial','failed'} else RunOutcome.COMPLETED)
            facts=RunFacts(finished_at=datetime.now(timezone.utc),created_papers=created,existing_papers=existing,
                statistics={**discovery.statistics,**phase_statistics,'integrated_candidates':sum(r.candidates for r in discovery.providers),
                    'integrated_deduplicated':len(groups),'conflicts':discovery.statistics.get('conflicts',0)+conflicts},
                journals=discovery.journals,issues=tuple(RunIssueFact(category=i.stage,message=i.message,severity=i.severity.value) for i in issues),
                details={**discovery.details,**({'provider_totals':provider_totals} if provider_totals is not None else {}),
                    'discovery_status':'cancelled' if cancel.is_set() else discovery.status,
                    'completion_status':'cancelled' if cancel.is_set() else completion_status,
                    'provider_runs':[r.fact() for r in discovery.providers]})
            return RunResult(provider=RunProvider.INTEGRATED,resolved_date_range=dates,
                warnings=warnings,errors=errors,outcome=outcome,facts=facts)
        if cancel.is_set():
            return result()
        # Classify the complete saved index, including Rejected, before helper requests.
        with commit_run_workspace(snapshot,cancel_event=cancel) as lock:
            current=read_workspace_identities(lock)
            targets={index:group.evidence for index,group in enumerate(groups)
                if current.complete and not (keys:={key for record in group.evidence for key in evidence_identifiers(record)}) & current.blocked_identifiers
                and not any(key in current.by_identifier for key in keys)}
        phase_statistics['completion_targets']=len(targets)
        completed_papers={}
        completed_keys={}
        if targets:
            if progress_callback:
                progress_callback(ProgressEvent(stage=ProgressStage.COMPLETING_PAPERS))
            prime_record_cache(tuple(record for record in discovery.records if record.provenance.provider=='pubmed'),
                request_cache=request_cache,capability='fetch')
            prime_record_cache(tuple(record for record in discovery.records if record.provenance.provider=='openalex'),request_cache=request_cache)
            for doi,value in work.responses.items():
                request_cache['openalex','doi',doi]=value
            prepared={}
            ordinary_roots={}
            for index,records in targets.items():
                keys={key for record in records for key in strong_identifiers(record.external_ids)}
                ordinary_roots[index]=keys
                associated,_=bind_records((*records,*all_work),keys)
                prepared[index]=tuple(associated)
            before_requests=sum(getattr(client,'request_count',0) for client in clients.values())
            pubmed = clients['pubmed']
            doi_targets = _pubmed_identity_targets(prepared, ordinary_roots)
            settlement = CompletionSettlement()
            matches = {}
            if doi_targets and hasattr(pubmed, 'resolve_pubmed_dois'):
                if hasattr(pubmed, 'begin_completion'):
                    pubmed.begin_completion()
                def lookup():
                    try:
                        return pubmed.resolve_pubmed_dois(sorted(doi_targets))
                    except ContentChangedError:
                        if guard_errors or not cancel.is_set():
                            raise
                        return {}

                matches.update(settlement.capture(pubmed, lookup, matches.update))

            def prepare_completion():
                enriched, resolutions = _bind_pubmed_identities(prepared, doi_targets, matches, groups, current)
                for index, (_, outcome) in resolutions.items():
                    if outcome and not isinstance(outcome, Exception):
                        keys = ordinary_roots[index] | set(evidence_identifiers(outcome[0]))
                        if keys & (current.by_identifier.keys() | current.blocked_identifiers):
                            completed_keys[index] = keys
                            enriched.pop(index)
                return enriched, resolutions

            def complete(enriched, settlement=None):
                return tuple(complete_metadata_many(enriched, RUN_COMPLETION_PROVIDERS, clients=clients,
                    cancel_event=cancel, request_cache=request_cache, paper_guard=lambda _: guard(),
                    ordinary_root_ids=ordinary_roots, settlement=settlement))

            enriched, resolutions = prepare_completion()
            completions = complete(enriched, settlement)
            if settlement.settle(cancel):
                enriched, resolutions = prepare_completion()
                completions = complete(enriched)

            for doi, outcome in resolutions.values():
                status = ('cancelled' if isinstance(outcome, Cancelled) else
                    'conflicts' if isinstance(outcome, IdentityMismatch) else
                    'failed' if isinstance(outcome, Exception) else 'matched' if outcome else 'no_match')
                key = 'pmid_resolution_' + status
                phase_statistics[key] = phase_statistics.get(key, 0) + 1
                if status in {'conflicts', 'failed'}:
                    issues.append(MonitorIssue(MonitorIssueSeverity.WARNING, MonitorIssueComponent.CANONICALIZATION,
                        'pmid_resolution', f'PubMed DOI {doi}: {outcome}'))
            statuses=['partial'] if any(issue.stage == 'pmid_resolution' for issue in issues) else []
            from allfold.paper_dates import collect_dates
            for index,completed in completions:
                if isinstance(completed,Exception):
                    statuses.append('failed')
                    issues.append(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.CANONICALIZATION,
                        'completion',f'API Completion: {type(completed).__name__}'))
                    records=enriched[index]
                else:
                    statuses.append(completed.status)
                    first_public_key = 'first_public_' + completed.first_public_status
                    if completed.first_public_status in {'no_association','known_unresolved','conflict','failed','cancelled'}:
                        phase_statistics[first_public_key] = phase_statistics.get(first_public_key,0)+1
                    records=completed.records
                    issues.extend(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.CANONICALIZATION,
                        'completion',f'{issue.provider}: {issue.message}') for issue in completed.issues)
                root_keys=ordinary_roots[index]
                formal=formal_records(records,root_keys)
                completed_keys[index]={key for record in formal for key in evidence_identifiers(record)}
                canonical=canonicalize_records(formal)
                issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,
                    item.stage,item.message) for item in canonical.issues)
                if len(canonical.papers)!=1:
                    continue
                base=canonical.papers[0]
                folded=completion_metadata(records)
                completed_papers[index]=base.model_copy(update={'date_evidence':folded.date_evidence,
                    'sources':folded.sources,'metadata':base.metadata.model_copy(update={'first_public_at':folded.metadata.first_public_at})})
                phase_statistics['completion_date_facts_added']+=len(set(folded.date_evidence)-set(collect_dates(prepared[index])))
                phase_statistics['first_public_recorded']+=bool(folded.metadata.first_public_at)
            phase_statistics['completion_requests']=sum(getattr(client,'request_count',0) for client in clients.values())-before_requests
            completion_status=('cancelled' if cancel.is_set() else 'partial' if any(status in {'failed','partial'} for status in statuses)
                else 'complete')
        if guard_errors:
            raise guard_errors[0]
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
                for index, group in enumerate(groups):
                    keys=completed_keys.get(index,{key for record in group.evidence for key in evidence_identifiers(record)})
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
                    eligible.append((group, keys))
                    if not owners:
                        if index in completed_papers:
                            incoming.append(completed_papers[index])
                saved=materialize_papers(incoming,config.output_dir,operation_lock=lock,cancel_event=cancel,progress_callback=progress_callback)
                created=len(saved.created_papers)
                issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.MATERIALIZATION,'write',i.message) for i in saved.issues)
                identities=read_workspace_identities(lock)
                matched_owners=set()
                matched_record_ids=set()
                for group, keys in eligible:
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
