"""Read-only PDF discovery over real Workspace/task/HTTP lifetimes."""
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
import time
import shutil

import httpx
import pytest

from allfold.application.collection_runtime import BranchSpec
from allfold.application.pdf_discovery import submit_pdf_discovery
from allfold.application.task_clients import IndependentClientFactory
from allfold.application.workspace_tasks import WorkspaceTaskHost
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.pdf_discovery import CandidateResult
from allfold.pdf_rules import PdfRuleInputs, PdfTarget
from allfold.models import ExternalIds
from allfold.persistence.library_models import MetadataDelta, PaperMetadata
from allfold.persistence.paper_repository import InvalidPaperState, PaperRepository, StaleWriteError
from safety_config_helpers import current_mapping_document


def setup_host(tmp_path, handler, **kwargs):
    config, _, _, _ = current_mapping_document(tmp_path)
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id,
            direct_ids=ExternalIds(doi='10.5555/task'), metadata=PaperMetadata(title='Saved Paper')).paper
    factory = IndependentClientFactory(config)
    host = WorkspaceTaskHost(config, factory=factory, **kwargs)
    options = {'transport': httpx.MockTransport(handler), 'resolver': lambda *_: ('93.184.216.34',)}
    return host, workspace, paper, options


def target(paper):
    return PdfTarget(str(paper.id), doi='10.5555/task', article_url='https://onlinelibrary.wiley.com/doi/10.5555/task',
        content_type='journal-article')


def test_doi_free_saved_work_complete_cache_uses_real_task_without_native_or_lookup(tmp_path):
    from allfold.persistence.run_library import metadata_from_run
    from allfold.canonicalize import canonicalize_records
    from allfold.providers.discovery_evidence import normalize_openalex
    from allfold.providers.integrated import SourceScope
    from test_pdf_source_facts import openalex_raw
    bridge = NativeBridge()
    requests = []
    def handler(request):
        requests.append(str(request.url))
        assert request.url.host == 'repository.example'
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    host, workspace, _, options = setup_host(tmp_path, handler, bridge=bridge)
    try:
        record = normalize_openalex(openalex_raw() | {'doi': None}, SourceScope('journal', 'Journal', issns=('0006-341X',)))
        canonical, = canonicalize_records((record,)).papers
        with PaperRepository.open(workspace) as repository:
            paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(openalex='W123'),
                metadata=metadata_from_run(canonical, records=(record,))).paper
        with pytest.raises(ValueError, match='direct identities'):
            submit_pdf_discovery(host, paper, target=PdfTarget(str(paper.id), direct_identities=(('openalex', 'W999'),)), http_options=options)
        task = submit_pdf_discovery(host, paper, target=PdfTarget(str(paper.id)), http_options=options,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True))
        result = task.future.result(3)
        assert (result.status, result.pdf_source, result.fallback_used) == ('transferred', 'P5', False)
        assert requests == ['https://repository.example/Best.PDF?version=2'] and bridge.calls == []
        with PaperRepository.open(workspace) as repository:
            after = repository.get(paper.id)
        assert (after.metadata, after.token, after.collection, after.body) == (paper.metadata, paper.token, paper.collection, None)
    finally:
        bridge.finish(); host.shutdown(); host.join()


@pytest.mark.parametrize('content_type', ['book', 'chapter', 'supplement'])
def test_task_rejects_explicit_unsupported_target_before_reservation_or_http(tmp_path, content_type):
    host, workspace, paper, options = setup_host(tmp_path, lambda _: pytest.fail('Unsupported target sent HTTP'))
    try:
        with pytest.raises(ValueError, match='content type'):
            submit_pdf_discovery(host, paper, target=replace(target(paper), content_type=content_type), http_options=options)
        assert not host.active
        with PaperRepository.open(workspace) as repository:
            assert repository.get(paper.id) == paper
    finally:
        host.shutdown(); host.join()


