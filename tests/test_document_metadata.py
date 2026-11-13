"""Fixed native task adapter, captured authority and actual worker settlement."""
from concurrent.futures import Future
from threading import Event
import time

import pytest

from allfold.application.collection_runtime import WorkspaceRegistry
from allfold.application.document_metadata import document_metadata_branch
from allfold.application.task_clients import IndependentClientFactory
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperMetadata, PaperRepository


def pdf_clues(**changes):
    return dict(status='complete', landing_url='https://www.nature.com/articles/one',
        observed_at='2026-11-13T01:02:03.000Z', platform='nature', content_type='journal-article',
        identifiers=[], candidates=[], diagnostics=[]) | changes

def envelope(*, abstract='Background\nA short result.', dates=None, diagnostics=()):
    return {'outcome': 'retrieved', 'metadata_status': 'partial' if set(diagnostics) & {'abstract_candidate_failed', 'abstract_budget_exceeded'} else 'complete', 'pdf_clues': pdf_clues(), 'metadata': {'dates': dates if dates is not None else [
        {'value': '2020-05-02', 'precision': 'day'}], 'abstract': abstract},
        'extraction_diagnostics': list(diagnostics),
        'document': {'pageId': 2, 'processId': 5, 'frameToken': 'native-token',
                     'documentId': 'opaque-document', 'navigationGeneration': 1},
        'diagnostics_status': {'available': False, 'incomplete': True}}


class Bridge:
    def __init__(self):
        self.started, self.cleaning = Event(), Event()
        self.operation, self.cleanup = Future(), Future()
        self.calls = []

    def execute(self, action, data, *args, **kwargs):
        self.calls.append((action, data, kwargs))
        if action == 'release_workflow_pages':
            self.cleaning.set()
            return self.cleanup
        self.started.set()
        return self.operation

    def cancel_task(self, *_):
        pass


def start(tmp_path, bridge, **kwargs):
    path = tmp_path / 'workspace'
    path.mkdir()
    with PaperRepository.create(path):
        pass
    factory = IndependentClientFactory(tmp_path / 'missing-config.yaml')
    registry = WorkspaceRegistry(path, factory=factory, bridge=bridge)
    before_register = kwargs.pop('before_register', None)
    direct_ids = kwargs.pop('direct_ids', ExternalIds(doi='10.5555/formal'))
    branches = kwargs.pop('branches', (document_metadata_branch(),))
    task = registry.admit(direct_ids=direct_ids,
        metadata=PaperMetadata(title='Original'), branches=branches, **kwargs)
    if before_register:
        before_register(path, task)
    registry.register(task)
    return path, registry, task


def settle(registry, bridge):
    if not bridge.operation.done():
        bridge.operation.set_result(envelope())
    if not bridge.cleanup.done():
        bridge.cleanup.set_result({'released': True})
    registry.shutdown()
    registry.join()


def test_real_registry_native_payload_and_normal_page_close_preserve_verified_result(tmp_path):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge, deadline=time.monotonic() + 6)
    try:
        assert bridge.started.wait(2)
        action, payload, options = bridge.calls[0]
        assert action == 'extract_paper_metadata'
        assert payload['identity'] == {'doi': '10.5555/formal'}
        assert payload['paper_id'] == str(task.paper_id)
        assert len(payload['workspace_identity']) == 64
        assert payload['workspace_identity'] != str(task.workspace_id)
        assert payload['wantAbstract'] is True
        assert 0 < payload['deadline_ms'] - int(time.time() * 1000) <= 6000
        assert not set(payload) & {'service_scope', 'service_id', 'preparation_key', 'target_page_id'}
        options['verify_recovery']()
        # Main returns this small evidence only after its actual work-page close.
        bridge.operation.set_result(envelope())
        assert bridge.cleaning.wait(2)
        assert not task.future.done() and registry.active
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'completed'
        assert paper.metadata.abstract == 'Background\nA short result.'
        assert paper.metadata.ordinary_dates == ('2020-05-02',)
        assert [item[0] for item in bridge.calls] == ['extract_paper_metadata', 'release_workflow_pages']
    finally:
        settle(registry, bridge)


@pytest.mark.parametrize('diagnostic', ['abstract_candidate_failed', 'abstract_budget_exceeded'])
def test_partial_abstract_saves_dates_but_branch_remains_failed(tmp_path, diagnostic):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        bridge.operation.set_result(envelope(abstract=None, diagnostics=(diagnostic,)))
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'failed'
        assert paper.metadata.ordinary_dates == ('2020-05-02',)
        assert paper.collection.branches[0].reason == 'DocumentMetadataPartial'
    finally:
        settle(registry, bridge)


@pytest.mark.parametrize('bad', [
    {'diagnostic': {'code': 'document_changed'}},
    envelope(dates=[{'value': '2020-02-30', 'precision': 'day'}]),
    envelope(dates=[{'value': '２０２０-０５-０２', 'precision': 'day'}]),
    envelope(dates=[{'value': '2020-05', 'precision': 'month'}, {'value': '2020-05-02', 'precision': 'day'}]),
    envelope(abstract='x' * 65537),
    envelope(abstract='😀' * 32769),
    envelope(abstract='Unsafe\x00text'),
    envelope(diagnostics=('untrusted-detail',)),
])
def test_failed_or_invalid_native_result_never_becomes_empty_success(tmp_path, bad):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        bridge.operation.set_result(bad)
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'failed'
        assert paper.metadata.abstract is None and paper.metadata.ordinary_dates == ()
    finally:
        settle(registry, bridge)


