from datetime import datetime, timezone

import httpx
import pytest

from allfold.canonicalize import canonicalize_records, completion_metadata, consolidate_evidence
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.supplemental import SupplementalClient


@pytest.mark.parametrize('provider', ('biorxiv', 'medrxiv'))
@pytest.mark.parametrize('status', ('service unavailable', 'Preprint for DOI 10.1093/bioinformatics not found'))
def test_native_no_match_does_not_hide_errors_or_truncated_doi(provider, status):
    from allfold.providers.integrated import DiscoveryError
    with SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'messages': [{'status': status}], 'collection': []}))) as client:
        with pytest.raises(DiscoveryError):
            client.lookup_published_preprints('10.1093/bioinformatics/btaf638')


@pytest.mark.parametrize('provider', ('biorxiv', 'medrxiv'))
def test_publication_lookup_accepts_current_native_preprint_doi_field(provider):
    def response(request):
        if request.url.path.startswith('/pubs/'):
            return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
                'preprint_doi': '10.1101/123456', 'published_doi': '10.5555/formal',
                'preprint_platform': provider, 'preprint_date': '2022-01-02',
                'published_date': '2026-01-02', 'published_journal': 'Journal',
            }]})
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': '10.1101/123456', 'published': '10.5555/formal', 'server': provider,
            'date': '2022-01-02', 'version': '1', 'title': 'Original preprint',
        }]})
    with SupplementalClient(provider, transport=httpx.MockTransport(response), interval=0) as client:
        records = client.lookup_published_preprints('10.5555/formal')
    assert records[0].external_ids.doi == '10.5555/formal'
    assert records[0].related_dois == ('10.1101/123456',)
    assert records[1].external_ids.doi == '10.1101/123456'
    assert len(consolidate_evidence(records).clusters) == 2
    paper = completion_metadata(records)
    assert paper.doi == '10.5555/formal'
    assert paper.metadata.first_public_at == '2022-01-02'


def test_crossref_uses_exact_doi_and_only_explicit_same_work_relations_and_dates():
    requests = []
    def response(request):
        requests.append(request)
        return httpx.Response(200, json={"message": {
            "DOI": "10.5555/main", "title": ["Formal paper"], "type": "journal-article",
            "container-title": ["Journal"], "author": [{"given": "A", "family": "Author"}],
            "accepted": {"date-parts": [[2025, 12, 1]]},
            "published-online": {"date-parts": [[2026, 1, 2]]},
            "indexed": {"date-parts": [[2020, 1, 1]]},
            "relation": {"has-preprint": [{"id-type": "doi", "id": "10.5555/preprint"}],
                         "is-referenced-by": [{"id-type": "doi", "id": "10.5555/unrelated"}]},
        }})
    with SupplementalClient("crossref", transport=httpx.MockTransport(response), interval=0) as client:
        records = client.lookup("doi", "10.5555/main")
    assert len(requests) == 1 and requests[0].url.path == "/works/10.5555/main"
    assert records[0].related_dois == ("10.5555/preprint",)
    paper = canonicalize_records(records).papers[0]
    assert any(d.kind.value=="accepted" and (d.year,d.month,d.day)==(2025,12,1) for d in paper.date_evidence)
    assert paper.metadata.first_public_at is None
    assert records[0].provenance.role == "supplement"


def test_arxiv_looks_up_known_id_and_keeps_first_version_date():
    requests = []
    atom = '''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry><id>http://arxiv.org/abs/2201.12345v3</id><title>Preprint title</title>
      <published>2022-01-02T00:00:00Z</published><updated>2025-01-03T00:00:00Z</updated>
      <summary>Preprint abstract</summary><author><name>A Author</name></author>
      <arxiv:doi>10.5555/formal</arxiv:doi><category term="stat.ML"/></entry></feed>'''
    with SupplementalClient("arxiv", transport=httpx.MockTransport(
            lambda request: requests.append(request) or httpx.Response(200, text=atom)), interval=0) as client:
        records = client.lookup("arxiv", "2201.12345")
    assert dict(requests[0].url.params) == {"id_list": "2201.12345", "max_results": "1"}
    assert records[0].external_ids.arxiv == "2201.12345"
    assert records[0].provenance.version == "v3"
    assert records[0].publication_date == "2022-01-02"
    assert records[0].related_dois == ("10.5555/formal",)
    paper = canonicalize_records(records).papers[0]
    assert paper.metadata.first_public_at == "2022-01-02"
    assert not any(d.kind.value=="accepted" for d in paper.date_evidence)


