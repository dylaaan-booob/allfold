"""Identity-only public body actions over real host, files and SQLite."""
from concurrent.futures import Future
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from allfold.pdf_facts import PdfDiscoveryFacts
from allfold.persistence.paper_repository import PaperRepository
from allfold.web.app import create_app
from electron_test_helpers import PendingBridge
from library_application_helpers import create_paper


@pytest.mark.parametrize('oce_context', ['permitted', 'denied', 'unbound'])
def test_public_lww_empty_viewer_uses_only_its_captured_oce_capability(tmp_path, oce_context):
    import httpx
    from allfold.config import AccessService
    from allfold.pdf_facts import PdfIdentifier, openalex_discovery_facts
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from library_application_helpers import read_paper
    from test_document_metadata import envelope, pdf_clues
    from test_login import opened

    article = 'https://journals.lww.com/journal/fulltext/2026/paper.aspx'
    pdf = 'https://assets.ovid.com/Body.PDF?Signature=A%2FB&key=Keep'
    fact = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi='10.5555/decision', landing_url=article,
        platform='lww', identifiers=(PdfIdentifier(kind='an', value='22222222-222222222-22222', rule_id='R060'),))
    empty = openalex_discovery_facts({'doi': '10.5555/decision', 'best_oa_location': None, 'locations': []},
        datetime.now(timezone.utc))
    config, workspace, paper = create_paper(tmp_path, discovery_facts=(fact, empty))
    service = AccessService.create('Prepared reader', 'https://ds.carsi.edu.cn/resource/entry', access_method='manual')
    if oce_context != 'unbound':
        saved = load_user_state(config)
        compare_write_user_state(config, replace(saved.state, access_services=(service,), journals=tuple(
            journal.model_copy(update={'access_service_id': service.id}) for journal in saved.state.journals)), saved.revision)

    class OceBodyBridge:
        connected, closing = True, False
        def __init__(self):
            self.calls, self.first, self.body_terminal = [], Future(), Future()
            self.started, self.body_written = Event(), Event()
            self.used_oce = False

        def execute(self, action, data, progress=None, *, verify_recovery=None):
            if verify_recovery: verify_recovery()
            self.calls.append((action, data))
            result = Future()
            if action == 'visit_manual_service':
                result.set_result(opened(17))
            elif action == 'extract_paper_pdf_clues':
                assert 'wantAbstract' not in data
                if data.get('reader_access_only'):
                    result.set_result({'outcome': 'retrieved', 'reader_access': {'oce': oce_context != 'denied'}})
                else:
                    reader = data['reader']
                    assert reader['platform'] in {'lww', 'oce'}
                    self.used_oce = reader['platform'] == 'oce'
                    result.set_result(envelope() | {'pdf_clues': pdf_clues(platform=reader['platform'],
                        landing_url=reader['url'], candidates=[{'stage': 'P4', 'rule_id': 'R060', 'url': pdf}]
                        if self.used_oce else [])})
            else:
                assert action == 'stream_paper_body'
                if data['url'].startswith('https://journals.lww.com/'):
                    self.started.set()
                    return self.first
                assert data['url'] == pdf
                output = data['output']
                (Path(data['workspace_root'])/output['temporary']).write_bytes(b'OCE body')
                self.body_result = dict(kind='pdf', outcome='stream_complete', pdf_type=True, transfer_complete=True,
                    size_bytes=8, output_file=output['file'], final_url=pdf)
                self.body_written.set()
                return self.body_terminal
            return result

        def cancel_task(self, *_): pass
        def finish_disconnected(self): pass

    bridge = OceBodyBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    def unavailable_api(request):
        assert request.url.host in {'doi.org', 'api.crossref.org'}
        return httpx.Response(404, json={})
    app.state.body_downloads.http_options = {'transport': httpx.MockTransport(unavailable_api),
        'resolver': lambda *_: ('93.184.216.34',)}
    with TestClient(app, base_url='http://localhost') as client:
        if oce_context != 'unbound':
            app.state.login.start(config, manual_service_id=service.id)
            app.state.login.join()
        snapshot = client.get('/api/ui-next/workspace').json()
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        response = client.post(f'/api/papers/{paper.id}/body/download', json=dict(csrf_token=snapshot['csrf_token'],
            workspace_id=snapshot['workspace_id'], qualification=item['download']['qualification']))
        assert response.status_code == 200, response.text
        assert bridge.started.wait(2)
        registry = app.state.workspace_tasks.current()
        task = registry._reservations[paper.id]
        first = next(data for action, data in bridge.calls if action == 'stream_paper_body')
        try:
            bridge.first.set_result(dict(kind='response', outcome='response', response=dict(url=first['url'],
                content_type='text/html', status=200, body='<body>Empty viewer</body>', access=None)))
            if oce_context == 'permitted':
                assert bridge.body_written.wait(2), 'The public body owner must enter its qualified OCE branch'
                assert not task.future.done() and app.state.workspace_tasks.active
                assert read_paper(workspace, paper.id).download.status == 'running'
        finally:
            if oce_context == 'permitted':
                bridge.body_terminal.set_result(bridge.body_result)
        result = task.future.result(3)
        body_calls = [(action, data) for action, data in bridge.calls if action in {'stream_paper_body', 'extract_paper_pdf_clues'}]
        readers = [data['reader']['platform'] for _, data in body_calls if 'reader' in data]
        assert readers == (['lww', 'oce'] if oce_context == 'permitted' else ['lww'])
        assert sum(bool(data.get('reader_access_only')) for _, data in body_calls) == (oce_context != 'unbound')
        assert all((data['workflow_id'], data['task_id']) == (task.workflow_id, task.task_id) for _, data in body_calls)
        if oce_context != 'unbound':
            assert all(data['service_id'] == service.id and data['target_page_id'] == 17 for _, data in body_calls)
        saved = read_paper(workspace, paper.id)
        assert saved.metadata == paper.metadata and saved.collection_status == 'not_started'
        projection = client.get('/api/ui-next/workspace').json()
        if oce_context == 'permitted':
            assert result.status == 'completed' and saved.body.pdf_source == 'P4' and saved.body.fallback_used
            assert (workspace/saved.body.relative_path).read_bytes() == b'OCE body'
            assert saved.download.output is None and projection['counts']['downloaded'] == 1
            assert 'Signature' not in str(saved.body) and 'Signature' not in str(projection)
        else:
            assert saved.body is None and saved.download.status == 'failed' and projection['counts']['downloaded'] == 0
        assert not app.state.workspace_tasks.active


