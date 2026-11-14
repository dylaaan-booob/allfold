"""Workspace task services exercised with SQLite, owned threads and real resources."""
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event, Thread
import time
import sqlite3

import pytest

from allfold.application.collection_runtime import BranchSpec, WorkspaceRegistry
from allfold.application.task_clients import IndependentClientFactory
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import InvalidPaperState, MetadataDelta, PaperMetadata, PaperRepository, StaleWriteError
from allfold.persistence.library_database import LibraryBusyError


def workspace(tmp_path):
    path = tmp_path / 'workspace'
    path.mkdir()
    with PaperRepository.create(path):
        pass
    return path


def submit(registry, suffix, branches, **kwargs):
    return registry.submit(direct_ids=ExternalIds(doi=f'10.1234/{suffix}'),
        metadata=PaperMetadata(title=f'Paper {suffix}'), branches=branches, **kwargs)


def test_reject_during_authority_capture_keeps_original_admission_and_never_renews_token(tmp_path):
    capturing, finish_capture = Event(), Event()
    captured = []
    def capture(service_id, providers):
        captured.append((service_id, providers))
        capturing.set()
        assert finish_capture.wait(3)
        return Authority(service_id)
    path = workspace(tmp_path)
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        authority_capture=capture)
    try:
        task = submit(registry, 'late-admit', [BranchSpec('empty', lambda _: pytest.fail('Rejected executed'))])
        assert capturing.wait(2)
        with PaperRepository.open(path) as repository:
            original = repository.get(task.paper_id)
            rejected = repository.exclude(original.token)
        targets = registry.prepare_cancel_paper(task.paper_id)
        with PaperRepository.open(path) as repository:
            restored = repository.restore(rejected.token)
            assert restored.token != task.token.write
        registry.signal_cancel_targets(targets)
        assert registry.admit(direct_ids=ExternalIds(doi='10.1234/late-admit'),
            metadata=PaperMetadata(title='Repeat'), branches=task.branches) is task
        assert not task.future.done()
        finish_capture.set()
        finished = task.future.result(3)
        assert finished.id == original.id and finished.collection_status == 'cancelled'
        assert finished.collection.attempt == 1
        assert captured == [(None, ())]
        assert not registry.active
    finally:
        finish_capture.set()
        registry.shutdown()
        registry.join()


def test_native_branch_failure_remains_retryable_after_callback_returns(tmp_path):
    class Bridge:
        def __init__(self):
            self.started, self.operation = Event(), Future()

        def execute(self, action, data, *args, **kwargs):
            if action == 'release_workflow_pages':
                released = Future()
                released.set_result({'released': True})
                return released
            self.started.set()
            return self.operation

        def cancel_task(self, *_):
            pass

    path, bridge = workspace(tmp_path), Bridge()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), bridge=bridge)
    try:
        def collect(context):
            context.execute_native('controlled-probe', {})

        task = submit(registry, 'native-retry', [BranchSpec('native', collect)])
        assert bridge.started.wait(2)
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).collection.branches[0].state != 'completed'
        bridge.operation.set_exception(RuntimeError('Controlled native failure'))
        failed = task.future.result(3)
        assert failed.collection_status == 'failed'
        assert failed.collection.branches[0].state == 'failed'
        retried = registry.retry(task.paper_id, branches=[BranchSpec('native', lambda _: MetadataDelta(
            ordinary_dates=('2026-11-13',)))])
        assert retried.future.result(3).metadata.ordinary_dates == ('2026-11-13',)
    finally:
        if not bridge.operation.done():
            bridge.operation.set_result({})
        registry.shutdown()
        registry.join()


def test_final_diagnostic_write_retains_paper_and_logs_occupancy(tmp_path):
    from allfold.diagnostics import DiagnosticStore
    writing, finish_write = Event(), Event()

    class Store(DiagnosticStore):
        def event(self, event, details=None, *, level='info'):
            if event == 'workflow_finished':
                writing.set()
                assert finish_write.wait(3)
            return super().event(event, details, level=level)

    path = workspace(tmp_path)
    store = Store(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), diagnostics=store)
    try:
        task = submit(registry, 'diagnostic-cleanup', [BranchSpec('empty', lambda _: None)])
        assert writing.wait(2)
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).collection_status == 'completed'
        assert registry.active and registry.cleanup_pending(task.paper_id, registry.workspace_id)
        assert not task.future.done()
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
        finish_write.set()
        completed = task.future.result(3)
        with PaperRepository.open(path) as repository:
            assert completed.revision == repository.get(task.paper_id).revision
        assert not registry.active
    finally:
        finish_write.set()
        registry.shutdown()
        registry.join()


def test_incremental_results_and_empty_completion_persist_without_automatic_replay(tmp_path):
    path = workspace(tmp_path)
    factory = IndependentClientFactory(tmp_path / 'config.yaml')
    registry = WorkspaceRegistry(path, factory=factory)

    def collect(context):
        context.emit(MetadataDelta(abstract='Observed abstract'), sequence=1)

    try:
        task = submit(registry, 'incremental', [BranchSpec('metadata', collect), BranchSpec('empty', lambda _: None)])
        paper = task.future.result(3)
        assert paper.collection_status == 'completed'
        assert paper.metadata.abstract == 'Observed abstract'
        assert not registry.busy(paper.id)
        assert submit(registry, 'incremental', [BranchSpec('metadata', lambda _: None)]).id == paper.id
    finally:
        registry.shutdown()
        registry.join()
    reopened = WorkspaceRegistry(path, factory=factory)
    try:
        assert submit(reopened, 'incremental', [BranchSpec('metadata', lambda _: None)]).collection_status == 'completed'
    finally:
        reopened.shutdown()
        reopened.join()
        factory.close()


