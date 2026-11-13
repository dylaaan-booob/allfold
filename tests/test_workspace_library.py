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
    from allfold.application.preprint_lookup import require_lookup_doi
    from allfold.persistence.library_models import DirectIdentity
    from allfold.web.ui_next import paper_payload
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/zzz'),
            additional_identities=(DirectIdentity('doi', '10.5555/aaa'),),
            metadata=PaperMetadata(title='Article', publication_type='journal')).paper
    projected, = load_workspace(workspace).inbox
    assert projected.paper_id == paper.id and projected.external_ids.doi == '10.5555/zzz'
    assert projected.identity_label == 'doi:10.5555/zzz'
    assert require_lookup_doi(projected.record) == paper_payload(projected)['doi'] == '10.5555/zzz'
    assert paper_payload(projected)['preprint_lookup_available']


def test_v1_multiple_dois_remain_unresolved_in_workspace_and_http_lookup(tmp_path):
    import sqlite3
    from uuid import uuid4
    import pytest
    from fastapi.testclient import TestClient
    from allfold.application.preprint_lookup import require_lookup_doi
    from allfold.persistence.library_database import APPLICATION_ID, DATABASE_NAME, V1_SCHEMA
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from test_web_app import write_valid_config

    config, workspace = write_valid_config(tmp_path)
    workspace.mkdir()
    workspace_id, paper_id = uuid4(), uuid4()
    metadata = PaperMetadata(title='Existing formal article', publication_type='journal', journal='Biometrics')
    with sqlite3.connect(workspace / DATABASE_NAME) as connection:
        for statement in V1_SCHEMA:
            connection.execute(statement)
        connection.execute('INSERT INTO library_info VALUES (1, ?)', (str(workspace_id),))
        connection.execute('INSERT INTO paper_core (paper_id) VALUES (?)', (str(paper_id),))
        for doi in ('10.5555/zzz', '10.5555/aaa'):
            connection.execute('INSERT INTO paper_identities VALUES (?, ?, ?)', ('doi', doi, str(paper_id)))
        connection.execute('INSERT INTO paper_metadata (paper_id, payload) VALUES (?, ?)',
                           (str(paper_id), metadata.model_dump_json(exclude={'discovered_at'})))
        connection.execute(f'PRAGMA application_id = {APPLICATION_ID}')
        connection.execute('PRAGMA user_version = 1')

    projected, = load_workspace(workspace).inbox
    assert projected.record.primary_identity is None
    assert projected.external_ids.doi is None
    with pytest.raises(ValueError, match='formal publication DOI'):
        require_lookup_doi(projected.record)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        item, = [paper for group in snapshot['subjects'] for journal in group['journals'] for paper in journal['papers']]
        assert item['primary_identity'] is None and item['doi'] is None
        assert 'doi' not in item['external_ids'] and not item['preprint_lookup_available']
        assert item['identities'] == [{'namespace': 'doi', 'value': '10.5555/aaa'},
                                      {'namespace': 'doi', 'value': '10.5555/zzz'}]
        started = client.post(f'/api/papers/{paper_id}/preprint-lookup/start', json={
            'csrf_token': snapshot['csrf_token'], 'workspace_id': str(workspace_id)})
        assert started.status_code == 409 and 'formal publication DOI' in started.json()['error']
    with PaperRepository.open(workspace) as repository:
        paper = repository.get(paper_id)
        assert paper.primary_identity is None and len(paper.identities) == 2


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
    assert 'workflow:' in raw and 'managed_page_global_limit: 16' in raw
    assert 'paper_global_concurrency' not in raw
    assert all(retired not in raw for retired in ('kept_workflow', 'zotero_', 'translator_concurrency'))


def test_trash_retains_authoritative_journal_group_until_metadata_is_cleared(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.config import JournalConfig, render_settings_list_text
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from library_application_helpers import create_paper

    config, _, paper = create_paper(tmp_path)
    journals = tmp_path / 'list.md'
    journals.write_text(render_settings_list_text(None,
        (JournalConfig(name='Biometrics', issn='0006-341X', group='Statistics'),),
        path=journals, groups=('Statistics',), custom_labels=(), access_services=()))
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        initial = client.get('/api/ui-next/workspace').json()
        assert initial['subjects'][0]['name'] == 'Statistics'
        body = {'csrf_token': initial['csrf_token'], 'workspace_id': initial['workspace_id']}
        endpoint = f'/api/ui-next/papers/{paper.id}'
        assert client.post(f'{endpoint}/reject', json=body).status_code == 200
        snapshot = client.get('/api/ui-next/workspace').json()
        assert not snapshot['subjects']
        journal = snapshot['trash']['papers'][0]['journal']
        assert journal['key'] == '0006-341X' and journal['source_type'] == 'journal'
        assert journal['group'] == 'Statistics'
        assert snapshot['downloaded']['journals'][0]['group'] == 'Statistics'
        assert client.post(f'{endpoint}/restore', json=body).status_code == 200
        assert client.get('/api/ui-next/workspace').json()['subjects'][0]['name'] == 'Statistics'
        assert client.post(f'{endpoint}/reject', json=body).status_code == 200
        assert client.post(f'{endpoint}/clear-metadata', json=body).status_code == 200
        cleared = client.get('/api/ui-next/workspace').json()['trash']['papers'][0]
        assert not cleared['paper']['metadata_present'] and not cleared['paper']['journal_issns']
        assert cleared['journal']['source_type'] == 'unmapped' and cleared['journal']['group'] is None
        assert cleared['journal']['issn'] is None
