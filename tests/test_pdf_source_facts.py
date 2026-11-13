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
        facts, = paper.metadata.discovery_facts
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
        facts, = paper.metadata.discovery_facts
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
