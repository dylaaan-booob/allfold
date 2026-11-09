from datetime import date
import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.config import JournalConfig


@pytest.mark.parametrize('timeout', [httpx.ReadTimeout, httpx.ConnectTimeout])
def test_timeout_retries_native_request_and_reports_progress(timeout):
    from allfold.providers.integrated import DiscoveryClient
    calls, waits, events = [], [], []
    def response(request):
        calls.append(request)
        if len(calls) == 1:
            raise timeout('synthetic-secret', request=request)
        return httpx.Response(200, text='<feed/>')
    with DiscoveryClient('arxiv', transport=httpx.MockTransport(response), interval=0,
            sleep=waits.append, progress_callback=events.append) as client:
        client.begin_completion()
        assert client.request('/api/query', {'id_list':'2505.01146'}, response_format='xml') == '<feed/>'
    assert len(calls)==2 and waits==[5]
    retries=[event.activity for event in events if event.activity and event.activity.kind.value=='RETRYING']
    assert len(retries)==1 and retries[0].operation=='native-version-retry'
    assert 'Retry 2/3' in retries[0].label and 'Retry 2/3' in retries[0].detail
    assert 'synthetic-secret' not in repr(events)


@pytest.mark.parametrize('cancelled', [None, 'response', 'backoff'])
def test_timeout_retry_is_bounded_and_cancellable(cancelled):
    from threading import Event
    from allfold.providers.integrated import DiscoveryClient, Cancelled, DiscoveryError
    signal, calls, waits = Event(), [], []
    def response(request):
        calls.append(request)
        if cancelled=='response':signal.set()
        raise httpx.ReadTimeout('synthetic-secret', request=request)
    def wait(seconds):
        waits.append(seconds)
        if cancelled=='backoff':signal.set()
    with DiscoveryClient('arxiv', transport=httpx.MockTransport(response), interval=0,
            sleep=wait, cancel_event=signal) as client:
        with pytest.raises(Cancelled if cancelled else DiscoveryError) as error:
            client.request('/api/query', {'id_list':'2505.01146'}, response_format='xml')
    assert len(calls)==(1 if cancelled else 3)
    assert waits==([] if cancelled=='response' else [5] if cancelled else [5,10])
    assert 'synthetic-secret' not in str(error.value)


def test_non_timeout_network_error_is_not_automatically_replayed():
    from allfold.providers.integrated import DiscoveryClient, DiscoveryError
    calls, waits = [], []
    def response(request):
        calls.append(request)
        raise httpx.ConnectError('synthetic-secret', request=request)
    with DiscoveryClient('arxiv', transport=httpx.MockTransport(response), interval=0, sleep=waits.append) as client:
        with pytest.raises(DiscoveryError) as error:
            client.request('/api/query', {'id_list':'2505.01146'})
    assert len(calls)==1 and not waits and 'synthetic-secret' not in str(error.value)


def test_openalex_null_source_completion_keeps_other_providers_hit():
    from allfold.application.metadata_completion import complete_metadata
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.providers.integrated import DiscoveryClient
    from datetime import datetime, timezone
    original = ProviderWorkEvidence(title='Native hit', journal='Journal', external_ids=ExternalIds(doi='10.5555/null'),
        provenance=MetadataSource(provider='europe_pmc', record_id='MED:42', retrieved_at=datetime.now(timezone.utc),role='discovery'))
    raw={'id':'https://openalex.org/W123','doi':'https://doi.org/10.5555/null','title':'Native hit','primary_location':None}
    with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'results':[raw], 'meta':{'count':1}})),interval=0) as client:
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


