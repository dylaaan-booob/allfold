"""Local body actions through the real HTTP/host/repository boundary."""
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
import os
import threading
import sqlite3
import io
import json
import zipfile
from uuid import uuid4

import pytest

from fastapi.testclient import TestClient

from allfold.persistence.paper_repository import BodyReference, PaperRepository
from allfold.web.app import create_app
from library_application_helpers import create_paper, read_paper


class LocalBridge:
    connected = True
    closing = False

    def __init__(self):
        self.calls = []
        self.outcome = 'opened'

    def execute(self, action, data, progress=None, *, verify_recovery=None):
        assert action == 'local_paper_body', 'Local reading must not acquire Session or Prepare'
        self.calls.append((action, data))
        verify_recovery()
        result = Future()
        result.set_result(dict(outcome=self.outcome))
        return result

    def finish_disconnected(self):
        pass


def saved_body(tmp_path, *, trash=False, identity_only=False):
    config, workspace, paper = create_paper(tmp_path)
    path = workspace / 'Documents' / 'nested' / 'retained.pdf'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'normal transfer bytes')
    with PaperRepository.open(workspace) as repository:
        paper = repository.complete_body(paper.token, BodyReference(relative_path='Documents/nested/retained.pdf'))
        if trash or identity_only:
            paper = repository.exclude(paper.token)
        if identity_only:
            paper = repository.clear_metadata(paper.token)
            if not trash:
                paper = repository.unexclude(paper.token)
    return config, workspace, paper, path


