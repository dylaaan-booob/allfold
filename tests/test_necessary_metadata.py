"""Necessary identity/relationship services at their plan and registry boundaries."""
from datetime import datetime, timezone

import httpx
import pytest

from allfold.models import Author, ExternalIds, MetadataSource, ProviderWorkEvidence


def record(provider='crossref', doi='10.5555/formal', **values):
    return ProviderWorkEvidence(provenance=MetadataSource(provider=provider, record_id=doi,
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)),
        external_ids=ExternalIds(doi=doi), publication_type='journal', **values)


def test_ordinary_gaps_do_not_schedule_requests_after_necessary_capabilities_settle():
    from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse, necessary_requests

    root = {('doi', '10.5555/formal')}
    facts = (VerifiedResponse(NecessaryRequest('crossref', 'doi', '10.5555/formal', 'exact'), ()),
        VerifiedResponse(NecessaryRequest('crossref', 'doi', '10.5555/formal', 'reverse'), ()))
    missing = record()
    full = record(title='Title', abstract='Abstract', authors=(Author(name='Author'),),
        journal='Journal', publication_date='2026-01-02')
    for evidence in (missing, full):
        assert necessary_requests((evidence,), root_ids=root, facts=facts,
            providers=('crossref', 'openalex', 'pubmed')) == ()


def execute(tmp_path, branch, *, transport, metadata=None, on_task=None, direct_ids=None):
    from contextlib import contextmanager
    from allfold.application.collection_runtime import WorkspaceRegistry
    from allfold.application.metadata_completion import completion_client
    from allfold.application.task_clients import IndependentClientFactory
    from allfold.persistence.paper_repository import PaperMetadata, PaperRepository

    path = tmp_path / 'workspace'
    path.mkdir()
    with PaperRepository.create(path):
        pass
    clients = []
    @contextmanager
    def client_factory(provider, **kwargs):
        with completion_client(provider, transport=httpx.MockTransport(transport), interval=0, **kwargs) as client:
            clients.append(('opened', provider))
            yield client
        clients.append(('closed', provider))
    factory = IndependentClientFactory(tmp_path / 'config.yaml', client_factory=client_factory)
    class Authority:
        service_id = service_scope = None
        def verify(self):
            pass
    registry = WorkspaceRegistry(path, factory=factory, authority_capture=lambda *_: Authority())
    try:
        task = registry.submit(direct_ids=direct_ids or ExternalIds(doi='10.5555/formal'),
            metadata=metadata or PaperMetadata(title='Original', journal='Journal', publication_type='journal'),
            branches=(branch,))
        if on_task:
            on_task(registry, task)
        return task.future.result(5), clients
    finally:
        registry.shutdown()
        registry.join()
        factory.close()


def test_actual_branch_saves_formal_increment_and_keeps_related_preprint_separate(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    requests = []
    def response(request):
        requests.append(request)
        filters = request.url.params.get('filter', '')
        if 'relation.type:' in filters:
            rows = []
        elif '10.5555/formal' in filters:
            rows = [{'DOI': '10.5555/formal', 'type': 'journal-article',
                'abstract': '<jats:p>Formal abstract.</jats:p>',
                'published-online': {'date-parts': [[2026, 1, 2]]},
                'relation': {'has-preprint': [{'id-type': 'doi', 'id': '10.5555/preprint'}]}}]
        else:
            rows = [{'DOI': '10.5555/preprint', 'type': 'posted-content',
                'abstract': 'Related abstract must remain separate',
                'posted': {'date-parts': [[2020, 1, 2]]}}]
        return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})
    paper, clients = execute(tmp_path, necessary_metadata_branch(providers=('crossref',)), transport=response)
    assert paper.collection_status == 'completed'
    assert paper.metadata.abstract == 'Formal abstract.'
    assert paper.metadata.ordinary_dates == ('2026-01-02',)
    assert paper.metadata.first_public_at is None
    assert any(item.kind.value == 'preprint' and item.year == 2020 for item in paper.metadata.preprint_evidence)
    assert len(requests) == 3 and clients == [('opened', 'crossref'), ('closed', 'crossref')]