def test_completed_collection_uses_real_discovery_without_changing_collection_or_content(tmp_path):
    requests, received, threads = [], [], []
    def handler(request):
        requests.append(str(request.url))
        threads.append(threading.get_ident())
        return httpx.Response(200, headers={'content-type': 'application/pdf'}, content=b'controlled-transfer')
    host, workspace, paper, options = setup_host(tmp_path, handler)
    try:
        registry = host.current()
        completed = registry.submit(direct_ids=ExternalIds(doi='10.5555/task'), metadata=paper.metadata,
            branches=(BranchSpec('settled', lambda _: None),)).future.result(3)
        task = submit_pdf_discovery(host, completed, target=target(completed), http_options=options,
            transfer=lambda response, _: received.append(response.read()) or CandidateResult.pdf(transfer_complete=True))
        result = task.future.result(3)
        assert result.status == 'transferred' and result.pdf_source == 'P1'
        assert len(requests) == 1 and received == [b'controlled-transfer']
        assert threads[0] != threading.get_ident()
        with PaperRepository.open(workspace) as repository:
            after = repository.get(paper.id)
        assert after.collection == completed.collection and after.token == completed.token
        assert after.metadata == completed.metadata and after.body is None
        assert not host.cleanup_pending(paper.id, paper.workspace_id)
    finally:
        host.shutdown(); host.join()


class ClosingTransport(httpx.MockTransport):
    def __init__(self, handler, *, failure=False):
        super().__init__(handler)
        self.cleaning, self.finish = threading.Event(), threading.Event()
        self.failure = failure

    def close(self):
        self.cleaning.set()
        assert self.finish.wait(4)
        if self.failure:
            raise OSError('Controlled HTTP transport close failure')
        super().close()


def test_cancelled_http_worker_keeps_occupancy_until_owned_clients_really_close(tmp_path):
    entered, response = threading.Event(), threading.Event()
    def handler(request):
        entered.set()
        assert response.wait(4)
        return httpx.Response(404)
    host, _, paper, options = setup_host(tmp_path, handler)
    transport = ClosingTransport(handler)
    options['transport'] = transport
    try:
        task = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
        assert entered.wait(2)
        registry = host.current()
        captured = registry.prepare_cancel_paper(paper.id, paper.workspace_id)
        registry.signal_cancel_targets(captured)
        response.set()
        assert transport.cleaning.wait(2)
        assert host.active and not task.future.done()
        assert not task.future.cancel()
        with pytest.raises(InvalidPaperState):
            registry.reserve(paper.id, kind='legacy')
        transport.finish.set()
        assert task.future.result(3).status == 'cancelled'
        assert not host.active
    finally:
        response.set(); transport.finish.set()
        host.shutdown(); host.join()


class NativeBridge:
    def __init__(self):
        self.operation, self.cleanup = Future(), Future()
        self.started, self.cleaning = threading.Event(), threading.Event()
        self.calls, self.cancellations = [], []

    def execute(self, action, data, *args, **kwargs):
        self.calls.append((action, data, kwargs))
        if action == 'release_workflow_pages':
            self.cleaning.set()
            return self.cleanup
        self.started.set()
        return self.operation

    def cancel_task(self, workflow_id, task_id):
        self.cancellations.append((workflow_id, task_id))

    def finish(self):
        if not self.operation.done():
            self.operation.set_result(native_envelope())
        if not self.cleanup.done():
            self.cleanup.set_result({'released': True})


