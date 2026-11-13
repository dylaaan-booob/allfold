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


def test_control_reservation_blocks_new_use_while_old_owners_settle_outside_admission():
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from allfold.application.browser_runtime import BrowserTaskLock

    admission = threading.RLock()
    lock = BrowserTaskLock(admission_lock=admission)
    scope = {'service:fixture:publisher'}
    old = lock.acquire('collection', scopes=scope, shared=True)
    with admission:
        control = lock.reserve_control('access-cleanup', scopes=scope)
    assert control is not None
    assert lock.acquire('collection', scopes=scope, shared=True) is None
    unrelated = lock.acquire('collection', scopes={'service:fixture:other'}, shared=True)
    assert unrelated is not None
    assert lock.acquire('access-cleanup', scopes=scope, control=control) is None
    with ThreadPoolExecutor(max_workers=1) as worker:
        with admission:
            worker.submit(lock.release, old).result(timeout=1)
    cleanup = lock.acquire('access-cleanup', scopes=scope, control=control)
    assert cleanup is not None
    lock.release(cleanup)
    lock.release_control(control)
    fresh = lock.acquire('collection', scopes=scope, shared=True)
    assert fresh is not None
    lock.release(fresh)
    lock.release(unrelated)


def test_global_maintenance_reservation_has_exact_ownership_and_blocks_other_controls():
    from allfold.application.browser_runtime import BrowserTaskLock
    lock = BrowserTaskLock()
    reservation = lock.reserve_control('workspace-reset')
    assert reservation is not None
    assert lock.reserve_control('logs-reset') is None
    assert lock.acquire('covers') is None
    other = BrowserTaskLock()
    with pytest.raises(RuntimeError):
        other.acquire('workspace-reset', control=reservation)
    owner = lock.acquire('workspace-reset', control=reservation)
    assert owner is not None
    lock.release(owner)
    lock.release_control(reservation)
    lock.release_control(reservation)  # own cleanup is idempotent
    assert lock.acquire('covers') is not None


def test_service_data_owners_share_authority_but_keep_control_and_page_exclusivity():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from allfold.application.browser_runtime import BrowserTaskLock

    lock, ready = BrowserTaskLock(), Barrier(2)
    scope = {'service:scope:publisher'}

    def claim(page):
        ready.wait(timeout=2)
        return lock.acquire('collection', scopes=scope, shared=True, pages={page})

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = tuple(pool.map(claim, (101, 102)))
    assert first and second
    assert lock.acquire('login', scopes=scope) is None
    assert lock.acquire('access-cleanup', scopes=scope) is None
    assert lock.acquire('credentials') is None
    assert lock.acquire('collection', scopes={'service:scope:other'}, shared=True, pages={101}) is None
    assert lock.conflicts(scope)
    lock.release(first)
    assert lock.acquire('login', scopes=scope) is None
    lock.require(second)
    lock.release(second)
    control = lock.acquire('login', scopes=scope)
    assert control and lock.acquire('collection', scopes=scope, shared=True) is None
    unrelated = lock.acquire('collection', scopes={'service:scope:other'}, shared=True)
    assert unrelated
    lock.release(unrelated)
    lock.release(control)


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
