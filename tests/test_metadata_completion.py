from datetime import datetime, timezone
from threading import Event

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
    records = (evidence("dblp", "10.5555/main"),)
    clients = {"crossref": Lookup(error=ValueError("crossref: HTTP 503")),
               "openalex": Lookup((evidence("openalex", "10.5555/unrelated"),))}
    result = complete_metadata(records, ("crossref", "openalex"), clients=clients)
    assert result.records == records
    assert len(result.issues) == 2
    assert any("does not match" in issue.message for issue in result.issues)


def test_known_openalex_work_links_different_dois_only_when_selected():
    first, second = evidence("dblp", "10.5555/first"), evidence("europe_pmc", "10.5555/second")
    class WorkLookup:
        def lookup(self, namespace, identifier):
            return (evidence("openalex", identifier).model_copy(update={
                "external_ids": ExternalIds(doi=identifier, openalex="https://openalex.org/W123")}),)
    result = complete_metadata((second, first), ("openalex",), clients={"openalex": WorkLookup()})
    assert len(canonicalize_records(result.records).papers) == 1
    without = complete_metadata((second, first), (), clients={"openalex": WorkLookup()})
    assert len(canonicalize_records(without.records).papers) == 2


def test_completion_order_is_stable_and_cancellation_stops_requests():
    a, b = evidence("dblp", "10.5555/b"), evidence("europe_pmc", "10.5555/a")
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
    records = tuple(evidence("dblp", f"10.5555/work-{n}") for n in range(201))
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
    result = complete_metadata((evidence("dblp", "10.5555/work-0"),),
                               ("crossref",), clients={"crossref": client})
    assert client.calls == [("doi", f"10.5555/work-{n}") for n in range(5)]
    assert len(result.records) == 6 and not result.issues