def test_first_public_waits_for_reverse_discovery_and_every_native_family(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import ProviderRecordRef
    from allfold.persistence.paper_repository import PaperRepository

    reverse_started, release_reverse = Event(), Event()
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
        <id>http://arxiv.org/abs/2201.12345v3</id><published>2022-01-02T00:00:00Z</published>
        <updated>2025-02-02T00:00:00Z</updated></entry></feed>'''
    def response(request):
        if request.url.path == '/api/query':
            return httpx.Response(200, text=atom)
        if request.url.path.startswith('/details/'):
            return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
                'doi': '10.64898/earlier', 'server': 'medrxiv', 'published': '10.5555/formal',
                'version': '1', 'date': '2019-01-02', 'abstract': 'Separate preprint'}]})
        if 'relation.type:' in request.url.params.get('filter', ''):
            reverse_started.set()
            assert release_reverse.wait(4)
            rows = [{'DOI': '10.64898/earlier', 'type': 'posted-content', 'publisher': 'medrxiv',
                'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': '10.5555/formal'}]}}]
        elif request.url.params.get('filter') == 'doi:10.5555/formal':
            rows = [{'DOI': '10.5555/formal', 'type': 'journal-article',
                'published': {'date-parts': [[2026, 2, 3]]}}]
        else:
            rows = [{'DOI': '10.64898/earlier', 'type': 'posted-content', 'publisher': 'medrxiv'}]
        return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})
    branch = necessary_metadata_branch(providers=('arxiv', 'crossref', 'medrxiv'), records=(record(
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345', relation='preprint'),)),))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(execute, tmp_path, branch, transport=response)
        try:
            assert reverse_started.wait(3)
            with PaperRepository.open(tmp_path / 'workspace') as repository:
                paper, = repository.list_papers()
                assert paper.metadata.first_public_at is None
                assert paper.metadata.ordinary_dates == ('2026-02-03',)
                assert any(item.first_version for item in paper.metadata.preprint_evidence)
        finally:
            release_reverse.set()
        paper, _ = pending.result(5)
    assert paper.collection_status == 'completed'
    assert paper.metadata.first_public_at == '2019-01-02'
    assert paper.metadata.ordinary_dates == ('2026-02-03',)


def test_partial_reverse_retains_facts_and_cannot_publish_first_public(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    native = ProviderWorkEvidence(provenance=MetadataSource(provider='arxiv', record_id='2201.12345',
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc)), external_ids=ExternalIds(arxiv='2201.12345'),
        publication_type='preprint', dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT,
            year=2022, month=1, day=2, first_version=True),))
    rows = [{'DOI': '10.5555/formal', 'type': 'journal-article', 'abstract': 'Survives failure',
        'published': {'date-parts': [[2026, 1, 2]]}}]
    def response(request):
        if 'relation.type:' in request.url.params.get('filter', ''):
            # The verified first page contains another known preprint; cursor
            # failure must be partial rather than a successful empty relation.
            if request.url.params['cursor'] != '*':
                return httpx.Response(200, json={'invalid': 'page'})
            reverse = [{'DOI': '10.48550/arxiv.2201.12345', 'type': 'posted-content',
                'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': '10.5555/formal'}]}}]
            return httpx.Response(200, json={'message': {'total-results': 2, 'items': reverse, 'next-cursor': 'next'}})
        found = rows if request.url.params.get('filter') == 'doi:10.5555/formal' else []
        return httpx.Response(200, json={'message': {'total-results': len(found), 'items': found}})
    branch = necessary_metadata_branch(providers=('crossref',), records=(record(
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345', relation='preprint'),)), native))
    paper, _ = execute(tmp_path, branch, transport=response)
    assert paper.collection_status == 'failed'
    assert paper.metadata.abstract == 'Survives failure'
    assert paper.metadata.first_public_at is None
    assert paper.metadata.ordinary_dates == ('2026-01-02',)


def test_crossref_and_arxiv_parsers_preserve_structured_candidate_text():
    from allfold.providers.supplemental import SupplementalClient
    crossref_text = '<jats:abstract><jats:sec><jats:title>Background</jats:title><jats:p>α + β = γ.</jats:p></jats:sec><jats:sec><jats:title>Methods</jats:title><jats:p>Line two.</jats:p></jats:sec></jats:abstract>'
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200,
            json={'message': {'DOI': '10.5555/formal', 'type': 'journal-article', 'abstract': crossref_text}}))) as client:
        formal, = client.lookup('doi', '10.5555/formal')
    assert formal.abstract == 'Background\nα + β = γ.\nMethods\nLine two.'
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2201.12345v2</id>
        <published>2022-01-02T00:00:00Z</published><summary>Background: α + β = γ.

Methods: Line two.</summary></entry></feed>'''
    with SupplementalClient('arxiv', interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, text=atom))) as client:
        native, = client.lookup('arxiv', '2201.12345')
    assert native.abstract == 'Background: α + β = γ.\n\nMethods: Line two.'


