"""Isolated proxy routing; no user network configuration or external services."""

import os
import urllib.request

import httpx
import pytest

from allfold.http_client import create_http_client
from http_test_helpers import http_server, isolate_proxy_environment


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    isolate_proxy_environment(monkeypatch)


@pytest.mark.parametrize("proxy", [False, True])
@pytest.mark.parametrize("name", ["NO_PROXY", "no_proxy"])
def test_ipv6_cidr_does_not_break_client_creation(monkeypatch, proxy, name):
    monkeypatch.setenv(name, "fe80::/10,fc00::/7")
    if proxy:
        monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:12345")
    before = dict(os.environ)
    with create_http_client() as client:
        assert not client.is_closed
    assert client.is_closed
    assert dict(os.environ) == before


@pytest.fixture
def routes(monkeypatch):
    """Observe HTTPX's public transport boundary without DNS or sockets."""
    transports = []

    class RecordingTransport(httpx.BaseTransport):
        def __init__(self, **options):
            self.options = options
            self.closed = 0
            transports.append(self)

        def handle_request(self, request):
            proxy = self.options.get("proxy")
            return httpx.Response(200, text=proxy.url.host if proxy else "direct")

        def close(self):
            self.closed += 1

    monkeypatch.setattr(httpx, "HTTPTransport", RecordingTransport)
    return transports


@pytest.mark.parametrize(("rule", "matching", "other"), [
    ("example.com", "https://example.com", "https://notexample.com"),
    ("example.com", "https://a.b.example.com", "https://example.com.evil.test"),
    (".example.com", "https://a.example.com", "https://example.com"),
    ("*.example.com", "https://a.b.example.com", "https://example.com"),
    ("*example.com", "https://example.com", "https://notexample.com"),
    ("localhost", "http://localhost", "http://sub.localhost"),
    ("EXAMPLE.COM.", "https://a.example.com.", "https://notexample.com"),
    ("bücher.example", "https://bücher.example", "https://books.example"),
    ("faß.example", "https://faß.example", "https://fass.example"),
    ("192.168.1.7", "http://192.168.1.7", "http://192.168.1.8"),
    ("::1", "http://[0:0:0:0:0:0:0:1]", "http://[::2]"),
    ("[::1]", "http://[::1]", "http://[::2]"),
    ("192.168.0.0/16", "http://192.168.5.7", "http://192.169.5.7"),
    ("192.168.1.7/16", "http://192.168.5.7", "http://example.com"),
    ("fe80::/10", "http://[febf::123]", "http://[fec0::123]"),
    ("fc00::/7", "http://[fdff::123]", "http://[fe00::123]"),
    ("[fc00::]/7", "http://[fd00::1]", "http://[2001:db8::1]"),
    ("0.0.0.0/0", "http://192.0.2.1", "http://localhost"),
    ("::/0", "http://[2001:db8::1]", "http://127.0.0.1"),
    ("example.com:8080", "http://a.example.com:8080", "http://example.com:8081"),
    ("127.0.0.1:8080", "http://127.0.0.1:8080", "http://127.0.0.1:8081"),
    ("[::1]:8080", "http://[::1]:8080", "http://[::1]:8081"),
    ("example.com:443", "https://example.com", "http://example.com"),
    ("*:443", "https://any.example", "http://any.example"),
    ("http://example.com", "http://example.com", "http://a.example.com"),
    ("http://example.com", "http://example.com", "https://example.com"),
    ("http://example.com/", "http://example.com", "https://example.com"),
    ("all://example.com", "https://example.com", "https://a.example.com"),
    ("https://*.example.com:443", "https://a.example.com", "http://a.example.com"),
])
def test_no_proxy_routes_positive_and_negative_targets(monkeypatch, routes, rule, matching, other):
    monkeypatch.setenv("ALL_PROXY", "http://proxy.test:8000")
    monkeypatch.setenv("NO_PROXY", rule)
    with create_http_client() as client:
        assert client.get(matching).text == "direct"
        assert client.get(other).text == "proxy.test"


