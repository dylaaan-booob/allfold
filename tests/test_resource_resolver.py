"""Offline public resource discovery: complete snapshots and conservative choices."""

import json

import httpx
import pytest

from allfold.application.carsi_catalog import CatalogError, get_carsi_catalog, parse_carsi_directory
from allfold.config import JournalConfig
from http_test_helpers import http_server, isolate_proxy_environment


def directory(*records):
    return '<script>var SPList=' + json.dumps(list(records)) + ';</script>'


def resource(name="Springer Link", url="https://link.springer.com/", **extra):
    return dict(production=name, searchStr=name.upper(), url=url, sptype="1") | extra


def test_catalog_is_shared_and_a_failed_refresh_keeps_last_valid_resources(tmp_path):
    cache = tmp_path / ".allfold/resources.sqlite"
    first = get_carsi_catalog(cache, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, text=directory(resource()), headers={"content-type": "text/html"})))
    assert first.status == "fresh"
    assert first.resources[0].production == "Springer Link"

    def offline(request):
        raise httpx.ConnectError("offline", request=request)

    cached = get_carsi_catalog(cache, transport=httpx.MockTransport(offline))
    assert cached.status == "cached"
    stale = get_carsi_catalog(cache, refresh=True, transport=httpx.MockTransport(offline))
    assert stale.status == "stale"
    assert stale.error == "CARSI directory request failed"
    assert stale.resources == first.resources
    assert get_carsi_catalog(cache).resources == first.resources


def test_duplicate_catalog_identity_is_rejected():
    with pytest.raises(CatalogError, match="duplicate production"):
        parse_carsi_directory(directory(resource(), resource(url="https://example.org/")))


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


def test_gokb_reads_all_current_tipp_pages_and_reuses_complete_shared_snapshot(tmp_path):
    from allfold.providers.gokb import get_journal_resources

    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    cache = tmp_path / ".allfold/resources.sqlite"
    result = get_journal_resources(cache, journal, transport=gokb_transport(tipps=[tipp(i) for i in range(103)]))
    assert result.status == "fresh"
    assert result.outcome == "ok"
    assert len(result.snapshot.tipps) == 103
    assert result.snapshot.tipps[-1].package_name == "Journal collection"
    assert result.snapshot.tipps[-1].journal_uuid == "journal-1"
    assert result.snapshot.platforms[0].primary_url == "https://link.springer.com/"
    assert get_journal_resources(cache, journal).snapshot == result.snapshot


def resolver_transport(records, *, titles=None, tipps=None, platform_url="https://link.springer.com/"):
    gokb = gokb_transport(titles=titles, tipps=tipps, platform_url=platform_url)
    return httpx.MockTransport(lambda request: httpx.Response(200, text=directory(*records),
        headers={"content-type": "text/html"}) if request.url.host == "www.carsi.edu.cn"
        else gokb.handle_request(request))


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
def test_resolver_retains_specific_products_and_only_offers_one_reliable_product(tmp_path, platform_url, records, expected):
    from allfold.application.journal_resolver import resolve_journal

    result = resolve_journal(tmp_path / "config.yaml", JournalConfig(name="Fixture Journal", issn="1234-5679"),
                             cache_path=tmp_path / "resources.sqlite",
                             transport=resolver_transport(records, platform_url=platform_url))
    assert [item.production for item in result.candidates] == expected
    assert all(item.evidence[0].platform_uuid == "platform-1" for item in result.candidates)
    assert (result.unique_candidate is not None) == (len(expected) == 1)
    assert (result.status == "unique") == (len(expected) == 1)


@pytest.mark.parametrize("failure", ["short_page", "changed_count", "wrong_offset", "wrong_max", "duplicate_uuid",
                                    "missing_uuid", "wrong_title", "not_current", "oversized_count", "missing_count"])
def test_an_invalid_refresh_never_replaces_last_complete_gokb_snapshot(tmp_path, failure):
    from allfold.providers.gokb import get_journal_resources

    cache = tmp_path / "resources.sqlite"
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    first = get_journal_resources(cache, journal, transport=gokb_transport())
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

    failed = get_journal_resources(cache, journal, refresh=True, transport=httpx.MockTransport(broken))
    assert failed.status == "stale"
    assert failed.error
    assert failed.snapshot == first.snapshot
    assert get_journal_resources(cache, journal).snapshot == first.snapshot


