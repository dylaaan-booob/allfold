from allfold.application.workspace import load_workspace
from allfold.persistence.paper_repository import PaperRepository
from allfold.persistence.library_models import PaperMetadata, BodyReference
from allfold.models import ExternalIds


def test_workspace_reads_only_sqlite_and_keeps_identity_only_body(tmp_path):
    workspace = tmp_path / 'workspace'
    assert not load_workspace(workspace).initialized
    assert not workspace.exists()
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/paper'),
            metadata=PaperMetadata(title='A real paper', abstract='Saved')).paper
        paper = repository.complete_body(paper.token, BodyReference(relative_path='Documents/retained.pdf'))
        paper = repository.exclude(paper.token)
        paper = repository.clear_metadata(paper.token)
        repository.unexclude(paper.token)
    snapshot = load_workspace(workspace)
    assert snapshot.initialized
    assert not snapshot.inbox
    assert len(snapshot.downloaded) == 1
    projected = snapshot.downloaded[0]
    assert projected.paper_id == paper.id
    assert projected.title is None and not projected.metadata_present
    assert projected.identity_label == 'doi:10.5555/paper'
    assert not (workspace / 'Papers').exists()


def test_http_run_initializes_single_library_then_reopens_local_read_and_trash(tmp_path, monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from allfold.http_client import create_http_client
    from electron_test_helpers import OfflineBridge
    from test_pubmed_discovery import article
    from test_web_app import write_valid_config

    config, workspace = write_valid_config(tmp_path)
    config.write_text(config.read_text() + 'enabled_providers: [pubmed]\n')
    requests = []
    def respond(request):
        requests.append(request.url)
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': ['42'], 'webenv': 'fixture', 'querykey': '1'}})
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200, text='<PubmedArticleSet>' + article('42', '0006-341X') + '</PubmedArticleSet>')
        if request.url.host == 'www.ebi.ac.uk':
            return httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})
        assert request.url.host == 'api.openalex.org'
        return httpx.Response(200, json={'meta': {'count': 0}, 'results': []})
    def isolated_http(**kwargs):
        return create_http_client(**(kwargs | {'transport': httpx.MockTransport(respond)}))
    monkeypatch.setattr('allfold.providers.provider_http.create_http_client', isolated_http)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        empty = client.get('/api/ui-next/workspace')
        assert empty.status_code == 200 and not empty.json()['initialized']
        assert not (workspace / 'papers.sqlite').exists()
        csrf = empty.json()['csrf_token']
        started = client.post('/api/ui-next/run', json={'csrf_token': csrf, 'enabled_providers': ['pubmed']})
        assert started.status_code == 200
        app.state.run_coordinator.join()
        result = client.get('/api/ui-next/run').json()
        assert result['snapshot']['result']['facts']['created_papers'] == 1
        snapshot = client.get('/api/ui-next/workspace').json()
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        assert item['metadata_present'] and item['doi'] is None and item['external_ids']['pmid'] == '42'
        assert item['ordinary_dates'] == ['2026-04-02', '2026-09-12', '2026-10-03']
        assert not (workspace / 'Papers').exists() and not (workspace / 'Inbox.base').exists()
        workspace_id, paper_id = snapshot['workspace_id'], item['id']
        fields = client.get(f'/api/papers/{paper_id}/fields', params={'workspace_id': workspace_id}).json()
        # Local actions do not need the global Browser owner or Run slot.
        owner = app.state.browser_task_lock.acquire('fixture')
        try:
            edited = client.post(f'/api/papers/{paper_id}/abstract/input', json={
                'csrf_token': csrf, 'workspace_id': workspace_id, 'revision': fields['revision'], 'abstract': 'Human summary'})
            assert edited.status_code == 200 and edited.json()['paper']['abstract'] == 'Human summary'
            rejected = client.post(f'/api/ui-next/papers/{paper_id}/reject', json={
                'csrf_token': csrf, 'workspace_id': workspace_id})
            assert rejected.status_code == 200 and rejected.json()['paper']['status'] == 'trash'
        finally:
            app.state.browser_task_lock.release(owner)
    before_reopen = len(requests)
    reopened = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(reopened, base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        assert snapshot['workspace_id'] == workspace_id
        assert snapshot['counts']['candidates'] == 0 and snapshot['counts']['trash'] == 1
        item = snapshot['trash']['papers'][0]['paper']
        assert item['id'] == paper_id and item['abstract'] == 'Human summary'
        assert len(requests) == before_reopen


def test_corrupt_library_get_returns_error_without_overwrite(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from test_web_app import write_valid_config
    config, workspace = write_valid_config(tmp_path)
    workspace.mkdir()
    database = workspace / 'papers.sqlite'
    database.write_bytes(b'not a SQLite database')
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        result = client.get('/api/ui-next/workspace')
        assert result.status_code == 409
        assert 'initialized' not in result.json()
    assert database.read_bytes() == b'not a SQLite database'


def test_workspace_projection_uses_saved_primary_doi_with_multiple_direct_aliases(tmp_path):
    from allfold.persistence.library_models import DirectIdentity
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/aaa'),
            additional_identities=(DirectIdentity('doi', '10.5555/zzz'),), metadata=PaperMetadata(title='Article')).paper
    projected, = load_workspace(workspace).inbox
    assert projected.paper_id == paper.id and projected.external_ids.doi == '10.5555/aaa'
    assert projected.identity_label == 'doi:10.5555/aaa'


def test_legacy_import_settings_preserve_only_neutral_workflow_values(tmp_path):
    from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
    from allfold.config import load_config
    from test_web_app import write_valid_config
    config, _ = write_valid_config(tmp_path)
    config.write_text(config.read_text() + '\nkept_workflow:\n  prepare_service_concurrency: 3\n'
        '  paper_global_concurrency: 6\n  pdf_concurrency: 4\n  translator_concurrency: 2\n'
        '  zotero_writer_concurrency: 2\n  zotero_target:\n    server_id: FIXTURE\n    library_type: user\n    library_id: "0"\n')
    loaded = load_config(config)
    assert loaded.workflow.prepare_service_concurrency == 3 and loaded.workflow.pdf_concurrency == 4
    saved = save_settings(config, load_settings(config).draft)
    assert saved.outcome is SettingsSaveOutcome.SAVED
    raw = config.read_text()
    assert 'workflow:' in raw and 'paper_global_concurrency: 6' in raw
    assert all(retired not in raw for retired in ('kept_workflow', 'zotero_', 'translator_concurrency'))
