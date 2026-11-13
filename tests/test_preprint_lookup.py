"""Existing native Preprint proof and cancellation through real SQLite application paths."""
from threading import Event
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
from allfold.persistence.paper_repository import PaperRepository
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from library_application_helpers import create_paper, read_paper, FORMAL

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


@pytest.mark.parametrize('provider', ['biorxiv', 'medrxiv'])
@pytest.mark.parametrize('existing_first', [None, '2020-01'])
def test_native_versions_save_proof_on_selected_sqlite_paper(tmp_path, provider, existing_first):
    config, workspace, paper = create_paper(tmp_path, first_public_at=existing_first, abstract='Formal abstract')
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(
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
def test_unresolved_first_version_retains_relationship_without_inference(tmp_path, versions):
    config, workspace, paper = create_paper(tmp_path)
    native = native_fixture('biorxiv', *(versions or ()))
    def respond(request):
        return httpx.Response(404) if versions is None and request.url.path.startswith('/details/') else native(request)
    result = lookup(PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond)), paper.id)
    actual = read_paper(workspace, paper.id).metadata
    assert result['phase'] == 'Completed' and actual.first_public_at is None
    assert any(source.record_id == PREPRINT + ':publication' for source in actual.sources)
    assert len(actual.preprint_evidence) == len(versions or ())


@pytest.mark.parametrize('outcome', ['no_match', 'no_match_404', 'verification_404', 'http_failure',
    'truncated_status', 'wrong_formal', 'wrong_preprint', 'wrong_platform', 'wrong_details_publication',
    'self_relation', 'second_provider_failed', 'conflicting_alias', 'invalid_envelope'])
def test_no_match_and_failed_binding_do_not_change_saved_paper(tmp_path, outcome):
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
    result = lookup(PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond)), paper.id)
    assert result['phase'] == ('NoMatch' if outcome in {'no_match', 'no_match_404'} else 'Failed')
    assert read_paper(workspace, paper.id) == paper


@pytest.mark.parametrize('existing_evidence', ['independent_version', 'relation_without_versions', 'conflicting_v1'])
def test_native_v1_does_not_resolve_unproven_or_conflicting_family(tmp_path, existing_evidence):
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
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    assert lookup(service, paper.id)['phase'] == 'Completed'
    assert read_paper(workspace, paper.id).metadata.first_public_at is None


def test_reject_commits_before_precise_cancel_and_cleanup_blocks_clear(tmp_path):
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
            assert finish.wait(5)
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=PausedClient)
    service.start(paper.id, paper.workspace_id)
    try:
        assert entered.wait(5)
        result = apply_paper_action(workspace, paper.workspace_id, paper.id, 'reject', preprint_lookup=service)
        assert result.paper.excluded
        assert service.state(paper.id)['phase'] == 'Cancelling'
        apply_paper_action(workspace, paper.workspace_id, paper.id, 'restore', preprint_lookup=service)
        with pytest.raises(ValueError, match='active|cleaning'):
            service.start(paper.id, paper.workspace_id)
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


def test_local_abstract_edit_during_preprint_keeps_other_valid_proof(tmp_path):
    config, workspace, paper = create_paper(tmp_path)
    entered, release = Event(), Event()
    native = native_fixture('biorxiv', version('biorxiv'))
    def respond(request):
        if '/pubs/biorxiv/' in request.url.path:
            entered.set()
            assert release.wait(5)
        return native(request)
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond))
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


def test_preprint_can_use_known_metadata_with_unknown_legacy_discovery_time(tmp_path):
    import json
    import sqlite3
    config, workspace, paper = create_paper(tmp_path)
    # Valid legacy metadata never had this field; its unknown value must stay
    # unknown while transient proof provenance uses this operation's evidence.
    with sqlite3.connect(workspace / 'papers.sqlite') as connection:
        payload = paper.metadata.model_dump(mode='json')
        payload.pop('discovered_at')
        connection.execute('UPDATE paper_metadata SET payload = ? WHERE paper_id = ?', (json.dumps(payload), str(paper.id)))
    assert read_paper(workspace, paper.id).metadata.discovered_at is None
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    assert lookup(service, paper.id)['phase'] == 'Completed'
    metadata = read_paper(workspace, paper.id).metadata
    assert metadata.first_public_at == '2022-02-03' and metadata.discovered_at is None


@pytest.mark.parametrize('stop_kind', ['reject', 'exclude', 'cancel'])
def test_preprint_status_reports_current_same_library_revision_after_terminal_cleanup(tmp_path, stop_kind):
    config, workspace, paper = create_paper(tmp_path, abstract='Original')
    entered, release = Event(), Event()
    def respond(request):
        entered.set()
        assert release.wait(5)
        return collection(status=f'Preprint for DOI {FORMAL} not found')
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond))
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
    assert status['revision'] == expected_revision > task['revision']
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
        foreign_revision = repository.revision
    config.write_text(config.read_text().replace('output_dir: workspace', 'output_dir: other-workspace'))
    stale_status = service.state(paper.id, task['request_id'])
    assert stale_status['workspace_id'] == str(paper.workspace_id)
    assert stale_status['revision'] == task['revision'] < foreign_revision
