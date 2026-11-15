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
    compare_write_user_state(config, replace(saved.state, access_services=(service.model_copy(update={'access_method': 'manual'}),)), saved.revision)
    socket, bridge = Socket(), ElectronBridge('fixture-only', 'fixture')
    application = create_app(config, electron_bridge=bridge, diagnostics_root=root / 'logs')
    receiver = asyncio.create_task(bridge.connect(socket))
    await socket.ready.wait()
    login = application.state.login
    login.start(config)
    await asyncio.to_thread(login.join)
    access = BrowserServiceSnapshot.read(config)
    login.confirm_all(access, login.snapshot(access)['confirmation_workflow_id'])
    host = application.state.workspace_tasks
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://localhost')
    try:
        for index, kind in enumerate(('attachment', 'inline', 'iframe', 'existing-iframe', 'existing-target-changed', 'iframe-background', 'popup-background', 'iframe-replaced', 'popup-source-replaced', 'popup', 'current-form', 'get-form', 'get-changed', 'sciencedirect', 'blocked',
                                      'action-blocked', 'action-challenge', 'action-challenge-iframe', 'action-challenge-popup', 'action-html', 'cancel', 'drain')):
            science = kind == 'sciencedirect'
            access_blocked = kind in {'blocked', 'action-blocked'} or kind.startswith('action-challenge')
            article = (origin.replace('www.microbiologyresearch.org', 'www.sciencedirect.com') + '/science/article/pii/S1234567890123456'
                if science else origin + '/article?case=' + kind)
            candidate = PdfCandidateFact(stage='P4', rule_id='R024' if science else 'R059',
                url=article + '/pdfft' if science else origin + ('/expired-action' if kind == 'current-form' else '/once') + '?' + ('discard=old-action-query&' if kind in {'get-form', 'get-changed'} else '') + 'case=' + kind,
                reader_kind='sciencedirect' if science else None, action=None if science else 'refresh_form', referer=article)
            identity = 'W' + str(88000 + index)
            with PaperRepository.open(workspace) as repo:
                paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(openalex=identity),
                    metadata=PaperMetadata(title='Public original body', discovery_facts=(PdfDiscoveryFacts(
                        source='document', capability='document-pdf', status='complete', observed_at=datetime.now(timezone.utc),
                        target_openalex=identity, landing_url=article, platform='sciencedirect' if science else 'microbiology',
                        candidates=(candidate,)),))).paper
            state = (await client.get('/api/ui-next/workspace')).json()
            projected = paper_projection(state, paper.id)
            request = dict(csrf_token=state['csrf_token'], workspace_id=str(paper.workspace_id), qualification=projected['download']['qualification'])
            accepted = await client.post(f'/api/papers/{paper.id}/body/download', json=request)
            assert accepted.status_code == 200, accepted.text
            current = host.current()
            with current.paper_gate():
                task = current._reservations[paper.id]
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
            stale = kind in {'get-changed', 'existing-target-changed', 'iframe-replaced', 'popup-source-replaced'}
            expected = ('cancelled' if stopping else 'stale' if stale else 'local_failure' if kind == 'action-html'
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
                    assert stored.body.pdf_source == 'P4' and stored.body.fallback_used is False
                    assert stored.body.size_bytes == 256 * 1024
                elif access_blocked:
                    assert stored.download.reason == 'access-blocked'
                elif kind == 'action-html' or stale:
                    assert stored.download.reason == 'native-action'
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