@pytest.mark.parametrize("invalid", [
    "[::1", "[::1]oops", "[example.com]", "[::1]:", "[::1]:99999", "x:bad", "x:0", ":80",
    "[::/0", "::]/0", "[[::]]/0", "[0.0.0.0]/0", "http://[::]/0/",
    "http://", "http://user@host", "http://example.com/path", "http://*?x", "ftp://*", "foo*bar",
    "*.", ".", "*:*", "10.0.0.0/33", "fe80::/129", "[::1]/junk", "10.0.0.0/8?",
    "127.0.0.1/8/../0", "127.0.0.1:8080/8", "[fe80::1%en0]/64", "bad host", "x:" + "9" * 5000,
])
def test_invalid_bypass_entry_is_ignored_without_widening_scope(monkeypatch, routes, invalid):
    monkeypatch.setenv("ALL_PROXY", "http://proxy.test")
    monkeypatch.setenv("NO_PROXY", f"{invalid},valid.test")
    with create_http_client() as client:
        assert client.get("https://valid.test").text == "direct"
        assert client.get("https://example.com").text == "proxy.test"
        assert client.get("http://127.0.0.1").text == "proxy.test"
        assert client.get("http://[2001:db8::1]").text == "proxy.test"


@pytest.mark.parametrize("rule", ["*", "invalid,*", "http://*,https://*"])
def test_wildcard_bypasses_all_configured_proxies(monkeypatch, routes, rule):
    monkeypatch.setenv("HTTP_PROXY", "http://http-proxy.test")
    monkeypatch.setenv("HTTPS_PROXY", "http://https-proxy.test")
    monkeypatch.setenv("NO_PROXY", rule)
    with create_http_client() as client:
        for url in ("http://example.com", "https://[fc00::1]", "https://192.0.2.1"):
            assert client.get(url).text == "direct"


@pytest.mark.parametrize(("environment", "http_route", "https_route"), [
    ({}, "direct", "direct"),
    ({"HTTP_PROXY": "upper.test:8000"}, "upper.test", "direct"),
    ({"https_proxy": "http://secure.test"}, "direct", "secure.test"),
    ({"ALL_PROXY": "http://fallback.test"}, "fallback.test", "fallback.test"),
    ({"ALL_PROXY": "http://fallback.test", "HTTP_PROXY": "http://specific.test"}, "specific.test", "fallback.test"),
    ({"HTTPS_PROXY": "http://upper.test", "https_proxy": "http://lower.test"}, "direct", "lower.test"),
    ({"HTTP_PROXY": "http://upper.test", "http_proxy": ""}, "direct", "direct"),
    ({"HTTP_PROXY": "http://upper.test", "REQUEST_METHOD": "GET"}, "direct", "direct"),
    ({"HTTP_PROXY": "http://upper.test", "http_proxy": "http://lower.test", "REQUEST_METHOD": "GET"}, "lower.test", "direct"),
    ({"ALL_PROXY": "http://fallback.test", "all_proxy": "http://lower.test"}, "lower.test", "lower.test"),
    ({"ALL_PROXY": "http://fallback.test", "HTTPS_PROXY": "http://specific.test"}, "fallback.test", "specific.test"),
])
def test_stdlib_proxy_priority_and_defaults(monkeypatch, routes, environment, http_route, https_route):
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    with create_http_client() as client:
        assert client.get("http://example.com").text == http_route
        assert client.get("https://example.com").text == https_route


def test_lowercase_no_proxy_overrides_uppercase(monkeypatch, routes):
    monkeypatch.setenv("ALL_PROXY", "http://proxy.test")
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setenv("no_proxy", "fc00::/7")
    with create_http_client() as client:
        assert client.get("https://[fd00::1]").text == "direct"
        assert client.get("https://example.com").text == "proxy.test"


def test_system_proxy_source_and_no_dns_for_cidrs(monkeypatch, routes):
    import socket

    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"https": "system-proxy.test:8080", "no": "fc00::/7"})
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: pytest.fail("Proxy selection must not resolve DNS"))
    with create_http_client() as client:
        assert client.get("https://[fc00::5]").text == "direct"
        assert client.get("https://internal.example").text == "system-proxy.test"