def test_admitted_before_registration_is_atomic_against_download_and_legacy(tmp_path):
    path = workspace(tmp_path)
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))
    try:
        args = dict(direct_ids=ExternalIds(doi='10.1234/same'), metadata=PaperMetadata(title='Same'),
                    branches=[BranchSpec('empty', lambda _: None)])
        with ThreadPoolExecutor(max_workers=8) as pool:
            handles = list(pool.map(lambda _: registry.admit(**args), range(20)))
        assert all(handle is handles[0] for handle in handles)
        task = handles[0]
        for kind in ('download', 'legacy'):
            with pytest.raises(InvalidPaperState):
                registry.reserve(task.paper_id, kind=kind)
        assert registry.register(task).future.result(3).collection.attempt == 1
        owner = registry.reserve(task.paper_id)
        assert registry.reserve(task.paper_id) is owner
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id, kind='legacy')
        with pytest.raises(InvalidPaperState):
            registry.admit(**args)
        registry.release(owner)
        registry.release(owner)
        legacy = registry.reserve(task.paper_id, kind='legacy')
        assert legacy.kind == 'legacy'
        registry.release(legacy)
        assert not registry.active
        with PaperRepository.open(path) as repository:
            assert len(repository.list_papers()) == 1
            assert repository.get(task.paper_id).collection.attempt == 1
    finally:
        registry.shutdown()
        registry.join()


def test_failure_retains_incremental_results_and_occupancy_until_cleanup_then_retries_only_failed(tmp_path):
    path = workspace(tmp_path)
    entered, release = Event(), Event()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))

    def success(context):
        context.emit(MetadataDelta(abstract='Kept after failure'), sequence=1)

    def failure(_):
        raise ValueError('controlled failure')

    def cleanup(_):
        entered.set()
        assert release.wait(3)

    try:
        task = submit(registry, 'failed', [BranchSpec('success', success), BranchSpec('failure', failure), BranchSpec('cleanup', cleanup)])
        assert entered.wait(2)
        with PaperRepository.open(path) as repository:
            paper = repository.get(task.paper_id)
            assert paper.metadata.abstract == 'Kept after failure'
            assert paper.collection_status == 'running'
            assert {b.name: b.state for b in paper.collection.branches} == {
                'success': 'completed', 'failure': 'failed', 'cleanup': 'queued'}
        assert registry.cleanup_pending(task.paper_id, registry.workspace_id)
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
        with pytest.raises(InvalidPaperState):
            registry.retry(task.paper_id, branches=[BranchSpec('failure', lambda _: None)])
        release.set()
        assert task.future.result(3).collection_status == 'failed'
        assert submit(registry, 'failed', [BranchSpec('failure', lambda _: None)]).collection_status == 'failed'
        retried = registry.retry(task.paper_id, branches=[
            BranchSpec('success', lambda _: pytest.fail('successful branch was repeated')),
            BranchSpec('failure', lambda _: MetadataDelta(ordinary_dates=('2026-11-13',))),
            BranchSpec('cleanup', lambda _: pytest.fail('settled cleanup branch was repeated'))])
        paper = retried.future.result(3)
        assert paper.collection_status == 'completed'
        assert paper.collection.attempt == 2
        assert paper.metadata.abstract == 'Kept after failure'
        assert paper.metadata.ordinary_dates == ('2026-11-13',)
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_empty_missing_and_skipped_plans_are_distinct(tmp_path):
    registry = WorkspaceRegistry(workspace(tmp_path), factory=IndependentClientFactory(tmp_path / 'config.yaml'))
    try:
        with pytest.raises(ValueError, match='no_applicable'):
            submit(registry, 'undeclared', [])
        assert submit(registry, 'none', [], no_applicable=True).future.result(3).collection_status == 'completed'
        assert submit(registry, 'missing', [BranchSpec('missing')]).future.result(3).collection_status == 'failed'
        skipped = submit(registry, 'skipped', [BranchSpec('na', skip_reason='No DOI for this source')]).future.result(3)
        assert skipped.collection_status == 'completed'
        assert skipped.collection.branches[0].state == 'skipped'
    finally:
        registry.shutdown()
        registry.join()


class Authority:
    def __init__(self, service_id=None):
        self.service_id = service_id
        self.service_scope = f'config/service/{service_id}' if service_id else None
        self.revoked = Event()

    def verify(self):
        if self.revoked.is_set():
            raise ValueError('access revoked')


