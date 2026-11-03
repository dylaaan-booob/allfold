"""Coordinator observations through isolated stores and synthetic native transports."""
from allfold.diagnostics import DiagnosticStore
from allfold.browser_diagnostics import normalize_browser_diagnostic, format_browser_diagnostic
from allfold.application.batch_import import BatchImportService
from allfold.application.browser_runtime import BrowserTaskLock
from electron_test_helpers import paper
from test_electron_import import Bridge, confirmed
import pytest


def test_attachment_diagnostic_preserves_cross_runtime_evidence():
    value = dict(stage='attachment', step='hidden_iframe', code='timeout', net_error='ERR_ABORTED', status=403, message='secret')
    assert normalize_browser_diagnostic(value) == {k: value[k] for k in ('stage', 'step', 'code', 'net_error', 'status')}
    assert 'Attachment' in format_browser_diagnostic(value)


@pytest.mark.parametrize('result,outcome', [(confirmed(), 'confirmed'),
    ({'settled': True, 'parent': {'outcome': 'uncertain'}}, 'uncertain'),
    ({'settled': True, 'parent': {'outcome': 'no_effect'}}, 'partial')])
def test_import_history_waits_for_settlement_and_preserves_parent_pdf(tmp_path, result, outcome):
    value, _ = paper(tmp_path / 'workspace', 'fixture')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    lock, bridge = BrowserTaskLock(), Bridge()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=owner, workflow_id='workflow', parent_task_id='workflow')
    assert bridge.dispatched.wait(2)
    record = store.history()['records'][0]
    assert record['outcome'] == 'running'
    action, data = bridge.calls[0]
    assert data['workflow_id'] == 'workflow'
    assert data['parent_task_id'] == record['task_id']
    assert data['task_id'] != owner.id
    assert data['paper_id'] == str(value.id)
    bridge.future.set_result(result)
    batch.join()
    record = store.history()['records'][0]
    assert record['outcome'] == outcome
    item = record['details']['results'][0]
    assert item['parent_outcome'] == result['parent']['outcome']
    assert item['pdf_outcome'] == 'unverified'
    assert record['statistics']['confirmed'] == (outcome == 'confirmed')
    lock.release(owner)


def test_bridge_logs_actual_envelope_and_safe_native_result(tmp_path):
    import json, zipfile, io
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from allfold.web.electron_bridge import ElectronBridge
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', level='error')
    store.begin('enrich', 'business', workflow_id='workflow')
    bridge = ElectronBridge('secret', 'testserver', diagnostics=store)
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as socket:
            socket.send_json({'token':'secret'})
            assert socket.receive_json() == {'type':'ready', 'log_level':'error'}
            pending = bridge.execute('enrich_paper', {'task_id':'business', 'workflow_id':'workflow', 'doi':'10.5555/secret'})
            envelope = socket.receive_json()
            assert envelope['id'] != 'business'
            assert envelope['data']['log_level'] == 'error'
            result = {'diagnostic':{'stage':'attachment','step':'hidden_iframe','code':'timeout','net_error':'ERR_ABORTED'},
                'diagnostics_status':{'available':True, 'incomplete':False, 'rotations':0,'write_failures':0,'omitted':0}, 'item':{'title':'SECRET TITLE'}}
            socket.send_json({'type':'result','id':envelope['id'],'action':envelope['action'],'data':result})
            assert pending.result(2) == result
    payload = store.export('business')
    events = [json.loads(line) for line in zipfile.ZipFile(io.BytesIO(payload)).read('events.jsonl').splitlines()]
    correlated = [e for e in events if e.get('request_id') == envelope['id']]
    assert [e['event'] for e in correlated] == ['task_started', 'task_finished']
    assert all(e['task_id'] == 'business' and e['workflow_id'] == 'workflow' for e in correlated)
    assert correlated[-1]['stage'] == 'attachment'
    assert correlated[-1]['net_error'] == 'ERR_ABORTED'
    assert 'SECRET TITLE' not in json.dumps(events)
    assert '10.5555/secret' not in json.dumps(events)


