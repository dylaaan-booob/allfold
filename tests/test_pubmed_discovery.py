"""Merged native PubMed discovery and capability-aware exact metadata batches."""
import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope

A = SourceScope('journal', 'Journal A', 'a', ('0006-341X',))
B = SourceScope('journal', 'Journal B', 'b', ('0090-5364',))


def article(pmid, issn, doi=None):
    identity = f'<ArticleId IdType="doi">{doi}</ArticleId>' if doi else ''
    return f'''<PubmedArticle><MedlineCitation><PMID>{pmid}</PMID><Article>
    <Journal><ISSN>{issn}</ISSN><Title>Native Journal</Title><JournalIssue><PubDate><Year>2026</Year><Month>Oct</Month></PubDate></JournalIssue></Journal>
    <ArticleTitle>Native <i>causal</i> title</ArticleTitle><Abstract><AbstractText Label="METHODS">Study abstract</AbstractText></Abstract>
    <AuthorList><Author><LastName>Smith</LastName><ForeName>Ada</ForeName></Author></AuthorList>
    <ArticleDate DateType="Electronic"><Year>2026</Year><Month>10</Month><Day>03</Day></ArticleDate>
    </Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pubmed">{pmid}</ArticleId>{identity}</ArticleIdList>
    <History><PubMedPubDate PubStatus="received"><Year>2026</Year><Month>04</Month><Day>02</Day></PubMedPubDate><PubMedPubDate PubStatus="accepted"><Year>2026</Year><Month>09</Month><Day>12</Day></PubMedPubDate></History></PubmedData></PubmedArticle>'''


def test_merged_pubmed_history_fetch_preserves_pmid_only_and_page_callbacks():
    calls, pages = [], []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'count':'2', 'idlist':['41','42'], 'webenv':'fixture-history', 'querykey':'1'}})
        assert request.url.params['WebEnv'] == 'fixture-history'
        assert request.url.params['query_key'] == '1'
        index = int(request.url.params['retstart'])
        return httpx.Response(200, text='<PubmedArticleSet>' + article(str(41+index), A.issns[0] if index == 0 else B.issns[0], '10.5555/a' if index == 0 else None) + '</PubmedArticleSet>')
    with DiscoveryClient('pubmed', transport=httpx.MockTransport(response), interval=0, page_size=1) as client:
        results = client.discover_many((A,B), parse_keyword_expression('causal'), '2026-10-01', '2026-10-31', records_callback=pages.append)
        cached = client.lookup_many('pmid', ['41','42'], capability='summary')
    assert [r.status for r in results] == ['complete','complete']
    assert [r.records[0].external_ids.model_dump().get('pmid') for r in results] == ['41','42']
    assert results[1].records[0].external_ids.doi is None
    assert results[0].records[0].title == 'Native causal title'
    assert results[0].records[0].authors[0].name == 'Ada Smith'
    assert results[0].records[0].abstract == 'METHODS: Study abstract'
    assert {d.kind.value for d in results[0].records[0].dates} == {'received','accepted','published','published-online'}
    query = calls[0].url.params['term']
    assert '0006-341X[ISSN]' in query and '0090-5364[ISSN]' in query
    assert 'causal[Title/Abstract]' in query and '[Date - Publication]' in query
    assert len(calls) == 3 and len(pages) == 2 and len(cached.records) == 2


def test_pubmed_short_fetch_retains_verified_sibling_and_stops_without_skipping():
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200,json={'esearchresult':{'count':'2','idlist':['41','42'],'webenv':'fixture','querykey':'1'}})
        return httpx.Response(200,text='<PubmedArticleSet>'+article('41',A.issns[0])+'</PubmedArticleSet>')
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(response),interval=0) as client:
        result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
    assert result.status == 'partial' and len(result.records) == 1
    assert 'shortened batch' in result.limitations[0] and len(calls) == 2


def test_pubmed_native_date_shards_exhaust_esearch_window_and_report_impossible_day():
    searches = []
    def response(request):
        searches.append(request.url.params['term'])
        count = '10000' if len(searches)==1 else '0'
        return httpx.Response(200,json={'esearchresult':{'count':count,'idlist':[]}})
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(response),interval=0) as client:
        result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-02')
    assert result.status == 'empty' and len(searches)==3
    assert '"2026-10-01"[Date - Publication] : "2026-10-01"' in searches[1]
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(lambda _:httpx.Response(200,
        json={'esearchresult':{'count':'10000','idlist':[]}})),interval=0) as client:
        result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-01')
    assert result.status == 'failed' and '9999' in result.limitations[0]


