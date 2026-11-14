"""Purpose-driven identity, Preprint relationship and native-version services.

These components use the captured Workspace task. Ordinary missing fields are
never request goals. Production Run hands off immutable purpose-labelled evidence.
"""
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from allfold.abstract_text import normalize_abstract_text
from allfold.application.provider_lookup import (
    LookupIssue, LookupFact, LookupSettlement, _batch_lookup, bind_records, formal_records,
)
from allfold.identifiers import normalize_external_id, related_identifiers, strong_identifiers
from allfold.models import EvidenceDateKind, ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.paper_dates import (
    collect_dates, date_value, first_public_date, first_public_status, preprint_date_coverage,
    preprint_identity, preprint_query_refs,
)
from allfold.persistence.library_models import MetadataDelta
from allfold.pdf_facts import PdfDiscoveryFacts, discovery_facts_from_records
from allfold.providers.integrated import Cancelled, DiscoveryError, IdentityMismatch


@dataclass(frozen=True, order=True)
class NecessaryRequest:
    provider: str
    namespace: str
    identifier: str
    capability: str

    def __post_init__(self):
        capabilities = {
            ('crossref', 'doi'): {'exact', 'reverse'},
            ('pubmed', 'pmid'): {'summary', 'fetch', 'fetch-preprint'},
            ('openalex', 'doi'): {'work'}, ('openalex', 'openalex'): {'work'},
            ('europe_pmc', 'pmid'): {'preprints'},
            ('europe_pmc', 'europe_pmc'): {'native'}, ('europe_pmc', 'doi'): {'native'},
            ('arxiv', 'arxiv'): {'native'},
            ('biorxiv', 'doi'): {'native', 'reverse'}, ('medrxiv', 'doi'): {'native', 'reverse'},
        }
        value = normalize_external_id(self.namespace, self.identifier)
        if (self.capability not in capabilities.get((self.provider, self.namespace), ()) or not value
                or self.namespace == 'europe_pmc' and not value.startswith('PPR:')):
            raise ValueError('Invalid necessary Provider capability or identity')
        object.__setattr__(self, 'identifier', value)


@dataclass(frozen=True)
class VerifiedResponse:
    """Explicit immutable capability handoff; no Run client/cache/closure ownership."""
    request: NecessaryRequest
    records: tuple = ()
    complete: bool = True

    def __post_init__(self):
        if type(self.complete) is not bool:
            raise TypeError('Verified capability completeness must be boolean')
        object.__setattr__(self, 'records', tuple(self.records))
        if any(not isinstance(item, ProviderWorkEvidence) or item.provenance.provider != self.request.provider
               for item in self.records):
            raise ValueError('Verified capability facts must come from the named Provider')


def _satisfied(request, facts):
    return any(fact.complete and (fact.request == request or request.provider == 'pubmed'
        and (request.capability == 'summary' or request.capability == 'fetch-preprint' and
            any(item.publication_type == 'preprint' for item in fact.records)) and fact.request == NecessaryRequest(
            'pubmed', request.namespace, request.identifier, 'fetch')) for fact in facts)


def _native_proof_requests(records, *, include_proven=False):
    """Plan known native targets; explicit retries may revalidate positive proof."""
    _, answered = preprint_date_coverage(records)
    if include_proven:
        answered = set()
    requests = set()
    for item in records:
        platforms = {(ref.provider, ref.record_id) for ref in item.related_ids
            if ref.provider in {'biorxiv', 'medrxiv'}}
        if item.publication_type == 'preprint' and item.provenance.provider in {'biorxiv', 'medrxiv'} and item.external_ids.doi:
            platforms.add((item.provenance.provider, item.external_ids.doi))
        platforms.update((ref.provider, ref.record_id) for ref in preprint_query_refs(item.dates)
            if ref.provider in {'biorxiv', 'medrxiv'})
        for provider, doi in platforms:
            if preprint_identity('doi', doi) not in answered:
                requests.add(NecessaryRequest(provider, 'doi', doi, 'native'))
        for namespace, value in related_identifiers(item):
            if preprint_identity(namespace, value) in answered:
                continue
            if namespace == 'arxiv':
                requests.add(NecessaryRequest('arxiv', namespace, value, 'native'))
            elif namespace == 'europe_pmc' and value.startswith('PPR:'):
                requests.add(NecessaryRequest('europe_pmc', namespace, value, 'native'))
        preprint_dois = {ref.record_id for ref in item.related_ids if ref.provider == 'doi' and ref.relation == 'preprint'}
        if item.publication_type == 'preprint' and item.external_ids.doi:
            preprint_dois.add(item.external_ids.doi)
        for doi in preprint_dois:
            if (not doi.startswith('10.48550/arxiv.') and not any(value == doi for _, value in platforms)
                    and preprint_identity('doi', doi) not in answered):
                requests.add(NecessaryRequest('europe_pmc', 'doi', doi, 'native'))
    return requests