def test_enrich_history_confirms_only_saved_fields_and_exact_task(tmp_path):
    from test_paper_enrichment import missing
    from electron_test_helpers import PendingBridge, state
    from allfold.application.coordinators.paper_enrichment import PaperEnrichment
    paper_id, path = missing(tmp_path / 'workspace')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    enrich = PaperEnrichment(bridge, lock, diagnostics=store)
    started = enrich.start(tmp_path / 'workspace', paper_id)
    assert bridge.dispatched.wait(2)
    data = bridge.calls[0][1]
    assert data['task_id'] == started['request_id']
    assert data['workflow_id'] == started['request_id']
    assert data['paper_id'] == str(paper_id)
    assert store.history()['records'][0]['outcome'] == 'running'
    bridge.future.set_result({'item': {'DOI':bridge.calls[0][1]['doi'], 'itemType':'journalArticle', 'abstractNote':'Sensitive research'}})
    enrich.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'completed'
    assert record['details']['saved_fields'] == ['abstract']
    assert record['details']['requested_fields'] == ['abstract']
    assert record['details']['sync_warning'] is False
    assert 'Sensitive research' not in str(record)


def test_run_history_uses_retrieval_coverage_instead_of_last_stage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from allfold.application.coordinators.run_coordinator import RunCoordinator
    from allfold.application.run_state import RunProvider
    from test_web_app import write_valid_config
    from allfold.application.monitor import RunResult, RunOutcome, MonitorStatistics
    from allfold.application.run_state import RunFacts
    config, _ = write_valid_config(tmp_path)
    result = RunResult(provider=RunProvider.OPENALEX, resolved_date_range=None, canonical_paper_count=3,
        created_papers=2, matched_existing_papers=1, warnings=(), errors=(), outcome=RunOutcome.COMPLETED,
        statistics=MonitorStatistics(openalex_records=3), facts=RunFacts(created_papers=2,existing_papers=1),
        coverage=({'status':'PARTIAL'},))
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', lambda *a, **k: result)
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    coordinator = RunCoordinator(config, diagnostics=store)
    coordinator.start(RunProvider.OPENALEX)
    coordinator._worker.join(2)
    record = store.history()['records'][0]
    assert record['outcome'] == 'partial'
    assert record['details']['result_status'] == 'incomplete'
    assert record['details']['coverage_status'] == 'partial'
    assert record['statistics']['created'] == 2


@pytest.mark.parametrize('observed,expected', [(True,'opened'), (False,'needs_attention')])
def test_prepare_history_requires_observed_target_evidence(tmp_path, observed, expected):
    from safety_config_helpers import current_mapping_document
    from allfold.application.coordinators.preparation_coordinator import PreparationCoordinator
    from allfold.config import load_config
    from allfold.persistence.user_state import load_user_state
    from electron_test_helpers import PendingBridge
    config, _, _, service = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + 'institution:\n  name: Fixture University\n')
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    prep = PreparationCoordinator(bridge, lock, diagnostics=store)
    started = prep.start(config, service=service, workflow_id='root', parent_task_id='root')
    assert bridge.dispatched.wait(2)
    assert bridge.calls[0][1]['workflow_id'] == 'root'
    bridge.future.set_result({'outcome':'Opened','evidence':{'visit_action_observed':observed,
        'navigation_observed':True, 'target_page_id':17}})
    prep.join()
    record = store.history()['records'][0]
    assert record['task_id'] == started.task_id
    assert record['outcome'] == expected
    assert record['details']['results'][0]['outcome'] == expected


def test_cover_history_does_not_confirm_invalid_native_image(tmp_path):
    from safety_config_helpers import current_mapping_document
    from allfold.application.coordinators.journal_covers import JournalCoverSearch
    from electron_test_helpers import PendingBridge
    config, legacy, journal, _ = current_mapping_document(tmp_path)
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    covers = JournalCoverSearch(bridge, lock, diagnostics=store)
    started = covers.start(legacy, (journal,), journal.key, config_path=config)
    assert bridge.dispatched.wait(2)
    assert bridge.calls[0][1]['task_id'] == started['request_id']
    bridge.future.set_result({'image_base64':'not-valid-image', 'source_url':'https://example.org/cover.png'})
    covers.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'failed'
    assert record['statistics']['downloaded'] == 0
    assert lock.owner is None


