"""Merged native PubMed discovery and capability-aware exact metadata batches."""
import httpx

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
    for body in ({'error':'synthetic-secret-key'},{'esearchresult':{'errorlist':{'phrasesnotfound':['synthetic-secret-key']}}}):
        with DiscoveryClient('pubmed',api_key='synthetic-secret-key',transport=httpx.MockTransport(lambda _:httpx.Response(200,json=body)),interval=0) as client:
            result = client.discover(A,parse_keyword_expression('causal'),'2026-10-01','2026-10-31')
        assert result.status == 'failed' and 'synthetic-secret-key' not in repr(result)
        assert 'Entrez' in result.limitations[0]


def test_pubmed_summary_v2_dates_are_independent_and_fetch_is_stronger_capability():
    calls = []
    def response(request):
        calls.append(request)
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200,text='<PubmedArticleSet>'+article('41',A.issns[0])+'</PubmedArticleSet>')
        return httpx.Response(200,json={'result':{'uids':['41'],'41':{'uid':'41','title':'Summary title','pubdate':'2026 Oct',
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
