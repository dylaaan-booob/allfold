"""Identifier-only metadata completion before first Paper creation."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from threading import Event
from typing import Protocol

from allfold.identifiers import normalize_external_id, strong_identifiers
from allfold.models import ProviderWorkEvidence


# Identity services precede known-preprint lookups. This is execution order, not
# an authority score; canonicalization independently preserves primary fields.
COMPLETION_ORDER = ("openalex", "crossref", "europe_pmc", "dblp", "zbmath", "arxiv", "biorxiv", "medrxiv")
LOOKUP_NAMESPACES = {
    "openalex": ("openalex", "doi"), "crossref": ("doi",),
    "europe_pmc": ("europe_pmc", "pmid", "pmcid", "doi"),
    "dblp": ("dblp",), "zbmath": ("zbmath", "doi"),
    "arxiv": ("arxiv",), "biorxiv": ("doi",), "medrxiv": ("doi",),
}


class MetadataLookup(Protocol):
    def lookup(self, namespace: str, identifier: str) -> tuple[ProviderWorkEvidence, ...]: ...


@dataclass(frozen=True)
class CompletionIssue:
    provider: str
    identifier: str
    message: str


@dataclass(frozen=True)
class CompletionResult:
    records: tuple[ProviderWorkEvidence, ...]
    issues: tuple[CompletionIssue, ...]


def _identities(record):
    identities = set(strong_identifiers(record.external_ids, record.related_dois))
    # An arXiv DOI explicitly encodes a known arXiv identifier, not a title match.
    for namespace, value in tuple(identities):
        if namespace == "doi" and value.startswith("10.48550/arxiv."):
            arxiv = normalize_external_id("arxiv", value.removeprefix("10.48550/arxiv."))
            if arxiv:
                identities.add(("arxiv", arxiv))
    return identities


def _targets(provider, records):
    targets, already_returned = set(), set()
    for record in records:
        ids = _identities(record)
        if record.provenance.provider == provider:
            # Related DOI evidence does not mean that related record was fetched.
            already_returned.update(strong_identifiers(record.external_ids))
        for namespace in LOOKUP_NAMESPACES[provider]:
            keys = {key for key in ids if key[0] == namespace}
            if keys:
                targets.update(keys)
                break
    return sorted(targets - already_returned)


def complete_metadata(
    records: Sequence[ProviderWorkEvidence], enabled_providers: Sequence[str], *,
    clients: Mapping[str, MetadataLookup], cancel_event: Event | None = None,
) -> CompletionResult:
    """Reuse responses, then look up selected providers by known identity only.

    Follow reliable linked identities until no unqueried targets remain. Each
    provider/namespace/identifier is attempted once, including failed lookups.
    """
    output = sorted(records, key=lambda r: (r.provenance.provider, r.provenance.record_id))
    issues = []
    attempted = set()
    seen = {(r.provenance.provider, r.provenance.record_id) for r in output}
    while True:
        previous_attempts = len(attempted)
        for provider in COMPLETION_ORDER:
            if provider not in enabled_providers:
                continue
            for namespace, identifier in _targets(provider, output):
                if cancel_event is not None and cancel_event.is_set():
                    return CompletionResult(tuple(output), tuple(issues))
                request = provider, namespace, identifier
                if request in attempted:
                    continue
                attempted.add(request)
                client = clients.get(provider)
                if client is None:
                    issues.append(CompletionIssue(provider, identifier, "Selected metadata adapter is unavailable"))
                    continue
                try:
                    supplements = client.lookup(namespace, identifier)
                    for record in supplements:
                        if (namespace, identifier) not in _identities(record):
                            issues.append(CompletionIssue(provider, identifier, "Metadata response does not match requested identity"))
                            continue
                        key = provider, record.provenance.record_id
                        if key in seen:
                            continue
                        source = record.provenance.model_copy(update={"provider": provider, "role": "supplement"})
                        output.append(record.model_copy(update={"provenance": source}))
                        seen.add(key)
                except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                    # Provider clients emit credential-free diagnostics. A failed
                    # supplement never invalidates an independently legal hit.
                    issues.append(CompletionIssue(provider, identifier, str(error)))
        if len(attempted) == previous_attempts:
            break
    return CompletionResult(tuple(output), tuple(issues))