def _qualified_direct_records(records, root_ids):
    """A WoS PM is reported, unless the saved Paper already owns it.

    Keep the parser's source-field evidence and same-article metadata. The
    precreation PubMed DOI confirmation service owns any new formal PMID.
    """
    output = []
    for item in records:
        ids = item.external_ids.model_dump(exclude_none=True)
        if (item.provenance.provider == 'wos' and ids.get('pmid')
                and ('pmid', ids['pmid']) not in root_ids):
            ids.pop('pmid')
            item = item.model_copy(update={'external_ids': ExternalIds(**ids)})
        output.append(item)
    return tuple(output)


def necessary_requests(records, *, root_ids, providers, facts=(), required=(),
                       discover_relations=True, first_public_saved=False):
    """Plan only unfinished identity/relationship/native purposes, never field gaps.

    Work location and native /pubs reverse are explicit `required` purposes.
    Direct DOI→PMID closure belongs to the separate precreation service.
    """
    records = _qualified_direct_records(records, root_ids)
    requests = set(required)
    if discover_relations and not first_public_saved:
        _, answered = preprint_date_coverage(records)
        formal_ids = {key for item in formal_records(records, root_ids)
            for key in strong_identifiers(item.external_ids)}
        for namespace, value in formal_ids:
            if namespace == 'doi':
                requests.update((NecessaryRequest('crossref', namespace, value, 'exact'),
                    NecessaryRequest('crossref', namespace, value, 'reverse')))
            if namespace == 'pmid':
                requests.update((NecessaryRequest('pubmed', namespace, value, 'summary'),
                    NecessaryRequest('europe_pmc', namespace, value, 'preprints')))
        requests.update(_native_proof_requests(records))
        for item in records:
            if item.publication_type == 'preprint' and item.external_ids.model_dump().get('pmid'):
                requests.add(NecessaryRequest('pubmed', 'pmid', item.external_ids.model_dump()['pmid'], 'fetch-preprint'))
            for namespace, value in related_identifiers(item):
                if (namespace == 'doi' and (namespace, value) not in formal_ids
                        and preprint_identity(namespace, value) not in answered):
                    requests.add(NecessaryRequest('crossref', namespace, value, 'exact'))
            for ref in item.related_ids:
                if (ref.provider == 'pubmed' and ref.relation == 'preprint'
                        and preprint_identity('pmid', ref.record_id) not in answered):
                    requests.add(NecessaryRequest('pubmed', 'pmid', ref.record_id, 'fetch-preprint'))
                if ref.provider == 'doi' and preprint_identity('doi', ref.record_id) not in answered:
                    requests.add(NecessaryRequest('crossref', 'doi', ref.record_id, 'exact'))
    return tuple(sorted(request for request in requests if request.provider in providers
        and not _satisfied(request, facts)))


def confirm_formal_dois(client, identifiers, *, guard=lambda: None):
    """Precreation identity closure over the existing quoted [aid]/summary/fetch API.

    The caller owns the client, parent deadline, guards and identity-owner check.
    This is intentionally separate from the existing-Paper collection branch.
    """
    guard()
    result = client.resolve_pubmed_dois(tuple(dict.fromkeys(identifiers)))
    guard()
    return result


@dataclass(frozen=True)
class NecessaryResult:
    records: tuple
    lookups: tuple[LookupFact, ...]
    issues: tuple[LookupIssue, ...]
    first_public_status: str

    @property
    def status(self):
        if any(item.status == 'cancelled' for item in self.lookups):
            return 'cancelled'
        if self.issues:
            return 'partial' if any(item.status in {'evidence', 'partial'} for item in self.lookups) else 'failed'
        return 'complete' if any(item.status == 'evidence' for item in self.lookups) else 'empty'


