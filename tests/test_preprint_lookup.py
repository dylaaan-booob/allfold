from threading import Event
from uuid import uuid4

import httpx
import pytest

from allfold.application.browser_runtime import BrowserTaskLock
from allfold.application.coordinators.preprint_lookup import PreprintLookup
from allfold.application.decisions import reject_paper
from allfold.models import WorkflowStatus
from allfold.providers.supplemental import SupplementalClient
from test_application_decisions import document_parts, replace_frontmatter, write_paper
from test_paper_enrichment import missing
from test_web_app import write_valid_config


FORMAL = '10.5555/decision'
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
def test_only_selected_formal_paper_gets_native_version_evidence(tmp_path, provider, existing_first):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace, status=WorkflowStatus.KEPT)
    replace_frontmatter(path, first_public_at=existing_first)
    path.write_text(path.read_text().replace('status:', '# Preserve YAML comment\nstatus:', 1))
    unrelated = write_paper(workspace, uuid4(), filename='other.md')
    replace_frontmatter(unrelated, doi='10.5555/other', external_ids={'doi': '10.5555/other'})
    original, body = document_parts(path)
    unrelated_bytes = unrelated.read_bytes()
    calls = []
    native = native_fixture(provider, version(provider), version(provider, '2', '2022-08-03'))

    def respond(request):
        calls.append(request.url.path)
        assert request.url.host == 'api.biorxiv.org'
        return native(request)

    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond))
    result = lookup(service, paper_id)
    assert result['phase'] == 'Completed'
    assert set(calls) == {f'/pubs/biorxiv/{FORMAL}/na/json', f'/pubs/medrxiv/{FORMAL}/na/json',
                         f'/details/{provider}/{PREPRINT}/na/json'}
    assert len(calls) == 3 and unrelated.read_bytes() == unrelated_bytes
    actual, actual_body = document_parts(path)
    assert actual_body == body
    assert actual['first_public_at'] == (existing_first or '2022-02-03')
    assert {item['kind'] for item in actual['date_evidence']} == {'preprint'}
    assert [(item['version'], item['day'], item['first_version']) for item in actual['date_evidence']] == [
        ('1', 3, True), ('2', 3, False)]
    assert {source['record_id'] for source in actual['sources'] if source['provider'] == provider} == {
        PREPRINT + ':publication', PREPRINT + ':1', PREPRINT + ':2'}
    assert {key: value for key, value in actual.items() if key not in {'sources', 'date_evidence', 'first_public_at'}} == {
        key: value for key, value in original.items() if key not in {'sources', 'date_evidence', 'first_public_at'}}
    assert '# Preserve YAML comment' in path.read_text()
    first = path.read_bytes()
    assert lookup(service, paper_id)['saved_fields'] == []
    assert path.read_bytes() == first


@pytest.mark.parametrize('versions', [
    (),
    (version('biorxiv', '2'),),
    (version('biorxiv', date='2022-02'),),
    (version('biorxiv'), version('biorxiv', date='2022-02-04')),
    (version('biorxiv'), version('biorxiv', '2', '2021-12-01')),
])
def test_unresolved_first_public_saves_verified_relationship_without_inference(tmp_path, versions):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', *versions)))
    result = lookup(service, paper_id)
    assert result['phase'] == 'Completed' and 'first_public_at' not in result['saved_fields']
    actual, _ = document_parts(path)
    assert actual.get('first_public_at') is None
    assert any(source['record_id'] == PREPRINT + ':publication' for source in actual['sources'])
    assert len(actual.get('date_evidence', [])) == len(versions)


@pytest.mark.parametrize('outcome', ['no_match', 'http_failure', 'truncated_status', 'wrong_formal', 'wrong_preprint',
                                    'wrong_platform', 'wrong_details_publication', 'self_relation',
                                    'second_provider_failed', 'conflicting_alias', 'invalid_envelope'])
def test_no_match_and_failed_binding_do_not_write_paper(tmp_path, outcome):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    before = path.read_bytes()

    def respond(request):
        route = request.url.path
        if outcome == 'second_provider_failed' and '/medrxiv/' in route:
            return collection(status='service unavailable')
        if outcome == 'invalid_envelope':
            return httpx.Response(200, json={'collection': []})
        if outcome == 'http_failure' and route.startswith('/details/'):
            return httpx.Response(404, json={})
        if outcome == 'truncated_status':
            return collection(status='Preprint for DOI 10.5555/decisio not found')
        if outcome == 'no_match' or '/medrxiv/' in route:
            return collection(status=f'Preprint for DOI {FORMAL} not found')
        if '/pubs/' in route:
            row = publication('biorxiv')
            if outcome == 'wrong_formal':
                row['published_doi'] = '10.5555/unrelated'
            if outcome == 'wrong_platform':
                row['preprint_platform'] = 'medrxiv'
            if outcome == 'self_relation':
                row['preprint_doi'] = FORMAL
            if outcome == 'conflicting_alias':
                row['biorxiv_doi'] = '10.1101/unrelated'
            return collection(row)
        row = version('biorxiv')
        if outcome == 'wrong_preprint':
            row['doi'] = '10.1101/123'
        if outcome == 'wrong_details_publication':
            row['published'] = '10.5555/unrelated'
        return collection(row)

    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond))
    result = lookup(service, paper_id)
    assert result['phase'] == ('NoMatch' if outcome == 'no_match' else 'Failed')
    assert result['message'] and not result['saved_fields']
    assert path.read_bytes() == before


