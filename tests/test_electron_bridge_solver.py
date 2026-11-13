"""Public multiplexed Bridge and solver queue regressions; no personal services."""
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


def solve_message(request, target, *, deadline=None):
    return {**{key: request[key] for key in ('id', 'action')}, 'type': 'solve_cloudflare',
            'challenge_id': target, 'data': {'url': 'https://fixture.example/challenge',
            'target_id': target, 'deadline_ms': deadline or int(time.time() * 1000) + 5000}}


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


def test_solver_slot_waits_for_actual_cleanup_and_skips_expired_or_canceled_queue(monkeypatch):
    started, stopped, release = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def solve(_endpoint, _url, stop, *, target_id):
        calls.append(target_id)
        if target_id == 'a' * 32:
            started.set()
            assert stop.wait(3)
            stopped.set()
            assert release.wait(3)
        return {'outcome': 'clicked', 'reason': 'checkbox_clicked'}

    monkeypatch.setattr('allfold.web.electron_bridge.solve_cloudflare', solve)
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        requests, futures = [], []
        try:
            for index, target in enumerate('abcd'):
                futures.append(bridge.execute('prepare_service', {'workflow_id': 'login', 'task_id': target}))
                request = socket.receive_json(); requests.append(request)
                socket.send_json(solve_message(request, target * 32,
                    deadline=int(time.time() * 1000) - 1 if target == 'b' else None))
                assert started.wait(2)
            socket.send_json({**{key: requests[2][key] for key in ('id', 'action')},
                              'type': 'cancel_cloudflare', 'challenge_id': 'c' * 32})
            assert bridge.cancel_task('login', 'a').result(2)
            assert socket.receive_json()['id'] == requests[0]['id']
            assert stopped.wait(2)
            # A third operation can still settle while the first worker is cleaning up.
            other = bridge.execute('visit_manual_service', {})
            request = socket.receive_json()
            socket.send_json({'type': 'result', 'id': request['id'], 'action': request['action'], 'data': {'outcome': 'Opened'}})
            assert other.result(2) == {'outcome': 'Opened'}
            assert calls == ['a' * 32]
            release.set()
            reply = socket.receive_json()
            assert reply == {**{key: requests[3][key] for key in ('id', 'action')}, 'type': 'solve_cloudflare_result',
                             'challenge_id': 'd' * 32, 'data': {'outcome': 'clicked', 'reason': 'checkbox_clicked'}}
            assert calls == ['a' * 32, 'd' * 32]
            for future, request in zip(futures, requests):
                socket.send_json({'type': 'result', 'id': request['id'], 'action': request['action'], 'data': {'outcome': 'Opened'}})
                assert future.result(2) == {'outcome': 'Opened'}
        finally:
            release.set()


@pytest.mark.parametrize('shutdown', [False, True])
def test_disconnect_and_shutdown_stop_queue_and_join_workers(monkeypatch, shutdown):
    started, stopped, release, exited = (threading.Event() for _ in range(4))
    calls = []

    def solve(_endpoint, _url, stop, *, target_id):
        calls.append(target_id); started.set()
        assert stop.wait(3); stopped.set()
        assert release.wait(3); exited.set()
        return {'outcome': 'clicked', 'reason': 'checkbox_clicked'}

    monkeypatch.setattr('allfold.web.electron_bridge.solve_cloudflare', solve)
    bridge = ElectronBridge('secret', 'testserver')
    with TestClient(application(bridge)) as client, client.websocket_connect('/ws') as socket:
        socket.send_json({'token': 'secret'}); socket.receive_json()
        for target in 'ab':
            bridge.execute('prepare_service', {'task_id': target})
            request = socket.receive_json()
            socket.send_json(solve_message(request, target * 32))
            assert started.wait(2)
        try:
            if shutdown:
                socket.send_json({'type': 'shutdown'})
            else:
                socket.close()
            assert stopped.wait(2)
            assert not exited.is_set()
            assert calls == ['a' * 32]
        finally:
            release.set()
        if shutdown:
            assert socket.receive_json() == {'type': 'shutdown_ready'}
        assert exited.wait(2)
        assert calls == ['a' * 32]
        client.portal.call(bridge.finish_disconnected)