class NecessaryLookupFailed(DiscoveryError):
    def __init__(self, result):
        self.result = result
        super().__init__('Necessary Provider work did not complete: ' + result.status)


def _lookup_group(context, requests):
    first = requests[0]
    client = context.provider(first.provider)
    identifiers = tuple(item.identifier for item in requests)
    if first.provider in {'biorxiv', 'medrxiv'}:
        values = {}
        for identifier in identifiers:
            context.guard()
            try:
                values[identifier] = (client.lookup_published_preprints(identifier) if first.capability == 'reverse'
                    else client.lookup(first.namespace, identifier))
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                values[identifier] = error
        return values
    capability = {'exact': None, 'work': None, 'native': None,
        'reverse': 'preprints'}.get(first.capability, first.capability)
    return _batch_lookup(client, first.provider, first.namespace, identifiers, capability, context.cancel_event)


def paper_evidence(paper):
    metadata = paper.metadata
    direct = {identity.namespace: identity.value for identity in paper.identities}
    if paper.primary_identity is not None:
        direct[paper.primary_identity.namespace] = paper.primary_identity.value
    return ProviderWorkEvidence(provenance=MetadataSource(provider='workspace', record_id=str(paper.id),
        retrieved_at=datetime.now(timezone.utc)), external_ids=ExternalIds(**direct),
        publication_type=metadata.publication_type, journal=metadata.journal, conference=metadata.conference,
        dates=metadata.preprint_evidence,
        related_ids=tuple(dict.fromkeys((*metadata.preprint_relations, *preprint_query_refs(metadata.preprint_evidence)))),
        first_public_at=metadata.first_public_at)


def paper_evidence_records(paper):
    """Project every saved direct alias without changing the selected primary.

    One projection cannot hold multiple values in a namespace. Extra records
    express the trusted Paper closure for purpose/native/family planning, never
    turn related or unconfirmed source identities into direct ownership.
    """
    primary = paper_evidence(paper)
    represented = strong_identifiers(primary.external_ids)
    return (primary, *(primary.model_copy(update={'external_ids': primary.external_ids.model_copy(update={
        identity.namespace: identity.value})}) for identity in paper.identities
        if (identity.namespace, identity.value) not in represented))


def _formal_conflicts(records, root_ids, *, formal_root=True):
    """A returned direct root cannot carry a conflicting existing DOI or PMID."""
    known = defaultdict(set)
    for namespace, value in root_ids:
        known[namespace].add(value)
    accepted, rejected = [], []
    for item in records:
        primary = strong_identifiers(item.external_ids)
        direct = bool(primary & root_ids)
        conflict = direct and (formal_root and item.publication_type == 'preprint' or any(
            namespace in {'doi', 'pmid'} and known[namespace] and value not in known[namespace]
            for namespace, value in primary))
        if (formal_root and item.provenance.provider in {'biorxiv', 'medrxiv'} and item.publication_type == 'preprint'
                and known['doi'] and set(item.related_dois) - known['doi']):
            conflict = True  # Native details' explicit published DOI must bind to this formal Paper.
        (rejected if conflict else accepted).append(item)
    return tuple(accepted), tuple(rejected)


