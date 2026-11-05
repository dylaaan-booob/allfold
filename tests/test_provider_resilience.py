"""All Integrated Run HTTP providers share bounded, correctly classified failures."""
import httpx
import pytest

from allfold.providers.integrated import DiscoveryClient, DiscoveryError, ProviderHTTPError, PROVIDERS


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_temporary_html_server_errors_recover_for_every_provider(provider, status):
    calls, waits = [], []
    def response(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(status, headers={'content-type': 'text/html'},
                                  text=f'<html><h1>{status} upstream unavailable</h1></html>')
        return httpx.Response(200, json={'result': 'recovered'})
    with DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, sleep=waits.append) as client:
        result = client.request('/fixture', {'id': 'known'})
    assert result == {'result': 'recovered'} and waits == [5, 10]
    assert len(calls) == 3 and len({str(request.url) for request in calls}) == 1


def test_html_429_honors_retry_after_without_becoming_a_bot_challenge():
    calls, waits = [], []
    with DiscoveryClient('crossref', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(429, headers={'content-type': 'text/html', 'retry-after': '3'},
                                               text='<html>Too many requests</html>')), interval=0, sleep=waits.append) as client:
        with pytest.raises(ProviderHTTPError) as caught:
            client.request('/works/10.5555/example', {})
    assert caught.value.status == 429 and waits == [3, 3] and len(calls) == 3


def test_long_retry_after_is_reported_without_shortening_or_early_retry():
    calls, waits = [], []
    with DiscoveryClient('zbmath', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(503, headers={'retry-after': '120'})), interval=0, sleep=waits.append) as client:
        with pytest.raises(ProviderHTTPError, match='Retry-After exceeds'):
            client.request('/document/123', {})
    assert len(calls) == 1 and waits == []


def test_dblp_challenge_stops_later_requests_in_the_same_run_client():
    calls = []
    with DiscoveryClient('dblp', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(202, headers={'content-type': 'text/html'},
            text='<html>Making sure you are not a bot! Protected by Anubis</html>')), interval=0) as client:
        for stream in ('conf/nips', 'conf/icml'):
            with pytest.raises(DiscoveryError, match='Anubis'):
                client.request('/search/publ/api', {'q': f'streamid:{stream}:'})
    assert len(calls) == 1


def test_dblp_default_spacing_follows_official_crawling_guidance():
    waits = []
    with DiscoveryClient('dblp', transport=httpx.MockTransport(lambda _:httpx.Response(200, json={})), sleep=waits.append) as client:
        client.request('/fixture', {})
        client.request('/fixture', {})
    assert len(waits) == 1 and 1.5 < waits[0] <= 2


@pytest.mark.parametrize('status', [400, 401, 403, 404])
def test_permanent_http_errors_are_not_retried_or_mislabeled(status):
    calls = []
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(status, headers={'content-type': 'text/html'},
                                               text='<html>Request rejected</html>')), interval=0) as client:
        with pytest.raises(ProviderHTTPError) as caught:
            client.request('/works/W123', {})
    assert caught.value.status == status and len(calls) == 1


def test_retry_after_http_date_and_invalid_values_are_bounded():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    for header, expected in ((format_datetime(datetime.now(timezone.utc) + timedelta(seconds=12), usegmt=True), None),
                             ('NaN', 5), ('not-a-date', 5)):
        calls, waits = [], []
        def response(request):
            calls.append(request)
            return httpx.Response(503, headers={'retry-after': header}) if len(calls) == 1 else httpx.Response(200, json={})
        with DiscoveryClient('crossref', transport=httpx.MockTransport(response), interval=0, sleep=waits.append) as client:
            client.request('/fixture', {})
        assert len(calls) == 2 and len(waits) == 1
        assert 8 <= waits[0] <= 12 if expected is None else waits == [expected]


def test_success_status_with_generic_html_is_invalid_metadata_not_an_empty_result():
    calls = []
    with DiscoveryClient('zbmath', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(200, headers={'content-type': 'text/html'},
                                               text='<html>Maintenance screen</html>')), interval=0) as client:
        with pytest.raises(DiscoveryError, match='unexpected HTML'):
            client.request('/fixture', {})
    assert len(calls) == 1


def test_arxiv_wrong_xml_document_is_a_supplement_failure():
    from allfold.providers.supplemental import SupplementalClient
    with SupplementalClient('arxiv', transport=httpx.MockTransport(lambda _:httpx.Response(200,
        text='<response><version>1</version></response>')), interval=0) as client:
        with pytest.raises(DiscoveryError, match='Atom feed'):
            client.lookup('arxiv', '2201.12345')


def test_zbmath_incomplete_mapping_response_is_not_a_confirmed_missing_source():
    from datetime import date
    from allfold.keywords import parse_keyword_expression
    from allfold.providers.integrated import SourceScope
    with DiscoveryClient('zbmath', transport=httpx.MockTransport(lambda _:httpx.Response(200,
        json={'version':'1'})), interval=0) as client:
        result = client.discover(SourceScope('journal','Journal',issns=('0162-1459',)),
                                 parse_keyword_expression('learning'),date(2026,1,1),date(2026,12,31))
    assert result.status == 'failed' and 'response' in result.limitations[0]