def test_capabilities_are_distinct_and_fetch_can_satisfy_summary_only():
    from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse, necessary_requests
    root = {('doi', '10.5555/formal'), ('pmid', '42')}
    records = (record().model_copy(update={'external_ids': ExternalIds(doi='10.5555/formal', pmid='42')}),)
    summary = NecessaryRequest('pubmed', 'pmid', '42', 'summary')
    fetch = NecessaryRequest('pubmed', 'pmid', '42', 'fetch')
    reverse = NecessaryRequest('crossref', 'doi', '10.5555/formal', 'reverse')
    exact = NecessaryRequest('crossref', 'doi', '10.5555/formal', 'exact')
    pending = necessary_requests(records, root_ids=root, providers=('pubmed', 'crossref'),
        required=(fetch,), facts=(VerifiedResponse(summary), VerifiedResponse(exact)))
    assert pending == (reverse, fetch)
    pending = necessary_requests(records, root_ids=root, providers=('pubmed',), facts=(VerifiedResponse(fetch),))
    assert pending == ()


def test_explicit_target_cannot_query_an_unrelated_identity(tmp_path):
    from allfold.application.necessary_metadata import NecessaryRequest, necessary_metadata_branch
    branch = necessary_metadata_branch(providers=('openalex',), discover_relations=False,
        required=(NecessaryRequest('openalex', 'doi', '10.5555/unrelated', 'work'),))
    paper, clients = execute(tmp_path, branch, transport=lambda _: pytest.fail('Unrelated request escaped'))
    assert paper.collection_status == 'failed'
    assert paper.metadata.ordinary_dates == () and clients == []


