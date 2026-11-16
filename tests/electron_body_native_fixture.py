"""Public body HTTP -> production Bridge/Main -> original DownloadItem -> Workspace."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from functools import wraps
from pathlib import Path
import sys

import httpx
from fastapi import WebSocketDisconnect
from allfold.web.app import create_app
from allfold.web.electron_bridge import ElectronBridge
from allfold.models import ExternalIds
from allfold.pdf_facts import PdfDiscoveryFacts, PdfCandidateFact
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata
from allfold.persistence.body_files import ManagedBodyFiles
from allfold.persistence.user_state import load_user_state, compare_write_user_state
from allfold.application.browser_services import BrowserServiceSnapshot
from safety_config_helpers import current_mapping_document


def trace_native_adoption(owner, name):
    original = getattr(owner, name)
    @wraps(original)
    def traced(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except BaseException as error:
            print(json.dumps({'type': 'fixture_native_adoption_error', 'operation': name,
                'error': type(error).__name__, 'detail': str(error)[:256]}), file=sys.stderr, flush=True)
            raise
    setattr(owner, name, traced)


trace_native_adoption(ManagedBodyFiles, 'adopt_native')
trace_native_adoption(PaperRepository, 'adopt_native_output')


class Socket:
    headers = {'host': 'fixture'}
    def __init__(self):
        self.ready = asyncio.Event()
    async def accept(self):
        pass
    async def close(self, **kwargs):
        pass
    async def receive_json(self):
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            raise WebSocketDisconnect()
        return json.loads(line)
    async def send_json(self, value):
        print(json.dumps(value), flush=True)
        if value.get('type') == 'ready':
            self.ready.set()


def paper_projection(state, paper_id):
    for group in state['subjects']:
        for journal in group['journals']:
            for paper in journal['papers']:
                if paper['id'] == str(paper_id):
                    return paper
    return next(item['paper'] for item in state['downloaded']['papers'] if item['paper']['id'] == str(paper_id))


async def main():
    root, origin = Path(sys.argv[1]), sys.argv[2]
    config, _, _, service = current_mapping_document(root)
    workspace = root / 'workspace'
    workspace.mkdir(exist_ok=True)
    with PaperRepository.create(workspace):
        pass
    saved = load_user_state(config)
    compare_write_user_state(config, replace(saved.state, access_services=(service.model_copy(update={
        'access_method': 'manual', 'access_url': 'https://oce.ovid.com/fixture/prepared'}),)), saved.revision)
    socket, bridge = Socket(), ElectronBridge('fixture-only', 'fixture')
    application = create_app(config, electron_bridge=bridge, diagnostics_root=root / 'logs')
    receiver = asyncio.create_task(bridge.connect(socket))
    await socket.ready.wait()
    host = application.state.workspace_tasks
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://localhost')
    institution_ids = {'institution-complete': '11111111-111111111-11111',
        'institution-revoked': '22222222-222222222-22222', 'institution-unprepared': '33333333-333333333-33333'}
    async def invalidate_prepared(access, prepared):
        cleanup = bridge.execute('invalidate_access', dict(scope_id=access.scope['scope_id'],
            preparation_keys={service.id: prepared.key}, authentication_key=None))
        await asyncio.to_thread(cleanup.result, 5)
        application.state.login.invalidate_pages([prepared.page_id])
    try:
        for index, kind in enumerate(('attachment', 'inline', 'url-doi-form', 'microbiology-redirect', 'interrupted', 'iframe', 'iframe-many', 'predeclared-iframe', 'predeclared-target-changed', 'predeclared-popup-guard', 'existing-iframe', 'existing-target-changed', 'iframe-background', 'popup-background', 'iframe-replaced', 'popup-source-replaced', 'popup', 'named-popup', 'current-form', 'get-form', 'get-changed', 'sciencedirect', 'blocked',
                                      'action-blocked', 'action-challenge', 'action-challenge-iframe', 'action-challenge-popup', 'action-html',
                                      'institution-complete', 'institution-revoked', 'institution-unprepared', 'cancel', 'drain')):
            science = kind == 'sciencedirect'
            institutional = kind in institution_ids
            prepared = None
            if institutional and kind != 'institution-unprepared':
                application.state.login.start(config, manual_service_id=service.id)
                await asyncio.to_thread(application.state.login.join)
                access = BrowserServiceSnapshot.read(config)
                prepared = application.state.login.prepared_authority(access, service.id)
                assert prepared is not None and prepared.page_id is not None
            access_blocked = kind in {'blocked', 'action-blocked'} or kind.startswith('action-challenge')
            article = (origin.replace('www.microbiologyresearch.org', 'www.sciencedirect.com') + '/science/article/pii/S1234567890123456'
                if science else origin + ('/doi/10.5555/STRA%C3%9FE' if kind == 'url-doi-form' else '/article') + '?case=' + kind)
            candidate = PdfCandidateFact(stage='P4', rule_id='R024' if science else 'R059',
                url=article + '/pdfft' if science else origin + ('/expired-action' if kind == 'current-form' else '/once') + '?' + ('discard=old-action-query&' if kind in {'get-form', 'get-changed'} else '') + 'case=' + kind,
                reader_kind='sciencedirect' if science else None, action=None if science else 'refresh_form', referer=article)
            if institutional:
                lww = origin.replace('www.microbiologyresearch.org', 'journals.lww.com')
                article = lww+'/fixture/fulltext/2026/paper.aspx'
                candidate = PdfCandidateFact(stage='P4', rule_id='R060', reader_kind='lww',
                    url=lww+'/fixture/_layouts/15/oaks.journals/downloadpdf.aspx?an='+institution_ids[kind])
            fallback = kind in {'interrupted', 'institution-revoked', 'institution-unprepared'}
            fallback_url = (origin.replace('www.microbiologyresearch.org', 'repository.example.org')+'/oa.pdf?case='+kind
                if institutional else origin+'/fallback.pdf')
            identity = 'W' + str(88000 + index)
            facts = (PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete', observed_at=datetime.now(timezone.utc),
                target_openalex=identity, landing_url=article, platform='lww' if institutional else 'sciencedirect' if science else 'microbiology',
                candidates=(candidate,)),)
            if fallback:
                facts += (PdfDiscoveryFacts(source='openalex', capability='openalex-locations', status='complete',
                    observed_at=datetime.now(timezone.utc), target_openalex=identity,
                    candidates=(PdfCandidateFact(stage='P5', rule_id='OPENALEX', url=fallback_url),)),)
            with PaperRepository.open(workspace) as repo:
                paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(openalex=identity),
                    metadata=PaperMetadata(title='Public original body', publication_type='journal', journal='Biometrics',
                        journal_issns=('0006-341X',), discovery_facts=facts)).paper
            state = (await client.get('/api/ui-next/workspace')).json()
            projected = paper_projection(state, paper.id)
            assert projected['download']['available'], kind
            request = dict(csrf_token=state['csrf_token'], workspace_id=str(paper.workspace_id), qualification=projected['download']['qualification'])
            accepted = await client.post(f'/api/papers/{paper.id}/body/download', json=request)
            assert accepted.status_code == 200, accepted.text
            current = host.current()
            with current.paper_gate():
                task = current._reservations[paper.id]
            if institutional:
                async with asyncio.timeout(8):
                    while task.progress['received_bytes'] == 0:
                        assert not task.future.done(), (kind, task.future.result(), current.body_observations) if task.future.done() else None
                        await asyncio.sleep(.005)
                operation = task.access_operation
                assert operation is not None and not task.cancel_event.is_set()
                if prepared is not None:
                    assert operation.service_id == service.id
                    assert operation.authority.native_access().target_page_id == prepared.page_id
                else:
                    assert operation.service_id is None
                if kind == 'institution-revoked':
                    sequence = task.progress['sequence']
                    unrelated = host.begin_change(services=('svc_'+'f'*32,))
                    assert not unrelated.targets
                    await asyncio.to_thread(host.drain_change, unrelated)
                    host.finish_change(unrelated)
                    change = host.begin_change(services=(service.id,))
                    assert change.targets == (operation,) and not task.cancel_event.is_set()
                    await asyncio.to_thread(host.drain_change, change)
                    host.finish_change(change)
                    assert operation.future.done() and operation.browser_owner is None
                    async with asyncio.timeout(8):
                        while task.access_operation is None or task.access_operation.service_id is not None or task.progress['sequence'] <= sequence:
                            assert not task.future.done(), task.future.result() if task.future.done() else None
                            await asyncio.sleep(.005)
                    await invalidate_prepared(access, prepared)
                    prepared = None
                    later = host.begin_change(services=(service.id,))
                    assert not later.targets and not task.cancel_event.is_set() and not task.future.done()
                    await asyncio.to_thread(host.drain_change, later)
                    host.finish_change(later)
                    assert task.access_operation.authority.native_access().payload() == {}
                print(json.dumps({'type': 'fixture_release_body', 'case': kind,
                    'path': '/institution.pdf' if kind == 'institution-complete' else '/oa.pdf'}), flush=True)
            stopping = kind in {'cancel', 'drain'}
            if stopping:
                # Progress is observable through the public projection while the
                # original POST is still writing. No timer stands in for close.
                async with asyncio.timeout(5):
                    while True:
                        projected = paper_projection((await client.get('/api/ui-next/workspace')).json(), paper.id)
                        if projected['download'].get('received_bytes', 0) > 0:
                            break
                        assert not task.future.done(), task.future.result() if task.future.done() else None
                        await asyncio.sleep(.005)
                assert not projected['body_present']
                if kind == 'cancel':
                    cancel = await client.post(f'/api/papers/{paper.id}/body/cancel', json={
                        'csrf_token': state['csrf_token'], 'workspace_id': str(paper.workspace_id),
                        'task_id': task.task_id, 'attempt': task.download_token.attempt})
                    assert cancel.status_code == 200, cancel.text
                else:
                    from allfold.web.electron_server import drain_application
                    await drain_application(application)
            result = await asyncio.to_thread(task.future.result, 20 if kind.startswith('action-') else 10)
            stale = kind in {'get-changed', 'existing-target-changed', 'predeclared-target-changed'}
            expected = ('cancelled' if stopping else 'failed' if stale else 'failed' if kind == 'action-html'
                        else 'failed' if access_blocked else 'completed')
            assert result.status == expected, (kind, result)
            projected = paper_projection((await client.get('/api/ui-next/workspace')).json(), paper.id)
            assert projected['body_present'] is (expected == 'completed')
            assert not projected['download']['active'] and not projected['cleanup_pending']
            assert not host.active
            with PaperRepository.open(workspace) as repo:
                stored = repo.get(paper.id)
                assert stored.download.status == ('failed' if expected == 'local_failure' else 'cancelled' if expected == 'stale' else expected)
                assert stored.collection is None
                if expected == 'completed':
                    assert stored.body.pdf_source == ('P5' if fallback else 'P2' if science else 'P4')
                    assert stored.body.fallback_used is (fallback or institutional), kind
                    if fallback:
                        observations=projected['download']['source_observations']
                        reason = {'institution-revoked': 'service-invalidated', 'institution-unprepared': 'service-unprepared'}.get(kind, 'interrupted')
                        assert any(item['pdf_reason'] == reason and (not institutional or item['service_id'] == service.id) for item in observations)
                    assert 'Signature' not in str(projected)
                    assert stored.body.size_bytes == 256 * 1024
                elif access_blocked:
                    assert stored.download.reason == 'access-blocked'
                elif kind == 'action-html' or stale:
                    assert stored.download.reason == ('non-pdf' if kind=='action-html' else 'native-action')
            if prepared is not None:
                await invalidate_prepared(access, prepared)
            if institutional:
                assert task.access_operation is None and not host.browser_lock.owners
            print(json.dumps({'type': 'fixture_public_native', 'case': kind, 'status': result.status, 'paper': str(paper.id)}), flush=True)
        print(json.dumps({'type': 'fixture_complete'}), flush=True)
    finally:
        await client.aclose()
        await asyncio.to_thread(host.shutdown)
        await asyncio.to_thread(host.join)
    await receiver


async def checked():
    try:
        await main()
    except BaseException:
        import os, traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)


asyncio.run(checked())
