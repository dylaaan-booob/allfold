from datetime import datetime, timezone
from threading import Event

import pytest

from allfold.canonicalize import canonicalize_records
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
    discovered = evidence("europe_pmc", "10.5555/main", monitor_journal_issns=("0006-341X",),
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
    assert {s.provider: s.role for s in paper.sources} == {"europe_pmc": "discovery", "crossref": "supplement"}


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


def test_complete_provider_metadata_can_refresh_new_date_evidence_on_explicit_invocation():
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
    assert canonicalize_records(records).papers[0].metadata.first_public_at is None
    earliest = later.model_copy(update={'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2019, first_version=True),)})
    client = Lookup((earliest,))
    result = complete_metadata(records, ('arxiv',), clients={'arxiv': client})
    assert client.calls == [('arxiv', '1901.12345')]
    assert not result.issues
    assert canonicalize_records(result.records).papers[0].metadata.first_public_at == '2019'


def test_known_arxiv_doi_on_formal_record_is_an_unresolved_preprint_chain():
    from allfold.models import EvidenceDate, EvidenceDateKind
    formal = evidence('crossref', '10.5555/formal', abstract='Abstract', publication_date='2026-01',
        authors=(Author(name='Author'),), related_dois=('10.48550/arxiv.1901.12345', '10.48550/arxiv.2201.12345'))
    first = evidence('arxiv', '10.48550/arxiv.2201.12345').model_copy(update={
        'publication_type': 'preprint', 'external_ids': ExternalIds(arxiv='2201.12345'),
        'dates': (EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, first_version=True),)})
    records = (formal, first)
    assert canonicalize_records(records).papers[0].metadata.first_public_at is None
    client = Lookup()
    result = complete_metadata(records, ('arxiv',), clients={'arxiv': client})
    assert client.calls == [('arxiv', '1901.12345')]
    assert canonicalize_records(result.records).papers[0].metadata.first_public_at is None


def test_known_native_target_is_resolved_before_any_aggregation_and_then_stops():
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace', '10.5555/formal', abstract='Complete abstract', publication_date='2026',
        authors=(Author(name='Author'),), related_ids=(ProviderRecordRef(provider='arxiv', record_id='2201.12345'),))
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
        publication_date='2026',related_ids=(ProviderRecordRef(provider='arxiv',record_id='2201.12345'),))
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
    assert canonicalize_records(result.records).papers[0].metadata.first_public_at == '2019'


@pytest.mark.parametrize('kind',['accepted','published-online','published'])
def test_one_journal_date_and_local_first_version_suppress_date_only_and_optional_queries(kind):
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    formal = evidence('workspace','10.5555/formal',abstract='Abstract',authors=(Author(name='Author'),),
        dates=(EvidenceDate(kind=kind,year=2030,publication_type='journal'),),
        related_ids=(ProviderRecordRef(provider='arxiv',record_id='2201.12345'),))
    preprint = evidence('arxiv','10.48550/arxiv.2201.12345').model_copy(update={
        'external_ids':ExternalIds(arxiv='2201.12345'),'publication_type':'preprint',
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,first_version=True),)})
    forbidden = Lookup(error=AssertionError('Optional fields or more date precision are not goals'))
    result = complete_metadata((formal,preprint),('arxiv','crossref'),clients={'arxiv':forbidden,'crossref':forbidden})
    assert not result.lookups and result.first_public_status == 'recorded'


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
    assert canonicalize_records(records).papers[0].metadata.first_public_at is None


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
    assert canonicalize_records(result.records).papers[0].metadata.journal == 'Followed journal'


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