def test_native_batch_drains_every_arxiv_group_through_actual_registry(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import ProviderRecordRef
    queries = []
    def response(request):
        ids = request.url.params['id_list'].split(',')
        queries.append(ids)
        entries = ''.join(f'<entry><id>http://arxiv.org/abs/{key}v2</id>'
            '<published>2022-01-02T00:00:00Z</published></entry>' for key in ids)
        return httpx.Response(200, text=f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>')
    branch = necessary_metadata_branch(providers=('arxiv',), records=(record(related_ids=tuple(
        ProviderRecordRef(provider='arxiv', record_id=f'2201.{number:05d}', relation='preprint')
        for number in range(201))),))
    paper, _ = execute(tmp_path, branch, transport=response)
    assert paper.collection_status == 'completed'
    assert [len(ids) for ids in queries] == [200, 1]
    assert paper.metadata.first_public_at == '2022-01-02'
    assert len(paper.metadata.preprint_evidence) == 201


def test_guarded_read_never_renews_captured_abstract_generation(tmp_path):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.persistence.paper_repository import MetadataDelta, PaperRepository
    captured = []
    def collect(context):
        token = context.token
        first = context.read_paper()
        with PaperRepository.open(tmp_path / 'workspace') as repository:
            changed = repository.edit_metadata(first.token, {'abstract': 'User edit'})
            repository.edit_metadata(changed.token, {'abstract': None, 'notes': 'User note'})
        current = context.read_paper()
        captured.append((token, context.token, current.abstract_generation))
        context.emit(MetadataDelta(abstract='Stale automatic value', ordinary_dates=('2026-02',)), sequence=1)
    paper, _ = execute(tmp_path, BranchSpec('read', collect), transport=lambda _: pytest.fail('Unexpected HTTP'))
    original, current, generation = captured[0]
    assert original is current and generation != original.write.abstract_generation
    assert paper.metadata.abstract is None and paper.metadata.notes == 'User note'
    assert paper.metadata.ordinary_dates == ('2026-02',)


def test_pubmed_summary_relations_and_europe_native_proof_do_not_upgrade_formal_fetch(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    requests = []
    def response(request):
        requests.append(request)
        if request.url.path.endswith('/search'):
            query = request.url.params['query']
            if 'HAS_PREPRINT:Y' in query:
                rows = [{'source': 'MED', 'id': '42', 'doi': '10.5555/formal', 'title': 'Formal',
                    'commentCorrectionList': {'commentCorrection': [{'type': 'Preprint in',
                        'source': 'PPR', 'id': 'PPR123', 'note': 'Explicit relation'}]}}]
            else:
                assert 'SRC:PPR' in query and 'EXT_ID:PPR123' in query
                rows = [{'source': 'PPR', 'id': 'PPR123', 'title': 'Independent preprint',
                    'versionNumber': 1, 'firstPublicationDate': '2020-01-02'}]
            return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
        if request.url.path.endswith('esummary.fcgi'):
            assert request.url.params['id'] == '42'
            return httpx.Response(200, json={'result': {'uids': ['42'], '42': {'uid': '42',
                'articleids': [{'idtype': 'doi', 'value': '10.5555/formal'}], 'pubdate': '2026 Jan 2',
                'references': [{'reftype': 'PreprintIn', 'pmid': '43'}]}}})
        assert request.url.path.endswith('efetch.fcgi') and request.url.params['id'] == '43'
        return httpx.Response(200, text='''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>43</PMID>
            <Article><ArticleTitle>Linked preprint</ArticleTitle><Abstract><AbstractText>Related abstract</AbstractText></Abstract>
            <Journal><JournalIssue><PubDate><Year>2019</Year><Month>01</Month><Day>02</Day></PubDate></JournalIssue></Journal>
            </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>''')
    known = record().model_copy(update={'external_ids': ExternalIds(doi='10.5555/formal', pmid='42')})
    paper, _ = execute(tmp_path, necessary_metadata_branch(providers=('pubmed', 'europe_pmc'), records=(known,)), transport=response)
    assert paper.collection_status == 'completed'
    assert paper.metadata.abstract is None
    assert paper.metadata.ordinary_dates == ('2026-01-02',)
    assert paper.metadata.first_public_at is None  # Linked PMID's publication is not native-v1 proof.
    assert {(item.namespace, item.value) for item in paper.identities} == {('doi', '10.5555/formal'), ('pmid', '42'), ('europe_pmc', 'MED:42')}
    assert any(item.first_version and item.year == 2020 for item in paper.metadata.preprint_evidence)
    assert len(requests) == 4


def test_precreation_doi_identity_service_keeps_quoted_search_and_fetch_fallback():
    from allfold.application.necessary_metadata import confirm_formal_dois
    from allfold.providers.integrated import DiscoveryClient
    from test_pubmed_discovery import article
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            assert request.url.params['term'] == '"10.5555/formal"[aid]'
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': ['42']}})
        if request.url.path.endswith('esummary.fcgi'):
            return httpx.Response(200, json={'result': {'uids': ['42'], '42': {'uid': '42'}}})
        assert request.url.path.endswith('efetch.fcgi')
        return httpx.Response(200, text='<PubmedArticleSet>' + article('42', '0006-341X', '10.5555/formal') + '</PubmedArticleSet>')
    guards = []
    with DiscoveryClient('pubmed', interval=0, transport=httpx.MockTransport(response)) as client:
        result = confirm_formal_dois(client, ('10.5555/formal', '10.5555/formal'), guard=lambda: guards.append(True))
    formal, = result['10.5555/formal']
    assert formal.external_ids.doi == '10.5555/formal' and formal.external_ids.pmid == '42'
    assert len(calls) == 3 and len(guards) == 2


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
def test_explicit_native_reverse_uses_bound_publication_then_details(tmp_path, provider):
    from allfold.application.necessary_metadata import NecessaryRequest, necessary_metadata_branch
    requests = []
    def response(request):
        requests.append(request)
        assert '/' + provider + '/' in request.url.path
        if request.url.path.startswith('/pubs/'):
            rows = [{'preprint_doi': '10.64898/earlier', 'published_doi': '10.5555/formal',
                'preprint_platform': provider, 'published_date': '2026-01-02'}]
        else:
            rows = [{'doi': '10.64898/earlier', 'server': provider, 'published': '10.5555/formal',
                'version': '1', 'date': '2020-01-02', 'abstract': 'Independent abstract'}]
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': rows})
    branch = necessary_metadata_branch(providers=(provider,), discover_relations=False,
        required=(NecessaryRequest(provider, 'doi', '10.5555/formal', 'reverse'),))
    paper, _ = execute(tmp_path, branch, transport=response)
    assert paper.collection_status == 'completed'
    assert paper.metadata.first_public_at == '2020-01-02'
    assert paper.metadata.ordinary_dates == ('2026-01-02',) and paper.metadata.abstract is None
    assert len(requests) == 2


def test_explicit_native_details_rejects_conflicting_formal_publication(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import ProviderRecordRef
    def response(_):
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': '10.1101/123456', 'server': 'biorxiv', 'published': '10.5555/another',
            'version': '1', 'date': '2020-01-02'}]})
    branch = necessary_metadata_branch(providers=('biorxiv',), records=(record(related_ids=(
        ProviderRecordRef(provider='biorxiv', record_id='10.1101/123456', relation='preprint'),)),))
    paper, _ = execute(tmp_path, branch, transport=response)
    assert paper.collection_status == 'failed'
    assert paper.metadata.first_public_at is None and paper.metadata.preprint_evidence == ()


