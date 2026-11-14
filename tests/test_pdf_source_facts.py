"""Exact-target source facts survive the existing Run/collection boundaries."""
from datetime import datetime, timezone

import pytest

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperRepository
from allfold.providers.discovery_evidence import normalize_openalex
from allfold.providers.integrated import SourceScope
from integrated_run_helpers import run_integrated
from test_integrated_run import client_for, config


NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def openalex_raw(**updates):
    return dict(id='https://openalex.org/W123', doi='https://doi.org/10.5555/formal',
        title='Native hit', type='article', publication_date='2026-01-01',
        primary_location={'source': {'display_name': 'Journal', 'issn': ['0006-341X']}},
        best_oa_location={'pdf_url': 'https://repository.example/Best.PDF?version=2#page=3'},
        locations=[{'landing_page_url': 'https://repository.example/article/123',
            'pdf_url': 'https://repository.example/Best.PDF?version=2'},
            {'pdf_url': 'https://repository.example/Other.PDF'}],
        locations_count=2, **updates)


def test_normalized_openalex_facts_reach_production_run_and_disk_reopen(tmp_path):
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [pubmed]\n')
    record = normalize_openalex(openalex_raw(), SourceScope('journal', 'Journal', issns=('0006-341X',)))
    result = run_integrated(path, client_factory=client_for((record,)))
    assert result.facts.created_papers == 1
    with PaperRepository.open(tmp_path / 'workspace') as repository:
        paper = repository.match(ExternalIds(doi='10.5555/formal'))
        facts, = (fact for fact in paper.metadata.discovery_facts if fact.source == 'openalex')
        assert facts.source == 'openalex' and facts.capability == 'openalex-locations'
        assert facts.status == 'complete' and facts.target_doi == '10.5555/formal'
        assert facts.target_openalex == 'W123'
        assert [item.url for item in facts.candidates] == [
            'https://repository.example/Best.PDF?version=2', 'https://repository.example/Other.PDF']
        assert facts.candidates[0].field == 'best_oa_location.pdf_url'
        assert [item.url for item in facts.links if item.kind == 'landing'] == [
            'https://repository.example/article/123']
        assert paper.body is None


def test_crossref_response_facts_emit_through_necessary_branch_without_relation_ownership(tmp_path):
    import httpx
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from test_necessary_metadata import execute

    requests = []
    def response(request):
        requests.append(request)
        filters = request.url.params.get('filter', '')
        if 'relation.type:' in filters:
            rows = []
        elif '10.5555/formal' in filters:
            rows = [{'DOI': '10.5555/formal', 'type': 'journal-article',
                'alternative-id': ['S1234567890123456'],
                'resource': {'primary': {'URL': 'https://publisher.example/pii/S1234567890123456'}},
                'link': [{'URL': 'https://publisher.example/Target.PDF', 'content-type': 'application/pdf'},
                    {'URL': 'https://publisher.example/Target.xml', 'content-type': 'application/vnd.jats+xml'},
                    {'URL': 'https://publisher.example/Target.json', 'content-type': 'application/json'}],
                'relation': {'has-preprint': [{'id-type': 'doi', 'id': '10.5555/preprint'}]}}]
        else:
            rows = [{'DOI': '10.5555/preprint', 'type': 'posted-content',
                'link': [{'URL': 'https://repository.example/Related.PDF', 'content-type': 'application/pdf'}]}]
        return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})

    saved, _ = execute(tmp_path, necessary_metadata_branch(providers=('crossref',)), transport=response)
    with PaperRepository.open(tmp_path / 'workspace') as repository:
        paper = repository.get(saved.id)
        facts, = (fact for fact in paper.metadata.discovery_facts if fact.source == 'crossref')
        assert facts.target_doi == '10.5555/formal' and facts.status == 'complete'
        assert [(item.kind, item.url) for item in facts.links] == [
            ('landing', 'https://publisher.example/pii/S1234567890123456'),
            ('pdf', 'https://publisher.example/Target.PDF'),
            ('jats', 'https://publisher.example/Target.xml'),
            ('json', 'https://publisher.example/Target.json')]
        assert [(item.kind, item.value) for item in facts.identifiers] == [('alternative-id', 'S1234567890123456')]
        assert [item.url for item in facts.candidates] == ['https://publisher.example/Target.PDF']
        assert 'Related.PDF' not in facts.model_dump_json()
        assert len(requests) == 3


