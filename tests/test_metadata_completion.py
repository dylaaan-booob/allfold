from datetime import datetime, timezone
from threading import Event

import pytest

from allfold.canonicalize import canonicalize_records, completion_metadata
from allfold.models import Author, ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.application.metadata_completion import complete_metadata


def evidence(provider, identifier, *, title="Original", abstract=None, **fields):
    return ProviderWorkEvidence(
        provenance=MetadataSource(provider=provider, record_id=identifier,
                                  retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role="discovery"),
        external_ids=ExternalIds(doi=identifier), title=title, abstract=abstract,
        journal="Followed journal", publication_type="journal", **fields,
    )


class Lookup:
    def __init__(self, records=(), error=None):
        self.records, self.error, self.calls = records, error, []

    def lookup(self, namespace, identifier):
        self.calls.append((namespace, identifier))
        if self.error:
            raise self.error
        return self.records


def test_completion_only_uses_enabled_providers_and_never_replaces_discovery_fields():
    discovered = evidence("pubmed", "10.5555/main", monitor_journal_issns=("0006-341X",),
                          authors=(Author(name="Original Author"),))
    crossref = Lookup((evidence("crossref", "10.5555/main", title="Other title", abstract="Missing abstract",
                               authors=(Author(name="Other Author"),)),))
    forbidden = Lookup(error=AssertionError("Unselected provider was called"))
    result = complete_metadata((discovered,), ("europe_pmc", "crossref"),
                               clients={"europe_pmc": Lookup(), "crossref": crossref, "openalex": forbidden})
    assert crossref.calls == [("doi", "10.5555/main")]
    assert not forbidden.calls and not result.issues
    paper = canonicalize_records(result.records).papers[0]
    assert paper.metadata.title == "Original"
    assert paper.metadata.abstract == "Missing abstract"
    assert [a.name for a in paper.authors] == ["Original Author"]
    assert {s.provider: s.role for s in paper.sources} == {"pubmed": "discovery", "crossref": "supplement"}


def test_completion_failure_or_unrelated_response_never_removes_discovery():
    records = (evidence("europe_pmc", "10.5555/main"),)
    clients = {"crossref": Lookup(error=ValueError("crossref: HTTP 503")),
               "openalex": Lookup((evidence("openalex", "10.5555/unrelated"),))}
    result = complete_metadata(records, ("crossref", "openalex"), clients=clients)
    assert result.records == records
    assert len(result.issues) == 2
    assert any("does not match" in issue.message for issue in result.issues)


def test_known_openalex_work_links_different_dois_only_when_selected():
    first, second = evidence("europe_pmc", "10.5555/first"), evidence("europe_pmc", "10.5555/second")
    class WorkLookup:
        def lookup(self, namespace, identifier):
            return (evidence("openalex", identifier).model_copy(update={
                "external_ids": ExternalIds(doi=identifier, openalex="https://openalex.org/W123")}),)
    result = complete_metadata((second, first), ("openalex",), clients={"openalex": WorkLookup()})
    assert len(canonicalize_records(result.records).papers) == 1
    without = complete_metadata((second, first), (), clients={"openalex": WorkLookup()})
    assert len(canonicalize_records(without.records).papers) == 2


def test_completion_order_is_stable_and_cancellation_stops_requests():
    a, b = evidence("europe_pmc", "10.5555/b"), evidence("europe_pmc", "10.5555/a")
    lookups = []
    for records in ((a, b), (b, a)):
        client = Lookup()
        complete_metadata(records, ("crossref",), clients={"crossref": client})
        lookups.append(client.calls)
    assert lookups == [[("doi", "10.5555/a"), ("doi", "10.5555/b")]] * 2
    signal = Event()
    class CancellingLookup(Lookup):
        def lookup(self, namespace, identifier):
            signal.set()
            return super().lookup(namespace, identifier)
    client = CancellingLookup()
    complete_metadata((a, b), ("crossref",), clients={"crossref": client}, cancel_event=signal)
    assert len(client.calls) == 1


def test_completion_queries_every_known_identity_beyond_200():
    records = tuple(evidence("europe_pmc", f"10.5555/work-{n}") for n in range(201))
    client = Lookup()
    result = complete_metadata(records, ("crossref",), clients={"crossref": client})
    assert len(client.calls) == 201 and len(result.records) == 201
    assert not result.issues


def test_completion_follows_new_links_until_exhausted_and_deduplicates_cycles():
    class LinkedLookup:
        def __init__(self):
            self.calls = []

        def lookup(self, namespace, identifier):
            self.calls.append((namespace, identifier))
            number = int(identifier.rsplit("-", 1)[-1])
            related = f"10.5555/work-{(number + 1) % 5}"
            return (evidence("crossref", identifier, related_dois=(related,)),)

    client = LinkedLookup()
    result = complete_metadata((evidence("europe_pmc", "10.5555/work-0"),),
                               ("crossref",), clients={"crossref": client})
    assert client.calls == [("doi", f"10.5555/work-{n}") for n in range(5)]
    assert len(result.records) == 6 and not result.issues