def test_work_level_biomedical_ids_do_not_merge_formal_doi_free_records():
    from allfold.canonicalize import canonicalize_records, completion_metadata
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    for ids, epmc in (({'pmid':'https://pubmed.ncbi.nlm.nih.gov/123/'},{'source':'MED','id':'123'}),
                      ({'pmcid':'https://www.ncbi.nlm.nih.gov/pmc/articles/PMC456/'},{'source':'MED','id':'999','pmcid':'PMC456'})):
        with DiscoveryClient('openalex',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as oa, \
             DiscoveryClient('europe_pmc',transport=httpx.MockTransport(lambda _:httpx.Response(200,json={}))) as europe:
            left=oa.normalize({'id':'https://openalex.org/W123','title':'No DOI','ids':ids},SourceScope('journal','Journal'))
            right=europe.normalize(dict(epmc,title='No DOI'),SourceScope('journal','Journal'))
        assert len(canonicalize_records((left,right)).papers)==2
        assert left.external_ids.model_dump().get(next(iter(ids))) is None


def test_openalex_rejects_work_without_returned_primary_journal_identity():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests=[]
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda request: requests.append(request) or httpx.Response(200,
        json={'results':[{'id':'https://openalex.org/W123','title':'Learning'}], 'meta':{'count':1}})), interval=0) as client:
        found=client.discover(SourceScope('journal','Journal',issns=('0006-341X','1541-0420')),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert not found.records and found.status=='failed'
    assert any('primary journal identity' in value for value in found.limitations)
    assert len(requests)==1 and requests[0].url.path=='/works'


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
        return httpx.Response(200, json={'results':[{'id':'https://openalex.org/W1','doi':'https://doi.org/10.1234/native', 'title':'Title without search words','publication_date':'2026-01-02','primary_location':{'source':{'issn':['1234-567X']}}}], 'meta':{'count':1,'next_cursor':None}})
    with DiscoveryClient('openalex', transport=httpx.MockTransport(handler), interval=0) as client:
        result=client.discover(SourceScope('journal','Journal',issns=('1234-567X',)),parse_keyword_expression('statist* AND (learning OR "graph model")'),date(2026,1,1),date(2026,2,28))
    assert result.status == 'complete'
    assert len(result.records) == 1 # Native hits are not subjected to a second local filter.
    params = requests[-1].url.params
    assert params['search.title_abstract_keywords.exact'] == '(statist* AND (learning OR "graph model"))'
    assert 'search' not in params and 'search.exact' not in params
    assert 'primary_location.source.issn:1234-567X' in params['filter']
    assert len(requests)==1
    assert 'from_publication_date:2026-01-01' in params['filter']
    assert 'to_publication_date:2026-02-28' in params['filter']


def test_europe_pmc_discovery_refuses_without_network_but_exact_lookup_remains():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={'hitCount':1,'resultList':{'result':[{'id':'42','source':'MED','title':'A known record','keywordList':{'keyword':['indexed term']}}]}})
    with DiscoveryClient('europe_pmc',transport=httpx.MockTransport(handler),interval=0) as client:
        result=client.discover(SourceScope('journal','Test',issns=('1234-567X',)),parse_keyword_expression('learning'),date(2026,1,1),date(2026,2,28))
        assert result.status=='failed' and not requests
        record=client.lookup('pmid','42')[0]
    assert record.external_ids.model_dump()['pmid']=='42'
    assert record.indexed_terms[0].value=='indexed term'
    assert 'EXT_ID:"42" AND SRC:MED' in requests[0].url.params['query']


def test_cancellation_during_response_stops_pagination_and_keeps_cancelled_state():
    from threading import Event
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    cancel=Event();calls=[]
    def handler(request):
        calls.append(request);cancel.set()
        return httpx.Response(200,json={'hitCount':0,'resultList':{'result':[]}})
    with DiscoveryClient('pubmed',transport=httpx.MockTransport(handler),interval=0,cancel_event=cancel) as client:
        result=client.discover(SourceScope('journal','Journal',issns=('1234-567X',)),parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status=='cancelled'
    assert not result.records and len(calls)==1


def test_openalex_locations_supply_preprint_ids_without_guessing_from_accepted_version():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    from allfold.canonicalize import canonicalize_records, completion_metadata
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
    from allfold.canonicalize import canonicalize_records, completion_metadata
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(lambda _: pytest.fail('Normalization made a request'))) as client:
        formal = client.normalize({'source': 'MED', 'id': '42', 'doi': '10.5555/formal', 'title': 'Formal',
            'firstPublicationDate': '2026-01-01', 'abstractText': 'Formal abstract',
            'authorList': {'author': [{'fullName': 'Formal author'}]}, 'commentCorrectionList': {'commentCorrection': [
                {'type': 'Preprint in', 'source': 'PPR', 'id': 'PPR3'},
                {'type': 'Erratum in', 'source': 'MED', 'id': '99'},
            ]}}, SourceScope('journal', 'Journal'))
        preprint = client.normalize({'source': 'PPR', 'id': 'PPR3', 'title': 'Preprint', 'versionNumber': '3',
            'firstPublicationDate': '2025-09-01', 'versionList': {'version': versions}}, SourceScope('journal', ''))
    assert [(ref.provider, ref.record_id) for ref in formal.related_ids] == [('europe_pmc', 'PPR:PPR3')]
    assert len(canonicalize_records((formal, preprint)).papers) == 2
    paper = completion_metadata((formal, preprint))
    assert paper.doi == '10.5555/formal' and paper.metadata.first_public_at == expected
    assert any(d.record_id == 'PPR:PPR3' and d.version == '3' and d.year == 2025 for d in paper.date_evidence)
    if expected:
        assert any(d.record_id == 'PPR:PPR1' and d.first_version and d.day is None for d in paper.date_evidence)
        from allfold.application.metadata_completion import complete_metadata
        class Forbidden:
            def lookup(self, *_):
                pytest.fail('Sufficient aggregate version history triggered a native lookup')
        result = complete_metadata((formal, preprint), ('arxiv', 'biorxiv', 'medrxiv'),
            clients=dict.fromkeys(('arxiv', 'biorxiv', 'medrxiv'), Forbidden()))
        assert not result.lookups


