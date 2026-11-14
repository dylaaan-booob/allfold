"""Existing native Preprint proof and cancellation through real SQLite application paths."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Event, current_thread
from uuid import uuid4
import httpx
import pytest
from fastapi.testclient import TestClient

from allfold.providers.supplemental import SupplementalClient
from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.coordinators.preprint_lookup import PreprintLookup
from allfold.application.decisions import apply_paper_action
from allfold.application.paper_fields import edit_paper_fields, read_paper_fields
from allfold.models import EvidenceDate
from allfold.persistence.library_models import MetadataDelta
from allfold.persistence.paper_repository import InvalidPaperState, PaperRepository
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from library_application_helpers import create_paper, read_paper, FORMAL

@pytest.fixture
def make_lookup():
    services = []
    def create(*args, **kwargs):
        service = PreprintLookup(*args, **kwargs)
        services.append(service)
        return service
    yield create
    for service in services:
        service.shutdown()
        service.join()


PREPRINT = '10.1101/2022.02.01.123456'

def collection(*rows, status='ok'):
    return httpx.Response(200, json={'messages': [{'status': status}], 'collection': list(rows)})


def publication(provider, **changes):
    return {'preprint_doi': PREPRINT, 'published_doi': FORMAL, 'preprint_platform': provider,
            'published_date': '2025-08-10', 'preprint_date': '2022-02-01', **changes}


def version(provider, number='1', date='2022-02-03', **changes):
    return {'doi': PREPRINT, 'published': FORMAL, 'server': provider, 'version': number,
            'date': date, 'title': 'Preprint title', 'authors': 'Preprint Author', 'abstract': 'Preprint abstract',
            **changes}


def native_fixture(provider, *versions):
    def respond(request):
        if request.url.path == f'/pubs/{provider}/{FORMAL}/na/json':
            return collection(publication(provider))
        if request.url.path == f'/details/{provider}/{PREPRINT}/na/json':
            return collection(*versions)
        other = 'medrxiv' if provider == 'biorxiv' else 'biorxiv'
        assert request.url.path == f'/pubs/{other}/{FORMAL}/na/json'
        return collection(status=f'Preprint for DOI {FORMAL} not found')
    return respond


def factory(respond):
    return lambda provider, **kwargs: SupplementalClient(
        provider, interval=0, transport=httpx.MockTransport(respond), **kwargs)


def lookup(service, paper_id):
    service.start(paper_id)
    service.join()
    return service.state(paper_id)


def test_distinct_papers_query_concurrently_and_repeat_click_reuses_exact_request(tmp_path, make_lookup):
    from allfold.models import ExternalIds
    from allfold.persistence.library_models import PaperMetadata
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    config, workspace, paper = create_paper(tmp_path)
    with PaperRepository.open(workspace) as repository:
        other = repository.create_or_match(repository.workspace_id,
            direct_ids=ExternalIds(doi='10.5555/another-formal'),
            metadata=PaperMetadata(title='Other formal article', publication_type='journal')).paper
    entered = {FORMAL: Event(), '10.5555/another-formal': Event()}
    finish = Event()
    def respond(request):
        doi = request.url.path.split('/biorxiv/', 1)[-1].split('/medrxiv/', 1)[-1].removesuffix('/na/json')
        entered[doi].set()
        assert finish.wait(5)
        return collection(status=f'Preprint for DOI {doi} not found')
    host = WorkspaceTaskHost(config)
    service = make_lookup(config, BrowserTaskLock(), client_factory=factory(respond), workspace_tasks=host)
    try:
        first = service.start(paper.id, paper.workspace_id)
        assert entered[FORMAL].wait(2)
        second = service.start(other.id, other.workspace_id)
        assert entered['10.5555/another-formal'].wait(2)
        assert service.start(paper.id, paper.workspace_id)['request_id'] == first['request_id']
        assert second['request_id'] != first['request_id']
        assert service.state(paper.id, first['request_id'], paper.workspace_id)['phase'] == 'Running'
        assert service.state(paper.id, second['request_id'], paper.workspace_id)['phase'] == 'Idle'
        assert not service.cancel(paper.id, first['request_id'], uuid4())
        assert service.cancel(paper.id, first['request_id'], paper.workspace_id)
        assert service.state(other.id, second['request_id'], other.workspace_id)['phase'] == 'Running'
    finally:
        finish.set(); service.join(); host.shutdown(); host.join()
    assert service.state(paper.id, first['request_id'], paper.workspace_id)['phase'] == 'Cancelled'
    assert service.state(other.id, second['request_id'], other.workspace_id)['phase'] == 'NoMatch'
    assert read_paper(workspace, paper.id).collection_status == 'not_started'


def test_real_preprint_reservation_preserves_original_proof_before_deferred_collection(tmp_path, make_lookup):
    from allfold.application.collection_runtime import BranchSpec
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.models import ExternalIds
    config, workspace, paper = create_paper(tmp_path)
    requested, finish_request, closing, finish_close, collected = (Event() for _ in range(5))
    native = native_fixture('biorxiv', version('biorxiv'))
    class Client(SupplementalClient):
        def __exit__(self, *args):
            closing.set()
            assert finish_close.wait(5)
            return super().__exit__(*args)
    def respond(request):
        requested.set()
        assert finish_request.wait(5)
        return native(request)
    def clients(provider, **kwargs):
        return Client(provider, interval=0, transport=httpx.MockTransport(respond), **kwargs)
    host = WorkspaceTaskHost(config)
    service = make_lookup(config, BrowserTaskLock(), workspace_tasks=host, client_factory=clients)
    try:
        manual = service.start(paper.id, paper.workspace_id)
        assert requested.wait(2)
        registry = host.current()
        def collect(context):
            assert context.read_paper().metadata.first_public_at == '2022-02-03'
            collected.set()
            return MetadataDelta(ordinary_dates=('2026-11',))
        args = dict(direct_ids=ExternalIds(doi=FORMAL), metadata=paper.metadata,
                    branches=(BranchSpec('date', collect),))
        handle = registry.submit(**args)
        assert registry.submit(**args) is handle
        assert read_paper(workspace, paper.id).collection_status == 'queued'
        assert not collected.is_set()
        finish_request.set()
        assert closing.wait(2)
        assert service.state(paper.id, manual['request_id'], paper.workspace_id)['cleaning_up']
        assert not collected.is_set()
        finish_close.set()
        service.join()
        result = handle.future.result(3)
        assert result.collection_status == 'completed' and collected.is_set()
        assert result.metadata.first_public_at == '2022-02-03'
        assert result.metadata.ordinary_dates == ('2026-11',)
        assert service.state(paper.id, manual['request_id'], paper.workspace_id)['phase'] == 'Completed'
    finally:
        finish_request.set(); finish_close.set(); service.join(); host.shutdown(); host.join()


def test_host_revokes_only_matching_preprint_provider_epoch_and_drains_cleanup(tmp_path, make_lookup):
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    config, workspace, paper = create_paper(tmp_path)
    entered, finish_request, closing, finish_close = (Event() for _ in range(4))
    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def lookup_published_preprints(self, doi):
            entered.set()
            assert finish_request.wait(5)
            self.request_guard()
            return []
        def __exit__(self, *args):
            closing.set()
            assert finish_close.wait(5)
    host = WorkspaceTaskHost(config)
    service = make_lookup(config, BrowserTaskLock(), workspace_tasks=host, client_factory=Client)
    change = None
    try:
        task = service.start(paper.id, paper.workspace_id)
        assert entered.wait(2)
        unrelated = host.begin_change(services=('unrelated',), providers=('pubmed',))
        host.drain_change(unrelated); host.finish_change(unrelated)
        assert service.state(paper.id, task['request_id'], paper.workspace_id)['phase'] == 'Running'
        change = host.begin_change(providers=('biorxiv',))
        assert len(change.targets) == 1 and change.targets[0].paper_id == paper.id
        host.peek().signal_cancel_targets(change.targets)
        assert service.state(paper.id, task['request_id'], paper.workspace_id)['phase'] == 'Cancelling'
        finish_request.set()
        assert closing.wait(2) and host.cleanup_pending(paper.id, paper.workspace_id)
        assert not change.targets[0].future.done()
        finish_close.set()
        host.drain_change(change); host.finish_change(change); change = None
        assert not host.cleanup_pending(paper.id, paper.workspace_id)
        assert service.state(paper.id, task['request_id'], paper.workspace_id)['phase'] == 'Cancelled'
    finally:
        finish_request.set(); finish_close.set(); service.join()
        if change is not None:
            host.drain_change(change); host.finish_change(change)
        host.shutdown(); host.join()


@pytest.mark.parametrize('outcome', ['proof', 'empty', 'failed'])
def test_explicit_repeat_query_preserves_completed_empty_collection(tmp_path, outcome, make_lookup):
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.models import ExternalIds
    config, workspace, paper = create_paper(tmp_path)
    host = WorkspaceTaskHost(config)
    registry = host.current()
    initial = registry.submit(direct_ids=ExternalIds(doi=FORMAL), metadata=paper.metadata,
                              branches=(), no_applicable=True).future.result(3)
    native = native_fixture('biorxiv', version('biorxiv'))
    def respond(request):
        if outcome == 'proof':
            return native(request)
        return collection(status=f'Preprint for DOI {FORMAL} not found' if outcome == 'empty' else 'service unavailable')
    service = make_lookup(config, BrowserTaskLock(), workspace_tasks=host, client_factory=factory(respond))
    try:
        first = service.start(paper.id, paper.workspace_id)
        service.join()
        second = service.start(paper.id, paper.workspace_id)
        service.join()
        assert second['request_id'] != first['request_id']
        assert not service.cancel(paper.id, first['request_id'], paper.workspace_id)
        assert read_paper(workspace, paper.id).collection == initial.collection
        assert service.state(paper.id, second['request_id'], paper.workspace_id)['phase'] == {
            'proof': 'Completed', 'empty': 'NoMatch', 'failed': 'Failed'}[outcome]
    finally:
        host.shutdown(); host.join()


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
@pytest.mark.parametrize('existing_first', [None, '2020-01'])
def test_native_versions_save_proof_on_selected_sqlite_paper(tmp_path, provider, existing_first, make_lookup):
    config, workspace, paper = create_paper(tmp_path, first_public_at=existing_first, abstract='Formal abstract')
    service = make_lookup(config, BrowserTaskLock(), client_factory=factory(
        native_fixture(provider, version(provider), version(provider, '2', '2022-08-03'))))
    result = lookup(service, paper.id)
    assert result['phase'] == 'Completed'
    actual = read_paper(workspace, paper.id).metadata
    assert actual.abstract == 'Formal abstract'
    assert actual.first_public_at == (existing_first or '2022-02-03')
    assert [(date.version, date.day, date.first_version) for date in actual.preprint_evidence] == [('1', 3, True), ('2', 3, False)]
    assert {source.record_id for source in actual.sources if source.provider == provider} == {
        PREPRINT + ':publication', PREPRINT + ':1', PREPRINT + ':2'}
    assert not lookup(service, paper.id)['saved_fields']


@pytest.mark.parametrize('versions', [None, (), (version('biorxiv', '2'),),
    (version('biorxiv', date='2022-02'),),
    (version('biorxiv'), version('biorxiv', date='2022-02-04')),
    (version('biorxiv'), version('biorxiv', '2', '2021-12-01'))])
def test_unresolved_first_version_retains_relationship_without_inference(tmp_path, versions, make_lookup):
    config, workspace, paper = create_paper(tmp_path)
    native = native_fixture('biorxiv', *(versions or ()))
    def respond(request):
        return httpx.Response(404) if versions is None and request.url.path.startswith('/details/') else native(request)
    result = lookup(make_lookup(config, BrowserTaskLock(), client_factory=factory(respond)), paper.id)
    actual = read_paper(workspace, paper.id).metadata
    assert result['phase'] == 'Completed' and actual.first_public_at is None
    assert any(source.record_id == PREPRINT + ':publication' for source in actual.sources)
    assert len(actual.preprint_evidence) == len(versions or ())


@pytest.mark.parametrize('outcome', ['no_match', 'no_match_404', 'verification_404', 'http_failure',
    'truncated_status', 'wrong_formal', 'wrong_preprint', 'wrong_platform', 'wrong_details_publication',
    'self_relation', 'second_provider_failed', 'conflicting_alias', 'invalid_envelope'])
def test_no_match_and_failed_binding_do_not_change_saved_paper(tmp_path, outcome, make_lookup):
    config, workspace, paper = create_paper(tmp_path)
    def respond(request):
        route = request.url.path
        if outcome == 'no_match_404':
            return httpx.Response(404)
        if outcome == 'verification_404':
            return httpx.Response(404, text='<html>Verify you are human</html>')
        if outcome == 'second_provider_failed' and '/medrxiv/' in route:
            return collection(status='service unavailable')
        if outcome == 'invalid_envelope':
            return httpx.Response(200, json={'collection': []})
        if outcome == 'http_failure' and route.startswith('/details/'):
            return httpx.Response(400, json={})
        if outcome == 'truncated_status':
            return collection(status='Preprint for DOI 10.5555/decisio not found')
        if outcome == 'no_match' or '/medrxiv/' in route:
            return collection(status=f'Preprint for DOI {FORMAL} not found')
        if '/pubs/' in route:
            changes = {'wrong_formal': {'published_doi': '10.5555/unrelated'},
                'wrong_platform': {'preprint_platform': 'medrxiv'}, 'self_relation': {'preprint_doi': FORMAL},
                'conflicting_alias': {'biorxiv_doi': '10.1101/unrelated'}}
            return collection(publication('biorxiv', **changes.get(outcome, {})))
        changes = {'wrong_preprint': {'doi': '10.1101/123'},
                   'wrong_details_publication': {'published': '10.5555/unrelated'}}
        return collection(version('biorxiv', **changes.get(outcome, {})))
    result = lookup(make_lookup(config, BrowserTaskLock(), client_factory=factory(respond)), paper.id)
    assert result['phase'] == ('NoMatch' if outcome in {'no_match', 'no_match_404'} else 'Failed')
    actual = read_paper(workspace, paper.id)
    assert actual == replace(paper, revision=actual.revision)


@pytest.mark.parametrize('existing_evidence', ['independent_version', 'relation_without_versions', 'conflicting_v1'])
def test_native_v1_does_not_resolve_unproven_or_conflicting_family(tmp_path, existing_evidence, make_lookup):
    metadata = {}
    if existing_evidence == 'independent_version':
        metadata['preprint_evidence'] = (EvidenceDate(kind='preprint', year=2019, month=1, provider='arxiv',
            record_id='1901.12345', version='v2', publication_type='preprint', version_family='arxiv:1901.12345'),)
    elif existing_evidence == 'relation_without_versions':
        from allfold.models import ProviderRecordRef
        metadata['preprint_relations'] = (ProviderRecordRef(provider='medrxiv', record_id='10.1101/other', relation='preprint'),)
    else:
        metadata['preprint_evidence'] = (EvidenceDate(kind='preprint', year=2022, month=2, day=4,
            provider='biorxiv', record_id=PREPRINT + ':1', version='1', first_version=True, publication_type='preprint'),)
    config, workspace, paper = create_paper(tmp_path, **metadata)
    service = make_lookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    assert lookup(service, paper.id)['phase'] == 'Completed'
    assert read_paper(workspace, paper.id).metadata.first_public_at is None


def test_reject_commits_before_precise_cancel_and_cleanup_blocks_clear(tmp_path, make_lookup):
    config, workspace, paper = create_paper(tmp_path, abstract='Existing formal abstract')
    entered, release, cleaning, finish = Event(), Event(), Event(), Event()
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.persistence.library_models import PaperMetadata
    from datetime import datetime, timezone
    with PaperRepository.open(workspace) as repository:
        other = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/unrelated'),
            metadata=PaperMetadata(title='Unaffected article')).paper
    late_evidence = ProviderWorkEvidence(provenance=MetadataSource(provider='biorxiv', record_id=PREPRINT + ':1',
        retrieved_at=datetime.now(timezone.utc)), dates=(EvidenceDate(kind='preprint', year=2022, month=2, day=3,
        provider='biorxiv', record_id=PREPRINT + ':1', version='1', first_version=True, publication_type='preprint'),))
    class PausedClient:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def lookup_published_preprints(self, doi):
            self.request_guard()
            entered.set()
            assert release.wait(5)
            return [late_evidence]
        def __exit__(self, *args):
            cleaning.set()
            assert finish.wait(10)
    service = make_lookup(config, BrowserTaskLock(), client_factory=PausedClient)
    service.start(paper.id, paper.workspace_id)
    try:
        assert entered.wait(5)
        result = apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject', preprint_lookup=service)
        assert result.paper.excluded
        assert service.state(paper.id)['phase'] == 'Cancelling'
        apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore', preprint_lookup=service)
        assert service.start(paper.id, paper.workspace_id)['request_id'] == service.state(paper.id)['request_id']
        apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject', preprint_lookup=service)
        with pytest.raises(Exception, match='cleaning'):
            apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata', preprint_lookup=service)
        release.set()
        assert cleaning.wait(5) and service.cleaning_up(paper.id, paper.workspace_id)
    finally:
        release.set(); finish.set(); service.join()
    assert service.state(paper.id)['phase'] == 'Cancelled'
    assert read_paper(workspace, paper.id).metadata.abstract == 'Existing formal abstract'
    assert not read_paper(workspace, paper.id).metadata.preprint_evidence
    assert read_paper(workspace, other.id) == other
    apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata', preprint_lookup=service)
    assert read_paper(workspace, paper.id).metadata is None


@pytest.mark.parametrize('previous_lookup', [False, True])
def test_delayed_reject_cannot_cancel_replacement_preprint_lookup(tmp_path, monkeypatch, previous_lookup, make_lookup):
    from allfold.application.workspace_tasks import WorkspaceTaskHost

    config, workspace, paper = create_paper(tmp_path)
    host = WorkspaceTaskHost(config)
    registry = host.current()
    rejected, resume_reject, old_entered, finish_old = (Event() for _ in range(4))
    replacement_entered, finish_replacement = Event(), Event()
    lookup_events = []
    native = native_fixture('biorxiv', version('biorxiv'))

    def client_factory(provider, **kwargs):
        if provider == 'biorxiv':
            lookup_events.append(kwargs['cancel_event'])
        is_old = previous_lookup and len(lookup_events) == 1

        def respond(request):
            if request.url.path == f'/pubs/biorxiv/{FORMAL}/na/json':
                entered, finish = (old_entered, finish_old) if is_old else (replacement_entered, finish_replacement)
                entered.set()
                assert finish.wait(5)
            return native(request)

        return SupplementalClient(provider, interval=0, transport=httpx.MockTransport(respond), **kwargs)

    service = make_lookup(config, BrowserTaskLock(), client_factory=client_factory, workspace_tasks=host)
    operation_lock = registry.paper_gate

    @contextmanager
    def pause_after_unlock(*args, **kwargs):
        with operation_lock(*args, **kwargs):
            yield
        if current_thread().name.startswith('delayed-reject'):
            rejected.set()
            assert resume_reject.wait(5)

    monkeypatch.setattr(registry, 'paper_gate', pause_after_unlock)
    try:
        if previous_lookup:
            service.start(paper.id, paper.workspace_id)
            assert old_entered.wait(2)
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix='delayed-reject') as pool:
            delayed = pool.submit(apply_paper_action, workspace, paper.workspace_id, paper.id, 'reject',
                preprint_lookup=service, workspace_registry=registry)
            try:
                assert rejected.wait(2) and read_paper(workspace, paper.id).excluded
                finish_old.set()
                service.join()
                apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore',
                    preprint_lookup=service, workspace_registry=registry)
                started = service.start(paper.id, paper.workspace_id)
                assert replacement_entered.wait(2)
                replacement_event = lookup_events[-1]
                resume_reject.set()
                assert delayed.result(3).paper.excluded
                assert not replacement_event.is_set()
                assert service.state(paper.id, started['request_id'])['phase'] == 'Running'
            finally:
                resume_reject.set(); finish_replacement.set()
        service.join()
        assert service.state(paper.id, started['request_id'])['phase'] == 'Completed'
        assert read_paper(workspace, paper.id).metadata.first_public_at == '2022-02-03'
    finally:
        finish_old.set(); finish_replacement.set(); resume_reject.set()
        service.shutdown(); service.join()
        if host:
            host.shutdown(); host.join()


def test_local_abstract_edit_during_preprint_keeps_other_valid_proof(tmp_path, make_lookup):
    config, workspace, paper = create_paper(tmp_path)
    entered, release = Event(), Event()
    native = native_fixture('biorxiv', version('biorxiv'))
    def respond(request):
        if '/pubs/biorxiv/' in request.url.path:
            entered.set()
            assert release.wait(5)
        return native(request)
    service = make_lookup(config, BrowserTaskLock(), client_factory=factory(respond))
    service.start(paper.id, paper.workspace_id)
    try:
        assert entered.wait(5)
        fields = read_paper_fields(workspace, paper.id, workspace_id=paper.workspace_id)
        edit_paper_fields(workspace, paper.workspace_id, paper.id, fields['revision'], abstract='Human chosen abstract')
    finally:
        release.set(); service.join()
    actual = read_paper(workspace, paper.id)
    assert service.state(paper.id)['phase'] == 'Completed'
    assert actual.metadata.abstract == 'Human chosen abstract' and actual.metadata.first_public_at == '2022-02-03'
    with PaperRepository.open(workspace) as repository:
        actual = repository.merge_metadata(paper.token, MetadataDelta(abstract='Old automatic candidate', ordinary_dates=('2030-04',)))
    assert actual.metadata.abstract == 'Human chosen abstract' and actual.metadata.ordinary_dates == ('2030-04',)


@pytest.mark.parametrize('phase', ['Completed', 'NoMatch', 'Failed'])
@pytest.mark.parametrize('action', ['cancel', 'reject'])
def test_terminal_preprint_phase_survives_cancel_during_final_resource_release(tmp_path, phase, action, make_lookup):
    config, workspace, paper = create_paper(tmp_path)
    releasing, finish = Event(), Event()
    class PausedAdmission(BrowserTaskLock):
        def release(self, owner):
            releasing.set()
            assert finish.wait(5)
            super().release(owner)
    native = native_fixture('biorxiv', version('biorxiv'))
    def respond(request):
        if phase == 'Completed': return native(request)
        return collection(status=f'Preprint for DOI {FORMAL} not found' if phase == 'NoMatch' else 'service unavailable')
    service = make_lookup(config, PausedAdmission(), client_factory=factory(respond))
    started = service.start(paper.id, paper.workspace_id)
    try:
        assert releasing.wait(5)
        assert service.state(paper.id)['phase'] == phase
        if action == 'cancel':
            assert not service.cancel(paper.id, started['request_id'], paper.workspace_id)
        else:
            assert apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject', preprint_lookup=service).paper.excluded
            with pytest.raises(InvalidPaperState, match='cleaning'):
                apply_paper_action(workspace, paper.workspace_id, paper.id, 'clear-metadata', preprint_lookup=service)
        state = service.state(paper.id)
        assert state['phase'] == phase and state['cleaning_up']
        if action == 'reject':
            with pytest.raises(ValueError, match='active, complete'):
                service.start(paper.id, paper.workspace_id)
        else:
            assert service.start(paper.id, paper.workspace_id)['request_id'] == started['request_id']
    finally:
        finish.set(); service.join()
    state = service.state(paper.id)
    assert state['phase'] == phase and not state['cleaning_up']


def test_web_routes_use_workspace_identity_and_retire_business_endpoints(tmp_path):
    config, workspace, paper = create_paper(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        assert snapshot['workspace_id'] == str(paper.workspace_id)
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        assert item['id'] == str(paper.id) and item['metadata_present']
        assert item['collection_status'] == 'not_started'
        csrf = snapshot['csrf_token']
        endpoint = f'/api/ui-next/papers/{paper.id}/reject'
        body = {'csrf_token': csrf, 'workspace_id': str(paper.workspace_id)}
        assert client.post(endpoint, json={**body, 'csrf_token': 'bad'}).status_code == 403
        assert client.post(endpoint, json={**body, 'workspace_id': str(uuid4())}).status_code == 409
        rejected = client.post(endpoint, json=body)
        assert rejected.status_code == 200 and rejected.json()['paper']['status'] == 'trash'
        assert client.get('/api/ui-next/workspace').json()['counts']['trash'] == 1
        for retired in ('/api/kept-workflow/state', f'/api/papers/{paper.id}/enrichment/state', '/api/ui-next/zotero'):
            assert client.get(retired).status_code == 404


def test_public_preprint_identity_and_active_request_allow_actual_run(tmp_path, monkeypatch):
    import json
    from allfold.providers import integrated
    from http_test_helpers import http_server, isolate_proxy_environment
    isolate_proxy_environment(monkeypatch)
    config, workspace, paper = create_paper(tmp_path)
    config.write_text(config.read_text() + 'enabled_providers: [openalex]\n')
    entered, finish = Event(), Event()
    def respond(request):
        if request.path.startswith('/works?'):
            body = {'results': [], 'meta': {'count': 0}}
        else:
            assert request.path in {f'/pubs/{provider}/{FORMAL}/na/json' for provider in ('biorxiv', 'medrxiv')}
            entered.set()
            assert finish.wait(5)
            body = {'messages': [{'status': f'Preprint for DOI {FORMAL} not found'}], 'collection': []}
        return 200, {'Content-Type': 'application/json'}, json.dumps(body).encode()
    with http_server(respond) as origin:
        for provider in integrated.PROVIDERS:
            monkeypatch.setitem(integrated.BASE_URLS, provider, origin.url)
        app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
        try:
            with TestClient(app, base_url='http://localhost') as client:
                csrf = client.get('/api/ui-next/workspace').json()['csrf_token']
                endpoint = f'/api/papers/{paper.id}/preprint-lookup'
                body = dict(csrf_token=csrf, workspace_id=str(paper.workspace_id))
                assert client.post(endpoint + '/start', json={**body, 'csrf_token': 'bad'}).status_code == 403
                assert client.post(endpoint + '/start', json={**body, 'workspace_id': str(uuid4())}).status_code == 409
                started = client.post(endpoint + '/start', json=body)
                assert started.status_code == 200 and entered.wait(2)
                request = started.json()['request_id']
                params = dict(workspace_id=str(paper.workspace_id), request_id=request)
                assert client.get(endpoint + '/state').status_code == 422
                assert client.get(endpoint + '/state', params={**params, 'workspace_id': str(uuid4())}).status_code == 409
                assert client.get(endpoint + '/state', params={**params, 'request_id': 'old'}).json()['phase'] == 'Idle'
                assert client.post(endpoint + '/start', json=body).json()['request_id'] == request
                run = client.post('/api/ui-next/run', json={'csrf_token': csrf})
                assert run.status_code == 200, run.text
                app.state.run_coordinator.join()
                result = client.get('/api/ui-next/run').json()['snapshot']
                assert result['status'] == 'FINISHED' and result['unexpected_error'] is None
                client.get('/api/ui-next/workspace')
                client.get(f'/api/papers/{paper.id}/fields', params={'workspace_id': str(paper.workspace_id)})
                assert client.get(endpoint + '/state', params=params).json()['phase'] == 'Running'
                assert client.post(endpoint + '/cancel', json={**body, 'request_id': 'old'}).status_code == 409
                assert client.post(endpoint + '/cancel', json={**body, 'request_id': request}).status_code == 200
                finish.set()
                app.state.preprint_lookup.join()
                actual = client.get(endpoint + '/state', params=params).json()
                assert actual['phase'] == 'Cancelled' and not actual['cleaning_up']
                assert read_paper(workspace, paper.id).collection_status == 'not_started'
        finally:
            finish.set(); app.state.run_coordinator.join()
            app.state.preprint_lookup.shutdown(); app.state.preprint_lookup.join()
            app.state.workspace_tasks.shutdown(); app.state.workspace_tasks.join()


@pytest.mark.parametrize('stop_kind', ['reject', 'exclude', 'cancel'])
def test_preprint_status_reports_current_same_library_revision_after_terminal_cleanup(tmp_path, stop_kind, make_lookup):
    config, workspace, paper = create_paper(tmp_path, abstract='Original')
    entered, release = Event(), Event()
    def respond(request):
        entered.set()
        assert release.wait(5)
        return collection(status=f'Preprint for DOI {FORMAL} not found')
    service = make_lookup(config, BrowserTaskLock(), client_factory=factory(respond))
    task = service.start(paper.id, paper.workspace_id)
    try:
        assert entered.wait(5)
        if stop_kind == 'reject':
            action = apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject', preprint_lookup=service)
            expected_revision = action.revision
        elif stop_kind == 'exclude':
            with PaperRepository.open(workspace) as repository:
                repository.exclude(paper.token)
                expected_revision = repository.revision
        else:
            fields = read_paper_fields(workspace, paper.id, workspace_id=paper.workspace_id)
            _, expected_revision, _ = edit_paper_fields(workspace, paper.workspace_id, paper.id,
                fields['revision'], abstract='Local edit while stopping')
            assert service.cancel(paper.id, task['request_id'], paper.workspace_id)
    finally:
        release.set()
        service.join()
    status = service.state(paper.id, task['request_id'])
    assert status['phase'] == ('Failed' if stop_kind == 'exclude' else 'Cancelled')
    assert status['workspace_id'] == str(paper.workspace_id) and status['request_id'] == task['request_id']
    assert status['revision'] > expected_revision > task['revision']
    assert not status['cleaning_up'] and not read_paper(workspace, paper.id).metadata.preprint_evidence
    if stop_kind != 'cancel':
        from allfold.persistence.paper_repository import StaleWriteError
        with PaperRepository.open(workspace) as repository:
            with pytest.raises(StaleWriteError):
                repository.merge_metadata(paper.token, MetadataDelta(ordinary_dates=('2030-01',)))
    # A later library is not allowed to re-scope this old task's status envelope.
    other_workspace = tmp_path / 'other-workspace'
    other_workspace.mkdir()
    with PaperRepository.create(other_workspace) as repository:
        assert repository.workspace_id != paper.workspace_id
        from allfold.models import ExternalIds
        from allfold.persistence.library_models import PaperMetadata
        other = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/other'),
            metadata=PaperMetadata(title='Other library')).paper
        repository.exclude(other.token)
    config.write_text(config.read_text().replace('output_dir: workspace', 'output_dir: other-workspace'))
    stale_status = service.state(paper.id, task['request_id'])
    assert stale_status['workspace_id'] == str(paper.workspace_id)
    assert stale_status['revision'] == task['revision']
    with pytest.raises(Exception, match='Workspace'):
        service.state(paper.id, task['request_id'], paper.workspace_id)


def test_lookup_releases_its_owner_when_an_independent_browser_owner_started_first(tmp_path, make_lookup):
    config, _, paper = create_paper(tmp_path)
    admission = BrowserTaskLock()
    covers = admission.acquire('covers')
    service = make_lookup(config, admission, client_factory=factory(
        native_fixture('biorxiv', version('biorxiv'))))
    assert lookup(service, paper.id)['phase'] == 'Completed'
    assert admission.owners == (covers,)
    admission.release(covers)