def _increment(records, root_ids, *, preprint_root=False, target_doi=None):
    formal = formal_records(records, root_ids)
    abstracts = {}
    for item in formal:
        if text := normalize_abstract_text(item.abstract):
            abstracts.setdefault(text, item.abstract)
    dates = tuple(date_value(item) for item in collect_dates(formal)
        if item.kind != EvidenceDateKind.PREPRINT and item.publication_type != 'preprint' and item.month is not None)
    proof = tuple(item for item in collect_dates(records) if item.kind == EvidenceDateKind.PREPRINT)
    relations = tuple(dict.fromkeys(ref for item in records for ref in item.related_ids))
    # Reliable DOI aliases may each supply bibliography/relations, while the
    # bounded Crossref PDF snapshot belongs to the explicitly selected target.
    # Unknown targets retain the normal binding/conflict checks.
    discovery_records = tuple(item.model_copy(update={'discovery_facts': tuple(fact for fact in item.discovery_facts
        if not (fact.source == 'crossref' and target_doi and fact.target_doi != target_doi
                and ('doi', fact.target_doi) in root_ids))}) for item in records)
    delta = MetadataDelta(ordinary_dates=dates, abstract=next(iter(abstracts.values())) if len(abstracts) == 1 else None,
        discovery_facts=discovery_facts_from_records(discovery_records, root_ids, preprint_root=preprint_root),
        preprint_evidence=proof, preprint_relations=relations,
        sources=tuple(dict.fromkeys(item.provenance for item in records if item.provenance.provider != 'workspace')))
    identities = defaultdict(set)
    for item in formal:
        for namespace, value in strong_identifiers(item.external_ids):
            identities[namespace].add(value)
    if any(len(values) > 1 and not {(namespace, value) for value in values} <= root_ids
            for namespace, values in identities.items()):
        raise IdentityMismatch('Formal response has conflicting direct identities')
    direct = {namespace: sorted(values)[0] for namespace, values in identities.items()}
    return delta, ExternalIds(**direct) if direct else None


