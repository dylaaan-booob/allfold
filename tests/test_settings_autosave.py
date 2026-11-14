"""Safe domain patches share transaction revisions and active task exclusion."""
import pytest
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


def test_autosave_allows_unrelated_inputs_but_defers_overlapping_service_edits(tmp_path):
    from allfold.application.browser_services import BrowserServiceSnapshot
    config, _, _, service = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        saved_scope = BrowserServiceSnapshot.read(config)
        owner = app.state.browser_task_lock.acquire('login', scopes={saved_scope.service_scope(service.id)})
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='After edit')).json()
        assert saved['saved'] and saved['values']['name'] == 'After edit'
        services = saved['values']['access_services']
        services[0]['access_url'] = 'https://changed.example/'
        pending = client.post('/api/ui-next/settings/autosave', json=patch_body(saved, access_services=services)).json()
        assert pending['outcome'] == 'TASK_ACTIVE' and not pending['saved']
        app.state.browser_task_lock.release(owner)
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(saved, access_services=services)).json()
        assert saved['saved'] and saved['values']['access_services'][0]['access_url'] == 'https://changed.example/'


def test_autosave_rejects_secrets_workspace_moves_and_service_removal(tmp_path):
    config, _, _, service = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        for changes in ({'output_dir': 'other'}, {'openalex_key_action': 'clear'}, {'pubmed_key_action': 'clear'}, {'access_services': []}):
            rejected = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, **changes)).json()
            assert not rejected['saved'] and rejected['outcome'] == 'INVALID_DRAFT'
        actual = client.get('/api/ui-next/settings').json()
        assert actual['values']['output_dir'] == 'workspace'
        assert actual['values']['access_services'][0]['id'] == service.id


def test_explicit_save_preserves_unrelated_browser_work(tmp_path):
    from settings_api_helpers import form
    config, _, _, _ = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge())
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        owner = app.state.browser_task_lock.acquire('prepare')
        submitted = form(opened)
        submitted['name'] = 'Unsafe change'
        rejected = client.post('/settings/save', data=submitted).json()
        assert rejected['saved']
        assert client.get('/api/ui-next/settings').json()['values']['name'] == 'Unsafe change'
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
            started = client.post('/api/ui-next/run', json={'csrf_token': opened['csrf_token'], 'provider': 'integrated'})
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


@pytest.mark.parametrize('save_path', ['autosave', 'explicit'])
@pytest.mark.parametrize('foreground', ['run', 'preprint'])
def test_ordinary_save_rechecks_foreground_started_after_preflight(tmp_path, monkeypatch, save_path, foreground):
    import json
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from allfold.models import ExternalIds
    from allfold.persistence.library_models import PaperMetadata
    from allfold.persistence.paper_repository import PaperRepository
    from allfold.providers import integrated
    from allfold.web import settings_guard
    from http_test_helpers import http_server, isolate_proxy_environment
    from settings_api_helpers import form

    isolate_proxy_environment(monkeypatch)
    config, _, _, _ = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + 'enabled_providers: [openalex]\n')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    doi = '10.5555/settings-race'
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi=doi),
            metadata=PaperMetadata(title='Settings race', publication_type='journal')).paper

    preflight, resume_save, requesting, finish_request = (Event() for _ in range(4))
    drain = settings_guard.drain_settings_effects

    def pause_after_preflight(app, effects):
        assert not effects.get('change')
        preflight.set()
        assert resume_save.wait(5)
        drain(app, effects)

    monkeypatch.setattr(settings_guard, 'drain_settings_effects', pause_after_preflight)

    def response(request):
        requesting.set()
        assert finish_request.wait(5)
        if foreground == 'run':
            assert request.path.startswith('/works?')
            body = {'results': [], 'meta': {'count': 0}}
        else:
            assert request.path in {f'/pubs/{provider}/{doi}/na/json' for provider in ('biorxiv', 'medrxiv')}
            body = {'messages': [{'status': f'Preprint for DOI {doi} not found'}], 'collection': []}
        return 200, {'Content-Type': 'application/json'}, json.dumps(body).encode()

    with http_server(response) as origin:
        for provider in integrated.PROVIDERS:
            monkeypatch.setitem(integrated.BASE_URLS, provider, origin.url)
        app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
        with TestClient(app, base_url='http://localhost') as client:
            opened = client.get('/api/ui-next/settings').json()

            def save():
                if save_path == 'autosave':
                    return client.post('/api/ui-next/settings/autosave',
                        json=patch_body(opened, keyword_expression='inference')).json()
                submitted = form(opened)
                submitted['keyword_expression'] = 'inference'
                return client.post('/settings/save', data=submitted).json()

            with ThreadPoolExecutor(max_workers=1) as pool:
                saving = pool.submit(save)
                try:
                    assert preflight.wait(2)
                    if foreground == 'run':
                        started = client.post('/api/ui-next/run', json={'csrf_token': opened['csrf_token']})
                    else:
                        started = client.post(f'/api/papers/{paper.id}/preprint-lookup/start',
                            json={'csrf_token': opened['csrf_token'], 'workspace_id': str(paper.workspace_id)})
                    assert started.status_code == 200, started.text
                    assert requesting.wait(2)
                    resume_save.set()
                    pending = saving.result(timeout=2)
                    if foreground == 'run':
                        assert not pending['saved'] and pending.get('outcome') == 'TASK_ACTIVE'
                        assert client.get('/api/ui-next/settings').json()['values']['keyword_expression'] == 'causal'
                    else:
                        assert pending['saved'], pending
                        assert client.get('/api/ui-next/settings').json()['values']['keyword_expression'] == 'inference'
                finally:
                    resume_save.set()
                    finish_request.set()
                    app.state.run_coordinator.join()
                    app.state.preprint_lookup.join()
            if foreground == 'run':
                actual = client.get('/api/ui-next/run').json()
                assert actual['snapshot']['unexpected_error'] is None
                assert actual['snapshot']['result']['outcome'] == 'COMPLETED'
                assert actual['providers']['integrated']['latest'] is not None
            else:
                actual = client.get(f'/api/papers/{paper.id}/preprint-lookup/state', params={
                    'workspace_id': str(paper.workspace_id), 'request_id': started.json()['request_id']}).json()
                assert actual['phase'] == 'NoMatch', actual
                assert not actual['cleaning_up']
            assert origin.requests
            if foreground == 'run':
                assert save()['saved']
            assert client.get('/api/ui-next/settings').json()['values']['keyword_expression'] == 'inference'


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
        owner = app.state.browser_task_lock.acquire('covers')
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