def test_pubmed_http_200_application_error_never_becomes_empty_or_leaks_key():
    for body in (
        {'error': 'synthetic-secret-key'},
        {'esearchresult': {'count': '0', 'idlist': [], 'errorlist': {
            'phrasesnotfound': [A.issns[0], 'synthetic-secret-key']}}},
        {'esearchresult': {'count': '0', 'idlist': [], 'errorlist': {
            'phrasesnotfound': [A.issns[0]], 'fieldsnotfound': ['ISSN']}}},
        {'esearchresult': {'count': '0', 'idlist': [], 'errorlist': {'phrasesnotfound': A.issns[0]}}},
    ):
        with DiscoveryClient('pubmed',api_key='synthetic-secret-key',transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body)),interval=0) as client:
            result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
        assert result.status == 'failed' and 'synthetic-secret-key' not in repr(result)
        assert 'Entrez' in result.limitations[0]


@pytest.mark.parametrize('count', [0, 1])
def test_pubmed_unindexed_issn_does_not_discard_valid_search(count):
    calls = []

    def response(request):
        calls.append(request.url.path)
        if request.url.path.endswith('esearch.fcgi'):
            assert f'{B.issns[0]}[ISSN]' in request.url.params['term']
            return httpx.Response(200, json={'esearchresult': {
                'count': str(count), 'idlist': ['41'] if count else [],
                'webenv': 'fixture', 'querykey': '1',
                'errorlist': {'phrasesnotfound': [B.issns[0]], 'fieldsnotfound': []},
            }})
        assert request.url.params['WebEnv'] == 'fixture'
        return httpx.Response(200, text='<PubmedArticleSet>' + article('41', A.issns[0]) + '</PubmedArticleSet>')

    with DiscoveryClient('pubmed', transport=httpx.MockTransport(response), interval=0) as client:
        indexed, unindexed = client.discover_many(
            (A, B), parse_keyword_expression('causal'), '2026-10-01', '2026-10-31')

    assert indexed.status == ('complete' if count else 'empty')
    assert len(indexed.records) == count and not indexed.limitations
    assert unindexed.status == 'empty' and not unindexed.limitations
    assert len(calls) == 1 + count


@pytest.mark.parametrize('location', ['outer', 'esearchresult'])
@pytest.mark.parametrize('count', [0, 1])
def test_pubmed_empty_error_lists_preserve_valid_search_results(location, count):
    calls = []
    def response(request):
        calls.append(request.url.path)
        if request.url.path.endswith('esearch.fcgi'):
            search = {'count':str(count), 'idlist':['41'] if count else [],
                      'webenv':'fixture', 'querykey':'1'}
            body = {'esearchresult':search}
            target = body if location == 'outer' else search
            target['errorlist'] = {'phrasesnotfound':[], 'fieldsnotfound':[]}
            return httpx.Response(200, json=body)
        return httpx.Response(200, text='<PubmedArticleSet>'+article('41', A.issns[0])+'</PubmedArticleSet>')
    with DiscoveryClient('pubmed', transport=httpx.MockTransport(response), interval=0) as client:
        result = client.discover(A, parse_keyword_expression('causal'), '2026-10-01', '2026-10-31')
    assert result.status == ('complete' if count else 'empty')
    assert len(result.records) == count and not result.limitations
    assert len(calls) == 1 + count


def test_pubmed_summary_v2_dates_are_independent_and_fetch_is_stronger_capability():
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200,text='<PubmedArticleSet>'+article('41',A.issns[0])+'</PubmedArticleSet>')
        return httpx.Response(200,json={'errorlist':{'phrasesnotfound':[], 'fieldsnotfound':[]},
            'result':{'uids':['41'],'41':{'uid':'41','title':'Summary title','pubdate':'2026 Oct',
            'epubdate':'2026 Sep 30','history':[{'pubstatus':'received','date':'2026/03/01 00:00'},
            {'pubstatus':'accepted','date':'2026 Sep 10 00:00'},{'pubstatus':'entrez','date':'2026 Oct 2 00:00'}],
            'references':[{'reftype':'PreprintIn','pmid':'40'}]}}})
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(response),interval=0) as client:
        summary = client.lookup_many('pmid',['41'],capability='summary')
        fetched = client.lookup_many('pmid',['41'],capability='fetch')
        repeated = client.lookup_many('pmid',['41'],capability='summary')
    assert summary.status == 'complete' and {event.kind.value for event in summary.records[0].dates} == {'received','accepted','published-online','published'}
    assert summary.records[0].publication_date == '2026-10'
    assert summary.records[0].related_ids[0].relation == 'preprint'
    assert repeated.records == fetched.records and len(calls)==2


