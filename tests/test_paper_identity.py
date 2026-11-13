"""Canonical identity and native Preprint semantics retained after SQLite adoption."""
from datetime import datetime, timezone
import pytest

from allfold.canonicalize import canonicalize_records, completion_metadata
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence


def evidence(provider='openalex', record='W1000', **values):
    return ProviderWorkEvidence(provenance=MetadataSource(provider=provider, record_id=record,
        retrieved_at=datetime(2026, 11, 5, tzinfo=timezone.utc)), **values)


def test_primary_formal_record_and_dates_are_independent_of_arrival_order():
    from allfold.models import EvidenceDate, EvidenceDateKind as Kind, Author, ProviderTopic
    preprint = evidence('arxiv', '2201.00001', title='Preprint title', publication_type='preprint',
                        external_ids=ExternalIds(doi='10.5555/preprint', arxiv='2201.00001'),
                        related_dois=('10.5555/formal',),
                        authors=(Author(name='Preprint author'),),
                        dates=(EvidenceDate(kind=Kind.PREPRINT, year=2022, month=1, first_version=True),))
    formal = evidence('crossref', '10.5555/formal', title='Formal title', journal='Journal',
                      monitor_journal_issns=('1234-5678',), publication_date='2026-03',
                      external_ids=ExternalIds(doi='10.5555/formal'),
                      authors=(Author(name='Formal author'),),
                      dates=(EvidenceDate(kind=Kind.ACCEPTED, year=2021, month=12),
                             EvidenceDate(kind=Kind.PUBLISHED_ONLINE, year=2026, month=2, day=3)),
                      indexed_terms=(ProviderTopic(value='statistics', source='openalex', kind='topic'),))
    for records in ([preprint, formal], [formal, preprint]):
        assert len(canonicalize_records(records).papers) == 2
        paper = completion_metadata(records)
        assert paper.doi == '10.5555/formal'
        assert paper.metadata.title == 'Formal title'
        assert [a.name for a in paper.authors] == ['Formal author']
        assert paper.metadata.publication_date == '2026-03'
        assert paper.metadata.first_public_at == '2022-01'
        assert any(d.kind==Kind.ACCEPTED and d.year==2021 and d.month==12 for d in paper.date_evidence)
        assert paper.indexed_terms[0].kind == 'topic'
        assert {d.provider for d in paper.date_evidence} == {'arxiv', 'crossref'}


def test_date_inference_uses_public_versions_and_formal_acceptance_only():
    from allfold.models import EvidenceDate, EvidenceDateKind as Kind
    records = [evidence('openalex', 'W17', title='Title', journal='Journal', publication_date='2000-01-01',
                        external_ids=ExternalIds(doi='10.5555/date', openalex='W17')),
               evidence('crossref', 'formal', title='Title', journal='Journal',
                        external_ids=ExternalIds(doi='10.5555/date'),
                        dates=(EvidenceDate(kind=Kind.PUBLISHED_ONLINE, year=2021, month=5),)),
               evidence('biorxiv', 'preprint', title='Title', publication_type='preprint',
                        external_ids=ExternalIds(doi='10.5555/preprint'), related_dois=('10.5555/date',),
                        dates=(EvidenceDate(kind=Kind.ACCEPTED, year=2020), EvidenceDate(kind=Kind.PREPRINT, year=2022)))]
    paper = completion_metadata(records)
    assert paper.metadata.first_public_at is None  # a later preprint version does not establish its first public date
    assert any(item.kind==Kind.PUBLISHED_ONLINE and item.year==2021 for item in paper.date_evidence)
    assert any(item.year==2000 and item.kind==Kind.PUBLISHED for item in paper.date_evidence)


@pytest.mark.parametrize('year,month,first,expected', [(2020, None, True, '2020'), (2020, 2, True, '2020-02'),
    (2020, 2, False, None), (2099, 1, True, None)])
def test_first_public_requires_established_nonfuture_preprint_date(year, month, first, expected):
    from allfold.models import EvidenceDate, EvidenceDateKind as Kind
    formal = evidence('crossref', 'formal', title='Formal', journal='Journal', publication_type='journal',
        external_ids=ExternalIds(doi='10.5555/formal'), related_dois=('10.5555/preprint',),
        dates=(EvidenceDate(kind=Kind.ACCEPTED, year=2018), EvidenceDate(kind=Kind.PUBLISHED_ONLINE, year=2019)))
    preprint = evidence('arxiv', '2002.12345', title='Preprint', publication_type='preprint',
        external_ids=ExternalIds(doi='10.5555/preprint', arxiv='2002.12345'),
        dates=(EvidenceDate(kind=Kind.PREPRINT, year=year, month=month, first_version=first),))
    paper = completion_metadata((formal, preprint))
    assert paper.metadata.first_public_at == expected and paper.doi == '10.5555/formal'