def request_for(client, paper):
    snapshot = client.get('/api/ui-next/workspace').json()
    return dict(csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'], body_generation=paper.body_generation)


def test_identity_only_trash_can_open_and_locate_without_network_or_prepare(tmp_path):
    config, workspace, paper, path = saved_body(tmp_path, trash=True, identity_only=True)
    bridge = LocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        request = request_for(client, paper)
        opened = client.post(f'/api/papers/{paper.id}/body/open', json=request)
        assert opened.status_code == 200, opened.text
        assert opened.json()['outcome'] == 'opened'
        bridge.outcome = 'locate_requested'
        located = client.post(f'/api/papers/{paper.id}/body/locate', json=request)
        assert located.status_code == 200, located.text
        assert located.json()['outcome'] == 'locate_requested'
        assert [data['action'] for _, data in bridge.calls] == ['open', 'locate']
        assert all(data['body']['relative_path'] == 'Documents/nested/retained.pdf' for _, data in bridge.calls)
        assert path.read_bytes() == b'normal transfer bytes'
        assert read_paper(workspace, paper.id) == paper
        assert str(workspace) not in located.text and 'retained.pdf' not in located.text
        assert not app.state.workspace_tasks.active


@pytest.mark.parametrize('identity_only', [False, True])
def test_trash_pdf_deletion_removes_only_file_and_association(tmp_path, identity_only):
    config, workspace, paper, path = saved_body(tmp_path, trash=True, identity_only=identity_only)
    bridge = LocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        request = request_for(client, paper)
        deleted = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()['outcome'] == 'deleted'
        saved = read_paper(workspace, paper.id)
        assert saved.body is None and not path.exists()
        assert saved.body_generation == paper.body_generation + 1
        assert (saved.id, saved.identities, saved.metadata, saved.excluded) == (paper.id, paper.identities, paper.metadata, True)
        assert bridge.calls == []
        restore = client.post(f'/api/ui-next/papers/{paper.id}/unexclude', json={key: value for key, value in request.items() if key != 'body_generation'})
        assert restore.status_code == 200, restore.text
        assert restore.json()['paper']['status'] == (None if identity_only else 'candidate')
        assert restore.json()['paper']['download']['available'] is (not identity_only)


@pytest.mark.parametrize('action', ['open', 'locate', 'delete'])
def test_confirmed_missing_conditionally_clears_only_body_and_keeps_identity_placeholder(tmp_path, action):
    config, workspace, paper, path = saved_body(tmp_path, trash=True, identity_only=True)
    path.unlink()
    bridge = LocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        missing = client.post(f'/api/papers/{paper.id}/body/{action}', json=request_for(client, paper))
        assert missing.status_code == 200, missing.text
        assert missing.json()['outcome'] == 'missing'
        saved = read_paper(workspace, paper.id)
        assert saved.body is None and saved.metadata is None and saved.excluded
        assert saved.identities == paper.identities and saved.body_generation == paper.body_generation + 1
        assert bridge.calls == []


@pytest.mark.parametrize('unsafe', ['symlink', 'hardlink', 'directory', 'permission'])
def test_unsafe_or_inaccessible_body_preserves_association(tmp_path, monkeypatch, unsafe):
    config, workspace, paper, path = saved_body(tmp_path, trash=True)
    if unsafe == 'symlink':
        path.unlink(); path.symlink_to(workspace/'papers.sqlite')
    elif unsafe == 'hardlink':
        os.link(path, path.with_name('unrelated-link.pdf'))
    elif unsafe == 'directory':
        path.unlink(); path.mkdir()
    else:
        original_open = os.open
        def denied(name, *args, **kwargs):
            if name == 'retained.pdf':
                raise PermissionError('private filesystem error')
            return original_open(name, *args, **kwargs)
        monkeypatch.setattr(os, 'open', denied)
    bridge = LocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        failed = client.post(f'/api/papers/{paper.id}/body/open', json=request_for(client, paper))
        assert failed.status_code == 409, failed.text
        assert read_paper(workspace, paper.id) == paper and bridge.calls == []
        assert 'private filesystem error' not in failed.text and str(path) not in failed.text


def test_local_requests_reject_forged_capabilities_and_stale_generation(tmp_path):
    config, workspace, paper, path = saved_body(tmp_path)
    bridge = LocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        request = request_for(client, paper)
        endpoint = f'/api/papers/{paper.id}/body/open'
        assert client.post(endpoint, json={**request, 'csrf_token':'wrong'}).status_code == 403
        for name, value in [('path', str(path)), ('url', 'file://'+str(path)), ('headers', {'Cookie':'private'})]:
            assert client.post(endpoint, json={**request, name:value}).status_code == 422
        assert client.post(endpoint, json={**request, 'workspace_id':str(uuid4())}).status_code == 409
        assert client.post(endpoint, json={**request, 'body_generation':paper.body_generation-1}).status_code == 409
        assert client.post(f'/api/papers/{uuid4()}/body/open', json=request).status_code == 409
        assert bridge.calls == []


class PendingLocalBridge(LocalBridge):
    def __init__(self):
        super().__init__()
        self.started, self.future = threading.Event(), Future()
        self.cancelled = threading.Event()

    def execute(self, action, data, progress=None, *, verify_recovery=None):
        assert action == 'local_paper_body'
        self.calls.append((action, data))
        self.guard = verify_recovery
        self.started.set()
        return self.future

    def cancel_task(self, workflow_id, task_id):
        assert workflow_id == 'local-body' and task_id == self.calls[-1][1]['task_id']
        self.cancelled.set()


class ReadingCollectionBridge(PendingLocalBridge):
    def __init__(self, *, fail_first=False):
        super().__init__()
        self.document_started, self.document = threading.Event(), Future()
        self.fail_first = fail_first

    def execute(self, name, data, *args, **kwargs):
        if name == 'local_paper_body':
            return super().execute(name, data, *args, **kwargs)
        if name == 'release_workflow_pages':
            done = Future(); done.set_result({'released': True}); return done
        assert name == 'extract_paper_metadata'
        if self.fail_first:
            self.fail_first = False
            failed = Future()
            failed.set_result({'diagnostic': {'code': 'site_restricted', 'stage': 'navigation'}})
            return failed
        self.document_started.set()
        return self.document


@pytest.mark.parametrize('action,outcome', [('open', 'opened'), ('locate', 'locate_requested')])
def test_first_real_run_collects_saved_body_while_local_native_read_is_pending(tmp_path, action, outcome):
    from allfold.application.integrated_run import run_integrated
    from allfold.models import ExternalIds
    from integrated_run_helpers import EmptyLookup
    from test_document_metadata import envelope
    from test_integrated_run import client_for, evidence

    config, workspace, paper, path = saved_body(tmp_path)
    config.write_text(config.read_text() + 'enabled_providers: [pubmed]\n')
    bridge = ReadingCollectionBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    # Both foreground and independent collection use controlled Provider clients.
    app.state.workspace_tasks.factory.client_factory = EmptyLookup
    with TestClient(app, base_url='http://localhost') as client, ThreadPoolExecutor() as threads:
        pending = threads.submit(client.post, f'/api/papers/{paper.id}/body/{action}', json=request_for(client, paper))
        try:
            assert bridge.started.wait(2)
            host = app.state.workspace_tasks
            assert host.active and host.cleanup_pending(paper.id, paper.workspace_id)
            assert read_paper(workspace, paper.id).collection_status == 'not_started'
            result = run_integrated(config, client_factory=client_for((evidence(doi='10.5555/decision'),)),
                lookup_factory=EmptyLookup, workspace_tasks=host)
            assert (result.facts.existing_papers, result.facts.created_papers) == (1, 0)
            collecting = read_paper(workspace, paper.id)
            assert collecting.id == paper.id and collecting.collection_status in {'queued', 'running'}
            assert {branch.name for branch in collecting.collection.branches} == {'document', 'necessary-api'}
            assert bridge.document_started.wait(2) and not bridge.future.done()
            task = host.current().admit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=collecting.metadata,
                branches=app.state.collection_service.plan(paper=collecting))
            bridge.document.set_result(envelope())
            completed = task.future.result(3)
            assert completed.id == paper.id and completed.collection_status == 'completed'
            assert not pending.done() and host.cleanup_pending(paper.id, paper.workspace_id)
        finally:
            if not bridge.document.done(): bridge.document.set_result(envelope())
            if not bridge.future.done(): bridge.future.set_result(dict(outcome=outcome, resource_closed=True))
        opened = pending.result(3)
        assert opened.status_code == 200 and opened.json()['outcome'] == outcome
        assert path.read_bytes() == b'normal transfer bytes'
        assert not app.state.workspace_tasks.active


