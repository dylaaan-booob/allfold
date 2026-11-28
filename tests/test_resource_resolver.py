"""On-demand GOKB discovery with complete pages and conservative matches."""

import httpx
import pytest

from allfold.application import journal_resolver
from allfold.application.carsi_catalog import CarsiResource
from allfold.application.journal_resolver import resolve_journal
from allfold.config import JournalConfig
from allfold.providers.gokb import GokbClient
from http_test_helpers import http_server, isolate_proxy_environment


def resource(name="Springer Link", url="https://link.springer.com/", **extra):
    return CarsiResource(**(dict(production=name, searchStr=name.upper(), url=url, sptype="1") | extra))


def use_catalog(monkeypatch, records):
    monkeypatch.setattr(journal_resolver, 'get_carsi_catalog', lambda: {row.production: row for row in records})


def page(request, records, count=None):
    return httpx.Response(200, json=dict(result="OK", count=len(records) if count is None else count,
                                        max=int(request.url.params["max"]), offset=int(request.url.params["offset"]),
                                        records=records))


def title(uuid="journal-1", identifier="1234-5679"):
    return dict(uuid=uuid, name="Fixture Journal", componentType="JournalInstance",
                identifiers=[dict(namespace="issn", value=identifier)])


def tipp(index=0, journal="journal-1", platform="platform-1", package="Journal collection"):
    return dict(uuid=f"tipp-{index}", componentType="TitleInstancePackagePlatform", status="Current",
                tippTitleUuid=journal, hostPlatformUuid=platform, hostPlatformName="SpringerLink",
                tippPackageUuid=f"package-{index}", tippPackageName=package, url="https://link.springer.com/article/test")


def gokb_transport(*, titles=None, tipps=None, platform_url="https://link.springer.com/"):
    def handler(request):
        assert request.url.host == "gokb.org"
        query = request.url.params
        if query["componentType"] == "JournalInstance":
            return page(request, [title()] if titles is None else titles)
        if query["componentType"] == "TitleInstancePackagePlatform":
            assert query["status"] == "Current"
            assert query["linkedTitle"] in {item["uuid"] for item in ([title()] if titles is None else titles)}
            items = [tipp()] if tipps is None else tipps
            items = [item for item in items if item["tippTitleUuid"] == query["linkedTitle"]]
            offset, maximum = int(query["offset"]), int(query["max"])
            return page(request, items[offset:offset + maximum], len(items))
        assert query["componentType"] == "Platform"
        return page(request, [dict(uuid=query["uuid"], name="SpringerLink", primaryUrl=platform_url,
                                   componentType="Platform")])
    return httpx.MockTransport(handler)


def test_gokb_reads_all_current_tipp_pages():
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    result = GokbClient(transport=gokb_transport(tipps=[tipp(i) for i in range(103)])).fetch(journal)
    assert {entry.uuid for entry in result.tipps} == {f"tipp-{i}" for i in range(103)}
    assert all(entry.journal_uuid == "journal-1" and entry.package_name == "Journal collection"
               for entry in result.tipps)
    assert result.platforms[0].primary_url == "https://link.springer.com/"


@pytest.mark.parametrize(("platform_url", "records", "expected"), [
    ("https://LINK.SPRINGER.COM./", [resource(url="https://wayf.springernature.com/?redirect_uri=https%3A%2F%2Flink.springer.com%2F")],
     ["Springer Link"]),
    ("https://www.nature.com/", [resource("NATURE", "https://wayf.springernature.com/?redirect_uri=https://www.nature.com/nature ")],
     ["NATURE"]),
    ("https://academic.oup.com/", [resource("OXFORD JOURNALS", "https://academic.oup.com/journals"),
         resource("OXFORD SCHOLARSHIP ONLINE", "https://academic.oup.com/books")], ["OXFORD JOURNALS", "OXFORD SCHOLARSHIP ONLINE"]),
    ("https://ieeexplore.ieee.org/", [resource("IEEE-IET ELECTRONIC LIBRARY", "https://ieeexplore.ieee.org/Xplore/home.jsp"),
         resource("IEEE-WILEY EBOOKS LIBRARY", "https://ieeexplore.ieee.org/xpl/wileyieeepress")],
     ["IEEE-IET ELECTRONIC LIBRARY", "IEEE-WILEY EBOOKS LIBRARY"]),
    ("https://epubs.siam.org/", [resource("SIAM电子期刊", "https://epubs.siam.org/journals"),
         resource("SIAM LOCUS过刊库", "https://epubs.siam.org/locus"), resource("SIAM电子书", "https://epubs.siam.org/ebooks")],
     ["SIAM LOCUS过刊库", "SIAM电子书", "SIAM电子期刊"]),
])
def test_resolver_retains_specific_products_and_only_offers_one_reliable_product(monkeypatch, platform_url, records, expected):
    use_catalog(monkeypatch, records)
    result = resolve_journal(JournalConfig(name="Fixture Journal", issn="1234-5679"),
                             transport=gokb_transport(platform_url=platform_url))
    assert [item.production for item in result.candidates] == expected
    assert all(item.evidence[0].platform_uuid == "platform-1" for item in result.candidates)
    assert (result.unique_candidate is not None) == (len(expected) == 1)
    assert (result.status == "unique") == (len(expected) == 1)


@pytest.mark.parametrize("failure", ["short_page", "changed_count", "wrong_offset", "wrong_max", "duplicate_uuid",
                                    "missing_uuid", "wrong_title", "not_current", "oversized_count", "missing_count"])
