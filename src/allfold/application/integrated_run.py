"""Foreground Discovery/identity closure and atomic Workspace collection handoff."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timezone
from threading import Event, Condition, Lock

from allfold.config import ConfigurationError, resolve_runtime_date, validate_runtime_keyword
from allfold.integrations.openalex_credentials import read_credential
from allfold.progress import ProgressEvent, ProgressStage, ActivityUpdate, ActivityKind
from allfold.application.provider_lookup import formal_records
from allfold.application.necessary_metadata import confirm_formal_dois
from allfold.identifiers import evidence_identifiers, related_identifiers, strong_identifiers
from allfold.models import ExternalIds
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


RUN_IDENTITY_PROVIDERS = ('pubmed', 'openalex')


class _WorkQueue:
    """Operation-local bounded batches; the producer callback never performs I/O."""
    def __init__(self, client, cancel, guard, progress_callback, eligible_records=lambda rows: rows, eligible_dois=lambda values: values):
        self.client, self.cancel, self.guard, self.progress = client, cancel, guard, progress_callback
        self.eligible_records, self.eligible_dois = eligible_records, eligible_dois
        self.condition = Condition()
        self.pending, self.seen, self.finished = [], set(), False
        self.responses, self.problems = {}, []

    def submit(self, records):
        values = {value for record in self.eligible_records(records) if record.provenance.provider != 'openalex'
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
        from allfold.application.provider_lookup import _batch_lookup
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
            batch = self.eligible_dois(batch)
            if not batch:
                continue
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
                for namespace, value in ((item.namespace, item.value) for item in saved.identities) if namespace == 'doi'}
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
                   progress_callback=None, client_factory=DiscoveryClient, lookup_factory=None,
                   wos_stage=None, workflow_id=None, recovery_observer=None, pacing_state=None,
                   workspace_tasks=None, collection_service=None):
    from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
    from allfold.application.monitor import RunResult, RunOutcome, MonitorIssue, MonitorIssueSeverity, MonitorIssueComponent
    from allfold.application.run_state import RunProvider, RunFacts, RunIssueFact, LastRunSnapshot, RecordedRunOutcome, INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshotWriteError, write_last_run_snapshot
    from allfold.application.provider_lookup import (
        LookupSettlement, bind_records, provider_client,
    )
    from allfold.canonicalize import canonicalize_records, consolidate_evidence, completion_metadata
    from allfold.persistence.paper_repository import PaperRepository, DirectIdentity, IdentityConflict, LibraryError
    from allfold.persistence.run_library import RunIdentityIndex
    from allfold.persistence.safe_write import ContentChangedError
    cancel = cancel_event or Event()
    lookup_factory = lookup_factory or provider_client
    if progress_callback:
        progress_callback(ProgressEvent(stage=ProgressStage.CHECKING_MONITOR))
    with ExitStack() as stack:
        snapshot = workspace_snapshot or stack.enter_context(capture_run_workspace(config_path,loaded_config))
        config = snapshot.config
        validate_selection(config)
        dates = resolve_runtime_date(config,today=date.today())
        pacing = pacing_state if pacing_state is not None else {}
        clients = {}
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
        # Necessary identity helpers are independent of selected Discovery sources.
        for provider in RUN_IDENTITY_PROVIDERS:
            try:
                key = read_credential(config_path,provider=provider)[0] if provider in DISCOVERY_PROVIDERS else None
                kwargs = dict(api_key=key,cancel_event=cancel,pacing_state=pacing,progress_callback=progress_callback)
                factory = client_factory if provider in config.enabled_providers else lookup_factory
                if factory is lookup_factory:
                    kwargs['mailto'] = config.crossref_mailto
                client = factory(provider,**kwargs)
                client.request_guard = guard
                if isinstance(client, DiscoveryClient) and recovery_observer is not None:
                    client.recovery_observer = recovery_observer
                clients[provider] = stack.enter_context(client)
            except (ValueError,OSError) as error:
                clients[provider] = UnavailableClient(provider,str(error))
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.DISCOVERING_PAPERS))
        def eligible_records(records):
            records = tuple(records)
            # Keep the verified producer handoff even when authority is revoked;
            # the parent waits for all producers and reports its latched outcome.
            try:
                guard()
                with commit_run_workspace(snapshot, cancel_event=cancel):
                    with PaperRepository.open(config.output_dir, expected_workspace_id=snapshot.workspace_id) as repository:
                        keys = {key for record in records for key in evidence_identifiers(record)}
                        index = RunIdentityIndex.read(repository, keys)
                        return tuple(record for record in records if index.target(
                            evidence_identifiers(record), snapshot.initial_papers))
            except ContentChangedError as error:
                with guard_lock:
                    if not cancel.is_set():
                        guard_errors.append(error)
                    cancel.set()
                return ()
        def eligible_dois(values):
            values = tuple(values)
            guard()
            with commit_run_workspace(snapshot, cancel_event=cancel):
                with PaperRepository.open(config.output_dir, expected_workspace_id=snapshot.workspace_id) as repository:
                    index = RunIdentityIndex.read(repository, {('doi', doi) for doi in values})
                    return [doi for doi in values if index.target({('doi', doi)}, snapshot.initial_papers)]
        work = _WorkQueue(clients['openalex'],cancel,guard,progress_callback,eligible_records,eligible_dois)
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
        # A WoS PM on a DOI-bearing article is a reported identifier. PubMed
        # must confirm the pair before the PMID can merge, enrich or own a Paper.
        normalized, reported_pmids = {}, {}
        for record in discovery.records:
            ids = record.external_ids.model_dump(exclude_none=True)
            if record.provenance.provider == 'wos' and ids.get('doi') and (pmid := ids.pop('pmid', None)):
                clean = record.model_copy(update={'external_ids': ExternalIds(**ids)})
                normalized[id(record)] = clean
                reported_pmids[id(clean)] = ('pmid', pmid)
        if normalized:
            discovery = replace(discovery,
                records=tuple(normalized.get(id(record), record) for record in discovery.records),
                providers=tuple(replace(run, records=tuple(normalized.get(id(record), record)
                    for record in run.records)) for run in discovery.providers))
        if work.problems and discovery.status in {'complete','empty'}:
            discovery = replace(discovery,status='partial')
        # Work lookup may add direct Work identities to a discovered formal
        # DOI. Association-only anchors retain their related Work separately.
        all_work=tuple(record for value in work.responses.values()
            for record in (getattr(value, 'records', ()) if isinstance(value, Exception) else value))
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
        created=existing=conflicts=rebuilt=excluded=0
        paper_ids=[]
        provider_totals=None
        phase_statistics=dict(identity_targets=0, identity_requests=0, work_location_targets=len(work.seen),
            collection_admitted=0, collection_reused=0, collection_registration_failed=0)
        def result():
            warnings=tuple(i for i in issues if i.severity is MonitorIssueSeverity.WARNING)
            errors=tuple(i for i in issues if i.severity is MonitorIssueSeverity.ERROR)
            outcome=(RunOutcome.CANCELLED if cancel.is_set() else RunOutcome.FAILED if discovery.status=='failed' else
                RunOutcome.COMPLETED_WITH_ERRORS if errors else RunOutcome.COMPLETED_WITH_WARNINGS
                if warnings or discovery.status=='partial' else RunOutcome.COMPLETED)
            facts=RunFacts(finished_at=datetime.now(timezone.utc),created_papers=created,existing_papers=existing,
                statistics={**discovery.statistics,**phase_statistics,'integrated_candidates':sum(r.candidates for r in discovery.providers),
                    'integrated_deduplicated':len(groups),'rebuilt_papers':rebuilt,'excluded_papers':excluded,
                    'conflicts':discovery.statistics.get('conflicts',0)+conflicts},
                journals=discovery.journals,issues=tuple(RunIssueFact(category=i.stage,message=i.message,severity=i.severity.value) for i in issues),
                details={**discovery.details,**({'provider_totals':provider_totals} if provider_totals is not None else {}),
                    'discovery_status':'cancelled' if cancel.is_set() else discovery.status,
                    'paper_ids':list(paper_ids),'provider_runs':[r.fact() for r in discovery.providers]})
            return RunResult(provider=RunProvider.INTEGRATED,resolved_date_range=dates,
                warnings=warnings,errors=errors,outcome=outcome,facts=facts)
        if cancel.is_set():
            return result()
        # The unknown-only test suppresses helper queries; it never excludes a
        # complete saved not_started Paper from first collection admission.
        with commit_run_workspace(snapshot,cancel_event=cancel):
            with PaperRepository.open(config.output_dir, expected_workspace_id=snapshot.workspace_id) as repository:
                current = RunIdentityIndex.read(repository)
                targets = {index: group.evidence for index, group in enumerate(groups)
                    if current.target({key for record in group.evidence for key in evidence_identifiers(record)},
                        snapshot.initial_papers)}
        phase_statistics['identity_targets']=len(targets)
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.RESOLVING_IDENTITIES))
        ordinary_roots = {index: {key for record in group.evidence for key in strong_identifiers(record.external_ids)}
            for index, group in enumerate(groups)}
        prepared = {index: tuple(bind_records((*group.evidence, *all_work), ordinary_roots[index])[0])
            for index, group in enumerate(groups)}
        before_requests=sum(getattr(client,'request_count',0) for client in clients.values())
        pubmed = clients['pubmed']
        doi_targets = _pubmed_identity_targets({index: prepared[index] for index in targets}, ordinary_roots)
        settlement = LookupSettlement()
        matches = {}
        if doi_targets and hasattr(pubmed, 'resolve_pubmed_dois'):
            if hasattr(pubmed, 'begin_completion'):
                pubmed.begin_completion()
            def lookup():
                try:
                    return confirm_formal_dois(pubmed, sorted(doi_targets), guard=guard)
                except ContentChangedError:
                    if guard_errors or not cancel.is_set():
                        raise
                    return {}
            matches.update(settlement.capture(pubmed, lookup, matches.update))
            settlement.settle(cancel)
        prepared, resolutions = _bind_pubmed_identities(prepared, doi_targets, matches, groups, current)
        for doi, outcome in resolutions.values():
            status = ('cancelled' if isinstance(outcome, Cancelled) else
                'conflicts' if isinstance(outcome, IdentityMismatch) else
                'failed' if isinstance(outcome, Exception) else 'matched' if outcome else 'no_match')
            key = 'pmid_resolution_' + status
            phase_statistics[key] = phase_statistics.get(key, 0) + 1
            if status == 'cancelled':
                cancel.set()
            if status in {'conflicts', 'failed'}:
                issues.append(MonitorIssue(MonitorIssueSeverity.WARNING, MonitorIssueComponent.CANONICALIZATION,
                    'pmid_resolution', f'PubMed DOI {doi}: {outcome}'))
        phase_statistics['identity_requests']=sum(getattr(client,'request_count',0) for client in clients.values())-before_requests
        from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse
        # Only a verified complete capability can suppress a later request.
        # Discovery records alone carry no completeness promise.
        verified = []
        for records in prepared.values():
            for record in records:
                if record.provenance.provider == 'pubmed' and record.external_ids.model_dump().get('pmid') and hasattr(pubmed, 'cached_lookup'):
                    for capability in ('fetch', 'summary'):
                        value = pubmed.cached_lookup('pmid', record.external_ids.model_dump()['pmid'], capability)
                        if value is not None:
                            rows = tuple(getattr(value, 'records', ())) if isinstance(value, Exception) else tuple(value)
                            if rows or not isinstance(value, Exception):
                                verified.append(VerifiedResponse(NecessaryRequest('pubmed', 'pmid',
                                    record.external_ids.model_dump()['pmid'], capability), rows, complete=not isinstance(value, Exception)))
        for doi, value in work.responses.items():
            rows = tuple(getattr(value, 'records', ())) if isinstance(value, Exception) else tuple(value)
            if rows or not isinstance(value, Exception):
                verified.append(VerifiedResponse(NecessaryRequest('openalex', 'doi', doi, 'work'), rows,
                    complete=not isinstance(value, Exception)))
                if not isinstance(value, Exception):
                    for record in rows:
                        for namespace, identifier in strong_identifiers(record.external_ids):
                            if namespace == 'openalex':
                                verified.append(VerifiedResponse(NecessaryRequest('openalex', namespace, identifier, 'work'),
                                    tuple(row for row in rows if (namespace, identifier) in strong_identifiers(row.external_ids))))
        if guard_errors:
            raise guard_errors[0]
        if cancel.is_set():
            return result()
        if progress_callback:
            progress_callback(ProgressEvent(stage=ProgressStage.UPDATING_WORKSPACE))
        from allfold.application.collection_runtime import TaskHandle
        from allfold.application.collection_planner import ProductionCollectionService
        if workspace_tasks is None:
            raise ValueError('Production Run requires its application Workspace task host')
        registry = workspace_tasks.current()
        if registry.workspace_id != snapshot.workspace_id:
            raise ContentChangedError('Run collection host belongs to another Workspace')
        planner = collection_service or ProductionCollectionService(workspace_tasks)
        matched_record_owners={}
        created_ids=set()
        for index, group in enumerate(groups):
            if cancel.is_set():
                break
            records = prepared[index]
            root_keys = ordinary_roots[index]
            formal = formal_records(records, root_keys)
            if not formal:  # A direct native preprint remains its own Paper.
                formal = tuple(record for record in group.evidence if strong_identifiers(record.external_ids) & root_keys)
            keys = {key for record in formal for key in evidence_identifiers(record)}
            try:
                with commit_run_workspace(snapshot,cancel_event=cancel):
                    with PaperRepository.open(config.output_dir, expected_workspace_id=snapshot.workspace_id) as repository:
                        unverified = {reported_pmids[id(record)] for record in group.evidence if id(record) in reported_pmids}
                        current = RunIdentityIndex.read(repository, keys | unverified)
                        owners = current.owners(keys)
                        if len(owners) > 1:
                            raise IdentityConflict(f'Direct identifiers belong to different Papers: {sorted(map(str, owners))}')
                        owner = repository.get(next(iter(owners))) if owners else None
                        if owner is not None and owner.excluded:
                            excluded += 1
                            continue
                        if not owners and not any(namespace == 'pmid' for namespace, _ in keys):
                            if any((saved := current.by_identifier.get(key)) and
                                    not any(item.namespace == 'doi' for item in saved.identities) for key in unverified):
                                raise IdentityConflict(f'Unconfirmed WoS PMID overlaps a saved Paper: {sorted(unverified)}')
                        canonical = canonicalize_records(formal)
                        issues.extend(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,
                            item.stage,item.message) for item in canonical.issues)
                        if len(canonical.papers) != 1:
                            continue
                        base = canonical.papers[0]
                        bound_facts = tuple(fact for fact in verified if (fact.request.namespace, fact.request.identifier)
                            in {key for record in records for key in related_identifiers(record)})
                        # Retain native proof now, but defer a newly computed final
                        # value until all relation/reverse/native purposes finish.
                        folded = completion_metadata(records)
                        base = base.model_copy(update={'date_evidence':folded.date_evidence,
                            'sources':folded.sources,'metadata':base.metadata.model_copy(update={
                                'first_public_at':folded.metadata.first_public_at})})
                        metadata = planner.base_metadata(base, identities=keys, records=records, facts=bound_facts)
                        branches = planner.plan(paper=owner if owner and owner.metadata else None,
                            metadata=metadata, identities=keys, records=records, facts=bound_facts, config=config)
                        initial = snapshot.initial_papers.get(owner.id) if owner else None
                    # Base, extra direct IDs, complete plan and original owner are
                    # published together. No access capture runs in this boundary.
                    admitted = registry.admit(direct_ids=base.external_ids,
                        additional_identities=tuple(DirectIdentity(*key) for key in keys), metadata=metadata,
                        branches=branches, source_run_id=workflow_id,
                        expected_token=initial.token if initial is not None else None,
                        allow_rebuild=bool(initial is not None and initial.metadata is None and not initial.excluded))
                paper_id = admitted.paper_id if isinstance(admitted, TaskHandle) else admitted.id
                if owner is None:
                    created_ids.add(paper_id)
                elif owner.metadata is None:
                    rebuilt += 1
                matched_record_owners.update((id(record), paper_id) for record in group.evidence)
                if isinstance(admitted, TaskHandle):
                    fresh = owner is None or owner.collection is None
                    phase_statistics['collection_admitted' if fresh else 'collection_reused'] += 1
                    registry.register(admitted)  # Independent lifetime; never await its Future here.
                    if fresh and admitted.future.done() and admitted.scheduled is None:
                        phase_statistics['collection_registration_failed'] += 1
                        issues.append(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.MATERIALIZATION,
                            'collection_registration','Paper collection could not be registered'))
                else:
                    phase_statistics['collection_reused'] += 1
            except ContentChangedError:
                if cancel.is_set():
                    break
                raise
            except (LibraryError, ValueError) as error:
                conflicts += 1
                issues.append(MonitorIssue(MonitorIssueSeverity.ERROR,MonitorIssueComponent.CANONICALIZATION,
                    'identity',str(error)))
        created=len(created_ids)
        existing=len(set(matched_record_owners.values())-created_ids)
        paper_ids[:]=sorted(map(str, set(matched_record_owners.values())))
        updated_runs=[]
        for run in discovery.providers:
            owners={matched_record_owners[id(record)] for record in run.records if id(record) in matched_record_owners}
            updated_runs.append(replace(run,created=len(owners & created_ids),existing=len(owners-created_ids)))
        discovery=replace(discovery,providers=tuple(updated_runs))
        provider_totals=[]
        for provider in RUN_PROVIDERS:
            runs=[run for run in discovery.providers if run.provider==provider]
            if not runs: continue
            owners={matched_record_owners[id(record)] for run in runs for record in run.records if id(record) in matched_record_owners}
            provider_totals.append(dict(provider=provider,status=discovery_status(runs,cancel.is_set()),
                candidates=sum(run.candidates for run in runs),created=len(owners & created_ids),existing=len(owners-created_ids),
                limitations=list(dict.fromkeys(message for run in runs for message in run.limitations))))
        final=result()
        if not cancel.is_set():
            try:
                with commit_run_workspace(snapshot,cancel_event=cancel) as lock:
                    write_last_run_snapshot(config.output_dir,LastRunSnapshot(schema_version=INTEGRATED_RUN_SCHEMA_VERSION,resolved_date_range=dates,
                        outcome=RecordedRunOutcome(final.outcome.value),provider=RunProvider.INTEGRATED,facts=final.facts),operation_lock=lock)
            except LastRunSnapshotWriteError as error:
                issues.append(MonitorIssue(MonitorIssueSeverity.WARNING,MonitorIssueComponent.SNAPSHOT,
                    'snapshot_write',f'Latest Run result could not be saved: {error}'))
                final=result()
            except ContentChangedError:
                if not cancel.is_set():
                    raise
                final=result()
        return final
