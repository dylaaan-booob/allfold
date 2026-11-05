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


def test_doi_url_spellings_share_one_identity(tmp_path):
    spellings = ("10.5555/Example", "HTTPS://DOI.ORG/10.5555/EXAMPLE",
                 "http://dx.doi.org/10.5555/example", "doi:10.5555/Example")
    records = [evidence('crossref', str(i), title='Title', journal='Journal',
                        external_ids=ExternalIds(doi=value)) for i, value in enumerate(spellings)]
    papers = canonicalize_records(records).papers
    assert len(papers) == 1 and papers[0].doi == '10.5555/example'
    first = materialize_papers(papers, tmp_path)
    assert len(first.created_papers) == 1
    for record in records:
        repeated = materialize_papers(canonicalize_records([record]).papers, tmp_path)
        assert repeated.existing_papers == first.created_papers and not repeated.created_papers


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


def test_workspace_api_exposes_conference_and_date_provenance(tmp_path):
    from fastapi.testclient import TestClient
    from test_web_app import write_valid_config
    from electron_test_helpers import OfflineBridge
    from allfold.web.app import create_app
    from allfold.models import EvidenceDate, EvidenceDateKind as Kind, ProviderTopic
    config, workspace = write_valid_config(tmp_path)
    paper, = canonicalize_records([evidence(title='Conference item', conference='NeurIPS',
        conference_id='conf_example', publication_type='conference', publication_date='2026',
        external_ids=ExternalIds(dblp='conf/nips/Test'),
        indexed_terms=(ProviderTopic(value='machine learning', source='dblp', kind='topic'),),
        dates=(EvidenceDate(kind=Kind.CONFERENCE_YEAR, year=2026),))]).papers
    materialize_papers([paper], workspace)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        data = client.get('/api/ui-next/workspace').json()
    group, = data['subjects']
    venue, = group['journals']
    assert venue['name'] == 'NeurIPS'
    assert venue['source_type'] == 'conference'
    item, = venue['papers']
    assert item['doi'] is None and item['conference'] == 'NeurIPS'
    assert item['first_public_at'] is None and item['accepted_at'] is None
    assert item['date_evidence'][0]['kind'] == 'conference-year'
    assert item['indexed_terms'][0]['kind'] == 'topic'
    assert item['external_ids']['dblp'] == 'conf/nips/Test'


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
    paper, = canonicalize_records(records).papers
    assert paper.metadata.first_public_at == '2021-05'
    assert paper.metadata.accepted_at == '2021-05'
    assert paper.metadata.accepted_approximate
    assert not any(item.year == 2000 for item in paper.date_evidence)


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


def test_identity_scan_rejects_unreadable_known_ids_and_reads_legacy_aliases(tmp_path):
    from allfold.persistence.markdown_state import parse_paper_identity
    from allfold.persistence.materialize import render_paper_markdown
    paper, = canonicalize_records([evidence('crossref', 'formal', title='Title', journal='Journal',
        external_ids=ExternalIds(doi='10.5555/one', openalex='W17'))]).papers
    text = render_paper_markdown(paper)
    broken = text.replace('  openalex: W17', '  openalex: [W17, W18]')
    identity = parse_paper_identity(tmp_path/'paper.md', broken)
    assert not identity.index_complete
    # Older hand-managed notes may carry the top-level ID without external_ids.
    legacy = '---\ntype: paper\nid: '+str(paper.id)+'\ndoi: 10.5555/one\nopenalex_id: https://openalex.org/W17\n---\n'
    identity = parse_paper_identity(tmp_path/'old.md', legacy)
    assert ('openalex', 'W17') in identity.identifiers


def test_import_plan_uses_only_primary_doi_and_excludes_unsupported_targets(tmp_path):
    from allfold.application.decisions import keep_paper
    from allfold.application.workspace import plan_workspace_import
    from allfold.persistence.safe_write import workspace_operation_lock
    from allfold.models import WorkflowStatus
    records = [evidence(record='free', title='DOI-free', external_ids=ExternalIds(dblp='conf/c/free')),
               evidence('arxiv', '2601.00001', title='Preprint', publication_type='preprint',
                        external_ids=ExternalIds(doi='10.5555/preprint-only')),
               evidence('crossref', 'formal', title='Formal', journal='Journal', publication_type='journal',
                        external_ids=ExternalIds(doi='10.5555/formal'), related_dois=('10.5555/related',))]
    papers = canonicalize_records(records).papers
    materialize_papers(papers, tmp_path)
    for paper in papers:
        keep_paper(tmp_path, paper.id, WorkflowStatus.CANDIDATE)
    with workspace_operation_lock(tmp_path) as lock:
        plan = plan_workspace_import(lock)
    assert [paper.doi for paper in plan.papers] == ['10.5555/formal']
    assert any('primary DOI' in reason.reason for reason in plan.exclusions)
    assert any('Preprint' in reason.reason for reason in plan.exclusions)


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
