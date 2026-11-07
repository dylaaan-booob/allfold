"""Target-directed completion from saved Paper fields, independent of discovery."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from allfold.identifiers import strong_identifiers, related_identifiers
from allfold.models import ExternalIds, ProviderRecordRef, ProviderWorkEvidence

LOOKUP_NAMESPACES = {
    'openalex': ('openalex', 'doi'), 'crossref': ('doi',),
}


class MetadataLookup(Protocol):
    def lookup(self, namespace: str, identifier: str) -> tuple[ProviderWorkEvidence, ...]: ...


@dataclass(frozen=True)
class CompletionIssue:
    provider: str
    identifier: str
    message: str
    status: str = 'failed'


@dataclass(frozen=True)
class CompletionLookup:
    provider: str
    namespace: str
    identifier: str
    status: str
    capability: str | None = None


def _lookup(request, status):
    return CompletionLookup(*request[:3], status, request[3] if len(request) > 3 else None)


@dataclass(frozen=True)
class CompletionResult:
    records: tuple[ProviderWorkEvidence, ...]
    issues: tuple[CompletionIssue, ...]
    lookups: tuple[CompletionLookup, ...] = ()
    cancelled: bool = False
    first_public_status: str = 'no_association'
    status: str = 'complete'


def _identities(record):
    return set(related_identifiers(record))


def formal_records(records, root_ids):
    """Expand direct formal identities only; declared relations never own a root."""
    pending = [record for record in records if record.publication_type != 'preprint']
    accepted, keys = [], set(root_ids)
    while pending:
        matches = [record for record in pending if keys & strong_identifiers(record.external_ids)]
        if not matches:
            break
        for record in matches:
            pending.remove(record)
            accepted.append(record)
            keys.update(strong_identifiers(record.external_ids))
    return tuple(accepted)


def _ordinary_records(records, root_ids):
    return formal_records(records, root_ids) if root_ids is not None else records


def _ordinary_missing(records, root_ids=None):
    records = _ordinary_records(records, root_ids)
    formal = any(record.publication_type in {'journal', 'conference'} or
        record.publication_type != 'preprint' and (record.journal or record.conference) for record in records)
    if formal:
        records = tuple(record for record in records if record.publication_type != 'preprint')
    source_present = any(record.publication_type != 'preprint' and (record.journal or record.conference)
        for record in records) if formal else any(record.journal or record.conference or
        record.publication_type == 'preprint' for record in records)
    return (any(not any(getattr(record, field) for record in records) for field in ('title', 'abstract', 'authors'))
        or not source_present)


def _journal_dates_missing(records):
    from allfold.paper_dates import collect_dates
    from allfold.models import EvidenceDateKind
    journal = any(record.publication_type != 'preprint' and
        (record.journal or record.publication_type == 'journal') for record in records)
    required = {EvidenceDateKind.RECEIVED, EvidenceDateKind.ACCEPTED,
        EvidenceDateKind.PUBLISHED_ONLINE, EvidenceDateKind.PUBLISHED}
    present = {item.kind for item in collect_dates(records) if item.publication_type == 'journal'}
    return journal and not required.issubset(present)


def _native_targets(records, root_ids=None):
    from allfold.paper_dates import preprint_date_coverage, preprint_identity, preprint_query_refs
    _, answered = preprint_date_coverage(records)
    first_public_saved = any(record.first_public_at for record in records)
    # A related preprint cannot fill a formal root's ordinary fields. Its native
    # request is needed only for independent version proof in that case.
    ordinary = root_ids is None and _ordinary_missing(records)
    targets = set()
    for record in records:
        for ns, value in _identities(record):
            if ns == 'arxiv' and (ordinary or not first_public_saved and preprint_identity(ns, value) not in answered):
                targets.add(('arxiv', ns, value))
            if ns == 'europe_pmc' and value.startswith('PPR:') and (ordinary or not first_public_saved and preprint_identity(ns, value) not in answered):
                targets.add(('europe_pmc', ns, value))
        platforms = {(ref.provider, ref.record_id) for ref in record.related_ids if ref.provider in {'biorxiv','medrxiv'}}
        if record.provenance.provider in {'biorxiv','medrxiv'} and record.publication_type == 'preprint' and record.external_ids.doi:
            platforms.add((record.provenance.provider, record.external_ids.doi))
        platforms.update((ref.provider, ref.record_id) for ref in preprint_query_refs(record.dates)
            if ref.provider in {'biorxiv', 'medrxiv'})
        for platform, doi in platforms:
            if ordinary or not first_public_saved and preprint_identity('doi', doi) not in answered:
                targets.add((platform, 'doi', doi))
        preprint_dois = {ref.record_id for ref in record.related_ids if ref.provider == 'doi' and ref.relation == 'preprint'}
        if record.publication_type == 'preprint' and record.external_ids.doi:
            preprint_dois.add(record.external_ids.doi)
        for doi in preprint_dois:
            if (not doi.startswith('10.48550/arxiv.') and not any(value == doi for _, value in platforms)
                    and (ordinary or not first_public_saved and preprint_identity('doi', doi) not in answered)):
                targets.add(('europe_pmc', 'doi', doi))
    return sorted(targets)


def _requests(records, *, allow_formal_preprint_reverse=True, root_ids=None):
    from allfold.paper_dates import preprint_date_coverage, known_preprint_families, preprint_identity
    yield from _native_targets(records, root_ids)
    complete, answered = preprint_date_coverage(records)
    families = known_preprint_families(records)
    first_public_saved = any(record.first_public_at for record in records)
    ordinary = _ordinary_missing(records, root_ids)
    preprint_ordinary = ordinary and root_ids is None
    metadata = ordinary or _journal_dates_missing(records)
    if (complete or first_public_saved) and not metadata:
        return
    preprint_pmids = {ref.record_id for record in records for ref in record.related_ids
        if ref.provider == 'pubmed' and ref.relation == 'preprint'}
    preprint_pmids.update(value for record in records if record.publication_type == 'preprint'
        for ns, value in strong_identifiers(record.external_ids) if ns == 'pmid')
    for pmid in sorted(preprint_pmids):
        if preprint_ordinary or not first_public_saved and preprint_identity('pmid', pmid) not in answered:
            yield 'pubmed', 'pmid', pmid, 'fetch-preprint'
    formal_pmids = sorted({value for record in _ordinary_records(records, root_ids) if record.publication_type != 'preprint'
        for ns, value in strong_identifiers(record.external_ids) if ns == 'pmid'})
    for pmid in formal_pmids:
        yield 'pubmed', 'pmid', pmid, 'fetch' if ordinary else 'summary'
        if not first_public_saved:
            yield 'europe_pmc', 'pmid', pmid, 'preprints'
    # Each base API contributes independent evidence. Presence of Published
    # cannot suppress a Received, Accepted or electronic-publication target.
    for provider in ('crossref', 'openalex'):
        targets = set()
        for record in records:
            identities = _identities(record)
            primary = strong_identifiers(record.external_ids)
            for ns in LOOKUP_NAMESPACES[provider]:
                keys = {key for key in primary if key[0] == ns}
                if keys:
                    targets.update(keys)
                    break
            targets.update(key for key in identities - primary if key[0] in LOOKUP_NAMESPACES[provider])
        for ns, value in sorted(targets, key=lambda key: (preprint_identity(*key) in families, key)):
            if not preprint_ordinary and preprint_identity(ns, value) in answered:
                continue
            if provider == 'openalex' and any(record.provenance.provider == 'openalex'
                    and (ns, value) in strong_identifiers(record.external_ids) for record in records):
                continue
            yield provider, ns, value
    if not first_public_saved:
        for doi in sorted({value for record in records if record.publication_type != 'preprint'
                for ns, value in strong_identifiers(record.external_ids) if ns == 'doi'}):
            yield 'crossref', 'doi', doi, 'preprints'
    # Reverse lookup discovers associations; it never guesses a known preprint's
    # platform or enumerates other systems once a family has been established.
    if allow_formal_preprint_reverse and not first_public_saved and not families:
        formal = {value for record in records for ns, value in strong_identifiers(record.external_ids)
            if ns == 'doi' and not value.startswith(('10.1101/', '10.64898/', '10.48550/arxiv.'))}
        for provider in ('biorxiv', 'medrxiv'):
            for doi in sorted(formal):
                yield provider, 'doi', doi


def prime_record_cache(records, *, request_cache, capability=None):
    """Seed verified response capabilities from Discovery, never inferred aliases."""
    groups = {}
    for record in records:
        for namespace, identifier in strong_identifiers(record.external_ids):
            supported = {'pubmed': {'pmid'}, 'openalex': {'openalex', 'doi'}, 'crossref': {'doi'},
                'arxiv': {'arxiv'}, 'biorxiv': {'doi'}, 'medrxiv': {'doi'}, 'europe_pmc': {'europe_pmc'}}
            if namespace not in supported.get(record.provenance.provider, set()):
                continue
            key = record.provenance.provider, namespace, identifier
            if capability:
                key = (*key, capability)
            groups.setdefault(key, []).append(record)
    for key, values in groups.items():
        request_cache[key] = tuple(values)
        if len(key) == 4 and key[0] == 'pubmed' and key[3] == 'fetch':
            request_cache[(*key[:3], 'summary')] = tuple(values)


def _batch_lookup(client, provider, namespace, identifiers, capability, cancel_event):
    from allfold.providers.integrated import Cancelled, DiscoveryError
    from allfold.providers.supplemental import PartialLookup
    if cancel_event is not None and cancel_event.is_set():
        return {identifier: Cancelled('Metadata completion cancelled') for identifier in identifiers}
    try:
        if client is None:
            raise DiscoveryError('Selected metadata adapter is unavailable')
        if provider == 'crossref' and capability == 'preprints':
            result = client.lookup_preprints(identifiers)
        elif provider == 'pubmed':
            result = client.lookup_many(namespace, identifiers, capability='fetch' if capability == 'fetch-preprint' else capability)
        else:
            result = client.lookup_many(namespace, identifiers)
        if isinstance(result, dict):
            return {identifier: result.get(identifier, DiscoveryError('Incomplete metadata batch response')) for identifier in identifiers}
        output = {}
        for identifier in identifiers:
            accepted, _ = bind_records(result.records, {(namespace, identifier)})
            if provider == 'openalex' and namespace == 'doi':
                work_ids = {work for ns, requested, work in getattr(result, 'bindings', ())
                    if ns == namespace and requested == identifier}
                mapped = [record for record in result.records if
                    any(('openalex', work) in strong_identifiers(record.external_ids) for work in work_ids)]
                anchors = [ProviderWorkEvidence(provenance=record.provenance.model_copy(update={
                    'record_id': f'{record.provenance.record_id}:binding:{identifier}',
                    'note': 'Exact requested DOI matched an explicit Work location; linked Work identity remains separate'}),
                    external_ids=ExternalIds(doi=identifier), publication_type='journal',
                    related_ids=(ProviderRecordRef(provider='openalex', record_id=work),))
                    for record in mapped for work in sorted(work_ids)
                    if ('openalex', work) in strong_identifiers(record.external_ids)
                    and ('doi', identifier) not in strong_identifiers(record.external_ids)]
                accepted, _ = bind_records((*accepted, *anchors, *mapped), {(namespace, identifier)})
            if provider == 'pubmed' and hasattr(client, 'cached_lookup'):
                cached = client.cached_lookup(namespace, identifier, 'fetch' if capability == 'fetch-preprint' else capability)
                if isinstance(cached, Exception):
                    output[identifier] = cached
                    continue
                if cached is not None:
                    accepted = list(cached)
            if provider == 'pubmed' and capability == 'fetch-preprint':
                from allfold.models import EvidenceDateKind
                accepted = [record.model_copy(update={'publication_type': 'preprint', 'journal': None,
                    'dates': tuple(item.model_copy(update={'publication_type': 'preprint',
                        'kind': EvidenceDateKind.PREPRINT if item.kind in {EvidenceDateKind.PUBLISHED, EvidenceDateKind.PUBLISHED_ONLINE}
                            else item.kind, 'first_version': False}) for item in record.dates)}) for record in accepted]
            if provider == 'pubmed' and accepted:
                output[identifier] = tuple(accepted)
                continue
            if result.status in {'failed', 'partial', 'cancelled'}:
                message = '; '.join(result.limitations) or 'Incomplete metadata batch response'
                output[identifier] = (PartialLookup(message, accepted) if accepted else
                    Cancelled(message) if result.status == 'cancelled' else DiscoveryError(message))
            else:
                output[identifier] = tuple(accepted)
        return output
    except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
        return {identifier: error for identifier in identifiers}


def prime_completion_cache(record_groups, enabled_providers, *, clients, request_cache,
                           cancel_event=None, allow_formal_preprint_reverse=True, ordinary_root_ids=None):
    """Collect exact targets across Papers and run independent base API batches.

    Responses, no-match and failures are operation-local. Capability keys keep
    summary evidence from accidentally satisfying an EFetch or reverse-relation
    request. Native version targets are scheduled in later shared waves.
    """
    batches = {}
    for key, records in record_groups.items():
        root_ids = ordinary_root_ids.get(key) if ordinary_root_ids is not None else None
        native_only = (not _ordinary_missing(records, root_ids) and not _journal_dates_missing(records)
            and any(target not in request_cache for target in _native_targets(records, root_ids)))
        for request in _requests(records, allow_formal_preprint_reverse=allow_formal_preprint_reverse, root_ids=root_ids):
            provider, namespace, identifier = request[:3]
            if native_only and not (provider == 'crossref' and len(request) > 3 and request[3] == 'preprints'):
                continue  # Settle native proof, but first collect independent explicit reverse relations.
            if provider not in enabled_providers or provider in {'arxiv', 'biorxiv', 'medrxiv'}:
                continue
            if provider == 'europe_pmc' and namespace != 'pmid':
                continue
            if request in request_cache:
                continue
            client = clients.get(provider)
            capability = request[3] if len(request) > 3 else None
            if capability == 'summary' and (*request[:3], 'fetch') in request_cache:
                request_cache[request] = request_cache[(*request[:3], 'fetch')]
                continue
            if capability == 'preprints' and provider == 'crossref' and not hasattr(client, 'lookup_preprints'):
                continue
            if not hasattr(client, 'lookup_many'):
                continue
            batches.setdefault((provider, namespace, capability), set()).add(identifier)
    if not batches or cancel_event is not None and cancel_event.is_set():
        return
    with ThreadPoolExecutor(max_workers=min(6, len(batches)), thread_name_prefix='api-completion') as pool:
        futures = [(key, pool.submit(_batch_lookup, clients.get(key[0]), *key[:2], sorted(ids), key[2], cancel_event))
            for key, ids in sorted(batches.items(), key=lambda item: str(item[0]))]
        for (provider, namespace, capability), future in futures:
            for identifier, value in future.result().items():
                request = (provider, namespace, identifier) + ((capability,) if capability else ())
                request_cache[request] = value


def prime_arxiv_cache(record_groups, *, clients, request_cache, cancel_event=None, ordinary_root_ids=None):
    """Batch needed known IDs across selected Papers for this operation."""
    client = clients.get('arxiv')
    if client is None or not hasattr(client, 'lookup_many'):
        return
    ids = sorted({identifier for key, records in record_groups.items() for provider, ns, identifier in _native_targets(
        records, ordinary_root_ids.get(key) if ordinary_root_ids is not None else None)
        if provider == 'arxiv' and (provider, ns, identifier) not in request_cache})
    if not ids or cancel_event is not None and cancel_event.is_set():
        return
    results = client.lookup_many('arxiv', ids)
    for identifier in ids:
        request_cache['arxiv', 'arxiv', identifier] = results.get(identifier, ())


def bind_records(supplements, identities):
    """A primary response identity establishes the root, never a related alias.

    A native reverse response may also contain details linked by that root.
    """
    pending = list(supplements)
    accepted, identities = [], set(identities)
    while pending:
        matched = [record for record in pending if identities & set(strong_identifiers(record.external_ids))]
        if not matched:
            break
        for record in matched:
            pending.remove(record)
            accepted.append(record)
            identities.update(_identities(record))
    return accepted, pending


def _completion_steps(
    records: Sequence[ProviderWorkEvidence], enabled_providers: Sequence[str], *,
    clients: Mapping[str, MetadataLookup], cancel_event: Event | None = None, request_cache: dict | None = None,
    allow_formal_preprint_reverse=True, ordinary_root_ids=None,
):
    """Resolve local goals, schedule one needed target, then re-evaluate.

    Absorb all relations in each response before checking coverage. Cache each
    provider/namespace/identifier, including failures, for the whole operation.
    """
    from allfold.providers.integrated import Cancelled, ProviderHTTPError, IdentityMismatch
    from allfold.canonicalize import evidence_key
    from allfold.paper_dates import first_public_status
    output = sorted(records, key=lambda r: (r.provenance.provider, r.provenance.record_id))
    issues, lookups = [], []
    attempted, fetched = set(), set()
    cache = request_cache if request_cache is not None else {}
    seen = {evidence_key(record) for record in output}
    cache_requests, cache_identities = set(), set()
    reused_record_count = 0
    reported_failures, cached_cancelled = set(), False
    def reuse_cached_evidence():
        nonlocal reused_record_count, cached_cancelled
        # A prior selected Paper may already have obtained the exact same native
        # details or relation. Reuse positive facts without another lookup or alias
        # authority; only records rooted in this Paper's known identities qualify.
        # Cache responses are append-only for this operation. Match each new
        # response against known identities, and old responses only against IDs
        # added since the last pass; unchanged pairs never need rebinding.
        new_identities = {key for record in output[reused_record_count:]
            for key in _identities(record)} - cache_identities
        reused_record_count = len(output)
        cache_identities.update(new_identities)
        for request, value in cache.items():
            identities = new_identities if request in cache_requests else cache_identities
            cache_requests.add(request)
            provider = request[0]
            if provider not in enabled_providers:
                continue
            if isinstance(value, Exception):
                # A dispatched batch can finish while native proof is pending.
                # Settle its outcome before that proof can satisfy the goals;
                # only the requested Paper owns the failure, even when another
                # Paper can reuse some of its verified positive facts.
                if request[1:3] in cache_identities and request not in attempted:
                    attempted.add(request)
                    failure = (*request[:3], id(value))
                    if failure not in reported_failures:
                        reported_failures.add(failure)
                        status = ('cancelled' if isinstance(value, Cancelled) else
                            'partial' if getattr(value, 'records', ()) else
                            'no_match' if isinstance(value, ProviderHTTPError) and value.status == 404 else
                            'identity_mismatch' if isinstance(value, IdentityMismatch) else 'failed')
                        lookups.append(_lookup(request, status))
                        if status not in {'cancelled', 'no_match'}:
                            issues.append(CompletionIssue(provider, request[2], str(value), status))
                        cached_cancelled |= status == 'cancelled'
                value = getattr(value, 'records', ())
            for namespace, identifier in sorted(identities):
                accepted, _ = bind_records(value, {(namespace, identifier)})
                if accepted and not any((item.provider, item.namespace, item.identifier) == request[:3]
                        and item.capability == (request[3] if len(request) > 3 else None) for item in lookups):
                    lookups.append(_lookup(request, 'evidence'))
                    attempted.add(request)
                for record in accepted:
                    record = record.model_copy(update={'provenance': record.provenance.model_copy(
                        update={'provider': provider, 'role': 'supplement'})})
                    key = evidence_key(record)
                    if key not in seen:
                        output.append(record)
                        seen.add(key)
    def result(cancelled=False):
        status = 'cancelled' if cancelled else 'recorded' if any(record.first_public_at for record in output) else first_public_status(output)
        if status not in {'recorded', 'conflict', 'cancelled'} and issues:
            status = 'failed'
        completion_status = ('cancelled' if cancelled else 'partial' if issues and any(item.status in {'evidence', 'partial'} for item in lookups)
            else 'failed' if issues else 'empty' if lookups and all(item.status == 'no_match' for item in lookups) else 'complete')
        return CompletionResult(tuple(output), tuple(issues), tuple(lookups), cancelled, status, completion_status)
    def requests():
        for key in _requests(output, allow_formal_preprint_reverse=allow_formal_preprint_reverse, root_ids=ordinary_root_ids):
            if len(key) > 3 and key[0] == 'crossref' and key[3] == 'preprints' and not hasattr(clients.get('crossref'), 'lookup_preprints'):
                continue
            yield key
    started = False
    while True:
        reuse_cached_evidence()
        if cached_cancelled or cancel_event is not None and cancel_event.is_set():
            return result(True)
        if started and not any(key[0] in enabled_providers and key not in attempted and key not in fetched
                   for key in requests()):
            return result()
        yield tuple(output)
        started = True
        # Another Paper or the native batch may have supplied reusable facts
        # since this Paper paused. Re-evaluate before dispatching its next step.
        reuse_cached_evidence()
        if cached_cancelled or cancel_event is not None and cancel_event.is_set():
            return result(True)
        request = next((key for key in requests() if key[0] in enabled_providers
            and key not in attempted and key not in fetched), None)
        if request is None:
            return result()
        if request[0] == 'arxiv' and request not in cache and hasattr(clients.get('arxiv'), 'lookup_many'):
            # Cached native responses can reveal another family too. Hand that
            # target back to the next shared wave instead of a single-ID call.
            continue
        provider, namespace, identifier = request[:3]
        attempted.add(request)
        client = clients.get(provider)
        try:
            if request not in cache:
                try:
                    if client is None:
                        raise ValueError('Selected metadata adapter is unavailable')
                    if len(request) > 3:
                        cache[request] = _batch_lookup(client, provider, namespace, (identifier,), request[3], cancel_event)[identifier]
                    else:
                        cache[request] = client.lookup(namespace, identifier)
                except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                    cache[request] = error
            supplements = cache[request]
            partial = supplements if isinstance(supplements, Exception) and getattr(supplements, 'records', ()) else None
            if isinstance(supplements, Exception) and partial is None:
                raise supplements
            if partial is not None:
                supplements = partial.records
            accepted, rejected = bind_records(supplements, {(namespace, identifier)})
            status = 'evidence' if accepted else 'no_match'
            if rejected:
                issues.append(CompletionIssue(provider, identifier, 'Metadata response does not match requested identity', 'identity_mismatch'))
                status = 'identity_mismatch'
            for record in accepted:
                fetched.update((provider, ns, value) for ns, value in strong_identifiers(record.external_ids))
                source = record.provenance.model_copy(update={'provider': provider, 'role': 'supplement'})
                record = record.model_copy(update={'provenance': source})
                key = evidence_key(record)
                if key not in seen:
                    output.append(record)
                    seen.add(key)
            if partial is not None:
                issues.append(CompletionIssue(provider, identifier, str(partial), 'partial'))
                status = 'partial'
            lookups.append(_lookup(request, status))
        except Cancelled:
            lookups.append(_lookup(request, 'cancelled'))
            return result(True)
        except ProviderHTTPError as error:
            status = 'no_match' if error.status == 404 else 'failed'
            lookups.append(_lookup(request, status))
            if status == 'failed':
                issues.append(CompletionIssue(provider, identifier, str(error)))
        except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
            status = 'identity_mismatch' if isinstance(error, IdentityMismatch) else 'failed'
            issues.append(CompletionIssue(provider, identifier, str(error), status))
            lookups.append(_lookup(request, status))


def complete_metadata_many(record_groups, enabled_providers, *, clients, cancel_event=None,
                           request_cache=None, paper_guard=None, allow_formal_preprint_reverse=True, ordinary_root_ids=None):
    """Yield completed Papers while batching native targets across response waves.

    Each active Paper advances by at most one necessary response per wave. New
    relations therefore join the next native batch before that Paper can query
    another aggregator. The guard runs before each wave and each Paper step;
    failures are isolated to that Paper and completed results can be saved early.
    """
    cache = request_cache if request_cache is not None else {}
    for client in clients.values():
        if hasattr(client, 'begin_completion'):
            client.begin_completion()
    # Independent completion starts from the selected Paper. Run supplies the
    # original Discovery roots because its prepared groups already contain links.
    if ordinary_root_ids is None:
        ordinary_root_ids = {key: {identity for record in records for identity in strong_identifiers(record.external_ids)}
            for key, records in record_groups.items() if any(record.publication_type != 'preprint' and
                (record.journal or record.conference or record.publication_type in {'journal', 'conference'}) for record in records)}
    active, snapshots = {}, {}
    for key, records in record_groups.items():
        steps = _completion_steps(records, enabled_providers, clients=clients,
            cancel_event=cancel_event, request_cache=cache, allow_formal_preprint_reverse=allow_formal_preprint_reverse,
            ordinary_root_ids=ordinary_root_ids.get(key))
        try:
            snapshots[key] = next(steps)
            active[key] = steps
        except Exception as outcome:
            yield key, outcome.value if isinstance(outcome, StopIteration) else outcome
    while active:
        for key in tuple(active):
            try:
                if paper_guard and not (cancel_event is not None and cancel_event.is_set()):
                    paper_guard(key)
            except Exception as error:
                active.pop(key).close()
                snapshots.pop(key)
                yield key, error
        prime_completion_cache(snapshots, enabled_providers, clients=clients, request_cache=cache,
            cancel_event=cancel_event, allow_formal_preprint_reverse=allow_formal_preprint_reverse, ordinary_root_ids=ordinary_root_ids)
        prime_arxiv_cache(snapshots, clients={provider: client for provider, client in clients.items()
            if provider in enabled_providers}, request_cache=cache, cancel_event=cancel_event, ordinary_root_ids=ordinary_root_ids)
        for key, steps in tuple(active.items()):
            try:
                if paper_guard and not (cancel_event is not None and cancel_event.is_set()):
                    paper_guard(key)
                snapshots[key] = next(steps)
            except Exception as outcome:
                active.pop(key).close()
                snapshots.pop(key)
                yield key, outcome.value if isinstance(outcome, StopIteration) else outcome


def complete_metadata(
    records: Sequence[ProviderWorkEvidence], enabled_providers: Sequence[str], *,
    clients: Mapping[str, MetadataLookup], cancel_event: Event | None = None, request_cache: dict | None = None,
    allow_formal_preprint_reverse=True,
) -> CompletionResult:
    """Complete one Paper through the same native batch scheduler."""
    _, result = next(complete_metadata_many({0: records}, enabled_providers, clients=clients,
        cancel_event=cancel_event, request_cache=request_cache, allow_formal_preprint_reverse=allow_formal_preprint_reverse))
    if isinstance(result, Exception):
        raise result
    return result
