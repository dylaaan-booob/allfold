"""Europe PMC transient outages must not masquerade as access challenges or Empty."""
from datetime import date
from threading import Event

import httpx
import pytest

from allfold.keywords import parse_keyword_expression
from allfold.progress import ActivityKind
from allfold.providers.integrated import DiscoveryResult, SourceScope
from allfold.providers.supplemental import SupplementalClient
from test_provider_resilience import Clock


SOURCE = SourceScope('journal', 'Biometrics', issns=('0006-341X',))
QUERY = parse_keyword_expression('statist*')


def page(identifier='42', *, total=1, cursor=None):
    value = {'hitCount': total, 'resultList': {'result': [
        {'source': 'MED', 'id': identifier, 'title': 'Native indexed hit', 'firstPublicationDate': '2026-01-02'}]}}
    if cursor:
        value['nextCursorMark'] = cursor
    return value


def targeted_association(client):
    value = client.lookup_many('pmid', ['42'])['42']
    records = value.records if isinstance(value, Exception) and hasattr(value,'records') else () if isinstance(value,Exception) else value
    problems = (str(value),) if isinstance(value,Exception) else ()
    status = 'cancelled' if client.cancel.is_set() else 'partial' if problems and records else 'failed' if problems else 'complete' if records else 'empty'
    return DiscoveryResult('europe_pmc',SOURCE,status,records,problems)



def test_html_service_unavailable_retries_same_scoped_query_then_recovers():
    calls, clock, events = [], Clock(), []
    def response(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(503, headers={'content-type': 'text/html', 'Retry-After': '7'},
                                  text='<html><h1>503 Service Unavailable</h1></html>')
        return httpx.Response(200, json=page())
    with SupplementalClient('europe_pmc', transport=httpx.MockTransport(response), interval=0,
                         progress_callback=events.append, **clock.options()) as client:
        result = targeted_association(client)
    assert result.status == 'complete' and len(result.records) == 1
    assert len(calls) == 2 and calls[0].url == calls[1].url
    assert clock.waits == [7]
    retry = [event.activity for event in events if event.activity and event.activity.kind is ActivityKind.RETRYING]
    waiting = [event.activity for event in events if event.activity and event.activity.kind is ActivityKind.WAITING]
    assert len(retry) == 1 and '503' in retry[0].label and 'Retry 2/3' in retry[0].detail
    assert len(waiting) == 1 and '503' in waiting[0].detail and '7.00 seconds' in waiting[0].detail


def test_persistent_503_preserves_first_page_and_stops_after_three_attempts():
    calls, clock = [], Clock()
    def response(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(200, json=page(total=2, cursor='next-page'))
        return httpx.Response(503, text='Service Unavailable')
    with SupplementalClient('europe_pmc', transport=httpx.MockTransport(response), interval=0,
                         page_size=1, **clock.options()) as client:
        result = targeted_association(client)
    assert result.status == 'partial' and len(result.records) == 1
    assert len(calls) == 4 and clock.waits == [5.5, 11]
    assert all(request.url.params['cursorMark'] == 'next-page' for request in calls[1:])
    assert any('503' in value and 'unavailable' in value.lower() for value in result.limitations)


def test_cancel_during_service_backoff_stops_next_request():
    calls, cancel = [], Event()
    def response(request):
        calls.append(request)
        return httpx.Response(503)
    def progress(event):
        if event.activity and event.activity.kind is ActivityKind.RETRYING:
            cancel.set()
    with SupplementalClient('europe_pmc', transport=httpx.MockTransport(response), interval=0,
                         cancel_event=cancel, progress_callback=progress) as client:
        result = targeted_association(client)
    assert result.status == 'cancelled' and len(calls) == 1


@pytest.mark.parametrize('status', [200, 202, 503])
def test_actual_html_challenge_is_never_retried(status):
    calls = []
    with SupplementalClient('europe_pmc', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(status, headers={'content-type': 'text/html'},
                                                text='<html>Anubis challenge</html>')), interval=0) as client:
        result = targeted_association(client)
    assert result.status == 'failed' and len(calls) == 1
    assert 'access limited' in result.limitations[0]


@pytest.mark.parametrize('payload', [{'version': '6.9'}, {'hitCount': 0}])
def test_incomplete_200_json_is_failed_instead_of_empty(payload):
    calls = []
    with SupplementalClient('europe_pmc', transport=httpx.MockTransport(lambda request:
        calls.append(request) or httpx.Response(200, json=payload)), interval=0) as client:
        result = targeted_association(client)
    assert result.status == 'failed' and len(calls) == 1