@pytest.mark.parametrize('oce_access', [False, True])
def test_lww_empty_viewer_uses_only_independent_captured_oce_preparation(tmp_path, oce_access):
    from allfold.application.coordinators.login import LoginCoordinator
    from allfold.application.browser_services import BrowserServiceSnapshot
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.pdf_facts import PdfDiscoveryFacts, PdfIdentifier, openalex_discovery_facts
    from datetime import datetime, timezone
    from test_login import Native, opened
    from test_document_metadata import envelope, pdf_clues
    class OceBridge:
        calls = []
        def execute(self, action, data, *args, **kwargs):
            self.calls.append((action, data))
            future = Future()
            if action == 'release_workflow_pages':
                value = {'released': True}
            elif data.get('reader_access_only'):
                value = {'outcome': 'retrieved', 'reader_access': {'oce': oce_access}}
            else:
                platform = data['reader']['platform']
                value = envelope() | {'pdf_clues': pdf_clues(platform=platform, landing_url=data['reader']['url'],
                    candidates=[] if platform == 'lww' else [{'stage': 'P4', 'rule_id': 'R060',
                        'url': 'https://assets.ovid.com/Body.PDF?Signature=A%2FB&key=Keep'}])}
            future.set_result(value)
            return future
        def cancel_task(self, *_):
            pass
    seen = []
    def handler(request):
        seen.append(str(request.url))
        if request.url.host == 'journals.lww.com':
            return httpx.Response(200, headers={'Content-Type': 'text/html'}, content=b'<body>Empty viewer</body>')
        assert request.url.host == 'assets.ovid.com'
        return httpx.Response(200, headers={'Content-Type': 'application/pdf'})
    native, bridge, lock = Native(), OceBridge(), BrowserTaskLock()
    login = LoginCoordinator(native, lock)
    host, workspace, paper, options = setup_host(tmp_path, handler, bridge=bridge, login=login, browser_lock=lock)
    # A CARSI entry URL/name supplies no OCE permission. Only the bounded
    # native capability of this captured prepared target can supply it.
    saved = load_user_state(host.config_path)
    compare_write_user_state(host.config_path, replace(saved.state, access_services=tuple(
        s.model_copy(update={'access_method': 'manual', 'access_url': 'https://ds.carsi.edu.cn/resource/entry'})
        for s in saved.state.access_services)), saved.revision)
    service_id = BrowserServiceSnapshot.read(host.config_path).services[0].id
    login.start(host.config_path, manual_service_id=service_id)
    _, _, ready = native.operations.get(timeout=2);ready.set_result(opened(17));login.join()
    try:
        article_url = 'https://journals.lww.com/journal/fulltext/2026/paper.aspx'
        facts = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
            observed_at=datetime.now(timezone.utc), target_doi='10.5555/task', landing_url=article_url,
            platform='lww', identifiers=(PdfIdentifier(kind='an', value='22222222-222222222-22222', rule_id='R060'),))
        with PaperRepository.open(workspace) as repository:
            empty = openalex_discovery_facts({'doi': '10.5555/task', 'best_oa_location': None, 'locations': []}, datetime.now(timezone.utc))
            paper = repository.merge_metadata(paper.token, MetadataDelta(discovery_facts=(facts, empty)))
        task = submit_pdf_discovery(host, paper, target=PdfTarget(str(paper.id), doi='10.5555/task', article_url=article_url),
            service_id=service_id, http_options=options, transfer=lambda *_: CandidateResult.pdf(transfer_complete=True))
        result = task.future.result(3)
        readers = [data['reader']['platform'] for _, data in bridge.calls if 'reader' in data]
        assert readers == (['lww', 'oce'] if oce_access else ['lww'])
        assert sum(data.get('reader_access_only', False) for _, data in bridge.calls) == 1
        assert len(seen) == (2 if oce_access else 1)
        assert (result.status, result.pdf_source, result.fallback_used) == (
            ('transferred', 'P4', True) if oce_access else ('exhausted', None, False))
        assert all(data['service_id'] == service_id and data['target_page_id'] == 17
            for action, data in bridge.calls if action != 'release_workflow_pages')
    finally:
        host.shutdown();host.join()


def native_target(paper):
    return replace(target(paper), article_url='https://www.mdpi.com/1/2/3')


def native_envelope():
    from test_document_metadata import envelope, pdf_clues
    return envelope() | {'pdf_clues': pdf_clues(platform='mdpi', landing_url='https://www.mdpi.com/1/2/3',
        candidates=[{'stage': 'P3', 'rule_id': 'GENERIC', 'url': 'https://www.mdpi.com/1/2/3/pdf',
                     'field': 'citation_pdf_url'}])}