def test_arxiv_doi_routes_only_to_arxiv_and_no_match_is_an_explicit_result():
    record = evidence('openalex', '10.48550/arxiv.2201.12345')
    arxiv, bio, med = Lookup(), Lookup(), Lookup()
    result = complete_metadata((record,), ('arxiv', 'biorxiv', 'medrxiv'),
        clients={'arxiv': arxiv, 'biorxiv': bio, 'medrxiv': med})
    assert arxiv.calls == [('arxiv', '2201.12345')]
    assert not bio.calls and not med.calls and not result.issues
    assert [lookup.status for lookup in result.lookups] == ['no_match']


def test_saved_first_version_date_does_not_seal_later_metadata_gaps():
    from allfold.models import EvidenceDate, EvidenceDateKind
    known = evidence('arxiv', '10.48550/arxiv.2201.12345').model_copy(update={
        'publication_type': 'preprint', 'external_ids': ExternalIds(arxiv='2201.12345'),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True, publication_type='preprint'),)})
    client = Lookup((known.model_copy(update={'abstract': 'Later abstract', 'authors': (Author(name='Later author'),)}),))
    result = complete_metadata((known,), ('arxiv',), clients={'arxiv': client})
    assert client.calls == [('arxiv', '2201.12345')]
    assert any(record.abstract == 'Later abstract' for record in result.records)


def test_completion_fills_missing_journal_dates_even_when_bibliography_is_complete():
    from allfold.models import EvidenceDate, EvidenceDateKind
    old = evidence('crossref', '10.5555/complete', abstract='Saved abstract', publication_date='2026-01',
        authors=(Author(name='Saved author'),))
    new = old.model_copy(update={'dates': (EvidenceDate(kind=EvidenceDateKind.ACCEPTED, year=2025, month=12),)})
    client = Lookup((new,))
    result = complete_metadata((old,), ('crossref',), clients={'crossref': client})
    assert client.calls == [('doi', '10.5555/complete')]
    assert any(record.dates for record in result.records)


@pytest.mark.parametrize('later_year', [2020, None])
def test_each_preprint_version_chain_requires_its_own_first_public_proof(later_year):
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('crossref', '10.5555/formal', abstract='Abstract', publication_date='2026-01',
        authors=(Author(name='Author'),), related_ids=tuple(ProviderRecordRef(provider='arxiv', record_id=key)
            for key in ('2201.12345', '1901.12345')))
    first = evidence('arxiv', '10.48550/arxiv.2201.12345').model_copy(update={
        'publication_type': 'preprint', 'external_ids': ExternalIds(arxiv='2201.12345'),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),)})
    later = first.model_copy(update={'external_ids': ExternalIds(arxiv='1901.12345'),
        'provenance': first.provenance.model_copy(update={'record_id': '1901.12345', 'version': 'v2'}),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=later_year),) if later_year else ()})
    records = (formal, first, later)
    assert completion_metadata(records).metadata.first_public_at is None
    earliest = later.model_copy(update={'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2019, first_version=True),)})
    client = Lookup((earliest,))
    result = complete_metadata(records, ('arxiv',), clients={'arxiv': client})
    assert client.calls == [('arxiv', '1901.12345')]
    assert not result.issues
    assert completion_metadata(result.records).metadata.first_public_at == '2019'


def test_known_arxiv_doi_on_formal_record_is_an_unresolved_preprint_chain():
    from allfold.models import EvidenceDate, EvidenceDateKind
    formal = evidence('crossref', '10.5555/formal', abstract='Abstract', publication_date='2026-01',
        authors=(Author(name='Author'),), related_dois=('10.48550/arxiv.1901.12345', '10.48550/arxiv.2201.12345'))
    first = evidence('arxiv', '10.48550/arxiv.2201.12345').model_copy(update={
        'publication_type': 'preprint', 'external_ids': ExternalIds(arxiv='2201.12345'),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),)})
    records = (formal, first)
    assert completion_metadata(records).metadata.first_public_at is None
    client = Lookup()
    result = complete_metadata(records, ('arxiv',), clients={'arxiv': client})
    assert client.calls == [('arxiv', '1901.12345')]
    assert completion_metadata(result.records).metadata.first_public_at is None


