"""History/export/reset HTTP seams, isolated from browser and personal data."""
import io
import zipfile

from fastapi.testclient import TestClient
from electron_test_helpers import OfflineBridge
from allfold.web.app import create_app


def configuration(tmp_path):
    config = tmp_path / 'monitor.yaml'
    config.write_text('keyword_expression: synthetic\noutput_dir: workspace\nvenue_whitelist: list.md\nfrom_month: 2026-01\nto_month: 2026-01\n')
    return config


def test_history_export_and_logs_reset_require_csrf_one_use_and_leave_workspace(tmp_path):
    config = configuration(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    app.state.diagnostics.begin('run', 'run_one', provider='pubmed')
    app.state.diagnostics.finish('run_one', 'partial', statistics={'retrieved': 7})
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    preserved = workspace / 'private.txt'
    preserved.write_text('real data placeholder')
    with TestClient(app, base_url='http://localhost') as client:
        csrf = app.state.csrf_token
        assert client.get('/api/history').json()['records'][0]['outcome'] == 'partial'
        assert client.post('/api/diagnostics/export', json={'task_id': 'run_one'}).status_code == 403
        exported = client.post('/api/diagnostics/export', json={'csrf_token': csrf, 'task_id': 'run_one'})
        assert exported.status_code == 200
        assert zipfile.is_zipfile(io.BytesIO(exported.content))
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        assert preview['reset_plan']['scope'] == 'logs'
        data = {'csrf_token': csrf, 'reset_token': preview['reset_token']}
        assert client.post('/settings/logs-reset', data={**data, 'csrf_token': 'wrong'}).status_code == 403
        response = client.post('/settings/logs-reset', data=data)
        assert response.status_code == 200, response.text
        assert response.json()['reset_success']
        assert client.post('/settings/logs-reset', data=data).status_code == 409
        assert client.get('/api/history').json()['records'] == []
    assert preserved.read_text() == 'real data placeholder'


def test_workspace_reset_needs_no_word_and_keeps_pre_reset_history(tmp_path):
    config = configuration(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    app.state.diagnostics.begin('run', 'old_run')
    app.state.diagnostics.finish('old_run', 'completed')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'snapshot.json').write_text('old result')
    with TestClient(app, base_url='http://localhost') as client:
        preview = client.get('/api/ui-next/settings/reset-preview?scope=workspace').json()
        response = client.post('/settings/workspace-reset', data={
            'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
        assert response.status_code == 200, response.text
        assert not workspace.exists()
        history = client.get('/api/history').json()
        assert history['records'][0]['task_id'] == 'old_run'
        assert history['records'][0]['before_workspace_reset']


def test_partial_workspace_reset_marks_old_history_after_the_target_moves(tmp_path, monkeypatch):
    import allfold.application.workspace_reset as reset

    config = configuration(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    app.state.diagnostics.begin('run', 'old_run')
    app.state.diagnostics.finish('old_run', 'completed')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'snapshot.json').write_text('old result')
    unrelated = tmp_path / 'unrelated.txt'
    unrelated.write_text('preserved')
    def fail_delete(name, *, dir_fd):
        raise OSError('synthetic deletion failure after custody rename')
    fail_delete.avoids_symlink_attacks = True
    monkeypatch.setattr(reset.shutil, 'rmtree', fail_delete)
    with TestClient(app, base_url='http://localhost') as client:
        preview = client.get('/api/ui-next/settings/reset-preview?scope=workspace').json()
        data = {'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']}
        import_token = app.state.import_token
        response = client.post('/settings/workspace-reset', data=data)
        assert response.status_code == 409, response.text
        assert not response.json()['reset_success']
        assert response.json()['reset_result']['workspace_invalidated']
        assert not workspace.exists()
        assert client.get('/api/history').json()['records'][0]['before_workspace_reset']
        assert app.state.import_token == import_token
        assert client.post('/settings/workspace-reset', data=data).status_code == 409
    captured = next(tmp_path.glob('.allfold-reset-*/workspace'))
    assert (captured / 'snapshot.json').read_text() == 'old result'
    assert unrelated.read_text() == 'preserved'
    assert config.read_text().startswith('keyword_expression: synthetic')


def test_logs_reset_refuses_active_work_and_disconnected_native_files(tmp_path):
    config = configuration(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    app.state.diagnostics.begin('import', 'save')
    with TestClient(app, base_url='http://localhost') as client:
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        owner = app.state.browser_task_lock.acquire('import')
        try:
            response = client.post('/settings/logs-reset', data={
                'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
            assert response.status_code == 409
            assert len(client.get('/api/history').json()['records']) == 1
        finally:
            app.state.browser_task_lock.release(owner)
        native = app.state.diagnostics.root / 'scopes' / app.state.diagnostics.scope_id / 'electron'
        native.mkdir(mode=0o700)
        record = native / 'events.0.jsonl'
        record.write_text('native writer may still be running')
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        assert preview['reset_token'] is None
        assert record.read_text() == 'native writer may still be running'


def test_native_partial_reset_reports_failure_and_preserves_python_history(tmp_path):
    from concurrent.futures import Future
    class NativeBridge(OfflineBridge):
        connected = True
        def execute(self, action, data):
            assert action == 'diagnostics_reset'
            future = Future()
            if data['operation'] == 'preview':
                future.set_result({'scope_id': data['scope_id'], 'available': True,
                                   'token': 'native_token', 'status': {'incomplete': False}})
            else:
                assert data['expected']['token'] == 'native_token'
                future.set_result({'scope_id': data['scope_id'], 'success': False,
                    'partial': True, 'deleted': 1, 'failed': 1, 'status': {'incomplete': True}})
            return future
    config = configuration(tmp_path)
    app = create_app(config, electron_bridge=NativeBridge(), diagnostics_root=tmp_path / 'logs')
    app.state.diagnostics.begin('run', 'run_one')
    with TestClient(app, base_url='http://localhost') as client:
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        data = {'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']}
        response = client.post('/settings/logs-reset', data=data)
        assert response.status_code == 409
        assert response.json()['reset_result']['native']['partial']
        assert len(client.get('/api/history').json()['records']) == 1
        assert client.post('/settings/logs-reset', data=data).status_code == 409


def test_workspace_confirmation_expires_without_deleting_target(tmp_path, monkeypatch):
    import allfold.web.app as web
    config = configuration(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    (workspace / 'data').write_text('preserved')
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        preview = client.get('/api/ui-next/settings/reset-preview').json()
        original = web.time.monotonic
        monkeypatch.setattr(web.time, 'monotonic', lambda: original() + 301)
        response = client.post('/settings/workspace-reset', data={
            'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
        assert response.status_code == 409
        assert (workspace / 'data').read_text() == 'preserved'


def test_logs_reset_and_run_start_finish_without_a_diagnostic_lock_deadlock(tmp_path):
    # A subprocess bounds failure even if both real request threads deadlock.
    import subprocess
    import sys
    import textwrap

    probe = textwrap.dedent('''
        import os
        import sys
        import threading
        import time
        from pathlib import Path
        sys.path.insert(0, sys.argv[2])
        from fastapi.testclient import TestClient
        from allfold.web.app import create_app
        import allfold.application.coordinators.run_coordinator as runs
        from allfold.application.run_state import RunProvider
        from electron_test_helpers import OfflineBridge

        root = Path(sys.argv[1])
        config = root / 'monitor.yaml'
        config.write_text('keyword_expression: synthetic\\noutput_dir: workspace\\n')
        app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=root / 'logs')
        coordinator = app.state.run_coordinator
        beginning = threading.Event()
        checking = threading.Event()
        monitor_started = threading.Event()
        monitor_release = threading.Event()
        observe = runs.observe
        snapshot = coordinator.snapshot

        def held_begin(store, method, *args, **kwargs):
            if method == 'begin':
                beginning.set()
                assert checking.wait(3), 'Reset did not reach the Run gate'
            return observe(store, method, *args, **kwargs)

        def checked_snapshot():
            checking.set()
            return snapshot()

        def monitor(*args, **kwargs):
            monitor_started.set()
            assert monitor_release.wait(3), 'Run was not released'

        runs.observe = held_begin
        runs.run_monitor = monitor
        coordinator.snapshot = checked_snapshot
        with TestClient(app, base_url='http://localhost') as client:
            preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
            results = {}
            def start():
                results['start'] = coordinator.start(RunProvider.PUBMED).outcome.value
            def reset():
                response = client.post('/settings/logs-reset', data={
                    'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
                results['reset'] = response.status_code
            starter = threading.Thread(target=start, daemon=True)
            resetter = threading.Thread(target=reset, daemon=True)
            starter.start()
            assert beginning.wait(3)
            resetter.start()
            starter.join(3)
            resetter.join(3)
            if starter.is_alive() or resetter.is_alive():
                print('Run start / Logs Reset deadlocked', flush=True)
                os._exit(1)
            assert results == {'start': 'STARTED', 'reset': 409}, results
            assert monitor_started.wait(3)
            monitor_release.set()
            deadline = time.monotonic() + 3
            while snapshot().status.value == 'RUNNING' and time.monotonic() < deadline:
                time.sleep(0.01)
            assert snapshot().status.value == 'FINISHED'
            assert app.state.diagnostics.history()['records'][0]['outcome'] == 'failed'
        print('Run started and Logs Reset refused without blocking', flush=True)
    ''')
    from pathlib import Path
    result = subprocess.run([sys.executable, '-c', probe, str(tmp_path), str(Path(__file__).parent)],
                            capture_output=True, text=True, timeout=12)
    assert result.returncode == 0, result.stdout + result.stderr