def test_pdf_only_native_pipeline_uses_captured_identity_and_waits_exact_page_cleanup(tmp_path):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'application/pdf'})
    bridge, browser_lock = NativeBridge(), BrowserTaskLock()
    host, workspace, paper, options = setup_host(tmp_path, handler, bridge=bridge, browser_lock=browser_lock)
    try:
        task = submit_pdf_discovery(host, paper, target=native_target(paper), http_options=options,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True))
        assert bridge.started.wait(2)
        action, payload, callbacks = bridge.calls[0]
        assert action == 'extract_paper_pdf_clues'
        assert payload['identity'] == {'doi': '10.5555/task', 'confirmed_article_url': 'https://www.mdpi.com/1/2/3'}
        assert payload['paper_id'] == str(paper.id)
        assert (payload['workflow_id'], payload['task_id']) == (task.workflow_id, task.task_id)
        assert len(payload['workspace_identity']) == 64 and 'wantAbstract' not in payload
        callbacks['verify_recovery']()
        bridge.operation.set_result(native_envelope())
        assert bridge.cleaning.wait(2)
        assert requests == ['https://www.mdpi.com/1/2/3/pdf']
        assert host.browser_owner_ids and host.active and not task.future.done()
        bridge.cleanup.set_result({'released': True})
        assert task.future.result(3).status == 'transferred'
        assert not host.active and not browser_lock.owners
        with PaperRepository.open(workspace) as repository:
            after = repository.get(paper.id)
        assert after.metadata == paper.metadata and after.collection == paper.collection and after.token == paper.token
        assert [call[0] for call in bridge.calls] == ['extract_paper_pdf_clues', 'release_workflow_pages']
    finally:
        bridge.finish(); host.shutdown(); host.join()


def test_primary_doi_is_used_even_when_an_alias_sorts_first_in_direct_identities(tmp_path):
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'application/pdf'})
    bridge = NativeBridge()
    host, workspace, paper, options = setup_host(tmp_path, handler, bridge=bridge)
    try:
        with PaperRepository.open(workspace) as repository:
            paper = repository.merge_metadata(paper.token, MetadataDelta(), direct_ids=ExternalIds(doi='10.1111/alias'))
        assert paper.identities[0].value == '10.1111/alias' and paper.primary_identity.value == '10.5555/task'
        with pytest.raises(ValueError, match='DOI'):
            submit_pdf_discovery(host, paper, target=replace(native_target(paper), doi='10.1111/alias'), http_options=options)
        task = submit_pdf_discovery(host, paper, target=native_target(paper), http_options=options)
        assert bridge.started.wait(2)
        assert bridge.calls[0][1]['identity']['doi'] == '10.5555/task'
        bridge.finish()
        assert task.future.result(3).status == 'pending'
        assert requests == ['https://www.mdpi.com/1/2/3/pdf']
    finally:
        bridge.finish(); host.shutdown(); host.join()


def test_reject_restore_invalidates_original_token_and_delayed_signal_cannot_cancel_replacement(tmp_path):
    first, second, finish_first, finish_second = (threading.Event() for _ in range(4))
    requests = []
    def handler(request):
        requests.append(str(request.url))
        if len(requests) == 1:
            first.set(); assert finish_first.wait(4)
        else:
            second.set(); assert finish_second.wait(4)
        return httpx.Response(200, headers={'content-type': 'application/pdf'})
    bridge = NativeBridge()
    host, workspace, paper, options = setup_host(tmp_path, handler, bridge=bridge)
    try:
        old = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
        assert first.wait(2)
        registry = host.current()
        with registry.paper_gate(), PaperRepository.open(workspace) as repository:
            excluded = repository.exclude(paper.token)
            captured = registry.prepare_cancel_paper(paper.id, paper.workspace_id)
            restored = repository.restore(excluded.token)
        assert restored.token != old.token
        with pytest.raises(InvalidPaperState):
            submit_pdf_discovery(host, restored, target=target(restored), http_options=options)
        finish_first.set()
        assert old.future.result(3).status == 'cancelled'
        replacement = submit_pdf_discovery(host, restored, target=target(restored), http_options=options)
        assert second.wait(2)
        registry.signal_cancel_targets(captured)
        assert bridge.cancellations[-1] == (old.workflow_id, old.task_id)
        assert not replacement.cancel_event.is_set()
        finish_second.set()
        assert replacement.future.result(3).status == 'pending'
        assert len(requests) == 2
        with PaperRepository.open(workspace) as repository:
            assert repository.get(paper.id).metadata == paper.metadata
    finally:
        finish_first.set(); finish_second.set(); bridge.finish(); host.shutdown(); host.join()