def test_known_native_target_is_resolved_before_any_aggregation_and_then_stops():
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace', '10.5555/formal', abstract='Complete abstract', publication_date='2026',
        authors=(Author(name='Author'),), dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('received', 'accepted', 'published-online', 'published')),
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345'),))
    first = evidence('arxiv', '10.48550/arxiv.2201.12345').model_copy(update={
        'external_ids': ExternalIds(arxiv='2201.12345'), 'publication_type': 'preprint',
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),)})
    native = Lookup((first,))
    other = Lookup(error=AssertionError('Resolved local goals must not search unknown systems'))
    result = complete_metadata((formal,), ('crossref','openalex','arxiv'),
        clients={'crossref':other,'openalex':other,'arxiv':native})
    assert native.calls == [('arxiv','2201.12345')]
    assert not other.calls and not result.issues
    assert result.first_public_status == 'recorded'


def test_same_response_adds_another_family_before_stop_and_never_blind_probes():
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace','10.5555/formal',abstract='Abstract',authors=(Author(name='Author'),),
        publication_date='2026', dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('received', 'accepted', 'published-online', 'published')),
        related_ids=(ProviderRecordRef(provider='arxiv',record_id='2201.12345'),))
    class Native(Lookup):
        def lookup(self, namespace, identifier):
            self.calls.append((namespace,identifier))
            return (evidence('arxiv','10.48550/arxiv.'+identifier).model_copy(update={
                'external_ids':ExternalIds(arxiv=identifier),'publication_type':'preprint',
                'related_ids':(ProviderRecordRef(provider='arxiv',record_id='1901.12345'),) if identifier=='2201.12345' else (),
                'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2019 if identifier=='1901.12345' else 2022,first_version=True),)}),)
    native, forbidden = Native(), Lookup(error=AssertionError('No other systems needed'))
    result = complete_metadata((formal,),('arxiv','crossref','biorxiv','medrxiv'),
        clients={'arxiv':native,'crossref':forbidden,'biorxiv':forbidden,'medrxiv':forbidden})
    assert native.calls == [('arxiv','2201.12345'),('arxiv','1901.12345')]
    assert not forbidden.calls and result.first_public_status == 'recorded'
    assert completion_metadata(result.records).metadata.first_public_at == '2019'


@pytest.mark.parametrize('kind',['received','accepted','published-online','published'])
def test_one_journal_date_does_not_satisfy_other_independent_date_goals(kind):
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace','10.5555/formal',abstract='Abstract',authors=(Author(name='Author'),),
        dates=(EvidenceDate(kind=kind,year=2030,publication_type='journal'),),
        related_ids=(ProviderRecordRef(provider='arxiv',record_id='2201.12345'),))
    preprint = evidence('arxiv','10.48550/arxiv.2201.12345').model_copy(update={
        'external_ids':ExternalIds(arxiv='2201.12345'),'publication_type':'preprint',
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,first_version=True),)})
    forbidden, crossref = Lookup(error=AssertionError('Native goal is resolved')), Lookup()
    result = complete_metadata((formal,preprint),('arxiv','crossref'),clients={'arxiv':forbidden,'crossref':crossref})
    assert crossref.calls == [('doi', '10.5555/formal')]
    assert not forbidden.calls and result.first_public_status == 'recorded'


def test_wrong_response_primary_cannot_be_validated_by_related_requested_identity():
    wrong = evidence('crossref','10.5555/wrong',related_dois=('10.5555/main',))
    result = complete_metadata((evidence('workspace','10.5555/main'),),('crossref',),clients={'crossref':Lookup((wrong,))})
    assert len(result.records) == 1 and result.lookups[0].status == 'identity_mismatch'


def test_unknown_bio_platform_is_unresolved_without_guessing_enabled_server():
    formal = evidence('workspace','10.5555/formal',related_dois=('10.1101/123456',))
    forbidden = Lookup(error=AssertionError('Enabling a server does not prove platform identity'))
    result = complete_metadata((formal,),('biorxiv',),clients={'biorxiv':forbidden})
    assert not forbidden.calls and result.first_public_status == 'known_unresolved'


@pytest.mark.parametrize('year',[2018,2999])
def test_first_public_conflict_and_future_evidence_remain_unresolved(year):
    from allfold.models import EvidenceDate, EvidenceDateKind
    records = (evidence('arxiv','10.48550/arxiv.2201.12345').model_copy(update={
        'external_ids':ExternalIds(arxiv='2201.12345'),'publication_type':'preprint',
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,first_version=True),
            EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=year,first_version=True))}),)
    result = complete_metadata(records,(),clients={})
    assert result.first_public_status == 'conflict'
    assert completion_metadata(records).metadata.first_public_at is None