@pytest.mark.parametrize(("settings", "http_route", "https_route"), [
    ({"socks": "http://system-socks.test:1080"}, "system-socks.test", "system-socks.test"),
    ({"http": "http://specific.test", "socks": "http://system-socks.test:1080"}, "specific.test", "system-socks.test"),
    ({"all": "http://fallback.test", "socks": "http://system-socks.test:1080"}, "fallback.test", "fallback.test"),
    ({"http": "http://specific.test", "https": "http://secure.test", "socks": "http://system-socks.test:1080"},
     "specific.test", "secure.test"),
])
def test_macos_system_socks_fallback_and_priority(monkeypatch, routes, settings, http_route, https_route):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: settings)
    with create_http_client() as client:
        assert client.get("http://example.com").text == http_route
        assert client.get("https://example.com").text == https_route
    socks_pools = [t for t in routes if t.options.get("proxy") and t.options["proxy"].url.host == "system-socks.test"]
    if "system-socks.test" in (http_route, https_route):
        assert len(socks_pools) == 1
        assert socks_pools[0].options["proxy"].url.scheme == "socks5"
    else:
        assert not socks_pools  # Overridden SOCKS must not require an unused optional dependency.


def test_system_socks_normalization_preserves_explicit_port_80(monkeypatch, routes):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"socks": "http://system-socks.test:80"})
    with create_http_client():
        pass
    assert routes[1].options["proxy"].url.port == 80


@pytest.mark.parametrize("value", ["ftp://user:secret@private-proxy.test", "http://user:secret@private-proxy.test:bad",
                                     "http://", "http://private-proxy.test/path", "http://private-proxy.test:",
                                     "http://private-proxy.test:99999", "http://bad host"])
def test_bad_proxy_is_explicit_and_does_not_leak_configuration(monkeypatch, caplog, value):
    from allfold.http_client import ProxyConfigurationError

    monkeypatch.setenv("HTTPS_PROXY", value)
    with pytest.raises(ProxyConfigurationError, match="Invalid HTTPS_PROXY configuration") as error:
        create_http_client()
    assert "secret" not in str(error.value) + caplog.text
    assert "private-proxy.test" not in str(error.value) + caplog.text


@pytest.mark.parametrize("protocol", ["socks5", "socks5h"])
def test_socks_uses_httpx_optional_dependency_error(monkeypatch, protocol):
    import importlib.util
    from allfold.http_client import ProxyConfigurationError

    if importlib.util.find_spec("socksio") is not None:
        pytest.skip("This locked environment has SOCKS support")
    monkeypatch.setenv("ALL_PROXY", f"{protocol}://user:secret@127.0.0.1:9000")
    with pytest.raises(ProxyConfigurationError, match="optional SOCKS dependency"):
        create_http_client()


def test_system_socks_without_optional_dependency_fails_explicitly(monkeypatch):
    import importlib.util
    from allfold.http_client import ProxyConfigurationError

    if importlib.util.find_spec("socksio") is not None:
        pytest.skip("This locked environment has SOCKS support")
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {"socks": "http://system-socks.test:1080"})
    with pytest.raises(ProxyConfigurationError, match="SOCKS_PROXY.*socksio"):
        create_http_client()


def test_explicit_transport_and_direct_policy_do_not_read_proxies(monkeypatch):
    monkeypatch.setattr(urllib.request, "getproxies", lambda: pytest.fail("Unexpected proxy discovery"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="mocked"))
    with create_http_client(transport=transport) as client:
        assert client.get("https://example.com").text == "mocked"
    with create_http_client(proxy_policy="direct"):
        pass
    with create_http_client(trust_env=False):
        pass


def test_clients_snapshot_settings_and_close_every_pool_on_exception(monkeypatch, routes):
    monkeypatch.setenv("HTTPS_PROXY", "http://first.test")
    first = create_http_client()
    monkeypatch.setenv("HTTPS_PROXY", "http://second.test")
    with pytest.raises(KeyboardInterrupt):
        with first, create_http_client() as second:
            assert first.get("https://example.com").text == "first.test"
            assert second.get("https://example.com").text == "second.test"
            raise KeyboardInterrupt
    first.close()
    assert len(routes) == 4
    assert all(transport.closed == 1 for transport in routes)


def test_constructor_failure_closes_already_created_pools(monkeypatch, routes):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.test")
    with pytest.raises(TypeError):
        create_http_client(unknown_client_option=True)
    assert len(routes) == 2
    assert all(transport.closed == 1 for transport in routes)