def test_print_and_electronic_issns_retain_all_remote_journal_identities(tmp_path):
    from allfold.application.journal_resolver import resolve_journal

    journal = JournalConfig(name="Fixture Journal", issn="1234-5679", eissn="2049-3630")
    seen = []
    base = resolver_transport([resource()], titles=[title("print", "1234-5679"), title("electronic", "2049-3630")],
                              tipps=[tipp(0, "print"), tipp(1, "electronic")])

    def handler(request):
        if request.url.params.get("componentType") == "JournalInstance":
            identifier = request.url.params["identifier"]
            seen.append(identifier)
            row = title("print" if identifier == "1234-5679" else "electronic", identifier)
            row["identifiers"][0]["namespace"] = "issn" if identifier == "1234-5679" else "eissn"
            return page(request, [row])
        return base.handle_request(request)

    result = resolve_journal(tmp_path / "config.yaml", journal, cache_path=tmp_path / "resources.sqlite",
                             transport=httpx.MockTransport(handler))
    assert seen == ["1234-5679", "2049-3630"]
    assert {item.uuid for item in result.gokb.snapshot.journals} == {"print", "electronic"}
    assert len(result.candidates) == 1
    assert result.unique_candidate is None
    assert result.status == "ambiguous"
    assert set(result.candidates[0].evidence[0].journal_uuids) == {"print", "electronic"}


def test_confirmed_no_results_and_network_failure_remain_distinct(tmp_path):
    from allfold.providers.gokb import get_journal_resources

    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")

    def timeout(request):
        raise httpx.ReadTimeout("fixture timeout", request=request)

    failed = get_journal_resources(tmp_path / "failed.sqlite", journal, transport=httpx.MockTransport(timeout))
    assert failed.outcome == "unavailable"
    assert failed.snapshot is None
    empty = get_journal_resources(tmp_path / "empty.sqlite", journal, transport=gokb_transport(titles=[]))
    assert empty.outcome == "no_results"
    assert empty.status == "fresh"
    fallback = get_journal_resources(tmp_path / "empty.sqlite", journal, refresh=True, transport=httpx.MockTransport(timeout))
    assert fallback.outcome == "no_results"
    assert fallback.status == "stale"


def test_catalog_rename_and_product_conflict_are_visible_without_rewriting_choices(tmp_path):
    from allfold.application.carsi_catalog import validate_carsi_service

    cache = tmp_path / "resources.sqlite"

    def fetch(rows, refresh=False):
        return get_carsi_catalog(cache, refresh=refresh, transport=resolver_transport(rows))

    fetch([resource("Old name")])
    renamed = fetch([resource("New name")], refresh=True)
    assert renamed.changes[0].kind == "possible_rename"
    assert renamed.changes[0].previous_production == "Old name"
    assert renamed.changes[0].productions == ("New name",)
    assert get_carsi_catalog(cache).changes == renamed.changes
    with pytest.raises(CatalogError, match="not in"):
        validate_carsi_service("Old name", catalog=renamed)
    conflicted = fetch([resource("Product A"), resource("Product B")], refresh=True)
    assert conflicted.changes[0].kind == "identity_conflict"
    assert set(conflicted.changes[0].productions) == {"Product A", "Product B"}


def test_manual_carsi_choice_needs_catalog_membership_but_no_gokb_platform_proof(tmp_path):
    from allfold.application.carsi_catalog import validate_carsi_service
    from allfold.application.journal_resolver import resolve_journal

    journal = JournalConfig(name="Fixture Journal", issn="1234-5679", access_service_id="svc_" + "a" * 32)
    result = resolve_journal(tmp_path / "config.yaml", journal, cache_path=tmp_path / "resources.sqlite",
        transport=resolver_transport([resource("EBSCO", "https://search.ebscohost.com/")],
                                     platform_url="https://pubsonline.informs.org/"))
    assert result.candidates == ()
    assert result.status == "unresolved"
    assert validate_carsi_service("EBSCO", catalog=result.catalog).production == "EBSCO"
    assert journal.access_service_id == "svc_" + "a" * 32
    with pytest.raises(CatalogError):
        validate_carsi_service("Unknown CARSI", catalog=result.catalog)


def test_publisher_text_in_searchstr_does_not_establish_platform_match(tmp_path):
    from allfold.application.journal_resolver import resolve_journal

    catalog = [resource("Unrelated product", "https://unrelated.example/",
                        searchStr="OTHER PRODUCT-UNRELATED PRODUCT-SPRINGERLINK-SpringerLink")]
    result = resolve_journal(tmp_path / "config.yaml", JournalConfig(name="Fixture Journal", issn="1234-5679"),
                             cache_path=tmp_path / "resources.sqlite", transport=resolver_transport(catalog))
    assert result.candidates == ()


def test_an_ebook_only_host_match_is_never_a_reliable_journal_default(tmp_path):
    from allfold.application.journal_resolver import resolve_journal

    result = resolve_journal(tmp_path / "config.yaml", JournalConfig(name="Fixture Journal", issn="1234-5679"),
        cache_path=tmp_path / "resources.sqlite", transport=resolver_transport([
            resource("Oxford Ebooks", "https://academic.oup.com/books")], platform_url="https://academic.oup.com/"))
    assert len(result.candidates) == 1
    assert not result.candidates[0].reliable
    assert result.unique_candidate is None