def test_resolved_preprint_does_not_hide_missing_formal_journal_source():
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace','10.5555/formal',abstract='Abstract',authors=(Author(name='Author'),),
        publication_date='2026',related_ids=(ProviderRecordRef(provider='arxiv',record_id='2201.12345'),)).model_copy(update={'journal':None})
    preprint = evidence('arxiv','10.48550/arxiv.2201.12345').model_copy(update={
        'external_ids':ExternalIds(arxiv='2201.12345'),'publication_type':'preprint','journal':None,
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,first_version=True),)})
    crossref = Lookup((evidence('crossref','10.5555/formal'),))
    result = complete_metadata((formal,preprint),('crossref',),clients={'crossref':crossref})
    assert crossref.calls == [('doi','10.5555/formal')]
    assert completion_metadata(result.records).metadata.journal == 'Followed journal'


def test_complete_preprint_only_work_needs_no_formal_journal_source():
    from allfold.models import EvidenceDate, EvidenceDateKind
    preprint = evidence('arxiv','10.48550/arxiv.2201.12345',abstract='Abstract',authors=(Author(name='Author'),)).model_copy(update={
        'external_ids':ExternalIds(arxiv='2201.12345'),'publication_type':'preprint','journal':None,
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,first_version=True),)})
    native = Lookup(error=AssertionError('A preprint-only work does not need a formal journal source'))
    result = complete_metadata((preprint,),('arxiv',),clients={'arxiv':native})
    assert not native.calls and result.first_public_status == 'recorded'


def test_normalized_openalex_preprint_source_does_not_create_a_formal_date_goal():
    from allfold.providers.integrated import DiscoveryClient, SourceScope
    from allfold.models import EvidenceDate, EvidenceDateKind
    import httpx
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda _: pytest.fail('No discovery request'))) as client:
        preprint = client.normalize({'id': 'https://openalex.org/W123', 'doi': '10.48550/arxiv.2201.12345',
            'title': 'Preprint', 'type': 'preprint', 'abstract_inverted_index': {'Abstract': [0]},
            'authorships': [{'author': {'display_name': 'Author'}}]}, SourceScope('journal', 'arXiv'))
    preprint = preprint.model_copy(update={'dates': (
        EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True,
                     provider='arxiv', record_id='2201.12345', publication_type='preprint'),)})
    assert preprint.journal == 'arXiv'
    forbidden = Lookup(error=AssertionError('Preprint source names do not need formal journal dates'))
    result = complete_metadata((preprint,), ('crossref', 'arxiv'), clients={'crossref': forbidden, 'arxiv': forbidden})
    assert not result.lookups and result.first_public_status == 'recorded'


def test_late_preprint_identity_reuses_another_candidates_cached_native_details():
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    main, preprint = '10.5555/main', '10.1101/123456'
    cache = {('biorxiv', 'doi', preprint): (
        evidence('biorxiv', preprint, abstract='Cached abstract').model_copy(update={
            'publication_type': 'preprint', 'journal': None,
            'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),)}),
    )}
    formal = evidence('workspace', main, publication_date='2026', authors=(Author(name='Author'),))
    crossref = Lookup((evidence('crossref', main, related_dois=(preprint,), related_ids=(
        ProviderRecordRef(provider='biorxiv', record_id=preprint, relation='preprint'),)),))
    native = Lookup(error=AssertionError('Previously cached native details already answer the late identity'))
    result = complete_metadata((formal,), ('crossref', 'biorxiv'),
        clients={'crossref': crossref, 'biorxiv': native}, request_cache=cache)
    assert crossref.calls == [('doi', main)] and not native.calls
    assert result.first_public_status == 'recorded' and not result.issues
    assert {record.external_ids.doi for record in result.records} == {main, preprint}
    paper = completion_metadata(result.records)
    assert paper.metadata.abstract == 'Cached abstract' and paper.metadata.first_public_at == '2022'
    assert all(record.provenance.role == 'supplement' for record in result.records
               if record.provenance.provider == 'biorxiv')


def test_base_api_batches_overlap_and_map_each_paper_before_native_waves():
    from threading import Barrier, Event
    import httpx
    from allfold.application.metadata_completion import complete_metadata_many
    from allfold.providers.supplemental import SupplementalClient
    barrier, crossref_started = Barrier(2, timeout=3), Event()
    calls = []
    def response(request):
        calls.append(request)
        if request.url.host != 'api.crossref.org' or not crossref_started.is_set():
            crossref_started.set()
            barrier.wait()
        if request.url.host == 'api.crossref.org':
            filters = request.url.params['filter']
            if 'relation.type:' in filters:
                rows = []
            else:
                assert 'doi:10.5555/one' in filters and 'doi:10.5555/two' in filters
                rows = [{'DOI': doi, 'title': [doi], 'type': 'journal-article',
                    'published-online': {'date-parts': [[2026, month]]},
                    'assertion': [{'name': 'received', 'value': '2025-12'}]}
                    for doi, month in [('10.5555/two', 2), ('10.5555/one', 1)]]
            return httpx.Response(200, json={'message': {'total-results': len(rows), 'items': rows}})
        assert request.url.params['query'] == 'SRC:MED AND HAS_PREPRINT:Y AND (EXT_ID:101 OR EXT_ID:202)'
        return httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})
    groups = {key: (evidence('wos', doi, abstract='Abstract', authors=(Author(name='Author'),)).model_copy(
        update={'external_ids': ExternalIds(doi=doi, pmid=pmid)}),)
        for key, doi, pmid in [('one', '10.5555/one', '101'), ('two', '10.5555/two', '202')]}
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(response)) as crossref, SupplementalClient(
            'europe_pmc', interval=0, transport=httpx.MockTransport(response)) as europe:
        results = dict(complete_metadata_many(groups, ('crossref', 'europe_pmc'), clients={
            'crossref': crossref, 'europe_pmc': europe}))
    assert len(calls) == 3
    assert all(not result.issues for result in results.values())
    for key, month in [('one', 1), ('two', 2)]:
        dates = completion_metadata(results[key].records).date_evidence
        assert any(item.kind.value == 'published-online' and item.month == month for item in dates)
        assert any(item.kind.value == 'received' and item.year == 2025 and item.day is None for item in dates)


