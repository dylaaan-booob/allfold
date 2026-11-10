"""Public API regression for configuration admission and immutable Kept batches."""
from concurrent.futures import Future
import threading

import pytest
from fastapi.testclient import TestClient

from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge, edit, paper
from test_electron_import import confirmed
from test_kept_scope import scoped_workspace
from test_login import opened
from test_settings_autosave import patch_body


@pytest.mark.parametrize('external_change', [False, True], ids=['save-after-release', 'conflict-after-release'])
def test_import_pins_settings_and_revalidates_pending_changes_after_release(tmp_path, external_change):
    config, service, other, original = scoped_workspace(tmp_path)
    config.write_text(config.read_text().replace('kept_workflow:\n',
        'kept_workflow:\n  translator_concurrency: 3\n  paper_global_concurrency: 4\n'))

    class Bridge(OfflineBridge):
        connected = True
        def __init__(self):
            self.calls, self.dispatched, self.future = [], threading.Event(), Future()

        def execute(self, action, data, progress=None, *, verify_recovery=None):
            if action == 'import_paper':
                self.calls.append(data)
                self.dispatched.set()
                return self.future
            result = Future()
            if action == 'visit_manual_service':
                result.set_result(opened(18))
            else:
                assert action == 'zotero_local'
                result.set_result({'ok': True})
            return result

        def finish_disconnected(self):
            if not self.future.done():
                self.future.set_result({'settled': True, 'parent': {'outcome': 'uncertain'}})

    bridge = Bridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        settings = client.get('/api/ui-next/settings').json()
        disk_before = config.read_bytes()
        csrf = settings['csrf_token']
        assert client.post('/api/login/start', json={'csrf_token': csrf, 'service_id': other.id}).status_code == 200
        app.state.login.join()

        queue = client.get('/api/kept-workflow/queue', params={'service_id': other.id}).json()
        started = client.post('/api/kept-workflow/start', json={'csrf_token': csrf,
            'service_id': other.id, 'import_token': queue['import_token']})
        assert started.status_code == 200 and bridge.dispatched.wait(2)
        running = started.json()
        assert running['phase'] == 'importing' and running['can_cancel']
        assert running['service_id'] == other.id and running['planned_total'] == 1
        retained = patch_body(settings, translator_concurrency='4')
        pending = client.post('/api/ui-next/settings/autosave', json=retained).json()
        assert pending['outcome'] == 'TASK_ACTIVE' and not pending['saved']
        assert pending['values']['monitor_revision_digest'] == settings['values']['monitor_revision_digest']
        assert config.read_bytes() == disk_before

        # Queue selections and externally added Papers cannot enlarge a fixed plan.
        _, late = paper(tmp_path / 'workspace', 'added-during-import')
        edit(late, journal_issns=['0090-5364'])
        other_queue = client.get('/api/kept-workflow/queue', params={'service_id': service.id})
        assert other_queue.status_code == 200
        conflict = client.post('/api/kept-workflow/start', json={'csrf_token': csrf,
            'service_id': service.id, 'import_token': other_queue.json()['import_token']})
        assert conflict.status_code == 409
        assert conflict.json()['workflow_id'] == running['workflow_id']
        assert [(data['paper_id'], data['service_id']) for data in bridge.calls] == [(str(original[1].id), other.id)]
        assert bridge.calls[0]['limits']['translator'] == 3
        assert bridge.calls[0]['zotero_target'] == settings['values']['zotero_target']
        assert bridge.calls[0]['service_scope']['config_revision'] == settings['values']['monitor_revision_digest']

        bridge.future.set_result(confirmed())
        app.state.kept_workflow.join()
        terminal = client.get('/api/kept-workflow/state').json()
        assert terminal['workflow_id'] == running['workflow_id'] and terminal['generation'] == running['generation']
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
            assert retried['values']['translator_concurrency'] == '3'
        else:
            assert retried['saved'] and retried['outcome'] == 'SAVED'
            assert retried['values']['translator_concurrency'] == '4'
            assert retried['values']['monitor_revision_digest'] != settings['values']['monitor_revision_digest']