@pytest.mark.parametrize('edited', ['Already filled by API.', None])
def test_current_read_skips_abstract_without_renewing_manual_generation(tmp_path, edited):
    def edit(path, task):
        with PaperRepository.open(path) as repository:
            repository.edit_metadata(task.token.write, {'abstract': edited, 'notes': 'Keep notes'})
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge, before_register=edit)
    try:
        assert bridge.started.wait(2)
        assert bridge.calls[0][1]['wantAbstract'] is False
        bridge.operation.set_result(envelope())
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.metadata.abstract == edited
        assert paper.metadata.notes == 'Keep notes'
        assert paper.metadata.ordinary_dates == ('2020-05-02',)
    finally:
        settle(registry, bridge)


def test_legal_empty_and_json_ld_warning_are_completed_not_failed(tmp_path):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        bridge.operation.set_result(envelope(abstract=None, dates=[], diagnostics=('json_ld_invalid',)))
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'completed'
        assert paper.metadata.abstract is None and paper.metadata.ordinary_dates == ()
    finally:
        settle(registry, bridge)


def test_service_report_retains_bounded_native_annotations_and_partial_diagnostics():
    from allfold.application.document_metadata import validate_document_metadata
    value = envelope(abstract=None, diagnostics=('abstract_budget_exceeded',))
    value['recovery'] = {'attempts': 1}
    report = validate_document_metadata(value)
    assert report.partial and report.diagnostics == ('abstract_budget_exceeded',)
    assert report.recovery == value['recovery'] and report.diagnostics_status == value['diagnostics_status']
    assert report.delta.ordinary_dates == ('2020-05-02',)
    assert report.delta.discovery_facts[0].status == 'complete'


@pytest.mark.parametrize('confirmed', [None, 'https://article.example/paper#route'])
def test_doi_free_native_task_requires_explicit_upstream_article_confirmation(tmp_path, confirmed):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge, direct_ids=ExternalIds(pmid='123'),
        branches=(document_metadata_branch(confirmed_article_url=confirmed),))
    try:
        if confirmed:
            assert bridge.started.wait(2)
            assert bridge.calls[0][1]['identity'] == {'confirmed_article_url': confirmed}
            bridge.operation.set_result(envelope())
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == ('completed' if confirmed else 'failed')
        assert paper.metadata.abstract == ('Background\nA short result.' if confirmed else None)
        if not confirmed:
            assert not bridge.started.is_set()
    finally:
        settle(registry, bridge)


def test_reject_restore_refuses_old_native_result_and_recovery_without_reopening_page(tmp_path):
    from allfold.persistence.paper_repository import StaleWriteError
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        with registry.paper_gate(), PaperRepository.open(path) as repository:
            repository.restore(repository.exclude(repository.get(task.paper_id).token).token)
        with pytest.raises(StaleWriteError):
            bridge.calls[0][2]['verify_recovery']()
        bridge.operation.set_result(envelope())
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'cancelled'
        assert paper.metadata.abstract is None and paper.metadata.ordinary_dates == ()
    finally:
        settle(registry, bridge)


def test_host_forwards_captured_service_binding_and_revokes_original_access(tmp_path):
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import LoginCoordinator
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.persistence.paper_repository import StaleWriteError
    from test_login import login_fixture, Native, opened

    config, services = login_fixture(tmp_path, count=2)
    service, login_native = services[-1], Native()
    login = LoginCoordinator(login_native, BrowserTaskLock())
    login.start(config, manual_service_id=service.id)
    _, _, ready = login_native.operations.get(timeout=2)
    ready.set_result(opened(17))
    login.join()
    path = tmp_path / 'workspace'
    path.mkdir()
    with PaperRepository.create(path):
        pass
    bridge = Bridge()
    host = WorkspaceTaskHost(config, login=login, bridge=bridge)
    try:
        task = host.current().submit(direct_ids=ExternalIds(doi='10.5555/scoped'),
            metadata=PaperMetadata(title='Scoped'), branches=(document_metadata_branch(),), service_id=service.id)
        assert bridge.started.wait(2)
        payload = bridge.calls[0][1]
        assert payload['service_id'] == service.id and payload['target_page_id'] == 17
        assert len(payload['preparation_key']) == 64 and len(payload['service_scope']['scope_id']) == 64
        login.invalidate_pages([17])
        with pytest.raises(StaleWriteError):
            bridge.calls[0][2]['verify_recovery']()
        bridge.operation.set_result(envelope())
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'cancelled'
        assert paper.metadata.abstract is None and paper.metadata.ordinary_dates == ()
    finally:
        if not bridge.operation.done():
            bridge.operation.set_result(envelope())
        if not bridge.cleanup.done():
            bridge.cleanup.set_result({'released': True})
        host.shutdown()
        host.join()


