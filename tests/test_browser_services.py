"""Invocation-scoped saved identities; no real accounts or Workspace data."""
from dataclasses import replace
import pytest

from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from safety_config_helpers import current_mapping_document




def test_scope_is_canonical_config_specific_and_snapshot_never_hot_migrates(tmp_path):
    config, _, _, service = current_mapping_document(tmp_path)
    first = BrowserServiceSnapshot.read(config)
    assert first.scope == BrowserServiceSnapshot.read(config.parent / '.' / config.name).scope
    other = config.with_name('other.yaml')
    other.write_bytes(config.read_bytes())
    saved = load_user_state(other)
    compare_write_user_state(other, load_user_state(config).state, saved.revision)
    second = BrowserServiceSnapshot.read(other)
    assert first.scope['scope_id'] != second.scope['scope_id']
    assert first.services == second.services == (service,)
    assert str(config) not in repr(first.scope)
    initial = load_user_state(config)
    compare_write_user_state(config, replace(initial.state,
        journals=(initial.state.journals[0].model_copy(update={'access_service_id': None}),)), initial.revision)
    with pytest.raises(ContentChangedError):
        first.verify_snapshot()
    assert first.journals[0].access_service_id == service.id




@pytest.mark.parametrize('change', ['institution', 'service'])
def test_login_never_admits_preparation_under_stale_saved_scope(tmp_path, change):
    from allfold.application.coordinators.login import LoginCoordinator
    from allfold.application.browser_runtime import BrowserTaskLock
    from electron_test_helpers import PendingBridge

    config, _, journal, service = current_mapping_document(tmp_path)
    config.write_text(config.read_text() + 'institution:\n  name: Test University\n')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    login = LoginCoordinator(bridge, lock)
    login.start(config)
    assert bridge.dispatched.wait(2)
    action, request = bridge.calls[0]
    assert action == 'login_carsi'
    assert request['service_id'] is None
    assert request['service_scope'] == BrowserServiceSnapshot.read(config).scope
    if change == 'institution':
        config.write_text(config.read_text().replace('Test University', 'Other University'))
    else:
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state,
            access_services=(service.model_copy(update={'access_url': 'https://changed.example/'}),)), saved.revision)
    bridge.future.set_result({'outcome': 'Opened', 'portal_page_id': 7})
    login.join()
    saved = BrowserServiceSnapshot.read(config)
    assert login.snapshot(saved)['phase'] == 'failed'
    assert len(bridge.calls) == 1
    assert login.prepared_page(saved, service.id) is None
    assert lock.owner is None


def test_independent_browser_owners_share_admission_but_service_and_controls_remain_exclusive():
    from allfold.application.browser_runtime import BrowserTaskLock
    lock = BrowserTaskLock()
    login = lock.acquire('login', scopes={'service:scope:publisher'})
    covers = lock.acquire('covers')
    wos = lock.acquire('wos', scopes={'service:scope:wos'})
    assert login and covers and wos
    assert lock.acquire('login', scopes={'service:scope:wos'}) is None
    assert lock.acquire('credentials') is None
    lock.release(covers)
    lock.require(login)
    lock.require(wos)
    lock.release(login)
    lock.release(wos)
    control = lock.acquire('workspace-reset')
    assert control and lock.acquire('covers') is None
    lock.release(control)
    with pytest.raises(RuntimeError):
        lock.require(login)


def test_access_verification_preserves_unrelated_inputs_and_service_edits(tmp_path):
    from allfold.config import AccessService
    config, _, journal, service = current_mapping_document(tmp_path)
    saved = load_user_state(config)
    other = AccessService.create('Other Publisher', 'https://other.example/')
    compare_write_user_state(config, replace(saved.state, access_services=(service, other)), saved.revision)
    captured = BrowserServiceSnapshot.read(config)
    config.write_text(config.read_text() + '\n# ordinary input change\n')
    state = load_user_state(config)
    compare_write_user_state(config, replace(state.state,
        journals=(journal.model_copy(update={'access_service_id': None}),),
        access_services=(service, other.model_copy(update={'access_url': 'https://replacement.example/'}))), state.revision)
    captured.verify((service.id,))
    with pytest.raises(ContentChangedError):
        captured.verify((other.id,))