def test_facts_cannot_be_attached_to_a_different_paper_or_merged_across_works(tmp_path):
    from allfold.pdf_facts import PdfDiscoveryFacts, merge_discovery_facts
    from allfold.persistence.paper_repository import IdentityConflict, MetadataDelta, PaperMetadata

    facts = PdfDiscoveryFacts(source='openalex', capability='openalex-locations', status='complete',
        observed_at=NOW, target_doi='10.5555/other', target_openalex='W123')
    with PaperRepository.create(tmp_path) as repository:
        saved = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Paper')).paper
        with pytest.raises(IdentityConflict):
            repository.merge_metadata(saved.token, MetadataDelta(discovery_facts=(facts,)))
        assert repository.get(saved.id) == saved
        with pytest.raises(IdentityConflict):
            repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/new'),
                metadata=PaperMetadata(title='Other', discovery_facts=(facts,)))
        assert len(repository.list_papers()) == 1
    wrong_work = facts.model_copy(update={'target_openalex': 'W456'})
    with pytest.raises(ValueError, match='target'):
        merge_discovery_facts((facts,), (wrong_work,))


def test_openalex_capability_empty_partial_and_best_first_four_candidate_boundary():
    from datetime import timedelta
    from allfold.pdf_facts import merge_discovery_facts, openalex_discovery_facts

    empty = openalex_discovery_facts(dict(id='https://openalex.org/W123', doi='10.5555/formal',
        best_oa_location=None, locations=[]), NOW)
    assert empty.status == 'complete' and empty.candidates == ()
    partial = openalex_discovery_facts(dict(id='https://openalex.org/W123', doi='10.5555/formal'), NOW)
    assert partial.status == 'partial' and partial.candidates == ()
    raw = openalex_raw()
    raw['locations'] = [{'pdf_url': 'https://foo.content.openalex.org/Hidden.PDF'},
        {'pdf_url': 'http://127.0.0.1/Local.PDF'}, {'pdf_url': 'https://user:secret@example.org/a.pdf'},
        *({'pdf_url': f'https://repository.example/{index}.PDF'} for index in range(8))]
    raw['locations_count'] = len(raw['locations'])
    first = openalex_discovery_facts(raw, NOW)
    assert [item.url for item in first.candidates] == [
        'https://repository.example/Best.PDF?version=2',
        'https://repository.example/0.PDF', 'https://repository.example/1.PDF', 'https://repository.example/2.PDF']
    raw['best_oa_location'] = {'pdf_url': 'https://repository.example/NewBest.PDF'}
    second = openalex_discovery_facts(raw, NOW + timedelta(seconds=1))
    merged, = merge_discovery_facts((first,), (second,))
    assert len(merged.candidates) == 4
    assert merged.candidates[0].url == 'https://repository.example/NewBest.PDF'
    retained, = merge_discovery_facts((first,), (empty, partial))
    assert retained.status == 'complete' and retained.candidates == first.candidates


@pytest.mark.parametrize('preferred_is_new', [False, True])
def test_sqlite_fact_merge_size_overflow_preserves_preferred_snapshot_and_independent_content(tmp_path, preferred_is_new):
    from datetime import timedelta
    from allfold.pdf_facts import PdfCandidateFact, PdfDiscoveryFacts
    from allfold.persistence.paper_repository import MetadataDelta, PaperMetadata
    def snapshot(prefix, count, status, observed):
        return PdfDiscoveryFacts(source='document', capability='document-pdf', status=status,
            observed_at=observed, target_doi='10.5555/formal',
            candidates=tuple(PdfCandidateFact(stage='P3', rule_id='GENERIC',
                url='https://publisher.example/'+prefix+str(i)+'/'+'A'*3000+'.pdf') for i in range(count)))
    first = snapshot('old', 10, 'partial' if preferred_is_new else 'complete', NOW)
    second = snapshot('new', 12, 'complete' if preferred_is_new else 'partial', NOW + timedelta(seconds=1))
    preferred = second if preferred_is_new else first
    assert len(first.model_dump_json().encode()) < 65536 and len(second.model_dump_json().encode()) < 65536
    with PaperRepository.create(tmp_path) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Paper', discovery_facts=(first,))).paper
        saved = repository.merge_metadata(paper.token, MetadataDelta(abstract='Independent abstract.',
            ordinary_dates=('2026-01-02',), discovery_facts=(second,)))
    with PaperRepository.open(tmp_path) as repository:
        reopened = repository.get(saved.id)
        facts, = reopened.metadata.discovery_facts
        assert reopened.metadata.abstract == 'Independent abstract.' and reopened.metadata.ordinary_dates == ('2026-01-02',)
        assert facts.candidates == preferred.candidates and facts.status == preferred.status
        assert 'overflow' in facts.diagnostics and len(facts.model_dump_json().encode()) <= 65536


