"""Kept scope authority at the signed-target, plan and native dispatch boundaries."""
from dataclasses import replace
from concurrent.futures import Future

import pytest

from allfold.application.batch_import import BatchImportService, BatchPhase
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.import_target import _ImportTarget
from allfold.config import AccessService, JournalConfig
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from electron_test_helpers import paper, edit
from safety_config_helpers import current_mapping_document


def scoped_workspace(tmp_path):
    config, _, journal, service = current_mapping_document(tmp_path)
    other = AccessService.create('Other', 'https://other.example.org/', access_method='manual')
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, journals=(journal,
        JournalConfig(name='Other journal', issn='0090-5364', access_service_id=other.id)),
        access_services=(service, other)), saved.revision)
    workspace = tmp_path / 'workspace'
    values = []
    for name, issns in [('a', ['0006-341X']), ('b', ['0090-5364']),
                        ('missing', []), ('ambiguous', ['0006-341X', '0090-5364'])]:
        value, path = paper(workspace, name)
        edit(path, journal_issns=issns)
        values.append(value)
    return config, service, other, values


def test_signed_target_binds_saved_service_and_cannot_be_retargeted(tmp_path):
    config, service, other, _ = scoped_workspace(tmp_path)
    all_target, _ = _ImportTarget.read(config)
    selected, _ = _ImportTarget.read(config, service_id=service.id)
    other_target, _ = _ImportTarget.read(config, service_id=other.id)
    assert len({target.form_token('nonce') for target in (all_target, selected, other_target)}) == 3
    assert selected.service_id == service.id
    with pytest.raises(ContentChangedError):
        _ImportTarget.read(config, service_id='svc_' + '0' * 32)


def test_single_service_dispatch_and_history_use_execution_mapping(tmp_path):
    from allfold.diagnostics import DiagnosticStore
    config, service, other, values = scoped_workspace(tmp_path)
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    class Bridge:
        connected = True
        calls = []
        def execute(self, action, data, progress=None):
            self.calls.append(data)
            future = Future()
            future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
            return future
    bridge, lock = Bridge(), BrowserTaskLock()
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=lock.acquire('kept'),
                config_path=config, service_id=service.id)
    batch.join()
    assert batch.snapshot().phase is BatchPhase.COMPLETED
    assert [call['paper_id'] for call in bridge.calls] == [str(values[0].id)]
    assert bridge.calls[0]['service_id'] == service.id
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, journals=tuple(
        journal.model_copy(update={'access_service_id': other.id}) for journal in saved.state.journals)), saved.revision)
    details = store.history()['records'][0]['details']
    assert details['batch_scope'] == 'service'
    assert details['service_id'] == service.id
    assert details['results'][0]['service_id'] == service.id
    assert details['results'][0]['pdf_outcome'] == 'unverified'
    assert details['service_statistics'] == [{'service_id': service.id, 'total': 1,
        'processed': 1, 'confirmed': 0, 'no_effect': 1, 'uncertain': 0, 'skipped': 0, 'warnings': 0, 'pdf_unverified': 1}]


def test_scope_filter_runs_after_global_duplicate_scan(tmp_path):
    config, service, _, values = scoped_workspace(tmp_path)
    # An out-of-scope candidate still participates in identity safety.
    from allfold.models import WorkflowStatus
    paper(tmp_path / 'workspace', 'duplicate', doi=values[0].external_ids.doi,
          status=WorkflowStatus.CANDIDATE)
    class Bridge:
        connected = True
        def execute(self, *args):
            raise AssertionError('Duplicate DOI must never dispatch')
    lock = BrowserTaskLock()
    batch = BatchImportService(Bridge(), lock)
    batch.start(tmp_path / 'workspace', browser_owner=lock.acquire('kept'),
                config_path=config, service_id=service.id)
    batch.join()
    assert batch.snapshot().plan.papers == ()
    assert any('Duplicate normalized DOI' in item.reason for item in batch.snapshot().plan.exclusions)


