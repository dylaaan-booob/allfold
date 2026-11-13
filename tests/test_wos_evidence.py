"""Synthetic WoS source facts survive canonicalization and durable reuse."""
from datetime import datetime, timezone

from allfold.config import JournalConfig
from allfold.providers import wos


def test_wos_preserves_source_fields_and_distinct_formal_and_online_dates():
    raw = {key: [value] for key, value in {
        'PT': 'J', 'UT': 'WOS:123', 'DI': '10.1234/example', 'PM': '12345',
        'TI': 'Source title', 'SO': 'Actual source journal', 'SN': '0006-341X', 'EI': '1541-0420',
        'DT': 'Article; Early Access', 'AB': 'Source abstract', 'DE': 'one; two', 'ID': 'indexed one',
        'PD': 'JAN 1', 'PY': '2027', 'EA': 'SEP', 'EY': '2026',
        'VL': '8', 'IS': '2', 'BP': '10', 'EP': '19', 'AR': 'e123',
    }.items()}
    raw['AF'] = ['Second, Ada', 'First, Ben']
    raw['AU'] = ['Second A', 'First B']
    evidence = wos.record_evidence(raw, JournalConfig(name='Saved label', issn='0006-341X'))
    assert evidence.journal == 'Actual source journal'
    assert evidence.external_ids.pmid == '12345'
    assert [author.name for author in evidence.authors] == ['Second, Ada', 'First, Ben']
    assert evidence.document_types == ('Article', 'Early Access')
    assert evidence.publication_date == '2027-01-01'
    assert [(item.kind.value, item.year, item.month, item.day, item.source_label) for item in evidence.dates] == [
        ('published', 2027, 1, 1, 'PD/PY'), ('published-online', 2026, 9, None, 'EA/EY')]
    assert evidence.journal_issns == ('0006-341X', '1541-0420')
    assert (evidence.volume, evidence.issue, evidence.pages, evidence.article_number) == ('8', '2', '10-19', 'e123')
    assert evidence.author_keywords == ('one', 'two')
    assert [term.value for term in evidence.indexed_terms] == ['indexed one']
    fields = {field.tag: field for field in evidence.source_fields}
    assert fields['EA'].values == ('SEP',) and fields['EA'].status == 'valid'
    assert fields['GA'].status == 'unselected'


def test_optional_invalid_doi_preserves_ut_and_field_status_without_text_identity():
    import pytest
    evidence = wos.record_evidence({'UT': ['WOS:9'], 'DI': ['not a DOI'], 'TI': ['Title']},
                                   selected_fields={'UT', 'DI', 'TI', 'PM'})
    fields = {field.tag: field for field in evidence.source_fields}
    assert evidence.external_ids.doi is None and evidence.external_ids.wos == 'WOS:9'
    assert fields['DI'].status == 'parse-invalid'
    assert fields['PM'].status == 'absent'
    assert fields['AB'].status == 'unselected'
    with pytest.raises(ValueError, match='missing_identity'):
        wos.record_evidence({'GA': ['WOS:9'], 'AB': ['doi:10.1234/fake'], 'TI': ['12345']})
    pmid = wos.record_evidence({'PM': ['12345'], 'TI': ['Title']})
    assert pmid.external_ids.pmid == '12345'


def test_formal_wos_ordinary_values_win_deterministically_and_authors_stay_whole():
    from allfold.canonicalize import canonicalize_records
    from allfold.models import Author, ExternalIds, MetadataSource, ProviderWorkEvidence
    record = wos.record_evidence({'UT': ['WOS:9'], 'DI': ['10.1234/formal'], 'TI': ['WoS title'],
        'AF': ['Full, Ada'], 'AU': ['Full A', 'Extra B'], 'PY': ['2027'], 'EA': ['JUN 2025']})
    other = ProviderWorkEvidence(provenance=MetadataSource(provider='crossref', record_id='10.1234/formal',
        retrieved_at=datetime.now(timezone.utc)), external_ids=ExternalIds(doi='10.1234/formal'),
        title='Other formal title', abstract='Fills gap', authors=(Author(name='Other'),), publication_type='journal')
    preprint = other.model_copy(update={'publication_type': 'preprint', 'provenance': other.provenance.model_copy(update={'provider': 'wos'}),
        'title': 'Preprint title'})
    for records in ([other, preprint, record], [record, preprint, other]):
        paper, = canonicalize_records(records).papers
        assert paper.metadata.title == 'WoS title'
        assert paper.metadata.abstract == 'Fills gap'
        assert [author.name for author in paper.authors] == ['Full, Ada']
        assert paper.metadata.publication_date == '2027'
        assert paper.metadata.first_public_at is None
        assert not any(item.kind.value == 'accepted' for item in paper.date_evidence)


def test_wos_date_precision_does_not_borrow_formal_year_or_promote_early_access():
    for pd, py, ea, ey, published, online in [
        ('OCT', '2025', 'JUN 2025', '', '2025-10', '2025-06'),
        ('', '2027', 'SEP 2026', '', '2027', '2026-09'),
        ('', '', 'SEP 2026', '', None, '2026-09'),
        ('', '2027', 'SEP', '', '2027', None),
    ]:
        from allfold.paper_dates import date_value
        evidence = wos.record_evidence({'UT': ['WOS:1'], 'PD': [pd], 'PY': [py], 'EA': [ea], 'EY': [ey]})
        assert evidence.publication_date == published
        assert next((date_value(item) for item in evidence.dates if item.kind.value == 'published-online'), None) == online


def test_paper_dates_survive_restart_without_source_snapshot_storage(tmp_path):
    from allfold.application.wos import persist_wos
    from allfold.persistence.paper_repository import PaperRepository
    from allfold.persistence.safe_write import workspace_operation_lock
    from test_wos import record
    selected = JournalConfig(name='Biometrics', issn='0006-341X')
    paper = wos.record_paper(record(PD='FEB 2', EA='JAN 2026'), selected)
    with workspace_operation_lock(tmp_path) as lock:
        result = persist_wos([paper], lock, check_current=lambda: None, cancelled=lambda: False)
    with PaperRepository.open(tmp_path) as repository:
        saved, = repository.list_papers()
        assert saved.metadata.ordinary_dates == ('2026-01', '2026-02-02')
        assert saved.metadata.publication_date == '2026-02-02'
    later = wos.record_paper(record(TI='Changed title'), selected)
    with workspace_operation_lock(tmp_path) as lock:
        repeated = persist_wos([later], lock, check_current=lambda: None, cancelled=lambda: False)
    with PaperRepository.open(tmp_path) as repository:
        assert repository.get(saved.id) == saved
    assert repeated.skipped_existing_papers == 1


def test_early_access_only_does_not_become_generic_publication_on_creation():
    from allfold.canonicalize import canonicalize_records
    record = wos.record_evidence({'UT': ['WOS:1'], 'TI': ['Title'], 'EA': ['SEP 2026']})
    paper, = canonicalize_records([record]).papers
    assert paper.metadata.publication_date is None
    assert [item.kind.value for item in paper.date_evidence] == ['published-online']


def test_unselected_citations_and_addresses_are_not_archived_or_identity():
    evidence = wos.record_evidence({'UT':['WOS:42'], 'TI':['Selected title'],
        'CR':['PRIVATE reference DOI 10.5555/not-an-identity'], 'C1':['PRIVATE address']})
    assert evidence.external_ids.wos == 'WOS:42' and evidence.external_ids.doi is None
    assert not {'CR','C1'} & {field.tag for field in evidence.source_fields}
    assert 'PRIVATE' not in evidence.model_dump_json()
