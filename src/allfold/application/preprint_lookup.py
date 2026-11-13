"""Save only native preprint evidence on the selected formal Paper."""
from allfold.identifiers import normalize_external_id, valid_doi
from allfold.models import EvidenceDateKind, MetadataSource, ProviderRecordRef, ProviderWorkEvidence
from allfold.paper_dates import (
    collect_dates, first_public_date, known_preprint_families, merge_dates, preprint_identity, preprint_query_refs,
)
from allfold.persistence.library_models import MetadataDelta


PREPRINT_SERVERS = ('biorxiv', 'medrxiv')


def formal_lookup_doi(doi, publication_type, journal, conference):
    if publication_type in {'journal', 'conference'} or publication_type is None and (journal or conference):
        return valid_doi(doi)
    return None


def require_lookup_doi(paper):
    if paper.excluded or paper.metadata is None:
        raise ValueError('Preprint lookup requires active, complete Paper metadata')
    identity = paper.primary_identity
    doi = identity.value if identity and identity.namespace == 'doi' else None
    metadata = paper.metadata
    doi = formal_lookup_doi(doi, metadata.publication_type, metadata.journal, metadata.conference)
    if not doi:
        raise ValueError('A valid formal publication DOI is required for preprint lookup')
    return doi


def _first_public(state, records, native_dates):
    # Only a complete native v1 returned in this operation establishes new
    # proof. Every known family must be resolved before selecting an earliest.
    proof = tuple(item for item in native_dates if not item.first_version or item.day is not None)
    if state.first_public_at or not first_public_date(proof, records=records):
        return None

    refs = [*state.preprint_relations, *preprint_query_refs(state.preprint_evidence)]
    for source in state.sources:
        if source.provider in PREPRINT_SERVERS and source.record_id.endswith(':publication'):
            if doi := normalize_external_id('doi', source.record_id.removesuffix(':publication')):
                refs.append(ProviderRecordRef(provider=source.provider, record_id=doi, relation='preprint'))
    existing = ProviderWorkEvidence(provenance=MetadataSource(
        provider='workspace', record_id='saved-preprint-proof', retrieved_at=records[0].provenance.retrieved_at),
        related_ids=tuple(refs), dates=state.preprint_evidence)
    all_records = (existing, *records)
    families = known_preprint_families(all_records)
    all_dates = list(native_dates)
    for item in state.preprint_evidence:
        if item.kind != EvidenceDateKind.PREPRINT:
            continue
        family = families.get(item.version_family)
        if family is None:
            family = next((families[key] for ref in preprint_query_refs((item,))
                           if (key := preprint_identity(ref.provider, ref.record_id)) in families), None)
        if family:
            all_dates.append(item.model_copy(update={'version_family': family}))
    return first_public_date(all_dates, records=all_records)


def save_preprint_evidence(repository, paper, records):
    """Merge proof incrementally using the token captured before any request."""
    state = paper.metadata
    native_dates = tuple(item for item in collect_dates(records) if item.kind is EvidenceDateKind.PREPRINT)
    first_public = _first_public(state, records, native_dates)
    relations = tuple(ref for record in records for ref in record.related_ids if ref.relation == 'preprint')
    def source_key(source):
        return source.provider, source.record_id, source.version, source.url, source.note
    known_sources = {source_key(source) for source in state.sources}
    sources = tuple(record.provenance for record in records if source_key(record.provenance) not in known_sources)
    delta = MetadataDelta(preprint_evidence=native_dates, preprint_relations=relations,
                          first_public_at=first_public, sources=sources)
    result = repository.merge_metadata(paper.token, delta)
    fields = [name for name in ('preprint_evidence', 'preprint_relations', 'first_public_at', 'sources')
              if getattr(result.metadata, name) != getattr(state, name)]
    return result, fields
