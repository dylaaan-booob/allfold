"""Public multiplexed Bridge and solver queue regressions; no personal services."""
import asyncio
import threading
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from allfold.web.electron_bridge import ElectronBridge


def application(bridge):
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    return app


def solve_message(page, target):
    return {'type': 'solve_cloudflare', 'page_id': page, 'challenge_id': target, 'target_id': target}


def test_parallel_requests_receive_results_and_cancel_only_their_owner():
    bridge = ElectronBridge('secret', 'testserver')
    progress = [[], []]
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'})
        assert socket.receive_json()['type'] == 'ready'
        futures, requests = [], []
        for index in range(2):
            futures.append(bridge.execute('prepare_service', {'workflow_id': 'login', 'task_id': str(index)}, progress[index].append))
            requests.append(socket.receive_json())
        assert bridge.cancel_task('login', '0').result(2)
        assert socket.receive_json() == {'type': 'cancel', 'id': requests[0]['id'], 'action': 'prepare_service'}
        for index in (1, 0):
            socket.send_json({'type': 'progress', 'id': requests[index]['id'], 'action': 'prepare_service',
                              'data': {'message': str(index)}})
            socket.send_json({'type': 'result', 'id': requests[index]['id'], 'action': 'prepare_service',
                              'data': {'outcome': 'Opened', 'page_id': index}})
            assert futures[index].result(2)['page_id'] == index
            if index == 1:
                assert not futures[0].done()
        assert progress == [[{'message': '0'}], [{'message': '1'}]]


def test_paper_terminal_delivery_does_not_repeat_blocking_native_diagnostics():
    entered, release = threading.Event(), threading.Event()
    class Sink:
        level = 'info'
        def native_status(self, *_):
            pass
        def event(self, name, details):
            if name == 'task_finished':
                entered.set()
                assert release.wait(3)
    bridge = ElectronBridge('secret', 'testserver', diagnostics=Sink())
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        future = bridge.execute('local_paper_body', {'workflow_id': 'local-body', 'task_id': 'opened'})
        request = socket.receive_json()
        try:
            socket.send_json({'type': 'result', 'id': request['id'], 'action': request['action'],
                'data': {'outcome': 'opened', 'resource_closed': True}})
            assert future.result(.5)['outcome'] == 'opened'
            assert not entered.is_set()
        finally:
            release.set()


def test_normal_shutdown_keeps_captured_resource_cleanup_transport_open():
    from allfold.application.browser_runtime import ElectronDisconnected
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'})
        assert socket.receive_json()['type'] == 'ready'
        bridge.closing = True
        with pytest.raises(ElectronDisconnected):
            bridge.execute('prepare_service', {'workflow_id': 'old', 'task_id': 'old'}).result(2)
        cleanup = bridge.execute('release_workflow_pages', {'workflow_id': 'old', 'task_id': 'old'})
        with pytest.raises(TimeoutError):
            cleanup.result(.03)
        request = socket.receive_json()
        assert request['action'] == 'release_workflow_pages'
        assert not cleanup.done()
        socket.send_json({'type': 'result', 'id': request['id'], 'action': request['action'],
                          'data': {'released': True}})
        assert cleanup.result(2) == {'released': True}


def test_user_tab_solver_is_independent_and_cancel_waits_for_actual_cleanup(monkeypatch):
    started, stopped, release = (threading.Event() for _ in range(3))
    calls = []

    async def solve(_endpoint, stop, *, target_id, progress):
        calls.append(target_id)
        if target_id == 'a' * 32:
            started.set()
            assert await asyncio.to_thread(stop.wait, 3)
            stopped.set()
            assert await asyncio.to_thread(release.wait, 3)
        await progress({'outcome': 'clicked', 'reason': 'checkbox_clicked'})
        return {'outcome': 'not_executed', 'reason': 'canceled'}

    monkeypatch.setattr('allfold.web.electron_bridge.solve_cloudflare', solve)
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        a, b = solve_message(1, 'a' * 32), solve_message(2, 'b' * 32)
        try:
            socket.send_json(a)
            assert started.wait(2)
            socket.send_json(b)
            assert socket.receive_json() == {**b, 'type': 'cloudflare_progress',
                'data': {'outcome': 'clicked', 'reason': 'checkbox_clicked'}}
            assert socket.receive_json() == {**b, 'type': 'solve_cloudflare_result',
                'data': {'outcome': 'not_executed', 'reason': 'canceled'}}
            socket.send_json({**a, 'type': 'cancel_cloudflare', 'page_id': 2})
            assert not stopped.wait(.05)
            socket.send_json({**a, 'type': 'cancel_cloudflare'})
            assert stopped.wait(2)
            future = bridge.execute('prepare_service', {})
            request = socket.receive_json()
            socket.send_json({'type': 'result', 'id': request['id'], 'action': request['action'],
                              'data': {'outcome': 'Opened'}})
            assert future.result(2)['outcome'] == 'Opened'
            release.set()
            assert socket.receive_json() == {**a, 'type': 'solve_cloudflare_result',
                'data': {'outcome': 'not_executed', 'reason': 'canceled'}}
            assert calls == ['a' * 32, 'b' * 32]
        finally:
            release.set()