def test_verified_work_from_a_closed_discovery_client_is_reused_without_borrowing_it(tmp_path):
    from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse, necessary_metadata_branch
    from allfold.providers.integrated import DiscoveryClient
    calls = []
    def response(request):
        calls.append(request)
        row = {'id': 'https://openalex.org/W1', 'doi': 'https://doi.org/10.5555/formal',
            'title': 'Work title', 'publication_date': '2026-01-02', 'locations_count': 2,
            'ids': {'pmid': 'https://pubmed.ncbi.nlm.nih.gov/43/'},
            'locations': [{'landing_page_url': 'https://doi.org/10.5555/formal'}]}
        if request.url.path == '/works/W1':
            row['locations'].append({'landing_page_url': 'https://arxiv.org/abs/2201.12345'})
            return httpx.Response(200, json=row)
        return httpx.Response(200, json={'meta': {'count': 1}, 'results': [row]})
    work = NecessaryRequest('openalex', 'doi', '10.5555/formal', 'work')
    with DiscoveryClient('openalex', interval=0, transport=httpx.MockTransport(response)) as client:
        result = client.lookup_many('doi', ('10.5555/formal',))
    assert len(calls) == 2 and len(result.records[0].locations) == 2
    branch = necessary_metadata_branch(providers=('openalex',), discover_relations=False,
        required=(work,), facts=(VerifiedResponse(work, result.records),))
    paper, clients = execute(tmp_path, branch, transport=lambda _: pytest.fail('Verified Work was queried again'))
    assert paper.collection_status == 'completed' and clients == []
    assert ('openalex', 'W1') in {(item.namespace, item.value) for item in paper.identities}
    assert not any(item.namespace == 'pmid' for item in paper.identities)
    assert paper.metadata.ordinary_dates == ('2026-01-02',)


@pytest.mark.parametrize('provider', ['crossref', 'europe_pmc'])
def test_more_than_100_explicit_targets_drain_all_transport_groups(tmp_path, provider):
    import re
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import ProviderRecordRef
    requests = []
    def response(request):
        requests.append(request)
        if provider == 'crossref':
            filters = request.url.params['filter']
            ids = re.findall(r'(?:^|,)doi:([^,]+)', filters)
            rows = [{'DOI': key, 'type': 'posted-content' if key != '10.5555/formal' else 'journal-article'} for key in ids]
            return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})
        ids = re.findall(r'EXT_ID:(PPR\d+)', request.url.params['query'])
        rows = [{'source': 'PPR', 'id': key, 'title': 'Native preprint', 'versionNumber': 1,
            'firstPublicationDate': '2020-01-02'} for key in ids]
        return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
    refs = tuple(ProviderRecordRef(provider='doi' if provider == 'crossref' else 'europe_pmc',
        record_id=f'10.5555/preprint-{number}' if provider == 'crossref' else f'PPR:PPR{number}', relation='preprint')
        for number in range(101))
    branch = necessary_metadata_branch(providers=(provider,), records=(record(related_ids=refs),))
    paper, _ = execute(tmp_path, branch, transport=response)
    assert paper.collection_status == 'completed'
    if provider == 'europe_pmc':
        assert len(requests) == 2 and len(paper.metadata.preprint_evidence) == 101
        assert paper.metadata.first_public_at == '2020-01-02'
    else:
        assert len(requests) == 3  # two exact batches plus independent reverse
        assert len(paper.metadata.sources) == 103  # seed + formal and 101 related responses
        assert paper.metadata.first_public_at is None