def test_new_cache_rejects_a_preexisting_journal_symlink_without_touching_its_target(tmp_path):
    from allfold.persistence.resource_cache import ResourceCacheError, write_snapshot

    target = tmp_path / "unrelated.txt"
    target.write_text("preserve this user file")
    cache = tmp_path / "resources.sqlite"
    cache.with_name(cache.name + "-journal").symlink_to(target)
    with pytest.raises(ResourceCacheError, match="sidecar"):
        write_snapshot(cache, "fixture", {"complete": True})
    assert target.read_text() == "preserve this user file"
    assert not cache.exists()


@pytest.mark.parametrize("suffix", ["-journal", "-wal", "-shm"])
@pytest.mark.parametrize("kind", ["hardlink", "symlink", "directory"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_resource_cache_rejects_unsafe_sidecars_before_opening(tmp_path, suffix, kind, operation):
    from allfold.persistence.resource_cache import ResourceCacheError, read_snapshot, write_snapshot

    cache = tmp_path / "resources.sqlite"
    write_snapshot(cache, "fixture", {"complete": True})
    target = tmp_path / "unrelated.txt"
    original = b"\x00" + b"preserve user bytes\n" * 100
    target.write_bytes(original)
    sidecar = cache.with_name(cache.name + suffix)
    if kind == "hardlink":
        sidecar.hardlink_to(target)
    elif kind == "symlink":
        sidecar.symlink_to(target)
    else:
        sidecar.mkdir()
    with pytest.raises(ResourceCacheError, match="sidecar"):
        if operation == "read":
            read_snapshot(cache, "fixture")
        else:
            write_snapshot(cache, "fixture", {"complete": False})
    assert target.read_bytes() == original


def test_default_resource_path_is_shared_across_configurations_and_never_stores_user_choices(tmp_path):
    from allfold.application.journal_resolver import resolve_journal

    config = tmp_path / "statistics.yaml"
    other = tmp_path / "machine-learning.yaml"
    config.write_text("keep statistics config bytes")
    other.write_text("keep machine learning config bytes")
    selected = JournalConfig(name="Fixture Journal", issn="1234-5679", access_service_id="svc_" + "b" * 32)
    first = resolve_journal(config, selected, transport=resolver_transport([resource()]))

    def offline(request):
        pytest.fail("a second configuration should reuse the shared external snapshot")

    unassigned = JournalConfig(name="Fixture Journal", issn="1234-5679")
    second = resolve_journal(other, unassigned, transport=httpx.MockTransport(offline))
    assert second.unique_candidate == first.unique_candidate
    assert second.gokb.status == second.catalog.status == "cached"
    assert (tmp_path / ".allfold/resources.sqlite").is_file()
    assert not (tmp_path / ".allfold/user-data.sqlite").exists()
    assert selected.access_service_id == "svc_" + "b" * 32
    assert unassigned.access_service_id is None
    assert config.read_text() == "keep statistics config bytes"
    assert other.read_text() == "keep machine learning config bytes"


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("source", ["carsi", "gokb"])
def test_ipv6_proxy_environment_fetches_valid_complete_resources(tmp_path, monkeypatch, cached, source):
    from allfold.providers.gokb import get_journal_resources

    isolate_proxy_environment(monkeypatch)
    path = tmp_path / "resources.sqlite"
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    lookup = (lambda **kw: get_carsi_catalog(path, **kw)) if source == "carsi" else (
        lambda **kw: get_journal_resources(path, journal, **kw))
    fixture = resolver_transport([resource()]) if source == "carsi" else gokb_transport()
    if cached:
        assert lookup(transport=fixture).status == "fresh"
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
    result = lookup(refresh=True)
    assert result.status == "fresh"
    assert result.error is None
    assert used_proxies and set(used_proxies) == {"fixture-proxy.test"}
    if source == "carsi":
        assert result.resources[0].production == "Springer Link"
    else:
        assert result.snapshot.platforms[0].name == "SpringerLink"


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("source", ["carsi", "gokb"])
def test_proxy_http_failure_preserves_last_good_cache(tmp_path, monkeypatch, cached, source):
    from allfold.providers.gokb import get_journal_resources

    isolate_proxy_environment(monkeypatch)
    path = tmp_path / "resources.sqlite"
    journal = JournalConfig(name="Fixture Journal", issn="1234-5679")
    lookup = (lambda **kw: get_carsi_catalog(path, **kw)) if source == "carsi" else (
        lambda **kw: get_journal_resources(path, journal, **kw))
    fixture = resolver_transport([resource()]) if source == "carsi" else gokb_transport()
    previous = lookup(transport=fixture) if cached else None
    with http_server(lambda _: (503, {}, b"proxy unavailable")) as proxy:
        monkeypatch.setenv("HTTPS_PROXY", proxy.url)
        result = lookup(refresh=True)
        assert len(proxy.requests) == 1
    assert result.status == ("stale" if cached else "unavailable")
    if source == "carsi":
        assert result.resources == (previous.resources if previous else ())
    else:
        assert result.snapshot == (previous.snapshot if previous else None)
    assert result.error is not None
    if previous:
        assert lookup().fetched_at == previous.fetched_at
