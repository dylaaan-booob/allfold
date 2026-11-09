"""Save only native preprint evidence on the selected formal Paper."""
from allfold.application.paper_enrichment import _commit_fields, set_managed_value
from allfold.identifiers import normalize_external_id, valid_doi
from allfold.models import EvidenceDateKind, MetadataSource, ProviderRecordRef, ProviderWorkEvidence, WorkflowStatus
from allfold.paper_dates import (
    collect_dates, first_public_date, known_preprint_families, merge_dates, preprint_identity, preprint_query_refs,
)
from allfold.persistence.markdown_state import parse_paper_state
from allfold.persistence.safe_write import TextWriteCommittedError


PREPRINT_SERVERS = ('biorxiv', 'medrxiv')


def formal_lookup_doi(doi, publication_type, journal, conference):
    if publication_type in {'journal', 'conference'} or publication_type is None and (journal or conference):
        return valid_doi(doi)
    return None


def require_lookup_doi(target):
    state = parse_paper_state(target.path, target.original)
    if state.status is WorkflowStatus.REJECTED:
        raise ValueError('Rejected Paper is excluded from preprint lookup')
    doi = formal_lookup_doi(target.doi, state.publication_type, state.journal, state.conference)
    if not doi:
        raise ValueError('A valid formal publication DOI is required for preprint lookup')
    return doi


def _first_public(state, records, native_dates):
    # Only a complete native v1 returned in this operation establishes new
    # proof. Every known family must be resolved before selecting an earliest.
    proof = tuple(item for item in native_dates if not item.first_version or item.day is not None)
    if state.first_public_at or not first_public_date(proof, records=records):
        return None

    refs = list(preprint_query_refs(state.date_evidence))
    for source in state.sources:
        if source.provider in PREPRINT_SERVERS and source.record_id.endswith(':publication'):
            if doi := normalize_external_id('doi', source.record_id.removesuffix(':publication')):
                refs.append(ProviderRecordRef(provider=source.provider, record_id=doi, relation='preprint'))
    existing = ProviderWorkEvidence(provenance=MetadataSource(
        provider='workspace', record_id=str(state.paper_id), retrieved_at=state.discovered_at),
        related_ids=tuple(refs), dates=state.date_evidence)
    all_records = (existing, *records)
    families = known_preprint_families(all_records)
    all_dates = list(native_dates)
    for item in state.date_evidence:
        if item.kind != EvidenceDateKind.PREPRINT:
            continue
        family = families.get(item.version_family)
        if family is None:
            family = next((families[key] for ref in preprint_query_refs((item,))
                           if (key := preprint_identity(ref.provider, ref.record_id)) in families), None)
        if family:
            all_dates.append(item.model_copy(update={'version_family': family}))
    return first_public_date(all_dates, records=all_records)


def save_preprint_evidence(target, records, *, operation_lock):
    state = parse_paper_state(target.path, target.original)
    native_dates = tuple(item for item in collect_dates(records) if item.kind is EvidenceDateKind.PREPRINT)
    dates = merge_dates(state.date_evidence, native_dates)
    first_public = _first_public(state, records, native_dates)

    contents, fields = target.original, []
    if first_public:
        contents = set_managed_value(contents, 'first_public_at', first_public)
        fields.append('first_public_at')
    if native_dates and dates != state.date_evidence:
        contents = set_managed_value(contents, 'date_evidence', [item.model_dump(mode='json', exclude_none=True) for item in dates])
        fields.append('date_evidence')

    sources = list(state.sources)
    keys = {(s.provider, s.record_id, s.version, s.url, s.note) for s in sources}
    for record in records:
        source = record.provenance
        key = source.provider, source.record_id, source.version, source.url, source.note
        if key not in keys:
            sources.append(source)
            keys.add(key)
    if tuple(sources) != state.sources:
        contents = set_managed_value(contents, 'sources', [source.model_dump(mode='json', exclude_none=True) for source in sources])
        fields.append('sources')

    if fields:
        try:
            _commit_fields(target, contents, operation_lock=operation_lock)
        except TextWriteCommittedError as error:
            error.saved_fields = fields
            raise
    return fields