def test_independent_connections_preserve_fields_sequences_and_revoke_facts_after_restore_and_clear(tmp_path):
    from uuid import uuid4
    from allfold.pdf_facts import PdfCandidateFact, PdfDiscoveryFacts
    from allfold.persistence.paper_repository import BodyReference, MetadataDelta, PaperMetadata, StaleWriteError

    facts = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete', observed_at=NOW,
        target_doi='10.5555/formal', landing_url='https://publisher.example/article',
        candidates=(PdfCandidateFact(stage='P3', rule_id='META', url='https://publisher.example/Article.PDF'),))
    with PaperRepository.create(tmp_path) as owner:
        original = owner.create_or_match(owner.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Article', notes='Human note')).paper
        original = owner.complete_body(original.token, BodyReference(relative_path='Documents/existing.pdf'))
        admission = owner.admit_collection(owner.workspace_id, lifecycle_id=uuid4(), branches=('api', 'document'),
            direct_ids=ExternalIds(doi='10.5555/formal'), metadata=PaperMetadata(title='Unused'))
        token = admission.token
        owner.mark_collection_running(token)
        with PaperRepository.open(tmp_path) as independent:
            current = independent.get(original.id)
            current = independent.edit_metadata(current.token, {'abstract': 'Human abstract'})
            independent.commit_collection_branch(token, 'api', sequence=1, outcome='completed',
                delta=MetadataDelta(ordinary_dates=('2026-01-02',), abstract='Late API abstract'))
        saved = owner.commit_collection_branch(token, 'document', sequence=1, outcome='completed',
            delta=MetadataDelta(discovery_facts=(facts,)))
        repeated = owner.commit_collection_branch(token, 'document', sequence=1, outcome='completed',
            delta=MetadataDelta(discovery_facts=(facts.model_copy(update={'status': 'partial'}),)))
        assert repeated == saved
        finished = owner.finish_collection(token)
        assert finished.metadata.abstract == 'Human abstract'
        assert finished.metadata.notes == 'Human note' and finished.metadata.ordinary_dates == ('2026-01-02',)
        assert finished.metadata.discovery_facts == (facts,) and finished.body == original.body
        with PaperRepository.open(tmp_path) as independent:
            restored = independent.restore(independent.exclude(finished.token).token)
        with pytest.raises(StaleWriteError):
            owner.commit_collection_branch(token, 'document', sequence=2, delta=MetadataDelta(discovery_facts=(facts,)))
        assert owner.get(original.id).metadata.discovery_facts == (facts,)
        cleared = owner.clear_metadata(owner.exclude(restored.token).token)
        assert cleared.metadata is None and cleared.body == original.body
        assert cleared.identities == original.identities
        with pytest.raises(StaleWriteError):
            owner.merge_metadata(restored.token, MetadataDelta(discovery_facts=(facts,)))
    with PaperRepository.open(tmp_path) as reopened:
        assert reopened.get(original.id) == cleared


def test_source_facts_cancellation_refuses_a_late_sequence_and_explicit_retry_keeps_good_facts(tmp_path):
    from uuid import uuid4
    from allfold.pdf_facts import PdfDiscoveryFacts
    from allfold.persistence.paper_repository import MetadataDelta, PaperMetadata, StaleWriteError

    good = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete', observed_at=NOW,
        target_doi='10.5555/formal')
    with PaperRepository.create(tmp_path) as owner:
        admitted = owner.admit_collection(owner.workspace_id, lifecycle_id=uuid4(), branches=('document', 'api'),
            direct_ids=ExternalIds(doi='10.5555/formal'), metadata=PaperMetadata(title='Article'))
        owner.commit_collection_branch(admitted.token, 'document', sequence=1, outcome='completed',
            delta=MetadataDelta(discovery_facts=(good,)))
        with PaperRepository.open(tmp_path) as independent:
            independent.request_collection_cancel(admitted.token)
        with pytest.raises(StaleWriteError):
            owner.commit_collection_branch(admitted.token, 'api', sequence=1,
                delta=MetadataDelta(discovery_facts=(good.model_copy(update={'status': 'partial'}),)))
        owner.commit_collection_branch(admitted.token, 'api', sequence=1, outcome='cancelled')
        cancelled = owner.finish_collection(admitted.token)
        retry = owner.retry_collection(cancelled.token, lifecycle_id=uuid4(), branches=('document', 'api'))
        assert retry.paper.metadata.discovery_facts == (good,) and retry.token.attempt == 2
        with pytest.raises(StaleWriteError):
            owner.commit_collection_branch(admitted.token, 'api', sequence=2, delta=MetadataDelta(discovery_facts=(good,)))