@pytest.mark.parametrize('action,outcome', [('open', 'opened'), ('locate', 'locate_requested')])
def test_public_collection_retry_remains_available_while_native_read_is_pending(tmp_path, action, outcome):
    from allfold.models import ExternalIds
    from integrated_run_helpers import EmptyLookup
    from test_document_metadata import envelope

    config, workspace, paper, path = saved_body(tmp_path)
    bridge = ReadingCollectionBridge(fail_first=True)
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    app.state.workspace_tasks.factory.client_factory = EmptyLookup
    with TestClient(app, base_url='http://localhost') as client, ThreadPoolExecutor() as threads:
        registry = app.state.workspace_tasks.current()
        plan = app.state.collection_service.plan(paper=paper)
        failed = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
            branches=plan).future.result(3)
        assert failed.collection_status == 'failed'
        pending = threads.submit(client.post, f'/api/papers/{paper.id}/body/{action}', json=request_for(client, failed))
        try:
            assert bridge.started.wait(2)
            snapshot = client.get('/api/ui-next/workspace').json()
            item = snapshot['downloaded']['papers'][0]['paper']
            assert item['cleanup_pending'] and not item['collection']['cleaning_up']
            assert item['collection']['retry_available']
            assert registry.check_retry(paper.id, branches=plan, expected_token=failed.token,
                expected_attempt=1, expected_revision=failed.revision) == failed
            response = client.post(f'/api/papers/{paper.id}/collection/retry', json=dict(
                csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'], **item['collection']['retry']))
            assert response.status_code == 200, response.text
            assert bridge.document_started.wait(2) and not bridge.future.done()
            task = registry.admit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata, branches=plan)
            bridge.document.set_result(envelope())
            completed = task.future.result(3)
            assert completed.collection_status == 'completed' and completed.collection.attempt == 2
            assert completed.body == paper.body and not pending.done()
        finally:
            if not bridge.document.done(): bridge.document.set_result(envelope())
            if not bridge.future.done(): bridge.future.set_result(dict(outcome=outcome, resource_closed=True))
        assert pending.result(3).status_code == 200
        assert not app.state.workspace_tasks.active and path.read_bytes() == b'normal transfer bytes'


@pytest.mark.parametrize('terminal', ['cancelled-future', 'unclosed'])
@pytest.mark.parametrize('collection_state', ['not_started', 'failed'])
def test_unconfirmed_local_terminal_keeps_collection_blocked(tmp_path, terminal, collection_state):
    from concurrent.futures import CancelledError
    from allfold.application.collection_runtime import BranchSpec
    from allfold.models import ExternalIds

    config, workspace, paper, _ = saved_body(tmp_path)
    bridge = PendingLocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    client = TestClient(app, base_url='http://localhost')
    client.__enter__()
    try:
        registry = app.state.workspace_tasks.current()
        def failure(_): raise RuntimeError('Controlled collection failure')
        if collection_state == 'failed':
            paper = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
                branches=(BranchSpec('controlled', failure),)).future.result(3)
            assert paper.collection_status == 'failed'
        with ThreadPoolExecutor() as threads:
            pending = threads.submit(client.post, f'/api/papers/{paper.id}/body/open', json=request_for(client, paper))
            assert bridge.started.wait(2)
            if terminal == 'cancelled-future':
                bridge.future.cancel()
                with pytest.raises(CancelledError): pending.result(3)
            else:
                bridge.future.set_result(dict(outcome='local_failure', resource_closed=False))
                assert pending.result(3).status_code == 409
            blocked = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
                branches=(BranchSpec('must-not-start', lambda _: pytest.fail('Unconfirmed cleanup admitted collection')),))
            assert blocked == paper and read_paper(workspace, paper.id).collection_status == collection_state
            assert app.state.workspace_tasks.active and registry.cleanup_pending(paper.id)
            if collection_state == 'failed':
                from allfold.persistence.paper_repository import InvalidPaperState
                plan = (BranchSpec('controlled', lambda _: pytest.fail('Unconfirmed cleanup admitted Retry')),)
                for retry in (registry.check_retry, registry.retry):
                    with pytest.raises(InvalidPaperState, match='resources have not settled'):
                        retry(paper.id, branches=plan, expected_token=paper.token, expected_attempt=1)
    finally:
        # Assert shutdown separately so its expected error cannot hide a failed
        # collection/occupancy assertion above.
        with pytest.raises(RuntimeError, match='resources or state could not be settled'):
            client.__exit__(None, None, None)