def test_biorxiv_follows_known_formal_doi_to_original_versions_without_year_limit():
    requests = []
    def response(request):
        requests.append(request)
        if request.url.path.startswith("/pubs/"):
            rows = [{"biorxiv_doi": "10.1101/123456", "published_doi": "10.5555/formal",
                     "published_journal": "Journal", "preprint_title": "Preprint", "preprint_date": "2022-01-02",
                     "published_date": "2026-01-02", "preprint_platform": "bioRxiv"}]
        else:
            rows = [{"doi": "10.1101/123456", "title": "Preprint", "date": date, "version": version,
                     "server": "bioRxiv", "published": "10.5555/formal", "category": "neuroscience",
                     "abstract": "Original metadata"} for date, version in (("2022-01-02", "1"), ("2024-01-02", "2"))]
        return httpx.Response(200, json={"messages": [{"status": "ok"}], "collection": rows})
    with SupplementalClient("biorxiv", transport=httpx.MockTransport(response), interval=0) as client:
        records = client.lookup_published_preprints("10.5555/formal")
    assert [r.url.path for r in requests] == ["/pubs/biorxiv/10.5555/formal/na/json", "/details/biorxiv/10.1101/123456/na/json"]
    formal = ProviderWorkEvidence(provenance=MetadataSource(provider="europe_pmc", record_id="MED:42",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role="discovery"),
        title="Formal", journal="Journal", publication_date="2026-01-02", publication_type="journal",
        monitor_journal_issns=("0006-341X",), external_ids=ExternalIds(doi="10.5555/formal"))
    result = canonicalize_records((formal, *records))
    assert not result.issues
    assert len(result.papers) == 2
    paper = completion_metadata((formal, *records))
    assert paper.doi == "10.5555/formal"
    assert paper.metadata.publication_date == "2026-01-02"
    assert paper.metadata.first_public_at == "2022-01-02"
    assert any(d.kind.value=="published-online" and (d.year,d.month,d.day)==(2026,1,2) for d in paper.date_evidence)


def test_preprint_version_changes_are_evidence_not_conflicting_snapshots():
    rows=[{"doi":"10.1101/123456","title":title,"date":day,"version":version,"server":"medRxiv"}
          for title,day,version in (("First title","2022-01-02","1"),("Revised title","2024-01-02","2"))]
    with SupplementalClient("medrxiv",transport=httpx.MockTransport(lambda _:httpx.Response(200,
        json={"messages":[{"status":"ok"}],"collection":rows})),interval=0) as client:
        result=canonicalize_records(client.lookup("doi","10.1101/123456"))
    assert not result.issues and len(result.papers)==1
    assert result.papers[0].metadata.first_public_at=="2022-01-02"
    assert not any(d.publication_type=="journal" and d.kind.value=="accepted" for d in result.papers[0].date_evidence)


def test_crossref_conference_acceptance_does_not_enter_journal_dates():
    from allfold.paper_dates import journal_dates
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'message': {'DOI': '10.5555/conference', 'type': 'proceedings-article', 'title': ['Conference Paper'],
            'event': {'name': 'Conference'}, 'accepted': {'date-parts': [[2026, 5, 1]]}}}))) as client:
        paper, = canonicalize_records(client.lookup('doi', '10.5555/conference')).papers
    assert paper.metadata.publication_type == 'conference'
    assert any(item.kind.value == 'accepted' and item.publication_type == 'conference' for item in paper.date_evidence)
    assert not journal_dates(paper.date_evidence)


def test_crossref_distinct_publication_fields_are_not_conflicting_snapshots():
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'message': {'DOI':'10.5555/formal', 'type':'journal-article', 'title':['Formal'],
            'published':{'date-parts':[[2026,9,28]]}, 'issued':{'date-parts':[[2026,9,28]]},
            'published-online':{'date-parts':[[2026,9,28]]}, 'published-print':{'date-parts':[[2026,10,2]]}}}))) as client:
        records = client.lookup('doi', '10.5555/formal')
    result = canonicalize_records(records)
    assert not result.issues
    paper, = result.papers
    assert {(d.source_label,d.month,d.day) for d in paper.date_evidence if d.kind.value=='published'} == {
        ('published',9,28), ('issued',9,28), ('published-print',10,2)}
    changed = records[0].model_copy(update={'dates':tuple(
        d.model_copy(update={'day':29}) if d.source_label=='published' else d for d in records[0].dates)})
    conflicting = canonicalize_records((*records, changed))
    assert any(issue.stage=='date_conflict' and 'published date' in issue.message for issue in conflicting.issues)


