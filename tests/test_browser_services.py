"""Invocation-scoped saved identities; no real accounts or Workspace data."""
from dataclasses import replace
import pytest

from allfold.application.browser_services import BrowserServiceSnapshot
from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from safety_config_helpers import current_mapping_document


def test_import_dispatch_uses_saved_mapping_and_keeps_ambiguous_or_missing_unassigned(tmp_path):
    from concurrent.futures import Future
    from allfold.application.batch_import import BatchImportService, BatchPhase
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.config import AccessService, JournalConfig
    from electron_test_helpers import paper, edit

    config, _, journal, service = current_mapping_document(tmp_path)
    initial = load_user_state(config)
    other = AccessService.create('Other', 'https://other.example.org/', access_method='manual')
    compare_write_user_state(config, replace(initial.state,
        journals=(journal.model_copy(update={'eissn': '1541-0420'}),
            JournalConfig(name='Annals', issn='0090-5364', access_service_id=other.id),
            JournalConfig(name='Shared', issn='2168-8966', access_service_id=service.id),
            JournalConfig(name='Unassigned', issn='0162-1459')),
        access_services=(service, other)), initial.revision)
    identifiers = [('0006-341X',), ('0090-5364',), ('0006-341X', '0090-5364'), (),
        ('1541-0420',), ('1234-5679',), ('0006-341X', '2168-8966'), ('0006-341X', '0162-1459')]
    workspace = tmp_path / 'workspace'
    papers = []
    for index, issns in enumerate(identifiers):
        value, path = paper(workspace, str(index))
        edit(path, journal_issns=list(issns))
        papers.append(value)

    class Bridge:
        connected = True
        calls = []
        def execute(self, action, data, progress=None, *, verify_recovery=None):
            self.calls.append((action, data))
            future = Future()
            future.set_result({'settled': True, 'parent': {'outcome': 'no_effect'}})
            return future

    bridge, lock = Bridge(), BrowserTaskLock()
    owner = lock.acquire('kept')
    batch = BatchImportService(bridge, lock)
    batch.start(workspace, browser_owner=owner, services=BrowserServiceSnapshot.read(config))
    batch.join()
    assert batch.snapshot().phase is BatchPhase.COMPLETED
    assert {data['paper_id']: data['service_id'] for _, data in bridge.calls} == dict(zip(
        (str(p.id) for p in papers), [service.id, other.id, None, None, service.id, None, service.id, None], strict=True))
    assert len({data['task_id'] for _, data in bridge.calls}) == len(papers)
    assert len({data['parent_task_id'] for _, data in bridge.calls}) == 1
    assert all(data['task_id'] != owner.id for _, data in bridge.calls)
    assert all(data['service_scope'] == BrowserServiceSnapshot.read(config).scope for _, data in bridge.calls)


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
        first.verify()
    assert first.journals[0].access_service_id == service.id


@pytest.mark.parametrize('change', ['config', 'mapping'])
@pytest.mark.parametrize('outcome', ['confirmed', 'uncertain'])
def test_import_revision_change_settles_dispatched_parent_and_stops_next_paper(tmp_path, change, outcome):
    from allfold.application.batch_import import BatchImportService, BatchPhase
    from allfold.application.browser_runtime import BrowserTaskLock
    from electron_test_helpers import paper, PendingBridge, state
    from test_electron_import import confirmed

    config, _, _, _ = current_mapping_document(tmp_path)
    workspace = tmp_path / 'workspace'
    _, first = paper(workspace, 'a')
    _, second = paper(workspace, 'b')
    bridge, lock = PendingBridge(), BrowserTaskLock()
    batch = BatchImportService(bridge, lock)
    batch.start(workspace, browser_owner=lock.acquire('kept'), services=BrowserServiceSnapshot.read(config))
    assert bridge.dispatched.wait(2)
    if change == 'config':
        config.write_text(config.read_text() + '\n# changed\n')
    else:
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state,
            journals=(saved.state.journals[0].model_copy(update={'access_service_id': None}),)), saved.revision)
    bridge.future.set_result(confirmed() if outcome == 'confirmed' else
                            {'settled': True, 'parent': {'outcome': 'uncertain'}})
    batch.join()
    assert len(bridge.calls) == 1
    assert state(first).status.value == ('exported' if outcome == 'confirmed' else 'kept')
    assert state(second).status.value == 'kept'
    assert batch.snapshot().phase is (BatchPhase.BLOCKED if outcome == 'confirmed' else BatchPhase.PAUSED)


@pytest.mark.parametrize('change', ['config', 'mapping'])
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
    if change == 'config':
        config.write_text(config.read_text() + '\n# changed\n')
    else:
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state,
            journals=(journal.model_copy(update={'access_service_id': None}),)), saved.revision)
    bridge.future.set_result({'outcome': 'Opened', 'portal_page_id': 7})
    login.join()
    saved = BrowserServiceSnapshot.read(config)
    assert login.snapshot(saved)['phase'] == 'failed'
    assert len(bridge.calls) == 1
    assert login.prepared_page(saved, service.id) is None
    assert lock.owner is None
