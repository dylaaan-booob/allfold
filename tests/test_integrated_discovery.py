from datetime import date
import httpx
from allfold.keywords import parse_keyword_expression
from allfold.config import JournalConfig


def test_openalex_null_source_completion_keeps_other_providers_hit():
    from allfold.application.metadata_completion import complete_metadata
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.providers.integrated import DiscoveryClient
    from datetime import datetime, timezone
    original = ProviderWorkEvidence(title='Native hit', journal='Journal', external_ids=ExternalIds(doi='10.5555/null'),
        provenance=MetadataSource(provider='europe_pmc', record_id='MED:42', retrieved_at=datetime.now(timezone.utc),role='discovery'))
    raw={'id':'https://openalex.org/W123','doi':'https://doi.org/10.5555/null','title':'Native hit','primary_location':None}
    with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json=raw)),interval=0) as client:
        completed=complete_metadata((original,),('openalex',),clients={'openalex':client})
    assert not completed.issues and original in completed.records
    assert completed.records[1].external_ids.openalex=='https://openalex.org/W123'


def test_malformed_supplement_metadata_is_local_to_that_request():
    from allfold.application.metadata_completion import complete_metadata
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.providers.integrated import DiscoveryClient
    from datetime import datetime, timezone
    original=ProviderWorkEvidence(title='Native hit',external_ids=ExternalIds(doi='10.5555/bad'),
        provenance=MetadataSource(provider='dblp',record_id='journals/example/Paper',retrieved_at=datetime.now(timezone.utc)))
    with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={
        'id':'https://openalex.org/W123','title':'Native hit','primary_location':['malformed']})),interval=0) as client:
        completed=complete_metadata((original,),('openalex',),clients={'openalex':client})
    assert completed.records==(original,) and len(completed.issues)==1