def test_queued_cancel_and_expiry_never_create_clients_or_native_pages(tmp_path):
    path = workspace(tmp_path)
    entered, release = Event(), Event()
    factory = IndependentClientFactory(tmp_path / 'config.yaml')
    registry = WorkspaceRegistry(path, factory=factory, limit=1, group_limit=1)

    def block(_):
        entered.set()
        assert release.wait(3)

    try:
        first = submit(registry, 'held', [BranchSpec('held', block)])
        assert entered.wait(2)
        cancelled = submit(registry, 'cancelled', [BranchSpec('late', lambda _: pytest.fail('cancelled started'))])
        expired = submit(registry, 'expired', [BranchSpec('late', lambda _: pytest.fail('expired started'))],
                         deadline=time.monotonic() + .03)
        assert registry.cancel_paper(cancelled.paper_id, cancelled.workspace_id)
        assert cancelled.future.result(2).collection_status == 'cancelled'
        assert expired.future.result(2).collection_status == 'cancelled'
        assert not first.future.done()
        release.set()
        assert first.future.result(3).collection_status == 'completed'
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_reject_restore_blocks_old_writes_and_occupancy_until_actual_worker_exit(tmp_path):
    path = workspace(tmp_path)
    entered, release = Event(), Event()
    contexts = []
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))

    def collect(context):
        contexts.append(context)
        context.emit(MetadataDelta(abstract='Before reject'), sequence=1)
        entered.set()
        assert release.wait(3)
        context.emit(MetadataDelta(abstract='After restore'), sequence=2)

    try:
        task = submit(registry, 'reject', [BranchSpec('metadata', collect)])
        assert entered.wait(2)
        with PaperRepository.open(path) as repository:
            paper = repository.exclude(repository.get(task.paper_id).token)
        assert paper.excluded
        registry.cancel_paper(task.paper_id, task.workspace_id)
        with PaperRepository.open(path) as repository:
            paper = repository.restore(repository.get(task.paper_id).token)
            assert not paper.excluded
            with pytest.raises(InvalidPaperState):
                repository.clear_metadata(paper.token)
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
        # A separate Paper still writes while the first Paper cleans up.
        other = submit(registry, 'unrelated', [BranchSpec('metadata', lambda _: MetadataDelta(abstract='Other'))])
        assert other.future.result(3).metadata.abstract == 'Other'
        release.set()
        assert task.future.result(3).collection_status == 'cancelled'
        retry = registry.retry(task.paper_id, branches=[BranchSpec('metadata', lambda _: MetadataDelta(ordinary_dates=('2026-11',)))])
        assert retry.future.result(3).collection.attempt == 2
        with pytest.raises(StaleWriteError):
            contexts[0].emit(MetadataDelta(ordinary_dates=('2025-01-01',)), sequence=3)
        with PaperRepository.open(path) as repository:
            paper = repository.get(task.paper_id)
            assert paper.metadata.abstract == 'Before reject'
            assert paper.metadata.ordinary_dates == ('2026-11',)
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_duplicate_branch_delivery_does_not_refill_later_manual_abstract_clear(tmp_path):
    path = workspace(tmp_path)
    entered, release = Event(), Event()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))

    def collect(context):
        context.emit(MetadataDelta(abstract='First'), sequence=1)
        entered.set()
        assert release.wait(3)
        context.emit(MetadataDelta(abstract='First'), sequence=1)
        context.emit(MetadataDelta(ordinary_dates=('2026-11-13',)), sequence=2)

    try:
        task = submit(registry, 'duplicate', [BranchSpec('metadata', collect)])
        assert entered.wait(2)
        with PaperRepository.open(path) as repository:
            repository.edit_metadata(repository.get(task.paper_id).token, {'abstract': None})
        release.set()
        paper = task.future.result(3)
        assert paper.collection_status == 'completed'
        assert paper.metadata.abstract is None
        assert paper.metadata.ordinary_dates == ('2026-11-13',)
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_service_shared_owners_and_selective_cancellation_do_not_touch_api_work(tmp_path):
    path = workspace(tmp_path)
    release, a_started, b_started, api_started = Event(), Event(), Event(), Event()
    lock = BrowserTaskLock()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        browser_lock=lock, authority_capture=lambda service_id, providers: Authority(service_id))

    def held(started):
        def collect(_):
            started.set()
            assert release.wait(3)
        return collect

    try:
        a = submit(registry, 'service-a1', [BranchSpec('work', held(a_started))], service_id='a')
        b = submit(registry, 'service-a2', [BranchSpec('work', held(b_started))], service_id='a')
        api = submit(registry, 'api', [BranchSpec('work', held(api_started))])
        assert a_started.wait(2) and b_started.wait(2) and api_started.wait(2)
        assert len(registry.browser_owner_ids) == 2
        assert api.browser_owner is None
        assert lock.acquire('login', scopes=('config/service/a',)) is None
        independent = lock.acquire('login', scopes=('config/service/b',))
        assert independent is not None
        lock.release(independent)
        captured = registry.cancel_services((), all_access=True)
        assert set(captured) == {a, b}
        assert not api.cancel_event.is_set()
        release.set()
        assert a.future.result(3).collection_status == b.future.result(3).collection_status == 'cancelled'
        assert api.future.result(3).collection_status == 'completed'
        assert not registry.browser_owner_ids
        assert not lock.owners
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_recheck_authority_at_register_and_dispatch_prevents_late_execution(tmp_path):
    path = workspace(tmp_path)
    authority = Authority('a')
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        authority_capture=lambda service_id, providers: authority, limit=1, group_limit=1)
    try:
        task = registry.admit(direct_ids=ExternalIds(doi='10.1234/revoked'),
            metadata=PaperMetadata(title='Revoked'), service_id='a',
            branches=[BranchSpec('late', lambda _: pytest.fail('revoked started'))])
        authority.revoked.set()
        assert registry.register(task).future.result(3).collection_status == 'failed'
        assert not registry.active
    finally:
        registry.shutdown()
        registry.join()


