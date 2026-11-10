"""Kept scope authority at the signed-target, plan and native dispatch boundaries."""
from dataclasses import replace
from concurrent.futures import Future

import pytest

from allfold.application.batch_import import BatchImportService, BatchPhase
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.application.import_target import _ImportTarget
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.config import AccessService, JournalConfig
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from electron_test_helpers import paper, edit
from safety_config_helpers import current_mapping_document


def scoped_workspace(tmp_path):
    config, _, journal, service = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + 'kept_workflow:\n  zotero_target:\n    server_id: SERVERFIXTUR\n    library_type: group\n    library_id: \"12\"\n    collection_key: ABCDEFGH\n')
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
            if action == 'zotero_local':
                future = Future(); future.set_result({'ok': True}); return future
            self.calls.append(data)
            future = Future()
            future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
            return future
    bridge, lock = Bridge(), BrowserTaskLock()
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=lock.acquire('kept'),
                services=BrowserServiceSnapshot.read(config), service_id=service.id)
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
                services=BrowserServiceSnapshot.read(config), service_id=service.id)
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
            'import_token': all_queue['import_token'], 'service_id': service.id})
        assert invalid.status_code == 409
        assert app.state.kept_workflow.snapshot().workflow_id is None


def test_import_requires_explicit_unprepared_skips_and_keeps_the_doi_path(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge, state
    config, service, other, values = scoped_workspace(tmp_path)

    class Bridge(OfflineBridge):
        connected = True
        def __init__(self):
            self.calls = []

        def execute(self, action, data, progress=None):
            self.calls.append((action, data))
            future = Future()
            if action == 'zotero_local':
                future.set_result({'ok': True})
            else:
                assert action == 'import_paper'
                future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
            return future

    bridge = Bridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        queue = client.get('/api/kept-workflow/queue').json()
        assert {entry['id'] for entry in queue['unprepared_services']} == {service.id, other.id}
        body = {'csrf_token': app.state.csrf_token, 'import_token': queue['import_token']}
        assert client.post('/api/kept-workflow/start', json=body).status_code == 409
        assert not bridge.calls
        assert client.post('/api/kept-workflow/start', json={
            **body, 'skip_unprepared': [service.id]}).status_code == 409
        started = client.post('/api/kept-workflow/start', json={
            **body, 'skip_unprepared': [service.id, other.id]})
        assert started.status_code == 200
        app.state.batch_import.join()
        app.state.kept_workflow.join()

        imports = [data for action, data in bridge.calls if action == 'import_paper']
        assert {data['paper_id'] for data in imports} == {str(values[2].id), str(values[3].id)}
        assert all(data['service_id'] is None for data in imports)
        response = client.get('/api/kept-workflow/state').json()
        assert response['phase'] == 'completed'
        results = {entry['paper_id']: entry for entry in response['batch']['results']}
        for value, name in zip(values[:2], ['a', 'b'], strict=True):
            assert results[str(value.id)]['reason_code'] == 'service_unprepared'
            assert state(tmp_path / 'workspace' / 'Papers' / f'{name}.md').status.value == 'kept'
        assert client.post('/api/kept-workflow/start', json={
            **body, 'skip_unprepared': [service.id, other.id]}).status_code == 409
        assert [action for action, _ in bridge.calls].count('zotero_local') == 1

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


def test_queue_on_a_fresh_workspace_keeps_saved_services_visible_without_writes(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, _, _, service = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        response = client.get('/api/kept-workflow/queue')
        assert response.status_code == 200
        assert next(row for row in response.json()['services'] if row['id'] == service.id)['eligible'] == 0
    assert not (tmp_path / 'workspace').exists()


def test_import_uses_prepared_service_and_exposes_only_safe_local_keys(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from test_login import opened

    config, service, other, values = scoped_workspace(tmp_path)
    class Bridge(OfflineBridge):
        connected = True
        def __init__(self):
            self.calls = []

        def execute(self, action, data, progress=None):
            self.calls.append((action, data))
            future = Future()
            if action == 'zotero_local':
                future.set_result({'ok':True})
            elif action == 'visit_manual_service':
                future.set_result(opened(17))
            else:
                assert action == 'import_paper'
                future.set_result({'settled':True, 'parent':{'outcome':'confirmed', 'status':200,
                    'protocol':'local-api-v3', 'requested_id':'ABCDEFGH', 'accepted_id':'ABCDEFGH'},
                    'pdf':{'registered':True, 'failures':[{'phase':'initial_fetch', 'code':'http_error', 'status':403}]},
                    'zotero':{'parent_key':'ABCDEFGH', 'attachment_keys':['BCDEFGHI']},
                    'last_import':{'item_exists':True, 'pdf_attached':True, 'pdf_source':'openalex',
                                   'fallback_used':True, 'query_diagnostic':None}})
            return future

    bridge = Bridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        assert client.post('/api/login/start', json={'csrf_token':app.state.csrf_token, 'service_id':other.id}).status_code == 200
        app.state.login.join()
        queue = client.get('/api/kept-workflow/queue', params={'service_id':other.id}).json()
        assert not queue['unprepared_services']
        body = {'csrf_token': app.state.csrf_token, 'import_token': queue['import_token'], 'service_id': other.id}
        stale = client.post('/api/kept-workflow/start', json={**body, 'skip_unprepared': [other.id]})
        assert stale.status_code == 409
        response = client.post('/api/kept-workflow/start', json=body)
        assert response.status_code == 200
        app.state.kept_workflow.join()
        assert [action for action, _ in bridge.calls] == ['visit_manual_service', 'zotero_local', 'import_paper']
        observed = client.get('/api/kept-workflow/state').json()['batch']['results'][0]
        assert observed['paper_id'] == str(values[1].id) and observed['service_id'] == other.id
        assert observed['item_exists'] and observed['pdf_attached'] and observed['fallback_used']
        assert observed['pdf_source'] == 'openalex'
        assert observed['zotero_keys'] == {'parent_key': 'ABCDEFGH', 'attachment_keys': ['BCDEFGHI']}
        assert 'native_identity' not in observed
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state, journals=tuple(
            journal.model_copy(update={'access_service_id':service.id}) for journal in saved.state.journals)), saved.revision)
        retained = client.get('/api/kept-workflow/state').json()['batch']['results'][0]
        assert retained['service_id'] == other.id

def test_parallel_import_drains_exact_paper_results_after_uncertainty(tmp_path):
    from queue import Empty, Queue
    from test_electron_import import confirmed
    from electron_test_helpers import state

    config, service, other, values = scoped_workspace(tmp_path)
    workspace = tmp_path / 'workspace'
    (workspace / 'Papers' / 'ambiguous.md').rename(workspace / 'Papers' / 'z-ambiguous.md')
    _, later = paper(workspace, 'aa-later')
    edit(later, journal_issns=['0006-341X'])

    class Bridge:
        connected = True
        def __init__(self):
            self.dispatched = Queue()

        def execute(self, action, data, progress=None):
            assert action == 'import_paper'
            future = Future()
            self.dispatched.put((data, future))
            return future

        def cancel_current(self):
            pass

    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock)
    try:
        batch.start(workspace, browser_owner=owner, services=BrowserServiceSnapshot.read(config),
            paper_limit=2, service_limit=1, native_limits={'translator': 2, 'pdf': 2, 'writer': 2})
        first, uncertain = bridge.dispatched.get(timeout=2)
        second, accepted = bridge.dispatched.get(timeout=2)
        assert (first['service_id'], second['service_id']) == (service.id, other.id)
        assert (first['paper_id'], second['paper_id']) == (str(values[0].id), str(values[1].id))
        assert first['workspace_identity'] == second['workspace_identity']
        assert first['limits'] == second['limits'] == {'translator': 2, 'pdf': 2, 'writer': 2}
        uncertain.set_result({'settled': True, 'parent': {'outcome': 'uncertain'},
            'zotero': {'parent_key': 'ABCD2345'}})
        with pytest.raises(Empty):
            bridge.dispatched.get(timeout=.1)
        assert batch.running and lock.owner is owner
        with pytest.raises(RuntimeError):
            with workspace_operation_lock(workspace):
                pass
        accepted.set_result({**confirmed(), 'zotero': {'parent_key': 'ABCDEFGH'}})
        batch.join()
        result = {item.paper_id: item for item in batch.snapshot().results}
        assert batch.snapshot().phase is BatchPhase.PAUSED
        assert result[values[0].id].outcome == 'uncertain'
        assert result[values[0].id].native_identity == {'parent_key': 'ABCD2345'}
        assert result[values[1].id].outcome == 'exported'
        assert result[values[1].id].native_identity == {'parent_key': 'ABCDEFGH'}
        assert len(result) == 5 and sum(item.outcome == 'skipped' for item in result.values()) == 3
        assert state(workspace / 'Papers' / 'a.md').status.value == 'kept'
        assert state(workspace / 'Papers' / 'b.md').status.value == 'exported'
    finally:
        batch.stop()
        while not bridge.dispatched.empty():
            _, future = bridge.dispatched.get_nowait()
            future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
        for future in [locals().get('uncertain'), locals().get('accepted')]:
            if future is not None and not future.done():
                future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
        batch.join()
        lock.release(owner)



def test_scoped_import_can_settle_explicit_skips_without_a_native_connection(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge, state

    config, service, _, values = scoped_workspace(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        queue = client.get('/api/kept-workflow/queue', params={'service_id': service.id}).json()
        assert queue['unprepared_services'] == [{'id': service.id, 'name': service.name}]
        started = client.post('/api/kept-workflow/start', json={
            'csrf_token': app.state.csrf_token, 'import_token': queue['import_token'],
            'service_id': service.id, 'skip_unprepared': [service.id],
        })
        assert started.status_code == 200
        app.state.kept_workflow.join()
        terminal = client.get('/api/kept-workflow/state').json()
        assert terminal['phase'] == 'completed'
        observed, = terminal['batch']['results']
        assert observed['paper_id'] == str(values[0].id)
        assert observed['outcome'] == 'skipped' and observed['reason_code'] == 'service_unprepared'
        assert state(tmp_path / 'workspace' / 'Papers' / 'a.md').status.value == 'kept'