def test_real_provider_credential_change_revokes_inflight_task_without_fallback(tmp_path):
    from allfold.integrations.openalex_credentials import write_credential
    entered, finish = threading.Event(), threading.Event()
    requests = []
    def handler(request):
        requests.append(str(request.url)); entered.set()
        assert finish.wait(4)
        return httpx.Response(404)
    host, _, paper, options = setup_host(tmp_path, handler)
    try:
        task = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
        assert entered.wait(2)
        write_credential(host.config_path, action='replace', key='synthetic-task-key', revision='missing')
        finish.set()
        assert task.future.result(3).status == 'stale'
        assert len(requests) == 1 and not host.active
    finally:
        finish.set(); host.shutdown(); host.join()


@pytest.mark.parametrize('scope', ['service', 'provider', 'all-access'])
def test_scoped_maintenance_sees_api_only_reservation_and_waits_outside_write_locks(tmp_path, scope):
    from allfold.application.browser_services import BrowserServiceSnapshot
    from allfold.application.coordinators.login import LoginCoordinator
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from test_login import Native, opened
    entered, response = threading.Event(), threading.Event()
    def handler(request):
        entered.set(); assert response.wait(4)
        return httpx.Response(404)
    lock, native = BrowserTaskLock(), Native()
    login = LoginCoordinator(native, lock)
    host, _, paper, options = setup_host(tmp_path, handler, browser_lock=lock, login=login)
    transport = ClosingTransport(handler)
    options['transport'] = transport
    saved = load_user_state(host.config_path)
    compare_write_user_state(host.config_path, replace(saved.state, access_services=tuple(
        service.model_copy(update={'access_method': 'manual', 'access_url': 'https://library.example.org/'})
        for service in saved.state.access_services)), saved.revision)
    service_id = BrowserServiceSnapshot.read(host.config_path).services[0].id
    login.start(host.config_path, manual_service_id=service_id)
    _, _, ready = native.operations.get(timeout=2)
    ready.set_result(opened(17)); login.join()
    try:
        task = submit_pdf_discovery(host, paper, target=target(paper), service_id=service_id, http_options=options)
        assert entered.wait(2) and host.browser_owner_ids
        registry = host.current()
        change = host.begin_change(services=(service_id,) if scope == 'service' else (),
            providers=('openalex',) if scope == 'provider' else (), all_access=scope == 'all-access')
        assert change.targets == (task,)
        with ThreadPoolExecutor(max_workers=1) as pool:
            drained = pool.submit(host.drain_change, change)
            assert task.cancel_event.wait(2)
            response.set(); assert transport.cleaning.wait(2)
            assert not drained.done() and host.cleanup_pending(paper.id, paper.workspace_id)
            assert host.settings_lock.acquire(timeout=1)
            host.settings_lock.release()
            assert registry.paper_gate().acquire(timeout=1)
            registry.paper_gate().release()
            transport.finish.set(); drained.result(3)
        assert task.future.result(3).status == 'cancelled' and not host.active
        assert not lock.owners
        host.finish_change(change)
    finally:
        response.set(); transport.finish.set(); host.shutdown(); host.join()


def test_provider_maintenance_discards_queued_discovery_without_opening_clients_or_restarting_collection(tmp_path):
    entered, finish = [threading.Event(), threading.Event()], threading.Event()
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'application/pdf'})
    host, workspace, paper, options = setup_host(tmp_path, handler)
    try:
        registry = host.current()
        def occupy(index):
            def run(context):
                entered[index].set(); assert finish.wait(4)
            return run
        others = [registry.submit(direct_ids=ExternalIds(doi=f'10.5555/block-{index}'),
            metadata=PaperMetadata(title='Other Paper'), branches=(BranchSpec('blocking', occupy(index)),))
            for index in range(2)]
        assert all(event.wait(2) for event in entered)
        task = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
        change = host.begin_change(providers=('openalex',))
        assert change.targets == (task,)
        host.drain_change(change)
        assert task.future.result(3).status == 'cancelled' and requests == []
        assert all(not other.future.done() and not other.cancel_event.is_set() for other in others)
        host.finish_change(change)
        with PaperRepository.open(workspace) as repository:
            after = repository.get(paper.id)
        assert after.collection is None and after.metadata == paper.metadata
    finally:
        finish.set(); host.shutdown(); host.join()