def test_pubmed_anonymous_and_keyed_pacing_are_optional_and_cancel_stops_dispatch():
    from threading import Event
    cancel, calls = Event(), []
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(lambda request:calls.append(request) or httpx.Response(200,json={}))) as anonymous:
        assert anonymous.interval >= 1/3
    with DiscoveryClient('pubmed',api_key='synthetic-key',transport=httpx.MockTransport(lambda request:calls.append(request) or httpx.Response(200,json={}))) as keyed:
        assert 0.1 <= keyed.interval < 1/3
    cancel.set()
    with DiscoveryClient('pubmed',cancel_event=cancel,transport=httpx.MockTransport(lambda request:calls.append(request) or httpx.Response(200,json={}))) as cancelled:
        result=cancelled.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
    assert result.status=='cancelled' and not calls


def test_direct_formal_pmid_survives_merged_work_with_preprint_pmid():
    from allfold.canonicalize import canonicalize_records
    from allfold.providers.pubmed import fetch_records
    formal_doi = '10.1093/nar/gkag979'
    formal, = fetch_records('<PubmedArticleSet>'+article('42908400',A.issns[0],formal_doi)+'</PubmedArticleSet>')
    with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as client:
        merged = client.normalize({'id':'https://openalex.org/W7223175244','doi':formal_doi,'title':'Merged Work',
            'ids':{'pmid':'https://pubmed.ncbi.nlm.nih.gov/42239170/'},'type':'article'},A)
    paper, = canonicalize_records((merged,formal)).papers
    assert paper.external_ids.model_dump()['pmid'] == '42908400'
    assert paper.external_ids.doi == formal_doi and paper.external_ids.openalex == 'https://openalex.org/W7223175244'
    assert any(ref.provider=='pmid' and ref.record_id=='42239170' for ref in merged.related_ids)


@pytest.mark.parametrize('search, rows, expected', [
    (['43', '42'], {'42': '10.1093/bioinformatics/btag793', '43': '10.5555/second'}, '42'),
    (['42', '43'], {'42': '10.1093/bioinformatics/btag793', '43': '10.1093/bioinformatics/btag793'}, 'conflict'),
    (['42'], {'42': '10.5555/unrequested'}, 'conflict'),
    (['42', '43'], {'42': '10.1093/bioinformatics/btag793'}, 'incomplete'),
    (['42', '42'], {'42': '10.1093/bioinformatics/btag793'}, 'incomplete'),
    ([], {}, None),
])
def test_pubmed_resolves_only_direct_unambiguous_dois_in_complete_batches(search, rows, expected):
    from allfold.providers.integrated import DiscoveryError, IdentityMismatch
    target, other = '10.1093/bioinformatics/btag793', '10.5555/second'
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            assert request.url.params['term'] == f'"{target}"[aid] OR "{other}"[aid]'
            return httpx.Response(200, json={'esearchresult': {'count': str(len(search)), 'idlist': search}})
        assert request.url.path.endswith('esummary.fcgi')
        assert set(request.url.params['id'].split(',')) == set(search)
        return httpx.Response(200, json={'result': {'uids': list(rows), **{
            pmid: {'uid': pmid, 'articleids': [{'idtype': 'doi', 'value': doi}],
                'history': [{'pubstatus': 'received', 'date': '2026/01/06'},
                    {'pubstatus': 'entrez', 'date': '2026/09/01'}]}
            for pmid, doi in rows.items()}}})
    with DiscoveryClient('pubmed', transport=httpx.MockTransport(response), interval=0) as client:
        matches = client.resolve_pubmed_dois((f'https://doi.org/{target.upper()}', other, target))
        value = matches[target]
        if expected == 'conflict':
            assert isinstance(value, IdentityMismatch)
        elif expected == 'incomplete':
            assert isinstance(value, DiscoveryError)
        elif expected is None:
            assert value == ()
        else:
            match, = value
            assert match.external_ids.pmid == expected and match.external_ids.doi == target
            assert [date.kind.value for date in match.dates] == ['received']
            reused = client.lookup_many('pmid', [expected], capability='summary')
            assert reused.records == value
    assert len(calls) == (1 if not search or len(set(search)) != len(search) else 2)


def test_pubmed_doi_batches_respect_transport_limit_and_stop_on_cancel():
    from threading import Event
    from urllib.parse import parse_qs

    from allfold.providers.integrated import Cancelled, DiscoveryError

    dois = [f'10.5555/article{i:03d}' for i in range(230)]
    invalid = '10.5555/query"[Title]'
    for stop in (False, True):
        cancel, calls = Event(), []

        def handler(request):
            assert request.method == 'POST' and not request.url.query
            fields = parse_qs(request.content.decode())
            assert fields['api_key'] == ['synthetic-key']
            assert len(request.content) < 6000
            calls.append(fields['term'][0])
            if stop and len(calls) == 2:
                cancel.set()
            return httpx.Response(200, json={'esearchresult': {'count': '0', 'idlist': []}})

        with DiscoveryClient('pubmed', api_key='synthetic-key', cancel_event=cancel, interval=0,
                transport=httpx.MockTransport(handler)) as client:
            values = client.resolve_pubmed_dois([*dois, invalid])
        assert isinstance(values[invalid], DiscoveryError)
        assert calls == [' OR '.join(f'"{doi}"[aid]' for doi in dois[offset:offset + 100])
            for offset in ([0, 100] if stop else [0, 100, 200])]
        assert all(values[doi] == () for doi in dois[:100])
        if stop:
            assert isinstance(values[dois[100]], Cancelled) and dois[200] not in values
        else:
            assert all(values[doi] == () for doi in dois)


