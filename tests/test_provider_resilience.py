"""Discovery and metadata HTTP adapters classify bounded failures."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from threading import Event, Thread
import time

import httpx
import pytest

from allfold.providers.integrated import DiscoveryClient, DiscoveryError, ProviderHTTPError, PROVIDERS
from allfold.providers.openalex import OpenAlexClient
from allfold.providers.provider_http import ProviderBudgetExceeded, ProviderCooldowns
from http_test_helpers import http_server, isolate_proxy_environment


class Clock:
    def __init__(self):
        self.now = 100.0
        self.waits = []

    def monotonic(self):
        return self.now

    def wall_time(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=self.now)

    def sleep(self, seconds):
        self.waits.append(seconds)
        self.now += seconds

    def options(self):
        return dict(sleep=self.sleep, monotonic=self.monotonic, wall_time=self.wall_time,
                    jitter=lambda: 0.4)


@pytest.mark.parametrize('provider', PROVIDERS)
@pytest.mark.parametrize('status', [500, 502, 503, 504])
def test_temporary_html_server_errors_recover_for_every_provider(provider, status):
    calls, clock = [], Clock()
    def response(request):
        calls.append(request)
        if len(calls) < 3:
            return httpx.Response(status, headers={'content-type': 'text/html'},
                                  text=f'<html><h1>{status} upstream unavailable</h1></html>')
        return httpx.Response(200, json={'result': 'recovered'})
    with DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **clock.options()) as client:
        result = client.request('/fixture', {'id': 'known'})
    assert result == {'result': 'recovered'} and clock.waits == [5.5, 11]
    assert len(calls) == 3 and len({str(request.url) for request in calls}) == 1


def test_html_429_honors_retry_after_without_becoming_a_bot_challenge():
    calls, clock = [], Clock()
    with DiscoveryClient('crossref', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(429, headers={'content-type': 'text/html', 'retry-after': '3'},
                                               text='<html>Too many requests</html>')), interval=0, **clock.options()) as client:
        with pytest.raises(ProviderHTTPError) as caught:
            client.request('/works/10.5555/example', {})
    assert caught.value.status == 429 and clock.waits == [3, 3] and len(calls) == 3


def test_long_retry_after_survives_operation_budget_without_early_dispatch():
    clock, cooldowns, calls, evidence = Clock(), ProviderCooldowns(), [], []

    def respond(request):
        calls.append(clock.now)
        if len(calls) == 1:
            return httpx.Response(503, headers={'Retry-After': '120'})
        return httpx.Response(200, json={'result': 'recovered'})

    def client(**kwargs):
        return DiscoveryClient('crossref', transport=httpx.MockTransport(respond),
                               interval=0, cooldowns=cooldowns, **clock.options(), **kwargs)

    with client(recovery_observer=lambda event, details: evidence.append((event, details))) as first:
        with pytest.raises(ProviderHTTPError) as failure:
            first.request('/works/10.5555/known', {})
        assert failure.value.status == 503
        assert first.request_count == 1
    with client() as second:
        with pytest.raises(ProviderBudgetExceeded):
            second.request('/works/10.5555/known', {})
        assert second.request_count == 0
    assert calls == [100] and clock.waits == []
    assert any(event == 'recovery_exhausted' and detail['recovery_action'] == 'cooldown_wait'
               and detail['recovery_stop'] == 'budget' and detail['status'] == 503
               and detail['dispatch_outcome'] == 'not_dispatched'
               for event, detail in evidence)

    clock.now += 60
    with client() as later:
        assert later.request('/works/10.5555/known', {}) == {'result': 'recovered'}
    assert calls == [100, 220] and clock.waits == [60]


@pytest.mark.parametrize('streamed', [False, True])
def test_provider_deadline_stops_a_late_response_without_another_dispatch(streamed):
    clock, calls, chunks = Clock(), [], []

    class DelayedBody(httpx.SyncByteStream):
        def __iter__(self):
            yield b'{"result":'
            clock.now += 3
            yield b'"late"'
            chunks.append('read past deadline')
            yield b'}'

        def close(self):
            chunks.append('closed')

    def respond(request):
        calls.append(request)
        if streamed:
            return httpx.Response(200, stream=DelayedBody())
        clock.now += 3
        return httpx.Response(200, json={'result': 'late'})

    with DiscoveryClient('crossref', deadline=clock.now + 2, interval=0,
                         transport=httpx.MockTransport(respond), **clock.options()) as client:
        with pytest.raises(ProviderBudgetExceeded):
            client.request('/fixture', {})
        assert client.request_count == 1
    assert len(calls) == 1
    assert chunks == (['closed'] if streamed else [])


@pytest.mark.parametrize(('route', 'status'), [('direct', 200), ('proxy', 200), ('connect', 200), ('direct', 503)])
def test_provider_deadline_interrupts_a_blocked_body_read(monkeypatch, route, status):
    from contextlib import ExitStack
    from pathlib import Path
    import ssl
    from allfold.providers import integrated

    isolate_proxy_environment(monkeypatch)
    body_started, allow_tail, tail_released = Event(), Event(), Event()
    cooldowns = ProviderCooldowns()

    def slow_body(handler):
        time.sleep(0.35)
        handler.send_response(status)
        handler.send_header('Content-Length', '11')
        if status == 503:
            handler.send_header('Retry-After', '60')
        handler.end_headers()
        handler.wfile.write(b'{"ok":')
        handler.wfile.flush()
        body_started.set()
        allow_tail.wait(0.7)
        tail_released.set()
        try:
            handler.wfile.write(b'true}')
        except (BrokenPipeError, ConnectionResetError):
            pass

    with ExitStack() as stack:
        tls = None
        if route == 'connect':
            fixtures = Path(__file__).parent / 'fixtures/http'
            cert = fixtures / 'localhost-cert.pem'
            tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            tls.load_cert_chain(cert, fixtures / 'localhost-key.pem')
            monkeypatch.setenv('SSL_CERT_FILE', str(cert))
        server = stack.enter_context(http_server(slow_body, tls=tls))
        url = server.url
        if route == 'proxy':
            monkeypatch.setenv('HTTP_PROXY', server.url)
            url = 'http://provider.invalid'
        if route == 'connect':
            proxy = stack.enter_context(http_server(tunnel_target=('127.0.0.1', server.port)))
            monkeypatch.setenv('HTTPS_PROXY', proxy.url)
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', url)
        try:
            with DiscoveryClient('crossref', interval=0, cooldowns=cooldowns,
                                 deadline=time.monotonic() + 0.8) as client:
                expected = ProviderHTTPError if status == 503 else ProviderBudgetExceeded
                with pytest.raises(expected) as stopped:
                    client.request('/fixture', {})
                if status == 503:
                    assert stopped.value.status == 503
                assert client.request_count == 1
                assert body_started.is_set()
                assert not tail_released.is_set(), 'read returned only after the server released its final chunk'
                if route == 'connect':
                    assert proxy.closed.wait(1), 'aborted read left the proxy tunnel open'
        finally:
            allow_tail.set()
        assert server.closed.wait(1), 'aborted read left the server connection open'
        assert [request.path for request in server.requests] == [url + '/fixture' if route == 'proxy' else '/fixture']
        if route == 'connect':
            assert [request.method for request in proxy.requests] == ['CONNECT']
        if status == 503:
            with DiscoveryClient('crossref', interval=0, cooldowns=cooldowns,
                                 deadline=time.monotonic() + 1) as waiting:
                with pytest.raises(ProviderBudgetExceeded, match='HTTP 503 cooldown'):
                    waiting.request('/another', {})
                assert waiting.request_count == 0


def test_completion_final_check_routes_only_the_failed_redirect_target(monkeypatch):
    from allfold.providers import integrated

    isolate_proxy_environment(monkeypatch)
    clock = Clock()

    def respond(_):
        if len(origin.requests) < 4:
            return 503, {'Retry-After': '3'}, b''
        return 200, {}, b'{"results":[]}'

    with http_server(respond) as origin:
        with http_server(lambda _: (302, {'Location': origin.url + '/target'}, b'')) as proxy:
            monkeypatch.setenv('HTTP_PROXY', proxy.url)
            monkeypatch.setenv('NO_PROXY', f'127.0.0.1:{origin.port}')
            monkeypatch.setitem(integrated.BASE_URLS, 'openalex', 'http://provider.invalid')
            with DiscoveryClient('openalex', api_key='synthetic-key', interval=0,
                                 cooldowns=ProviderCooldowns(), **clock.options()) as client:
                with client.capture_transient_failures() as failures:
                    with pytest.raises(ProviderHTTPError):
                        client.request('/works', {})
                assert failures
                client.begin_settlement()
                assert client.request('/works', {}) == {'results': []}
                assert client.request('/works', {}) == {'results': []}
                assert client.request_count == 7
            assert [request.path for request in proxy.requests] == ['http://provider.invalid/works'] * 3
            assert all(request.headers['Authorization'] == 'Bearer synthetic-key' for request in proxy.requests)
        assert [request.path for request in origin.requests] == ['/target'] * 4
        assert all('Authorization' not in request.headers for request in origin.requests)
    assert clock.waits == [3, 3, 3]


def test_provider_deadline_transport_sends_buffered_pubmed_form(monkeypatch):
    from urllib.parse import parse_qs
    from allfold.providers import integrated

    isolate_proxy_environment(monkeypatch)
    with http_server(lambda _: (200, {}, b'{"esearchresult":{}}')) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'pubmed', origin.url)
        with DiscoveryClient('pubmed', api_key='synthetic-key', interval=0) as client:
            assert client.request('/esearch.fcgi', {'term': 'fixture'}) == {'esearchresult': {}}
        [request] = origin.requests
        assert (request.method, request.path) == ('POST', '/esearch.fcgi')
        assert parse_qs(request.body.decode()) == {'api_key': ['synthetic-key'], 'term': ['fixture']}


@pytest.mark.parametrize('revoked', ['cancel', 'authority'])
def test_cooldown_wait_rechecks_cancellation_and_request_authority(revoked):
    from allfold.persistence.safe_write import ContentChangedError
    clock, cooldowns, cancel, calls = Clock(), ProviderCooldowns(), Event(), []
    authority = True

    def revoke(seconds):
        nonlocal authority
        if revoked == 'cancel':
            cancel.set()
        else:
            authority = False

    def guard():
        if not authority:
            raise ContentChangedError('Workspace changed')

    def respond(request):
        calls.append(clock.now)
        return httpx.Response(503, headers={'Retry-After': '12'})

    options = dict(transport=httpx.MockTransport(respond), interval=0, cooldowns=cooldowns,
                   monotonic=clock.monotonic)
    with DiscoveryClient('crossref', sleep=revoke, cancel_event=cancel, **options) as client:
        client.request_guard = guard
        with pytest.raises(DiscoveryError if revoked == 'cancel' else ContentChangedError):
            client.request('/works/10.5555/known', {})
        assert client.request_count == 1
    with DiscoveryClient('crossref', deadline=clock.now + 1, **options) as waiting:
        with pytest.raises(ProviderBudgetExceeded):
            waiting.request('/works/10.5555/known', {})
        assert waiting.request_count == 0
    assert calls == [100]


def test_api_challenge_stops_later_requests_in_the_same_run_client():
    calls = []
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(202, headers={'content-type': 'text/html'},
            text='<html>Making sure you are not a bot! Protected by Anubis</html>')), interval=0) as client:
        for identifier in ('W1', 'W2'):
            with pytest.raises(DiscoveryError, match='Anubis'):
                client.request('/works/' + identifier, {})
    assert len(calls) == 1


def test_api_default_spacing_is_applied():
    clock = Clock()
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda _:httpx.Response(200, json={})),
                         **clock.options()) as client:
        client.request('/fixture', {})
        client.request('/fixture', {})
    assert clock.waits == pytest.approx([0.35])


@pytest.mark.parametrize('status', [400, 401, 403, 404])
def test_permanent_http_errors_are_not_retried_or_mislabeled(status):
    calls = []
    with DiscoveryClient('openalex', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(status, headers={'content-type': 'text/html'},
                                               text='<html>Request rejected</html>')), interval=0) as client:
        with pytest.raises(ProviderHTTPError) as caught:
            client.request('/works/W123', {})
    assert caught.value.status == status and len(calls) == 1


@pytest.mark.parametrize('header,wait', [(None, 12), ('NaN', 5.5), ('not-a-date', 5.5)])
def test_retry_after_http_date_and_invalid_values_are_bounded(header, wait):
    calls, clock = [], Clock()
    header = header or format_datetime(clock.wall_time() + timedelta(seconds=12), usegmt=True)

    def response(request):
        calls.append(clock.now)
        return httpx.Response(503, headers={'retry-after': header}) if len(calls) == 1 else httpx.Response(200, json={})

    with DiscoveryClient('crossref', transport=httpx.MockTransport(response), interval=0,
                         **clock.options()) as client:
        client.request('/fixture', {})
    assert calls == [100, 100 + wait] and clock.waits == [wait]


def test_app_clients_share_cooldown_with_parallel_lookups_by_origin_and_credential(monkeypatch):
    import asyncio
    from allfold.providers import provider_http
    clock, pacing = Clock(), {}
    isolate_proxy_environment(monkeypatch)
    # Exercise the application-owned default with a synthetic HTTPX transport.
    monkeypatch.setattr(provider_http, '_APPLICATION_COOLDOWNS', ProviderCooldowns())
    calls, statuses, failures = [], [], []
    in_flight = {name: Event() for name in ('late-success', 'late-limit', 'late-short')}
    release = {name: Event() for name in in_flight}
    waiter_entered, wake = Event(), Event()

    def respond(request):
        name = request.url.path[1:]
        calls.append((name, clock.now))
        if name in in_flight:
            in_flight[name].set()
            assert release[name].wait(3)
        if name == 'late-limit':
            return httpx.Response(503, headers={'Retry-After': '15'})
        if name in {'exhausted', 'late-short'}:
            return httpx.Response(429, headers={'Retry-After': '2'})
        return httpx.Response(200, json={'result': 'ok'})

    async def route(request):
        return await asyncio.to_thread(respond, request)

    monkeypatch.setattr(httpx, 'AsyncHTTPTransport', lambda **options: httpx.MockTransport(route))

    def sent_before_gate(name, deadline=None):
        try:
            with DiscoveryClient('openalex', api_key='shared-key', interval=0,
                                 deadline=deadline, pacing_state=pacing, **clock.options()) as client:
                client.request('/' + name, {})
            statuses.append((name, 200))
        except ProviderHTTPError as error:
            statuses.append((name, error.status))
        except Exception as error:
            failures.append(error)

    def paused_wait(seconds):
        if not waiter_entered.is_set():
            waiter_entered.set()
            assert wake.wait(3)
        clock.sleep(seconds)

    def wait_across_both_clients():
        try:
            with OpenAlexClient(api_key='shared-key', pacing_state=pacing, **{**clock.options(), 'sleep': paused_wait}) as client:
                assert client.search_sources('fixture') == {'result': 'ok'}
        except Exception as error:
            failures.append(error)

    senders = [Thread(target=sent_before_gate, args=('late-success',)),
               Thread(target=sent_before_gate, args=('late-limit', clock.now + 10)),
               Thread(target=sent_before_gate, args=('late-short', clock.now + 10))]
    waiter = Thread(target=wait_across_both_clients)
    for worker in senders:
        worker.start()
    try:
        assert all(event.wait(3) for event in in_flight.values())
        with DiscoveryClient('openalex', api_key='shared-key', interval=0, pacing_state=pacing, **clock.options()) as client:
            with pytest.raises(ProviderHTTPError):
                client.request('/exhausted', {})
            assert client.request_count == 3
        waiter.start()
        assert waiter_entered.wait(3)

        # A later success and a canceled waiter cannot clear the existing gate.
        release['late-success'].set()
        senders[0].join(3)
        cancel = Event()
        with DiscoveryClient('openalex', api_key='shared-key', interval=0, cancel_event=cancel,
                **{**clock.options(), 'sleep': lambda seconds: cancel.set()}) as canceled:
            with pytest.raises(DiscoveryError, match='cancelled'):
                canceled.request('/canceled', {})
            assert canceled.request_count == 0
        with DiscoveryClient('openalex', api_key='other-key', interval=0, **clock.options()) as other_key:
            assert other_key.request('/other-key', {}) == {'result': 'ok'}
        with DiscoveryClient('crossref', interval=0, **clock.options()) as other_origin:
            assert other_origin.request('/other-origin', {}) == {'result': 'ok'}

        # An already dispatched response extends the gate before the waiter wakes.
        release['late-limit'].set()
        senders[1].join(3)
        release['late-short'].set()
        senders[2].join(3)
        wake.set()
        waiter.join(3)
        assert not waiter.is_alive()
    finally:
        for event in (*release.values(), wake):
            event.set()
        for worker in (*senders, waiter):
            if worker.ident is not None:
                worker.join(3)
    assert not failures
    assert sorted(statuses) == [('late-limit', 503), ('late-short', 429), ('late-success', 200)]
    assert [time for name, time in calls if name == 'exhausted'] == [100, 102, 104]
    assert ('other-key', 104) in calls and ('other-origin', 104) in calls
    assert [time for name, time in calls if name == 'sources'] == [119]


def test_success_status_with_generic_html_is_invalid_metadata_not_an_empty_result():
    calls = []
    with DiscoveryClient('crossref', transport=httpx.MockTransport(lambda request:
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