def test_run_completion_does_not_use_biorxiv_without_an_explicit_platform_association():
    native = Lookup()
    result = complete_metadata((evidence('wos', '10.5555/no-clue'),), ('biorxiv',),
        clients={'biorxiv': native})
    assert not native.calls
    assert result.first_public_status == 'no_association'


def test_pubmed_completion_batches_confirmed_pmids_and_reuses_stronger_fetch_capability():
    import httpx
    from allfold.application.metadata_completion import complete_metadata_many
    from allfold.providers.integrated import DiscoveryClient
    from test_pubmed_discovery import article
    calls = []
    def response(request):
        calls.append(request)
        ids = request.url.params['id'].split(',')
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200, text='<PubmedArticleSet>' + ''.join(article(key, '0006-341X', f'10.5555/{key}') for key in ids) + '</PubmedArticleSet>')
        rows = {'uids': list(reversed(ids))}
        rows.update((key, {'uid': key, 'title': 'Summary', 'pubdate': '2026 Oct', 'epubdate': '2026 Sep 30',
            'articleids': [{'idtype': 'doi', 'value': f'10.5555/{key}'}],
            'history': [{'pubstatus': 'received', 'date': '2026/03/01 00:00'},
                {'pubstatus': 'accepted', 'date': '2026 Sep 10 00:00'}]}) for key in ids)
        return httpx.Response(200, json={'result': rows})
    groups = {key: (evidence('wos', f'10.5555/{key}', abstract=None if key == '3' else 'Abstract',
        authors=(Author(name='Author'),)).model_copy(update={'external_ids': ExternalIds(doi=f'10.5555/{key}', pmid=key)}),)
        for key in ('1', '2', '3', '4')}
    with DiscoveryClient('pubmed', interval=0, transport=httpx.MockTransport(response)) as client:
        client.lookup_many('pmid', ['4'], capability='fetch')  # Verified Discovery evidence.
        results = dict(complete_metadata_many(groups, ('pubmed',), clients={'pubmed': client}))
    assert len(calls) == 3
    assert sorted((request.url.path.rsplit('/', 1)[-1], request.url.params['id']) for request in calls) == [
        ('efetch.fcgi', '3'), ('efetch.fcgi', '4'), ('esummary.fcgi', '1,2')]
    for key, result in results.items():
        assert not result.issues
        assert {item.kind.value for item in completion_metadata(result.records).date_evidence} >= {
            'received', 'accepted', 'published-online', 'published'}
    assert completion_metadata(results['3'].records).metadata.abstract == 'METHODS: Study abstract'


