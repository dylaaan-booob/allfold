"""Target-directed completion of saved evidence, independent of discovery."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from allfold.identifiers import strong_identifiers, evidence_identifiers
from allfold.models import ProviderWorkEvidence

LOOKUP_NAMESPACES = {
    'openalex': ('openalex', 'doi'), 'crossref': ('doi',),
    'europe_pmc': ('europe_pmc', 'pmid', 'pmcid', 'doi'),
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


@dataclass(frozen=True)
class CompletionResult:
    records: tuple[ProviderWorkEvidence, ...]
    issues: tuple[CompletionIssue, ...]
    lookups: tuple[CompletionLookup, ...] = ()
    cancelled: bool = False
    first_public_status: str = 'no_association'


def _identities(record):
    return set(evidence_identifiers(record))


def _ordinary_missing(records):
    formal = any(record.publication_type in {'journal', 'conference'} or
        record.publication_type != 'preprint' and (record.journal or record.conference) for record in records)
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
    return journal and not (any(record.publication_date for record in records if record.publication_type != 'preprint')
        or any(item.kind in {EvidenceDateKind.ACCEPTED, EvidenceDateKind.PUBLISHED_ONLINE, EvidenceDateKind.PUBLISHED}
            and item.publication_type == 'journal' for item in collect_dates(records)))


def _native_targets(records):
    from allfold.paper_dates import preprint_date_coverage, preprint_identity
    _, answered = preprint_date_coverage(records)
    ordinary = _ordinary_missing(records)
    targets = set()
    for record in records:
        for ns, value in _identities(record):
            if ns == 'arxiv' and (ordinary or preprint_identity(ns, value) not in answered):
                targets.add(('arxiv', ns, value))
            if ns == 'europe_pmc' and value.startswith('PPR:') and (ordinary or preprint_identity(ns, value) not in answered):
                targets.add(('europe_pmc', ns, value))
        platforms = {(ref.provider, ref.record_id) for ref in record.related_ids if ref.provider in {'biorxiv','medrxiv'}}
        if record.provenance.provider in {'biorxiv','medrxiv'} and record.publication_type == 'preprint' and record.external_ids.doi:
            platforms.add((record.provenance.provider, record.external_ids.doi))
        for item in record.dates:
            if item.provider in {'biorxiv','medrxiv'} and item.record_id and item.kind.value == 'preprint':
                from allfold.identifiers import valid_doi
                raw = item.record_id
                if raw.rpartition(':')[2].isdigit():
                    raw = raw.rpartition(':')[0]
                if doi := valid_doi(raw):
                    platforms.add((item.provider, doi))
        for platform, doi in platforms:
            if ordinary or preprint_identity('doi', doi) not in answered:
                targets.add((platform, 'doi', doi))
    return sorted(targets)


def _requests(records):
    from allfold.paper_dates import preprint_date_coverage, known_preprint_families, preprint_identity
    yield from _native_targets(records)
    complete, answered = preprint_date_coverage(records)
    families = known_preprint_families(records)
    metadata = _ordinary_missing(records) or _journal_dates_missing(records)
    if complete and not metadata:
        return
    # Prefer the formal DOI's named relation before searching further aggregators.
    for provider in ('crossref', 'openalex', 'europe_pmc'):
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
            if not metadata and preprint_identity(ns, value) in answered:
                continue
            yield provider, ns, value
    # Reverse lookup discovers associations; it never guesses a known preprint's
    # platform or enumerates other systems once a family has been established.
    if not known_preprint_families(records):
        formal = {value for record in records for ns, value in strong_identifiers(record.external_ids)
            if ns == 'doi' and not value.startswith(('10.1101/', '10.48550/arxiv.'))}
        for provider in ('biorxiv', 'medrxiv'):
            for doi in sorted(formal):
                yield provider, 'doi', doi


def prime_arxiv_cache(record_groups, *, clients, request_cache, cancel_event=None):
    """Batch needed known IDs across selected Papers for this operation."""
    client = clients.get('arxiv')
    if client is None or not hasattr(client, 'lookup_many'):
        return
    ids = sorted({identifier for records in record_groups for provider, ns, identifier in _native_targets(records)
        if provider == 'arxiv' and (provider, ns, identifier) not in request_cache})
    if not ids or cancel_event is not None and cancel_event.is_set():
        return
    results = client.lookup_many('arxiv', ids)
    for identifier in ids:
        request_cache['arxiv', 'arxiv', identifier] = results.get(identifier, ())


def _bound_records(supplements, namespace, identifier):
    """A primary response identity establishes the root, never a related alias.

    A native reverse response may also contain details linked by that root.
    """
    pending = list(supplements)
    accepted, identities = [], {(namespace, identifier)}
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
):
    """Resolve local goals, schedule one needed target, then re-evaluate.

    Absorb all relations in each response before checking coverage. Cache each
    provider/namespace/identifier, including failures, for the whole operation.
    """
    from allfold.providers.integrated import Cancelled, ProviderHTTPError, IdentityMismatch
    from allfold.persistence.discovery_evidence import evidence_key
    from allfold.paper_dates import first_public_status
    output = sorted(records, key=lambda r: (r.provenance.provider, r.provenance.record_id))
    issues, lookups = [], []
    attempted, fetched = set(), set()
    cache = request_cache if request_cache is not None else {}
    seen = {evidence_key(record) for record in output}
    def reuse_cached_evidence():
        # A prior selected Paper may already have obtained the exact same native
        # details or relation. Reuse positive facts without another lookup or alias
        # authority; only records rooted in this Paper's known identities qualify.
        identities = {key for record in output for key in _identities(record)}
        for request, value in cache.items():
            provider = request[0]
            if provider not in enabled_providers or isinstance(value, Exception):
                continue
            for namespace, identifier in sorted(identities):
                accepted, _ = _bound_records(value, namespace, identifier)
                if accepted and not any((item.provider, item.namespace, item.identifier) == request for item in lookups):
                    lookups.append(CompletionLookup(*request, 'evidence'))
                    attempted.add(request)
                for record in accepted:
                    record = record.model_copy(update={'provenance': record.provenance.model_copy(
                        update={'provider': provider, 'role': 'supplement'})})
                    key = evidence_key(record)
                    if key not in seen:
                        output.append(record)
                        seen.add(key)
    def result(cancelled=False):
        status = 'cancelled' if cancelled else first_public_status(output)
        if status not in {'recorded', 'conflict', 'cancelled'} and issues:
            status = 'failed'
        return CompletionResult(tuple(output), tuple(issues), tuple(lookups), cancelled, status)
    started = False
    while True:
        reuse_cached_evidence()
        if cancel_event is not None and cancel_event.is_set():
            return result(True)
        if started and not any(key[0] in enabled_providers and key not in attempted and key not in fetched
                   for key in _requests(output)):
            return result()
        yield tuple(output)
        started = True
        # Another Paper or the native batch may have supplied reusable facts
        # since this Paper paused. Re-evaluate before dispatching its next step.
        reuse_cached_evidence()
        if cancel_event is not None and cancel_event.is_set():
            return result(True)
        request = next((key for key in _requests(output) if key[0] in enabled_providers
            and key not in attempted and key not in fetched), None)
        if request is None:
            return result()
        if request[0] == 'arxiv' and request not in cache and hasattr(clients.get('arxiv'), 'lookup_many'):
            # Cached native responses can reveal another family too. Hand that
            # target back to the next shared wave instead of a single-ID call.
            continue
        provider, namespace, identifier = request
        attempted.add(request)
        client = clients.get(provider)
        try:
            if request not in cache:
                try:
                    if client is None:
                        raise ValueError('Selected metadata adapter is unavailable')
                    cache[request] = client.lookup(namespace, identifier)
                except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                    cache[request] = error
            supplements = cache[request]
            if isinstance(supplements, Exception):
                raise supplements
            accepted, rejected = _bound_records(supplements, namespace, identifier)
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
            lookups.append(CompletionLookup(*request, status))
        except Cancelled:
            lookups.append(CompletionLookup(*request, 'cancelled'))
            return result(True)
        except ProviderHTTPError as error:
            status = 'no_match' if error.status == 404 else 'failed'
            lookups.append(CompletionLookup(*request, status))
            if status == 'failed':
                issues.append(CompletionIssue(provider, identifier, str(error)))
        except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
            status = 'identity_mismatch' if isinstance(error, IdentityMismatch) else 'failed'
            issues.append(CompletionIssue(provider, identifier, str(error), status))
            lookups.append(CompletionLookup(*request, status))


def complete_metadata_many(record_groups, enabled_providers, *, clients, cancel_event=None,
                           request_cache=None, paper_guard=None):
    """Yield completed Papers while batching native targets across response waves.

    Each active Paper advances by at most one necessary response per wave. New
    relations therefore join the next native batch before that Paper can query
    another aggregator. The guard runs before each wave and each Paper step;
    failures are isolated to that Paper and completed results can be saved early.
    """
    cache = request_cache if request_cache is not None else {}
    active, snapshots = {}, {}
    for key, records in record_groups.items():
        steps = _completion_steps(records, enabled_providers, clients=clients,
            cancel_event=cancel_event, request_cache=cache)
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
        prime_arxiv_cache(snapshots.values(), clients={provider: client for provider, client in clients.items()
            if provider in enabled_providers}, request_cache=cache, cancel_event=cancel_event)
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
) -> CompletionResult:
    """Complete one Paper through the same native batch scheduler."""
    _, result = next(complete_metadata_many({0: records}, enabled_providers, clients=clients,
        cancel_event=cancel_event, request_cache=request_cache))
    if isinstance(result, Exception):
        raise result
    return result