def test_composite_document_saves_bounded_pdf_facts_once_under_original_attempt(tmp_path):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        value = envelope()
        value['pdf_clues'] = pdf_clues(candidates=[{'stage': 'P3', 'rule_id': 'R037',
            'field': 'citation_pdf_url', 'url': 'https://cdn.example/Paper.PDF?signature=temporary'}])
        bridge.operation.set_result(value)
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'completed'
        facts, = paper.metadata.discovery_facts
        assert facts.target_doi == '10.5555/formal'
        assert facts.status == 'complete' and facts.landing_url == 'https://www.nature.com/articles/one'
        assert facts.candidates[0].url is None
        assert facts.candidates[0].refresh.landing_url == facts.landing_url
        assert paper.collection.branches[0].last_sequence == 2
    finally:
        settle(registry, bridge)


@pytest.mark.parametrize('failed', ['metadata', 'pdf'])
def test_independent_document_failure_preserves_other_success(tmp_path, failed):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        value = envelope()
        if failed == 'metadata':
            value.update(metadata=None, metadata_status='failed', extraction_diagnostics=['metadata_extraction_failed'])
            value['pdf_clues'] = pdf_clues(candidates=[{'stage': 'P4', 'rule_id': 'R037', 'url': 'https://cdn.example/main.pdf'}])
        else:
            value['pdf_clues'] = pdf_clues(status='failed', diagnostics=['pdf_parse_failed'])
        bridge.operation.set_result(value)
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'failed'
        if failed == 'metadata':
            assert paper.metadata.abstract is None and not paper.metadata.ordinary_dates
            assert paper.metadata.discovery_facts[0].candidates[0].url == 'https://cdn.example/main.pdf'
        else:
            assert paper.metadata.abstract == 'Background\nA short result.'
            assert paper.metadata.discovery_facts[0].status == 'failed'
    finally:
        settle(registry, bridge)


def test_pdf_only_validator_keeps_transient_current_candidate_and_durable_refresh_separate():
    from allfold.application.document_metadata import validate_document_pdf_clues
    value = envelope()
    del value['metadata']
    del value['metadata_status']
    del value['extraction_diagnostics']
    value['pdf_clues'] = pdf_clues(candidates=[{'stage': 'P2', 'rule_id': 'R060',
        'url': 'https://cdn.example/Case.PDF?signature=A%2FB&key=2', 'reader_kind': 'lww',
        'referer': 'https://journals.lww.com/journal/_layouts/15/oaks.journals/downloadpdf.aspx?an=12345678-123456789-12345'}])
    result = validate_document_pdf_clues(value, target_doi='10.5555/formal')
    assert result.current_candidates[0].url == 'https://cdn.example/Case.PDF?signature=A%2FB&key=2'
    assert result.current_candidates[0].referer.endswith('?an=12345678-123456789-12345')
    assert result.facts.candidates[0].url is None
    assert result.facts.candidates[0].refresh.kind == 'document-pdf'


def test_form_is_persisted_as_refresh_action_without_mechanical_get_url():
    from allfold.application.document_metadata import validate_document_pdf_clues
    value = envelope()
    value['pdf_clues'] = pdf_clues(candidates=[{'stage': 'P4', 'rule_id': 'R059',
        'url': 'https://www.microbiologyresearch.org/content/one/pdf', 'action': 'refresh_form'}])
    result = validate_document_pdf_clues(value)
    candidate, = result.facts.candidates
    assert candidate.url is None and candidate.action == 'refresh_form'
    assert candidate.refresh.kind == 'document-pdf'
    assert result.current_candidates[0].url == 'https://www.microbiologyresearch.org/content/one/pdf'


@pytest.mark.parametrize('change', [
    {'candidates': [{'stage': 'P4', 'rule_id': 'R037', 'url': 'http://127.0.0.1/private.pdf'}]},
    {'candidates': [{'stage': 'P4', 'rule_id': 'R037', 'url': 'https://user:password@cdn.example/private.pdf'}]},
    {'candidates': [{'stage': 'P4', 'rule_id': 'R037', 'url': 'https://cdn.example/main.pdf', 'body': 'secret'}]},
    {'identifiers': [{'kind': 'pii', 'value': 'secret', 'rule_id': 'R024', 'cookie': 'secret'}]},
    {'status': 'failed'},
    {'status': 'complete', 'diagnostics': ['pdf_parse_failed']},
    {'diagnostics': ['raw page error']},
])
def test_invalid_pdf_contract_invalidates_composite_before_any_emit(tmp_path, change):
    bridge = Bridge()
    path, registry, task = start(tmp_path, bridge)
    try:
        assert bridge.started.wait(2)
        value = envelope()
        value['pdf_clues'] = pdf_clues(**change)
        bridge.operation.set_result(value)
        bridge.cleanup.set_result({'released': True})
        paper = task.future.result(3)
        assert paper.collection_status == 'failed'
        assert paper.metadata.abstract is None and not paper.metadata.discovery_facts
    finally:
        settle(registry, bridge)