@pytest.mark.parametrize('collection_state', ['not_started', 'failed'])
def test_destructive_local_lease_still_blocks_collection_after_restore(tmp_path, collection_state):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.models import ExternalIds

    config, workspace, paper, path = saved_body(tmp_path)
    app = create_app(config, electron_bridge=LocalBridge(), diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        host = app.state.workspace_tasks
        registry = host.current()
        def failure(_): raise RuntimeError('Controlled collection failure')
        if collection_state == 'failed':
            paper = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
                branches=(BranchSpec('controlled', failure),)).future.result(3)
            assert paper.collection_status == 'failed'
        with PaperRepository.open(workspace) as repository:
            paper = repository.exclude(paper.token)
        request = request_for(client, paper)
        with host.local_operation(paper, destructive=True):
            restored = client.post(f'/api/ui-next/papers/{paper.id}/restore', json={
                key: value for key, value in request.items() if key != 'body_generation'})
            assert restored.status_code == 200, restored.text
            current = read_paper(workspace, paper.id)
            blocked = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=current.metadata,
                branches=(BranchSpec('must-not-start', lambda _: pytest.fail('Deletion admitted collection')),))
            assert blocked == current and current.collection_status == collection_state
            if collection_state == 'failed':
                from allfold.persistence.paper_repository import InvalidPaperState
                plan = (BranchSpec('controlled', lambda _: pytest.fail('Deletion admitted Retry')),)
                for retry in (registry.check_retry, registry.retry):
                    with pytest.raises(InvalidPaperState, match='resources have not settled'):
                        retry(paper.id, branches=plan, expected_token=current.token, expected_attempt=1)
            assert client.post(f'/api/papers/{paper.id}/body/open', json=request).status_code == 409
            assert host.active and host.cleanup_pending(paper.id, paper.workspace_id)
        assert not host.active and path.read_bytes() == b'normal transfer bytes'


