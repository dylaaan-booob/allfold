from concurrent.futures import Future
from dataclasses import replace
from queue import Queue
import threading

import pytest

from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.coordinators.login import LoginCoordinator, PreparedService
from allfold.application.coordinators.wos_coordinator import WoSCoordinator
from allfold.config import AccessService, load_config
from allfold.persistence.user_state import compare_write_user_state, load_user_state
from allfold.persistence.safe_write import ContentChangedError
from safety_config_helpers import current_mapping_document


def login_fixture(tmp_path, count=7):
    path, _, _, first = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + '\ninstitution:\n  name: Fixture University\n')
    services = (first, AccessService.create('Web of Science'), *(
        AccessService.create(f'Publisher {i}', 'https://publisher.example/') for i in range(count - 2)
    ), AccessService.create('Manual', 'https://publisher.example/', access_method='manual'))
    saved = load_user_state(path)
    compare_write_user_state(path, replace(saved.state, access_services=services), saved.revision)
    return path, services


class Native:
    connected = True

    def __init__(self):
        self.operations = Queue()
        self.cancellations = 0
        self.cancelled_workflows = []
        self.cancelled_tasks = []
        self.authority = {}

    def execute(self, action, data, progress, *, verify_recovery=None):
        result = Future()
        if verify_recovery:
            self.authority[data['task_id']] = verify_recovery
        self.operations.put((action, data, result))
        return result

    def cancel_workflow(self, workflow_id):
        self.cancellations += 1
        self.cancelled_workflows.append(workflow_id)

    def cancel_task(self, workflow_id, task_id):
        self.cancelled_tasks.append((workflow_id, task_id))


def opened(page_id):
    return {'outcome': 'Opened', 'evidence': {'visit_action_observed': True,
        'navigation_observed': True, 'target_page_id': page_id}}