@pytest.mark.parametrize('operation', ['reset', 'switch'])
def test_whole_workspace_maintenance_waits_native_cleanup_before_rebinding(tmp_path, operation):
    bridge, lock = NativeBridge(), BrowserTaskLock()
    requests = []
    def handler(request):
        requests.append(str(request.url))
        return httpx.Response(200, headers={'content-type': 'application/pdf'})
    host, workspace, paper, options = setup_host(tmp_path, handler, bridge=bridge, browser_lock=lock)
    try:
        task = submit_pdf_discovery(host, paper, target=native_target(paper), http_options=options)
        assert bridge.started.wait(2)
        old_registry = host.current()
        change = host.begin_change(whole=True)
        with ThreadPoolExecutor(max_workers=1) as pool:
            draining = pool.submit(host.drain_change, change)
            assert task.cancel_event.wait(2)
            bridge.operation.set_result(native_envelope())
            assert bridge.cleaning.wait(2)
            assert not draining.done() and workspace.exists() and lock.owners
            assert host.settings_lock.acquire(timeout=1)
            host.settings_lock.release()
            with PaperRepository.open(workspace) as repository:
                assert repository.get(paper.id).metadata == paper.metadata
            bridge.cleanup.set_result({'released': True}); draining.result(3)
        assert task.future.result(3).status == 'cancelled' and not requests
        if operation == 'reset':
            shutil.rmtree(workspace)
            workspace.mkdir()
            replacement = workspace
        else:
            replacement = tmp_path / 'other-workspace'
            replacement.mkdir()
            host.config_path.write_text(host.config_path.read_text().replace('output_dir: workspace', 'output_dir: other-workspace'))
        with PaperRepository.create(replacement) as repository:
            new_workspace_id = repository.workspace_id
        host.finish_change(change)
        assert host.current().workspace_id == new_workspace_id != old_registry.workspace_id
        assert old_registry.stopped and not old_registry.active and not lock.owners
        with pytest.raises(StaleWriteError, match='Workspace'):
            submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
    finally:
        bridge.finish(); host.shutdown(); host.join()


def test_shutdown_waits_real_native_terminal_and_cleanup_before_closing_factory(tmp_path):
    bridge = NativeBridge()
    host, _, paper, options = setup_host(tmp_path, lambda _: httpx.Response(404), bridge=bridge)
    try:
        task = submit_pdf_discovery(host, paper, target=native_target(paper), http_options=options)
        assert bridge.started.wait(2)
        host.shutdown()
        assert task.cancel_event.is_set()
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(host.join)
            bridge.operation.set_result(native_envelope())
            assert bridge.cleaning.wait(2)
            assert not task.future.done() and not joining.done() and host.active
            bridge.cleanup.set_result({'released': True}); joining.result(3)
        assert task.future.result(3).status == 'cancelled' and not host.active
        assert bridge.cancellations == [(task.workflow_id, task.task_id)]
        with pytest.raises(RuntimeError, match='closed'):
            with host.factory.open_pdf_discovery(cancel_event=threading.Event(), request_guard=lambda: None,
                    deadline=time.monotonic() + 10, http_options=options):
                pytest.fail('Shutdown factory admitted a new client scope')
    finally:
        bridge.finish(); host.shutdown(); host.join()


@pytest.mark.parametrize('resource', ['client', 'native'])
def test_unconfirmed_cleanup_is_a_fault_and_keeps_paper_occupied(tmp_path, resource):
    bridge = NativeBridge() if resource == 'native' else None
    host, _, paper, options = setup_host(tmp_path,
        lambda _: httpx.Response(200, headers={'content-type': 'application/pdf'}), bridge=bridge)
    if resource == 'client':
        transport = ClosingTransport(lambda _: httpx.Response(200, headers={'content-type': 'application/pdf'}), failure=True)
        transport.finish.set(); options['transport'] = transport
    task = submit_pdf_discovery(host, paper, target=native_target(paper) if bridge else target(paper), http_options=options)
    if bridge:
        assert bridge.started.wait(2)
        bridge.operation.set_result(native_envelope())
        assert bridge.cleaning.wait(2)
        bridge.cleanup.set_exception(RuntimeError('Controlled native page cleanup failure'))
    with pytest.raises((RuntimeError, OSError), match='[Cc]ontrolled'):
        task.future.result(3)
    registry = host.current()
    assert registry.busy(paper.id) and task.cleanup_failed and task.cleanup_ended
    assert registry.faults[-1]['phase'] == f'discovery-{resource}-cleanup'
    with pytest.raises(InvalidPaperState):
        registry.reserve(paper.id, kind='legacy')
    host.shutdown()
    with pytest.raises(RuntimeError, match='could not be settled'):
        host.join()