@pytest.mark.parametrize(('failed', 'expected_status'), [(False, 'complete'), (True, 'failed')])
def test_necessary_exact_response_without_records_persists_complete_empty_or_failure(tmp_path, failed, expected_status):
    import httpx
    from allfold.application.necessary_metadata import NecessaryRequest, necessary_metadata_branch
    from test_necessary_metadata import execute

    requests = []
    def response(request):
        requests.append(request)
        return (httpx.Response(400) if failed else
            httpx.Response(200, json={'message': {'total-results': 0, 'items': []}}))
    paper, _ = execute(tmp_path, necessary_metadata_branch(providers=('crossref',), discover_relations=False,
        required=(NecessaryRequest('crossref', 'doi', '10.5555/formal', 'exact'),)), transport=response)
    with PaperRepository.open(tmp_path / 'workspace') as repository:
        facts, = repository.get(paper.id).metadata.discovery_facts
        assert facts.status == expected_status and facts.candidates == ()
        assert facts.target_doi == '10.5555/formal'
        assert facts.diagnostics == (('parse-failed',) if failed else ())
    assert len(requests) == 1


def test_signed_source_links_become_refresh_facts_and_never_enter_workspace_projection(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge

    raw = openalex_raw()
    signed = 'https://repository.example/Case.PDF?X-Amz-Signature=secret123&version=2'
    raw['best_oa_location'] = {'pdf_url': signed, 'landing_page_url': 'https://repository.example/article/123'}
    raw['locations'] = [{'pdf_url': signed, 'landing_page_url': 'https://repository.example/article/123'}]
    raw['locations_count'] = 1
    normalized = normalize_openalex(raw, SourceScope('journal', 'Journal'))
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [pubmed]\n')
    result = run_integrated(path, client_factory=client_for((normalized,)))
    assert result.facts.created_papers == 1
    with PaperRepository.open(tmp_path / 'workspace') as repository:
        saved = repository.match(ExternalIds(doi='10.5555/formal'))
        facts, = (fact for fact in saved.metadata.discovery_facts if fact.source == 'openalex')
        candidate, = facts.candidates
        assert candidate.url is None and candidate.refresh.kind == 'openalex-work'
        assert candidate.refresh.landing_url == 'https://repository.example/article/123'
        assert signed == raw['best_oa_location']['pdf_url']
        assert 'secret123' not in saved.metadata.model_dump_json()
        assert saved.body is None
    with TestClient(create_app(path, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs'),
            base_url='http://localhost') as client:
        response = client.get('/api/ui-next/workspace')
        assert response.status_code == 200
        assert 'secret123' not in response.text and 'discovery_facts' not in response.text


def test_two_branch_connections_merge_source_facts_with_dates_without_losing_either(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from allfold.pdf_facts import PdfDiscoveryFacts
    from allfold.persistence.paper_repository import MetadataDelta, PaperMetadata

    with PaperRepository.create(tmp_path) as repository:
        admitted = repository.admit_collection(repository.workspace_id, lifecycle_id=uuid4(), branches=('api', 'document'),
            direct_ids=ExternalIds(doi='10.5555/formal'), metadata=PaperMetadata(title='Article', notes='User note'))
    barrier = Barrier(2)
    def commit(branch):
        with PaperRepository.open(tmp_path) as repository:
            barrier.wait(timeout=3)
            delta = (MetadataDelta(ordinary_dates=('2026-01-02',), abstract='API abstract') if branch == 'api' else
                MetadataDelta(discovery_facts=(PdfDiscoveryFacts(source='document', capability='document-pdf',
                    status='complete', observed_at=NOW, target_doi='10.5555/formal'),)))
            repository.commit_collection_branch(admitted.token, branch, sequence=1, outcome='completed', delta=delta)
    with ThreadPoolExecutor(max_workers=2) as pool:
        tuple(pool.map(commit, ('api', 'document')))
    with PaperRepository.open(tmp_path) as repository:
        paper = repository.finish_collection(admitted.token)
        assert len(paper.metadata.discovery_facts) == 1
        assert paper.metadata.ordinary_dates == ('2026-01-02',) and paper.metadata.abstract == 'API abstract'
        assert paper.metadata.notes == 'User note' and paper.body is None
