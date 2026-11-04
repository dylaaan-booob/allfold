"""Safe domain patches share transaction revisions and active task exclusion."""
from fastapi.testclient import TestClient
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from safety_config_helpers import current_mapping_document


def patch_body(state, **changes):
    return {'csrf_token': state['csrf_token'], 'base': {
        key: state['values'][key] for key in ('monitor_revision_exists', 'monitor_revision_digest',
        'journal_revision_exists', 'journal_revision_digest')}, 'changes': changes}


def test_autosave_patches_only_requested_fields_and_rejects_stale_revisions(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='Updated Monitor')).json()
        assert saved['saved'] and saved['values']['name'] == 'Updated Monitor'
        assert saved['values']['keyword_expression'] == 'causal'
        rejected = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, log_level='DEBUG')).json()
        assert rejected['outcome'] == 'REVISION_CONFLICT'
        actual = client.get('/api/ui-next/settings').json()
        assert actual['values']['name'] == 'Updated Monitor' and actual['values']['log_level'] == 'INFO'


def test_autosave_retains_original_revision_while_browser_task_owns_configuration(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        owner = app.state.browser_task_lock.acquire('prepare')
        pending = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='After task')).json()
        assert pending['outcome'] == 'TASK_ACTIVE' and not pending['saved']
        assert client.get('/api/ui-next/settings').json()['values']['name'] == 'Test Monitor'
        app.state.browser_task_lock.release(owner)
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='After task')).json()
        assert saved['saved'] and saved['values']['name'] == 'After task'


def test_autosave_rejects_secrets_workspace_moves_and_service_removal(tmp_path):
    config, _, _, service = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        for changes in ({'output_dir': 'other'}, {'openalex_key_action': 'clear'}, {'access_services': []}):
            rejected = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, **changes)).json()
            assert not rejected['saved'] and rejected['outcome'] == 'INVALID_DRAFT'
        actual = client.get('/api/ui-next/settings').json()
        assert actual['values']['output_dir'] == 'workspace'
        assert actual['values']['access_services'][0]['id'] == service.id


def test_explicit_legacy_save_cannot_invalidate_waiting_browser_task(tmp_path):
    from settings_api_helpers import form
    config, _, _, _ = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        owner = app.state.browser_task_lock.acquire('prepare')
        submitted = form(opened)
        submitted['name'] = 'Unsafe change'
        rejected = client.post('/settings/save', data=submitted).json()
        assert not rejected.get('saved', False) and rejected['outcome'] == 'TASK_ACTIVE'
        assert client.get('/api/ui-next/settings').json()['values']['name'] == 'Test Monitor'
        app.state.browser_task_lock.release(owner)


def test_ordinary_run_defers_autosave_until_worker_settles(tmp_path, monkeypatch):
    import threading
    import allfold.application.coordinators.run_coordinator as run_module
    entered, release = threading.Event(), threading.Event()
    def isolated_run(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return None
    monkeypatch.setattr(run_module, 'run_monitor', isolated_run)
    config, _, _, _ = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        try:
            started = client.post('/api/ui-next/run', json={'csrf_token': opened['csrf_token'], 'provider': 'crossref'})
            assert started.status_code == 200 and entered.wait(2)
            assert app.state.browser_task_lock.owner is None
            pending = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='Later')).json()
            assert pending['outcome'] == 'TASK_ACTIVE'
            assert client.get('/api/ui-next/settings').json()['values']['name'] == 'Test Monitor'
        finally:
            release.set()
        import time
        deadline = time.monotonic() + 2
        while client.get('/api/ui-next/run').json()['snapshot']['status'] == 'RUNNING' and time.monotonic() < deadline:
            time.sleep(.01)
        assert client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='Later')).json()['saved']


def test_credentials_are_explicit_native_settled_and_blocked_for_waiting_task(tmp_path):
    from concurrent.futures import Future
    class CredentialsBridge(OfflineBridge):
        connected = True
        def __init__(self):
            self.calls = []
        def execute(self, action, data):
            self.calls.append((action, data))
            result = Future()
            result.set_result({'ok': True, 'configured': True, 'username': 'fixture', 'revision': 'new'})
            return result
    config, _, _, _ = current_mapping_document(tmp_path)
    bridge = CredentialsBridge()
    app = create_app(config, electron_bridge=bridge)
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        body = {'csrf_token': opened['csrf_token'], 'operation': 'save', 'username': 'fixture',
                'password': 'synthetic-only', 'expected_revision': 'missing'}
        owner = app.state.browser_task_lock.acquire('kept')
        assert client.post('/api/ui-next/settings/credentials', json=body).json()['error'] == 'cas_task_active'
        assert not bridge.calls
        app.state.browser_task_lock.release(owner)
        saved = client.post('/api/ui-next/settings/credentials', json=body).json()
        assert saved == {'ok': True, 'configured': True, 'username': 'fixture', 'revision': 'new'}
        assert bridge.calls[0][0] == 'cas_credentials'
        assert app.state.browser_task_lock.owner is None
        actual = client.get('/api/ui-next/settings').json()
        assert actual['values']['monitor_revision_digest'] == opened['values']['monitor_revision_digest']
        assert 'synthetic-only' not in str(actual)