def test_one_login_prepares_all_saved_records_with_five_independent_slots(tmp_path):
    path, services = login_fixture(tmp_path)
    saved = BrowserServiceSnapshot.read(path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    assert len(login.snapshot(saved)['services']) == len(services)
    login.start(path)
    action, entry, ready = native.operations.get(timeout=2)
    assert action == 'login_carsi' and entry['service_id'] is None
    assert native.operations.empty()
    ready.set_result({'outcome': 'Opened', 'portal_page_id': 17})
    initial = [native.operations.get(timeout=2) for _ in range(5)]
    assert native.operations.empty()
    assert all(action == 'prepare_service' and data['portal_page_id'] == 17
               and data['workflow_id'] == entry['workflow_id'] for action, data, _ in initial)
    ids = {data['task_id'] for _, data, _ in initial}
    assert len(ids) == 5
    initial[0][2].set_result({'diagnostic': {'stage': 'preparation', 'code': 'timeout'}})
    next_operation = native.operations.get(timeout=2)
    assert next_operation[1]['task_id'] not in ids
    initial[1][2].set_result(opened(100))
    last_operation = native.operations.get(timeout=2)
    remaining = [*initial[2:], next_operation, last_operation]
    for page, (_, _, result) in enumerate(remaining, 101):
        result.set_result(opened(page))
    login.join()

    rows = {row['id']: row['preparation'] for row in login.snapshot(saved)['services']}
    assert set(rows) == {service.id for service in services}
    assert rows[services[0].id].status == 'Failed'
    assert login.prepared_page(saved, services[1].id) == 100
    assert rows[services[-1].id].reason == 'manual_action_required'
    assert all(rows[s.id].status == 'Opened' for s in services[1:-1])
    assert lock.owner is None

    login.start(path, manual_service_id=services[-1].id)
    action, data, result = native.operations.get(timeout=2)
    assert action == 'visit_manual_service' and data['access_url'] == services[-1].access_url
    result.set_result(opened(199))
    login.join()
    assert login.prepared_page(saved, services[-1].id) == 199
    assert login.prepared_page(saved, services[1].id) == 100


def test_login_cancel_drains_active_operations_and_preserves_observed_open(tmp_path):
    path, services = login_fixture(tmp_path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    workflow_id = login.start(path)['workflow_id']
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result({'outcome': 'Opened', 'portal_page_id': 17})
    pending = [native.operations.get(timeout=2)[2] for _ in range(5)]
    assert login.cancel(workflow_id)
    assert lock.owner is not None and native.cancelled_workflows == [workflow_id]
    pending[0].set_result(opened(29))
    for result in pending[1:]:
        result.set_result({})
    login.join()
    state = login.snapshot(BrowserServiceSnapshot.read(path))
    assert state['phase'] == 'canceled' and native.operations.empty()
    assert state['services'][0]['preparation'].status == 'Opened'
    assert state['services'][5]['preparation'].status == 'Canceled'
    assert lock.owner is None


def test_prepare_recovery_refuses_a_changed_service_revision(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    login.start(path)
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result({'outcome': 'Opened', 'portal_page_id': 17})
    first, second = [native.operations.get(timeout=2) for _ in range(2)]
    try:
        assert first[0] == second[0] == 'prepare_service'
        verify = native.authority[first[1]['task_id']]
        verify()
        state = load_user_state(path)
        changed = services[0].model_copy(update={'access_url': 'https://changed.example.org/'})
        compare_write_user_state(path, replace(state.state, access_services=(changed, *services[1:])), state.revision)
        with pytest.raises(ContentChangedError):
            verify()
    finally:
        for _, _, result in (first, second):
            result.set_result({'diagnostic': {'stage': 'navigation', 'code': 'document_changed'}})
        login.join()
    assert lock.owner is None


@pytest.mark.parametrize('visit_first', [False, True])
def test_manual_confirmation_marks_entire_finished_login_batch_available(tmp_path, visit_first):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge

    class Bridge(Native, OfflineBridge):
        pass

    path, services = login_fixture(tmp_path, count=3)
    first, wos, publisher, manual = services
    native = Bridge()
    app = create_app(path, electron_bridge=native, diagnostics_root=tmp_path / 'logs')
    saved = BrowserServiceSnapshot.read(path)
    with TestClient(app, base_url='http://localhost') as client:
        csrf = {'csrf_token': app.state.csrf_token}
        started = client.post('/api/login/start', json=csrf).json()
        assert started['confirmation_workflow_id'] is None
        body = {**csrf, 'workflow_id': started['workflow_id']}
        assert client.post('/api/login/confirm', json=body).status_code == 409

        _, _, carsi = native.operations.get(timeout=2)
        carsi.set_result({'outcome': 'Opened', 'portal_page_id': 17})
        attempts = {data['service_id']: result
                    for _, data, result in (native.operations.get(timeout=2) for _ in range(3))}
        attempts[publisher.id].set_result({'diagnostic': {'stage': 'navigation', 'code': 'load_failed'}})
        attempts[wos.id].set_result({'diagnostic': {'stage': 'navigation', 'code': 'load_failed'}})
        attempts[first.id].set_result(opened(100))
        app.state.login.join()
        assert client.get('/api/login/state').json()['confirmation_workflow_id'] == started['workflow_id']
        assert app.state.login.prepared_authority(saved, wos.id) is None
        if visit_first:
            visit = client.post('/api/login/start', json={**csrf, 'service_id': manual.id}).json()
            assert visit['workflow_id'] != started['workflow_id']
            assert visit['confirmation_workflow_id'] is None
            action, _, result = native.operations.get(timeout=2)
            assert action == 'visit_manual_service'
            result.set_result(opened(199))
            app.state.login.join()
            assert client.get('/api/login/state').json()['confirmation_workflow_id'] == started['workflow_id']
        assert client.post('/api/login/confirm', json={**body, 'workflow_id': 'stale'}).status_code == 409
        original = load_user_state(path)
        changed = replace(original.state, access_services=tuple(
            service.model_copy(update={'name': 'Changed Service'}) if service.id == publisher.id else service
            for service in services))
        compare_write_user_state(path, changed, original.revision)
        assert client.post('/api/login/confirm', json=body).status_code == 409
        compare_write_user_state(path, original.state, load_user_state(path).revision)

        owner = app.state.browser_task_lock.acquire('wos', scopes={saved.service_scope(wos.id)})
        assert owner is not None
        assert client.post('/api/login/confirm', json=body).status_code == 409
        app.state.browser_task_lock.release(owner)
        assert client.post('/api/login/confirm', json={**body, 'csrf_token': 'bad'}).status_code == 403

        result = client.post('/api/login/confirm', json=body)
        assert result.status_code == 200
        state = result.json()
        assert state['phase'] == 'confirmed' and state['confirmation_workflow_id'] is None
        assert state['workflow_id'] == started['workflow_id']
        rows = {row['id']: row['preparation'] for row in state['services']}
        assert all(row['status'] == 'Opened' and row['manually_confirmed'] for row in rows.values())
        assert rows[first.id]['page_id'] == 100 and rows[first.id]['reason'] == 'target_opened'
        assert app.state.login.prepared_page(saved, manual.id) == (199 if visit_first else None)
        for service in (wos, publisher):
            assert rows[service.id]['reason'] == 'manual_login_confirmed'
            assert app.state.login.prepared_authority(saved, service.id) is not None
            assert app.state.login.prepared_page(saved, service.id) is None
        assert native.operations.empty()
        assert client.post('/api/login/confirm', json=body).status_code == 409


def test_discover_asks_for_login_without_preparing_or_taking_browser_owner(tmp_path):
    path, _ = login_fixture(tmp_path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    discover = WoSCoordinator(path, login, threading.Lock(), bridge=native, browser_lock=lock)
    with pytest.raises(ValueError, match='Workflows → Login'):
        discover.start()
    assert native.operations.empty() and lock.owner is None


def test_prepared_pages_survive_unrelated_revisions_and_invalidate_only_changed_authority(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    first, wos, manual = services
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    login.start(path)
    _, _, carsi = native.operations.get(timeout=2)
    carsi.set_result({'outcome': 'Opened', 'portal_page_id': 17})
    keys = {}
    for page in (100, 101):
        action, data, future = native.operations.get(timeout=2)
        assert action == 'prepare_service'
        keys[data['service_id']] = data['preparation_key']
        future.set_result(opened(page))
    login.join()
    before = BrowserServiceSnapshot.read(path)
    first_page = login.prepared_page(before, first.id)
    wos_page = login.prepared_page(before, wos.id)
    assert first_page and wos_page and first_page != wos_page

    path.write_text(path.read_text().replace('keyword_expression: causal', 'keyword_expression: Bayesian'))
    saved = load_user_state(path)
    compare_write_user_state(path, replace(saved.state, journals=()), saved.revision)
    current = BrowserServiceSnapshot.read(path)
    assert before.scope != current.scope
    assert login.prepared_authority(current, first.id) == PreparedService(first_page, keys[first.id])
    assert login.prepared_authority(current, wos.id) == PreparedService(wos_page, keys[wos.id])

    saved = load_user_state(path)
    changed = first.model_copy(update={'access_url': 'https://changed.example.org/'})
    compare_write_user_state(path, replace(saved.state, access_services=(changed, wos, manual)), saved.revision)
    current = BrowserServiceSnapshot.read(path)
    assert login.prepared_page(current, first.id) is None
    assert login.prepared_page(current, wos.id) == wos_page

    path.write_text(path.read_text().replace('Fixture University', 'Changed University'))
    current = BrowserServiceSnapshot.read(path)
    assert login.prepared_page(current, wos.id) is None
    assert login.snapshot(current)['carsi'].status == 'Not prepared'


def test_credential_mutation_invalidates_prepared_page_only_after_confirmed_success(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge

    path, services = login_fixture(tmp_path, count=2)
    manual = services[-1]

    class Bridge(OfflineBridge):
        connected = True
        updated = False

        def execute(self, action, data, progress=None, *, verify_recovery=None):
            future = Future()
            if action == 'visit_manual_service':
                future.set_result(opened(17))
            else:
                assert action == 'cas_credentials'
                future.set_result({'ok': self.updated})
            return future

    bridge = Bridge()
    app = create_app(path, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        csrf = app.state.csrf_token
        login = client.post('/api/login/start', json={'csrf_token': csrf, 'service_id': manual.id})
        assert login.status_code == 200
        app.state.login.join()
        saved = BrowserServiceSnapshot.read(path)
        assert app.state.login.prepared_page(saved, manual.id) == 17
        body = {'csrf_token': csrf, 'operation': 'clear', 'expected_revision': 'test',
                'username': '', 'password': ''}
        assert client.post('/api/ui-next/settings/credentials', json=body).json()['ok'] is False
        assert app.state.login.prepared_page(saved, manual.id) == 17
        bridge.updated = True
        assert client.post('/api/ui-next/settings/credentials', json=body).json()['ok'] is True
        assert app.state.login.prepared_page(saved, manual.id) is None


def test_login_and_cover_share_session_and_cancellation_keeps_other_owner_active(tmp_path):
    from allfold.application.coordinators.journal_covers import JournalCoverSearch
    path, services = login_fixture(tmp_path, count=2)
    saved = BrowserServiceSnapshot.read(path)
    config = load_config(path)
    native, lock = Native(), BrowserTaskLock()
    login, covers = LoginCoordinator(native, lock), JournalCoverSearch(native, lock)
    workflow = login.start(path, manual_service_id=services[-1].id)['workflow_id']
    visit = native.operations.get(timeout=2)
    cover = covers.start(config.venue_whitelist, saved.journals, saved.journals[0].key, config_path=path)
    search = native.operations.get(timeout=2)
    try:
        assert len(lock.owners) == 2
        with pytest.raises(ValueError, match='already active'):
            login.start(path, manual_service_id=services[-1].id)
        with pytest.raises(ValueError, match='busy'):
            covers.start(config.venue_whitelist, saved.journals, saved.journals[0].key, config_path=path)
        assert not login.cancel('old')
        assert covers.cancel(cover['request_id'])
        assert native.cancelled_tasks == [(cover['request_id'], cover['request_id'])]
        assert not native.cancelled_workflows and login.snapshot(saved)['workflow_id'] == workflow
    finally:
        search[2].set_result({})
        covers.join()
        visit[2].set_result(opened(99))
        login.join()
    assert covers.state()['phase'] == 'Cancelled'
    assert login.prepared_page(saved, services[-1].id) == 99 and not lock.owners


def test_closed_prepared_page_invalidates_only_its_exact_context(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    manual = services[-1]
    saved = BrowserServiceSnapshot.read(path)
    for page in (17, 29):
        login.start(path, manual_service_id=manual.id)
        _, _, pending = native.operations.get(timeout=2)
        pending.set_result(opened(page))
        login.join()
    login.invalidate_pages([17])
    assert login.prepared_page(saved, manual.id) == 29
    login.invalidate_pages([29])
    assert login.prepared_authority(saved, manual.id) is None


def test_page_closed_before_login_result_cannot_be_accepted_as_prepared(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    login.start(path, manual_service_id=services[-1].id)
    _, _, pending = native.operations.get(timeout=2)
    login.invalidate_pages([17])
    pending.set_result(opened(17))
    login.join()
    assert login.prepared_authority(BrowserServiceSnapshot.read(path), services[-1].id) is None


def test_closed_settled_page_keeps_login_batch_and_admission_until_other_native_result(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    path.write_text(path.read_text() + '\nworkflow:\n  prepare_service_concurrency: 1\n')
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    saved = BrowserServiceSnapshot.read(path)
    login.start(path)
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result({'outcome': 'Opened', 'portal_page_id': 17})
    first = native.operations.get(timeout=2)
    first[2].set_result(opened(100))
    # The next dispatch is admitted only after the first result was accepted.
    second = native.operations.get(timeout=2)
    try:
        assert login.prepared_page(saved, first[1]['service_id']) == 100
        login.invalidate_pages([100])
        assert login.prepared_authority(saved, first[1]['service_id']) is None
        assert lock.owners and login.running
    finally:
        second[2].set_result(opened(101))
        login.join()
    rows = {row['id']: row['preparation'] for row in login.snapshot(saved)['services']}
    assert rows[first[1]['service_id']].status == 'Needs attention'
    assert rows[first[1]['service_id']].page_id is None
    assert login.prepared_page(saved, second[1]['service_id']) == 101
    assert not lock.owners


@pytest.mark.parametrize('manual', [False, True])
def test_terminal_failed_login_drops_the_temporary_progress_page(tmp_path, manual):
    class ProgressNative(Native):
        def __init__(self):
            super().__init__()
            self.progress = {}

        def execute(self, action, data, progress, **kwargs):
            self.progress[data['task_id']] = progress
            return super().execute(action, data, progress, **kwargs)

    path, services = login_fixture(tmp_path, count=2)
    native = ProgressNative()
    login = LoginCoordinator(native, BrowserTaskLock())
    login.start(path, manual_service_id=services[-1].id if manual else None)
    _, data, result = native.operations.get(timeout=2)
    native.progress[data['task_id']]({'page_id': 77, 'waiting_for_user': True})
    state = login.snapshot(BrowserServiceSnapshot.read(path))
    active = state['services'][-1]['preparation'] if manual else state['carsi']
    assert active.page_id == 77 and active.waiting_for_user
    result.set_result({'diagnostic': {'stage': 'preparation', 'code': 'timeout'}})
    login.join()
    state = login.snapshot(BrowserServiceSnapshot.read(path))
    failed = state['services'][-1]['preparation'] if manual else state['carsi']
    assert failed.page_id is None and not failed.waiting_for_user
    assert login.prepared_page(BrowserServiceSnapshot.read(path), services[-1].id) is None