def test_raw_service_404_is_failure_and_never_empty_success(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    paper, _ = execute(tmp_path, necessary_metadata_branch(providers=('crossref',)),
        transport=lambda _: httpx.Response(404))
    assert paper.collection_status == 'failed'
    assert paper.metadata.ordinary_dates == () and paper.metadata.first_public_at is None


def test_cancellation_during_response_discards_candidate_and_waits_for_client_close(tmp_path):
    from threading import Event
    from allfold.application.necessary_metadata import necessary_metadata_branch
    entered, finish = Event(), Event()
    def response(_):
        entered.set()
        assert finish.wait(3)
        return httpx.Response(200, json={'message': {'total-results': 1, 'items': [{
            'DOI': '10.5555/formal', 'type': 'journal-article', 'abstract': 'Must not commit'}]}})
    def cancel(registry, task):
        assert entered.wait(2)
        assert registry.cancel_paper(task.paper_id, task.workspace_id)
        assert not task.future.done()
        finish.set()
    paper, clients = execute(tmp_path, necessary_metadata_branch(providers=('crossref',)),
        transport=response, on_task=cancel)
    assert paper.collection_status == 'cancelled'
    assert paper.metadata.abstract is None and clients == [('opened', 'crossref'), ('closed', 'crossref')]


@pytest.mark.parametrize('rows,unknown', [
    ([{'version': '2', 'date': '2020-01-02'}], False),
    ([{'version': '1', 'date': '2999-01-02'}], False),
    ([{'version': '1', 'date': '2020-01-02'}, {'version': '2', 'date': '2019-01-02'}], False),
    ([{'version': '1', 'date': '2020-01-02'}], True),
])
def test_unresolved_future_conflicting_and_unknown_families_cannot_establish_first_public(tmp_path, rows, unknown):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.models import ProviderRecordRef
    refs = [ProviderRecordRef(provider='biorxiv', record_id='10.1101/123456', relation='preprint')]
    if unknown:
        refs.append(ProviderRecordRef(provider='doi', record_id='10.5555/unknown-family', relation='preprint'))
    def response(_):
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [
            {'doi': '10.1101/123456', 'server': 'biorxiv', 'published': '10.5555/formal', **row} for row in rows]})
    paper, _ = execute(tmp_path, necessary_metadata_branch(providers=('biorxiv',),
        records=(record(related_ids=tuple(refs)),)), transport=response)
    assert paper.collection_status == 'completed'
    assert paper.metadata.first_public_at is None and paper.metadata.ordinary_dates == ()


def test_native_proof_service_accepts_known_preprint_paper_identity(tmp_path):
    from allfold.application.necessary_metadata import necessary_metadata_branch
    from allfold.persistence.paper_repository import PaperMetadata
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2201.12345v2</id>
        <published>2022-01-02T00:00:00Z</published></entry></feed>'''
    paper, _ = execute(tmp_path, necessary_metadata_branch(providers=('arxiv',)),
        metadata=PaperMetadata(title='Known Preprint', publication_type='preprint'),
        direct_ids=ExternalIds(arxiv='2201.12345'), transport=lambda _: httpx.Response(200, text=atom))
    assert paper.collection_status == 'completed'
    assert paper.metadata.first_public_at == '2022-01-02'


def test_structured_pubmed_candidate_reaches_service_report_with_headings_and_scientific_text(tmp_path):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse, collect_necessary_metadata
    reports = []
    def response(request):
        assert request.url.path.endswith('efetch.fcgi') and request.url.params['id'] == '42'
        return httpx.Response(200, text='''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID>
            <Article><ArticleTitle>Formal</ArticleTitle><Abstract><AbstractText Label="Background">α + β = γ.</AbstractText>
            <AbstractText Label="Methods">Scientific text remains.</AbstractText></Abstract></Article></MedlineCitation>
            <PubmedData><ArticleIdList><ArticleId IdType="doi">10.5555/formal</ArticleId></ArticleIdList></PubmedData>
            </PubmedArticle></PubmedArticleSet>''')
    def run(context):
        parsed = context.provider('pubmed').lookup_many('pmid', ('42',), capability='fetch')
        known = record().model_copy(update={'external_ids': ExternalIds(doi='10.5555/formal', pmid='42')})
        reports.append(collect_necessary_metadata(context, providers=('pubmed',), records=(known,),
            discover_relations=False, facts=(VerifiedResponse(NecessaryRequest('pubmed', 'pmid', '42', 'fetch'), parsed.records),)))
    paper, _ = execute(tmp_path, BranchSpec('pubmed-candidate', run, providers=('pubmed',)), transport=response)
    assert paper.collection_status == 'completed'
    assert reports[0].records[-1].abstract == 'Background: α + β = γ.\nMethods: Scientific text remains.'
