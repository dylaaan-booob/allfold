"""Integrated Run exhausts scoped results without application quotas."""
from datetime import date

import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope
from allfold.providers.supplemental import SupplementalClient


@pytest.mark.parametrize('provider', ['openalex', 'europe_pmc', 'dblp', 'zbmath'])
def test_discovery_retains_all_5100_results_across_51_pages(provider):
    pages = []
    total = 5100

    def handler(request):
        params = request.url.params
        if '/sources/' in request.url.path:
            return httpx.Response(200, json={'id': 'https://openalex.org/S1', 'issn': ['1234-567X']})
        if '/serial/' in request.url.path:
            return httpx.Response(200, json={'result': [{'id': 1, 'issn': ['1234-567X']}],
                                           'status': {'execution_bool': True, 'nr_total_results': 1}})
        if provider == 'openalex':
            offset = 0 if params['cursor'] == '*' else int(params['cursor'])
        elif provider == 'europe_pmc':
            offset = 0 if params['cursorMark'] == '*' else int(params['cursorMark'])
        elif provider == 'dblp':
            offset = int(params['f'])
        else:
            offset = int(params['page']) * 100
        pages.append(offset)
        numbers = range(offset, offset + 100)
        next_cursor = str(offset + 100) if offset + 100 < total else None
        if provider == 'openalex':
            body = {'results': [{'id': f'https://openalex.org/W{n + 1}', 'title': 'Learning'} for n in numbers],
                    'meta': {'count': total, 'next_cursor': next_cursor}}
        elif provider == 'europe_pmc':
            body = {'hitCount': total, 'nextCursorMark': next_cursor,
                    'resultList': {'result': [{'id': str(n + 1), 'source': 'MED', 'title': 'Learning'} for n in numbers]}}
        elif provider == 'dblp':
            body = {'result': {'hits': {'@total': str(total), '@computed': str(total), '@first': str(offset),
                    'hit': [{'info': {'key': f'journals/test/{n}', 'title': 'Learning', 'year': '2026'}} for n in numbers]}}}
        else:
            body = {'result': [{'id': n + 1, 'title': {'title': 'Learning'}, 'year': '2026'} for n in numbers],
                    'status': {'execution_bool': True, 'nr_total_results': total}}
        return httpx.Response(200, json=body)

    source = SourceScope('journal', 'Journal', issns=('1234-567X',), stream='streams/journals/test')
    with DiscoveryClient(provider, transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.discover(source, parse_keyword_expression('learning'), date(2026, 1, 1), date(2026, 12, 31))
    assert result.status == 'complete'
    assert result.candidates == len(result.records) == total
    assert pages == list(range(0, total, 100))


def test_dblp_boolean_expansion_exceeds_32_clauses_without_rejecting_scope():
    calls = []
    expression = ' OR '.join(f'(term{n} AND word{n})' for n in range(6))
    with DiscoveryClient('dblp', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(200, json={'result': {'hits': {
            '@total': '0', '@computed': '0', '@first': '0'}}})), interval=0) as client:
        result = client.discover(SourceScope('conference', 'Conference', stream='streams/conf/test'),
                                 parse_keyword_expression(expression), date(2026, 1, 1), date(2026, 12, 31))
    assert result.status == 'empty' and len(calls) == 1
    assert len(calls[0].url.params['q'].split()) == 66  # Stream + year + 2**6 CNF clauses.


@pytest.mark.parametrize('ambiguous', [False, True])
def test_zbmath_checks_later_serial_pages_before_authorizing_source(ambiguous):
    calls = []

    def handler(request):
        calls.append(request)
        if '/serial/' in request.url.path:
            page = int(request.url.params.get('page', 0))
            if page == 0:
                rows = [{'id': n + 1, 'issn': ['1234-567X'] if ambiguous and n == 0 else ['0000-0000']}
                        for n in range(100)]
            else:
                rows = [{'id': 101, 'issn': ['1234-567X']}]
            return httpx.Response(200, json={'result': rows,
                'status': {'execution_bool': True, 'nr_total_results': 101}})
        assert 'se:101' in request.url.params['search_string']
        return httpx.Response(200, json={'result': [], 'status': {'execution_bool': True, 'nr_total_results': 0}})

    with DiscoveryClient('zbmath', transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.discover(SourceScope('journal', 'Journal', issns=('1234-567X',)),
                                 parse_keyword_expression('learning'), date(2026, 1, 1), date(2026, 12, 31))
    assert [r.url.params['page'] for r in calls if '/serial/' in r.url.path] == ['0', '1']
    assert result.status == ('skipped' if ambiguous else 'empty')
    assert len(calls) == (2 if ambiguous else 3)
    if ambiguous:
        assert 'ambiguous' in result.limitations[0]


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
def test_preprint_lookup_retains_more_than_16_linked_records(provider):
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.startswith('/pubs/'):
            rows = [{'preprint_doi': f'10.1101/{n:06}', 'published_doi': '10.5555/formal',
                     'preprint_platform': provider, 'published_date': '2026-01-02'} for n in range(17)]
        else:
            doi = request.url.path.split('/na/')[0].split(f'/details/{provider}/')[1]
            rows = [{'doi': doi, 'published': '10.5555/formal', 'server': provider,
                     'date': '2022-01-02', 'version': '1', 'title': 'Preprint'}]
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': rows})

    with SupplementalClient(provider, transport=httpx.MockTransport(handler), interval=0) as client:
        records = client.lookup('doi', '10.5555/formal')
    assert len(calls) == 18
    assert {record.external_ids.doi for record in records} == {'10.5555/formal'} | {
        f'10.1101/{n:06}' for n in range(17)}
