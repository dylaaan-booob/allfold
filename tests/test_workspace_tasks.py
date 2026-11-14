"""Application lifetime and Paper admission over real isolated Workspace libraries."""
import threading
from uuid import uuid4

import pytest

from allfold.application.collection_runtime import BranchSpec
from allfold.application.workspace_tasks import WorkspaceTaskHost
from allfold.models import ExternalIds
from allfold.persistence.library_models import MetadataDelta, PaperMetadata
from allfold.persistence.paper_repository import InvalidPaperState, PaperRepository
from safety_config_helpers import current_mapping_document


def library(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id,
            direct_ids=ExternalIds(doi='10.5555/host'), metadata=PaperMetadata(title='Host Paper')).paper
    return config, workspace, paper


def test_host_binds_existing_lifetime_once_and_never_creates_missing_library(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    host = WorkspaceTaskHost(config)
    try:
        assert host.initialize() is None and host.peek() is None
        assert not (tmp_path / 'workspace').exists()
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        with PaperRepository.create(workspace) as repository:
            queued = repository.admit_collection(repository.workspace_id, lifecycle_id=uuid4(),
                branches=('date',), direct_ids=ExternalIds(doi='10.5555/interrupted'),
                metadata=PaperMetadata(title='Interrupted'))
        assert host.peek() is None
        with PaperRepository.open(workspace) as repository:
            assert repository.get(queued.paper.id).collection_status == 'queued'
        first = host.current()
        assert first is host.current()
        with PaperRepository.open(workspace) as repository:
            paper = repository.get(queued.paper.id)
            assert paper.collection_status == 'failed' and paper.collection.reason == 'interrupted'
        fresh = first.admit(direct_ids=ExternalIds(doi='10.5555/new'),
            metadata=PaperMetadata(title='New'), branches=(BranchSpec('date', lambda context: None),))
        assert host.current() is first
        with PaperRepository.open(workspace) as repository:
            assert repository.get(fresh.paper_id).collection_status == 'queued'
    finally:
        host.shutdown(); host.join()


def test_manual_claim_and_deferred_collection_share_original_tokens_until_actual_release(tmp_path):
    config, workspace, paper = library(tmp_path)
    host = WorkspaceTaskHost(config)
    claim = None
    try:
        registry = host.current()
        claim = registry.reserve(paper.id, kind='legacy', expected_token=paper.token, cancel=lambda: None)
        args = dict(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
                    branches=(BranchSpec('date', lambda context: MetadataDelta(ordinary_dates=('2026-11',))),))
        task = registry.submit(**args)
        assert registry.submit(**args) is task
        assert task.waiting_on is claim and not task.future.done()
        with PaperRepository.open(workspace) as repository:
            assert repository.get(paper.id).collection_status == 'queued'
            # The accepted manual operation retains its exact original write authority.
            repository.merge_metadata(claim.token, MetadataDelta(abstract='Manual result'))
        claim.guard()
        with pytest.raises(InvalidPaperState):
            registry.reserve(paper.id, kind='download')
        with pytest.raises(InvalidPaperState):
            registry.reserve(paper.id, kind='legacy', expected_token=paper.token, cancel=lambda: None)
        assert host.cleanup_pending(paper.id, paper.workspace_id)
        registry.release(claim)
        finished = task.future.result(3)
        assert finished.collection_status == 'completed'
        assert finished.metadata.abstract == 'Manual result'
        assert finished.metadata.ordinary_dates == ('2026-11',)
        assert not host.cleanup_pending(paper.id, paper.workspace_id)
    finally:
        if claim is not None and not claim.released:
            registry.release(claim)
        host.shutdown(); host.join()


def test_app_projects_queued_running_cleanup_and_rejects_before_worker_finishes(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, workspace, paper = library(tmp_path)
    entered, cleanup, release = threading.Event(), threading.Event(), threading.Event()
    def branch(context):
        entered.set()
        context.cancel_event.wait(3)
        cleanup.set()
        assert release.wait(3)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        host = app.state.workspace_tasks
        registry = host.current()
        task = registry.admit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
                              branches=(BranchSpec('date', branch),))
        snapshot = client.get('/api/ui-next/workspace').json()
        projected = snapshot['subjects'][0]['journals'][0]['papers'][0]
        assert projected['collection_status'] == 'queued' and projected['cleanup_pending']
        registry.register(task)
        assert entered.wait(2)
        body = {'csrf_token': app.state.csrf_token, 'workspace_id': str(paper.workspace_id)}
        try:
            rejected = client.post(f'/api/ui-next/papers/{paper.id}/reject', json=body)
            assert rejected.status_code == 200 and rejected.json()['paper']['status'] == 'trash', rejected.text
            assert rejected.json()['paper']['cleanup_pending'] and cleanup.wait(2)
            restored = client.post(f'/api/ui-next/papers/{paper.id}/restore', json=body)
            assert restored.status_code == 200
            refused = client.post(f'/api/ui-next/papers/{paper.id}/clear-metadata', json=body)
            assert refused.status_code == 409
        finally:
            release.set()
        assert task.future.result(timeout=3).collection_status == 'cancelled'
        final = client.get('/api/ui-next/workspace').json()
        projected = final['subjects'][0]['journals'][0]['papers'][0]
        assert projected['collection_status'] == 'cancelled' and not projected['cleanup_pending']
        assert final['revision'] > snapshot['revision']


def test_delayed_http_reject_cannot_cancel_restored_paper_retry(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from allfold.persistence.library_models import MetadataDelta
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge

    config, workspace, paper = library(tmp_path)
    entered, finish_old, rejected, resume_reject = (threading.Event() for _ in range(4))
    retry_entered, finish_retry = threading.Event(), threading.Event()
    local = threading.local()

    def old_branch(context):
        entered.set()
        assert finish_old.wait(5)

    def retry_branch(context):
        retry_entered.set()
        assert finish_retry.wait(5)
        return MetadataDelta(abstract='Replacement attempt survived the old Reject')

    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        import allfold.web.ui_next as ui_next
        apply_action = ui_next.apply_paper_action
        settings_lock = app.state.settings_write_lock

        def mark_reject(*args, **kwargs):
            result = apply_action(*args, **kwargs)
            local.reject_committed = args[3] == 'reject'
            return result

        class PauseAfterSettingsUnlock:
            def __enter__(self):
                return settings_lock.__enter__()

            def __exit__(self, *args):
                settings_lock.__exit__(*args)
                if getattr(local, 'reject_committed', False):
                    local.reject_committed = False
                    rejected.set()
                    assert resume_reject.wait(5)

        monkeypatch.setattr(ui_next, 'apply_paper_action', mark_reject)
        app.state.settings_write_lock = PauseAfterSettingsUnlock()
        registry = app.state.workspace_tasks.current()
        old = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', old_branch),))
        body = {'csrf_token': app.state.csrf_token, 'workspace_id': str(paper.workspace_id)}
        try:
            assert entered.wait(2)
            with ThreadPoolExecutor(max_workers=1) as pool:
                delayed = pool.submit(client.post, f'/api/ui-next/papers/{paper.id}/reject', json=body)
                try:
                    assert rejected.wait(2)
                    with PaperRepository.open(workspace) as repository:
                        assert repository.get(paper.id).excluded
                    finish_old.set()
                    assert old.future.result(3).collection_status == 'cancelled'
                    assert client.post(f'/api/ui-next/papers/{paper.id}/restore', json=body).status_code == 200
                    replacement = registry.retry(paper.id, branches=(BranchSpec('date', retry_branch),))
                    assert retry_entered.wait(2) and replacement.token.attempt == 2
                    resume_reject.set()
                    assert delayed.result(3).status_code == 200
                    assert not replacement.cancel_event.is_set()
                finally:
                    resume_reject.set()
            finish_retry.set()
            assert replacement.future.result(3).collection_status == 'completed'
            with PaperRepository.open(workspace) as repository:
                assert repository.get(paper.id).metadata.abstract == 'Replacement attempt survived the old Reject'
        finally:
            finish_old.set(); finish_retry.set(); resume_reject.set()


def test_preprint_claim_survives_client_cleanup_and_submission_failure_rolls_back(tmp_path):
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.preprint_lookup import PreprintLookup
    from test_preprint_lookup import create_paper
    config, workspace, paper = create_paper(tmp_path)
    entered, cleaning, finish = threading.Event(), threading.Event(), threading.Event()
    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def lookup_published_preprints(self, doi):
            entered.set()
            return []
        def __exit__(self, *args):
            cleaning.set()
            assert finish.wait(3)
    host = WorkspaceTaskHost(config)
    lookup = PreprintLookup(config, BrowserTaskLock(), client_factory=Client, workspace_tasks=host)
    try:
        lookup.start(paper.id, paper.workspace_id)
        assert entered.wait(2) and cleaning.wait(2)
        registry = host.current()
        with pytest.raises(InvalidPaperState):
            registry.reserve(paper.id)
        assert host.cleanup_pending(paper.id, paper.workspace_id)
        finish.set(); lookup.join()
        assert not host.cleanup_pending(paper.id, paper.workspace_id)
        with PaperRepository.open(workspace) as repository:
            assert repository.get(paper.id).collection_status == 'not_started'
        registry._scheduler.close()
        with pytest.raises(RuntimeError, match='closed'):
            lookup.start(paper.id, paper.workspace_id)
        lookup.join()
        assert not host.cleanup_pending(paper.id, paper.workspace_id)
        claim = registry.reserve(paper.id)
        registry.release(claim)
    finally:
        finish.set(); lookup.shutdown(); lookup.join(); host.shutdown(); host.join()


def test_actual_application_drain_waits_client_and_native_terminal_before_factory_close(tmp_path):
    import asyncio
    import httpx
    from allfold.persistence.paper_repository import MetadataDelta
    from allfold.web.app import create_app
    from allfold.web.electron_server import drain_application
    from electron_test_helpers import PendingBridge
    config, workspace, paper = library(tmp_path)
    cleanup, release, factory_closed = threading.Event(), threading.Event(), threading.Event()
    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args):
            cleanup.set()
            assert release.wait(4)
    async def scenario():
        bridge = PendingBridge()
        app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path / 'logs')
        host = app.state.workspace_tasks
        host.factory.client_factory = Client
        actual_close = host.factory.close
        def close():
            factory_closed.set()
            actual_close()
        host.factory.close = close
        registry = host.current()
        def branch(context):
            context.provider('crossref')
            context.emit(MetadataDelta(abstract='Committed before shutdown'), sequence=1)
            context.execute_native('controlled_fixture', {})
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', branch, providers=('crossref',)),))
        draining = None
        try:
            assert await asyncio.to_thread(bridge.dispatched.wait, 2)
            queued = registry.admit(direct_ids=ExternalIds(doi='10.5555/queued'),
                metadata=PaperMetadata(title='Queued'), branches=(BranchSpec('date', branch),))
            draining = asyncio.create_task(drain_application(app))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://localhost') as client:
                assert (await client.get('/api/electron/health')).status_code == 200
                assert not factory_closed.is_set() and not draining.done()
                with pytest.raises(InvalidPaperState):
                    registry.reserve(paper.id)
                bridge.future.set_result({'done': True})
                assert await asyncio.to_thread(cleanup.wait, 2)
                assert not draining.done() and not factory_closed.is_set()
                release.set()
                await asyncio.wait_for(draining, 3)
                await drain_application(app)
            assert factory_closed.is_set()
            assert task.future.result().collection_status == 'cancelled'
            assert queued.future.result().collection_status == 'cancelled'
            with PaperRepository.open(workspace) as repository:
                assert repository.get(paper.id).metadata.abstract == 'Committed before shutdown'
        finally:
            release.set()
            if bridge.future is not None and not bridge.future.done():
                bridge.future.set_result({})
            if draining is not None:
                await draining
            else:
                await drain_application(app)
    asyncio.run(scenario())


