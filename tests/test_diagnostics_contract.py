"""Actual Node producer → Python export, using disposable evidence only."""
from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

from allfold.browser_diagnostics import normalize_browser_diagnostic
from allfold.diagnostics import DiagnosticStore


def test_collection_event_preserves_bounded_attempt_identity_in_export(tmp_path):
    from uuid import uuid4
    store = DiagnosticStore(tmp_path / 'synthetic.yaml', root=tmp_path / 'logs')
    workspace_id, paper_id = str(uuid4()), str(uuid4())
    assert store.event('workflow_started', dict(kind='collection', stage='collection',
        workflow_id='collection_1', task_id='attempt_1', workspace_id=workspace_id,
        paper_id=paper_id, attempt=3, collection_status='queued', html='PRIVATE_BODY'))
    with zipfile.ZipFile(io.BytesIO(store.export())) as archive:
        events = [json.loads(line) for line in archive.read('events.jsonl').splitlines()]
    event = next(item for item in events if item.get('task_id') == 'attempt_1')
    assert event['kind'] == event['stage'] == 'collection'
    assert event['workspace_id'] == workspace_id
    assert event['paper_id'] == paper_id and event['attempt'] == 3
    assert event['collection_status'] == 'queued'
    assert 'PRIVATE_BODY' not in json.dumps(events)


def test_non_ascii_csrf_is_rejected_without_running_export_or_reset(tmp_path):
    from electron_test_helpers import OfflineBridge
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app

    config = tmp_path / 'synthetic.yaml'
    config.write_text('keyword_expression: synthetic\n')
    application = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(application, base_url='http://127.0.0.1') as client:
        exported = client.post('/api/diagnostics/export', json={'csrf_token': '无效'})
        reset = client.post('/settings/logs-reset', data={'csrf_token': '无效'})
    assert exported.status_code == reset.status_code == 403


@pytest.mark.parametrize('scope', ['workspace', 'logs'])
def test_non_ascii_reset_confirmation_preserves_both_stores(tmp_path, scope):
    from electron_test_helpers import OfflineBridge
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app

    config = tmp_path / 'synthetic.yaml'
    config.write_text('name: Synthetic\nvenue_whitelist: list.md\nkeyword_expression: synthetic\n'
                      'output_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-01\nlog_level: INFO\n')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    paper = workspace / 'synthetic.md'
    paper.write_text('protected synthetic Paper')
    application = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    application.state.diagnostics.begin('run', 'protected_task', provider='crossref')
    application.state.diagnostics.finish('protected_task', 'completed')
    with TestClient(application, base_url='http://127.0.0.1') as client:
        preview = client.get('/api/ui-next/settings/reset-preview', params={'scope': scope}).json()
        assert preview['reset_token'], preview['reset_error']
        response = client.post(f'/settings/{scope}-reset', data={
            'csrf_token': application.state.csrf_token, 'reset_token': '无效',
        })
    assert response.status_code == 409
    assert paper.read_text() == 'protected synthetic Paper'
    assert application.state.diagnostics.history()['records'][0]['task_id'] == 'protected_task'


@pytest.mark.parametrize('override', [None, 'ERROR'])
def test_settings_reports_active_level_and_saved_changes_take_effect_after_restart(tmp_path, monkeypatch, override):
    from electron_test_helpers import OfflineBridge
    from fastapi.testclient import TestClient
    from safety_config_helpers import current_mapping_document
    from settings_api_helpers import form
    from allfold.web.app import create_app

    monkeypatch.delenv('ALLFOLD_LOG_LEVEL', raising=False)
    if override:
        monkeypatch.setenv('ALLFOLD_LOG_LEVEL', override)
    config, *_ = current_mapping_document(tmp_path)
    application = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(application, base_url='http://127.0.0.1') as client:
        state = client.get('/api/ui-next/settings').json()
        assert state['logging']['effective_level'] == ('error' if override else 'info')
        submitted = form(state)
        submitted['log_level'] = 'WARNING'
        saved = client.post('/settings/save', data=submitted).json()
        assert saved['saved']
        assert saved['values']['log_level'] == 'WARNING'
        assert saved['logging'] == {'effective_level': 'error' if override else 'info',
                                    'environment_override': bool(override), 'restart_required': True}
    restarted = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    assert restarted.state.diagnostics.level == ('error' if override else 'warn')


