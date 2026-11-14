"""Framed transport through production Bridge, application host and Workspace projection."""
import asyncio
import json
from pathlib import Path
import sys
import threading

import httpx
from fastapi import WebSocketDisconnect
from allfold.web.electron_bridge import ElectronBridge
from allfold.web.app import create_app
from allfold.application.body_downloads import submit_body_download, BodyResult
from allfold.models import ExternalIds
from allfold.pdf_rules import PdfTarget, PdfCandidate
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata
from safety_config_helpers import current_mapping_document


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
    async def send_json(self, message):
        print(json.dumps(message), flush=True)
        if message.get('type') == 'ready':
            self.ready.set()


async def main():
    root, origin = Path(sys.argv[1]), sys.argv[2]
    config, _, _, service = current_mapping_document(root)
    workspace = root / 'workspace'
    workspace.mkdir()
    with PaperRepository.create(workspace):
        pass
    socket = Socket()
    bridge = ElectronBridge('fixture-only', 'fixture')
    application = create_app(config, electron_bridge=bridge, diagnostics_root=root / 'logs')
    receiver = asyncio.create_task(bridge.connect(socket))
    await socket.ready.wait()
    # Real saved Service authority, using the established manual-confirmation policy.
    from dataclasses import replace
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_services import BrowserServiceSnapshot
    saved=load_user_state(config)
    service=service.model_copy(update={'access_method':'manual'})
    compare_write_user_state(config,replace(saved.state,access_services=(service,)),saved.revision)
    login=application.state.login
    login.start(config)
    await asyncio.to_thread(login.join)
    access=BrowserServiceSnapshot.read(config)
    login.confirm_all(access,login.snapshot(access)['confirmation_workflow_id'])
    host = application.state.workspace_tasks
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url='http://localhost')
    try:
        for index, path in enumerate(['redirect?Signature=A%2FB', 'encoded', 'chunked', 'html.pdf', 'unknown', 'truncated', 'cancel', 'expiry', 'cross', 'challenge', 'disk-write', 'disk-flush', 'slow-writer', 'cross-referer']):
            with PaperRepository.open(workspace) as repo:
                paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi=f'10.5555/body{index}'),
                    metadata=PaperMetadata(title='Same title')).paper
            target = PdfTarget(str(paper.id), doi=f'10.5555/body{index}', direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
            candidate = PdfCandidate(target, 'P1', 'GENERIC', 'generic', origin+'/'+path,
                referer=origin.replace('pdf.','other.')+'/article?InstitutionToken=synthetic' if path=='cross-referer' else origin+'/article')
            received, closing = threading.Event(), threading.Event()
            def progress(value):
                if value.get('received_bytes',0)>0:received.set()
                if value.get('fixture_close_pending'):closing.set()
            task = await asyncio.to_thread(submit_body_download, host, paper, candidates=(candidate,), service_id=service.id,
                deadline=__import__('time').monotonic() + (.3 if path=='expiry' else 8),
                progress=progress)
            if path in {'redirect?Signature=A%2FB','cancel','expiry'}:
                assert await asyncio.to_thread(received.wait, 3)
                # Observe bytes on disk while the real server is still streaming.
                for _ in range(100):
                    parts=list((workspace/'Documents/.downloads').glob('*.part'))
                    if any(item.stat().st_size>0 for item in parts):break
                    await asyncio.sleep(.001)
                assert any(item.stat().st_size>0 for item in parts) and not task.future.done()
                before = (await client.get('/api/ui-next/workspace')).json()
                assert 'Downloaded' not in str(before.get('downloaded',[]))
                duplicate = await asyncio.to_thread(submit_body_download, host, paper, candidates=(candidate,), service_id=service.id)
                assert duplicate is task
                if path=='redirect?Signature=A%2FB':
                    with PaperRepository.open(workspace) as repo:
                        repo.edit_metadata(paper.token, {'abstract':'Manual abstract', 'notes':'Manual notes'})
                    admitted = host.current().admit(direct_ids=ExternalIds(doi=f'10.5555/body{index}'),
                        metadata=paper.metadata, branches=(), no_applicable=True)
                    assert admitted.id == paper.id and admitted.collection is None
                if path=='cancel':
                    host.current().cancel_paper(paper.id, paper.workspace_id)
            if path=='slow-writer':
                assert await asyncio.to_thread(closing.wait,3)
                assert not task.future.done() and host.active
                with PaperRepository.open(workspace) as repo:
                    assert repo.get(paper.id).body is None
            result = await asyncio.to_thread(task.future.result, 10)
            with PaperRepository.open(workspace) as repo:
                saved = repo.get(paper.id)
            if path.startswith('disk-'):assert result.status=='local_failure'
            if path=='challenge':assert result.candidate_result.response.access=='challenge'
            if path=='html.pdf':assert result.candidate_result.response.access=='login'
            success = path in {'redirect?Signature=A%2FB','encoded','chunked','slow-writer','cross-referer'}
            assert (result.status == 'completed') == success, (path,result)
            assert (saved.body is not None) == success
            if success:
                assert (workspace / saved.body.relative_path).stat().st_size == saved.body.size_bytes
                assert 'Signature' not in saved.body.source_url
                again = await asyncio.to_thread(submit_body_download, host, saved, candidates=(candidate,))
                assert isinstance(again,BodyResult) and again.paper.body == saved.body
            assert not host.active
            projection = (await client.get('/api/ui-next/workspace')).json()
            encoded = json.dumps(projection)
            assert str(workspace) not in encoded and 'Signature' not in encoded and 'output_file' not in encoded
            assert saved.download.status == ('completed' if success else 'cancelled' if path in {'cancel','expiry'} else 'failed'), (path, result, saved.download)
            if index==0:
                assert saved.metadata.abstract=='Manual abstract' and saved.metadata.notes=='Manual notes'
            print(json.dumps({'type':'fixture_case','path':path,'status':result.status,'paper':str(paper.id)}),flush=True)
        # Equal URL, separate native request/attempt/output. Cancel only A.
        pair=[]
        for index in range(2):
            with PaperRepository.open(workspace) as repo:
                paper=repo.create_or_match(repo.workspace_id,direct_ids=ExternalIds(doi=f'10.5555/same{index}'),metadata=PaperMetadata(title='Same')).paper
            target=PdfTarget(str(paper.id),doi=f'10.5555/same{index}',direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
            candidate=PdfCandidate(target,'P1','GENERIC','generic',origin+'/same',referer=origin+'/article')
            received=threading.Event()
            task=await asyncio.to_thread(submit_body_download,host,paper,candidates=(candidate,),
                progress=lambda value,event=received:event.set() if value.get('received_bytes',0)>0 else None)
            pair.append((paper,task,received))
        assert all([await asyncio.to_thread(event.wait,3) for _,_,event in pair])
        host.current().cancel_paper(pair[0][0].id)
        values=await asyncio.gather(*(asyncio.to_thread(task.future.result,5) for _,task,_ in pair))
        assert [value.status for value in values]==['cancelled','completed']
        assert not host.active
        print(json.dumps({'type':'fixture_pair','statuses':[value.status for value in values]}),flush=True)
        with PaperRepository.open(workspace) as repo:
            paper=repo.create_or_match(repo.workspace_id,direct_ids=ExternalIds(doi='10.5555/shutdown'),metadata=PaperMetadata(title='Shutdown')).paper
        target=PdfTarget(str(paper.id),doi='10.5555/shutdown',direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
        candidate=PdfCandidate(target,'P1','GENERIC','generic',origin+'/shutdown',referer=origin+'/article')
        received=threading.Event()
        task=await asyncio.to_thread(submit_body_download,host,paper,candidates=(candidate,),service_id=service.id,
            progress=lambda value:received.set() if value.get('received_bytes',0)>0 else None)
        assert await asyncio.to_thread(received.wait,3)
        from allfold.web.electron_server import drain_application
        await drain_application(application)
        assert task.future.done() and task.future.result().status=='cancelled' and not host.active
        print(json.dumps({'type':'fixture_drain','status':'settled'}),flush=True)
        await asyncio.to_thread(host.shutdown)
        await asyncio.to_thread(host.join)
        print(json.dumps({'type':'fixture_complete'}),flush=True)
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
