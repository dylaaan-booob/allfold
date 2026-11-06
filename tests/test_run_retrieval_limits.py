"""Integrated Run exhausts scoped results without application quotas."""
from datetime import date

import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope
from allfold.providers.supplemental import SupplementalClient


@pytest.mark.parametrize('provider', ['openalex', 'europe_pmc'])
def test_discovery_retains_all_5100_results_across_51_pages(provider):
    pages = []
    total = 5100

    def handler(request):
        params = request.url.params
        if '/sources/' in request.url.path:
            return httpx.Response(200, json={'id': 'https://openalex.org/S1', 'issn': ['1234-567X']})
        if provider == 'openalex':
            offset = 0 if params['cursor'] == '*' else int(params['cursor'])
        else:
            offset = 0 if params['cursorMark'] == '*' else int(params['cursorMark'])
        pages.append(offset)
        numbers = range(offset, offset + 100)
        next_cursor = str(offset + 100) if offset + 100 < total else None
        if provider == 'openalex':
            body = {'results': [{'id': f'https://openalex.org/W{n + 1}', 'title': 'Learning'} for n in numbers],
                    'meta': {'count': total, 'next_cursor': next_cursor}}
        elif provider == 'europe_pmc':
            body = {'hitCount': total, 'nextCursorMark': next_cursor,
                    'resultList': {'result': [{'id': str(n + 1), 'source': 'MED', 'title': 'Learning'} for n in numbers]}}
        return httpx.Response(200, json=body)

    source = SourceScope('journal', 'Journal', issns=('1234-567X',))
    with DiscoveryClient(provider, transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.discover(source, parse_keyword_expression('learning'), date(2026, 1, 1), date(2026, 12, 31))
    assert result.status == 'complete'
    assert result.candidates == len(result.records) == total
    assert pages == list(range(0, total, 100))


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