def test_native_evidence_survives_restart_and_export_filters_exact_scope_and_workflow(tmp_path):
    config = tmp_path / 'synthetic.yaml'
    config.write_text('keyword_expression: synthetic\n')
    root = tmp_path / 'logs'
    store = DiagnosticStore(config, root=root, runtime_id='runtime_original')
    store.begin('prepare', 'batch_1', workflow_id='workflow_1')
    store.finish('batch_1', 'uncertain', statistics={'uncertain': 1},
                 details={'parent_outcome': 'uncertain', 'pdf_outcome': 'unverified'})
    script = r'''
const {createLogger}=require(process.argv[1]);
const root=process.argv[2],scopeId=process.argv[3];
const logger=createLogger({root,scopeId,runtimeId:'runtime_original',level:'error',stderr(){}});
logger.log('info','task_finished',{workflow_id:'workflow_1',task_id:'batch_1',
  request_id:'native_1',action:'prepare_service',page_id:7,source_page_id:3,
  service_id:'svc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',stage:'attachment',step:'hidden_iframe',
  code:'load_failed',net_error:'ERR_CONNECTION_RESET',status:503,parent:'uncertain',pdf:'unverified',
  host:'private.invalid',body:'PRIVATE_SENTINEL',url:'https://private.invalid/?token=PRIVATE_SENTINEL'});
logger.log('warn','task_finished',{workflow_id:'workflow_1',task_id:'batch_1',
  request_id:'imperva_request',action:'prepare_service',stage:'navigation',
  code:'site_restricted',status:200,imperva_edet:15,imperva_incident_id:'123-456'});
logger.log('error','task_finished',{workflow_id:'workflow_2',task_id:'batch_2',
  request_id:'unrelated_request',action:'prepare_service',parent:'confirmed'});
const other=createLogger({root,scopeId:'b'.repeat(64),runtimeId:'other_runtime',stderr(){}});
other.log('error','task_finished',{workflow_id:'workflow_1',task_id:'batch_1',
  request_id:'other_scope_request',action:'prepare_service',parent:'confirmed'});
'''
    module = Path(__file__).resolve().parents[1] / 'electron/src/shared/logging.cjs'
    subprocess.run(['node', '-e', script, str(module), str(root), store.scope_id], check=True)
    reopened = DiagnosticStore(config, root=root, runtime_id='runtime_restarted')
    with zipfile.ZipFile(io.BytesIO(reopened.export('batch_1'))) as bundle:
        assert {'manifest.json', 'summary.json', 'events.jsonl', 'README.md'} <= set(bundle.namelist())
        events = [json.loads(line) for line in bundle.read('events.jsonl').splitlines()]
        assert events == sorted(events, key=lambda event: event['time'])
        native = next(event for event in events if event.get('request_id') == 'native_1')
        assert {key: native[key] for key in ('page_id', 'source_page_id', 'stage', 'step',
                'code', 'net_error', 'status', 'parent', 'pdf')} == {
            'page_id': 7, 'source_page_id': 3, 'stage': 'attachment', 'step': 'hidden_iframe',
            'code': 'load_failed', 'net_error': 'ERR_CONNECTION_RESET', 'status': 503,
            'parent': 'uncertain', 'pdf': 'unverified',
        }
        assert native['service_id'] == 'svc_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        assert native['workflow_id'] == 'workflow_1'
        assert native['task_id'] == 'batch_1'
        blocked = next(event for event in events if event.get('request_id') == 'imperva_request')
        assert normalize_browser_diagnostic(blocked) == {
            'stage': 'navigation', 'code': 'site_restricted', 'status': 200,
            'imperva_edet': 15, 'imperva_incident_id': '123-456',
        }
        assert blocked['time'].endswith('Z')
        encoded = b'\n'.join(bundle.read(name) for name in bundle.namelist())
        for excluded in (b'unrelated_request', b'other_scope_request', b'PRIVATE_SENTINEL', b'private.invalid'):
            assert excluded not in encoded


