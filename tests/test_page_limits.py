"""Physical page configuration replaces the retired neutral Paper bounds."""
import pytest
from pydantic import ValidationError
from allfold.config import WorkflowConfig


def test_legacy_paper_bounds_do_not_become_physical_limits():
    workflow = WorkflowConfig.model_validate({
        'paper_global_concurrency': 6, 'paper_service_concurrency': 2,
        'prepare_service_concurrency': 3, 'pdf_concurrency': 4})
    assert workflow.managed_page_global_limit == 16
    assert workflow.managed_page_service_limit == 4
    assert workflow.prepare_service_concurrency == 3
    assert workflow.pdf_concurrency == 4
    assert 'paper_global_concurrency' not in workflow.model_dump()
    for field, values in (
        ('managed_page_global_limit', (3, 65, True, '16')),
        ('managed_page_service_limit', (2, 17, True, '4')),
    ):
        for value in values:
            with pytest.raises(ValidationError):
                WorkflowConfig.model_validate({field: value})


def test_page_limit_autosave_preserves_services_and_publishes_one_effective_pair(tmp_path):
    from concurrent.futures import Future
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from safety_config_helpers import current_mapping_document
    from test_settings_autosave import patch_body

    class LimitsBridge(OfflineBridge):
        def __init__(self):
            self.published = []

        def refresh_page_limits(self):
            self.published.append(self.page_limits())
            result = Future()
            result.set_result(None)
            return result

    config, _, _, service = current_mapping_document(tmp_path)
    bridge = LimitsBridge()
    with TestClient(create_app(config, electron_bridge=bridge), base_url='http://localhost') as client:
        opened = client.get('/api/ui-next/settings').json()
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(
            opened, managed_page_global_limit='4', managed_page_service_limit='3')).json()
        assert saved['saved']
        assert saved['values']['access_services'] == opened['values']['access_services']
        assert saved['values']['access_services'][0]['id'] == service.id
        assert bridge.published == [{'global_limit': 4, 'service_limit': 3}]
        refused = client.post('/api/ui-next/settings/autosave', json=patch_body(
            saved, managed_page_global_limit='3')).json()
        assert refused['outcome'] == 'INVALID_DRAFT'
        assert bridge.published == [{'global_limit': 4, 'service_limit': 3}]
        actual = client.get('/api/ui-next/settings').json()
        assert actual['values']['managed_page_global_limit'] == '4'
        assert actual['values']['managed_page_service_limit'] == '3'
