"""Native merged journal lookup and verified exact Work evidence reuse."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope

A = SourceScope('journal','Journal A','a',('0006-341X','1541-0420'))
B = SourceScope('journal','Journal B','b',('0090-5364',))


def work(number, issns=('0006-341X',), **fields):
    return {'id':f'https://openalex.org/W{number}', 'doi':f'https://doi.org/10.5555/{number}',
        'title':f'Native title {number}', 'publication_date':'2026-10',
        'primary_location':{'source':{'id':'https://openalex.org/S1','display_name':'Native Journal','issn':list(issns)}},
        'authorships':[{'author':{'display_name':'A. Author'}}], 'locations':[], **fields}


def test_merged_native_issn_mapping_keeps_each_primary_source_and_reuses_full_details():
    calls, pages = [], []
    def response(request):
        calls.append(request)
        assert request.url.path == '/works'
        assert 'primary_location.source.issn:0006-341X|1541-0420|0090-5364' in request.url.params['filter']
        assert request.url.params['search.title_abstract_keywords.exact'] == '(causal AND statist*)'
        return httpx.Response(200,json={'meta':{'count':2,'next_cursor':None},'results':[work(2,B.issns),work(1)]})
    with DiscoveryClient('openalex',transport=httpx.MockTransport(response),interval=0) as client:
        results = client.discover_many((A,B),parse_keyword_expression('causal AND statist*'),'2026-10-01','2026-10-31',records_callback=pages.append)
        cached = client.lookup_many('doi',['10.5555/1','10.5555/2'])
    assert [result.status for result in results] == ['complete','complete']
    assert [[record.external_ids.doi for record in result.records] for result in results] == [['10.5555/1'],['10.5555/2']]
    assert results[0].records[0].journal_issns == ('0006-341X',)
    assert len(calls) == 1 and len(pages) == 1
    assert cached.bindings == (('doi','10.5555/1','W1'),('doi','10.5555/2','W2'))


def test_exact_batch_maps_location_doi_completes_locations_and_isolates_preprint_pmid():
    calls = []
    formal, preprint = '10.1093/nar/gkag979','10.1101/2026.09.01.123456'
    def response(request):
        calls.append(request)
        row = work(7223175244,doi='https://doi.org/'+formal, ids={'pmid':'https://pubmed.ncbi.nlm.nih.gov/42239170/'},locations_count=2,
            locations=[{'landing_page_url':'https://doi.org/'+formal}])
        if request.url.path == '/works/W7223175244':
            row['locations'].append({'landing_page_url':'https://www.biorxiv.org/content/'+preprint+'v1'})
            return httpx.Response(200,json=row)
        return httpx.Response(200,json={'meta':{'count':1},'results':[row]})
    with DiscoveryClient('openalex',transport=httpx.MockTransport(response),interval=0) as client:
        result = client.lookup_many('doi',[formal,preprint])
        repeated = client.lookup_many('openalex',['W7223175244'])
    assert result.status == 'complete' and len(result.records) == 1
    record = result.records[0]
    assert record.external_ids.model_dump().get('pmid') is None
    assert any(ref.provider == 'pmid' and ref.record_id == '42239170' and ref.relation is None for ref in record.related_ids)
    assert any(ref.provider == 'biorxiv' for ref in record.related_ids)
    assert len(record.locations) == 2 and len(result.bindings) == 2
    assert repeated.records == result.records and len(calls) == 2


def test_anonymous_pagination_is_explicitly_incomplete_and_keeps_first_page():
    with DiscoveryClient('openalex',interval=0,transport=httpx.MockTransport(lambda _:httpx.Response(200,
        json={'meta':{'count':2,'next_cursor':'second'},'results':[work(1)]}))) as client:
        result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
    assert result.status == 'partial' and len(result.records) == 1
    assert any('API Key' in limitation for limitation in result.limitations)


def test_concurrent_identical_exact_batches_share_one_request_and_cache_empty():
    entered, release, calls = Event(), Event(), []
    def response(request):
        calls.append(request); entered.set(); assert release.wait(5)
        return httpx.Response(200,json={'meta':{'count':1},'results':[work(1)]})
    with DiscoveryClient('openalex',interval=0,transport=httpx.MockTransport(response)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.lookup_many,'doi',['10.5555/1','10.5555/missing'])
        assert entered.wait(5)
        second = pool.submit(client.lookup_many,'doi',['10.5555/1','10.5555/missing'])
        release.set()
        assert first.result().records == second.result().records
        assert client.cached_lookup('doi','10.5555/missing') == ()
    assert len(calls) == 1


def test_exact_pagination_failure_keeps_verified_records_and_caches_missing_target_failure():
    calls = []
    with DiscoveryClient('openalex',api_key='synthetic-key',interval=0,transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(200,json={'meta':{'count':2},'results':[work(2)]}))) as client:
        first = client.lookup_many('doi',['10.5555/1','10.5555/2'])
        repeated = client.lookup_many('doi',['10.5555/1','10.5555/2'])
        assert isinstance(client.cached_lookup('doi','10.5555/1'),Exception)
    assert first.status == repeated.status == 'partial'
    assert [record.external_ids.doi for record in first.records] == ['10.5555/2']
    assert first.records == repeated.records and len(calls)==1
    assert any('pagination ended' in value for value in first.limitations)


def test_truncated_locations_with_wrong_singleton_identity_fail_without_binding_or_replay():
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path == '/works/W1':
            return httpx.Response(200,json=work(2))
        return httpx.Response(200,json={'meta':{'count':1},'results':[work(1,locations_count=2)]})
    with DiscoveryClient('openalex',interval=0,transport=httpx.MockTransport(response)) as client:
        first = client.lookup_many('doi',['10.5555/1'])
        repeated = client.lookup_many('doi',['10.5555/1'])
    assert first.status == repeated.status == 'failed' and not first.records and not first.bindings
    assert 'another Work identity' in first.limitations[0] and len(calls)==2


@pytest.mark.parametrize('singleton_status',[200,404])
def test_discovery_and_exact_lookup_share_inflight_truncated_work_singleton(singleton_status):
    from threading import get_ident
    singleton_entered, exact_dispatched, release = Event(), Event(), Event()
    singletons = []
    exact_thread = None
    full = work(1, locations_count=1, locations=[{'landing_page_url':'https://arxiv.org/abs/2201.12345'}])
    def response(request):
        if request.url.path == '/works/W1':
            singletons.append(request)
            singleton_entered.set()
            assert release.wait(5)
            return httpx.Response(singleton_status,json=full if singleton_status==200 else {})
        return httpx.Response(200,json={'meta':{'count':1},'results':[work(1,locations_count=1)]})
    with DiscoveryClient('openalex',interval=0,transport=httpx.MockTransport(response)) as client, ThreadPoolExecutor(max_workers=2) as pool:
        def guard():
            if get_ident() == exact_thread:
                exact_dispatched.set()
        client.request_guard = guard
        discovery = pool.submit(client.discover_many,(A,),parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
        assert singleton_entered.wait(5)
        def locate():
            nonlocal exact_thread
            exact_thread = get_ident()
            return client.lookup_many('doi',['10.5555/1'])
        exact = pool.submit(locate)
        assert exact_dispatched.wait(5)
        release.set()
        found, = discovery.result(timeout=5)
        located = exact.result(timeout=5)
    assert len(singletons) == 1
    if singleton_status == 200:
        assert found.status == located.status == 'complete'
        assert [location.url for location in found.records[0].locations] == [location.url for location in located.records[0].locations]
        assert len(found.records[0].locations) == 1
    else:
        assert found.status == located.status == 'failed'
        assert not found.records and not located.records
        assert all(any('404' in issue for issue in result.limitations) for result in (found,located))


@pytest.mark.parametrize('bad_record', ['parse', 'identity', 'singleton404', 'singletonidentity'])
def test_record_failure_keeps_verified_neighbors_callbacks_and_later_pages(bad_record):
    calls, pages = [], []
    bad = work(2)
    if bad_record == 'parse':
        bad['abstract_inverted_index'] = {'invalid': None}
    elif bad_record == 'identity':
        bad['id'] = 'invalid-work'
    else:
        bad['locations_count'] = 1
    def response(request):
        calls.append(request.url.path)
        if request.url.path == '/works/W2':
            return httpx.Response(404 if bad_record == 'singleton404' else 200, json=work(999))
        if request.url.params.get('filter') == 'openalex:W2':
            return httpx.Response(200, json={'meta': {'count': 1}, 'results': [bad]})
        later = request.url.params['cursor'] == 'second'
        return httpx.Response(200, json={'meta': {'count': 4, 'next_cursor': None if later else 'second'},
            'results': [work(4, B.issns)] if later else [work(1), bad, work(3)]})
    with DiscoveryClient('openalex', api_key='synthetic-key', interval=0, transport=httpx.MockTransport(response)) as client:
        first, second = client.discover_many((A, B), parse_keyword_expression('causal'), '2026-10-01', '2026-10-31',
            records_callback=pages.append)
        if bad_record.startswith('singleton'):
            repeated = client.lookup_many('openalex', ['W2', 'W3', 'W4'])
            assert repeated.status == 'partial'
            assert {row.external_ids.doi for row in repeated.records} == {'10.5555/3', '10.5555/4'}
            assert calls.count('/works/W2') == 1
    assert first.status == second.status == 'partial'
    assert [row.external_ids.doi for row in first.records] == ['10.5555/1', '10.5555/3']
    assert [row.external_ids.doi for row in second.records] == ['10.5555/4']
    assert first.candidates == 2 and second.candidates == 1
    assert first.total is second.total is None and len(first.limitations) == 1
    assert [[row.external_ids.doi for row in page] for page in pages] == [
        ['10.5555/1', '10.5555/3'], ['10.5555/4']]


def test_missing_title_remains_a_verified_identity_for_completion():
    from allfold.application.metadata_completion import complete_metadata
    from allfold.models import Author
    from allfold.canonicalize import completion_metadata
    rows = [work(1), work(2, title=None), work(3)]
    pages = []
    with DiscoveryClient('openalex', interval=0, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'meta': {'count': 3}, 'results': rows}))) as client:
        discovered = client.discover_many((A,), parse_keyword_expression('causal'), '2026-10-01', '2026-10-31',
            records_callback=pages.append)[0]
        assert discovered.status == 'complete' and discovered.candidates == 3
        missing = next(row for row in discovered.records if row.external_ids.doi == '10.5555/2')
        assert missing.title is None and client.cached_lookup('doi', '10.5555/2')[0].title is None
        class Formal:
            def lookup(self, namespace, identifier):
                return (missing.model_copy(update={'title': 'Completed formal title', 'abstract': 'Formal abstract',
                    'authors': (Author(name='Formal One'), Author(name='Formal Two')),
                    'provenance': missing.provenance.model_copy(update={'provider': 'crossref'})}),)
        completed = complete_metadata((missing,), ('crossref',), clients={'crossref': Formal()},
            allow_formal_preprint_reverse=False)
    assert len(pages) == 1 and len(pages[0]) == 3
    metadata = completion_metadata(completed.records)
    assert metadata.metadata.title == 'Completed formal title'
    assert metadata.authors == (Author(name='Formal One'), Author(name='Formal Two'))


@pytest.mark.parametrize('revocation', ['cancel', 'workspace'])
def test_record_isolation_does_not_continue_after_authority_revocation(revocation):
    from allfold.persistence.safe_write import ContentChangedError
    calls = []
    cancel = Event()
    def response(request):
        calls.append(request.url.path)
        if request.url.path == '/works/W2':
            if revocation == 'cancel':
                cancel.set()
            else:
                raise ContentChangedError('Controlled Workspace revocation')
        return httpx.Response(200, json={'meta': {'count': 4, 'next_cursor': 'second'},
            'results': [work(1), work(2, locations_count=1), work(3)]})
    with DiscoveryClient('openalex', api_key='synthetic-key', interval=0,
            cancel_event=cancel, transport=httpx.MockTransport(response)) as client:
        def discover():
            return client.discover_many((A,), parse_keyword_expression('causal'), '2026-10-01', '2026-10-31')[0]
        if revocation == 'workspace':
            with pytest.raises(ContentChangedError):
                discover()
        else:
            assert discover().status == 'cancelled'
    assert calls == ['/works', '/works/W2']