def test_cleared_metadata_invalidates_original_task_without_any_late_write_or_fallback(tmp_path):
    entered, finish = threading.Event(), threading.Event()
    requests = []
    def handler(request):
        requests.append(str(request.url)); entered.set(); assert finish.wait(4)
        return httpx.Response(404)
    host, workspace, paper, options = setup_host(tmp_path, handler)
    try:
        task = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
        assert entered.wait(2)
        with PaperRepository.open(workspace) as repository:
            rejected = repository.exclude(paper.token)
            cleared = repository.clear_metadata(rejected.token)
        finish.set()
        assert task.future.result(3).status == 'stale' and len(requests) == 1
        with PaperRepository.open(workspace) as repository:
            after = repository.get(paper.id)
        assert after.token == cleared.token and after.metadata is None and not host.active
    finally:
        finish.set(); host.shutdown(); host.join()


def test_replaced_workspace_path_cannot_renew_authority_or_release_into_replacement_library(tmp_path):
    entered, finish = threading.Event(), threading.Event()
    requests = []
    def handler(request):
        requests.append(str(request.url)); entered.set(); assert finish.wait(4)
        return httpx.Response(404)
    host, workspace, paper, options = setup_host(tmp_path, handler)
    task = submit_pdf_discovery(host, paper, target=target(paper), http_options=options)
    try:
        assert entered.wait(2)
        workspace.rename(tmp_path / 'original-workspace')
        workspace.mkdir()
        with PaperRepository.create(workspace) as repository:
            replacement_id = repository.workspace_id
        finish.set()
        with pytest.raises(StaleWriteError, match='replaced'):
            task.future.result(3)
        registry = host.peek()
        assert registry.active and registry.faults[-1]['phase'] == 'reservation-release'
        assert task.cleanup_ended and not task.released and len(requests) == 1
        with PaperRepository.open(workspace) as repository:
            assert repository.workspace_id == replacement_id and repository.list_papers() == ()
    finally:
        finish.set(); host.shutdown()
        with pytest.raises(RuntimeError, match='could not be settled'):
            host.join()


@pytest.mark.parametrize('phase', ['P1', 'P2', 'unavailable'])
def test_factory_keeps_optional_pdf_credentials_and_redirect_limit_out_of_openalex_options(tmp_path, caplog, phase):
    secret, requests = 'controlled-wiley-only-secret', []
    def handler(request):
        requests.append(request)
        if request.url.host == 'api.wiley.com':
            assert request.headers.get('Wiley-TDM-Client-Token') == secret
            return httpx.Response(200, headers={'content-type': 'application/pdf'})
        assert secret not in str(request.url) and secret not in str(request.headers)
        if phase == 'P1' and request.url.host == 'onlinelibrary.wiley.com':
            return httpx.Response(200, headers={'content-type': 'application/pdf'})
        return httpx.Response(404)
    host, _, paper, options = setup_host(tmp_path, handler)
    options['max_redirects'] = 6
    if phase != 'unavailable':
        options['credentials'] = (('wiley_tdm', secret),)
    selected = target(paper)
    inputs = PdfRuleInputs(selected, conditions=frozenset({'wiley_tdm_access'}))
    try:
        task = submit_pdf_discovery(host, paper, target=selected, inputs=inputs, http_options=options,
            transfer=lambda *_: CandidateResult.pdf(transfer_complete=True))
        result = task.future.result(3)
        if phase == 'unavailable':
            assert result.status == 'exhausted' and result.pdf_source is None
            assert not any(request.url.host == 'api.wiley.com' for request in requests)
        else:
            assert result.status == 'transferred' and result.pdf_source == phase
            assert len(requests) == (1 if phase == 'P1' else 2)
        assert secret not in repr(result) and secret not in caplog.text
        assert not host.active
    finally:
        host.shutdown(); host.join()