def test_retry_rechecks_native_uncertainty_captured_after_initial_qualification(tmp_path):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.application.local_body import LocalBodyService
    from allfold.application.task_authority import TaskAuthority
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.models import ExternalIds
    from allfold.persistence.paper_repository import InvalidPaperState

    class UnclosedBridge(LocalBridge):
        def execute(self, action, data, progress=None, *, verify_recovery=None):
            assert action == 'local_paper_body'
            verify_recovery()
            self.calls.append((action, data))
            result = Future()
            result.set_result(dict(outcome='local_failure', resource_closed=False))
            return result

    config, workspace, paper, path = saved_body(tmp_path)
    bridge, inject_local_failure = UnclosedBridge(), False
    def capture(service_id, providers):
        nonlocal inject_local_failure
        if inject_local_failure:
            inject_local_failure = False
            # Authority is captured outside the Paper gate. An independent
            # local request can settle uncertain after the first idle check.
            result = LocalBodyService(host).perform(paper.id, paper.workspace_id,
                action='open', body_generation=paper.body_generation)
            assert result.status == 'local_failure'
        return TaskAuthority.capture(config, None, service_id, providers)
    host = WorkspaceTaskHost(config, bridge=bridge, authority_capture=capture)
    try:
        registry = host.current()
        def failure(_): raise RuntimeError('Controlled collection failure')
        failed = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
            branches=(BranchSpec('controlled', failure),)).future.result(3)
        assert failed.collection_status == 'failed'
        inject_local_failure = True
        with pytest.raises(InvalidPaperState, match='resources have not settled'):
            registry.retry(paper.id, branches=(BranchSpec('controlled', lambda _: None),),
                expected_token=failed.token, expected_attempt=1, expected_revision=failed.revision)
        assert len(bridge.calls) == 1 and host.active
        assert read_paper(workspace, paper.id) == failed and path.read_bytes() == b'normal transfer bytes'
    finally:
        host.shutdown()
        with pytest.raises(RuntimeError, match='resources or state could not be settled'):
            host.join()


def test_old_missing_native_result_cannot_clear_a_new_body(tmp_path):
    config, workspace, paper, path = saved_body(tmp_path)
    bridge = PendingLocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client, ThreadPoolExecutor() as threads:
        request = request_for(client, paper)
        pending = threads.submit(client.post, f'/api/papers/{paper.id}/body/open', json=request)
        assert bridge.started.wait(2)
        path.unlink()
        path.write_bytes(b'new current body')
        with PaperRepository.open(workspace) as repository:
            cleared = repository.clear_body(paper.token)
            replacement = repository.complete_body(cleared.token, BodyReference(relative_path=paper.body.relative_path))
        bridge.future.set_result(dict(outcome='missing', resource_closed=True))
        assert pending.result(3).status_code == 409
        assert read_paper(workspace, paper.id) == replacement and path.read_bytes() == b'new current body'


def test_local_native_terminal_is_host_visible_and_drain_waits_outside_settings_lock(tmp_path):
    config, workspace, paper, path = saved_body(tmp_path)
    bridge = PendingLocalBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client, ThreadPoolExecutor() as threads:
        pending = threads.submit(client.post, f'/api/papers/{paper.id}/body/open', json=request_for(client, paper))
        assert bridge.started.wait(2)
        host = app.state.workspace_tasks
        assert host.active and host.cleanup_pending(paper.id, paper.workspace_id)
        # A separate HTTP thread can acquire both locks while shell awaits.
        def locks_available():
            with app.state.settings_write_lock, app.state.reset_lock:
                return True
        assert threads.submit(locks_available).result(2)
        change = host.begin_change(whole=True)
        draining = threads.submit(host.drain_change, change)
        try:
            assert bridge.cancelled.wait(2)
            assert not draining.done() and not bridge.future.done() and host.active
        finally:
            bridge.future.set_result(dict(outcome='opened', resource_closed=True))
        assert pending.result(3).status_code == 409
        draining.result(3)
        assert not host.active and path.read_bytes() == b'normal transfer bytes'
        host.finish_change(change)


def test_shell_failure_preserves_association_and_reports_failure(tmp_path):
    config, workspace, paper, path = saved_body(tmp_path)
    bridge = LocalBridge(); bridge.outcome = 'local_failure'
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        failed = client.post(f'/api/papers/{paper.id}/body/open', json=request_for(client, paper))
        assert failed.status_code == 409, failed.text
        assert failed.json()['outcome'] == 'local_failure'
        assert read_paper(workspace, paper.id) == paper and path.exists()