class NativeBridge:
    """Transport seam with independently delivered actual native terminal results."""
    connected = True

    def __init__(self):
        self.operation, self.release = Future(), Future()
        self.started, self.cancelled, self.releasing = Event(), Event(), Event()
        self.identities = []

    def execute(self, action, data, progress=None, **kwargs):
        self.identities.append((action, data['workflow_id'], data['task_id']))
        if action == 'release_workflow_pages':
            self.releasing.set()
            return self.release
        self.started.set()
        return self.operation

    def cancel_task(self, workflow_id, task_id):
        self.identities.append(('cancel', workflow_id, task_id))
        self.cancelled.set()


def test_parent_deadline_cancels_exact_native_task_but_waits_terminal_and_page_release(tmp_path):
    path = workspace(tmp_path)
    bridge, lock = NativeBridge(), BrowserTaskLock()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        bridge=bridge, browser_lock=lock, authority_capture=lambda service_id, providers: Authority(service_id))
    protected = []

    def collect(context):
        protected.append(context.execute_native('controlled-probe', {}))

    join_finished = Event()
    try:
        task = submit(registry, 'native', [BranchSpec('native', collect)],
                      service_id='a', deadline=time.monotonic() + .15)
        assert bridge.started.wait(2)
        assert protected[0].cancel() is False
        assert bridge.cancelled.wait(2)
        assert task.cancel_event.is_set()
        assert not task.future.done()
        assert registry.busy(task.paper_id)
        assert lock.acquire('login', scopes=('config/service/a',)) is None
        bridge.operation.set_result({'ok': True})
        assert bridge.releasing.wait(2)
        assert not task.future.done()
        registry.shutdown()
        waiter = Thread(target=lambda: (registry.join(), join_finished.set()))
        waiter.start()
        assert not join_finished.wait(.03)
        bridge.release.set_result({'ok': True})
        waiter.join(3)
        assert join_finished.is_set()
        assert task.future.result(3).collection_status == 'cancelled'
        assert all(workflow == task.workflow_id and native_task == task.task_id
                   for _, workflow, native_task in bridge.identities)
        assert not lock.owners
        assert not registry.active
        registry.shutdown()
        registry.join()
    finally:
        if not bridge.operation.done():
            bridge.operation.set_result({'ok': True})
        if not bridge.release.done():
            bridge.release.set_result({'ok': True})
        registry.shutdown()
        registry.join()


def test_independent_client_survives_source_run_close_and_unrelated_paper_cancel(tmp_path, monkeypatch):
    from allfold.providers import integrated
    from http_test_helpers import http_server, isolate_proxy_environment

    isolate_proxy_environment(monkeypatch)
    path = workspace(tmp_path)
    request_started, response_release, collector_started, request_release = Event(), Event(), Event(), Event()

    def respond(_):
        request_started.set()
        assert response_release.wait(3)
        return 200, {}, b'{"abstract":"Independent HTTP result"}'

    with http_server(respond) as origin:
        monkeypatch.setitem(integrated.BASE_URLS, 'crossref', origin.url)
        source_factory = IndependentClientFactory(tmp_path / 'config.yaml')
        source_cancel = Event()
        with source_factory.open(cancel_event=source_cancel, request_guard=lambda: None,
                deadline=time.monotonic() + 5, providers=('crossref',)) as source:
            source_client = source.provider('crossref')
        source_factory.close()
        source_cancel.set()
        registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
            authority_capture=lambda service_id, providers: Authority(service_id))

        def collect(context):
            collector_started.set()
            assert request_release.wait(3)
            assert context.provider('crossref') is not source_client
            result = context.provider('crossref').request('/independent', {})
            context.emit(MetadataDelta(abstract=result['abstract']), sequence=1)

        try:
            task = submit(registry, 'http', [BranchSpec('metadata', collect, providers=('crossref',))], source_run_id='finished-source-run')
            assert collector_started.wait(2)
            unrelated = registry.admit(direct_ids=ExternalIds(doi='10.1234/unrelated-cancel'),
                metadata=PaperMetadata(title='Unrelated'), branches=[BranchSpec('unused', lambda _: None)])
            registry.cancel_paper(unrelated.paper_id)
            registry.register(unrelated).future.result(3)
            request_release.set()
            assert request_started.wait(2)
            assert not task.cancel_event.is_set()
            response_release.set()
            assert task.future.result(3).metadata.abstract == 'Independent HTTP result'
            assert [request.path for request in origin.requests] == ['/independent']
            with pytest.raises(integrated.Cancelled):
                source_client.request('/after-source-close', {})
        finally:
            response_release.set()
            request_release.set()
            registry.shutdown()
            registry.join()


