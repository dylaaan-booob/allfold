"""Independent attempt clients use real isolated loopback HTTP and owned threads."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import time

import pytest

from allfold.application.task_clients import IndependentClientFactory, new_provider_pacing
from allfold.providers.integrated import Cancelled
from allfold.providers import integrated
from http_test_helpers import http_server, isolate_proxy_environment


def test_declared_provider_context_does_not_read_unrelated_credentials(tmp_path, monkeypatch):
    isolate_proxy_environment(monkeypatch)
    config = tmp_path / 'config.yaml'
    # An unrelated corrupt key must not prevent a public Crossref-only branch.
    config.with_suffix('.pubmed-secrets.json').write_text('invalid unrelated key store')
    with http_server(lambda _: (200, {}, b'{"ok": true}')) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', origin.url)
        factory = IndependentClientFactory(config)
        try:
            with factory.open(cancel_event=Event(), request_guard=lambda: None,
                              deadline=time.monotonic() + 5, providers=('crossref',)) as attempt:
                assert attempt.provider('crossref').request('/public', {}) == {'ok': True}
                with pytest.raises(ValueError, match='declared'):
                    attempt.provider('pubmed')
        finally:
            factory.close()
        assert [request.path for request in origin.requests] == ['/public']


def test_attempts_have_fresh_clients_cache_and_cancellation_and_close_owned_transport(tmp_path, monkeypatch):
    isolate_proxy_environment(monkeypatch)
    first_cancel, second_cancel = Event(), Event()
    with http_server(lambda _: (200, {}, b'{"ok": true}')) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', origin.url)
        factory = IndependentClientFactory(tmp_path / 'config.yaml')
        with factory.open(cancel_event=first_cancel, request_guard=lambda: None,
                          deadline=time.monotonic() + 5) as first:
            first_client = first.provider('crossref')
            assert first_client.request('/first', {}) == {'ok': True}
            first.request_cache['only-first'] = 'cached'
            with factory.open(cancel_event=second_cancel, request_guard=lambda: None,
                              deadline=time.monotonic() + 5) as second:
                second_client = second.provider('crossref')
                assert second.request_cache == {}
                assert second_client is not first_client
                first_cancel.set()
                with pytest.raises(Cancelled):
                    first_client.request('/cancelled', {})
                assert second_client.request('/second', {}) == {'ok': True}
            with pytest.raises(RuntimeError, match='closed'):
                second_client.request('/after-close', {})
        with pytest.raises(RuntimeError, match='closed'):
            first.provider('crossref')
        factory.close()
        with pytest.raises(RuntimeError, match='closed'):
            with factory.open(cancel_event=Event(), request_guard=lambda: None,
                              deadline=time.monotonic() + 5):
                pytest.fail('closed factory admitted work')
        assert [request.path for request in origin.requests] == ['/first', '/second']


def test_pacing_survives_run_and_manual_preprint_clients_and_new_attempts(tmp_path, monkeypatch):
    import httpx
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.preprint_lookup import PreprintLookup
    from integrated_run_helpers import run_integrated
    from allfold.application.provider_lookup import provider_client
    from library_application_helpers import create_paper, FORMAL
    from test_provider_resilience import Clock

    config, _, paper = create_paper(tmp_path)
    config.write_text(config.read_text() + 'enabled_providers: [pubmed]\n')
    clock, calls, pacing = Clock(), [], new_provider_pacing()
    for provider in integrated.PROVIDERS:
        monkeypatch.setitem(integrated.BASE_URLS, provider, 'https://shared.example')

    def respond(request):
        calls.append((request.url.path, clock.now))
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'count': '0', 'idlist': []}})
        if request.url.path.startswith('/pubs/'):
            return httpx.Response(200, json={'messages': [{'status': f'Preprint for DOI {FORMAL} not found'}], 'collection': []})
        assert request.url.path == '/factory'
        return httpx.Response(200, json={'ok': True})

    def clients(provider, **kwargs):
        return provider_client(provider, interval=1, transport=httpx.MockTransport(respond),
                                 **clock.options(), **kwargs)

    options = dict(client_factory=clients, lookup_factory=clients, pacing_state=pacing)
    assert run_integrated(config, **options).facts.created_papers == 0
    lookup = PreprintLookup(config, BrowserTaskLock(), client_factory=clients, pacing_state=pacing)
    lookup.start(paper.id)
    lookup.join()
    assert lookup.state(paper.id)['phase'] == 'NoMatch'
    factory = IndependentClientFactory(config, pacing_state=pacing, client_factory=clients)
    with factory.open(cancel_event=Event(), request_guard=lambda: None, deadline=clock.now + 10) as attempt:
        assert attempt.provider('crossref').request('/factory', {}) == {'ok': True}
    factory.close()
    assert run_integrated(config, **options).facts.created_papers == 0
    assert [now for _, now in calls] == [100, 101, 102, 103, 104]
    lookup.shutdown(); lookup.join()


def test_factory_shutdown_waits_until_in_flight_response_and_worker_clients_settle(tmp_path, monkeypatch):
    isolate_proxy_environment(monkeypatch)
    entered, finish, worker_closed = Event(), Event(), Event()

    def response(_):
        entered.set()
        assert finish.wait(3)
        return 200, {}, b'{"ok": true}'

    with http_server(response) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', origin.url)
        factory = IndependentClientFactory(tmp_path / 'config.yaml')

        def work():
            with factory.open(cancel_event=Event(), request_guard=lambda: None,
                              deadline=time.monotonic() + 5) as attempt:
                result = attempt.provider('crossref').request('/slow', {})
            worker_closed.set()
            return result

        with ThreadPoolExecutor(max_workers=2) as pool:
            running = pool.submit(work)
            assert entered.wait(2)
            closing = pool.submit(factory.close)
            try:
                with pytest.raises(TimeoutError):
                    closing.result(timeout=.05)
                assert not worker_closed.is_set()
            finally:
                finish.set()
            assert running.result(timeout=2) == {'ok': True}
            closing.result(timeout=2)
        assert worker_closed.is_set()
        assert origin.closed.wait(2)


def test_captured_guard_and_deadline_still_apply_to_lazy_clients(tmp_path, monkeypatch):
    from allfold.providers.provider_http import ProviderBudgetExceeded
    from allfold.persistence.safe_write import ContentChangedError

    isolate_proxy_environment(monkeypatch)
    revoked = Event()

    def guard():
        if revoked.is_set():
            raise ContentChangedError('Captured attempt authority revoked')

    with http_server(lambda _: (200, {}, b'{"ok": true}')) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', origin.url)
        factory = IndependentClientFactory(tmp_path / 'config.yaml')
        with factory.open(cancel_event=Event(), request_guard=guard,
                          deadline=time.monotonic() + 5) as attempt:
            client = attempt.provider('crossref')
            revoked.set()
            with pytest.raises(ContentChangedError):
                client.request('/revoked', {})
            with pytest.raises(ContentChangedError):
                attempt.provider('crossref')
        with factory.open(cancel_event=Event(), request_guard=lambda: None,
                          deadline=time.monotonic() - 1) as expired:
            with pytest.raises(ProviderBudgetExceeded):
                expired.provider('crossref').request('/expired', {})
        factory.close()
        assert origin.requests == []