def test_an_invalid_page_yields_no_candidates(failure):
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    valid = gokb_transport(tipps=[tipp(i) for i in range(103)])

    def broken(request):
        response = valid.handle_request(request)
        query = request.url.params
        if query["componentType"] != "TitleInstancePackagePlatform":
            return response
        payload = response.json()
        if failure == "short_page":
            payload["records"] = payload["records"][:-1]
        elif failure == "changed_count" and query["offset"] != "0":
            payload["count"] = 102
        elif failure == "wrong_offset":
            payload["offset"] += 1
        elif failure == "wrong_max":
            payload["max"] -= 1
        elif failure == "duplicate_uuid" and query["offset"] != "0":
            payload["records"][0]["uuid"] = "tipp-0"
        elif failure == "missing_uuid":
            payload["records"][0].pop("uuid")
        elif failure == "wrong_title":
            payload["records"][0]["tippTitleUuid"] = "other-journal"
        elif failure == "not_current":
            payload["records"][0]["status"] = "Retired"
        elif failure == "oversized_count":
            payload["count"] = 10_001
        elif failure == "missing_count":
            payload.pop("count")
        return httpx.Response(200, json=payload)

    failed = resolve_journal(journal, transport=httpx.MockTransport(broken))
    assert failed.status == "unavailable"
    assert failed.error
    assert failed.gokb is None and failed.candidates == ()


def test_print_and_electronic_issns_retain_all_remote_journal_identities(monkeypatch):
    use_catalog(monkeypatch, [resource()])
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679", eissn="2049-3630")
    seen = []
    base = gokb_transport(titles=[title("print", "1234-5679"), title("electronic", "2049-3630")],
                          tipps=[tipp(0, "print"), tipp(1, "electronic")])

    def handler(request):
        if request.url.params.get("componentType") == "JournalInstance":
            identifier = request.url.params["identifier"]
            seen.append(identifier)
            row = title("print" if identifier == "1234-5679" else "electronic", identifier)
            row["identifiers"][0]["namespace"] = "issn" if identifier == "1234-5679" else "eissn"
            return page(request, [row])
        return base.handle_request(request)

    result = resolve_journal(journal, transport=httpx.MockTransport(handler))
    assert seen == ["1234-5679", "2049-3630"]
    assert {item.uuid for item in result.gokb.journals} == {"print", "electronic"}
    assert len(result.candidates) == 1
    assert result.unique_candidate is None
    assert result.status == "ambiguous"
    assert set(result.candidates[0].evidence[0].journal_uuids) == {"print", "electronic"}


def test_each_discovery_queries_gokb_and_distinguishes_empty_results_from_failure(monkeypatch):
    use_catalog(monkeypatch, [resource()])
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")

    def timeout(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    assert resolve_journal(journal, transport=gokb_transport()).status == "unique"
    empty = resolve_journal(journal, transport=gokb_transport(titles=[]))
    assert empty.status == "no_results" and empty.gokb.journals == ()
    failed = resolve_journal(journal, transport=httpx.MockTransport(timeout))
    assert failed.status == "unavailable"
    assert failed.error == "GOKB request timed out"
    assert failed.gokb is None and failed.unique_candidate is None and failed.candidates == ()


def test_publisher_text_in_searchstr_does_not_establish_platform_match(monkeypatch):
    use_catalog(monkeypatch, [resource("Unrelated product", "https://unrelated.example/",
                                       searchStr="OTHER PRODUCT-UNRELATED PRODUCT-SPRINGERLINK-SpringerLink")])
    result = resolve_journal(JournalConfig(name="Fixture Journal", issn="1234-5679"), transport=gokb_transport())
    assert result.candidates == ()


@pytest.mark.parametrize("name,extra", [
    ("Oxford Ebooks", {}),
    ("Closed journals", {"unavailable_reason": "Service closed"}),
])
def test_ebook_or_stopped_product_cannot_be_the_reliable_journal_default(monkeypatch, name, extra):
    use_catalog(monkeypatch, [resource(name, "https://academic.oup.com/", **extra)])
    result = resolve_journal(JournalConfig(name="Fixture Journal", issn="1234-5679"),
                             transport=gokb_transport(platform_url="https://academic.oup.com/"))
    assert len(result.candidates) == 1
    assert not result.candidates[0].reliable
    assert result.unique_candidate is None and result.status == "unresolved"


def test_ipv6_proxy_environment_fetches_complete_gokb_results(monkeypatch):
    isolate_proxy_environment(monkeypatch)
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    fixture = gokb_transport()
    monkeypatch.setenv("NO_PROXY", "fe80::/10,fc00::/7")
    monkeypatch.setenv("no_proxy", "fe80::/10,fc00::/7")
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture-proxy.test:8000")
    used_proxies = []

    def transport(**options):
        def handle(request):
            used_proxies.append(options["proxy"].url.host)
            return fixture.handle_request(request)
        return httpx.MockTransport(handle)

    monkeypatch.setattr(httpx, "HTTPTransport", transport)
    result = GokbClient().fetch(journal)
    assert used_proxies and set(used_proxies) == {"fixture-proxy.test"}
    assert result.platforms[0].name == "SpringerLink"


def test_proxy_http_failure_reports_gokb_unavailable(monkeypatch):
    isolate_proxy_environment(monkeypatch)
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    with http_server(lambda _: (503, {}, b"proxy unavailable")) as proxy:
        monkeypatch.setenv("HTTPS_PROXY", proxy.url)
        result = resolve_journal(journal)
        assert len(proxy.requests) == 1
    assert result.status == "unavailable"
    assert result.gokb is None
    assert result.error == "GOKB request failed"
