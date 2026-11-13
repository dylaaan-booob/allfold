"""Background access captures only the Service and Provider authority it uses."""
from dataclasses import replace

import pytest

from allfold.application.task_authority import TaskAuthority
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.coordinators.login import LoginCoordinator
from allfold.integrations.openalex_credentials import write_credential
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from test_login import login_fixture, Native, opened


def test_api_authority_ignores_unrelated_inputs_and_provider_credentials(tmp_path):
    config = tmp_path / 'config.yaml'
    config.write_text('keyword_expression: first\n')
    pubmed = TaskAuthority.capture(config, None, None, ('pubmed',))
    crossref = TaskAuthority.capture(config, None, None, ('crossref',))
    config.write_text('keyword_expression: changed\n')
    write_credential(config, action='replace', key='synthetic-openalex', revision='missing')
    pubmed.verify()
    crossref.verify()
    write_credential(config, provider='pubmed', action='replace', key='synthetic-pubmed', revision='missing')
    with pytest.raises(ContentChangedError):
        pubmed.verify()
    crossref.verify()
    assert 'synthetic-pubmed' not in repr(pubmed)


@pytest.mark.parametrize('revoke', ['service', 'page', 'credential'])
def test_prepared_service_authority_is_narrow_and_retired_context_never_renews(tmp_path, revoke):
    config, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    service, other = services[-1], services[0]
    login.start(config, manual_service_id=service.id)
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result(opened(17))
    login.join()
    authority = TaskAuthority.capture(config, login, service.id, ())
    assert authority.service_scope.endswith(':' + service.id)
    config.write_text(config.read_text().replace('causal', 'changed'))
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, access_services=tuple(
        item.model_copy(update={'name': 'Unrelated renamed Service'}) if item.id == other.id else item
        for item in saved.state.access_services)), saved.revision)
    authority.verify()
    if revoke == 'service':
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state, access_services=tuple(
            item.model_copy(update={'access_url': 'https://changed.example/'}) if item.id == service.id else item
            for item in saved.state.access_services)), saved.revision)
    elif revoke == 'page':
        login.invalidate_pages([17])
    else:
        login.invalidate_credentials()
    with pytest.raises((ContentChangedError, ValueError)):
        authority.verify()


def test_unprepared_or_unsaved_service_is_not_background_authority(tmp_path):
    config, services = login_fixture(tmp_path, count=2)
    login = LoginCoordinator(Native(), BrowserTaskLock())
    with pytest.raises(ValueError, match='prepared'):
        TaskAuthority.capture(config, login, services[-1].id, ())
    with pytest.raises(ValueError, match='saved'):
        TaskAuthority.capture(config, login, 'svc_' + '0' * 32, ())


def test_native_projection_uses_original_prepared_scope_and_never_loads_public_config(tmp_path):
    # API/public work has no unrelated saved-Service configuration requirement.
    public = TaskAuthority.capture(tmp_path / 'missing.yaml', None, None, ())
    assert public.native_access().payload() == {}
    config, services = login_fixture(tmp_path, count=2)
    native, lock = Native(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    service = services[-1]
    login.start(config, manual_service_id=service.id)
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result(opened(17))
    login.join()
    authority = TaskAuthority.capture(config, login, service.id, ())
    payload = authority.native_access().payload()
    assert payload['service_id'] == service.id
    assert payload['target_page_id'] == 17
    assert len(payload['preparation_key']) == 64
    assert set(payload['service_scope']) == {'scope_id', 'config_revision', 'user_state_revision'}
    payload['service_scope']['scope_id'] = 'changed'
    assert authority.native_access().payload()['service_scope']['scope_id'] != 'changed'
    login.invalidate_pages([17])
    with pytest.raises(ContentChangedError):
        authority.verify()
    assert authority.native_access().payload()['target_page_id'] == 17