def test_pubmed_preprint_reference_keeps_formal_pmid_and_follows_explicit_native_identity():
    import httpx
    from allfold.models import ProviderRecordRef
    from allfold.providers.integrated import DiscoveryClient
    from allfold.providers.supplemental import SupplementalClient
    from test_pubmed_discovery import article
    calls = []
    formal = evidence('wos', '10.1093/nar/gkag979', abstract='Formal abstract', authors=(Author(name='Formal Author'),)).model_copy(update={
        'external_ids': ExternalIds(doi='10.1093/nar/gkag979', pmid='42908400'),
        'related_ids': (ProviderRecordRef(provider='pubmed', record_id='42239170', relation='preprint'),)})
    def response(request):
        calls.append(request)
        if request.url.path.endswith('esummary.fcgi'):
            return httpx.Response(200, json={'result': {'uids': ['42908400'], '42908400': {'uid': '42908400'}}})
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200, text='<PubmedArticleSet>' + article('42239170', '0006-341X', '10.64898/2026.01.01.123456') + '</PubmedArticleSet>')
        query = request.url.params['query']
        if 'HAS_PREPRINT' in query:
            return httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})
        assert 'SRC:PPR' in query and 'DOI:"10.64898/2026.01.01.123456"' in query
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{
            'source': 'PPR', 'id': 'PPR1', 'title': 'Preprint', 'doi': '10.64898/2026.01.01.123456',
            'firstPublicationDate': '2026-01-01', 'versionNumber': 1}]}})
    with DiscoveryClient('pubmed', interval=0, transport=httpx.MockTransport(response)) as pubmed, SupplementalClient(
            'europe_pmc', interval=0, transport=httpx.MockTransport(response)) as europe:
        result = complete_metadata((formal,), ('pubmed', 'europe_pmc'), clients={'pubmed': pubmed, 'europe_pmc': europe})
    assert not result.issues
    assert result.first_public_status == 'recorded'
    assert completion_metadata(result.records).metadata.first_public_at == '2026-01-01'
    assert all(record.publication_type == 'preprint' for record in result.records
        if record.external_ids.model_dump().get('pmid') == '42239170')
    assert not any(request.url.params.get('id') == '42908400,42239170' for request in calls)


def test_openalex_verified_location_binding_keeps_returned_top_identity_separate():
    import httpx
    from allfold.providers.integrated import DiscoveryClient
    raw = {'id': 'https://openalex.org/W7223175244', 'doi': 'https://doi.org/10.1101/2026.04.01.123456',
        'title': 'Merged Work title', 'type': 'preprint', 'ids': {'pmid': 'https://pubmed.ncbi.nlm.nih.gov/42239170/'},
        'locations_count': 1, 'locations': [{'landing_page_url': 'https://doi.org/10.1093/nar/gkag979',
            'source': {'id': 'https://openalex.org/S1'}}]}
    formal = evidence('wos', '10.1093/nar/gkag979', abstract='Formal abstract', authors=(Author(name='Formal Author'),)).model_copy(
        update={'external_ids': ExternalIds(doi='10.1093/nar/gkag979', pmid='42908400')})
    with DiscoveryClient('openalex', interval=0, transport=httpx.MockTransport(lambda request: httpx.Response(200,
            json={'results': [raw], 'meta': {'count': 1}}))) as client:
        result = complete_metadata((formal,), ('openalex',), clients={'openalex': client})
    assert not result.issues
    returned = [record for record in result.records if record.external_ids.openalex]
    assert len(returned) == 1 and returned[0].external_ids.doi == '10.1101/2026.04.01.123456'
    anchor = next(record for record in result.records if record.provenance.provider == 'openalex' and record.external_ids.doi == '10.1093/nar/gkag979')
    assert anchor.external_ids.openalex is None and anchor.title is None
    assert any(ref.provider == 'openalex' and ref.record_id == 'W7223175244' for ref in anchor.related_ids)


def test_known_unverified_family_does_not_suppress_run_crossref_reverse_batch():
    import httpx
    from allfold.models import EvidenceDate, ProviderRecordRef
    from allfold.providers.supplemental import SupplementalClient
    formal_doi, new_preprint = '10.5555/formal', '10.64898/2019.01.01.123456'
    formal = evidence('wos', formal_doi, abstract='Abstract', authors=(Author(name='Author'),),
        dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('received', 'accepted', 'published-online', 'published')),
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345', relation='preprint'),))
    calls = []
    def response(request):
        calls.append(request)
        if request.url.host == 'api.crossref.org':
            reverse = 'relation.type:is-preprint-of' in request.url.params['filter']
            rows = [{'DOI': new_preprint, 'title': ['New preprint family'], 'type': 'posted-content', 'publisher': 'bioRxiv',
                'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': formal_doi}]}}] if reverse else [
                {'DOI': formal_doi, 'title': ['Formal'], 'type': 'journal-article'}]
            return httpx.Response(200, json={'message': {'items': rows, 'total-results': len(rows)}})
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                '<id>https://arxiv.org/abs/2201.12345v1</id><title>Known family</title>'
                '<published>2022-01-02T00:00:00Z</published></entry></feed>')
        assert request.url.path == f'/details/biorxiv/{new_preprint}/na/json'
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': new_preprint, 'title': 'New family', 'server': 'biorxiv', 'date': '2019-01-01', 'version': '1'}]})
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(response)) as crossref, SupplementalClient(
            'arxiv', interval=0, transport=httpx.MockTransport(response)) as arxiv, SupplementalClient(
            'biorxiv', interval=0, transport=httpx.MockTransport(response)) as biorxiv:
        result = complete_metadata((formal,), ('crossref', 'arxiv', 'biorxiv'), clients={
            'crossref': crossref, 'arxiv': arxiv, 'biorxiv': biorxiv})
    assert not result.issues
    assert any('relation.type:is-preprint-of' in request.url.params.get('filter', '') for request in calls)
    assert result.first_public_status == 'recorded'
    assert completion_metadata(result.records).metadata.first_public_at == '2019-01-01'


