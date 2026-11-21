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
from safety_config_helpers import A, current_mapping_document


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
    root, origin, secure_origin = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    config, _, _, service = current_mapping_document(root)
    config.write_text(config.read_text()+'enabled_providers: [openalex]\n')
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
        # Formal public identity-only entry, through the same authenticated
        # Bridge/Main Session, managed files, SQLite and Workspace projection.
        from datetime import datetime, timezone
        from allfold.pdf_facts import PdfDiscoveryFacts, PdfCandidateFact
        from allfold.application.integrated_run import run_integrated
        from allfold.application.collection_planner import ProductionCollectionService
        from allfold.application.collection_runtime import BranchSpec
        from allfold.persistence.paper_repository import MetadataDelta
        from allfold.models import ProviderWorkEvidence, MetadataSource
        from allfold.config import load_config
        from test_integrated_run import client_for
        from integrated_run_helpers import EmptyLookup
        collected, release_collection = threading.Event(), threading.Event()
        facts=PdfDiscoveryFacts(source='document',capability='document-pdf',status='complete',
            observed_at=datetime.now(timezone.utc),target_openalex='W777',landing_url=origin+'/article',
            candidates=(PdfCandidateFact(stage='P3',rule_id='GENERIC',url=origin.replace('pdf.','other.')+'/challenge',
                referer=origin+'/article',field='citation_pdf_url'),
                PdfCandidateFact(stage='P4',rule_id='GENERIC',url=origin+'/public',referer=origin+'/article')))
        collection_calls=[]
        class Collection(ProductionCollectionService):
            def plan(self,**kwargs):
                def collect(context):
                    collection_calls.append(context)
                    collected.set()
                    assert release_collection.wait(5)
                    context.emit(MetadataDelta(abstract='Collected abstract.',ordinary_dates=('2026-01-02',),
                        discovery_facts=(facts,)),sequence=1)
                return (BranchSpec('document',collect,service_id=None),)
        row=ProviderWorkEvidence(title='Public PDF',journal='Biometrics',publication_type='journal',
            external_ids=ExternalIds(openalex='W777'),provenance=MetadataSource(provider='openalex',
                record_id='W777',retrieved_at=datetime.now(timezone.utc)))
        planner=Collection(host)
        run_options=dict(loaded_config=load_config(config),
            client_factory=client_for((row,)),lookup_factory=EmptyLookup,workspace_tasks=host,collection_service=planner)
        run=await asyncio.to_thread(run_integrated,config,**run_options)
        assert run.facts.created_papers==1, run.facts
        assert collected.wait(2), (run.facts,host.current().faults)
        with PaperRepository.open(workspace) as repo:
            public,=repo.list_papers()
            assert public.collection.active and public.metadata.abstract is None and public.body is None
        collection_task=host.current()._tasks[public.id]
        release_collection.set()
        await asyncio.to_thread(collection_task.future.result,5)
        with PaperRepository.open(workspace) as repo:
            public=repo.get(public.id)
            assert public.collection_status=='completed' and public.metadata.abstract=='Collected abstract.'
            assert public.metadata.ordinary_dates==('2026-01-02',) and public.metadata.discovery_facts==(facts,)
        repeat=await asyncio.to_thread(run_integrated,config,**run_options)
        assert repeat.facts.existing_papers==1 and len(collection_calls)==1
        state = (await client.get('/api/ui-next/workspace')).json()
        public_projection = next(paper for group in state['subjects'] for journal in group['journals'] for paper in journal['papers'] if paper['id']==str(public.id))
        public_request = dict(csrf_token=state['csrf_token'], workspace_id=str(public.workspace_id),
            qualification=public_projection['download']['qualification'])
        accepted = await client.post(f'/api/papers/{public.id}/body/download', json=public_request)
        assert accepted.status_code == 200, accepted.text
        current = host.current()
        with current.paper_gate():
            public_task = current._reservations[public.id]
        assert (await asyncio.to_thread(public_task.future.result, 8)).status == 'completed'
        projection = (await client.get('/api/ui-next/workspace')).json()
        projected = next(entry['paper'] for entry in projection['downloaded']['papers'] if entry['paper']['id'] == str(public.id))
        assert projected['download']['pdf_source'] == 'P4' and projected['download']['fallback_used'] is True
        observations=projected['download']['source_observations']
        assert any(item['pdf_reason']=='access-challenge' and item['subsequent_attempted'] for item in observations)
        assert projected['body_present'] and projection['counts']['downloaded'] == 1
        assert not projected['download']['active'] and not projected['cleanup_pending']
        print(json.dumps({'type':'fixture_public','status':'completed','paper':str(public.id)}), flush=True)
        local_request = dict(csrf_token=state['csrf_token'], workspace_id=str(public.workspace_id),
            body_generation=projected['download']['qualification']['body_generation'])
        # Existing-body Download uses local authority before discovery or Prepare.
        opened = await client.post(f'/api/papers/{public.id}/body/download', json={key:value for key,value in local_request.items() if key != 'body_generation'})
        assert opened.status_code == 200 and opened.json()['outcome'] == 'opened', opened.text
        located = await client.post(f'/api/papers/{public.id}/body/locate', json=local_request)
        assert located.status_code == 200 and located.json()['outcome'] == 'locate_requested', located.text
        shell_failed = await client.post(f'/api/papers/{public.id}/body/open', json=local_request)
        assert shell_failed.status_code == 409 and shell_failed.json()['paper']['body_present'], shell_failed.text
        # A completed Paper remains complete; local reads cannot restart collection.
        from allfold.persistence.paper_repository import PaperRecord
        collected = await asyncio.to_thread(current.submit, direct_ids=ExternalIds(openalex='W777'),
            metadata=public.metadata, branches=(BranchSpec('document',lambda _: (_ for _ in ()).throw(AssertionError('Completed Paper recollected')),service_id=None),))
        assert isinstance(collected,PaperRecord) and collected.collection_status=='completed'
        reading = await client.post(f'/api/papers/{public.id}/body/open', json=local_request)
        assert reading.status_code == 200 and reading.json()['outcome'] == 'opened', reading.text
        rejected = await client.post(f'/api/ui-next/papers/{public.id}/reject', json={key:value for key,value in local_request.items() if key != 'body_generation'})
        assert rejected.status_code == 200, rejected.text
        deleted = await client.post(f'/api/papers/{public.id}/body/delete', json=local_request)
        assert deleted.status_code == 200 and deleted.json()['outcome'] == 'deleted', deleted.text
        assert not (workspace/'Documents'/f'{public.id}.pdf').exists()
        restored = await client.post(f'/api/ui-next/papers/{public.id}/restore', json={key:value for key,value in local_request.items() if key != 'body_generation'})
        assert restored.status_code == 200 and restored.json()['paper']['download']['available'], restored.text
        # A historical completed record is not a new-download gate.
        retried = await client.post(f'/api/papers/{public.id}/body/download', json=dict(
            csrf_token=state['csrf_token'], workspace_id=str(public.workspace_id),
            qualification=restored.json()['paper']['download']['qualification']))
        assert retried.status_code == 200, retried.text
        with current.paper_gate():
            retry_task = current._reservations[public.id]
        assert (await asyncio.to_thread(retry_task.future.result, 8)).status == 'completed'
        assert retry_task.download_token.attempt == public_task.download_token.attempt + 1
        # Identity-only Trash has an actual legal nested current body, with zero
        # discovery/Session dependency. The fixture shell never opens a real app.
        from allfold.persistence.paper_repository import BodyReference
        retained = workspace/'Documents'/'retained'/'nested.pdf'
        retained.parent.mkdir(); retained.write_bytes(b'local identity-only body')
        with PaperRepository.open(workspace) as repo:
            identity_only = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(openalex='W778'),
                metadata=PaperMetadata(title='Local identity-only')).paper
            identity_only = repo.complete_body(identity_only.token, BodyReference(relative_path='Documents/retained/nested.pdf'))
            identity_only = repo.exclude(identity_only.token)
            identity_only = repo.clear_metadata(identity_only.token)
        identity_request = dict(csrf_token=state['csrf_token'], workspace_id=str(public.workspace_id), body_generation=identity_only.body_generation)
        identity_read = await client.post(f'/api/papers/{identity_only.id}/body/open', json=identity_request)
        assert identity_read.status_code == 200 and identity_read.json()['outcome'] == 'opened', identity_read.text
        retained.unlink()
        missing = await client.post(f'/api/papers/{identity_only.id}/body/locate', json=identity_request)
        assert missing.status_code == 200 and missing.json()['outcome'] == 'missing', missing.text
        assert missing.json()['paper']['body_present'] is False and missing.json()['paper']['metadata_present'] is False
        print(json.dumps({'type':'fixture_local','status':'settled','retry_attempt':retry_task.download_token.attempt}), flush=True)
        cases=[(path,origin+'/'+path,None) for path in ['redirect?Signature=A%2FB', 'encoded', 'chunked', 'html.pdf', 'unknown', 'truncated', 'cancel', 'expiry', 'cross', 'cross-private', 'cross-unsafe', 'bad-encoding', 'close-delimited', 'challenge', 'disk-write', 'disk-flush', 'slow-writer', 'cross-referer', 'completed-late-signals', 'octet', 'missing-mime', 'wrong-mime', 'split-prefix', 'fake-pdf', 'cookie-progress']]
        cases.extend([
            ('protected-cdn',secure_origin+'/protected.pdf?Signature=fixture',None),
            ('protected-cdn-warm',secure_origin+'/protected.pdf?Signature=renewed',None),
            ('protected-cdn-inline',secure_origin+'/protected.pdf?Signature=inline',None),
            ('unrelated-ready',origin+'/unrelated-ready',None),
            ('pending-challenge',origin+'/pending-challenge',None),
            ('cross-challenge',origin+'/cross-challenge',None),
            ('post-only-challenge',origin+'/post-only-challenge',None),
            ('long-public-url',origin+'/long?ticket='+'x'*9000+'%2FB',None),
            ('background-cloudflare',origin+'/background-cloudflare',None),
            ('oxford-cdn',origin.replace('pdf.example.org','academic.oup.com')+'/nar/article-pdf/51/2/870/123/body.pdf',None),
            ('oxford-private-dns',origin.replace('pdf.example.org','academic.oup.com')+'/nar/article-pdf/51/2/870/123/blocked.pdf',None),
            ('ieee-reader',origin.replace('pdf.example.org','ieeexplore.ieee.org')+'/stamp/stamp.jsp?arnumber=12345',
                origin.replace('pdf.example.org','ieeexplore.ieee.org')+'/document/12345')])
        for index, (path,url,article) in enumerate(cases):
            if path == 'cookie-progress':
                url += f'?doi=10.5555/body{index}'
            with PaperRepository.open(workspace) as repo:
                paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi=f'10.5555/body{index}'),
                    metadata=PaperMetadata(title='Same title')).paper
            target = PdfTarget(str(paper.id), doi=f'10.5555/body{index}', article_url=article, direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
            referer = secure_origin+'/article' if path.startswith('protected-cdn') else origin+'/article'
            if path=='cross-referer':
                referer=origin.replace('pdf.','other.')+'/article?InstitutionToken=synthetic'
            candidate = PdfCandidate(target, 'P1', 'GENERIC', 'generic', url, referer=referer)
            received, closing, waiting = threading.Event(), threading.Event(), threading.Event()
            def progress(value):
                if value.get('received_bytes',0)>0:received.set()
                if value.get('fixture_close_pending'):closing.set()
                if value.get('waiting_for_user'):waiting.set()
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
            if path=='pending-challenge':
                assert await asyncio.to_thread(waiting.wait,3)
                assert not task.future.done()
                host.current().cancel_paper(paper.id,paper.workspace_id)
            result = await asyncio.to_thread(task.future.result, 10)
            with PaperRepository.open(workspace) as repo:
                saved = repo.get(paper.id)
            if path.startswith('disk-'):assert result.status=='local_failure'
            if path in {'challenge', 'html.pdf'}:
                reason = 'access-blocked' if path == 'challenge' else 'access-login'
                assert result.status == 'failed' and result.candidate_result.kind == 'failed'
                assert result.candidate_result.diagnostic == reason
                assert saved.download.reason == reason
            if path=='background-cloudflare':assert not saved.download.reason.startswith('access-')
            if path=='pending-challenge':assert result.status=='cancelled'
            success = path.startswith('protected-cdn') or path in {'redirect?Signature=A%2FB','encoded','chunked','cross','close-delimited','slow-writer','cross-referer','completed-late-signals','oxford-cdn','ieee-reader','octet','missing-mime','wrong-mime','split-prefix','cookie-progress','cross-challenge','long-public-url'}
            assert (result.status == 'completed') == success, (path,result)
            assert (saved.body is not None) == success
            if success:
                if path in {'cross','cookie-progress'}:assert saved.body.pdf_source=='P1' and not saved.body.fallback_used
                assert (workspace / saved.body.relative_path).stat().st_size == saved.body.size_bytes
                assert 'Signature' not in saved.body.source_url
                again = await asyncio.to_thread(submit_body_download, host, saved, candidates=(candidate,))
                assert isinstance(again,BodyResult) and again.paper.body == saved.body
            assert not host.active
            if path == 'completed-late-signals':
                (root/'terminal-before-main-log').touch()
            projection = (await client.get('/api/ui-next/workspace')).json()
            encoded = json.dumps(projection)
            assert str(workspace) not in encoded and 'Signature' not in encoded and 'output_file' not in encoded
            assert saved.download.status == ('completed' if success else 'cancelled' if path in {'cancel','expiry','pending-challenge'} else 'failed'), (path, result, saved.download)
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

        # Same public operation, through an owned institution Browser record
        # and the selected Session, with an independent preprint available.
        saved = load_user_state(config)
        service = service.model_copy(update={'name': 'EBSCO',
            'access_url': 'https://research.ebsco.com/c/test-profile/search'})
        compare_write_user_state(config, replace(saved.state, access_services=(service,)), saved.revision)
        login.start(config, manual_service_id=service.id)
        await asyncio.to_thread(login.join)
        access = login.snapshot(BrowserServiceSnapshot.read(config))['services'][0]['preparation']
        assert access.status == 'Opened' and access.page_id, access
        doi = '10.5555/licensed'
        ebsco_facts = (
            PdfDiscoveryFacts(source='document', capability='document-pdf', status='complete',
                observed_at=datetime.now(timezone.utc), target_doi=doi, landing_url=origin+'/fixture-publisher',
                candidates=(PdfCandidateFact(stage='P4', rule_id='GENERIC', url=origin+'/fixture-publisher-pdf'),)),
            PdfDiscoveryFacts(source='openalex', capability='openalex-locations', status='complete',
                observed_at=datetime.now(timezone.utc), target_doi=doi,
                candidates=(PdfCandidateFact(stage='P5', rule_id='OPENALEX', url=origin+'/fixture-preprint'),)),
        )
        with PaperRepository.open(workspace) as repo:
            licensed = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi=doi),
                metadata=PaperMetadata(title='Licensed fixture', journal='Biometrics', publication_type='journal',
                    journal_issns=(A,), discovery_facts=ebsco_facts)).paper
        state = (await client.get('/api/ui-next/workspace')).json()
        licensed_projection = next(paper for group in state['subjects'] for journal in group['journals']
            for paper in journal['papers'] if paper['id'] == str(licensed.id))
        accepted = await client.post(f'/api/papers/{licensed.id}/body/download', json=dict(
            csrf_token=state['csrf_token'], workspace_id=str(licensed.workspace_id),
            qualification=licensed_projection['download']['qualification']))
        assert accepted.status_code == 200, accepted.text
        with current.paper_gate():
            licensed_task = current._reservations[licensed.id]
        assert (await asyncio.to_thread(licensed_task.future.result, 8)).status == 'completed'
        with PaperRepository.open(workspace) as repo:
            licensed = repo.get(licensed.id)
        assert licensed.body.pdf_source == 'P4' and licensed.download.status == 'completed', licensed.download
        assert licensed.body.source_url == 'https://content.ebscohost.com/'
        assert (workspace / licensed.body.relative_path).read_bytes() == b'%PDF-licensed-ebsco'
        print(json.dumps({'type':'fixture_ebsco','status':'completed','paper':str(licensed.id)}),flush=True)

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