class ClosingFactory:
    def __init__(self, config, *, fail=False):
        self.real = IndependentClientFactory(config)
        self.closing, self.release, self.closed = Event(), Event(), Event()
        self.fail = fail

    @contextmanager
    def open(self, **kwargs):
        try:
            with self.real.open(**kwargs) as clients:
                yield clients
        finally:
            self.closing.set()
            assert self.release.wait(4)
            self.closed.set()
            if self.fail:
                raise OSError('controlled client close failure')


def test_client_cleanup_and_terminal_write_fault_never_open_next_paper_qualification(tmp_path):
    path = workspace(tmp_path)
    factory = ClosingFactory(tmp_path / 'config.yaml')
    registry = WorkspaceRegistry(path, factory=factory)
    locker = None
    try:
        task = submit(registry, 'write-fault', [BranchSpec('metadata', lambda _: MetadataDelta(abstract='Committed first'))])
        assert factory.closing.wait(2)
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).metadata.abstract == 'Committed first'
        assert not task.future.done()
        locker = sqlite3.connect(path / 'papers.sqlite', isolation_level=None)
        locker.execute('BEGIN IMMEDIATE')
        factory.release.set()
        with pytest.raises(LibraryBusyError):
            task.future.result(5)
        assert factory.closed.is_set()
        assert registry.busy(task.paper_id)
        assert registry.faults[-1]['phase'] == 'terminal-write'
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
    finally:
        if locker is not None:
            locker.rollback()
            locker.close()
        factory.release.set()
        registry.shutdown()
        registry.join()


def test_cleanup_exception_is_exposed_and_retains_conservative_occupancy(tmp_path):
    path = workspace(tmp_path)
    factory = ClosingFactory(tmp_path / 'config.yaml', fail=True)
    registry = WorkspaceRegistry(path, factory=factory)
    try:
        task = submit(registry, 'cleanup-fault', [BranchSpec('metadata', lambda _: MetadataDelta(abstract='Committed'))])
        assert factory.closing.wait(2)
        factory.release.set()
        with pytest.raises(RuntimeError, match='disposal'):
            task.future.result(3)
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).collection_status == 'running'
            assert repository.get(task.paper_id).metadata.abstract == 'Committed'
        assert registry.active
        assert any(fault['phase'] == 'client-cleanup' for fault in registry.faults)
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
    finally:
        factory.release.set()
        registry.shutdown()
        registry.join()


def test_closed_factory_submission_failure_and_admit_shutdown_have_explicit_terminal_states(tmp_path, monkeypatch):
    path = workspace(tmp_path)
    factory = IndependentClientFactory(tmp_path / 'config.yaml')
    factory.close()
    registry = WorkspaceRegistry(path, factory=factory)
    try:
        task = submit(registry, 'construction-failed', [BranchSpec('never', lambda _: pytest.fail('closed factory executed'))])
        assert task.future.result(3).collection_status == 'failed'
        assert not registry.busy(task.paper_id)
    finally:
        registry.shutdown()
        registry.join()

    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))
    try:
        # Executor submission is the real platform boundary. No worker starts.
        def reject_submission(*args, **kwargs):
            raise RuntimeError('executor unavailable')
        monkeypatch.setattr(ThreadPoolExecutor, 'submit', reject_submission)
        task = submit(registry, 'submission-failed', [BranchSpec('never', lambda _: pytest.fail('submission failure executed'))])
        assert task.future.result(3).collection_status == 'failed'
        monkeypatch.undo()
        queued = registry.admit(direct_ids=ExternalIds(doi='10.1234/shutdown-gap'),
            metadata=PaperMetadata(title='Queued'), branches=[BranchSpec('never', lambda _: pytest.fail('shutdown gap executed'))])
        registry.shutdown()
        registry.join()
        assert registry.register(queued).future.result(3).collection_status == 'cancelled'
        assert not registry.active
    finally:
        registry.shutdown()
        registry.join()


def test_first_lifecycle_bind_interrupts_old_tasks_once_without_network_or_replay(tmp_path):
    from uuid import uuid4
    path = workspace(tmp_path)
    old_lifecycle = uuid4()
    with PaperRepository.open(path) as repository:
        admission = repository.admit_collection(repository.workspace_id, lifecycle_id=old_lifecycle,
            branches=('successful', 'unfinished'), direct_ids=ExternalIds(doi='10.1234/interrupted'),
            metadata=PaperMetadata(title='Interrupted'))
        repository.mark_collection_running(admission.token)
        repository.commit_collection_branch(admission.token, 'successful', sequence=1,
            delta=MetadataDelta(abstract='Durable increment'), outcome='completed')
        completed = repository.admit_collection(repository.workspace_id, lifecycle_id=old_lifecycle,
            branches=(), direct_ids=ExternalIds(doi='10.1234/previously-empty'), metadata=PaperMetadata(title='Empty'))
        repository.finish_collection(completed.token)
    factory = IndependentClientFactory(tmp_path / 'config.yaml')
    registry = WorkspaceRegistry(path, factory=factory)
    try:
        assert not registry.active
        with PaperRepository.open(path) as repository:
            interrupted = repository.get(admission.paper.id)
            assert interrupted.collection_status == 'failed'
            assert interrupted.collection.reason == 'interrupted'
            assert interrupted.metadata.abstract == 'Durable increment'
            assert {branch.name: branch.state for branch in interrupted.collection.branches} == {
                'successful': 'completed', 'unfinished': 'failed'}
            assert repository.get(completed.paper.id).collection_status == 'completed'
            with pytest.raises(StaleWriteError):
                repository.commit_collection_branch(admission.token, 'unfinished', sequence=1,
                    delta=MetadataDelta(abstract='Old late result'))
        # Repeated ordinary connections do not interrupt this lifecycle's work.
        entered, release = Event(), Event()
        def running(_):
            entered.set()
            assert release.wait(3)
        task = submit(registry, 'current-running', [BranchSpec('work', running)])
        assert entered.wait(2)
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).collection_status == 'running'
        release.set()
        assert task.future.result(3).collection_status == 'completed'
        assert submit(registry, 'interrupted', [BranchSpec('never', lambda _: pytest.fail('replayed'))]).collection_status == 'failed'
    finally:
        registry.shutdown()
        registry.join()


