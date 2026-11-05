from datetime import datetime, timezone

import httpx

from allfold.canonicalize import canonicalize_records
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.supplemental import SupplementalClient


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
    assert paper.metadata.accepted_at == "2025-12-01"
    assert not paper.metadata.accepted_approximate
    assert paper.metadata.first_public_at == "2026-01-02"
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
    assert paper.metadata.accepted_at is None


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
        records = client.lookup("doi", "10.5555/formal")
    assert [r.url.path for r in requests] == ["/pubs/biorxiv/10.5555/formal/na/json", "/details/biorxiv/10.1101/123456/na/json"]
    formal = ProviderWorkEvidence(provenance=MetadataSource(provider="europe_pmc", record_id="MED:42",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role="discovery"),
        title="Formal", journal="Journal", publication_date="2026-01-02", publication_type="journal",
        monitor_journal_issns=("0006-341X",), external_ids=ExternalIds(doi="10.5555/formal"))
    paper = canonicalize_records((formal, *records)).papers[0]
    assert paper.doi == "10.5555/formal"
    assert paper.related_dois == ("10.1101/123456",)
    assert paper.metadata.publication_date == "2026-01-02"
    assert paper.metadata.first_public_at == "2022-01-02"
    assert paper.metadata.accepted_at == "2026-01-02" and paper.metadata.accepted_approximate