def test_active_browser_owner_can_settle_while_configuration_admission_is_held():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from allfold.application.browser_runtime import BrowserTaskLock
    admission = threading.RLock()
    browser = BrowserTaskLock(admission_lock=admission)
    owner = browser.acquire('covers')
    with ThreadPoolExecutor(max_workers=1) as executor:
        with admission:
            finished = executor.submit(browser.release, owner)
            assert finished.result(timeout=1) is None
    assert browser.owner is None


def test_access_save_waits_old_context_cleanup_without_holding_settings_lock(tmp_path):
    import threading
    from concurrent.futures import Future, ThreadPoolExecutor
    from dataclasses import replace
    from allfold.application.browser_services import BrowserServiceSnapshot
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.config import AccessService
    class Native(OfflineBridge):
        connected = True
        def __init__(self):
            self.pending = Future()
            self.invalidating = threading.Event()
        def execute(self, action, data, progress=None, **kwargs):
            if action == 'invalidate_access':
                self.invalidation = data
                self.invalidating.set()
                return self.pending
            assert action == 'visit_manual_service'
            done = Future()
            done.set_result({'outcome': 'Opened', 'evidence': {'visit_action_observed': True,
                'navigation_observed': True, 'target_page_id': 17}})
            return done
    config, _, _, service = current_mapping_document(tmp_path)
    initial = load_user_state(config)
    manual = AccessService.create('Manual', 'https://publisher.example/', access_method='manual')
    compare_write_user_state(config, replace(initial.state, access_services=(*initial.state.access_services, manual)), initial.revision)
    bridge = Native()
    app = create_app(config, electron_bridge=bridge)
    with TestClient(app, base_url='http://localhost') as client:
        app.state.login.start(config, manual_service_id=manual.id)
        app.state.login.join()
        old = BrowserServiceSnapshot.read(config)
        old_key = app.state.login.prepared_authority(old, manual.id).key
        opened = client.get('/api/ui-next/settings').json()
        rows = opened['values']['access_services']
        rows[-1]['access_url'] = 'https://replacement.example/'
        with ThreadPoolExecutor(max_workers=1) as pool:
            saving = pool.submit(client.post, '/api/ui-next/settings/autosave',
                json=patch_body(opened, access_services=rows))
            try:
                assert bridge.invalidating.wait(2)
                assert app.state.settings_write_lock.acquire(blocking=False)
                app.state.settings_write_lock.release()
                assert bridge.invalidation == {'scope_id': old.scope_id,
                    'preparation_keys': {manual.id: old_key}, 'authentication_key': None}
                with pytest.raises(ValueError, match='Browser workflow'):
                    app.state.login.start(config, manual_service_id=manual.id)
                assert app.state.browser_task_lock.acquire('credentials') is None
                assert app.state.login.prepared_authority(BrowserServiceSnapshot.read(config), manual.id) is None
            finally:
                bridge.pending.set_result({'ok': True})
            assert saving.result(timeout=2).json()['saved']
        assert not app.state.browser_task_lock.owners
