"""Coordinator observations through isolated stores and synthetic native transports."""
from allfold.diagnostics import DiagnosticStore
from allfold.browser_diagnostics import normalize_browser_diagnostic, format_browser_diagnostic
from allfold.application.browser_runtime import BrowserTaskLock
import pytest


def test_attachment_diagnostic_preserves_cross_runtime_evidence():
    value = dict(stage='attachment', step='hidden_iframe', code='timeout', net_error='ERR_ABORTED', status=403, message='secret')
    assert normalize_browser_diagnostic(value) == {k: value[k] for k in ('stage', 'step', 'code', 'net_error', 'status')}
    assert '附件操作超时' in format_browser_diagnostic(value)




@pytest.mark.parametrize('available', [True, False])
def test_authenticated_handshake_reports_native_health_before_any_task(tmp_path, available):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from allfold.web.electron_bridge import ElectronBridge
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    bridge = ElectronBridge('secret', 'testserver', diagnostics=store)
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    app.get('/history')(store.history)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as socket:
            socket.send_json({'token': 'secret', 'diagnostics_status': {
                'available': available, 'incomplete': not available,
                'rotations': 0, 'write_failures': 0 if available else 1, 'omitted': 0,
                'message': 'PRIVATE_SENTINEL',
            }})
            assert socket.receive_json()['type'] == 'ready'
            history = client.get('/history').json()
            assert history['records'] == []
            native = history['integrity']['native']
            assert native['status_known'] is True
            assert native['available'] is available
            assert native['incomplete'] is not available
            assert 'PRIVATE_SENTINEL' not in str(history)


def test_invalid_handshake_cannot_replace_known_native_health(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from allfold.web.electron_bridge import ElectronBridge
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    store.native_status({'available': False, 'incomplete': True, 'write_failures': 1})
    bridge = ElectronBridge('secret', 'testserver', diagnostics=store)
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as socket:
            socket.send_json({'token': 'wrong', 'diagnostics_status': {'available': True, 'incomplete': False}})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()
    assert store.history()['integrity']['native']['available'] is False
    assert store.history()['integrity']['native']['write_failures'] == 1


def test_bridge_logs_actual_envelope_and_safe_native_result(tmp_path):
    import json, zipfile, io
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from allfold.web.electron_bridge import ElectronBridge
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', level='error')
    store.begin('prepare', 'business', workflow_id='workflow')
    bridge = ElectronBridge('secret', 'testserver', diagnostics=store)
    app = FastAPI()
    app.websocket('/ws')(bridge.connect)
    with TestClient(app) as client:
        with client.websocket_connect('/ws') as socket:
            socket.send_json({'token':'secret'})
            assert socket.receive_json() == {'type':'ready', 'log_level':'error'}
            pending = bridge.execute('prepare_service', {'task_id':'business', 'workflow_id':'workflow', 'doi':'10.5555/secret'})
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




def test_run_history_uses_retrieval_coverage_instead_of_last_stage(tmp_path, monkeypatch):
    from allfold.application.coordinators.run_coordinator import RunCoordinator
    from allfold.application.run_state import RunProvider
    from test_web_app import write_valid_config
    from allfold.application.monitor import RunResult, RunOutcome
    from allfold.application.run_state import RunFacts
    config, _ = write_valid_config(tmp_path)
    result = RunResult(provider=RunProvider.INTEGRATED, resolved_date_range=None,
        warnings=(), errors=(), outcome=RunOutcome.COMPLETED,
        facts=RunFacts(created_papers=2, existing_papers=1, statistics={"integrated_candidates": 3},
                       details={"discovery_status": "partial"}))
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', lambda *a, **k: result)
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    coordinator = RunCoordinator(config, diagnostics=store)
    coordinator.start(RunProvider.INTEGRATED)
    coordinator._worker.join(2)
    record = store.history()['records'][0]
    assert record['outcome'] == 'partial'
    assert record['details']['result_status'] == 'incomplete'
    assert record['details']['coverage_status'] == 'partial'
    assert record['statistics']['created'] == 2
    assert record['statistics']['retrieved'] == 3
    assert record['statistics']['unchanged'] == 1


@pytest.mark.parametrize('observed,expected', [(True,'opened'), (False,'needs_attention')])
def test_login_history_requires_observed_target_evidence(tmp_path, observed, expected):
    from safety_config_helpers import current_mapping_document
    from allfold.application.coordinators.login import LoginCoordinator
    from test_login import Native
    config, _, _, service = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + 'institution:\n  name: Fixture University\n')
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    bridge, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(bridge, lock, diagnostics=store)
    started = login.start(config)
    action, _, future = bridge.operations.get(timeout=2)
    assert action == 'login_carsi'
    future.set_result({'outcome': 'Opened', 'portal_page_id': 9})
    action, request, future = bridge.operations.get(timeout=2)
    assert action == 'prepare_service' and request['workflow_id'] == started['workflow_id']
    recovery = [{'recovery_action': 'resource_reentry', 'count': 1, 'outcome': 'recovered',
        'first': {'code': 'load_failed', 'net_code': -100, 'source_page_id': 11},
        'last': {'page_id': 17}}]
    future.set_result({'outcome':'Opened',
        'evidence':{'visit_action_observed':observed, 'navigation_observed':True, 'target_page_id':17},
        'recovery': recovery})
    login.join()
    assert len(store.history()['records']) == 1
    record = store.history()['records'][0]
    assert record['task_id'] == started['workflow_id']
    assert record['outcome'] == expected
    assert record['details']['results'][0]['outcome'] == expected
    assert record['details']['results'][0]['recovery'] == recovery

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







@pytest.mark.parametrize('code,text', [
    ('no_resolver','未找到可用的附件来源'), ('mime_mismatch','返回内容不是预期附件类型'),
    ('empty_response','附件响应为空'), ('network_error','附件网络请求失败'),
    ('redirect_rejected','附件重定向未被接受'), ('attachment_rejected','附件保存请求未被接受'),
    ('timeout','附件操作超时'),
])
def test_attachment_message_describes_problem_and_preserves_pdf_uncertainty(code, text):
    message = format_browser_diagnostic({'stage':'attachment','code':code,'status':403,'net_error':'ERR_ABORTED'})
    assert text in message
    assert 'PDF 是否保存仍未验证' in message
    assert '403' in message and 'ERR_ABORTED' in message
    assert '父条目失败' not in message
    assert '重试' not in message