def test_saved_first_public_with_received_gap_queries_dates_without_association_or_blind_native_probes():
    import httpx
    from allfold.models import EvidenceDate
    from allfold.providers.supplemental import SupplementalClient
    formal = evidence('workspace', '10.5555/saved', abstract='Abstract', authors=(Author(name='Author'),),
        first_public_at='2020', dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('accepted', 'published-online', 'published'))).model_copy(
        update={'external_ids': ExternalIds(doi='10.5555/saved', pmid='7')})
    calls = []
    def response(request):
        calls.append(request)
        if request.url.host == 'api.crossref.org':
            rows = [] if 'relation.type:' in request.url.params['filter'] else [
                {'DOI': '10.5555/saved', 'type': 'journal-article'}]
            return httpx.Response(200, json={'message': {'items': rows, 'total-results': len(rows)}})
        if request.url.host == 'www.ebi.ac.uk':
            return httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': []})
    from contextlib import ExitStack
    with ExitStack() as stack:
        clients = {provider: stack.enter_context(SupplementalClient(provider, interval=0, transport=httpx.MockTransport(response)))
            for provider in ('crossref', 'europe_pmc', 'biorxiv', 'medrxiv')}
        result = complete_metadata((formal,), tuple(clients), clients=clients)
    assert not result.issues and result.first_public_status == 'recorded'
    assert len(calls) == 1
    assert calls[0].url.host == 'api.crossref.org' and calls[0].url.params['filter'] == 'doi:10.5555/saved'
    assert next(record for record in result.records if record.provenance.provider == 'workspace').first_public_at == '2020'


@pytest.mark.parametrize('verified', [False, True])
def test_partial_reverse_page_is_absorbed_before_pending_native_family_can_finish(verified):
    import httpx
    from contextlib import ExitStack
    from allfold.models import EvidenceDate, ProviderRecordRef
    from allfold.paper_dates import first_public_status, known_preprint_families, preprint_date_coverage
    from allfold.providers.supplemental import SupplementalClient
    formal_doi, preprint = '10.5555/formal', '10.64898/2019.01.01.123456'
    formal = evidence('wos', formal_doi, abstract='Abstract', authors=(Author(name='Author'),),
        dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('received', 'accepted', 'published-online', 'published')),
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345', relation='preprint'),))
    calls = []
    def response(request):
        calls.append((request.url.host, request.url.path, request.url.params.get('cursor')))
        if request.url.host == 'api.crossref.org':
            assert 'relation.type:is-preprint-of' in request.url.params['filter']
            if request.url.params['cursor'] != '*':
                return httpx.Response(400)
            return httpx.Response(200, json={'message': {'total-results': 2, 'next-cursor': 'second', 'items': [{
                'DOI': preprint, 'type': 'posted-content', 'publisher': 'bioRxiv',
                'relation': {'is-preprint-of': [{'id-type': 'doi', 'id': formal_doi}]}}]}})
        if request.url.host == 'export.arxiv.org':
            return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
                '<id>https://arxiv.org/abs/2201.12345v1</id><title>Known family</title>'
                '<published>2022-01-02T00:00:00Z</published></entry></feed>')
        assert request.url.path == f'/details/biorxiv/{preprint}/na/json'
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': preprint, 'server': 'biorxiv', 'date': '2019-01-01', 'version': '1' if verified else '2'}]})
    cache = {('crossref', 'doi', formal_doi): (), ('crossref', 'doi', preprint): ()}
    with ExitStack() as stack:
        clients = {provider: stack.enter_context(SupplementalClient(provider, interval=0,
            transport=httpx.MockTransport(response))) for provider in ('crossref', 'arxiv', 'biorxiv')}
        result = complete_metadata((formal,), tuple(clients), clients=clients, request_cache=cache)
        # Cached partial facts and failure belong only to their formal target.
        other = formal.model_copy(update={'external_ids': ExternalIds(doi='10.5555/other'),
            'related_ids': (), 'first_public_at': '2020'})
        unrelated = complete_metadata((other,), tuple(clients), clients=clients, request_cache=cache)
    assert result.status == 'partial'
    assert len(result.issues) == 1 and result.issues[0].status == 'partial'
    assert [(lookup.identifier, lookup.status) for lookup in result.lookups if lookup.capability == 'preprints'] == [
        (formal_doi, 'partial')]
    assert completion_metadata(result.records).metadata.first_public_at == ('2019-01-01' if verified else None)
    assert f'doi:{preprint}' in known_preprint_families(result.records)
    assert preprint_date_coverage(result.records)[0] is verified
    assert first_public_status(result.records) == ('recorded' if verified else 'known_unresolved')
    assert len(calls) == 4 and calls.count(('api.crossref.org', '/works', 'second')) == 1
    assert unrelated.records == (other,) and not unrelated.issues and not unrelated.lookups