def test_settings_ordinary_inputs_preserve_work_and_service_change_drains_only_affected(tmp_path):
    from concurrent.futures import Future, ThreadPoolExecutor
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from allfold.config import AccessService
    from allfold.persistence.user_state import compare_write_user_state, load_user_state
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from test_settings_autosave import patch_body
    config, workspace, paper = library(tmp_path)
    state = load_user_state(config)
    first = state.state.access_services[0].model_copy(update={'access_method': 'manual'})
    other = AccessService.create('Other', 'https://other.example/', access_method='manual')
    compare_write_user_state(config, replace(state.state, access_services=(first, other)), state.revision)
    class Native(OfflineBridge):
        connected = True
        def execute(self, action, data, *args, **kwargs):
            done = Future()
            done.set_result({'outcome': 'Opened', 'evidence': {'visit_action_observed': True,
                'navigation_observed': True, 'target_page_id': 17 if data.get('service_id') == first.id else 18}})
            return done
    app = create_app(config, electron_bridge=Native(), diagnostics_root=tmp_path / 'logs')
    release, finish_other = threading.Event(), threading.Event()
    with TestClient(app, base_url='http://localhost') as client:
        for service in (first, other):
            app.state.login.start(config, manual_service_id=service.id)
            app.state.login.join()
        registry = app.state.workspace_tasks.current()
        def affected(context):
            context.cancel_event.wait(5)
            assert release.wait(5)
        def unrelated(context):
            assert finish_other.wait(5)
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            service_id=first.id, branches=(BranchSpec('date', affected),))
        other_task = registry.submit(direct_ids=ExternalIds(doi='10.5555/other'), metadata=PaperMetadata(title='Other'),
            service_id=other.id, branches=(BranchSpec('date', unrelated),))
        try:
            opened = client.get('/api/ui-next/settings').json()
            ordinary = client.post('/api/ui-next/settings/autosave', json=patch_body(opened,
                keyword_expression='new', from_month='2026-02', to_month='2026-03')).json()
            assert ordinary['saved'] and not task.cancel_event.is_set() and not other_task.cancel_event.is_set(), {key: ordinary.get(key) for key in ('outcome', 'message', 'issues')}
            rows = ordinary['values']['access_services']
            rows[0]['access_url'] = 'https://replacement.example/'
            with ThreadPoolExecutor(max_workers=1) as pool:
                saving = pool.submit(client.post, '/api/ui-next/settings/autosave',
                    json=patch_body(ordinary, access_services=rows))
                assert task.cancel_event.wait(2)
                assert not saving.done() and not other_task.cancel_event.is_set()
                assert app.state.settings_write_lock.acquire(timeout=1)
                app.state.settings_write_lock.release()
                late = registry.admit(direct_ids=ExternalIds(doi='10.5555/late'), metadata=paper.metadata,
                    service_id=first.id, branches=(BranchSpec('date', lambda context: pytest.fail('Maintenance renewed authority')),))
                release.set()
                assert saving.result(timeout=3).json()['saved']
            assert registry.register(late).future.result(3).collection_status == 'failed'
            assert task.future.result(timeout=2).collection_status == 'cancelled'
            assert not other_task.future.done() and not other_task.cancel_event.is_set()
        finally:
            release.set(); finish_other.set()


