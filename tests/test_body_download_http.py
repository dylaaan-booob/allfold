"""Identity-only public body actions over real host, files and SQLite."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from allfold.pdf_facts import PdfDiscoveryFacts
from allfold.persistence.paper_repository import PaperRepository
from allfold.web.app import create_app
from electron_test_helpers import PendingBridge
from library_application_helpers import create_paper


def test_public_download_reuses_exact_attempt_and_projects_durable_completion(tmp_path):
    fact = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi='10.5555/decision',
        landing_url='https://link.springer.com/article/10.5555/decision', platform='springer')
    config, workspace, paper = create_paper(tmp_path, discovery_facts=(fact,))
    bridge = PendingBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        assert item['download']['available']
        body = dict(csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'],qualification=item['download']['qualification'])
        endpoint = f'/api/papers/{paper.id}/body/download'
        assert client.post(endpoint, json={'workspace_id':snapshot['workspace_id']}).status_code == 403
        assert client.post(endpoint, json={**body, 'url':'https://attacker.example/file.pdf'}).status_code == 422
        assert client.post(endpoint, json={**body, 'workspace_id':str(uuid4())}).status_code == 409
        started = client.post(endpoint, json=body)
        assert started.status_code == 200, started.text
        assert bridge.dispatched.wait(2)
        task = started.json()['paper']['download']
        duplicate = client.post(endpoint, json=body).json()['paper']['download']
        assert (duplicate['task_id'], duplicate['attempt'], duplicate['deadline_ms']) == (task['task_id'],task['attempt'],task['deadline_ms'])
        assert len(bridge.calls) == 1
        assert bridge.calls[0][0] == 'stream_paper_body'
        data = bridge.calls[0][1]
        assert data['url'] == 'https://link.springer.com/content/pdf/10.5555%2Fdecision.pdf'
        bridge.progress({'received_bytes':4, 'total_bytes':0, 'url':'private-secret'})
        current = client.get('/api/ui-next/workspace').json()['subjects'][0]['journals'][0]['papers'][0]
        assert current['download']['received_bytes'] == 4 and current['download']['total_bytes'] is None
        assert 'private-secret' not in str(current)
        change=app.state.workspace_tasks.begin_change(providers=('openalex',))
        assert change.targets==(), 'Unused OpenAlex credentials must not revoke an active P1 stream'
        app.state.workspace_tasks.drain_change(change)
        app.state.workspace_tasks.finish_change(change)
        output = data['output']
        (Path(data['workspace_root'])/output['temporary']).write_bytes(b'body')
        bridge.future.set_result(dict(kind='pdf',outcome='stream_complete',pdf_type=True,transfer_complete=True,
            size_bytes=4,output_file=output['file'],final_url=data['url']))
        host = app.state.workspace_tasks.current()
        reservation = host._reservations.get(paper.id)
        if reservation:
            assert reservation.future.result(3).status == 'completed'
        final = client.get('/api/ui-next/workspace').json()
        saved = final['downloaded']['papers'][0]['paper']
        assert saved['body_present'] and saved['download']['pdf_source'] == 'P1'
        assert saved['download']['fallback_used'] is False
        assert not saved['download']['active'] and not saved['download']['available']
        assert 'output_file' not in str(saved) and str(workspace) not in str(saved)
        assert final['counts']['downloaded'] == 1 and final['counts']['candidates'] == 0


def test_cancel_is_exact_and_retains_occupancy_until_actual_terminal(tmp_path):
    fact = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi='10.5555/decision',
        landing_url='https://link.springer.com/article/10.5555/decision', platform='springer')
    config, workspace, paper = create_paper(tmp_path, discovery_facts=(fact,))
    bridge = PendingBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        snapshot=client.get('/api/ui-next/workspace').json()
        request=dict(csrf_token=snapshot['csrf_token'],workspace_id=snapshot['workspace_id'])
        download_request=request|dict(qualification=snapshot['subjects'][0]['journals'][0]['papers'][0]['download']['qualification'])
        start=f'/api/papers/{paper.id}/body/download'
        cancel=f'/api/papers/{paper.id}/body/cancel'
        active=client.post(start,json=download_request).json()['paper']['download']
        assert bridge.dispatched.wait(2)
        captured=dict(task_id=active['task_id'],attempt=active['attempt'])
        old_progress=bridge.progress
        assert client.post(cancel,json=request|captured|{'task_id':'other'}).status_code==409
        assert bridge.cancels==0
        result=client.post(cancel,json=request|captured)
        assert result.status_code==200 and result.json()['paper']['download']['cleaning_up']
        assert result.json()['paper']['download']['active'] and not result.json()['paper']['download']['available']
        task=app.state.workspace_tasks.current()._reservations[paper.id]
        assert not task.future.done() and bridge.cancels==1
        assert client.post(start,json=request).json()['paper']['download']['task_id']==active['task_id']
        bridge.future.set_result(dict(kind='cancelled',outcome='cancelled'))
        assert task.future.result(3).status=='cancelled'
        bridge.dispatched.clear()
        final=client.get('/api/ui-next/workspace').json()['subjects'][0]['journals'][0]['papers'][0]
        assert client.post(start,json=download_request).status_code==409
        retried=client.post(start,json=request|dict(qualification=final['download']['qualification'])).json()['paper']['download']
        assert retried['attempt']==active['attempt']+1 and retried['task_id']!=active['task_id']
        assert client.post(cancel,json=request|captured).status_code==409
        assert bridge.cancels==1
        assert bridge.dispatched.wait(2)
        current=app.state.workspace_tasks.current()._reservations[paper.id]
        old_progress({'received_bytes':999999})
        projected=client.get('/api/ui-next/workspace').json()['subjects'][0]['journals'][0]['papers'][0]
        assert projected['download']['received_bytes']==0 and projected['download']['task_id']==retried['task_id']
        client.post(cancel,json=request|dict(task_id=retried['task_id'],attempt=retried['attempt']))
        bridge.future.set_result(dict(kind='cancelled',outcome='cancelled'))
        current.future.result(3)


def test_existing_identity_only_trash_body_precedes_all_download_eligibility(tmp_path, monkeypatch):
    from allfold.persistence.paper_repository import BodyReference
    from electron_test_helpers import OfflineBridge
    config,workspace,paper=create_paper(tmp_path)
    with PaperRepository.open(workspace) as repository:
        paper=repository.complete_body(paper.token,BodyReference(relative_path='Documents/retained.pdf'))
        paper=repository.exclude(paper.token)
        paper=repository.clear_metadata(paper.token)
    app=create_app(config,electron_bridge=OfflineBridge(),diagnostics_root=tmp_path/'logs')
    seen=[]
    app.state.body_downloads.local_body=lambda captured,**kw:seen.append((captured,kw))
    monkeypatch.setattr('allfold.application.body_downloads.saved_pdf_target',lambda _:(_ for _ in ()).throw(AssertionError('No discovery target for local bodies')))
    with TestClient(app,base_url='http://localhost') as client:
        snapshot=client.get('/api/ui-next/workspace').json()
        response=client.post(f'/api/papers/{paper.id}/body/download',json=dict(csrf_token=snapshot['csrf_token'],workspace_id=snapshot['workspace_id']))
        assert response.status_code==200,response.text
        assert seen==[(paper,{'action':'open'})]
        assert response.json()['paper']['status']=='trash' and not app.state.workspace_tasks.active


def test_reject_restore_does_not_renew_a_late_download_click(tmp_path):
    config,workspace,paper=create_paper(tmp_path)
    bridge=PendingBridge()
    app=create_app(config,electron_bridge=bridge,diagnostics_root=tmp_path/'logs')
    with TestClient(app,base_url='http://localhost') as client:
        snapshot=client.get('/api/ui-next/workspace').json()
        item=snapshot['subjects'][0]['journals'][0]['papers'][0]
        request=dict(csrf_token=snapshot['csrf_token'],workspace_id=snapshot['workspace_id'],qualification=item['download']['qualification'])
        with PaperRepository.open(workspace) as repository:
            excluded=repository.exclude(paper.token)
            repository.restore(excluded.token)
        denied=client.post(f'/api/papers/{paper.id}/body/download',json=request)
        assert denied.status_code==409 and bridge.calls==[] and not app.state.workspace_tasks.active