def test_cached_batch_failure_is_reported_once_before_native_proof_satisfies_goals():
    from allfold.models import EvidenceDate, ProviderRecordRef
    from allfold.providers.integrated import DiscoveryError
    formal = evidence('wos', '10.5555/formal', abstract='Abstract', authors=(Author(name='Author'),),
        dates=tuple(EvidenceDate(kind=kind, year=2026, publication_type='journal')
            for kind in ('received', 'accepted', 'published-online', 'published')),
        related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345', relation='preprint'),)).model_copy(
            update={'external_ids': ExternalIds(doi='10.5555/formal', pmid='7')})
    native = Lookup((ProviderWorkEvidence(publication_type='preprint', external_ids=ExternalIds(arxiv='2201.12345'),
        provenance=MetadataSource(provider='arxiv', record_id='2201.12345', retrieved_at=datetime.now(timezone.utc)),
        dates=(EvidenceDate(kind='preprint', year=2022, first_version=True, publication_type='preprint'),)),))
    failure = DiscoveryError('Controlled batch failure')
    cache = {('pubmed', 'pmid', '7', capability): failure for capability in ('summary', 'fetch')}
    cache[('pubmed', 'pmid', '8', 'fetch')] = DiscoveryError('Other Paper failure')
    result = complete_metadata((formal,), ('pubmed', 'arxiv'), clients={'pubmed': Lookup(), 'arxiv': native},
        request_cache=cache)
    assert result.status == 'partial' and result.first_public_status == 'recorded'
    assert [(issue.identifier, issue.message) for issue in result.issues] == [('7', 'Controlled batch failure')]
    assert len([lookup for lookup in result.lookups if lookup.provider == 'pubmed']) == 1
    assert native.calls == [('arxiv', '2201.12345')]


def test_preprint_relations_join_shared_native_batches_across_completion_waves():
    import httpx

    from allfold.application.metadata_completion import complete_metadata_many
    from allfold.providers.supplemental import SupplementalClient

    groups = {index: (evidence('wos', f'10.5555/formal-{index}', abstract='Abstract',
        authors=(Author(name='Author'),)),) for index in (1, 2)}
    batches = []

    def handler(request):
        if request.url.host == 'api.crossref.org':
            dois = [item.removeprefix('doi:') for item in request.url.params['filter'].split(',')
                if item.startswith('doi:')]
            rows = [{'DOI': doi, 'type': 'journal-article', 'relation': {'has-preprint': [
                {'id-type': 'uri', 'id': f'https://arxiv.org/abs/2201.0000{doi[-1]}'}]}} for doi in dois]
            return httpx.Response(200, json={'message': {'items': rows, 'total-results': len(rows)}})
        assert request.url.host == 'export.arxiv.org'
        identifiers = request.url.params['id_list'].split(',')
        batches.append(identifiers)
        entries = []
        for identifier in reversed(identifiers):
            index = int(identifier[-1])
            relation = f'<arxiv:doi>10.48550/arxiv.2201.{index + 2:05}</arxiv:doi>' if index < 3 else ''
            entries.append(f'<entry><id>https://arxiv.org/abs/{identifier}</id><title>Preprint</title>'
                f'<published>2022-01-02T00:00:00Z</published>{relation}</entry>')
        return httpx.Response(200, text='<feed xmlns="http://www.w3.org/2005/Atom" '
            'xmlns:arxiv="http://arxiv.org/schemas/atom">' + ''.join(entries) + '</feed>')

    transport = httpx.MockTransport(handler)
    with SupplementalClient('crossref', interval=0, transport=transport) as crossref, SupplementalClient(
            'arxiv', interval=0, transport=transport) as arxiv:
        outcomes = dict(complete_metadata_many(groups, ('crossref', 'arxiv'),
            clients={'crossref': crossref, 'arxiv': arxiv}))
    assert batches == [['2201.00001', '2201.00002'], ['2201.00003', '2201.00004']]
    assert all(result.first_public_status == 'recorded' and not result.issues for result in outcomes.values())
