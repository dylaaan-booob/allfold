from concurrent.futures import Future
from dataclasses import replace
from queue import Queue

import pytest

from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.coordinators.login import LoginCoordinator
from allfold.config import AccessService
from allfold.persistence.safe_write import ContentChangedError
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
        self.cancelled_workflows = []
        self.cancelled_tasks = []
        self.authority = {}
        self.progress = {}

    def execute(self, action, data, progress=None, *, verify_recovery=None):
        result = Future()
        if verify_recovery:
            self.authority[data['task_id']] = verify_recovery
        if progress:
            self.progress[data['task_id']] = progress
        self.operations.put((action, data, result))
        return result

    def cancel_workflow(self, workflow_id):
        self.cancellations += 1
        self.cancelled_workflows.append(workflow_id)

    def cancel_task(self, workflow_id, task_id):
        self.cancelled_tasks.append((workflow_id, task_id))


def opened(page_id):
    return {'outcome': 'Opened', 'target_page_id': page_id}


def test_selected_services_wait_for_first_real_completion_then_dispatch_independently(tmp_path):
    path, services = login_fixture(tmp_path, count=9)
    saved = BrowserServiceSnapshot.read(path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    selected = services[1:-1]
    login.start(path, service_ids=[service.id for service in reversed(selected)])
    action, data, first = native.operations.get(timeout=2)
    try:
        assert action == 'prepare_service' and data['service_id'] == selected[0].id
        assert data['first_entry'] is True
        native.progress[data['task_id']]({'waiting_for_user': True, 'page_id': 17})
        assert login.snapshot(saved)['services'][1]['preparation'].waiting_for_user
        assert native.operations.empty()
    finally:
        first.set_result(opened(17))

    pending = [native.operations.get(timeout=2) for _ in selected[1:]]
    try:
        assert [data['service_id'] for _, data, _ in pending] == [service.id for service in selected[1:]]
        assert all(action == 'prepare_service' and not data['first_entry'] for action, data, _ in pending)
    finally:
        for index, (_, _, future) in enumerate(pending, start=18):
            future.set_result(opened(index))
        login.join()
    assert not lock.owners and login.prepared_page(saved, services[1].id) == 17
    assert login.prepared_authority(saved, services[0].id) is None
    assert login.prepared_authority(saved, services[-1].id) is None


@pytest.mark.parametrize('cancel', [False, True])
def test_incomplete_first_service_does_not_dispatch_the_rest(tmp_path, cancel):
    path, services = login_fixture(tmp_path, count=3)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    workflow_id = login.start(path, service_ids=[service.id for service in services[:-1]])['workflow_id']
    _, _, first = native.operations.get(timeout=2)
    try:
        if cancel:
            assert login.cancel(workflow_id)
            assert native.cancelled_workflows == [workflow_id] and lock.owner
    finally:
        first.set_result(opened(13) if cancel else {'outcome': 'Needs attention'})
        login.join()
    assert native.operations.empty() and not lock.owners
    assert login.snapshot(BrowserServiceSnapshot.read(path))['phase'] == ('canceled' if cancel else 'completed')


def test_unavailable_service_is_reported_before_first_executable_entry(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    saved = load_user_state(path)
    stopped = AccessService.create('中国科学院文献情报中心期刊分区表')
    compare_write_user_state(path, replace(saved.state, access_services=(stopped, *services)), saved.revision)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    login.start(path, service_ids=(stopped.id, services[0].id))
    action, data, result = native.operations.get(timeout=2)
    try:
        assert action == 'prepare_service' and data['first_entry'] and data['service_id'] == services[0].id
        status = login.snapshot(BrowserServiceSnapshot.read(path))['services'][0]['preparation']
        assert status.status == 'Unavailable' and '2026-09-30' in status.reason
    finally:
        result.set_result(opened(29))
        login.join()
    assert native.operations.empty()


def test_cancel_keeps_submitted_prepares_owned_until_all_native_results(tmp_path):
    path, services = login_fixture(tmp_path, count=4)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    workflow_id = login.start(path, service_ids=[service.id for service in services[:-1]])['workflow_id']
    native.operations.get(timeout=2)[2].set_result(opened(17))
    pending = [native.operations.get(timeout=2)[2] for _ in range(3)]
    try:
        assert login.cancel(workflow_id)
        assert login.running and lock.owner and native.cancelled_workflows == [workflow_id]
        pending[0].set_result({'diagnostic': {'stage': 'authentication', 'code': 'configuration_changed'}})
        assert login.running and lock.owner
    finally:
        for future in pending:
            if not future.done():
                future.set_result({})
        login.join()
    assert not lock.owners


def test_prepare_refuses_changed_target_at_recovery(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    login.start(path, service_ids=(services[0].id,))
    _, data, future = native.operations.get(timeout=2)
    try:
        verify = native.authority[data['task_id']]
        verify()
        current = load_user_state(path)
        changed = services[0].model_copy(update={'access_url': 'https://changed.example.org/'})
        compare_write_user_state(path, replace(current.state, access_services=(changed, *services[1:])), current.revision)
        with pytest.raises(ContentChangedError):
            verify()
    finally:
        future.set_result(opened(42))
        login.join()
    assert native.operations.empty()


def test_prepare_without_a_selection_does_not_start_saved_services(tmp_path):
    path, _services = login_fixture(tmp_path)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    for selection in (None, ()):
        with pytest.raises(ValueError, match='Choose saved CARSI Services'):
            login.start(path, service_ids=selection)
    assert native.operations.empty() and not lock.owners


def test_manual_visit_has_its_own_action_and_page_closure_only_drops_the_handle(tmp_path):
    path, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    manual = services[-1]
    login.start(path, manual_service_id=manual.id)
    action, data, future = native.operations.get(timeout=2)
    try:
        assert action == 'visit_manual_service' and data['service_entry'] is None
        assert data['access_url'] == manual.access_url
    finally:
        future.set_result(opened(29))
        login.join()
    saved = BrowserServiceSnapshot.read(path)
    assert login.prepared_page(saved, manual.id) == 29
    login.invalidate_pages([29])
    assert login.prepared_page(saved, manual.id) is None
    assert login.prepared_authority(saved, manual.id).status == 'Opened'
