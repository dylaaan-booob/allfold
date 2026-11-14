"""Public retry qualification with the production service and real Workspace registry."""
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from allfold.application.collection_runtime import BranchSpec
from allfold.persistence.paper_repository import MetadataDelta, PaperRepository, PaperMetadata, BodyReference
from allfold.models import ExternalIds
from allfold.web.app import create_app
from electron_test_helpers import OfflineBridge
from library_application_helpers import create_paper


@pytest.mark.parametrize('with_body', [False, True])
def test_retry_projection_and_http_share_exact_settled_paper_qualification(tmp_path, monkeypatch, with_body):
    config, workspace, paper = create_paper(tmp_path)
    entered, release = Event(), Event()
    attempts = []

    def api(context):
        attempts.append(True)
        if len(attempts) == 1:
            raise RuntimeError('controlled failure with https://private.invalid/?signature=secret')
        entered.set()
        assert release.wait(5)
        return MetadataDelta(abstract='Retry result')

    monkeypatch.setattr('allfold.application.collection_planner.document_metadata_branch',
        lambda: BranchSpec('document', lambda _: MetadataDelta(ordinary_dates=('2026-11-14',))))
    monkeypatch.setattr('allfold.application.collection_planner.necessary_metadata_branch',
        lambda **_: BranchSpec('necessary-api', api))
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        registry = app.state.workspace_tasks.current()
        # Avoid access-dependent native work; collectors above are controlled public branch seams.
        task = registry.submit(direct_ids=ExternalIds(doi='10.5555/decision'),
            metadata=paper.metadata, branches=app.state.collection_service.plan(paper=paper))
        failed = task.future.result(3)
        assert failed.collection_status == 'failed'
        if with_body:
            with PaperRepository.open(workspace) as repository:
                repository.complete_body(failed.token, BodyReference(relative_path='Documents/associated.pdf'))
        def projected():
            snapshot = client.get('/api/ui-next/workspace').json()
            items = [paper for group in snapshot['subjects'] for journal in group['journals'] for paper in journal['papers']]
            items += [entry['paper'] for entry in snapshot['downloaded']['papers']]
            return snapshot, items[0]
        reservation = registry.reserve(paper.id, kind='legacy')
        try:
            snapshot, occupied = projected()
            assert occupied['cleanup_pending'] and not occupied['collection']['retry_available']
            blocked = client.post(f'/api/papers/{paper.id}/collection/retry', json=dict(
                csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'], **occupied['collection']['retry']))
            assert blocked.status_code == 409
        finally:
            registry.release(reservation)
        snapshot, item = projected()
        assert item['collection']['retry_available'] is True
        assert item['collection']['attempt'] == 1
        assert 'signature' not in str(item) and 'private.invalid' not in str(item)
        endpoint = f'/api/papers/{paper.id}/collection/retry'
        body = dict(workspace_id=snapshot['workspace_id'], **item['collection']['retry'])
        assert client.post(endpoint, json=body).status_code == 403
        body['csrf_token'] = snapshot['csrf_token']
        assert client.post(endpoint, json={**body, 'workspace_id': str(uuid4())}).status_code == 409
        assert client.post(endpoint, json={**body, 'attempt': 99}).status_code == 409
        assert client.post(endpoint, json={**body, 'revision': item['revision'] - 1}).status_code == 409
        try:
            started = client.post(endpoint, json=body)
            assert started.status_code == 200, started.text
            assert entered.wait(2)
            assert started.json()['paper']['collection']['attempt'] == 2
            assert not started.json()['paper']['collection']['retry_available']
            assert client.post(endpoint, json=body).status_code == 409
        finally:
            release.set()
        deadline = monotonic() + 3
        while True:
            _, final = projected()
            if final['collection_status'] == 'completed':
                break
            assert monotonic() < deadline, final
            sleep(.01)
        assert final['abstract'] == 'Retry result'
        assert final['ordinary_dates'] == ['2026-11-14']
        assert final['collection_status'] == 'completed'
        assert not final['collection']['retry_available']
        assert client.post(endpoint, json={**body, **final['collection']['retry']}).status_code == 409


def test_projection_of_a_later_external_library_never_binds_or_normalizes_it(tmp_path):
    from test_web_app import write_valid_config
    config, workspace = write_valid_config(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        assert app.state.workspace_tasks.peek() is None
        workspace.mkdir()
        with PaperRepository.create(workspace) as repository:
            failed = repository.admit_collection(repository.workspace_id, lifecycle_id=uuid4(),
                branches=('document', 'necessary-api'), direct_ids=ExternalIds(pmid='42'), metadata=PaperMetadata(title='Failed'))
            for name in ('document', 'necessary-api'):
                repository.commit_collection_branch(failed.token, name, sequence=1, outcome='failed')
            repository.finish_collection(failed.token)
            queued = repository.admit_collection(repository.workspace_id, lifecycle_id=uuid4(),
                branches=('document', 'necessary-api'), direct_ids=ExternalIds(pmid='43'), metadata=PaperMetadata(title='Queued'))
            before = repository.snapshot()
        snapshot = client.get('/api/ui-next/workspace')
        assert snapshot.status_code == 200
        assert app.state.workspace_tasks.peek() is None
        assert not any(paper['collection']['retry_available'] for group in snapshot.json()['subjects']
            for journal in group['journals'] for paper in journal['papers'])
        with PaperRepository.open(workspace) as repository:
            assert repository.snapshot() == before
            assert repository.get(queued.paper.id).collection_status == 'queued'


def test_retry_never_forces_not_started_excluded_or_identity_only_metadata(tmp_path):
    config, workspace, paper = create_paper(tmp_path)
    app = create_app(config, electron_bridge=OfflineBridge(), diagnostics_root=tmp_path / 'logs')
    with TestClient(app, base_url='http://localhost') as client:
        def denied(item, snapshot):
            assert not item['collection']['retry_available']
            body = dict(csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'], **item['collection']['retry'])
            body['attempt'] = max(1, body['attempt'])
            assert client.post(f'/api/papers/{paper.id}/collection/retry', json=body).status_code == 409
        snapshot = client.get('/api/ui-next/workspace').json()
        denied(snapshot['subjects'][0]['journals'][0]['papers'][0], snapshot)
        with PaperRepository.open(workspace) as repository:
            current = repository.get(paper.id)
            current = repository.complete_body(current.token, BodyReference(relative_path='Documents/retained.pdf'))
            repository.exclude(current.token)
        snapshot = client.get('/api/ui-next/workspace').json()
        denied(snapshot['trash']['papers'][0]['paper'], snapshot)
        with PaperRepository.open(workspace) as repository:
            current = repository.get(paper.id)
            current = repository.clear_metadata(current.token)
            repository.unexclude(current.token)
        snapshot = client.get('/api/ui-next/workspace').json()
        item = snapshot['downloaded']['papers'][0]['paper']
        assert not item['metadata_present']
        denied(item, snapshot)
