from concurrent.futures import Future
from dataclasses import replace
from queue import Queue
import threading

import pytest

from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.coordinators.login import LoginCoordinator
from allfold.application.coordinators.wos_coordinator import WoSCoordinator
from allfold.config import AccessService
from allfold.persistence.user_state import compare_write_user_state, load_user_state
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

    def execute(self, action, data, progress):
        result = Future()
        self.operations.put((action, data, result))
        return result

    def cancel_current(self):
        self.cancellations += 1


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
    assert lock.owner is not None and native.cancellations == 1
    pending[0].set_result(opened(29))
    for result in pending[1:]:
        result.set_result({})
    login.join()
    state = login.snapshot(BrowserServiceSnapshot.read(path))
    assert state['phase'] == 'canceled' and native.operations.empty()
    assert state['services'][0]['preparation'].status == 'Opened'
    assert state['services'][5]['preparation'].status == 'Canceled'
    assert lock.owner is None


def test_discover_asks_for_login_without_preparing_or_taking_browser_owner(tmp_path):
    path, _ = login_fixture(tmp_path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    discover = WoSCoordinator(path, login, threading.Lock(), bridge=native, browser_lock=lock)
    with pytest.raises(ValueError, match='Workflows → Login'):
        discover.start()
    assert native.operations.empty() and lock.owner is None
