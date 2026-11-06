"""Selected-provider identifier traversal for an explicit API operation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from allfold.identifiers import normalize_external_id, strong_identifiers, evidence_identifiers
from allfold.models import ProviderWorkEvidence


# Identity services precede known-preprint lookups. This is execution order, not
# an authority score; canonicalization independently preserves primary fields.
COMPLETION_ORDER = ("openalex", "crossref", "europe_pmc", "arxiv", "biorxiv", "medrxiv")
LOOKUP_NAMESPACES = {
    "openalex": ("openalex", "doi"), "crossref": ("doi",),
    "europe_pmc": ("europe_pmc", "pmid", "pmcid", "doi"),
    "arxiv": ("arxiv",), "biorxiv": ("doi",), "medrxiv": ("doi",),
}


class MetadataLookup(Protocol):
    def lookup(self, namespace: str, identifier: str) -> tuple[ProviderWorkEvidence, ...]: ...


@dataclass(frozen=True)
class CompletionIssue:
    provider: str
    identifier: str
    message: str
    status: str = "failed"


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


def _identities(record):
    identities = set(evidence_identifiers(record))
    # An arXiv DOI explicitly encodes a known arXiv identifier, not a title match.
    for namespace, value in tuple(identities):
        if namespace == "doi" and value.startswith("10.48550/arxiv."):
            arxiv = normalize_external_id("arxiv", value.removeprefix("10.48550/arxiv."))
            if arxiv:
                identities.add(("arxiv", arxiv))
    return identities


def _targets(provider, records):
    from allfold.paper_dates import collect_dates, first_public_date, date_value
    dates = collect_dates(records)
    earliest = {date_value(item) for item in dates if item.first_version and item.kind.value == 'preprint'}
    metadata_answered = all(any(getattr(record, field) for record in records) for field in ('abstract', 'authors', 'publication_date'))
    if provider in {'arxiv', 'biorxiv', 'medrxiv'} and first_public_date(dates) and len(earliest) == 1 and metadata_answered:
        return []  # Aggregated first-version evidence already answers the gap.
    targets = set()
    for record in records:
        ids = _identities(record)
        for namespace in LOOKUP_NAMESPACES[provider]:
            primary = strong_identifiers(record.external_ids)
            keys = {key for key in primary if key[0] == namespace}
            if keys:
                targets.update(keys)
                break
        targets.update(key for key in ids - set(strong_identifiers(record.external_ids))
                       if key[0] in LOOKUP_NAMESPACES[provider])
        if provider == 'arxiv':
            targets.update(key for key in ids if key[0] == 'arxiv')
    if provider in {'biorxiv', 'medrxiv'}:
        other = 'medrxiv' if provider == 'biorxiv' else 'biorxiv'
        known_other = {ref.record_id for record in records for ref in record.related_ids if ref.provider == other}
        targets = {key for key in targets if not key[1].startswith('10.48550/arxiv.') and key[1] not in known_other}
    return sorted(targets)


def complete_metadata(
    records: Sequence[ProviderWorkEvidence], enabled_providers: Sequence[str], *,
    clients: Mapping[str, MetadataLookup], cancel_event: Event | None = None, request_cache: dict | None = None,
) -> CompletionResult:
    """Reuse responses, then look up selected providers by known identity only.

    Follow reliable linked identities until no unqueried targets remain. Each
    provider/namespace/identifier is attempted once, including failed lookups.
    """
    from allfold.providers.integrated import Cancelled, ProviderHTTPError, IdentityMismatch
    from allfold.persistence.discovery_evidence import evidence_key
    output = sorted(records, key=lambda r: (r.provenance.provider, r.provenance.record_id))
    issues, lookups = [], []
    attempted = set()
    fetched = set()
    cache = request_cache if request_cache is not None else {}
    seen = {evidence_key(record) for record in output}
    while True:
        previous_attempts = len(attempted)
        for provider in COMPLETION_ORDER:
            if provider not in enabled_providers:
                continue
            for namespace, identifier in _targets(provider, output):
                if cancel_event is not None and cancel_event.is_set():
                    return CompletionResult(tuple(output), tuple(issues), tuple(lookups), True)
                request = provider, namespace, identifier
                if request in attempted or request in fetched:
                    continue
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
                    status = 'no_match'
                    for record in supplements:
                        if (namespace, identifier) not in _identities(record):
                            issues.append(CompletionIssue(provider, identifier, 'Metadata response does not match requested identity', 'identity_mismatch'))
                            if status != 'evidence':
                                status = 'identity_mismatch'
                            continue
                        status = 'evidence'
                        # Reuse identities actually returned in this operation.
                        # Ordinary completeness in old evidence is not a refresh ban.
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
                    return CompletionResult(tuple(output), tuple(issues), tuple(lookups), True)
                except ProviderHTTPError as error:
                    status = 'no_match' if error.status == 404 else 'failed'
                    lookups.append(CompletionLookup(*request, status))
                    if status == 'failed':
                        issues.append(CompletionIssue(provider, identifier, str(error)))
                except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                    status = 'identity_mismatch' if isinstance(error, IdentityMismatch) else 'failed'
                    issues.append(CompletionIssue(provider, identifier, str(error), status))
                    lookups.append(CompletionLookup(*request, status))
        if len(attempted) == previous_attempts:
            break
    return CompletionResult(tuple(output), tuple(issues), tuple(lookups))
