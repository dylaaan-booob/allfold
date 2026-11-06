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
