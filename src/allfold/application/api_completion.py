"""Build evidence from saved Papers and apply a narrow, exact-revision update."""
from allfold.application.paper_enrichment import fill_abstract, fill_authors, fill_publication_date, _commit_fields, set_managed_value
from allfold.canonicalize import canonicalize_records
from allfold.models import Author, MetadataSource, ProviderWorkEvidence, WorkflowStatus
from allfold.paper_dates import merge_dates
from allfold.persistence.markdown_state import parse_paper_state


def saved_paper_evidence(target):
    state = parse_paper_state(target.path, target.original)
    return ProviderWorkEvidence(
        provenance=MetadataSource(provider='workspace', record_id=str(state.paper_id), retrieved_at=state.discovered_at, role='discovery'),
        title=state.title, journal=state.journal, conference=state.conference, conference_id=state.conference_id,
        publication_type=state.publication_type or ('journal' if state.journal else None),
        publication_date=state.publication_date, abstract=state.abstract, authors=tuple(Author(name=name) for name in state.authors),
        external_ids=state.external_ids, related_dois=state.related_dois,
        dates=state.date_evidence, monitor_journal_issns=state.journal_issns)




def save_api_completion(target, records, *, operation_lock):
    state = parse_paper_state(target.path, target.original)
    if state.status is WorkflowStatus.REJECTED:
        raise ValueError('Rejected Paper is excluded from API completion')
    if not any(record.provenance.provider != 'workspace' for record in records):
        return []
    canonical = canonicalize_records(records)
    if len(canonical.papers) != 1:
        raise ValueError('Completion evidence does not identify one research work')
    paper = canonical.papers[0]
    contents, fields = target.original, []
    if not state.abstract and paper.metadata.abstract:
        contents = fill_abstract(contents, paper.metadata.abstract)
        fields.append('abstract')
    if not state.authors and paper.authors:
        contents = fill_authors(contents, [author.name for author in paper.authors])
        fields.append('authors')
    if state.publication_date is None and paper.metadata.publication_date:
        contents = fill_publication_date(contents, paper.metadata.publication_date)
        fields.append('publication_date')
    for field in ('first_public_at', 'journal', 'conference', 'conference_id', 'publication_type', 'author_keywords'):
        if not getattr(state, field) and (value := getattr(paper.metadata, field)):
            contents = set_managed_value(contents, field, value)
            fields.append(field)
    dates = merge_dates(state.date_evidence, paper.date_evidence)
    if dates != state.date_evidence:
        contents = set_managed_value(contents, 'date_evidence', [item.model_dump(mode='json', exclude_none=True) for item in dates])
        fields.append('date_evidence')
    sources = list(state.sources)
    keys = {(s.provider, s.record_id, s.version, s.url) for s in sources}
    for source in paper.sources:
        key = source.provider, source.record_id, source.version, source.url
        if source.provider != 'workspace' and key not in keys:
            sources.append(source)
            keys.add(key)
    if tuple(sources) != state.sources:
        contents = set_managed_value(contents, 'sources', [source.model_dump(mode='json', exclude_none=True) for source in sources])
        fields.append('sources')
    if contents != target.original:
        _commit_fields(target, contents, operation_lock=operation_lock)
    return fields