def test_shutdown_joins_legacy_actual_release_and_old_release_cannot_unseat_new_owner(tmp_path):
    path = workspace(tmp_path)
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))
    paper = submit(registry, 'reservation', [BranchSpec('empty', lambda _: None)]).future.result(3)
    old = registry.reserve(paper.id, kind='legacy')
    registry.release(old)
    current = registry.reserve(paper.id, kind='legacy')
    registry.release(old)
    assert registry.busy(paper.id)
    registry.shutdown()
    assert current.cancel_event.is_set()
    joined = Event()
    thread = Thread(target=lambda: (registry.join(), joined.set()))
    thread.start()
    try:
        assert not joined.wait(.03)
        registry.release(current)
        thread.join(3)
        assert joined.is_set()
        assert not registry.active
    finally:
        registry.release(current)
        thread.join(3)


def test_dynamic_registry_admits_new_service_during_work_and_reuses_idle_scheduler(tmp_path):
    path = workspace(tmp_path)
    first_started, release = Event(), Event()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        authority_capture=lambda service_id, providers: Authority(service_id), limit=1, group_limit=1)
    order = []

    def work(label, held=False):
        def collect(_):
            order.append(label)
            if held:
                first_started.set()
                assert release.wait(3)
            return MetadataDelta(abstract=label)
        return collect

    try:
        first = submit(registry, 'fair-first', [BranchSpec('work', work('first', True))], service_id='old')
        assert first_started.wait(2)
        old = [submit(registry, f'fair-old-{i}', [BranchSpec('work', work(f'old-{i}'))], service_id='old') for i in range(4)]
        new = submit(registry, 'fair-new', [BranchSpec('work', work('new'))], service_id='new')
        release.set()
        assert new.future.result(3).metadata.abstract == 'new'
        assert order.index('new') <= 2
        for task in (first, *old):
            assert task.future.result(3).collection_status == 'completed'
        later = submit(registry, 'fair-idle', [BranchSpec('work', work('after-idle'))])
        assert later.future.result(3).metadata.abstract == 'after-idle'
    finally:
        release.set()
        registry.shutdown()
        registry.join()


def test_collection_diagnostics_preserve_captured_attempt_and_source_without_history_growth(tmp_path):
    import io
    import json
    import zipfile
    from allfold.diagnostics import DiagnosticStore

    path = workspace(tmp_path)
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs')
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), diagnostics=store)
    try:
        task = submit(registry, 'diagnostic', [BranchSpec('empty', lambda _: None)], source_run_id='source-run')
        assert task.future.result(3).collection_status == 'completed'
        with zipfile.ZipFile(io.BytesIO(store.export())) as archive:
            events = [json.loads(line) for line in archive.read('events.jsonl').decode().splitlines()]
        collection = [event for event in events if event.get('kind') == 'collection']
        assert [event['collection_status'] for event in collection] == ['queued', 'completed']
        assert all(event['workspace_id'] == str(task.workspace_id) and event['paper_id'] == str(task.paper_id)
                   and event['attempt'] == 1 and event['parent_task_id'] == 'source-run' for event in collection)
        assert store.history()['records'] == []
    finally:
        registry.shutdown()
        registry.join()


def test_close_admission_does_not_cancel_until_shutdown_and_unregistered_cancel_settles(tmp_path):
    path = workspace(tmp_path)
    bridge = NativeBridge()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), bridge=bridge,
        authority_capture=lambda service_id, providers: Authority(service_id))
    try:
        task = registry.admit(direct_ids=ExternalIds(doi='10.1234/not-registered'), metadata=PaperMetadata(title='Unregistered'),
            service_id='a', branches=[BranchSpec('never', lambda _: pytest.fail('cancelled registration started'))])
        assert registry.cancel_services(('a',)) == (task,)
        assert task.future.result(3).collection_status == 'cancelled'
        assert registry.register(task) is task
        queued = registry.admit(direct_ids=ExternalIds(doi='10.1234/close-admission'), metadata=PaperMetadata(title='Close'),
            branches=[BranchSpec('never', lambda _: pytest.fail('closed admission started'))])
        bridge.cancelled.clear()
        registry.close_admission()
        assert registry.stopped
        assert not bridge.cancelled.is_set()
        assert not queued.cancel_event.is_set()
        registry.shutdown()
        registry.join()
        assert queued.future.result(3).collection_status == 'cancelled'
        assert bridge.cancelled.is_set()
        assert not registry.active
    finally:
        registry.shutdown()
        registry.join()