def test_failed_unlink_restores_owned_body_without_clearing_association(tmp_path, monkeypatch):
    config, workspace, paper, path = saved_body(tmp_path, trash=True)
    original_unlink = os.unlink
    def denied(name, *args, **kwargs):
        if str(name).startswith('body-') and str(name).endswith('.removed'):
            raise PermissionError('private unlink failure')
        return original_unlink(name, *args, **kwargs)
    app = create_app(config, electron_bridge=LocalBridge(), diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        monkeypatch.setattr(os, 'unlink', denied)
        failed = client.post(f'/api/papers/{paper.id}/body/delete', json=request_for(client, paper))
        assert failed.status_code == 409 and path.read_bytes() == b'normal transfer bytes'
        assert read_paper(workspace, paper.id) == paper
        assert not list((workspace/'Documents/.downloads/.cleanup').iterdir())


def test_db_failure_after_physical_delete_preserves_reference_until_explicit_missing_retry(tmp_path, monkeypatch):
    config, workspace, paper, path = saved_body(tmp_path, trash=True)
    app = create_app(config, electron_bridge=LocalBridge(), diagnostics_root=tmp_path/'logs')
    real_connect = sqlite3.connect
    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == 'DELETE FROM paper_body WHERE paper_id = ?':
                raise sqlite3.OperationalError('fixture disk I/O failure')
            return super().execute(sql, *args, **kwargs)
    with TestClient(app, base_url='http://localhost') as client:
        request = request_for(client, paper)
        with monkeypatch.context() as fault:
            fault.setattr(sqlite3, 'connect', lambda *a, **kw: real_connect(*a, **kw, factory=FailingConnection))
            failed = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
        assert failed.status_code == 409 and failed.json()['outcome'] == 'association_failure' and not path.exists()
        assert read_paper(workspace, paper.id) == paper
        with zipfile.ZipFile(io.BytesIO(app.state.diagnostics.export())) as archive:
            logs = archive.read('events.jsonl').decode()
        assert any(event.get('action') == 'local_paper_body' and event.get('outcome') == 'association_failure'
            for event in map(json.loads, logs.splitlines()))
        assert str(path) not in logs and 'fixture disk I/O failure' not in logs
        retried = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
        assert retried.status_code == 200 and retried.json()['outcome'] == 'missing'
        saved = read_paper(workspace, paper.id)
        assert saved.body is None and saved.metadata == paper.metadata and saved.excluded


def test_replacement_between_final_check_and_move_is_restored_never_unlinked(tmp_path, monkeypatch):
    config, workspace, paper, path = saved_body(tmp_path, trash=True)
    app = create_app(config, electron_bridge=LocalBridge(), diagnostics_root=tmp_path/'logs')
    real_stat = os.stat
    armed = False
    def swap_after_check(name, *args, **kwargs):
        nonlocal armed
        result = real_stat(name, *args, **kwargs)
        # The private disposal location exists only for the final destructive
        # boundary. Substitute after that leaf check, immediately before move.
        if name == 'retained.pdf' and not armed and (workspace/'Documents/.downloads/.cleanup').exists():
            armed = True
            path.rename(path.with_name('original.pdf'))
            path.write_bytes(b'unknown replacement')
        return result
    with TestClient(app, base_url='http://localhost') as client:
        request = request_for(client, paper)
        monkeypatch.setattr(os, 'stat', swap_after_check)
        failed = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
        assert armed and failed.status_code == 409
        assert path.read_bytes() == b'unknown replacement'
        assert path.with_name('original.pdf').read_bytes() == b'normal transfer bytes'
        assert read_paper(workspace, paper.id) == paper


def test_reject_is_immediate_but_delete_waits_for_actual_collection_exit(tmp_path):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.models import ExternalIds
    config, workspace, paper, path = saved_body(tmp_path)
    app = create_app(config, electron_bridge=LocalBridge(), diagnostics_root=tmp_path/'logs')
    entered, release = threading.Event(), threading.Event()
    def held(context):
        entered.set()
        assert release.wait(4)
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'), metadata=paper.metadata,
            branches=(BranchSpec('held', held),))
        assert entered.wait(2)
        request = request_for(client, paper)
        try:
            rejected = client.post(f'/api/ui-next/papers/{paper.id}/reject', json={key:value for key,value in request.items() if key != 'body_generation'})
            assert rejected.status_code == 200 and rejected.json()['paper']['excluded']
            assert rejected.json()['paper']['cleanup_pending'] and not task.future.done()
            denied = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
            assert denied.status_code == 409 and path.exists()
        finally:
            release.set()
        task.future.result(3)
        deleted = client.post(f'/api/papers/{paper.id}/body/delete', json=request)
        assert deleted.status_code == 200 and deleted.json()['outcome'] == 'deleted'
        assert not path.exists() and read_paper(workspace, paper.id).excluded