def test_queue_qualification_and_scope_tokens_are_authoritative(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, service, other, values = scoped_workspace(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        all_queue = client.get('/api/kept-workflow/queue').json()
        queue = client.get('/api/kept-workflow/queue', params={'service_id': service.id}).json()
        rows = {row['id']: row for row in queue['services']}
        assert rows['all']['kept'] == rows['all']['eligible'] == 4
        assert rows[service.id]['eligible'] == rows[other.id]['eligible'] == 1
        assert rows['unassigned']['kept'] == rows['ambiguous']['kept'] == 1
        assert queue['import_token'] != all_queue['import_token']
        assert client.get('/api/kept-workflow/queue', params={'service_id': 'unknown'}).status_code == 409
        invalid = client.post('/api/kept-workflow/start', json={'csrf_token': app.state.csrf_token,
            'import_token': all_queue['import_token'], 'service_id': service.id, 'mode': 'import_only'})
        assert invalid.status_code == 409
        assert app.state.kept_workflow.snapshot().workflow_id is None


def test_prepare_wait_continue_keep_one_scope_and_conflicting_start_cannot_retarget(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, service, other, values = scoped_workspace(tmp_path)
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, access_services=(
        service.model_copy(update={'access_method': 'manual'}), other)), saved.revision)
    class Bridge(OfflineBridge):
        connected = True
        calls = []
        def execute(self, action, data, progress=None):
            self.calls.append(data)
            future = Future()
            future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
            return future
    bridge = Bridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        def start(selected):
            queue = client.get('/api/kept-workflow/queue', params={'service_id': selected}).json()
            return client.post('/api/kept-workflow/start', json={'csrf_token': app.state.csrf_token,
                'import_token': queue['import_token'], 'service_id': selected})
        result = start(service.id)
        assert result.status_code == 200
        state = result.json()
        assert state['phase'] == 'waiting_for_user'
        assert state['service_id'] == service.id
        assert [entry['id'] for entry in state['preparation']['manual_services']] == [service.id]
        assert start(other.id).status_code == 409
        assert app.state.kept_workflow.snapshot().service_id == service.id
        # A display refresh or newly Kept Paper cannot enlarge the explicit batch.
        _, added = paper(tmp_path / 'workspace', 'added-later')
        edit(added, journal_issns=['0006-341X'])
        queue = client.get('/api/kept-workflow/queue').json()
        row = next(row for row in queue['services'] if row['id'] == service.id)
        assert row['kept'] == 2
        assert row['planned'] == 1
        identity = {'csrf_token': app.state.csrf_token, 'workflow_id': state['workflow_id'], 'generation': state['generation']}
        assert client.post('/api/kept-workflow/continue', json=identity).status_code == 200
        app.state.batch_import.join()
        app.state.kept_workflow.advance()
        assert [call['paper_id'] for call in bridge.calls] == [str(values[0].id)]
        assert client.post('/api/kept-workflow/continue', json=identity).status_code == 409
        assert len(bridge.calls) == 1


def test_interrupted_history_retains_execution_scope_and_rejects_unbounded_identity(tmp_path):
    from allfold.diagnostics import DiagnosticStore
    config, service, _, _ = scoped_workspace(tmp_path)
    store = DiagnosticStore(config, root=tmp_path / 'logs', runtime_id='first')
    store.begin('kept', 'kept-task', details={'batch_scope': 'service', 'service_id': service.id,
        'config_revision': 'a' * 64, 'user_state_revision': 'b' * 64, 'url': 'PRIVATE_SENTINEL'})
    restored = DiagnosticStore(config, root=tmp_path / 'logs', runtime_id='second').history()['records'][0]
    assert restored['outcome'] == 'uncertain'
    assert restored['details']['service_id'] == service.id
    assert restored['details']['config_revision'] == 'a' * 64
    assert 'PRIVATE_SENTINEL' not in repr(restored)
