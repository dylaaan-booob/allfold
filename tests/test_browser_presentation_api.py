"""Read-only saved Service labels for the trusted Browser Workbench."""
from fastapi.testclient import TestClient

from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from safety_config_helpers import current_mapping_document


def test_browser_services_project_only_saved_identity_and_navigation_metadata(tmp_path):
    config, _, _, service = current_mapping_document(tmp_path)
    snapshot = BrowserServiceSnapshot.read(config)
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        response = client.get('/api/ui-next/browser-services')
    assert response.status_code == 200
    assert response.json() == {
        'scope': snapshot.scope,
        'services': [{'id': service.id, 'name': service.name,
                      'access_method': service.access_method, 'access_url': service.access_url}],
    }
    assert response.headers['cache-control'] == 'no-store'
    assert all(path.read_bytes() == content for path, content in before.items())