@pytest.mark.parametrize('provider', ['dblp', 'zbmath'])
def test_disabled_or_removed_provider_cannot_construct_a_network_client(provider):
    from allfold.providers.integrated import DiscoveryClient
    with pytest.raises(ValueError, match='Provider'):
        DiscoveryClient(provider, transport=httpx.MockTransport(lambda _: pytest.fail('Disabled provider made a request')))


@pytest.mark.parametrize('second_first,expected', [(True, '2020-06'), (False, None)])
def test_europe_pmc_relation_aliases_identify_each_target_without_joining_distinct_preprints(second_first, expected):
    from datetime import datetime, timezone
    from allfold.models import EvidenceDate, EvidenceDateKind, ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    from allfold.canonicalize import canonicalize_records, completion_metadata
    raw = {'source': 'MED', 'id': '42', 'doi': '10.5555/formal', 'title': 'Formal',
        'commentCorrectionList': {'commentCorrection': [
            {'type': 'Preprint in', 'source': 'PPR', 'id': f'PPR{number}', 'doi': f'10.1101/{number}'} for number in (1, 2)]}}
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(lambda _: pytest.fail('Unexpected request'))) as client:
        formal = client.normalize(raw, SourceScope('journal', 'Journal'))
    preprints = tuple(ProviderWorkEvidence(provenance=MetadataSource(provider='biorxiv', record_id=f'10.1101/{number}:1',
        retrieved_at=datetime.now(timezone.utc)), title='Preprint', publication_type='preprint', external_ids=ExternalIds(doi=f'10.1101/{number}'),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2020 if number == 1 else 2021, month=6,
            first_version=number == 1 or second_first),)) for number in (1, 2))
    assert len(canonicalize_records((formal, *preprints)).papers) == 3
    paper = completion_metadata((formal, *preprints))
    assert paper.metadata.first_public_at == expected


@pytest.mark.parametrize('failure', ['http', 'timeout'])
def test_final_settlement_retries_only_the_failed_redirect_target(failure):
    from allfold.providers.integrated import DiscoveryClient, DiscoveryError

    calls = []
    def respond(request):
        calls.append((request.url.host, request.url.path))
        if request.url.host == 'api.openalex.org':
            assert request.headers['Authorization'] == 'Bearer synthetic-key'
            return httpx.Response(302, headers={'Location': 'https://fixture.invalid/target'})
        assert 'Authorization' not in request.headers
        if calls.count(('fixture.invalid', '/target')) < 4:
            if failure == 'timeout':
                raise httpx.ReadTimeout('fixture timeout')
            return httpx.Response(503)
        return httpx.Response(200, json={'results': []})

    with DiscoveryClient('openalex', api_key='synthetic-key', transport=httpx.MockTransport(respond),
            interval=0, sleep=lambda _: None) as client:
        with client.capture_transient_failures() as failures:
            with pytest.raises(DiscoveryError):
                client.request('/works', {})
        assert failures
        client.begin_settlement()
        assert client.request('/works', {}) == {'results': []}
        assert client.request('/works', {}) == {'results': []}
        assert client.request_count == len(calls) == 7
    assert calls == [('api.openalex.org', '/works'), ('fixture.invalid', '/target')] * 3 + [
        ('fixture.invalid', '/target')]


def test_cancellation_before_redirect_stops_dispatch_and_does_not_count_it():
    from threading import Event

    from allfold.providers.integrated import Cancelled, DiscoveryClient

    cancel, calls = Event(), []
    def respond(request):
        calls.append(request.url.path)
        cancel.set()
        return httpx.Response(302, headers={'Location': '/target'})

    with DiscoveryClient('openalex', cancel_event=cancel, transport=httpx.MockTransport(respond),
            interval=0) as client:
        with pytest.raises(Cancelled):
            client.request('/works', {})
        assert client.request_count == 1
    assert calls == ['/works']