def test_kept_root_aggregates_batch_partial_without_claiming_success(tmp_path):
    from types import SimpleNamespace
    import threading
    from allfold.application.coordinators.kept_workflow import KeptWorkflow
    from allfold.config import KeptWorkflowConfig
    paper(tmp_path / 'workspace', 'fixture')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = Bridge(), BrowserTaskLock()
    batch = BatchImportService(bridge, lock, diagnostics=store)
    def begin(target, authorization, **context):
        return batch.start(target.workspace, browser_owner=flow.browser_owner, **context)
    flow = KeptWorkflow(None, batch, threading.RLock(), begin_import=begin,
        has_kept=lambda target:True, browser_lock=lock, diagnostics=store)
    started = flow.start(SimpleNamespace(workspace=tmp_path / 'workspace'),
        SimpleNamespace(kept_workflow=KeptWorkflowConfig(), institution=None), 'grant', mode='import_only')
    assert bridge.dispatched.wait(2)
    bridge.future.set_result({'settled':True,'parent':{'outcome':'no_effect'}})
    batch.join()
    flow.advance()
    records = store.history()['records']
    root = next(r for r in records if r['kind'] == 'kept')
    imported = next(r for r in records if r['kind'] == 'import')
    assert root['task_id'] == root['workflow_id'] == started.workflow_id
    assert root['outcome'] == 'partial'
    assert root['statistics']['no_effect'] == 1
    assert imported['parent_task_id'] == root['task_id']
    assert imported['workflow_id'] == root['workflow_id']
    assert lock.owner is None


def test_history_keeps_accepted_parent_distinct_from_conflicted_paper(tmp_path):
    from electron_test_helpers import edit
    _, path = paper(tmp_path / 'workspace', 'fixture')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=owner)
    assert bridge.dispatched.wait(2)
    edit(path, title='Human edit')
    bridge.future.set_result(confirmed())
    batch.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'partial'
    assert record['statistics']['confirmed'] == 1
    assert record['statistics']['exported'] == 0
    assert record['details']['results'][0]['parent_outcome'] == 'confirmed'
    assert record['details']['results'][0]['reason'] == 'write_failed'
    lock.release(owner)


def test_unexpected_native_future_failure_is_unconfirmed_not_failed_save(tmp_path):
    paper(tmp_path / 'workspace', 'fixture')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=owner)
    assert bridge.dispatched.wait(2)
    bridge.future.set_exception(RuntimeError('do not persist this secret'))
    batch.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'uncertain'
    assert record['details']['results'][0]['parent_outcome'] == 'uncertain'
    assert 'secret' not in str(record)
    lock.release(owner)


def test_diagnostic_failure_does_not_change_confirmed_import_or_ownership(tmp_path):
    from electron_test_helpers import state
    class FailedDiagnostics:
        def begin(self, *args, **kwargs):
            raise OSError('read-only diagnostics')
        finish = begin
    _, path = paper(tmp_path / 'workspace', 'fixture')
    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=FailedDiagnostics())
    batch.start(tmp_path / 'workspace', browser_owner=owner)
    assert bridge.dispatched.wait(2)
    bridge.future.set_result(confirmed())
    batch.join()
    assert state(path).status.value == 'exported'
    assert batch.snapshot().successful
    assert lock.owner is owner
    lock.release(owner)


def test_cancelled_import_history_retains_settled_save_and_remaining_count(tmp_path):
    paper(tmp_path / 'workspace', 'a')
    paper(tmp_path / 'workspace', 'b')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=owner)
    assert bridge.dispatched.wait(2)
    batch.stop()
    assert store.history()['records'][0]['outcome'] == 'running'
    bridge.future.set_result(confirmed())
    batch.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'cancelled'
    assert record['statistics']['confirmed'] == 1
    assert record['statistics']['skipped'] == 1
    assert len(bridge.calls) == 1
    lock.release(owner)


