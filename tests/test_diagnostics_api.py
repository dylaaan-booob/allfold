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