@pytest.mark.parametrize('html', [
    '<body><p>CPE00001</p><p>There was a problem providing the content you requested</p></body>',
    '<body><iframe src="/_Incapsula_Resource?edet=15&incident_id=123-456">Request unsuccessful. Incapsula incident ID: 123-456</iframe></body>',
    '<body><div class="hcaptcha">Verify you are human</div></body>',
], ids=['visible-cpe', 'imperva-shell', 'challenge'])
def test_public_bounded_html_access_barrier_persists_its_reason_without_fallback(tmp_path, html):
    import httpx
    from allfold.pdf_facts import PdfCandidateFact, openalex_discovery_facts
    from library_application_helpers import read_paper

    fact = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi='10.5555/decision',
        landing_url='https://link.springer.com/article/10.5555/decision', platform='springer',
        candidates=(PdfCandidateFact(stage='P3', rule_id='GENERIC', url='https://cdn.example.org/Alternative.PDF',
            field='citation_pdf_url'),))
    fallback = openalex_discovery_facts({'doi': '10.5555/decision',
        'best_oa_location': {'pdf_url': 'https://repository.example/Fallback.PDF'}, 'locations': []},
        datetime.now(timezone.utc))
    config, workspace, paper = create_paper(tmp_path, discovery_facts=(fact, fallback))
    bridge = PendingBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    app.state.body_downloads.http_options = {'transport': httpx.MockTransport(
        lambda _: pytest.fail('Access refusal must not start another discovery request'))}
    with TestClient(app, base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        started = client.post(f'/api/papers/{paper.id}/body/download', json=dict(csrf_token=snapshot['csrf_token'],
            workspace_id=snapshot['workspace_id'], qualification=item['download']['qualification']))
        assert started.status_code == 200, started.text
        assert bridge.dispatched.wait(2)
        task = app.state.workspace_tasks.current()._reservations[paper.id]
        data = bridge.calls[0][1]
        bridge.future.set_result(dict(kind='response', outcome='response', response=dict(url=data['url'],
            content_type='text/html', status=200, body=html, access=None)))
        result = task.future.result(3)
        assert result.status == 'failed' and result.candidate_result.diagnostic == 'access-blocked'
        saved = read_paper(workspace, paper.id)
        assert saved.download.status == 'failed' and saved.download.reason == 'access-blocked'
        assert saved.body is None and saved.download.output is None and saved.metadata == paper.metadata
        assert [action for action, _ in bridge.calls] == ['stream_paper_body']
        assert not list((workspace/'Documents').rglob('*.part')) and not app.state.workspace_tasks.active
        projection = client.get('/api/ui-next/workspace').json()
        current = projection['subjects'][0]['journals'][0]['papers'][0]
        assert current['download']['reason'] == 'access-blocked'
        assert projection['counts']['candidates'] == 1 and projection['counts']['downloaded'] == 0


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


def test_terminal_storage_failure_is_idle_and_explicit_download_recovers_exact_attempt(tmp_path, monkeypatch):
    from allfold.persistence.paper_repository import LibraryError
    fact = PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
        observed_at=datetime.now(timezone.utc), target_doi='10.5555/decision',
        landing_url='https://link.springer.com/article/10.5555/decision', platform='springer')
    config, workspace, paper = create_paper(tmp_path, discovery_facts=(fact,))
    bridge = PendingBridge()
    app = create_app(config, electron_bridge=bridge, diagnostics_root=tmp_path/'logs')
    with TestClient(app, base_url='http://localhost') as client:
        snapshot = client.get('/api/ui-next/workspace').json()
        request = dict(csrf_token=snapshot['csrf_token'], workspace_id=snapshot['workspace_id'])
        item = snapshot['subjects'][0]['journals'][0]['papers'][0]
        endpoint = f'/api/papers/{paper.id}/body/download'
        assert client.post(endpoint, json=request | dict(qualification=item['download']['qualification'])).status_code == 200
        assert bridge.dispatched.wait(2)
        registry = app.state.workspace_tasks.current()
        old = registry._reservations[paper.id]
        with monkeypatch.context() as patch:
            def failed_write(*args, **kwargs):
                raise LibraryError('controlled private terminal store error')
            patch.setattr(PaperRepository, 'finish_download', failed_write)
            bridge.future.set_result(dict(kind='local_failure', outcome='local_failure'))
            with pytest.raises(LibraryError):
                old.future.result(3)
            assert not registry.active
            with PaperRepository.open(workspace) as repository:
                before = repository.revision
                assert repository.get(paper.id).download.active
            projected = client.get('/api/ui-next/workspace').json()['subjects'][0]['journals'][0]['papers'][0]
            assert projected['download']['status'] == 'failed' and projected['download']['reason'] == 'storage-error'
            assert projected['download']['available'] and not projected['download']['active'] and not projected['cleanup_pending']
            assert 'private' not in str(projected)
            with PaperRepository.open(workspace) as repository:
                assert repository.revision == before
            retry = request | dict(qualification=projected['download']['qualification'])
            denied = client.post(endpoint, json=retry)
            assert denied.status_code == 409 and '数据库' in denied.json()['message']
            assert len(bridge.calls) == 1
        bridge.dispatched.clear()
        accepted = client.post(endpoint, json=retry)
        assert accepted.status_code == 200, accepted.text
        assert bridge.dispatched.wait(2)
        current = registry._reservations[paper.id]
        assert current.download_token.attempt == old.download_token.attempt + 1
        assert not app.state.body_downloads.cancel(paper.id, paper.workspace_id, old.task_id, old.download_token.attempt)
        data = bridge.calls[-1][1]
        assert data['output']['temporary'] != bridge.calls[0][1]['output']['temporary']
        (workspace/data['output']['temporary']).write_bytes(b'body')
        bridge.future.set_result(dict(kind='pdf', outcome='stream_complete', pdf_type=True, transfer_complete=True,
            output_file=data['output']['file'], size_bytes=4, final_url=data['url']))
        assert current.future.result(3).status == 'completed' and not registry.active


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


