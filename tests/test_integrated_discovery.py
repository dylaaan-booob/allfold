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
        provenance=MetadataSource(provider='europe_pmc',record_id='MED:42',retrieved_at=datetime.now(timezone.utc)))
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


import pytest


def test_cancellation_during_response_stops_pagination_and_keeps_cancelled_state():
    from threading import Event
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    cancel=Event();calls=[]
    def handler(request):
        calls.append(request);cancel.set()
        return httpx.Response(200,json={'hitCount':0,'resultList':{'result':[]}})
    with DiscoveryClient('europe_pmc',transport=httpx.MockTransport(handler),interval=0,cancel_event=cancel) as client:
        result=client.discover(SourceScope('journal','Journal',issns=('1234-567X',)),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='cancelled'
    assert not result.records and len(calls)==1


def test_openalex_locations_supply_preprint_ids_without_guessing_from_accepted_version():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    from allfold.canonicalize import canonicalize_records
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda _: pytest.fail('Normalization made a request'))) as client:
        record = client.normalize({'id': 'https://openalex.org/W42', 'title': 'Formal', 'publication_date': '2026-02',
            'related_works': ['https://openalex.org/W99'], 'locations': [
                {'landing_page_url': 'https://arxiv.org/abs/2201.12345v3', 'pdf_url': 'https://arxiv.org/pdf/2201.12345v3.pdf',
                 'source': {'id': 'https://openalex.org/S4306400194', 'display_name': 'arXiv'}, 'version': 'submittedVersion'},
                {'landing_page_url': 'https://repository.example.test/record', 'version': 'acceptedVersion', 'is_accepted': True},
            ]}, SourceScope('journal', 'Journal'))
    assert [(ref.provider, ref.record_id) for ref in record.related_ids] == [('arxiv', '2201.12345')]
    assert len(record.locations) == 3 and not record.related_dois
    paper, = canonicalize_records((record,)).papers
    assert paper.metadata.first_public_at is None and not any(d.kind.value == 'accepted' for d in paper.date_evidence)


@pytest.mark.parametrize('versions,expected', [([], None), ([{'id': 'PPR1', 'source': 'PPR', 'versionNumber': '1', 'firstPublishDate': '2020-06'}], '2020-06')])
def test_europe_pmc_preserves_explicit_relations_and_per_version_dates(versions, expected):
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    from allfold.canonicalize import canonicalize_records
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(lambda _: pytest.fail('Normalization made a request'))) as client:
        formal = client.normalize({'source': 'MED', 'id': '42', 'doi': '10.5555/formal', 'title': 'Formal',
            'firstPublicationDate': '2026-01-01', 'commentCorrectionList': {'commentCorrection': [
                {'type': 'Preprint in', 'source': 'PPR', 'id': 'PPR3'},
                {'type': 'Erratum in', 'source': 'MED', 'id': '99'},
            ]}}, SourceScope('journal', 'Journal'))
        preprint = client.normalize({'source': 'PPR', 'id': 'PPR3', 'title': 'Preprint', 'versionNumber': '3',
            'firstPublicationDate': '2025-09-01', 'versionList': {'version': versions}}, SourceScope('journal', ''))
    assert [(ref.provider, ref.record_id) for ref in formal.related_ids] == [('europe_pmc', 'PPR:PPR3')]
    paper, = canonicalize_records((formal, preprint)).papers
    assert paper.doi == '10.5555/formal' and paper.metadata.first_public_at == expected
    assert any(d.record_id == 'PPR:PPR3' and d.version == '3' and d.year == 2025 for d in paper.date_evidence)
    if expected:
        assert any(d.record_id == 'PPR:PPR1' and d.first_version and d.day is None for d in paper.date_evidence)


@pytest.mark.parametrize('provider', ['dblp', 'zbmath'])
def test_disabled_or_removed_provider_cannot_construct_a_network_client(provider):
    from allfold.providers.integrated import DiscoveryClient
    with pytest.raises(ValueError, match='Provider'):
        DiscoveryClient(provider, transport=httpx.MockTransport(lambda _: pytest.fail('Disabled provider made a request')))
