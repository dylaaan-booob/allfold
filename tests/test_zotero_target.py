"""The existing configuration transaction owns the default Local API target."""
from fastapi.testclient import TestClient
from allfold.web.app import create_app
from allfold.application.import_target import _ImportTarget
from electron_test_helpers import OfflineBridge
from safety_config_helpers import current_mapping_document
from test_settings_autosave import patch_body

TARGET = {'server_id': 'SERVERFIXTUR', 'library_type': 'group', 'library_id': '12', 'collection_key': 'ABCDEFGH'}

def test_target_uses_normal_autosave_revisions_and_is_frozen_with_import_target(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, zotero_target=TARGET)).json()
        assert saved['saved'] and saved['values']['zotero_target'] == TARGET
        fixed, _ = _ImportTarget.read(config)
        changed = dict(TARGET, library_id='13')
        later = client.post('/api/ui-next/settings/autosave', json=patch_body(saved, zotero_target=changed)).json()
        assert later['saved']
        assert fixed.zotero_target.model_dump() == TARGET
        stale = client.post('/api/ui-next/settings/autosave', json=patch_body(saved, zotero_target=TARGET)).json()
        assert stale['outcome'] == 'REVISION_CONFLICT'

def test_target_rejects_credentials_remote_addresses_and_arbitrary_paths(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        for target in (dict(TARGET, api_key='secret'), dict(TARGET, library_id='../items'), dict(TARGET, collection_key='wrong'), dict(TARGET, server_id='https://remote.example')):
            result = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, zotero_target=target)).json()
            assert not result['saved']
        assert 'secret' not in config.read_text()

def test_local_api_exact_key_receipt_commits_parent_without_claiming_pdf(tmp_path):
    from allfold.application.export_attempts import _reserve_export_attempt_locked, complete_electron_import
    from allfold.persistence.safe_write import workspace_operation_lock
    from electron_test_helpers import paper, state
    value, path = paper(tmp_path, 'local-api')
    result = {'settled': True, 'parent': {'outcome': 'confirmed', 'status': 200,
        'requested_id': 'ABCDEFGH', 'accepted_id': 'ABCDEFGH', 'protocol': 'local-api-v3'},
        'pdf': {'registered': False}}
    with workspace_operation_lock(tmp_path) as lock:
        reservation = _reserve_export_attempt_locked(lock, value.id)
        completion = complete_electron_import(reservation, result, operation_lock=lock)
    assert completion.outcome.value == 'EXPORTED'
    assert state(path).status.value == 'exported'