def collect_necessary_metadata(context, *, records=(), facts=(), required=(), providers=(),
                               discover_relations=True):
    """Run one captured branch, emitting reliable increments as responses arrive.

    Facts are immutable, explicitly capability-labelled verified responses. Local
    caches and failure state end with this invocation; clients remain task-owned.
    The returned report is for the caller, never a registry branch result.
    """
    from allfold.canonicalize import evidence_key

    paper = context.read_paper()
    root_ids = {(identity.namespace, identity.value) for identity in paper.identities}
    target_doi = (paper.primary_identity.value if paper.primary_identity is not None
        and paper.primary_identity.namespace == 'doi' else None)
    output = list(paper_evidence_records(paper))
    seen = {evidence_key(item) for item in output}
    lookups, issues, attempted, completed = [], [], set(), []
    required = set(required)
    sequence = 0

    def absorb(request, values, *, complete=True):
        nonlocal sequence
        error = values if isinstance(values, Exception) else None
        candidates = tuple(getattr(error, 'records', ())) if error else tuple(values)
        candidates = _qualified_direct_records(candidates, root_ids)
        candidates, conflicts = _formal_conflicts(candidates, root_ids,
            formal_root=paper.metadata.publication_type != 'preprint')
        accepted, rejected = bind_records(candidates, root_ids if request is None else {
            (request.namespace, request.identifier)})
        if request is not None:
            status = ('cancelled' if isinstance(error, Cancelled) else
                'partial' if error and accepted else 'identity_mismatch' if isinstance(error, IdentityMismatch)
                or conflicts or rejected else 'failed' if error else 'evidence' if accepted else 'no_match')
            if conflicts or rejected or error and status != 'no_match':
                issues.append(LookupIssue(request.provider, request.identifier,
                    'Response conflicts with the requested direct identity' if conflicts or rejected else str(error), status))
            lookups.append(LookupFact(request.provider, request.namespace, request.identifier, status, request.capability))
            attempted.add(request)
            if status in {'evidence', 'no_match'}:
                completed.append(VerifiedResponse(request, tuple(accepted), complete=complete))
        elif conflicts or rejected:
            raise IdentityMismatch('Verified handoff does not bind to this Paper')
        new = []
        for item in accepted:
            key = evidence_key(item)
            if key not in seen:
                seen.add(key)
                output.append(item)
                new.append(item)
        empty_snapshot = ()
        if (request is not None and not accepted and not isinstance(error, Cancelled)
                and request.provider in {'crossref', 'openalex'} and request.capability in {'exact', 'work'}
                and (request.namespace, request.identifier) in root_ids
                and not (request.provider == 'crossref' and target_doi and request.identifier != target_doi)):
            failed = bool(error or conflicts or rejected)
            empty_snapshot = (PdfDiscoveryFacts(source=request.provider,
                capability='crossref-links' if request.provider == 'crossref' else 'openalex-locations',
                status='failed' if failed else 'complete' if complete else 'partial',
                observed_at=datetime.now(timezone.utc),
                target_doi=request.identifier if request.namespace == 'doi' else None,
                target_openalex=request.identifier if request.namespace == 'openalex' else None,
                diagnostics=('parse-failed',) if failed else ('incomplete-response',) if not complete else ()),)
        if new or empty_snapshot:
            delta, direct_ids = _increment(tuple(new), root_ids,
                preprint_root=paper.metadata.publication_type == 'preprint', target_doi=target_doi)
            if empty_snapshot:
                delta = delta.model_copy(update={'discovery_facts': empty_snapshot})
            sequence += 1
            context.emit(delta, sequence=sequence, direct_ids=direct_ids)
            root_ids.update((identity.namespace, identity.value) for identity in context.read_paper().identities)
        if isinstance(error, Cancelled):
            context.cancel_event.set()
            raise error

    absorb(None, records)
    pending = [fact for fact in facts if fact.request.provider in providers]
    while pending:
        context.guard()
        linked = {key for item in output for key in related_identifiers(item)}
        ready = [fact for fact in pending if (fact.request.namespace, fact.request.identifier) in linked]
        if not ready:
            raise IdentityMismatch('Verified capability does not belong to this Paper')
        for fact in ready:
            pending.remove(fact)
            absorb(fact.request, fact.records, complete=fact.complete)
            if not fact.complete:
                completed[:] = [item for item in completed if item.request != fact.request]
                attempted.discard(fact.request)
                # Positive partial proof can satisfy a family heuristic, but
                # cannot finish the capability that supplied the handoff.
                required.add(fact.request)
    if context.token.attempt > 1 and not paper.metadata.first_public_at:
        # A failed prior attempt can persist positive proof without persisting
        # complete capability facts. Explicit retry revalidates known native
        # targets; a complete handoff in this invocation can satisfy them.
        required.update(_native_proof_requests(tuple(output), include_proven=True))
    while True:
        context.guard()
        requests = tuple(item for item in necessary_requests(tuple(output), root_ids=root_ids,
            providers=providers, facts=completed, required=required, discover_relations=discover_relations,
            first_public_saved=bool(paper.metadata.first_public_at)) if item not in attempted)
        if not requests:
            break
        first = requests[0]
        group = tuple(item for item in requests if (item.provider, item.namespace, item.capability)
            == (first.provider, first.namespace, first.capability))
        linked = {key for item in output for key in related_identifiers(item)}
        if any((item.namespace, item.identifier) not in linked for item in group):
            raise IdentityMismatch('Necessary target lacks a verified Paper identity or relation')
        client = context.provider(first.provider)
        if hasattr(client, 'begin_completion'):
            client.begin_completion()
        values, settlement = {}, LookupSettlement()
        values.update(settlement.capture(client, lambda: _lookup_group(context, group), values.update))
        settlement.settle(context.cancel_event)
        for request in group:
            context.guard()
            absorb(request, values[request.identifier])

    current = context.read_paper()
    # Include latest independent proof increments without recapturing write
    # authority. A newly known unresolved family must prevent an early value.
    final_records = (*output, *paper_evidence_records(current))
    status = 'recorded' if current.metadata.first_public_at else first_public_status(final_records)
    if issues and status != 'conflict' and not current.metadata.first_public_at:
        status = 'failed'
    if not issues and not current.metadata.first_public_at:
        first_public = first_public_date(collect_dates(final_records), records=final_records)
        if first_public:
            sequence += 1
            context.emit(MetadataDelta(first_public_at=first_public), sequence=sequence)
    return NecessaryResult(tuple(output), tuple(lookups), tuple(issues), status)


def necessary_metadata_branch(*, name='necessary-api', providers=(), records=(), facts=(),
                              required=(), discover_relations=True):
    """Declare a complete purpose-driven branch with immutable handoff facts."""
    from allfold.application.collection_runtime import BranchSpec

    providers, records, facts, required = tuple(providers), tuple(records), tuple(facts), tuple(required)
    if any(item.provider not in providers for item in required):
        raise ValueError('A necessary request requires a declared Provider')
    def run(context):
        result = collect_necessary_metadata(context, records=records, facts=facts, required=required,
            providers=providers, discover_relations=discover_relations)
        if result.issues:
            raise NecessaryLookupFailed(result)
        # All content has already been emitted with explicit branch sequences.
    return BranchSpec(name, run, providers=providers)