def test_workspace_switch_drains_old_connections_before_save_and_rebinds_actual_path(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from allfold.config import load_config
    from electron_test_helpers import OfflineBridge
    from settings_api_helpers import form
    config, workspace, paper = library(tmp_path)
    other = tmp_path / 'other'
    other.mkdir()
    with PaperRepository.create(other) as repository:
        target_id = repository.workspace_id
    entered, cleanup, release = threading.Event(), threading.Event(), threading.Event()
    def branch(context):
        entered.set()
        context.cancel_event.wait(5)
        cleanup.set()
        assert release.wait(5)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', branch),))
        assert entered.wait(2)
        opened = client.get('/api/ui-next/settings').json()
        submitted = form(opened)
        submitted['output_dir'] = 'other'
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                saving = pool.submit(client.post, '/settings/save', data=submitted)
                assert cleanup.wait(2)
                assert registry.stopped and not saving.done()
                assert load_config(config).output_dir == workspace
                assert app.state.settings_write_lock.acquire(timeout=1)
                app.state.settings_write_lock.release()
                assert client.post('/api/ui-next/run', json={'csrf_token': app.state.csrf_token}).status_code == 409
                release.set()
                saved = saving.result(timeout=3)
                assert saved.json()['saved'], saved.text
            current = app.state.workspace_tasks.current()
            assert current is not registry and current.workspace_id == target_id
            assert registry.stopped and task.future.result().collection_status == 'cancelled'
            with PaperRepository.open(workspace) as repository:
                assert repository.get(paper.id).metadata.title == 'Host Paper'
        finally:
            release.set()


def test_invalid_stale_and_unapproved_settings_do_not_revoke_registry_work(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from settings_api_helpers import form
    from test_settings_autosave import patch_body
    config, workspace, paper = library(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        task = registry.admit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', lambda context: None),))
        opened = client.get('/api/ui-next/settings').json()
        invalid = form(opened); invalid.update(output_dir='other', keyword_expression='a b')
        assert not client.post('/settings/save', data=invalid).json()['saved']
        assert not task.cancel_event.is_set() and not registry.stopped
        stale_key = form(opened)
        stale_key.update(pubmed_key_action='clear', pubmed_key_revision='stale-credential-revision')
        assert not client.post('/settings/save', data=stale_key).json()['saved']
        assert not task.cancel_event.is_set() and not registry.stopped
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(opened, name='Changed')).json()
        stale = form(opened); stale['output_dir'] = 'other'
        assert not client.post('/settings/save', data=stale).json()['saved']
        assert not task.cancel_event.is_set() and not registry.stopped
        removal = form(saved)
        for key in ('service_id', 'service_name', 'service_access_url', 'service_access_method'):
            removal.pop(key)
        removal['journal_access_service_id'] = ['']
        preview = client.post('/settings/save', data=removal).json()
        assert not preview['saved'] and preview['deletion_plan']['services']
        assert not task.cancel_event.is_set() and not registry.stopped


def test_workspace_reset_accepts_api_cleanup_but_waits_outside_locks_before_deletion(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, workspace, paper = library(tmp_path)
    entered, cleaning, release = threading.Event(), threading.Event(), threading.Event()
    def branch(context):
        entered.set()
        context.cancel_event.wait(5)
        cleaning.set()
        assert release.wait(5)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', branch),))
        assert entered.wait(2)
        preview = client.get('/api/ui-next/settings/reset-preview').json()
        data = {'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']}
        assert client.post('/settings/workspace-reset', data={**data, 'reset_token': 'stale'}).status_code == 409
        assert not task.cancel_event.is_set()
        preview = client.get('/api/ui-next/settings/reset-preview').json()
        data['reset_token'] = preview['reset_token']
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                resetting = pool.submit(client.post, '/settings/workspace-reset', data=data)
                assert cleaning.wait(2)
                assert not resetting.done() and (workspace / 'papers.sqlite').exists()
                assert registry.stopped
                for lock in (app.state.settings_write_lock, app.state.reset_lock):
                    assert lock.acquire(blocking=False)
                    lock.release()
                release.set()
                result = resetting.result(timeout=3)
                assert result.status_code == 200, result.text
            assert not workspace.exists() and app.state.workspace_tasks.peek() is None
            assert task.future.result().collection_status == 'cancelled'
            assert not client.get('/api/ui-next/workspace').json()['initialized']
            assert not workspace.exists()
        finally:
            release.set()


def test_carsi_credentials_do_not_stop_unrelated_api_work(tmp_path):
    from concurrent.futures import Future
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, workspace, paper = library(tmp_path)
    entered, finish = threading.Event(), threading.Event()
    class Native(OfflineBridge):
        connected = True
        def execute(self, action, data, *args, **kwargs):
            assert action == 'cas_credentials'
            done = Future(); done.set_result({'ok': True})
            return done
    app = create_app(config, electron_bridge=Native(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        def branch(context):
            entered.set()
            assert finish.wait(5)
        registry = app.state.workspace_tasks.current()
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', branch, providers=('crossref',)),))
        assert entered.wait(2)
        try:
            result = client.post('/api/ui-next/settings/credentials', json={
                'csrf_token': app.state.csrf_token, 'operation': 'save',
                'username': 'fixture', 'password': 'synthetic', 'expected_revision': 'missing'})
            assert result.status_code == 200 and result.json() == {'ok': True}, result.text
            assert not task.cancel_event.is_set() and not task.future.done()
        finally:
            finish.set()


def test_logs_reset_refuses_api_queued_work_and_native_wait_releases_configuration_locks(tmp_path):
    from concurrent.futures import Future, ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, workspace, paper = library(tmp_path)
    class Native(OfflineBridge):
        connected = True
        def __init__(self):
            self.resetting = threading.Event()
            self.result = Future()
        def execute(self, action, data, *args, **kwargs):
            assert action == 'diagnostics_reset'
            if data['operation'] == 'preview':
                done = Future(); done.set_result({'scope_id': data['scope_id'], 'available': True, 'token': 'native'})
                return done
            self.scope_id = data['scope_id']
            self.resetting.set()
            return self.result
    native = Native()
    app = create_app(config, electron_bridge=native, diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        task = registry.admit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', lambda context: None),))
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        result = client.post('/settings/logs-reset', data={
            'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
        assert result.status_code == 409 and not native.resetting.is_set()
        assert registry.register(task).future.result(timeout=2).collection_status == 'completed'
        preview = client.get('/api/ui-next/settings/reset-preview?scope=logs').json()
        with ThreadPoolExecutor(max_workers=1) as pool:
            resetting = pool.submit(client.post, '/settings/logs-reset', data={
                'csrf_token': app.state.csrf_token, 'reset_token': preview['reset_token']})
            try:
                assert native.resetting.wait(2)
                for lock in (app.state.settings_write_lock, app.state.reset_lock):
                    assert lock.acquire(blocking=False)
                    lock.release()
            finally:
                native.result.set_result({'scope_id': native.scope_id, 'success': True})
            assert resetting.result(timeout=3).status_code == 200
        with PaperRepository.open(workspace) as repository:
            assert repository.get(paper.id).metadata.title == 'Host Paper'


def test_partial_output_save_rebinds_fresh_lifetime_to_actual_old_path(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    import allfold.application.settings as settings
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from settings_api_helpers import form
    config, workspace, paper = library(tmp_path)
    actual_write = settings.compare_write_user_state
    def concurrent_monitor(config_path, state, revision):
        saved = actual_write(config_path, state, revision)
        config.write_bytes(config.read_bytes() + b'# external revision after UserState write\n')
        return saved
    monkeypatch.setattr(settings, 'compare_write_user_state', concurrent_monitor)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        original = app.state.workspace_tasks.current()
        queued = original.admit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', lambda context: None),))
        opened = client.get('/api/ui-next/settings').json()
        submitted = form(opened)
        submitted['output_dir'] = 'requested-but-not-saved'
        submitted['service_access_url'] = ['https://saved-service.example/']
        result = client.post('/settings/save', data=submitted).json()
        assert result['save']['outcome'] == 'PARTIAL_SAVE' and not result['saved']
        assert result['values']['output_dir'] == 'requested-but-not-saved'
        current = app.state.workspace_tasks.current()
        assert current is not original and current.workspace == workspace
        assert current.workspace_id == original.workspace_id and current.lifecycle_id != original.lifecycle_id
        assert original.stopped and queued.future.result().collection_status == 'cancelled'


def test_provider_key_change_drains_only_declared_provider_attempts(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from settings_api_helpers import form
    config, workspace, paper = library(tmp_path)
    pubmed_started, crossref_started = threading.Event(), threading.Event()
    release, finish_other = threading.Event(), threading.Event()
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        def pubmed(context):
            pubmed_started.set()
            context.cancel_event.wait(5)
            assert release.wait(5)
        def crossref(context):
            crossref_started.set()
            assert finish_other.wait(5)
        affected = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=(BranchSpec('date', pubmed, providers=('pubmed',)),))
        other = registry.submit(direct_ids=ExternalIds(doi='10.5555/independent-provider'), metadata=PaperMetadata(title='Crossref'),
            branches=(BranchSpec('date', crossref, providers=('crossref',)),))
        assert pubmed_started.wait(2) and crossref_started.wait(2)
        opened = client.get('/api/ui-next/settings').json()
        submitted = form(opened)
        submitted['pubmed_key_action'] = 'clear'
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                saving = pool.submit(client.post, '/settings/save', data=submitted)
                assert affected.cancel_event.wait(2)
                assert not saving.done() and not other.cancel_event.is_set()
                release.set()
                saved = saving.result(timeout=3)
                assert saved.json()['saved'], saved.text
            assert affected.future.result(timeout=2).collection_status == 'cancelled'
            assert not other.cancel_event.is_set() and not other.future.done()
        finally:
            release.set(); finish_other.set()


def test_preprint_cleanup_exception_preserves_occupancy_and_refuses_maintenance(tmp_path):
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.preprint_lookup import PreprintLookup
    from allfold.application.decisions import apply_paper_action
    from test_preprint_lookup import create_paper
    config, workspace, paper = create_paper(tmp_path)
    class BrokenClose:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def lookup_published_preprints(self, doi): return []
        def __exit__(self, *args): raise RuntimeError('Synthetic unconfirmed client close')
    host = WorkspaceTaskHost(config)
    lookup = PreprintLookup(config, BrowserTaskLock(), client_factory=BrokenClose, workspace_tasks=host)
    lookup.start(paper.id, paper.workspace_id)
    lookup.join()
    registry = host.current()
    assert lookup.state(paper.id)['phase'] == 'Failed'
    assert host.cleanup_pending(paper.id, paper.workspace_id)
    assert registry.faults[-1]['reason'] == 'RuntimeError'
    with pytest.raises(InvalidPaperState):
        registry.reserve(paper.id)
    with pytest.raises(InvalidPaperState):
        apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata', workspace_registry=registry)
    with PaperRepository.open(workspace) as repository:
        assert repository.get(paper.id).collection_status == 'not_started'
    change = host.begin_change(whole=True)
    with pytest.raises(RuntimeError, match='settled'):
        host.drain_change(change)
    host.finish_change(change)
    lookup.shutdown(); host.shutdown()
    with pytest.raises(RuntimeError, match='settled'):
        host.join()


def test_workspace_get_does_not_initialize_or_interrupt_a_late_appearing_library(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, _, _, _ = current_mapping_document(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        queued = repository.admit_collection(repository.workspace_id, lifecycle_id=uuid4(),
            branches=('date',), direct_ids=ExternalIds(doi='10.5555/late-library'),
            metadata=PaperMetadata(title='Late library'))
    with TestClient(app, base_url='http://localhost') as client:
        for _ in range(2):
            state = client.get('/api/ui-next/workspace').json()
            item = state['subjects'][0]['journals'][0]['papers'][0]
            assert item['collection_status'] == 'queued'
            assert app.state.workspace_tasks.peek() is None
        app.state.workspace_tasks.current()
        state = client.get('/api/ui-next/workspace').json()
        item = state['subjects'][0]['journals'][0]['papers'][0]
        assert item['collection_status'] == 'failed'
        with PaperRepository.open(workspace) as repository:
            assert repository.get(queued.paper.id).collection.reason == 'interrupted'


def test_service_change_cancels_only_matching_branch_and_does_not_renew_queued_epoch(tmp_path):
    config, workspace, paper = library(tmp_path)
    entered, cancelled, cleanup_release, api_entered, api_release = (threading.Event() for _ in range(5))
    class Authority:
        def __init__(self, service):
            self.service_id, self.service_scope = service, f'service/{service}' if service else None
        def verify(self): pass
    host = WorkspaceTaskHost(config, authority_capture=lambda service, providers: Authority(service))
    registry = host.current()
    def document(context):
        entered.set()
        assert context.cancel_event.wait(3)
        cancelled.set()
        assert cleanup_release.wait(3)
    def api(context):
        api_entered.set()
        assert api_release.wait(3)
        context.emit(MetadataDelta(abstract='Independent API survives Service change'), sequence=1)
    try:
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/host'), metadata=paper.metadata,
            branches=[BranchSpec('document', document, service_id='publisher'), BranchSpec('api', api, service_id=None)])
        assert entered.wait(2) and api_entered.wait(2)
        change = host.begin_change(services=('publisher',))
        registry.signal_cancel_targets(change.targets)
        assert cancelled.wait(2)
        assert not task.cancel_event.is_set()
        late = registry.admit(direct_ids=ExternalIds(doi='10.5555/late'), metadata=PaperMetadata(title='Late'),
            branches=[BranchSpec('document', lambda _: pytest.fail('Renewed old Service epoch'), service_id='publisher')])
        skipped = registry.submit(direct_ids=ExternalIds(doi='10.5555/inapplicable'),
            metadata=PaperMetadata(title='Inapplicable'), branches=[
                BranchSpec('document', skip_reason='No applicable article page', service_id='publisher')])
        assert skipped.future.result(3).collection_status == 'completed'
        cleanup_release.set()
        host.drain_change(change)
        host.finish_change(change)
        assert not task.future.done()
        # Even when initialized after maintenance, this original admission cannot borrow new authority.
        assert registry.register(late).future.result(3).collection_status == 'failed'
        api_release.set()
        finished = task.future.result(3)
        assert finished.metadata.abstract == 'Independent API survives Service change'
        assert {b.name: b.state for b in finished.collection.branches} == {'api': 'completed', 'document': 'cancelled'}
    finally:
        cleanup_release.set(); api_release.set()
        host.shutdown(); host.join()
