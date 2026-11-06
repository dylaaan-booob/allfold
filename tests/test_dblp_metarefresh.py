import html
import json
from urllib.parse import urlencode
from threading import Event

import httpx
import pytest

from allfold.providers.integrated import DiscoveryClient, DiscoveryError

VERIFY = '/.within.website/x/cmd/anubis/api/pass-challenge'


def challenge(request, *, meta=False, algorithm='metarefresh', version='v1.27.0',
              delay=2, destination=None):
    target = destination or VERIFY + '?' + urlencode(dict(id='fixture-id', challenge='fixture-data', redir=str(request.url)))
    refresh = f'{delay}; url={target}'
    payload = {'rules': {'algorithm': algorithm, 'difficulty': 1},
               'challenge': {'id': 'fixture-id', 'randomData': 'fixture-data'}}
    body = '<html>Anubis' + ''.join(f'<script id="{key}" type="application/json">{json.dumps(value)}</script>'
        for key, value in [('anubis_version', version), ('anubis_challenge', payload)])
    if meta:
        body += f'<meta http-equiv="refresh" content="{html.escape(refresh, quote=True)}">'
    return httpx.Response(202, text=body + '</html>', headers={
        'content-type': 'text/html', 'set-cookie': 'verify=fixture; Path=/; Secure',
        **({} if meta else {'refresh': refresh})})


@pytest.mark.parametrize('meta', [False, True])
def test_dblp_metarefresh_waits_reuses_cookies_and_returns_to_exact_query(meta):
    calls, waits = [], []
    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return challenge(request, meta=meta)
        if request.url.path == VERIFY:
            assert 'verify=fixture' in request.headers['cookie']
            assert waits == [2]
            return httpx.Response(302, headers={'location': str(calls[0].url), 'set-cookie': 'auth=fixture; Path=/; Secure'})
        assert 'auth=fixture' in request.headers['cookie']
        return httpx.Response(200, json={'result': {'hits': {'@total': '0', '@computed': '0', '@first': '0'}}})
    with DiscoveryClient('dblp', transport=httpx.MockTransport(handler), interval=0, sleep=waits.append) as client:
        data = client.request('/search/publ/api', {'q': 'streamid:conf/nips: learning$', 'format': 'json'})
        client.request('/search/publ/api', {'q': 'streamid:conf/icml: learning$', 'format': 'json'})
    assert data['result']['hits']['@total'] == '0'
    assert calls[0].url == calls[2].url
    assert len(calls) == 4 and waits == [2]


@pytest.mark.parametrize('change', [
    {'algorithm': 'fast'}, {'version': 'v9.0.0'}, {'delay': 0}, {'delay': 61},
    {'destination': 'https://other.example/'}, {'destination': 'http://dblp.org/'},
    {'destination': VERIFY + '?id=wrong&challenge=fixture-data&redir=https://dblp.org/'},
])
def test_unsupported_or_unsafe_challenge_stops_run_client(change):
    calls = []
    with DiscoveryClient('dblp', transport=httpx.MockTransport(lambda r: calls.append(r) or challenge(r, **change)), interval=0) as client:
        for _ in range(2):
            with pytest.raises(DiscoveryError, match='access limited'):
                client.request('/search/publ/api', {'format': 'json'})
    assert len(calls) == 1


@pytest.mark.parametrize('result', ['challenge', 'html', 'invalid_json', 'invalid_hits', 'external_redirect', 'missing_location'])
def test_verification_redirect_is_not_proof_of_recovery(result):
    from datetime import date
    from allfold.keywords import parse_keyword_expression
    from allfold.providers.integrated import SourceScope
    calls = []
    def handler(request):
        calls.append(request)
        if len(calls) == 1 or result == 'challenge' and len(calls) == 3:
            return challenge(request)
        if request.url.path == VERIFY:
            if result == 'missing_location':
                return httpx.Response(302)
            return httpx.Response(302, headers={'location': 'https://other.example/' if result == 'external_redirect' else str(calls[0].url)})
        if result == 'invalid_hits':
            return httpx.Response(200, json={'result': {}})
        return httpx.Response(200, text='<html>Not metadata</html>' if result == 'html' else 'broken')
    with DiscoveryClient('dblp', transport=httpx.MockTransport(handler), interval=0, sleep=lambda _: None) as client:
        r = client.discover(SourceScope('conference', 'NeurIPS', stream='streams/conf/nips'), parse_keyword_expression('learning'), date(2025,1,1), date(2025,12,31))
    assert r.status == 'failed' and not r.records
    assert len(calls) <= 3 and all(c.url.host == 'dblp.org' for c in calls)


def test_cancellation_during_metarefresh_wait_never_dispatches_verification():
    cancel, calls = Event(), []
    with DiscoveryClient('dblp', transport=httpx.MockTransport(lambda r: calls.append(r) or challenge(r)),
                         interval=0, sleep=lambda _: cancel.set(), cancel_event=cancel) as client:
        with pytest.raises(DiscoveryError, match='cancelled'):
            client.request('/search/publ/api', {'format': 'json'})
    assert len(calls) == 1


def test_only_dblp_may_recover_and_a_client_never_repeats_verification():
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path == VERIFY:
            return httpx.Response(302, headers={'location': str(calls[0].url)})
        if len(calls) == 3:
            return httpx.Response(200, json={'result': {}})
        return challenge(request)
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(handler), interval=0) as client:
        with pytest.raises(DiscoveryError, match='access limited'):
            client.request('/search', {})
    assert len(calls) == 1
    calls.clear()
    with DiscoveryClient('dblp', transport=httpx.MockTransport(handler), interval=0, sleep=lambda _: None) as client:
        client.request('/search/publ/api', {'f': 0})
        for offset in (2, 4):
            with pytest.raises(DiscoveryError, match='access limited'):
                client.request('/search/publ/api', {'f': offset})
    assert len(calls) == 4