def test_openalex_biomedical_ids_join_doi_free_europe_pmc_records():
    from allfold.canonicalize import canonicalize_records
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    for ids, epmc in (({'pmid':'https://pubmed.ncbi.nlm.nih.gov/123/'},{'source':'MED','id':'123'}),
                      ({'pmcid':'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC456/'},{'source':'MED','id':'999','pmcid':'PMC456'})):
        with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as oa, \
             DiscoveryClient('europe_pmc',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as europe:
            left=oa.normalize({'id':'https://openalex.org/W123','title':'No DOI','ids':ids},SourceScope('journal','Journal'))
            right=europe.normalize(dict(epmc,title='No DOI'),SourceScope('journal','Journal'))
        assert len(canonicalize_records((left,right)).papers)==1


def test_openalex_uses_verified_source_when_another_issn_is_not_found():
    from allfold.keywords import parse_keyword_expression
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    for identifiers in (('0006-341X','1541-0420'),('1541-0420','0006-341X')):
        requests=[]
        def response(request):
            requests.append(request)
            if request.url.path.endswith('1541-0420'):
                return httpx.Response(404,json={})
            if '/sources/' in request.url.path:
                return httpx.Response(200,json={'id':'https://openalex.org/S123','issn':['0006-341X']})
            return httpx.Response(200,json={'results':[{'id':'https://openalex.org/W123','title':'Learning'}],
                                          'meta':{'count':1,'next_cursor':None}})
        with DiscoveryClient('openalex',transport=httpx.MockTransport(response),interval=0) as client:
            found=client.discover(SourceScope('journal','Journal',issns=identifiers),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
        assert len(found.records)==1 and found.status=='partial'
        assert any('1541-0420' in value for value in found.limitations)
        assert requests[-1].url.params['filter'].startswith('primary_location.source.id:S123,')


def test_openalex_journal_issue_is_not_a_paper_candidate():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as client:
        found=client.normalize({'id':'https://openalex.org/W123','title':'Whole issue',
            'primary_location':{'raw_type':'journal-issue'}},SourceScope('journal','Journal'))
    assert found is None


def test_openalex_request_scopes_native_keywords_source_and_dates():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests = []
    def handler(request):
        requests.append(request)
        if '/sources/' in request.url.path:
            return httpx.Response(200, json={'id':'https://openalex.org/S123','issn':['1234-567X']})
        return httpx.Response(200, json={'results':[{'id':'https://openalex.org/W1','doi':'https://doi.org/10.1234/native', 'title':'Title without search words','publication_date':'2026-01-02'}], 'meta':{'count':1,'next_cursor':None}})
    with DiscoveryClient('openalex', transport=httpx.MockTransport(handler), interval=0) as client:
        result=client.discover(SourceScope('journal','Journal',issns=('1234-567X',)),parse_keyword_expression('statist* AND (learning OR "graph model")'),date(2026,1,1),date(2026,2,28))
    assert result.status == 'complete'
    assert len(result.records) == 1 # Native hits are not subjected to a second local filter.
    params = requests[-1].url.params
    assert params['search.title_abstract_keywords.exact'] == '(statist* AND (learning OR "graph model"))'
    assert 'search' not in params and 'search.exact' not in params
    assert 'primary_location.source.id:S123' in params['filter']
    assert 'from_publication_date:2026-01-01' in params['filter']
    assert 'to_publication_date:2026-02-28' in params['filter']


def test_dblp_pages_accessible_window_and_marks_upstream_truncation():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests=[]
    def handler(request):
        requests.append(request)
        offset=int(request.url.params['f'])
        return httpx.Response(200,json={'result':{'hits':{'@total':'4','@computed':'2','@first':str(offset),'hit':[{'info':{'key':f'journals/test/{offset}','title':'Graph learning','year':'2026','doi':f'10.1234/{offset}'}}]}}})
    with DiscoveryClient('dblp',transport=httpx.MockTransport(handler),interval=0,page_size=1) as client:
        result=client.discover(SourceScope('journal','Test',stream='streams/journals/test'),parse_keyword_expression('"graph learning" OR statist*'),date(2026,1,1),date(2026,3,31))
    assert result.status == 'partial'
    assert len(result.records)==2
    assert [r.url.params['f'] for r in requests]==['0','1']
    assert all('streamid:journals/test:' in r.url.params['q'] and 'year:2026:' in r.url.params['q'] for r in requests)
    assert any('computed' in s for s in result.limitations)
    assert any('year' in s for s in result.limitations)


def test_dblp_html_verification_is_failed_not_empty_and_no_retry():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    calls=[]
    with DiscoveryClient('dblp',transport=httpx.MockTransport(lambda r:(calls.append(r) or httpx.Response(202,text='<html>Anubis challenge</html>'))),interval=0) as client:
        result=client.discover(SourceScope('conference','NeurIPS',stream='streams/conf/nips'),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='failed'
    assert 'access limited' in result.limitations[0]
    assert len(calls)==1


def test_europe_pmc_scoped_request_keeps_source_identity_and_indexed_terms():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'hitCount':1,'resultList':{'result':[{'id':'42','source':'AGR','title':'A native hit','firstPublicationDate':'2026-02-01','keywordList':{'keyword':['indexed term']},'journalInfo':{'journal':{'issn':'1234-567X'}}}]}})
    with DiscoveryClient('europe_pmc',transport=httpx.MockTransport(handler),interval=0) as client:
        result=client.discover(SourceScope('journal','Test',issns=('1234-567X',)),parse_keyword_expression('learning OR inference'),date(2026,1,1),date(2026,2,28))
    assert result.status=='complete'
    assert result.records[0].external_ids.model_dump()['europe_pmc']=='AGR:42'
    assert not result.records[0].author_keywords
    q=requests[0].url.params['query']
    assert '(TITLE_ABS:learning OR KW:learning)' in q
    assert 'ISSN:1234-567X' in q and 'FIRST_PDATE:[2026-01-01 TO 2026-02-28]' in q
    assert requests[0].url.host=='www.ebi.ac.uk'


def test_zbmath_verifies_issn_serial_mapping_and_excludes_review_query_and_abstract():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests=[]
    def handler(request):
        requests.append(request)
        if '/serial/' in request.url.path:
            return httpx.Response(200,json={'result':[{'id':77,'issn':['1234-567X']}], 'status':{'nr_total_results':1,'execution_bool':True}})
        return httpx.Response(200,json={'result':[{'id':123,'title':{'title':'Native hit'},'year':'2026','editorial_contributions':[{'text':'Review text'}],'license':['https://creativecommons.org/licenses/by/4.0/']}], 'status':{'nr_total_results':1,'execution_bool':True}})
    with DiscoveryClient('zbmath',transport=httpx.MockTransport(handler),interval=0) as client:
        result=client.discover(SourceScope('journal','Test',issns=('1234-567X',)),parse_keyword_expression('learning AND statist*'),date(2026,1,1),date(2026,2,28))
    assert result.status=='partial'
    assert result.records[0].abstract is None
    assert result.records[0].provenance.licenses==('https://creativecommons.org/licenses/by/4.0/',)
    assert result.records[0].external_ids.model_dump()['zbmath']=='123'
    q=requests[-1].url.params['search_string']
    assert 'se:77' in q and 'py:2026-2026' in q
    assert '(ti:learning | ut:learning | cc:learning)' in q
    assert 'ab:' not in q and 'any:' not in q


import pytest

@pytest.mark.parametrize('mode,expected,count', [('empty','empty',0),('repeated','partial',1),('failure','partial',1)])
def test_dblp_pagination_outcomes_preserve_valid_partial_records(mode,expected,count):
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    calls=[]
    def handler(request):
        calls.append(request)
        offset=int(request.url.params['f'])
        if mode=='failure' and offset:
            return httpx.Response(503)
        if mode=='empty':
            hits={'@total':'0','@computed':'0','@first':'0'}
        else:
            hits={'@total':'3','@computed':'3','@first':'0' if mode=='repeated' else str(offset),
                  'hit':[{'info':{'key':f'journals/test/{offset}','title':'Learning','year':'2026'}}]}
        return httpx.Response(200,json={'result':{'hits':hits}})
    with DiscoveryClient('dblp',transport=httpx.MockTransport(handler),interval=0,sleep=lambda _:None,page_size=1) as client:
        result=client.discover(SourceScope('journal','Test',stream='streams/journals/test'),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status==expected
    assert len(result.records)==count
    assert len(calls)==(4 if mode=='failure' else 2 if mode=='repeated' else 1)


def test_dblp_respects_retry_after_and_stops_after_bounded_retries():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    calls,sleeps=[],[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={'Retry-After':'2'})
    with DiscoveryClient('dblp',transport=httpx.MockTransport(handler),interval=0,sleep=sleeps.append) as client:
        result=client.discover(SourceScope('conference','NeurIPS',stream='streams/conf/nips'),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='failed'
    assert len(calls)==3 and sleeps==[2,2]


def test_cancellation_during_response_stops_pagination_and_keeps_cancelled_state():
    from threading import Event
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    cancel=Event();calls=[]
    def handler(request):
        calls.append(request);cancel.set()
        return httpx.Response(200,json={'result':{'hits':{'@total':'1','@computed':'1','@first':'0','hit':[]}}})
    with DiscoveryClient('dblp',transport=httpx.MockTransport(handler),interval=0,cancel_event=cancel) as client:
        result=client.discover(SourceScope('conference','NeurIPS',stream='streams/conf/nips'),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='cancelled'
    assert not result.records and len(calls)==1


def test_unmapped_dblp_journal_reports_not_run_without_network():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    with DiscoveryClient('dblp',transport=httpx.MockTransport(lambda _:pytest.fail('Unmapped source queried')),interval=0) as client:
        result=client.discover(SourceScope('journal','Test',issns=('0006-341X',)),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='skipped'


def test_conference_year_stays_year_and_month_query_reports_partial_precision():
    from allfold.providers.integrated import DiscoveryClient,SourceScope
    from allfold.canonicalize import canonicalize_records
    def handler(request):
        return httpx.Response(200,json={'result':{'hits':{'@total':'1','@computed':'1','@first':'0','hit':[{'info':{'key':'conf/icml/Example26','title':'Learning','year':'2026'}}]}}})
    with DiscoveryClient('dblp',transport=httpx.MockTransport(handler),interval=0) as client:
        result=client.discover(SourceScope('conference','ICML','conf_1',stream='streams/conf/icml'),parse_keyword_expression('learning'),date(2026,2,1),date(2026,2,28))
    assert result.status=='partial'
    paper=canonicalize_records(result.records).papers[0]
    assert paper.metadata.publication_date=='2026'
    assert paper.metadata.conference=='ICML' and paper.metadata.journal is None
    assert paper.metadata.accepted_at is None
    assert paper.external_ids.model_dump()['dblp']=='conf/icml/Example26'


def test_zbmath_license_placeholders_are_missing_metadata_not_paper_content():
    from allfold.providers.integrated import DiscoveryClient,SourceScope
    placeholder='zbMATH Open Web Interface contents unavailable due to conflicting licenses.'
    raw={'id':8053521,'year':'2025','title':{'title':placeholder},'keywords':[placeholder],
         'contributors':{'authors':[{'name':placeholder}]},'msc':[{'code':'62-XX','text':'Statistics'}],
         'links':[{'type':'doi','identifier':'10.1080/01621459.2024.2393463'},{'type':'arxiv','identifier':'2209.04977'}]}
    with DiscoveryClient('zbmath',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={})),interval=0) as client:
        record=client.normalize(raw,SourceScope('journal','JASA'))
    assert record.title is None and not record.authors
    assert [x.value for x in record.indexed_terms]==['62-XX']
    assert record.external_ids.doi=='10.1080/01621459.2024.2393463'
    assert record.external_ids.arxiv=='2209.04977'


def test_dblp_explicit_electronic_edition_dois_remain_known_identifiers():
    from allfold.providers.integrated import DiscoveryClient,SourceScope
    with DiscoveryClient('dblp',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as client:
        record=client.normalize({'key':'conf/icml/test26','title':'Learning','year':'2026','ee':['https://doi.org/10.5555/main','https://doi.org/10.5555/other']},SourceScope('conference','ICML','conf_1',stream='streams/conf/icml'))
    assert record.external_ids.doi=='10.5555/main'
    assert record.related_dois==('10.5555/other',)