def test_recovery_events_and_summary_survive_cross_runtime_export(tmp_path):
    from allfold.recovery_diagnostics import normalize_recovery

    config = tmp_path / 'fixture.yaml'
    config.write_text('keyword_expression: fixture\n')
    root = tmp_path / 'logs'
    store = DiagnosticStore(config, root=root, runtime_id='fixture')
    store.begin('login', 'workflow')
    module = Path(__file__).resolve().parents[1] / 'electron/src/shared'
    script = r'''
const {initializeLogging,log,withLogContext}=require(process.argv[1]+'/logging.cjs');
const {invocationRecovery}=require(process.argv[1]+'/recovery-summary.cjs');
initializeLogging({root:process.argv[2],scopeId:process.argv[3],runtimeId:'fixture',level:'error',stderr(){}});
const recovery=invocationRecovery();
withLogContext({workflow_id:'workflow',task_id:'prepare',request_id:'native',action:'prepare_service'},()=>{
  log('info','page_load_recovery',{page_id:7,attempt:1,generation:1});
  const details={recovery_action:'resource_reentry',stage:'preparation',attempt:1,attempt_limit:1};
  recovery.record('recovery_scheduled',{...details,code:'load_failed',net_code:-100,
    net_error:'ERR_CONNECTION_CLOSED',source_page_id:7,failure_kind:'transport',dispatch_outcome:'confirmed',
    wait_ms:300,remaining_ms:4000,url:'https://PRIVATE_SENTINEL'});
  recovery.record('recovery_succeeded',{...details,source_page_id:7,page_id:9});
  log('info','recovery_scheduled',{...details,recovery_action:'PRIVATE_SENTINEL'});
});
process.stdout.write(JSON.stringify(recovery.summary()));
'''
    native = subprocess.check_output(['node', '-e', script, str(module), str(root), store.scope_id])
    recovery = normalize_recovery(json.loads(native))
    assert recovery == [{
        'recovery_action': 'resource_reentry', 'count': 1, 'outcome': 'recovered',
        'first': {'stage': 'preparation', 'code': 'load_failed', 'net_code': -100,
                  'net_error': 'ERR_CONNECTION_CLOSED', 'source_page_id': 7,
                  'failure_kind': 'transport', 'dispatch_outcome': 'confirmed'},
        'last': {'stage': 'preparation', 'source_page_id': 7, 'page_id': 9},
    }]
    assert store.finish('workflow', 'opened', details={'results': [{
        'service_id': 'svc_' + 'a' * 32, 'outcome': 'opened', 'recovery': recovery,
    }]})
    assert not store.finish('workflow', 'failed')
    reopened = DiagnosticStore(config, root=root, runtime_id='reopened')
    assert reopened.history()['records'][0]['details']['results'][0]['recovery'] == recovery
    with zipfile.ZipFile(io.BytesIO(reopened.export('workflow'))) as bundle:
        events = [json.loads(line) for line in bundle.read('events.jsonl').splitlines()]
        native_events = [event for event in events if event.get('request_id') == 'native']
        assert [event['event'] for event in native_events] == [
            'page_load_recovery', 'recovery_scheduled', 'recovery_succeeded',
        ]
        assert native_events[1]['wait_ms'] == 300
        assert native_events[2]['page_id'] == 9
        assert json.loads(bundle.read('manifest.json'))['integrity']['invalid_records'] == 0
        assert b'PRIVATE_SENTINEL' not in bundle.read('events.jsonl')

    from allfold.diagnostics import validate_event
    assert validate_event({**native_events[1], 'recovery_action': {'url': 'https://PRIVATE_SENTINEL'}}) is None
    assert validate_event({**native_events[1], 'event': 'recovery_exhausted'}) is None
    assert 'wait_ms' not in validate_event({**native_events[1], 'wait_ms': True, 'body': 'PRIVATE_SENTINEL'})