def test_transport_creation_failure_closes_partial_pools(monkeypatch, routes):
    monkeypatch.setenv("HTTP_PROXY", "http://first.test")
    monkeypatch.setenv("HTTPS_PROXY", "http://second.test")
    recording = httpx.HTTPTransport

    def fail_last(**options):
        if options.get("proxy") and options["proxy"].url.host == "second.test":
            raise RuntimeError("transport creation interrupted")
        return recording(**options)

    monkeypatch.setattr(httpx, "HTTPTransport", fail_last)
    with pytest.raises(RuntimeError, match="creation interrupted"):
        create_http_client()
    assert len(routes) == 2
    assert all(transport.closed == 1 for transport in routes)


@pytest.mark.parametrize("protocol", ["http", "https", "socks5", "socks5h"])
def test_proxy_protocol_and_transport_options_are_preserved(monkeypatch, routes, protocol):
    import ssl

    monkeypatch.setenv("HTTPS_PROXY", f"{protocol}://user:password@proxy.test:8443")
    tls = ssl.create_default_context()
    limits = httpx.Limits(max_connections=7, max_keepalive_connections=3)
    with create_http_client(verify=tls, limits=limits, http1=True, http2=False):
        pass
    assert len(routes) == 2
    assert all(t.options["verify"] is tls and t.options["limits"] is limits for t in routes)
    proxy = routes[1].options["proxy"]
    assert proxy.url.scheme == protocol
    assert proxy.raw_auth == (b"user", b"password")


def test_real_requests_proxy_bypass_no_proxy_and_connection_pooling(monkeypatch):
    with http_server() as origin, http_server(lambda _: (200, {}, b"proxy")) as proxy:
        monkeypatch.setenv("HTTP_PROXY", proxy.url)
        with create_http_client() as client:
            assert client.get(origin.url + "/proxied").text == "proxy"
            assert client.get(origin.url + "/again").text == "proxy"
        assert len(proxy.requests) == 2
        assert proxy.requests[0].path == origin.url + "/proxied"
        assert proxy.requests[0].peer == proxy.requests[1].peer
        assert proxy.closed.wait(1)
        assert not origin.requests

        monkeypatch.setenv("NO_PROXY", "127.0.0.0/8")
        with create_http_client() as client:
            assert client.get(origin.url + "/bypassed").text == "origin"
        monkeypatch.delenv("HTTP_PROXY")
        monkeypatch.delenv("NO_PROXY")
        with create_http_client() as client:
            assert client.get(origin.url + "/no-proxy").text == "origin"
        assert [r.path for r in origin.requests] == ["/bypassed", "/no-proxy"]
        assert len(proxy.requests) == 2


@pytest.mark.parametrize("refused", [False, True])
def test_failed_proxy_does_not_send_to_reachable_origin(monkeypatch, refused):
    import socket

    with http_server() as origin:
        if refused:
            with http_server(lambda _: (407, {}, b"proxy authentication required")) as proxy:
                monkeypatch.setenv("HTTP_PROXY", proxy.url)
                with create_http_client() as client:
                    assert client.get(origin.url).status_code == 407
                assert len(proxy.requests) == 1
        else:
            # A bound non-listening port cannot be acquired by another test.
            with socket.socket() as unavailable:
                unavailable.bind(("127.0.0.1", 0))
                monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{unavailable.getsockname()[1]}")
                with create_http_client(timeout=.1) as client, pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
                    client.get(origin.url)
        assert not origin.requests


@pytest.mark.parametrize("start_direct", [False, True])
def test_redirect_reselects_route_for_new_target(monkeypatch, start_direct):
    with http_server() as origin:
        def proxy_response(request):
            if request.path.endswith("/redirect"):
                return 302, {"Location": origin.url + "/finish"}, b""
            return 200, {}, b"proxy finish"

        with http_server(proxy_response) as proxy:
            monkeypatch.setenv("HTTP_PROXY", proxy.url)
            monkeypatch.setenv("NO_PROXY", f"127.0.0.1:{origin.port}")
            if start_direct:
                with http_server(lambda _: (302, {"Location": proxy.url + "/finish"}, b"")) as start:
                    monkeypatch.setenv("NO_PROXY", f"127.0.0.1:{start.port}")
                    with create_http_client(follow_redirects=True) as client:
                        assert client.get(start.url).text == "proxy finish"
                    assert len(start.requests) == 1
            else:
                with create_http_client(follow_redirects=True) as client:
                    assert client.get("http://fixture.invalid/redirect").text == "origin"
                assert [r.path for r in origin.requests] == ["/finish"]
            assert len(proxy.requests) == 1