def test_existing_terminal_paper_reuses_without_capturing_irrelevant_new_authority(tmp_path):
    path = workspace(tmp_path)
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'))
    try:
        paper = submit(registry, 'reuse', [BranchSpec('empty', lambda _: None)]).future.result(3)
        reused = submit(registry, 'reuse', [BranchSpec('metadata', providers=('openalex',))], service_id='unprepared-service')
        assert reused.id == paper.id
        assert reused.collection_status == 'completed'
    finally:
        registry.shutdown()
        registry.join()


def test_reservation_projection_and_prepare_cancel_are_atomic_without_native_callbacks(tmp_path):
    path = workspace(tmp_path)
    bridge = NativeBridge()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), bridge=bridge,
        authority_capture=lambda service_id, providers: Authority(service_id))
    try:
        paper = submit(registry, 'projection', [BranchSpec('empty', lambda _: None)]).future.result(3)
        with PaperRepository.open(path) as repository:
            before = repository.revision
        claim = registry.reserve(paper.id, kind='legacy')
        with PaperRepository.open(path) as repository:
            assert repository.revision == before + 1
        registry.release(claim)
        with PaperRepository.open(path) as repository:
            assert repository.revision == before + 2
        registry.release(claim)
        with PaperRepository.open(path) as repository:
            assert repository.revision == before + 2
        task = registry.admit(direct_ids=ExternalIds(doi='10.1234/prepared-cancel'), metadata=PaperMetadata(title='Cancel'),
            service_id='a', branches=[BranchSpec('never', lambda _: pytest.fail('cancel preparation started'))])
        bridge.cancelled.clear()
        captured = registry.prepare_cancel_services(('a',))
        assert captured == (task,)
        assert task.cancel_event.is_set()
        assert not bridge.cancelled.is_set()
        assert not task.future.done()
        with PaperRepository.open(path) as repository:
            assert repository.get(task.paper_id).collection.cancel_requested
        registry.signal_cancel_targets(captured)
        assert bridge.cancelled.is_set()
        assert task.future.result(3).collection_status == 'cancelled'
    finally:
        registry.shutdown()
        registry.join()


def test_api_work_acquires_browser_owner_only_when_it_actually_dispatches_native(tmp_path):
    path = workspace(tmp_path)
    bridge, lock, entered, proceed = NativeBridge(), BrowserTaskLock(), Event(), Event()
    bridge.release.set_result({'ok': True})
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), bridge=bridge, browser_lock=lock)

    def collect(context):
        entered.set()
        assert proceed.wait(3)
        context.execute_native('controlled-probe', {})

    try:
        task = submit(registry, 'api-native', [BranchSpec('work', collect)])
        assert entered.wait(2)
        assert not lock.owners
        assert task.browser_owner is None
        credentials = lock.acquire('credentials')
        assert credentials is not None
        lock.release(credentials)
        proceed.set()
        assert bridge.started.wait(2)
        assert task.browser_owner is not None
        assert task.browser_owner.scopes == frozenset()
        assert lock.acquire('credentials') is None
        bridge.operation.set_result({'ok': True})
        assert task.future.result(3).collection_status == 'completed'
        assert not lock.owners
    finally:
        proceed.set()
        if not bridge.operation.done():
            bridge.operation.set_result({'ok': True})
        registry.shutdown()
        registry.join()


def test_base_is_queued_before_branch_authority_failure_and_independent_branch_survives(tmp_path):
    path = workspace(tmp_path)
    capturing, finish_capture, api_entered, api_release = Event(), Event(), Event(), Event()
    def capture(service_id, providers):
        if service_id:
            capturing.set()
            assert finish_capture.wait(3)
            raise InvalidPaperState('Service is not prepared')
        return Authority()
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        authority_capture=capture, limit=1, group_limit=1)
    def api(context):
        api_entered.set()
        assert api_release.wait(3)
        context.emit(MetadataDelta(abstract='Independent result'), sequence=1)
    try:
        task = submit(registry, 'authority-gap', [
            BranchSpec('document', lambda _: pytest.fail('unprepared document ran'), service_id='unprepared'),
            BranchSpec('api', api, service_id=None)])
        assert capturing.wait(2)
        assert api_entered.wait(2)
        with PaperRepository.open(path) as repository:
            paper = repository.get(task.paper_id)
            assert paper.metadata.title == 'Paper authority-gap'
            assert paper.collection.active
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
        assert registry.admit(direct_ids=ExternalIds(doi='10.1234/authority-gap'),
            metadata=PaperMetadata(title='Repeat'), branches=task.branches) is task
        finish_capture.set()
        api_release.set()
        failed = task.future.result(3)
        assert failed.collection_status == 'failed'
        assert failed.metadata.abstract == 'Independent result'
        assert {b.name: b.state for b in failed.collection.branches} == {'api': 'completed', 'document': 'failed'}
    finally:
        finish_capture.set()
        api_release.set()
        registry.shutdown()
        registry.join()