def test_explicit_crossref_preprint_relation_without_date_keeps_first_public_unsettled():
    from allfold.models import EvidenceDate, EvidenceDateKind
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'message': {'DOI': '10.5555/formal', 'type': 'journal-article', 'title': ['Formal'],
            'relation': {'has-preprint': [{'id-type': 'doi', 'id': key} for key in ('10.5555/first', '10.5555/unknown')]}}}))) as client:
        formal, = client.lookup('doi', '10.5555/formal')
    first = ProviderWorkEvidence(provenance=MetadataSource(provider='crossref', record_id='10.5555/first',
        retrieved_at=datetime.now(timezone.utc)), title='First preprint', publication_type='preprint',
        external_ids=ExternalIds(doi='10.5555/first'),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),))
    paper = completion_metadata((formal, first))
    assert paper.metadata.first_public_at is None
    assert any(ref.record_id == '10.5555/unknown' and ref.relation == 'preprint' for ref in formal.related_ids)


@pytest.mark.parametrize('malformed', [False, True])
def test_native_details_reuses_no_match_but_allows_retry_after_failure(malformed):
    from allfold.providers.integrated import DiscoveryError
    calls = []
    def response(request):
        calls.append(request.url.path)
        rows = [{'preprint_doi': '10.1101/123456', 'published_doi': '10.5555/formal'}] if '/pubs/' in request.url.path else (
            'invalid collection' if malformed else [])
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': rows})
    with SupplementalClient('biorxiv', interval=0, transport=httpx.MockTransport(response)) as client:
        if malformed:
            with pytest.raises(DiscoveryError):
                client.lookup_published_preprints('10.5555/formal')
            with pytest.raises(DiscoveryError):
                client.lookup('doi', '10.1101/123456')
        else:
            client.lookup_published_preprints('10.5555/formal')
            assert client.lookup('doi', '10.1101/123456') == ()
    details = '/details/biorxiv/10.1101/123456/na/json'
    assert calls == ['/pubs/biorxiv/10.5555/formal/na/json', *([details] * (2 if malformed else 1))]


def test_crossref_explicit_preprint_versions_keep_dates_without_native_first_version_proof():
    def response(request):
        first = request.url.path.endswith('/10.5555/v1')
        doi, related = ('10.5555/v1', '10.5555/v2') if first else ('10.5555/v2', '10.5555/v1')
        return httpx.Response(200, json={'message': {'DOI': doi, 'type': 'posted-content', 'title': ['Preprint'],
            'version': '1' if first else '2', 'posted': {'date-parts': [[2021 if first else 2022, 6]]},
            'relation': {'has-version' if first else 'is-version-of': [{'id-type': 'doi', 'id': related}]}}})
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(response)) as client:
        records = client.lookup('doi', '10.5555/v2') + client.lookup('doi', '10.5555/v1')
    assert len(canonicalize_records(records).papers) == 2
    paper = completion_metadata(records)
    assert paper.metadata.first_public_at is None
    assert {(item.version, item.year) for item in paper.date_evidence} == {('1', 2021), ('2', 2022)}


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
        records = client.lookup_published_preprints('10.5555/formal')
    assert len(calls) == 18
    assert {record.external_ids.doi for record in records} == {'10.5555/formal'} | {
        f'10.1101/{n:06}' for n in range(17)}


