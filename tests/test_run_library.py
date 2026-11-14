"""Production Run identity classification and SQLite writes, without Paper Markdown."""
from dataclasses import replace
from datetime import datetime, timezone

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperMetadata, PaperRepository
from integrated_run_helpers import EmptyLookup, run_integrated
from test_integrated_run import config, evidence, client_for


def configured(tmp_path):
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [pubmed]\n')
    return path


def test_run_uses_repository_uuid_and_keeps_complete_records_unchanged(tmp_path):
    path = configured(tmp_path)
    rows = (evidence(),)
    first = run_integrated(path, client_factory=client_for(rows))
    workspace = tmp_path / 'workspace'
    with PaperRepository.open(workspace) as repository:
        saved, = repository.list_papers()
    assert saved.id != __import__('uuid').UUID(int=0)
    assert first.facts.details['paper_ids'] == [str(saved.id)]
    assert not (workspace / 'Papers').exists() and not (workspace / 'Inbox.base').exists()
    helper_calls = []
    class Completion(EmptyLookup):
        def lookup_many(self, namespace, ids, **kwargs):
            helper_calls.extend(ids)
            return super().lookup_many(namespace, ids, **kwargs)
    second = run_integrated(path, client_factory=client_for((evidence(title='Replacement'),)), lookup_factory=Completion)
    assert second.facts.created_papers == 0 and second.facts.existing_papers == 1
    assert helper_calls == []
    with PaperRepository.open(workspace) as repository:
        assert repository.get(saved.id) == saved


def test_excluded_and_released_placeholder_have_distinct_early_run_classification(tmp_path):
    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Old title', notes='Deleted notes')).paper
        excluded = repository.exclude(saved.token)
    result = run_integrated(path, client_factory=client_for((evidence(),)))
    assert result.facts.created_papers == result.facts.existing_papers == 0
    assert result.facts.statistics['identity_targets'] == 0
    with PaperRepository.open(workspace) as repository:
        released = repository.unexclude(repository.clear_metadata(excluded.token).token)
    result = run_integrated(path, client_factory=client_for((evidence(),)))
    assert result.facts.statistics['identity_targets'] == 1
    assert result.facts.statistics['rebuilt_papers'] == 1
    with PaperRepository.open(workspace) as repository:
        rebuilt = repository.get(saved.id)
        assert rebuilt.id == released.id and rebuilt.metadata.title == 'Native hit'
        assert rebuilt.metadata.notes == ''


def test_reject_restore_during_identity_lookup_cannot_renew_placeholder_authority(tmp_path):
    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Old title')).paper
        placeholder = repository.unexclude(repository.clear_metadata(repository.exclude(saved.token).token).token)
    changed = []
    class Completion(EmptyLookup):
        def lookup_many(self, namespace, ids, **kwargs):
            if not changed:
                with PaperRepository.open(workspace) as repository:
                    current = repository.get(placeholder.id)
                    changed.append(repository.unexclude(repository.exclude(current.token).token))
            return super().lookup_many(namespace, ids, **kwargs)
    run_integrated(path, client_factory=client_for((evidence(),)), lookup_factory=Completion)
    assert changed
    with PaperRepository.open(workspace) as repository:
        assert repository.get(placeholder.id).metadata is None


def test_run_preserves_formal_fields_future_dates_and_full_preprint_family_proof(tmp_path):
    from allfold.models import Author, EvidenceDate, EvidenceDateKind, MetadataSource, ProviderRecordRef, ProviderTopic, ProviderWorkEvidence
    from allfold.canonicalize import completion_metadata
    from allfold.persistence.run_library import metadata_from_run

    formal = evidence().model_copy(update={
        'abstract': 'Formal abstract', 'authors': (Author(name='Formal Author'),),
        'author_keywords': ('causality',), 'journal_issns': ('0006-341X',),
        'publication_date': '2027', 'indexed_terms': (ProviderTopic(value='Statistics', source='openalex'),),
        'related_ids': (ProviderRecordRef(provider='europe_pmc', record_id='PPR:123', relation='preprint'),
            ProviderRecordRef(provider='doi', record_id='10.5555/unresolved-preprint', relation='preprint')),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PUBLISHED, year=2027, month=2),
            EvidenceDate(kind=EvidenceDateKind.PUBLISHED_ONLINE, year=2027, month=2, day=3),
            EvidenceDate(kind=EvidenceDateKind.ACCEPTED, year=2027, month=2, day=4)),
    })
    native = ProviderWorkEvidence(provenance=MetadataSource(provider='europe_pmc', record_id='PPR:123',
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)), publication_type='preprint',
        external_ids=ExternalIds(europe_pmc='PPR:123'), related_dois=('10.5555/formal',),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2025, month=1, day=2,
            first_version=True, publication_type='preprint'),))
    rows = (formal, native)
    metadata = metadata_from_run(completion_metadata(rows), records=rows)
    assert metadata.abstract == 'Formal abstract' and metadata.authors[0].name == 'Formal Author'
    assert metadata.author_keywords == ('causality',) and metadata.indexed_terms[0].value == 'Statistics'
    assert metadata.publication_date == '2027'
    assert metadata.ordinary_dates == ('2027-02-03', '2027-02-04')
    assert metadata.first_public_at is None  # another known preprint family remains unresolved
    assert metadata.preprint_evidence[0].first_version
    assert metadata.preprint_evidence[0].version_family == 'europe_pmc:PPR:123'
    assert any(ref.record_id == '10.5555/unresolved-preprint' for ref in metadata.preprint_relations)
    assert not any(ref.record_id == '10.5555/formal' for ref in metadata.preprint_relations)
    workspace = tmp_path / 'proof'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=formal.external_ids, metadata=metadata).paper
    with PaperRepository.open(workspace) as repository:
        assert repository.get(saved.id) == saved
        assert repository.match(ExternalIds(europe_pmc='PPR:123')) is None


