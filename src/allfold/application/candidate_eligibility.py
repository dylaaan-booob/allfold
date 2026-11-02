"""Journal attribution for one Provider's DOI-first candidates."""
from collections import defaultdict
from collections.abc import Sequence

from allfold.config import JournalConfig
from allfold.identifiers import valid_doi
from allfold.models import ProviderWorkEvidence
from allfold.providers.openalex import DiscoveryResult


def openalex_attribution(openalex: DiscoveryResult, journals: Sequence[JournalConfig]) -> dict[str, tuple[str, ...]]:
    configured = {journal.key for journal in journals}
    sources = defaultdict(set)
    for source in openalex.sources:
        if source.journal_key in configured:
            sources[source.openalex_id].add(source.journal_key)
    attribution = defaultdict(set)
    for record in openalex.records:
        doi = valid_doi(record.external_ids.doi)
        if doi and len(sources[record.source_id]) == 1:
            attribution[doi].update(sources[record.source_id])
    return {doi: tuple(sorted(issns)) for doi, issns in attribution.items()}


def filter_candidate_evidence(
    records: Sequence[ProviderWorkEvidence], attribution: dict[str, tuple[str, ...]],
    journals: Sequence[JournalConfig],
) -> tuple[ProviderWorkEvidence, ...]:
    evidence = []
    for item in records:
        known = attribution.get(item.external_ids.doi, ())
        if not known:
            continue
        # Settings owns display names; all reliable matched Journal keys survive.
        journal = next(journal.name for journal in journals if journal.key in known)
        evidence.append(item.model_copy(update={
            "journal": journal,
            "monitor_journal_issns": tuple(sorted(known)),
        }))
    return tuple(evidence)
