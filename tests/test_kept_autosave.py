"""Public API regression for configuration admission and immutable Kept batches."""
from concurrent.futures import Future
from dataclasses import replace
import threading
import time

import pytest
from fastapi.testclient import TestClient

from allfold.models import WorkflowStatus
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge, edit, paper
from test_electron_import import confirmed
from test_kept_scope import scoped_workspace
from test_settings_autosave import patch_body


@pytest.mark.parametrize('external_change', [False, True], ids=['save-after-release', 'conflict-after-release'])
def test_pending_kept_settings_do_not_retarget_continue_and_revalidate_after_release(tmp_path, external_change):
    config, service, other, original = scoped_workspace(tmp_path)
    config.write_text(config.read_text() + 'kept_workflow:\n  display_name: Original Researcher\n'
        '  transition_delay_seconds: 3\n  auto_import_after_preparation: false\n')
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, access_services=(
        service.model_copy(update={'access_method': 'manual'}), other)), saved.revision)
    late, late_path = paper(tmp_path / 'workspace', 'kept-during-wait', status=WorkflowStatus.CANDIDATE)
    edit(late_path, journal_issns=['0006-341X'])

    class Bridge(OfflineBridge):
        connected = True
        def __init__(self):
            self.calls, self.dispatched, self.future = [], threading.Event(), Future()
        def execute(self, action, data, progress=None):
            self.calls.append((action, data))
            self.dispatched.set()
            return self.future
        def finish_disconnected(self):
            if not self.future.done():
                self.future.set_result({'settled': True, 'parent': {'outcome': 'uncertain'}})

    bridge = Bridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        disk_before = config.read_bytes()
        queue = client.get('/api/kept-workflow/queue', params={'service_id': service.id}).json()
        started = client.post('/api/kept-workflow/start', json={'csrf_token': opened['csrf_token'],
            'service_id': service.id, 'import_token': queue['import_token']})
        assert started.status_code == 200
        waiting = started.json()
        assert waiting['phase'] == 'waiting_for_user' and waiting['can_continue']
        assert waiting['service_id'] == service.id and waiting['planned_total'] == 1
        assert [item['id'] for item in waiting['preparation']['manual_services']] == [service.id]
        identity = {'csrf_token': opened['csrf_token'], 'workflow_id': waiting['workflow_id'],
                    'generation': waiting['generation']}
        retained = patch_body(opened, display_name='Edited During Task', transition_delay_seconds='7')
        pending = client.post('/api/ui-next/settings/autosave', json=retained).json()
        assert pending['outcome'] == 'TASK_ACTIVE' and not pending['saved']
        assert pending['values']['monitor_revision_digest'] == opened['values']['monitor_revision_digest']
        assert config.read_bytes() == disk_before

        # Display selection and a newly Kept Paper both remain outside this fixed batch.
        assert client.get('/api/kept-workflow/queue', params={'service_id': other.id}).status_code == 200
        assert client.post(f'/api/ui-next/papers/{late.id}/keep', json={
            'csrf_token': opened['csrf_token'], 'expected_status': 'candidate'}).status_code == 200
        continued = client.post('/api/kept-workflow/continue', json=identity)
        assert continued.status_code == 200 and bridge.dispatched.wait(2)
        importing = client.get('/api/kept-workflow/state').json()
        assert importing['workflow_id'] == identity['workflow_id'] and importing['generation'] == identity['generation']
        assert importing['service_id'] == service.id
        assert importing['settings']['display_name'] == 'Original Researcher'
        assert importing['settings']['transition_delay_seconds'] == 3
        assert [(action, data['paper_id'], data['service_id']) for action, data in bridge.calls] == [
            ('import_paper', str(original[0].id), service.id)]
        assert bridge.calls[0][1]['service_scope']['config_revision'] == opened['values']['monitor_revision_digest']
        assert client.post('/api/ui-next/settings/autosave', json=retained).json()['outcome'] == 'TASK_ACTIVE'
        assert config.read_bytes() == disk_before

        bridge.future.set_result(confirmed())
        deadline = time.monotonic() + 3
        terminal = importing
        while terminal['active'] and time.monotonic() < deadline:
            time.sleep(.01)
            terminal = client.get('/api/kept-workflow/state').json()
        assert terminal['phase'] == 'completed' and not terminal['active']
        assert terminal['batch']['total'] == 1 and terminal['batch']['statistics']['exported_parent'] == 1
        assert len(bridge.calls) == 1
        if external_change:
            config.write_text(config.read_text() + '\n# external configuration revision\n')
            external_bytes = config.read_bytes()
        retried = client.post('/api/ui-next/settings/autosave', json=retained).json()
        if external_change:
            assert retried['outcome'] == 'REVISION_CONFLICT' and not retried['saved']
            assert config.read_bytes() == external_bytes
            assert retried['values']['display_name'] == 'Original Researcher'
        else:
            assert retried['saved'] and retried['outcome'] == 'SAVED'
            assert retried['values']['display_name'] == 'Edited During Task'
            assert float(retried['values']['transition_delay_seconds']) == 7
            assert retried['values']['monitor_revision_digest'] != opened['values']['monitor_revision_digest']
            assert client.get('/api/ui-next/settings').json()['values']['display_name'] == 'Edited During Task'
        assert client.post('/api/kept-workflow/continue', json=identity).status_code == 409
        assert len(bridge.calls) == 1