def test_streaming_timeout_and_early_close(monkeypatch):
    from threading import Event

    release = Event()

    def response(request):
        if request.path.endswith("/slow"):
            release.wait(2)
        return 200, {}, b"first-second"

    with http_server(response) as proxy:
        monkeypatch.setenv("HTTP_PROXY", proxy.url)
        try:
            with create_http_client(timeout=.05) as client:
                with client.stream("GET", "http://fixture.invalid/stream") as stream:
                    assert not stream.is_closed
                    assert next(stream.iter_bytes(chunk_size=5)) == b"first"
                assert stream.is_closed
                with pytest.raises(httpx.ReadTimeout):
                    client.get("http://fixture.invalid/slow")
        finally:
            release.set()
        assert len(proxy.requests) == 2


@pytest.mark.parametrize(("status", "server_id", "outcome"), [
    (200, "fixture-server", "VERIFIED"), (200, "", "INVALID_RESPONSE"),
    (403, "fixture-server", "API_FAILURE"), (412, "fixture-server", "SERVER_ID_MISMATCH"),
])
def test_zotero_health_stays_direct_with_external_proxy(monkeypatch, status, server_id, outcome):
    import allfold.integrations.zotero_local as zotero

    with http_server(lambda _: (status, {"Zotero-Server-ID": server_id}, b"{}")) as local:
        with http_server(lambda _: pytest.fail("Zotero must never reach the proxy")) as proxy:
            monkeypatch.setenv("ALL_PROXY", proxy.url)
            monkeypatch.setenv("HTTP_PROXY", proxy.url)
            monkeypatch.setattr(zotero, "LOCAL_API_BASE", local.url + "/api")
            with zotero.ZoteroLocalClient() as client:
                result = client.current_instance()
            assert result.outcome.value == outcome
            assert result.server_id == (server_id if outcome == "VERIFIED" else None)
            assert [(r.method, r.path) for r in local.requests] == [("GET", "/api/")]
            assert local.requests[0].headers["Zotero-API-Version"] == "3"
            assert not proxy.requests


@pytest.mark.parametrize("via_proxy", [False, True])
@pytest.mark.parametrize("ca_source", ["default", "file", "directory", "context"])
def test_real_tls_verification_and_environment_ca(monkeypatch, tmp_path, via_proxy, ca_source):
    from contextlib import nullcontext
    from pathlib import Path
    import ssl

    fixtures = Path(__file__).parent / "fixtures/http"
    certificate = fixtures / "localhost-cert.pem"
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(certificate, fixtures / "localhost-key.pem")
    options = {}
    if ca_source == "file":
        monkeypatch.setenv("SSL_CERT_FILE", str(certificate))
    elif ca_source == "directory":
        # OpenSSL's subject hash for the fixed, public test certificate.
        (tmp_path / "8461719e.0").write_bytes(certificate.read_bytes())
        monkeypatch.setenv("SSL_CERT_DIR", str(tmp_path))
    elif ca_source == "context":
        options["verify"] = ssl.create_default_context(cafile=str(certificate))

    with http_server(tls=tls) as origin:
        proxy_context = http_server(tunnel_target=("127.0.0.1", origin.port)) if via_proxy else nullcontext()
        with proxy_context as proxy:
            if proxy:
                monkeypatch.setenv("HTTPS_PROXY", proxy.url)
            with create_http_client(**options) as client:
                if ca_source == "default":
                    with pytest.raises(httpx.ConnectError, match="CERTIFICATE_VERIFY_FAILED"):
                        client.get(origin.url)
                    assert not origin.requests
                else:
                    assert client.get(origin.url).text == "origin"
                    assert len(origin.requests) == 1
            if proxy:
                assert [r.method for r in proxy.requests] == ["CONNECT"]