def test_arxiv_batches_all_ids_and_maps_unordered_partial_duplicate_entries():
    ids = [f'2201.{number:05}' for number in range(205)]
    calls = []
    def response(request):
        requested = request.url.params['id_list'].split(',')
        calls.append(requested)
        entries = ''.join(f'<entry><id>https://arxiv.org/abs/{key}v3</id><title>Title</title>'
            '<published>2022-01-02T00:00:00Z</published><updated>2025-01-01T00:00:00Z</updated></entry>'
            for key in [*reversed(requested[1:]), requested[-1], '2301.99999'])
        return httpx.Response(200, text=f'<feed xmlns="http://www.w3.org/2005/Atom">{entries}</feed>')
    with SupplementalClient('arxiv', interval=0, transport=httpx.MockTransport(response)) as client:
        results = client.lookup_many('arxiv', ids)
    assert sum(map(len,calls)) == 205 and len(calls) == 2
    assert set(results) == set(ids)
    assert all(len(results[key]) == 1 and results[key][0].publication_date == '2022-01-02'
        for key in ids if key not in {group[0] for group in calls})
    assert all(isinstance(results[group[0]], Exception) for group in calls)


def test_crossref_named_arxiv_and_official_uri_relations_reject_untrusted_shapes():
    relations = {'has-preprint': [
        {'id-type':'arxiv','id':'2201.12345v2'},
        {'id-type':'uri','id':'https://www.medrxiv.org/content/10.1101/2022.01.01.123456v3.full.pdf'},
        {'id-type':'uri','id':'https://evil.example/arxiv.org/abs/1901.12345'},
        {'id-type':'uri','id':'https://arxiv.org@evil.example/abs/1901.12345'},
        {'id-type':'uri','id':'https://arxiv.org/abs/1901.12345?track=1'}, None],
        'is-referenced-by':[{'id-type':'arxiv','id':'1801.12345'}]}
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(lambda request:
        httpx.Response(200,json={'message':{'DOI':'10.5555/main','title':['Formal'],'type':'journal-article','relation':relations}}))) as client:
        record, = client.lookup('doi','10.5555/main')
    assert {(ref.provider,ref.record_id,ref.relation) for ref in record.related_ids} == {
        ('arxiv','2201.12345','preprint'),('medrxiv','10.1101/2022.01.01.123456','preprint')}


def test_arxiv_batch_cancellation_stops_later_groups_and_does_not_cache_forever():
    from threading import Event
    from allfold.providers.integrated import Cancelled
    signal, calls = Event(), []
    def response(request):
        calls.append(request)
        signal.set()
        return httpx.Response(200,text='<feed xmlns="http://www.w3.org/2005/Atom"/>')
    with SupplementalClient('arxiv',interval=0,cancel_event=signal,transport=httpx.MockTransport(response)) as client:
        results = client.lookup_many('arxiv',[f'2201.{index:05}' for index in range(201)])
    assert len(calls) == 1 and len(results) == 201
    assert all(isinstance(result,Cancelled) for result in results.values())


def test_arxiv_batch_service_failure_isolated_from_later_groups_and_atom_error():
    calls = []
    def response(request):
        ids = request.url.params['id_list'].split(','); calls.append(ids)
        if len(ids) > 1:
            return httpx.Response(200,text='<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/api/errors#bad</id></entry></feed>')
        return httpx.Response(200,text=f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/{ids[0]}v1</id><published>2022-01-02T00:00:00Z</published></entry></feed>')
    with SupplementalClient('arxiv',interval=0,transport=httpx.MockTransport(response)) as client:
        results = client.lookup_many('arxiv',[f'2201.{index:05}' for index in range(201)])
    assert len(calls) == 2
    assert all(isinstance(results[f'2201.{index:05}'],Exception) for index in range(200))
    assert results['2201.00200'][0].publication_date == '2022-01-02'


def test_arxiv_next_group_rechecks_operation_ownership_before_network():
    from allfold.persistence.safe_write import ContentChangedError
    calls=[]
    with SupplementalClient('arxiv',interval=0,transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(200,text='<feed xmlns="http://www.w3.org/2005/Atom"/>'))) as client:
        def guard():
            if calls:
                raise ContentChangedError('Configuration changed')
        client.request_guard=guard
        results=client.lookup_many('arxiv',[f'2201.{index:05}' for index in range(201)])
    assert len(calls)==1
    assert all(isinstance(value,ContentChangedError) for value in results.values())


