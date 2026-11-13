"""Captured Run identities across the public coordinator and HTTP boundary."""
import threading
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

from allfold.application.coordinators.run_coordinator import RunCoordinator
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from safety_config_helpers import current_mapping_document


def test_old_cancel_cannot_cancel_replacement_run_or_retarget_wos(tmp_path, monkeypatch):
    path, _, _, _ = current_mapping_document(tmp_path)
    entered, release = threading.Event(), threading.Event()
    signals = []
    def isolated_run(*args, **kwargs):
        signals.append(kwargs['cancel_event'])
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', isolated_run)
    coordinator = RunCoordinator(path)
    forwarded, continue_cancel = threading.Event(), threading.Event()
    class NativeStage:
        running = True
        task = None
        execute_stage = None
        def cancel(self, task_id):
            forwarded.set()
            assert continue_cancel.wait(3)
            self.cancelled = task_id
    stage = NativeStage()
    coordinator.wos_stage = stage
    coordinator.start()
    assert entered.wait(2)
    first = coordinator.snapshot().task_id
    try:
        assert not coordinator.cancel('obsolete')
        assert not signals[0].is_set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            cancelled = pool.submit(coordinator.cancel, first)
            assert forwarded.wait(2)
            release.set()
            coordinator.join()
            entered.clear(); release.clear()
            coordinator.start()
            assert entered.wait(2)
            second = coordinator.snapshot().task_id
            assert second != first
            continue_cancel.set()
            assert cancelled.result(timeout=2)
        assert stage.cancelled == first
        assert not coordinator.cancel(first)
        assert not signals[1].is_set()
    finally:
        continue_cancel.set(); release.set()
        coordinator.join()


def test_public_run_cancel_requires_captured_task_id(tmp_path, monkeypatch):
    path, _, _, _ = current_mapping_document(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def isolated_run(*args, **kwargs):
        entered.set()
        assert release.wait(3)
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', isolated_run)
    app = create_app(path, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        csrf = {'csrf_token': app.state.csrf_token}
        started = client.post('/api/ui-next/run', json=csrf).json()
        assert entered.wait(2)
        try:
            assert client.post('/api/ui-next/run/cancel', json=csrf).status_code == 422
            assert client.post('/api/ui-next/run/cancel', json={**csrf, 'task_id': 'old'}).status_code == 409
            assert client.post('/api/ui-next/run/cancel', json={**csrf, 'task_id': started['snapshot']['task_id']}).json()['accepted']
        finally:
            release.set()


def test_shutdown_stops_new_run_admission(tmp_path, monkeypatch):
    path, _, _, _ = current_mapping_document(tmp_path)
    dispatched = []
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor',
        lambda *args, **kwargs: dispatched.append(True))
    coordinator = RunCoordinator(path)
    coordinator.shutdown()
    assert coordinator.start().outcome.value == 'START_FAILED'
    coordinator.join()
    assert not dispatched