def test_library_open_failure_releases_run_admission_and_valid_retry_works(tmp_path, monkeypatch):
    import threading
    from allfold.application.coordinators.run_coordinator import RunCoordinator, StartOutcome
    from integrated_run_helpers import run_integrated as production_run

    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'papers.sqlite').write_bytes(b'corrupt isolated database')
    slot = threading.Lock()
    coordinator = RunCoordinator(path, run_slot=slot)
    assert coordinator.start().outcome is StartOutcome.START_FAILED
    assert not slot.locked()
    assert coordinator.snapshot().unexpected_error.category == 'LibraryCorruptError'
    (workspace / 'papers.sqlite').rename(workspace / 'corrupt.fixture')
    with PaperRepository.create(workspace):
        pass
    def isolated_run(config_path, **kwargs):
        kwargs.pop('provider')
        return production_run(config_path, client_factory=client_for(()), lookup_factory=EmptyLookup, **kwargs)
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', isolated_run)
    assert coordinator.start().outcome is StartOutcome.STARTED
    coordinator.join()
    assert not slot.locked() and coordinator.snapshot().unexpected_error is None


def test_run_batch_uses_indexed_identity_reads_instead_of_rescanning_each_target(tmp_path, monkeypatch):
    path = configured(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/existing'),
            metadata=PaperMetadata(title='Untouched library article'))
    full_reads = []
    original = PaperRepository.list_papers
    def read_all(repository):
        full_reads.append(True)
        return original(repository)
    monkeypatch.setattr(PaperRepository, 'list_papers', read_all)
    rows = tuple(evidence(doi=f'10.5555/incoming-{index}', pmid=str(100 + index)) for index in range(8))
    result = run_integrated(path, client_factory=client_for(rows))
    assert result.facts.created_papers == 8 and not result.errors
    # Initial authority capture and batch classification may read the library;
    # individual request guards and final captures must use indexed matching.
    assert len(full_reads) <= 2


def test_saved_not_started_paper_is_admitted_only_when_actually_hit(tmp_path):
    path=configured(tmp_path)
    workspace=tmp_path/'workspace';workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        hit=repository.create_or_match(repository.workspace_id,direct_ids=ExternalIds(doi='10.5555/formal',pmid='42'),
            metadata=PaperMetadata(title='Saved title')).paper
        untouched=repository.create_or_match(repository.workspace_id,direct_ids=ExternalIds(doi='10.5555/unhit'),
            metadata=PaperMetadata(title='Unhit')).paper
    result=run_integrated(path,client_factory=client_for((evidence(),)))
    assert result.facts.created_papers == 0 and result.facts.existing_papers == 1
    assert result.facts.statistics['identity_targets'] == 0
    assert result.facts.statistics['collection_admitted'] == 1
    with PaperRepository.open(workspace) as repository:
        captured=repository.get(hit.id)
        assert captured.metadata.title == 'Saved title' and captured.collection.attempt == 1
        assert repository.get(untouched.id) == untouched
    repeat=run_integrated(path,client_factory=client_for((evidence(),)))
    assert repeat.facts.statistics['collection_admitted'] == 0
    with PaperRepository.open(workspace) as repository:
        assert repository.get(hit.id) == captured


def test_old_run_cannot_rebuild_a_paper_cleared_after_its_initial_snapshot(tmp_path):
    path=configured(tmp_path)
    workspace=tmp_path/'workspace';workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        initial=repository.create_or_match(repository.workspace_id,direct_ids=ExternalIds(doi='10.5555/formal',pmid='42'),
            metadata=PaperMetadata(title='Original',notes='Private note')).paper
    changed=[]
    def clear_during_discovery():
        with PaperRepository.open(workspace) as repository:
            placeholder=repository.unexclude(repository.clear_metadata(repository.exclude(initial.token).token).token)
            changed.append(placeholder)
        return (evidence(),)
    result=run_integrated(path,client_factory=client_for(clear_during_discovery))
    assert result.facts.created_papers == result.facts.existing_papers == 0
    with PaperRepository.open(workspace) as repository:
        assert repository.get(initial.id) == changed[0]
        assert repository.get(initial.id).metadata is None


def test_run_preserves_all_reliable_direct_aliases_in_one_namespace(tmp_path):
    path=configured(tmp_path)
    rows=tuple(evidence('pubmed').model_copy(update={'external_ids':ExternalIds(
        doi='10.5555/formal',pmid='42',wos=value)}) for value in ('WOS:0001','WOS:0002'))
    result=run_integrated(path,client_factory=client_for(rows))
    assert result.facts.created_papers == 1
    with PaperRepository.open(tmp_path/'workspace') as repository:
        saved,=repository.list_papers()
        assert {(item.namespace,item.value) for item in saved.identities} == {
            ('doi','10.5555/formal'),('pmid','42'),('wos','WOS:0001'),('wos','WOS:0002')}
        assert next(branch for branch in saved.collection.branches if branch.name=='necessary-api').state == 'completed'