def test_public_missing_input_api_is_lazy_and_its_answer_drives_first_session_body_request(tmp_path):
    import httpx
    config,workspace,paper=create_paper(tmp_path)
    api_requests=[]
    def api(request):
        api_requests.append(str(request.url))
        assert str(request.url)=='https://doi.org/api/handles/10.5555/decision'
        return httpx.Response(200,json={'values':[{'type':'URL','data':{'value':'https://link.springer.com/article/10.5555/Decision'}}]})
    bridge=PendingBridge()
    app=create_app(config,electron_bridge=bridge,diagnostics_root=tmp_path/'logs')
    app.state.body_downloads.http_options={'transport':httpx.MockTransport(api),'resolver':lambda *_:('93.184.216.34',)}
    with TestClient(app,base_url='http://localhost') as client:
        snapshot=client.get('/api/ui-next/workspace').json()
        item=snapshot['subjects'][0]['journals'][0]['papers'][0]
        response=client.post(f'/api/papers/{paper.id}/body/download',json=dict(csrf_token=snapshot['csrf_token'],
            workspace_id=snapshot['workspace_id'],qualification=item['download']['qualification']))
        assert response.status_code==200,response.text
        assert bridge.dispatched.wait(2)
        task=app.state.workspace_tasks.current()._reservations[paper.id]
        data=bridge.calls[-1][1]
        assert api_requests==['https://doi.org/api/handles/10.5555/decision']
        assert len(bridge.calls)==1 and bridge.calls[0][0]=='stream_paper_body'
        assert data['url']=='https://link.springer.com/content/pdf/10.5555%2Fdecision.pdf'
        output=data['output'];(Path(data['workspace_root'])/output['temporary']).write_bytes(b'body')
        bridge.future.set_result(dict(kind='pdf',outcome='stream_complete',pdf_type=True,transfer_complete=True,
            size_bytes=4,output_file=output['file'],final_url=data['url']))
        assert task.future.result(3).status=='completed'
        final=client.get('/api/ui-next/workspace').json()['downloaded']['papers'][0]['paper']
        assert final['download']['pdf_source']=='P2' and final['download']['fallback_used'] is False
        assert final['collection_status']=='not_started'