@pytest.mark.parametrize('change', ['reject', 'content', 'directory', 'file', 'workspace', 'configuration', 'authority', 'cancel'])
def test_revoked_or_changed_paper_cannot_reach_later_request_or_commit(tmp_path, change):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    waiting, release = Event(), Event()
    calls = []

    def respond(request):
        calls.append(request.url.path)
        waiting.set()
        assert release.wait(5)
        return collection(publication('biorxiv'))

    task_lock = BrowserTaskLock()
    service = PreprintLookup(config, task_lock, client_factory=factory(respond))
    task = service.start(paper_id)
    try:
        assert waiting.wait(5)
        if change == 'reject':
            reject_paper(workspace, paper_id, WorkflowStatus.CANDIDATE)
        elif change == 'content':
            path.write_text(path.read_text() + 'Human edit\n')
        elif change in {'directory', 'workspace'}:
            original = path.parent if change == 'directory' else workspace
            old = original.with_name(original.name + '-old')
            original.rename(old)
            path.parent.mkdir(parents=True)
            path.write_bytes((old / path.relative_to(original)).read_bytes())
        elif change == 'file':
            old = path.with_suffix('.old')
            path.rename(old)
            path.write_bytes(old.read_bytes())
        elif change == 'configuration':
            config.write_text(config.read_text() + '\n# changed configuration\n')
        elif change == 'authority':
            task_lock.release(task_lock.owner)
            replacement_owner = task_lock.acquire('replacement')
        else:
            assert not service.cancel(uuid4(), task['request_id'])
            assert service.cancel(paper_id, task['request_id'])
        before = path.read_bytes()
    finally:
        release.set()
        service.join()
    assert calls == [f'/pubs/biorxiv/{FORMAL}/na/json']
    assert path.read_bytes() == before
    assert service.state(paper_id)['phase'] == ('Cancelled' if change == 'cancel' else 'Failed')
    if change == 'authority':
        assert task_lock.owner is replacement_owner


def test_saved_conflicting_v1_without_family_blocks_filling_first_public(tmp_path):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    replace_frontmatter(path, date_evidence=[dict(kind='preprint', year=2022, month=2, day=4,
        provider='biorxiv', record_id=PREPRINT + ':1', version='1', first_version=True, publication_type='preprint')])
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    result = lookup(service, paper_id)
    paper, _ = document_parts(path)
    assert result['phase'] == 'Completed'
    assert not paper.get('first_public_at')
    assert {fact['day'] for fact in paper['date_evidence']} == {3, 4}


@pytest.mark.parametrize('change', ['no_doi', 'preprint', 'unknown_type', 'rejected', 'missing_workspace'])
def test_ineligible_paper_or_missing_workspace_never_dispatches(tmp_path, change):
    config, workspace = write_valid_config(tmp_path)
    paper_id = uuid4()
    if change != 'missing_workspace':
        path = write_paper(workspace, paper_id)
        if change == 'no_doi':
            replace_frontmatter(path, doi=None, external_ids={'pmid': '12345678'})
        elif change == 'preprint':
            replace_frontmatter(path, publication_type='preprint')
        elif change == 'unknown_type':
            replace_frontmatter(path, publication_type=None, journal=None, conference=None)
        elif change == 'rejected':
            reject_paper(workspace, paper_id, WorkflowStatus.CANDIDATE)
        before = path.read_bytes()

    def unexpected_request(_):
        pytest.fail('Ineligible Paper must not dispatch a request')

    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(unexpected_request))
    with pytest.raises((ValueError, OSError)):
        service.start(paper_id)
    assert service.state(paper_id)['phase'] == 'Idle'
    if change == 'missing_workspace':
        assert not (workspace / 'Papers').exists()
    else:
        assert path.read_bytes() == before


def test_formal_lookup_does_not_guess_endpoint_from_doi_prefix(tmp_path):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    formal = '10.1101/formal'
    replace_frontmatter(path, doi=formal, external_ids={'doi': formal}, publication_type='journal')
    calls = []

    def respond(request):
        calls.append(request.url.path)
        return collection(status=f'Preprint for DOI {formal} not found')

    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(respond))
    assert lookup(service, paper_id)['phase'] == 'NoMatch'
    assert calls == [f'/pubs/{provider}/{formal}/na/json' for provider in ('biorxiv', 'medrxiv')]