def test_known_related_preprint_doi_without_date_does_not_supply_first_public():
    paper, = canonicalize_records((evidence('crossref', 'formal', title='Formal', journal='Journal',
        external_ids=ExternalIds(doi='10.5555/formal'), related_dois=('10.5555/preprint',), publication_date='2026-01'),)).papers
    assert paper.metadata.first_public_at is None


def test_wos_without_doi_uses_ut_and_create_only_shared_identity(tmp_path):
    from allfold.application.wos import persist_wos
    from allfold.persistence.safe_write import workspace_operation_lock
    from allfold.providers.wos import record_paper, WoSRecords
    from allfold.config import JournalConfig
    journal = JournalConfig(name='Journal', issn='0006-341X')
    raw = {'TI': ['No DOI WoS paper'], 'UT': ['WOS:12345'], 'PY': ['2026'], 'DE': ['author keyword'], 'ID': ['indexed term']}
    paper = record_paper(raw, journal)
    assert paper.doi is None
    assert paper.external_ids.wos == 'WOS:12345'
    assert paper.metadata.author_keywords == ('author keyword',)
    assert paper.indexed_terms[0].kind == 'Keywords Plus'
    union = WoSRecords()
    union.add(paper)
    other = record_paper({**raw, 'UT': ['WOS:67890']}, journal)
    union.add(other)
    assert len(union.papers) == 2
    with workspace_operation_lock(tmp_path, create=True) as lock:
        first = persist_wos(list(union.papers.values()), lock, check_current=lambda:None, cancelled=lambda:False)
        second = persist_wos([paper], lock, check_current=lambda:None, cancelled=lambda:False)
    assert first.created_papers == 2
    assert second.skipped_existing_papers == 1 and second.created_papers == 0


def test_duplicate_snapshot_metadata_is_independent_of_retrieval_time():
    from datetime import timedelta
    first = evidence('europe_pmc', 'MED:123', title='A fixed title',
                     external_ids=ExternalIds(europe_pmc='MED:123'))
    second = first.model_copy(update={'title': 'Z other title', 'abstract': 'More complete'})
    for records in ([first, second.model_copy(update={'provenance': second.provenance.model_copy(update={'retrieved_at': second.provenance.retrieved_at+timedelta(days=1)})})],
                    [first.model_copy(update={'provenance': first.provenance.model_copy(update={'retrieved_at': first.provenance.retrieved_at+timedelta(days=1)})}), second]):
        paper, = canonicalize_records(records).papers
        # Fixed snapshot payload ordering makes either retrieval timestamp immaterial.
        assert paper.metadata.title == 'Z other title'


def test_duplicate_provider_snapshots_fill_missing_fields_without_overwriting():
    discovery = evidence('europe_pmc', 'MED:123', title='Discovery title',
                         external_ids=ExternalIds(europe_pmc='MED:123'))
    supplement = evidence('europe_pmc', 'MED:123', abstract='Retrieved abstract',
                          external_ids=ExternalIds(europe_pmc='MED:123'))
    supplement = supplement.model_copy(update={'provenance': supplement.provenance.model_copy(update={'role': 'supplement'})})
    for records in ([discovery, supplement], [supplement, discovery]):
        paper, = canonicalize_records(records).papers
        assert paper.metadata.title == 'Discovery title'
        assert paper.metadata.abstract == 'Retrieved abstract'
        assert len(paper.sources) == 1


def test_formal_published_date_never_falls_back_to_linked_preprint_date():
    from allfold.models import EvidenceDate, EvidenceDateKind
    formal = ProviderWorkEvidence(provenance=MetadataSource(provider='crossref',record_id='10.5555/formal',
        retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc)),external_ids=ExternalIds(doi='10.5555/formal'),
        title='Formal',journal='Journal',publication_type='journal',
        dates=(EvidenceDate(kind=EvidenceDateKind.PUBLISHED_ONLINE,year=2026,month=1),))
    preprint = ProviderWorkEvidence(provenance=MetadataSource(provider='arxiv',record_id='2201.12345',
        retrieved_at=datetime(2026,1,1,tzinfo=timezone.utc)),external_ids=ExternalIds(arxiv='2201.12345'),
        related_dois=('10.5555/formal',),title='Preprint',publication_type='preprint',publication_date='2022-01-02',
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,month=1,day=2,first_version=True),))
    paper=completion_metadata((formal,preprint))
    assert paper.metadata.publication_date is None
    assert paper.metadata.first_public_at == '2022-01-02'


@pytest.mark.parametrize('ids', [
    {'dblp': 'conf/example/old'},
    {'openalex': 'W123', 'dblp': 'conf/example/old'},
    {'doi': '10.5555/formal', ' DBLP ': 'conf/example/old'},
])
def test_retired_namespace_cannot_create_a_new_paper_even_with_valid_ids(ids):
    with pytest.raises(ValueError, match='Retired external identifier namespace'):
        ExternalIds.model_validate(ids)