@pytest.mark.parametrize('shutdown', [False, True])
def test_disconnect_and_shutdown_stop_and_join_all_tab_workers(monkeypatch, shutdown):
    started = [threading.Event(), threading.Event()]
    stopped = [threading.Event(), threading.Event()]
    exited = [threading.Event(), threading.Event()]
    release = threading.Event()

    async def solve(_endpoint, stop, *, target_id, progress):
        index = int(target_id[0])
        started[index].set()
        assert await asyncio.to_thread(stop.wait, 3); stopped[index].set()
        assert await asyncio.to_thread(release.wait, 3); exited[index].set()
        return {'outcome': 'not_executed', 'reason': 'canceled'}

    monkeypatch.setattr('allfold.web.electron_bridge.solve_cloudflare', solve)
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        for index in range(2):
            socket.send_json(solve_message(index + 1, str(index) * 32))
            assert started[index].wait(2)
        try:
            if shutdown:
                socket.send_json({'type': 'shutdown'})
            else:
                socket.close()
            assert all(event.wait(2) for event in stopped)
            assert not any(event.is_set() for event in exited)
        finally:
            release.set()
        if shutdown:
            replies = [socket.receive_json() for _ in range(3)]
            assert replies[-1] == {'type': 'shutdown_ready'}
            assert {item['page_id'] for item in replies[:-1]} == {1, 2}
        assert all(event.wait(2) for event in exited)


@pytest.mark.parametrize('tamper', [lambda value: value.update(page_id=0),
    lambda value: value.update(target_id='wrong'), lambda value: value.update(challenge_id='old'),
    lambda value: value.update(id='fake-business', action='prepare_service')])
def test_solver_rejects_invalid_tab_envelopes(monkeypatch, tamper):
    calls = []
    monkeypatch.setattr('allfold.web.electron_bridge.solve_cloudflare', lambda *a, **kw: calls.append(kw))
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        message = solve_message(1, 'a' * 32); tamper(message)
        socket.send_json(message)
        from fastapi import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert calls == []


def test_access_close_events_and_shared_limits_use_the_authenticated_bridge():
    bridge = ElectronBridge('secret', 'testserver')
    closed = []
    bridge.access_pages_closed = closed.extend
    bridge.page_limits = lambda: {'global_limit': 16, 'service_limit': 4}
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'})
        assert socket.receive_json()['page_limits'] == {'global_limit': 16, 'service_limit': 4}
        socket.send_json({'type': 'access_pages_closed', 'page_ids': [17, 29]})
        bridge.page_limits = lambda: {'global_limit': 8, 'service_limit': 3}
        bridge.refresh_page_limits().result(2)
        assert socket.receive_json() == {'type': 'page_limits', 'page_limits': {'global_limit': 8, 'service_limit': 3}}
        request = bridge.execute('invalidate_access', {'scope_id': 'a' * 64,
            'preparation_keys': {'publisher': 'b' * 64}, 'authentication_key': None})
        sent = socket.receive_json()
        socket.send_json({**{key: sent[key] for key in ('id', 'action')}, 'type': 'result', 'data': {'ok': True}})
        assert request.result(2) == {'ok': True} and closed == [17, 29]


@pytest.mark.parametrize('action', ['extract_paper_metadata', 'extract_paper_pdf_clues'])
def test_internal_extraction_contract_and_scoped_recovery_preserve_empty_success(action):
    bridge = ElectronBridge('secret', 'testserver')
    verified = threading.Event()
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        for invalid in ({'wantAbstract': 'false', 'deadline_ms': int(time.time() * 1000) + 5000},
                        {'wantAbstract': False, 'deadline_ms': True},
                        {'wantAbstract': False, 'reader_access_only': True, 'deadline_ms': int(time.time() * 1000) + 5000}):
            with pytest.raises(ValueError, match='extraction'):
                bridge.execute('extract_paper_metadata', invalid).result(2)
        with pytest.raises(ValueError, match='extraction'):
            bridge.execute('extract_paper_pdf_clues', {'reader_access_only': 'true', 'deadline_ms': int(time.time() * 1000) + 5000}).result(2)
        parameters = {'wantAbstract': False} if action == 'extract_paper_metadata' else {}
        future = bridge.execute(action, parameters | {
            'workflow_id': 'collection', 'task_id': 'captured',
            'deadline_ms': int(time.time() * 1000) + 5000,
        }, verify_recovery=verified.set)
        request = socket.receive_json()
        assert request['action'] == action
        assert request['data'].get('wantAbstract') is (False if action == 'extract_paper_metadata' else None)
        socket.send_json({key: request[key] for key in ('id', 'action')} | {
            'type': 'verify_recovery_authority', 'check_id': 'a' * 32, 'data': {}})
        response = socket.receive_json()
        assert response['data'] == {'allowed': True}
        assert verified.is_set()
        socket.send_json({key: request[key] for key in ('id', 'action')} | {
            'type': 'result', 'data': {'outcome': 'retrieved',
                                     'metadata': {'dates': [], 'abstract': None},
                                     'extraction_diagnostics': []}})
        assert future.result(2)['metadata'] == {'dates': [], 'abstract': None}


def test_unauthenticated_connection_cannot_report_solver_drain():
    drained = []
    bridge = ElectronBridge('secret', 'testserver')
    bridge.solver_drained = lambda: drained.append(True)
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'wrong'})
        from fastapi import WebSocketDisconnect
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert drained == []