def test_native_reset_control_does_not_mutate_python_preview_identity(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from allfold.web.electron_bridge import ElectronBridge
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge = ElectronBridge('secret', 'testserver', diagnostics=store)
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as socket:
            socket.send_json({'token':'secret'})
            socket.receive_json()
            plan = store.preview_reset()
            pending = bridge.execute('diagnostics_reset', {'operation':'preview','scope_id':store.scope_id})
            envelope = socket.receive_json()
            socket.send_json({'type':'result','id':envelope['id'],'action':'diagnostics_reset','data':{'scope_id':store.scope_id}})
            assert pending.result(2)['scope_id'] == store.scope_id
            assert store.reset(plan)['success'] is True


def test_enrich_disconnect_is_interrupted_history_and_never_saved(tmp_path):
    from test_paper_enrichment import missing
    from electron_test_helpers import PendingBridge
    from allfold.application.coordinators.paper_enrichment import PaperEnrichment
    from allfold.application.browser_runtime import ElectronDisconnected
    paper_id, path = missing(tmp_path / 'workspace')
    original = path.read_bytes()
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    enrich = PaperEnrichment(bridge, lock, diagnostics=store)
    enrich.start(tmp_path / 'workspace', paper_id)
    assert bridge.dispatched.wait(2)
    bridge.future.set_exception(ElectronDisconnected('connection gone'))
    enrich.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'interrupted'
    assert record['details']['reason'] == 'connection_lost'
    assert record['details']['saved_fields'] == []
    assert path.read_bytes() == original


def test_app_composition_keeps_workflow_ids_through_import_and_http_export(tmp_path):
    import zipfile, io, json
    from test_web_app import write_valid_config
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from allfold.application.import_target import _ImportTarget
    config, workspace = write_valid_config(tmp_path)
    paper(workspace, 'fixture')
    bridge = Bridge()
    # Full app shutdown also calls the browser workers' cancellation seam.
    bridge.closing = False
    bridge.finish_disconnected = lambda:None
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        target, loaded = _ImportTarget.read(config)
        started = app.state.kept_workflow.start(target, loaded, app.state.import_token, mode='import_only')
        assert bridge.dispatched.wait(2)
        assert bridge.calls[0][1]['workflow_id'] == started.workflow_id
        bridge.future.set_result(confirmed())
        app.state.batch_import.join()
        app.state.kept_workflow.advance()
        records = client.get('/api/history').json()['records']
        root = next(r for r in records if r['kind'] == 'kept')
        assert root['task_id'] == started.workflow_id
        assert root['outcome'] == 'completed'
        response = client.post('/api/diagnostics/export', json={'csrf_token':app.state.csrf_token, 'task_id':root['task_id']})
        assert response.status_code == 200
        summary = json.loads(zipfile.ZipFile(io.BytesIO(response.content)).read('summary.json'))
        assert len(summary['records']) == 2
        assert {r['workflow_id'] for r in summary['records']} == {root['workflow_id']}


def test_import_history_keeps_reviewed_attachment_failure_without_unconfirming_parent(tmp_path):
    paper(tmp_path / 'workspace', 'fixture')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock, diagnostics=store)
    batch.start(tmp_path / 'workspace', browser_owner=owner)
    assert bridge.dispatched.wait(2)
    result = confirmed()
    result['pdf']['failures'] = [{'phase':'initial_fetch','code':'http_error','status':403,
        'url':'https://example.org/?secret=token','message':'sensitive body'}]
    bridge.future.set_result(result)
    batch.join()
    record = store.history()['records'][0]
    assert record['outcome'] == 'confirmed'
    assert record['details']['results'][0]['diagnostic'] == {'stage':'attachment','code':'http_error','status':403}
    assert record['statistics']['warnings'] == 1
    assert record['details']['pdf_outcome'] == 'unverified'
    assert 'sensitive body' not in str(record)
    assert 'secret=token' not in str(record)
    lock.release(owner)