@pytest.mark.parametrize('labels', [
    ('issued', 'published-print', 'published'), ('published-print', 'published', 'issued'),
    ('published', 'issued', 'published-print'), ('issued', 'published-print'), ('issued',),
])
def test_crossref_publication_selection_uses_native_label_priority_not_response_order(labels):
    years = {'issued': 2024, 'published-print': 2025, 'published': 2026}
    raw = {'DOI': '10.5555/main', 'title': ['Paper'], 'type': 'journal-article',
        **{label: {'date-parts': [[years[label]]]} for label in labels}}
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'message': raw}))) as client:
        record, = client.lookup('doi', '10.5555/main')
    assert record.publication_date == ('2026' if 'published' in labels else '2025' if 'published-print' in labels else '2024')
    assert {(item.source_label, item.year) for item in record.dates} == {(label, years[label]) for label in labels}


@pytest.mark.parametrize('invalid_first', [False, True])
def test_arxiv_batch_keeps_valid_siblings_when_one_identified_entry_cannot_be_parsed(invalid_first):
    good = '<entry><id>https://arxiv.org/abs/2201.00001v1</id><title>Good</title><published>2022-01-02T00:00:00Z</published></entry>'
    bad = '<entry><id>https://arxiv.org/abs/2201.00002v1</id><title>Bad</title><arxiv:doi/></entry>'
    atom = '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">' + (
        bad + good if invalid_first else good + bad) + '</feed>'
    with SupplementalClient('arxiv', interval=0, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, text=atom))) as client:
        results = client.lookup_many('arxiv', ['2201.00001', '2201.00002'])
    good_record, = results['2201.00001']
    assert good_record.external_ids.arxiv == '2201.00001'
    assert good_record.publication_date == '2022-01-02'
    assert isinstance(results['2201.00002'], ValueError)


def test_crossref_assertions_preserve_history_semantics_and_date_precision():
    raw = {'DOI': '10.5555/history', 'type': 'journal-article', 'title': ['Paper'],
        'published': {'date-parts': [[2026]]}, 'published-online': {'date-parts': [[2026, 2]]},
        'assertion': [
            {'name': 'received', 'label': 'Received', 'value': '17 September 2025',
             'group': {'name': 'publication_history', 'label': 'Publication History'}},
            {'name': 'accepted', 'label': 'Accepted', 'value': '2026-01',
             'group': {'name': 'ArticleHistory', 'label': 'Article history'}},
            {'name': 'received', 'label': 'Received', 'value': '31 February 2025'},
            {'name': 'created', 'label': 'Created', 'value': '2024-01-01'},
            {'name': 'other', 'label': 'Deposit accepted', 'value': '2024-01-01'},
        ]}
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={'message': raw}))) as client:
        record, = client.lookup('doi', '10.5555/history')
    assert {(item.kind.value, item.year, item.month, item.day) for item in record.dates} == {
        ('received', 2025, 9, 17), ('accepted', 2026, 1, None),
        ('published', 2026, None, None), ('published-online', 2026, 2, None)}
    assert next(item for item in record.dates if item.kind.value == 'received').source_label == 'assertion:publication_history:received:Received'


def test_crossref_batches_reverse_relations_with_explicit_target_mapping_and_cursor():
    targets = ('10.1007/s10462-026-11743-y', '10.5555/second')
    calls = []
    def response(request):
        calls.append(request)
        assert request.url.path == '/works'
        filters = request.url.params['filter']
        assert all('relation.object:' + target in filters for target in targets)
        page = request.url.params['cursor']
        rows = ([{'DOI': '10.21203/rs.3.rs-8330917/v1', 'title': ['Preprint'], 'type': 'posted-content',
            'posted': {'date-parts': [[2025, 12, 4]]}, 'version': '1',
            'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': targets[0]}]}}] if page == '*' else
            [{'DOI': '10.5555/second-preprint', 'title': ['Second'], 'type': 'posted-content',
            'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': targets[1]}]}}])
        return httpx.Response(200, json={'message': {'items': rows, 'total-results': 2, 'next-cursor': 'next' if page == '*' else 'end'}})
    with SupplementalClient('crossref', interval=0, page_size=1, transport=httpx.MockTransport(response)) as client:
        result = client.lookup_preprints(targets)
    assert len(calls) == 2
    for formal, preprint in zip(targets, ('10.21203/rs.3.rs-8330917/v1', '10.5555/second-preprint'), strict=True):
        assert {record.external_ids.doi for record in result[formal]} == {formal, preprint}
        assert result[formal][0].related_ids[0].record_id == preprint
    assert not any(item.first_version for record in result[targets[0]] for item in record.dates)


