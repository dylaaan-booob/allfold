from datetime import datetime, timezone

from allfold.canonicalize import canonicalize_records
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.persistence.materialize import materialize_papers
from allfold.application.workspace import load_workspace


def evidence(provider='dblp', record='conf/nips/Example26', **values):
    return ProviderWorkEvidence(provenance=MetadataSource(provider=provider, record_id=record,
        retrieved_at=datetime(2026, 11, 5, tzinfo=timezone.utc)), **values)


def test_doi_free_conference_round_trip_and_saved_bytes_are_immutable(tmp_path):
    source = evidence(title='A conference paper', conference='NeurIPS', conference_id='neurips',
                      external_ids=ExternalIds(dblp='conf/nips/Example26'), publication_date='2026')
    result = canonicalize_records([source])
    assert len(result.papers) == 1
    paper = result.papers[0]
    assert paper.external_ids.doi is None
    assert paper.metadata.journal is None
    assert paper.metadata.conference == 'NeurIPS'
    first = materialize_papers(result.papers, tmp_path)
    assert not first.issues
    path = first.created_papers[0]
    before = path.read_bytes()
    snapshot = load_workspace(tmp_path)
    assert not snapshot.issues
    assert snapshot.papers[0].conference == 'NeurIPS'
    later = canonicalize_records([source.model_copy(update={'title': 'Changed title'})])
    second = materialize_papers(later.papers, tmp_path)
    assert second.existing_papers == (path,)
    assert not second.created_papers
    assert path.read_bytes() == before


def test_primary_formal_record_and_dates_are_independent_of_arrival_order():
    from allfold.models import EvidenceDate, EvidenceDateKind as Kind, Author, ProviderTopic
    preprint = evidence('arxiv', '2201.00001', title='Preprint title', publication_type='preprint',
                        external_ids=ExternalIds(doi='10.5555/preprint', arxiv='2201.00001'),
                        related_dois=('10.5555/formal',),
                        authors=(Author(name='Preprint author'),),
                        dates=(EvidenceDate(kind=Kind.PREPRINT, year=2022, month=1),))
    formal = evidence('crossref', '10.5555/formal', title='Formal title', journal='Journal',
                      monitor_journal_issns=('1234-5678',), publication_date='2026-03',
                      external_ids=ExternalIds(doi='10.5555/formal'),
                      authors=(Author(name='Formal author'),),
                      dates=(EvidenceDate(kind=Kind.ACCEPTED, year=2021, month=12),
                             EvidenceDate(kind=Kind.PUBLISHED_ONLINE, year=2026, month=2, day=3)),
                      indexed_terms=(ProviderTopic(value='62G05', source='zbmath', kind='MSC'),))
    for records in ([preprint, formal], [formal, preprint]):
        paper, = canonicalize_records(records).papers
        assert paper.doi == '10.5555/formal'
        assert paper.related_dois == ('10.5555/preprint',)
        assert paper.metadata.title == 'Formal title'
        assert [a.name for a in paper.authors] == ['Formal author']
        assert paper.metadata.publication_date == '2026-03'
        assert paper.metadata.first_public_at == '2022-01'
        assert paper.metadata.accepted_at == '2021-12'
        assert not paper.metadata.accepted_approximate
        assert paper.indexed_terms[0].kind == 'MSC'
        assert {d.provider for d in paper.date_evidence} == {'arxiv', 'crossref'}


