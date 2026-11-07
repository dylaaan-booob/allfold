from datetime import datetime, timezone

import httpx
import pytest

from allfold.canonicalize import canonicalize_records
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.supplemental import SupplementalClient


@pytest.mark.parametrize('provider', ('biorxiv', 'medrxiv'))
@pytest.mark.parametrize('status', ('service unavailable', 'Preprint for DOI 10.1093/bioinformatics not found'))
def test_native_no_match_does_not_hide_errors_or_truncated_doi(provider, status):
    from allfold.providers.integrated import DiscoveryError
    with SupplementalClient(provider, interval=0, transport=httpx.MockTransport(lambda request:
            httpx.Response(200, json={'messages': [{'status': status}], 'collection': []}))) as client:
        with pytest.raises(DiscoveryError):
            client.lookup('doi', '10.1093/bioinformatics/btaf638')


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
        records = client.lookup('doi', '10.5555/formal')
    assert records[0].external_ids.doi == '10.5555/formal'
    assert records[0].related_dois == ('10.1101/123456',)
    assert records[1].external_ids.doi == '10.1101/123456'
    paper, = canonicalize_records(records).papers
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
        records = client.lookup("doi", "10.5555/formal")
    assert [r.url.path for r in requests] == ["/pubs/biorxiv/10.5555/formal/na/json", "/details/biorxiv/10.1101/123456/na/json"]
    formal = ProviderWorkEvidence(provenance=MetadataSource(provider="europe_pmc", record_id="MED:42",
        retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc), role="discovery"),
        title="Formal", journal="Journal", publication_date="2026-01-02", publication_type="journal",
        monitor_journal_issns=("0006-341X",), external_ids=ExternalIds(doi="10.5555/formal"))
    result = canonicalize_records((formal, *records))
    assert not result.issues
    paper = result.papers[0]
    assert paper.doi == "10.5555/formal"
    assert paper.related_dois == ("10.1101/123456",)
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
    paper, = canonicalize_records((formal, first)).papers
    assert paper.metadata.first_public_at is None
    assert any(ref.record_id == '10.5555/unknown' and ref.relation == 'preprint' for ref in formal.related_ids)


@pytest.mark.parametrize('malformed', [False, True])
def test_native_details_no_match_or_failure_is_also_reused_within_operation(malformed):
    from allfold.providers.integrated import DiscoveryError
    calls = []
    def response(request):
        calls.append(request.url.path)
        rows = [{'preprint_doi': '10.1101/123456', 'published_doi': '10.5555/formal'}] if '/pubs/' in request.url.path else (
            'invalid collection' if malformed else [])
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': rows})
    with SupplementalClient('biorxiv', interval=0, transport=httpx.MockTransport(response)) as client:
        for doi in ('10.5555/formal', '10.1101/123456'):
            if malformed:
                with pytest.raises(DiscoveryError):
                    client.lookup('doi', doi)
            else:
                client.lookup('doi', doi)
    assert calls == ['/pubs/biorxiv/10.5555/formal/na/json', '/details/biorxiv/10.1101/123456/na/json']


def test_crossref_explicit_preprint_versions_share_first_version_proof():
    def response(request):
        first = request.url.path.endswith('/10.5555/v1')
        doi, related = ('10.5555/v1', '10.5555/v2') if first else ('10.5555/v2', '10.5555/v1')
        return httpx.Response(200, json={'message': {'DOI': doi, 'type': 'posted-content', 'title': ['Preprint'],
            'version': '1' if first else '2', 'posted': {'date-parts': [[2021 if first else 2022, 6]]},
            'relation': {'has-version' if first else 'is-version-of': [{'id-type': 'doi', 'id': related}]}}})
    with SupplementalClient('crossref', interval=0, transport=httpx.MockTransport(response)) as client:
        records = client.lookup('doi', '10.5555/v2') + client.lookup('doi', '10.5555/v1')
    paper, = canonicalize_records(records).papers
    assert paper.metadata.first_public_at == '2021-06'
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
        records = client.lookup('doi', '10.5555/formal')
    assert len(calls) == 18
    assert {record.external_ids.doi for record in records} == {'10.5555/formal'} | {
        f'10.1101/{n:06}' for n in range(17)}