def test_europe_pmc_targets_has_preprint_batches_and_preserves_native_matching_note():
    calls = []
    note = 'Matched by title and first author'
    def response(request):
        calls.append(request)
        query = request.url.params['query']
        if 'HAS_PREPRINT:Y' in query:
            assert all('EXT_ID:' + key in query for key in ('42908400', '1234'))
            rows = [{'source': 'MED', 'id': '42908400', 'doi': '10.1093/nar/gkag979', 'title': 'Formal',
                'commentCorrectionList': {'commentCorrection': [{'type': 'Preprint in', 'source': 'PPR',
                    'id': 'PPR123', 'doi': '10.64898/2026.01.01.123456', 'note': note}]}}]
        else:
            assert 'SRC:PPR' in query
            rows = [{'source': 'PPR', 'id': 'PPR123', 'doi': '10.64898/2026.01.01.123456', 'title': 'Preprint',
                'firstPublicationDate': '2026-01-01', 'versionNumber': 2,
                'bookOrReportDetails': {'publisher': 'bioRxiv'},
                'versionList': {'version': [{'source': 'PPR', 'id': 'PPR122', 'versionNumber': 1,
                    'firstPublishDate': '2025-12-31'}]}}]
        return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
    with SupplementalClient('europe_pmc', interval=0, transport=httpx.MockTransport(response)) as client:
        result = client.lookup_many('pmid', ['42908400', '1234'])
        preprint, = client.lookup('europe_pmc', 'PPR:PPR123')
    assert len(calls) == 2 and result['1234'] == ()
    formal, = result['42908400']
    assert formal.external_ids.pmid == '42908400'
    assert formal.related_ids[0].note == note
    assert note in formal.provenance.note
    assert any(ref.provider == 'biorxiv' and ref.record_id.startswith('10.64898/') for ref in preprint.related_ids)
    assert any(date.first_version and date.year == 2025 for date in preprint.dates)


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
def test_new_preprint_prefix_uses_native_details_not_formal_reverse(provider):
    calls = []
    doi = '10.64898/2026.01.01.123456'
    with SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda request:
            calls.append(request.url.path) or httpx.Response(200, json={'messages': [{'status': 'ok'}],
                'collection': [{'doi': doi, 'server': provider, 'version': '1', 'date': '2026-01-01', 'title': 'Preprint'}]}))) as client:
        record, = client.lookup('doi', doi)
    assert calls == [f'/details/{provider}/{doi}/na/json']
    assert completion_metadata((record,)).metadata.first_public_at == '2026-01-01'


def test_crossref_reverse_failed_page_retains_verified_relation_and_reports_partial():
    calls = []
    formal, preprint = '10.5555/formal', '10.5555/preprint'
    def response(request):
        calls.append(request)
        rows = [{'DOI': preprint, 'type': 'posted-content',
            'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': formal}]}}] if len(calls) == 1 else []
        return httpx.Response(200, json={'message': {'items': rows, 'total-results': 2, 'next-cursor': 'next'}})
    with SupplementalClient('crossref', interval=0, page_size=1, transport=httpx.MockTransport(response)) as client:
        result = client.lookup_preprints((formal,))[formal]
    assert isinstance(result, Exception) and 'no progress' in str(result)
    assert {record.external_ids.doi for record in result.records} == {formal, preprint}


def test_crossref_exact_batch_maps_out_of_order_dates_without_using_response_order():
    calls = []
    def response(request):
        calls.append(request)
        assert request.url.params['filter'] == 'doi:10.5555/one,doi:10.5555/two'
        return httpx.Response(200, json={'message': {'total-results': 2, 'items': [
            {'DOI': '10.5555/two', 'type': 'journal-article', 'published': {'date-parts': [[2026, 2]]}},
            {'DOI': '10.5555/one', 'type': 'journal-article', 'published': {'date-parts': [[2026, 1]]}}]}})
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(response)) as client:
        results = client.lookup_many('doi', ['10.5555/one', '10.5555/two', '10.5555/one'])
    assert len(calls) == 1
    assert results['10.5555/one'][0].publication_date == '2026-01'
    assert results['10.5555/two'][0].publication_date == '2026-02'