def test_pubmed_doi_resolution_fetches_missing_direct_doi_and_retains_summary_history():
    doi = '10.5555/formal'
    calls = []

    def handler(request):
        path = request.url.path.rsplit('/', 1)[-1]
        calls.append(path)
        if path == 'esearch.fcgi':
            return httpx.Response(200, json={'esearchresult': {'count': '2', 'idlist': ['41', '42']}})
        if path == 'esummary.fcgi':
            return httpx.Response(200, json={'result': {'uids': ['41', '42'],
                '41': {'uid': '41', 'pubtype': ['Preprint'], 'articleids': [{'idtype': 'doi', 'value': doi}]},
                '42': {'uid': '42', 'history': [{'pubstatus': 'received', 'date': '2026/01/06'}]}}})
        assert request.url.params['id'] == '42'
        xml = article('42', A.issns[0], doi).split('<History>')[0] + '</PubmedData></PubmedArticle>'
        return httpx.Response(200, text='<PubmedArticleSet>' + xml + '</PubmedArticleSet>')

    with DiscoveryClient('pubmed', interval=0, transport=httpx.MockTransport(handler)) as client:
        matches = client.resolve_pubmed_dois((doi,))
        resolved, = matches[doi]
        fetched = client.lookup_many('pmid', ['42'], capability='fetch')
        assert fetched.records == (resolved,)
    assert resolved.external_ids.pmid == '42'
    assert [(date.month, date.day) for date in resolved.dates if date.kind.value == 'received'] == [(1, 6)]
    assert calls == ['esearch.fcgi', 'esummary.fcgi', 'efetch.fcgi']


@pytest.mark.parametrize('capability', ['summary', 'fetch'])
@pytest.mark.parametrize('outcome', ['cancelled', 'conflict', 'http_failure'])
def test_pubmed_doi_resolution_preserves_exact_request_outcomes(capability, outcome):
    from threading import Event

    from allfold.providers.integrated import Cancelled, IdentityMismatch, ProviderHTTPError

    doi, pmid = '10.5555/formal', '42'
    cancel = Event()
    calls = []

    def respond(request):
        path = request.url.path.rsplit('/', 1)[-1]
        calls.append(path)
        if path == 'esearch.fcgi':
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': [pmid]}})
        if path == 'esummary.fcgi' and capability == 'fetch':
            return httpx.Response(200, json={'result': {'uids': [pmid], pmid: {'uid': pmid}}})
        if outcome == 'cancelled':
            cancel.set()
            return httpx.Response(200, json={})
        if outcome == 'http_failure':
            return httpx.Response(400)
        if capability == 'fetch':
            return httpx.Response(200, text='<PubmedArticleSet>' +
                article('43', A.issns[0], doi) + '</PubmedArticleSet>')
        return httpx.Response(200, json={'result': {'uids': [pmid], pmid: {
            'uid': pmid, 'articleids': [{'idtype': 'doi', 'value': doi},
                {'idtype': 'doi', 'value': '10.5555/other'}]}}})

    with DiscoveryClient('pubmed', interval=0, cancel_event=cancel, transport=httpx.MockTransport(respond)) as client:
        result = client.resolve_pubmed_dois((doi,))[doi]
    assert isinstance(result, {'cancelled': Cancelled, 'conflict': IdentityMismatch,
        'http_failure': ProviderHTTPError}[outcome])
    assert calls == ['esearch.fcgi', 'esummary.fcgi'] + (['efetch.fcgi'] if capability == 'fetch' else [])


def test_successful_pubmed_summary_can_follow_an_unavailable_fetch():
    def respond(request):
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(404)
        assert request.url.path.endswith('esummary.fcgi')
        return httpx.Response(200, json={'result': {'uids': ['42'], '42': {'uid': '42',
            'history': [{'pubstatus': 'received', 'date': '2026/01/06'}]}}})

    with DiscoveryClient('pubmed', interval=0, transport=httpx.MockTransport(respond)) as client:
        assert client.lookup_many('pmid', ('42',), capability='fetch').status == 'failed'
        summary = client.lookup_many('pmid', ('42',), capability='summary')
    assert summary.status == 'complete'
    record, = summary.records
    assert [(item.kind.value, item.day) for item in record.dates] == [('received', 6)]