def test_invalid_environment_ca_is_not_silently_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    with pytest.raises(FileNotFoundError):
        create_http_client()


def test_proxy_authentication_is_sent_without_logging_credentials(monkeypatch, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    with http_server(lambda _: (200, {}, b"proxy")) as proxy:
        monkeypatch.setenv("HTTP_PROXY", proxy.url.replace("//", "//fixture-user:fixture-password@"))
        with create_http_client() as client:
            assert client.get("http://fixture.invalid/").text == "proxy"
        assert proxy.requests[0].headers["Proxy-Authorization"].startswith("Basic ")
    assert "fixture-user" not in caplog.text
    assert "fixture-password" not in caplog.text
    assert "Proxy-Authorization" not in caplog.text


@pytest.mark.parametrize("provider", ["crossref", "openalex"])
@pytest.mark.parametrize("injected", [False, True])
def test_provider_requests_keep_proxy_query_and_retry_semantics(monkeypatch, provider, injected):
    from datetime import date
    from urllib.parse import parse_qs
    from allfold.providers.supplemental import SupplementalClient
    from allfold.providers.openalex import OpenAlexClient

    monkeypatch.setenv("NO_PROXY", "fe80::/10,fc00::/7")
    monkeypatch.setenv("HTTPS_PROXY", "http://fixture-proxy.test:8000")
    requests, used_proxies, sleeps = [], [], []

    def handle(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b'{"ok":true}')

    if injected:
        options = {"transport": httpx.MockTransport(handle)}
        monkeypatch.setattr(urllib.request, "getproxies", lambda: pytest.fail("Injected transport read proxies"))
    else:
        def transport(**options):
            def route(request):
                used_proxies.append(options["proxy"].url.host)
                return handle(request)
            return httpx.MockTransport(route)
        monkeypatch.setattr(httpx, "HTTPTransport", transport)
        options = {}

    if provider == "crossref":
        with SupplementalClient("crossref", interval=0, sleep=sleeps.append, **options) as client:
            assert client.request("/works/10.5555/known", {"mailto":"fixture@example.test"}) == {"ok": True}
        params = requests[-1].url.params
        assert requests[-1].url.path == "/works/10.5555/known"
        assert params["mailto"] == "fixture@example.test"
    else:
        with OpenAlexClient(api_key="fixture-key", sleep=sleeps.append, **options) as client:
            assert client.get_sources_by_issns(["1234-5679", "2345-6787"]) == {"ok": True}
        assert requests[-1].url.params["filter"] == "issn:1234-5679|2345-6787"
        assert requests[-1].headers["Authorization"] == "Bearer fixture-key"
    assert len(requests) == 2
    assert sleeps
    if not injected:
        assert used_proxies == ["fixture-proxy.test", "fixture-proxy.test"]


def test_provider_redirect_policies_are_preserved():
    from datetime import date
    from allfold.providers.supplemental import SupplementalClient
    from allfold.providers.openalex import OpenAlexClient

    requests = []

    def handle(request):
        requests.append(request)
        if request.url.path != "/destination":
            return httpx.Response(302, headers={"Location": "/destination"})
        return httpx.Response(200, json={"ok": True})

    with SupplementalClient("crossref", interval=0, transport=httpx.MockTransport(handle)) as client:
        assert client.request("/works/10.5555/known", {}) == {"ok": True}
    assert len(requests) == 2
    with OpenAlexClient(transport=httpx.MockTransport(handle)) as client:
        assert client.search_sources("statistics") == {"ok": True}
    assert len(requests) == 4
    assert requests[-1].url.path == "/destination"


def test_openalex_authorization_error_remains_terminal():
    from allfold.providers.openalex import OpenAlexClient, OpenAlexFailureKind, OpenAlexRequestError

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(403)

    with OpenAlexClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(OpenAlexRequestError) as denied:
            client.search_sources("statistics")
        assert denied.value.kind == OpenAlexFailureKind.AUTHORIZATION
        with pytest.raises(OpenAlexRequestError) as circuit:
            client.search_sources("statistics")
        assert circuit.value.kind == OpenAlexFailureKind.CIRCUIT_OPEN
    assert len(requests) == 1