def test_lookup_reports_committed_fields_when_directory_sync_fails(tmp_path, monkeypatch):
    import os
    import stat

    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    fsync, failures = os.fsync, []

    def fail_committed_directory_sync(descriptor):
        if not failures and stat.S_ISDIR(os.fstat(descriptor).st_mode) and PREPRINT + ':publication' in path.read_text():
            failures.append(True)
            raise OSError('Synthetic directory sync failure')
        return fsync(descriptor)

    monkeypatch.setattr(os, 'fsync', fail_committed_directory_sync)
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    result = lookup(service, paper_id)
    assert failures and result['phase'] == 'Completed'
    assert 'filesystem sync failed' in result['message']
    assert set(result['saved_fields']) == {'date_evidence', 'first_public_at', 'sources'}
    assert document_parts(path)[0]['first_public_at'] == '2022-02-03'


def test_lookup_routes_require_csrf_and_hold_run_settings_reset_and_enrich_admission(tmp_path):
    from fastapi.testclient import TestClient
    from electron_test_helpers import OfflineBridge
    from allfold.web.app import create_app
    from allfold.web.settings_guard import settings_task_active

    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    app = create_app(config, electron_bridge=OfflineBridge())
    waiting, release = Event(), Event()

    def respond(_):
        waiting.set()
        assert release.wait(5)
        return collection(status=f'Preprint for DOI {FORMAL} not found')

    service = app.state.preprint_lookup
    service.client_factory = factory(respond)
    with TestClient(app, base_url='http://localhost') as client:
        endpoint = f'/api/papers/{paper_id}/preprint-lookup'
        assert client.post(endpoint + '/start', json={'csrf_token': 'bad'}).status_code == 403
        assert client.post('/api/papers/api-completion/start', json={}).status_code == 404
        settings = client.get('/api/ui-next/settings').json()
        csrf = settings['csrf_token']
        assert client.post(endpoint + '/start', json={'csrf_token': csrf, 'paper_ids': [str(paper_id)]}).status_code == 422
        service.run_slot.acquire()
        try:
            refused = client.post(endpoint + '/start', json={'csrf_token': csrf})
            assert refused.status_code == 409 and 'Run is active' in refused.json()['error']
        finally:
            service.run_slot.release()
        try:
            start = client.post(endpoint + '/start', json={'csrf_token': csrf})
            assert start.status_code == 200 and waiting.wait(5)
            request_id = start.json()['request_id']
            assert client.get(endpoint + '/state').json()['phase'] == 'Running'
            assert client.get(endpoint + '/state?request_id=stale').json()['phase'] == 'Idle'
            assert client.get(f'/api/papers/{uuid4()}/preprint-lookup/state').json()['phase'] == 'Idle'
            assert settings_task_active(app) and not service.run_slot.acquire(blocking=False)
            assert app.state.browser_task_lock.acquire('enrichment') is None
            assert client.post(endpoint + '/start', json={'csrf_token': csrf}).status_code == 409
            base = {key: settings['values'][key] for key in ('monitor_revision_exists', 'monitor_revision_digest',
                    'journal_revision_exists', 'journal_revision_digest')}
            saved = client.post('/api/ui-next/settings/autosave', json={
                'csrf_token': csrf, 'base': base, 'changes': {'name': 'Another Monitor'}}).json()
            assert saved['outcome'] == 'TASK_ACTIVE'
            preview = client.get('/api/ui-next/settings/reset-preview').json()
            reset = client.post('/settings/workspace-reset', data={'csrf_token': csrf, 'reset_token': preview['reset_token']})
            assert reset.status_code == 409 and path.exists()
            assert client.post(endpoint + '/cancel', json={'csrf_token': csrf, 'request_id': 'stale'}).status_code == 409
            assert client.post(endpoint + '/cancel', json={'csrf_token': csrf, 'request_id': request_id}).status_code == 200
        finally:
            release.set()
            service.join()
        assert client.get(endpoint + '/state').json()['phase'] == 'Cancelled'
        assert not settings_task_active(app)


@pytest.mark.parametrize('existing_evidence', ['independent_version', 'relation_without_versions'])
def test_native_v1_does_not_resolve_an_independent_preprint_family(tmp_path, existing_evidence):
    config, workspace = write_valid_config(tmp_path)
    paper_id, path = missing(workspace)
    if existing_evidence == 'independent_version':
        replace_frontmatter(path, date_evidence=[dict(kind='preprint', year=2019, month=1, provider='arxiv',
            record_id='1901.12345', version='v2', publication_type='preprint', version_family='arxiv:1901.12345')])
    else:
        original, _ = document_parts(path)
        replace_frontmatter(path, sources=[*original['sources'], dict(provider='medrxiv', record_id='10.1101/other:publication',
            retrieved_at='2026-10-12T00:00:00Z', role='supplement',
            url=f'https://api.biorxiv.org/pubs/medrxiv/{FORMAL}/na/json')])
    service = PreprintLookup(config, BrowserTaskLock(), client_factory=factory(native_fixture('biorxiv', version('biorxiv'))))
    result = lookup(service, paper_id)
    paper, _ = document_parts(path)
    assert result['phase'] == 'Completed'
    assert not paper.get('first_public_at')
    assert any(fact['provider'] == 'biorxiv' and fact['first_version'] for fact in paper['date_evidence'])