def test_doi_free_paper_local_edit_and_primary_doi_enrichment(tmp_path):
    import pytest
    from allfold.application.paper_enrichment import paper_fields, edit_paper_fields, read_enrichment_target
    source = evidence(title='No DOI', conference='NeurIPS', external_ids=ExternalIds(dblp='conf/nips/Test'))
    paper, = canonicalize_records([source]).papers
    path, = materialize_papers([paper], tmp_path).created_papers
    fields = paper_fields(tmp_path, paper.id)
    edit_paper_fields(tmp_path, paper.id, fields['revision'], abstract='Human abstract')
    assert 'Human abstract' in path.read_text()
    with pytest.raises(ValueError, match='primary DOI'):
        read_enrichment_target(tmp_path, paper.id)
    multi, = canonicalize_records([evidence('crossref', 'formal', title='Formal', journal='Journal',
                external_ids=ExternalIds(doi='10.5555/formal'), related_dois=('10.5555/preprint',))]).papers
    materialize_papers([multi], tmp_path)
    target = read_enrichment_target(tmp_path, multi.id)
    assert target.doi == '10.5555/formal'


def test_shared_work_ids_merge_but_titles_and_unknown_ids_never_do(tmp_path):
    from allfold.persistence.materialize import read_workspace_identities
    from allfold.persistence.safe_write import workspace_operation_lock
    records = [evidence('openalex', 'A', title='Same title', journal='Journal', external_ids=ExternalIds(doi='10.5555/a', openalex='W123')),
               evidence('crossref', 'B', title='Same title', journal='Journal', external_ids=ExternalIds(doi='10.5555/b', openalex='https://openalex.org/W123')),
               evidence('dblp', 'C', title='Same title', conference='Conference', external_ids=ExternalIds(dblp='conf/c/C')),
               evidence('dblp', 'D', title='Same title', conference='Conference', external_ids=ExternalIds(dblp='conf/c/D'))]
    papers = canonicalize_records(records).papers
    assert len(papers) == 3
    assert not canonicalize_records([evidence(title='Title', external_ids=ExternalIds(unknown='same'))]).papers
    result = materialize_papers(papers, tmp_path)
    assert len(result.created_papers) == 3
    with workspace_operation_lock(tmp_path) as lock:
        index = read_workspace_identities(lock)
    assert ('dblp', 'conf/c/C') in index.by_identifier
    assert {'10.5555/a', '10.5555/b'} <= index.saved.keys()
    ambiguous, = canonicalize_records([evidence(title='Bridge', external_ids=ExternalIds(dblp='conf/c/C', openalex='W123'))]).papers
    before = {path: path.read_bytes() for path in result.created_papers}
    blocked = materialize_papers([ambiguous], tmp_path)
    assert blocked.has_errors and not blocked.created_papers and not blocked.existing_papers
    assert {path: path.read_bytes() for path in result.created_papers} == before


def test_cancellation_reports_committed_count_and_stops_next_write(tmp_path):
    from threading import Event
    cancel = Event()
    papers = canonicalize_records([evidence(record=str(i), title=f'Title {i}', external_ids=ExternalIds(dblp=f'conf/c/{i}'))
                                   for i in range(3)]).papers
    def progress(event):
        if event.activity and event.activity.operation == 'materialize_write' and event.activity.current == 1:
            cancel.set()
    result = materialize_papers(papers, tmp_path, cancel_event=cancel, progress_callback=progress)
    assert len(result.created_papers) == 1
    assert len(list((tmp_path / 'Papers').glob('*.md'))) == 1
    assert any('cancelled' in issue.message for issue in result.issues)


def test_related_strong_ids_survive_canonicalization_and_repeated_run(tmp_path):
    first = evidence('dblp', 'conf/c/First', title='Title', conference='Conference',
                     external_ids=ExternalIds(doi='10.5555/shared', dblp='conf/c/First'))
    second = evidence('dblp', 'conf/c/Second', title='Title', conference='Conference',
                      external_ids=ExternalIds(doi='10.5555/shared', dblp='conf/c/Second'))
    paper, = canonicalize_records([first, second]).papers
    created = materialize_papers([paper], tmp_path)
    repeat, = canonicalize_records([second.model_copy(update={'external_ids': ExternalIds(dblp='conf/c/Second')})]).papers
    result = materialize_papers([repeat], tmp_path)
    assert result.existing_papers == created.created_papers
    assert not result.created_papers