def test_retry_checks_only_pending_branch_dependencies_before_creating_attempt(tmp_path):
    path = workspace(tmp_path)
    revoked, captures = set(), []
    def capture(service_id, providers):
        captures.append((service_id, providers))
        if service_id in revoked:
            raise InvalidPaperState('Service unavailable')
        return Authority(service_id)
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'),
        authority_capture=capture)
    def failed(_):
        raise RuntimeError('Controlled API failure')
    plan = [BranchSpec('document', lambda _: MetadataDelta(ordinary_dates=('2026-11',)), service_id='publisher'),
            BranchSpec('api', failed, service_id=None)]
    try:
        task = submit(registry, 'retry-dependencies', plan)
        assert task.future.result(3).collection_status == 'failed'
        captures.clear()
        revoked.add('publisher')
        retry_plan = [plan[0], BranchSpec('api', lambda _: MetadataDelta(abstract='Retried API'), service_id=None)]
        qualified = registry.check_retry(task.paper_id, branches=retry_plan, expected_attempt=1)
        assert qualified.collection.attempt == 1
        assert captures == [(None, ())]
        retried = registry.retry(task.paper_id, branches=retry_plan, expected_attempt=1)
        assert retried.future.result(3).metadata.abstract == 'Retried API'
        assert all(service is None for service, _ in captures)
        with pytest.raises(InvalidPaperState):
            registry.check_retry(task.paper_id, branches=retry_plan, expected_attempt=2)
        # A currently unavailable pending dependency refuses without creating attempt 2.
        other = submit(registry, 'retry-denied', [BranchSpec('document', failed, service_id='other')])
        assert other.future.result(3).collection_status == 'failed'
        revoked.add('other')
        with pytest.raises(InvalidPaperState, match='unavailable'):
            registry.retry(other.paper_id, branches=[BranchSpec('document', failed, service_id='other')], expected_attempt=1)
        with PaperRepository.open(path) as repository:
            assert repository.get(other.paper_id).collection.attempt == 1
    finally:
        registry.shutdown()
        registry.join()


def test_same_paper_branches_overlap_with_thread_owned_client_cache_and_sqlite(tmp_path):
    from threading import get_ident
    path = workspace(tmp_path)
    first, second, release, first_closed, second_closed, finish_close = (Event() for _ in range(6))
    scopes = []
    real = IndependentClientFactory(tmp_path / 'config.yaml')
    class Factory:
        @contextmanager
        def open(self, **kwargs):
            with real.open(**kwargs) as clients:
                scopes.append((get_ident(), clients, clients.request_cache))
                yield clients
                (first_closed if scopes[0][1] is clients else second_closed).set()
                assert finish_close.wait(3)
    registry = WorkspaceRegistry(path, factory=Factory(),
        authority_capture=lambda service, providers: Authority(service), limit=1, group_limit=1)
    # Different execution groups allow a webpage and API to overlap even at one Paper worker.
    def collect(entered, abstract, dates):
        def run(context):
            entered.set()
            assert release.wait(3)
            assert context.read_paper().metadata.title == 'Paper branch-scopes'
            context.emit(MetadataDelta(abstract=abstract, ordinary_dates=dates), sequence=1)
        return run
    try:
        task = submit(registry, 'branch-scopes', [
            BranchSpec('document', collect(first, 'Document abstract', ('2026-11',)), service_id='publisher'),
            BranchSpec('api', collect(second, 'API abstract', ('2026-11-02',)), service_id=None)])
        assert first.wait(2) and second.wait(2)
        assert len(scopes) == 2 and scopes[0][0] != scopes[1][0]
        assert scopes[0][1] is not scopes[1][1] and scopes[0][2] is not scopes[1][2]
        release.set()
        assert first_closed.wait(2) and second_closed.wait(2)
        assert not task.future.done() and registry.busy(task.paper_id)
        with pytest.raises(InvalidPaperState):
            registry.reserve(task.paper_id)
        finish_close.set()
        finished = task.future.result(3)
        assert finished.collection_status == 'completed'
        assert finished.metadata.abstract in {'Document abstract', 'API abstract'}
        assert finished.metadata.ordinary_dates == ('2026-11-02',)
    finally:
        release.set(); finish_close.set()
        registry.shutdown(); registry.join(); real.close()


def test_deferred_intent_expires_without_revoking_original_manual_reservation(tmp_path):
    path = workspace(tmp_path)
    with PaperRepository.open(path) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.1234/deferred'),
            metadata=PaperMetadata(title='Manual')).paper
    registry = WorkspaceRegistry(path, factory=IndependentClientFactory(tmp_path / 'config.yaml'), limit=1, group_limit=1)
    reservation = registry.reserve(paper.id, kind='legacy')
    try:
        task = registry.submit(direct_ids=ExternalIds(doi='10.1234/deferred'), metadata=paper.metadata,
            branches=[BranchSpec('never', lambda _: pytest.fail('Expired intent executed'))],
            deadline=time.monotonic() + .1)
        assert task.future.result(3).collection_status == 'cancelled'
        assert not reservation.cancel_event.is_set()
        reservation.guard()
        with PaperRepository.open(path) as repository:
            repository.merge_metadata(reservation.token, MetadataDelta(abstract='Accepted manual result'))
        assert registry.busy(paper.id)
        with pytest.raises(InvalidPaperState):
            registry.reserve(paper.id)
        registry.release(reservation)
        assert not registry.busy(paper.id)
    finally:
        registry.release(reservation)
        registry.shutdown(); registry.join()
