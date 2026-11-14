"""Managed body ownership and durable completion, using disposable real files/SQLite."""
from uuid import uuid4
import pytest
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata, BodyReference, StaleWriteError
from allfold.persistence.body_files import ManagedBodyFiles


def test_download_completion_keeps_manual_edits_and_never_replaces(tmp_path):
    with PaperRepository.create(tmp_path) as repo:
        paper = repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi='10.5555/body'),
            metadata=PaperMetadata(title='Saved')).paper
        token = repo.begin_download(paper.token, lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path, paper.id, token.attempt) as files:
            proof = files.prepare()
            repo.record_download_output(token, proof)
            # Native stream owns these synthetic bytes; no PDF content validation.
            (tmp_path / proof.temporary).write_bytes(b'synthetic body')
            repo.mark_download_running(token)
            edited = repo.edit_metadata(paper.token, {'abstract': 'My abstract', 'notes': 'My notes'})
            repo.require_download(token)
            size = files.publish(proof)
            saved = repo.complete_download(token, size_bytes=size, source_url='https://publisher.example/body')
            assert saved.metadata == edited.metadata
            assert saved.body.relative_path == f'Documents/{paper.id}.pdf'
            assert saved.download.status == 'completed'
            assert repo.complete_download(token, size_bytes=size) == saved
            assert repo.complete_body(saved.token, BodyReference(relative_path='Documents/replacement.pdf')) == saved
            files.cleanup(proof, associated=True)
            assert (tmp_path / saved.body.relative_path).read_bytes() == b'synthetic body'


def make_paper(repo, doi='10.5555/body'):
    return repo.create_or_match(repo.workspace_id, direct_ids=ExternalIds(doi=doi), metadata=PaperMetadata(title='Same title')).paper


@pytest.mark.parametrize('race', ['before', 'after'])
def test_target_conflict_never_overwrites_or_claims(tmp_path, race):
    with PaperRepository.create(tmp_path) as repo:
        paper = make_paper(repo)
        token = repo.begin_download(paper.token, lifecycle_id=uuid4())
        final = tmp_path / f'Documents/{paper.id}.pdf'
        if race == 'before':
            final.parent.mkdir(); final.write_bytes(b'unrelated')
        with ManagedBodyFiles(tmp_path, paper.id, token.attempt) as files:
            if race == 'before':
                with pytest.raises(FileExistsError): files.prepare()
            else:
                proof = files.prepare();repo.record_download_output(token, proof)
                (tmp_path / proof.temporary).write_bytes(b'new')
                final.write_bytes(b'unrelated')
                with pytest.raises(FileExistsError):files.publish(proof)
        assert final.read_bytes() == b'unrelated' and repo.get(paper.id).body is None


@pytest.mark.parametrize('changed', ['Documents', '.downloads', 'file'])
def test_replaced_output_objects_are_never_written_published_or_removed(tmp_path, changed):
    from allfold.persistence.library_database import UnsafeLibraryPath
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo); token=repo.begin_download(paper.token,lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path,paper.id,token.attempt) as files:
            proof=files.prepare()
            target=tmp_path / ('Documents' if changed=='Documents' else 'Documents/.downloads' if changed=='.downloads' else proof.temporary)
            moved=target.with_name(target.name+'.old'); target.rename(moved)
            if changed=='file':target.write_bytes(b'external')
            else:target.mkdir()
            with pytest.raises((UnsafeLibraryPath,FileNotFoundError)):files.publish(proof)
            with pytest.raises((UnsafeLibraryPath,FileNotFoundError)):files.cleanup(proof)
            if changed=='file':assert target.read_bytes()==b'external'
            assert repo.get(paper.id).body is None


@pytest.mark.parametrize('component', ['Documents', '.downloads'])
def test_output_parent_symlink_is_refused(tmp_path, component):
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo)
        outside=tmp_path/'outside';outside.mkdir()
        target=tmp_path/'Documents'
        if component=='.downloads':target.mkdir();target=target/'.downloads'
        target.symlink_to(outside, target_is_directory=True)
        with ManagedBodyFiles(tmp_path,paper.id,1) as files:
            with pytest.raises(OSError):files.prepare()
        assert list(outside.iterdir())==[]


@pytest.mark.parametrize('winner', ['reject', 'complete'])
def test_reject_final_transaction_order_and_restore_never_revives_old_token(tmp_path,winner):
    from allfold.application.body_downloads import complete_attempt
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo); token=repo.begin_download(paper.token,lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path,paper.id,token.attempt) as files:
            proof=files.prepare();repo.record_download_output(token,proof)
            (tmp_path/proof.temporary).write_bytes(b'body');files.publish(proof)
            if winner=='reject':
                excluded=repo.exclude(paper.token);restored=repo.restore(excluded.token)
                with pytest.raises(StaleWriteError):repo.complete_download(token,size_bytes=4)
                files.cleanup(proof)
                assert not (tmp_path/proof.target).exists() and repo.get(paper.id).body is None
            else:
                saved=repo.complete_download(token,size_bytes=4)
                excluded=repo.exclude(saved.token);restored=repo.restore(excluded.token)
                # Late terminal must preserve committed body, revision, Trash.
                assert repo.complete_download(token,size_bytes=4)==restored
                assert repo.finish_download(token,status='cancelled',reason='late')==restored
                assert (tmp_path/proof.target).read_bytes()==b'body'


def test_v3_forward_change_preserves_content_and_schema_failure_rolls_back(tmp_path, monkeypatch):
    import sqlite3
    import allfold.persistence.library_database as db
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo)
        body=repo.complete_body(paper.token,BodyReference(relative_path='Documents/existing.pdf'))
        saved=repo.exclude(body.token)
        revision=repo.revision
    with sqlite3.connect(tmp_path/'papers.sqlite') as conn:
        conn.execute('DROP TABLE paper_download');conn.execute('PRAGMA user_version=3')
    original=db.DOWNLOAD_SCHEMA
    with monkeypatch.context() as patch:
        patch.setattr(db,'DOWNLOAD_SCHEMA',original+('CREATE TABLE broken syntax',))
        with pytest.raises(db.LibraryError):PaperRepository.open(tmp_path)
    with sqlite3.connect(tmp_path/'papers.sqlite') as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0]==3
        assert conn.execute("SELECT name FROM sqlite_schema WHERE name='paper_download'").fetchone() is None
    with PaperRepository.open(tmp_path) as repo:
        assert repo.get(paper.id)==saved and repo.revision==revision
        assert repo._database.connection.execute('PRAGMA user_version').fetchone()[0]==4
        definitions=db._schema_definitions(repo._database.connection)
    fresh=tmp_path/'fresh';fresh.mkdir()
    with PaperRepository.create(fresh) as repo:
        assert db._schema_definitions(repo._database.connection)==definitions


@pytest.mark.parametrize('phase', ['temporary','published'])
def test_process_interruption_keeps_only_proven_outputs_without_replay(tmp_path,phase):
    import subprocess,sys
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo)
    script='''from pathlib import Path
import os,sys
from uuid import uuid4
from allfold.persistence.paper_repository import PaperRepository
from allfold.persistence.body_files import ManagedBodyFiles
workspace=Path(sys.argv[1])
with PaperRepository.open(workspace) as repo:
 paper=repo.list_papers()[0];token=repo.begin_download(paper.token,lifecycle_id=uuid4())
 with ManagedBodyFiles(workspace,paper.id,token.attempt) as files:
  proof=files.prepare();repo.record_download_output(token,proof)
  (workspace/proof.temporary).write_bytes(b'partial or closed')
  if sys.argv[2]=='published':files.publish(proof)
  os._exit(17)
'''
    assert subprocess.run([sys.executable,'-c',script,str(tmp_path),phase],check=False).returncode==17
    with PaperRepository.open(tmp_path) as repo:
        repo.interrupt_downloads(uuid4())
        saved=repo.get(paper.id)
        assert saved.download.status=='failed' and saved.download.reason=='interrupted' and saved.body is None
        with pytest.raises(Exception,match='cleaned'):repo.begin_download(saved.token,lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path,paper.id,saved.download.token.attempt) as files:files.cleanup(saved.download.output)
        repo.record_download_output(saved.download.token,None)
        new=repo.begin_download(saved.token,lifecycle_id=uuid4())
        assert new.attempt==2


class ControlledNative:
    """External native boundary, with real Futures and filesystem output."""
    connected = True
    def __init__(self):
        from threading import Event
        self.started=Event();self.calls=[];self.cancels=[]
    def execute(self,action,data,progress=None,**kwargs):
        from concurrent.futures import Future
        self.calls.append((action,data))
        if action=='release_workflow_pages':
            done=Future();done.set_result({});return done
        self.result=Future();self.started.set();return self.result
    def cancel_task(self,workflow,task):self.cancels.append((workflow,task))
    def finish(self,kind='pdf'):
        data=self.calls[-1][1]
        from pathlib import Path
        output=data['output']
        (Path(data['workspace_root'])/output['temporary']).write_bytes(b'body')
        self.result.set_result(dict(kind=kind,outcome='stream_complete' if kind=='pdf' else kind,
            pdf_type=kind=='pdf',transfer_complete=kind=='pdf',size_bytes=4,
            output_file=output['file'],final_url=data['url']))


def application_host(tmp_path):
    from safety_config_helpers import current_mapping_document
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.pdf_rules import PdfCandidate,PdfTarget
    config,*_=current_mapping_document(tmp_path)
    workspace=tmp_path/'workspace';workspace.mkdir()
    with PaperRepository.create(workspace) as repo:paper=make_paper(repo)
    bridge=ControlledNative();host=WorkspaceTaskHost(config,bridge=bridge)
    target=PdfTarget(str(paper.id),doi='10.5555/body',direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
    candidate=PdfCandidate(target,'P1','GENERIC','generic','https://publisher.example.org/body')
    return host,workspace,paper,bridge,candidate


def test_current_ieee_reader_response_finishes_the_same_body_attempt(tmp_path):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    article='https://ieeexplore.ieee.org/document/12345'
    reader='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'
    pdf='https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?arnumber=12345'
    candidate=replace(candidate,target=replace(candidate.target,article_url=article),
        url=reader,platform='ieee',rule_id='R025')
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=reader,content_type='text/html',status=200,
            body='<html><iframe src="'+pdf+'"></iframe></html>',access=None)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:
            time.sleep(.005)
        assert len(bridge.calls)==2, 'A qualified current reader must continue to its PDF'
        assert bridge.calls[-1][1]['url']==pdf
        assert bridge.calls[-1][1]['attempt']==task.download_token.attempt
        bridge.finish()
        result=task.future.result(2)
        assert result.status=='completed'
        assert (workspace/result.paper.body.relative_path).read_bytes()==b'body'
        assert result.paper.collection_status=='not_started'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():
            bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('url,location,source',[
    ('https://academic.oup.com/nar/article-pdf/51/2/870/48929720/gkac1225.pdf',
        'https://watermark02.silverchair.com/gkac1225.pdf?token=transient','https://watermark02.silverchair.com/'),
    ('https://www.sciencedirect.com/science/article/pii/S0047259X2400006X/pdfft?md5=transient',
        'https://pdf.sciencedirectassets.com/272481/1-s2.0-S0047259X2400006X/main.pdf?token=transient','https://pdf.sciencedirectassets.com/'),
])
def test_observed_publisher_cdn_redirect_is_requalified_before_the_next_get(tmp_path,url,location,source):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    candidate=replace(candidate,url=url)
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='redirect',outcome='response',response=dict(
            url=url,status=302,location=location)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:
            time.sleep(.005)
        assert len(bridge.calls)==2, 'The observed Oxford CDN needs a newly checked request'
        assert bridge.calls[-1][1]['url']==location
        bridge.finish()
        result=task.future.result(2)
        assert result.status=='completed'
        assert result.paper.body.source_url==source
        assert 'transient' not in str(result.paper.body)
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():
            bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('tracking',['','?ref=pdf_download&fr=RR-2'])
def test_sciencedirect_article_return_refreshes_current_signed_pdf_from_document(tmp_path,tracking):
    from dataclasses import replace
    import time
    from test_document_metadata import envelope,pdf_clues
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    article='https://www.sciencedirect.com/science/article/pii/S0047259X2400006X'
    candidate=replace(candidate,target=replace(candidate.target,article_url=article),url=article)
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=article+tracking,content_type='text/html',status=200,body='<title>ScienceDirect article</title>',access=None)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2 and bridge.calls[-1][0]=='extract_paper_pdf_clues'
        assert 'reader' not in bridge.calls[-1][1]
        assert bridge.calls[-1][1]['identity']['confirmed_article_url']==article
        pdf='https://pdf.sciencedirectassets.com/1-s2.0-S0047259X2400006X/main.pdf?token=transient'
        bridge.result.set_result(envelope() | {'pdf_clues':pdf_clues(platform='sciencedirect',landing_url=article,
            candidates=[dict(stage='P1',rule_id='R024',url=pdf)])})
        until=time.monotonic()+2
        while (bridge.calls[-1][0]!='stream_paper_body' or len(bridge.calls)<3) and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert bridge.calls[-1][0]=='stream_paper_body' and bridge.calls[-1][1]['url']==pdf
        bridge.finish()
        assert task.future.result(2).status=='completed'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


def test_known_challenge_reader_uses_managed_document_access_before_its_pdf(tmp_path):
    from dataclasses import replace
    import time
    from test_document_metadata import envelope,pdf_clues
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    article='https://www.sciencedirect.com/science/article/pii/S0047259X2400006X'
    reader=article+'/pdfft?md5=current'
    candidate=replace(candidate,target=replace(candidate.target,article_url=article),
        url=reader,platform='sciencedirect',rule_id='R024')
    def wait_for(action,after):
        until=time.monotonic()+2
        while (len(bridge.calls)<=after or bridge.calls[-1][0]!=action) and not task.future.done() and time.monotonic()<until:
            time.sleep(.005)
        assert len(bridge.calls)>after and bridge.calls[-1][0]==action
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=reader,content_type='text/html',status=200,
            body='<html><title>Just a moment...</title></html>',access='challenge')))
        wait_for('extract_paper_pdf_clues',1)
        assert bridge.calls[-1][1]['reader']['identifier']=='S0047259X2400006X'
        pdf='https://pdf.sciencedirectassets.com/body.pdf?token=transient'
        bridge.result.set_result(envelope() | {'pdf_clues':pdf_clues(platform='sciencedirect',landing_url=reader,
            candidates=[dict(stage='P1',rule_id='R024',url=pdf)])})
        wait_for('stream_paper_body',2)
        assert bridge.calls[-1][1]['url']==pdf
        bridge.finish()
        result=task.future.result(2)
        assert result.status=='completed' and result.paper.collection_status=='not_started'
        assert result.paper.metadata==paper.metadata
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():
            bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('signed',[True,False])
def test_unsigned_sciencedirect_reader_qualifies_current_link_before_any_stream(tmp_path,signed):
    from dataclasses import replace
    import time
    from test_document_metadata import envelope,pdf_clues
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    article='https://www.sciencedirect.com/science/article/pii/S0047259X2400006X'
    candidate=replace(candidate,target=replace(candidate.target,article_url=article),url=article+'/pdfft')
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        assert bridge.calls[-1][0]=='extract_paper_pdf_clues'
        assert not list((workspace/'Documents/.downloads').glob('*.part'))
        pdf=article+'/pdfft'+('?md5=current' if signed else '')
        bridge.result.set_result(envelope() | {'pdf_clues':pdf_clues(platform='sciencedirect',landing_url=article,
            candidates=[dict(stage='P4',rule_id='R024',url=pdf,referer=article)])})
        until=time.monotonic()+2
        while bridge.calls[-1][0]!='stream_paper_body' and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert bridge.calls[-1][0]=='stream_paper_body' and bridge.calls[-1][1]['url']==pdf
        bridge.finish()
        assert task.future.result(2).status=='completed'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('location',[
    'https://watermark02.silverchair.com/other.pdf',
    'https://watermark02.silverchair.com.evil.example/gkac1225.pdf',
    'https://other.example.org/gkac1225.pdf',
    'http://watermark02.silverchair.com/gkac1225.pdf',
])
def test_unqualified_body_redirect_never_starts_another_request(tmp_path,location):
    from dataclasses import replace
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    url='https://academic.oup.com/nar/article-pdf/51/2/870/48929720/gkac1225.pdf'
    try:
        task=submit_body_download(host,paper,candidates=(replace(candidate,url=url),))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='redirect',outcome='response',response=dict(
            url=url,status=302,location=location)))
        result=task.future.result(2)
        assert result.status=='failed' and len(bridge.calls)==1
        with PaperRepository.open(workspace) as repo:
            assert repo.get(paper.id).body is None and repo.get(paper.id).download.output is None
    finally:
        host.shutdown();host.join()


def test_current_reader_cycle_settles_without_repeating_the_request(tmp_path):
    from dataclasses import replace
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    url='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'
    try:
        task=submit_body_download(host,paper,candidates=(replace(candidate,url=url),))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=url,content_type='text/html',status=200,
            body='<iframe src="'+url+'"></iframe>',access=None)))
        result=task.future.result(2)
        assert result.status!='completed' and len(bridge.calls)==1
        assert not host.active
    finally:
        host.shutdown();host.join()


@pytest.mark.parametrize('access',[None,'challenge'])
def test_reader_alternatives_continue_only_after_an_ordinary_empty_response(tmp_path,access):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    reader='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'
    empty='https://cdn.example.org/empty.pdf';good='https://cdn.example.org/good.pdf'
    try:
        task=submit_body_download(host,paper,candidates=(replace(candidate,url=reader),))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=reader,content_type='text/html',status=200,
            body='<iframe src="'+empty+'"></iframe><iframe src="'+good+'"></iframe>',access=None)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=empty,content_type='text/html',status=200,body='<html>No PDF here</html>',access=access)))
        until=time.monotonic()+2
        while len(bridge.calls)<3 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        if access is None:
            assert len(bridge.calls)==3 and bridge.calls[-1][1]['url']==good
            bridge.finish()
            assert task.future.result(2).status=='completed'
        else:
            assert task.future.result(2).status=='response' and len(bridge.calls)==2
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('reason',['cancelled','expired'])
def test_known_reader_cancellation_retains_its_terminal_after_native_cleanup(tmp_path,reason):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    reader='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'
    try:
        task=submit_body_download(host,paper,candidates=(replace(candidate,url=reader),),deadline=time.monotonic()+.5)
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=reader,content_type='text/html',status=200,
            body='<title>Just a moment...</title>',access='challenge')))
        until=time.monotonic()+.3
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2 and bridge.calls[-1][0]=='extract_paper_pdf_clues'
        if reason=='cancelled':task.registry.cancel_paper(paper.id)
        else:assert task.cancel_event.wait(1)
        bridge.result.set_result(dict(diagnostic=dict(code='canceled' if reason=='cancelled' else 'timeout',stage='navigation')))
        result=task.future.result(2)
        assert result.status==reason
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            assert saved.download.status=='cancelled' and saved.download.reason==reason
            assert saved.body is None and saved.download.output is None
        assert not host.active and bridge.calls[-1][0]=='release_workflow_pages'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('code',['content_access_blocked','site_restricted','article_identity_unconfirmed','article_identity_conflict'])
def test_native_document_access_barrier_stops_queued_body_alternatives(tmp_path,code):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    reader='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'
    try:
        task=submit_body_download(host,paper,candidates=(replace(candidate,url=reader),candidate))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=reader,content_type='text/html',status=200,body='<html>Reader</html>',access=None)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2
        bridge.result.set_result(dict(diagnostic=dict(code=code,stage='navigation')))
        until=time.monotonic()+2
        while not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert task.future.done(), 'Document access denial must not start the queued source'
        assert task.future.result().status=='failed'
        assert [a for a,_ in bridge.calls]==['stream_paper_body','extract_paper_pdf_clues','release_workflow_pages']
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('status,body',[
    (418,'<title>Unusual Traffic Detected (Error 418)</title>'),
    (200,'<p>CPE00001</p><p>There was a problem providing the content you requested</p>'),
    (200,'<iframe src="/_Incapsula_Resource?edet=15&incident_id=123-456">Request unsuccessful. Incapsula incident ID: 123-456</iframe>'),
])
def test_http_access_barriers_stop_queued_body_alternatives(tmp_path,status,body):
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    from dataclasses import replace
    try:
        task=submit_body_download(host,paper,candidates=(candidate,replace(candidate,url=candidate.url+'?next=1')))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=candidate.url,content_type='text/html',status=status,body=body,access=None)))
        assert task.future.result(2).status!='completed'
        assert len(bridge.calls)==1
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('body',[
    '<div hidden>CPE00001 There was a problem providing the content you requested</div><p>Article</p>',
    '<div aria-hidden="true">CPE00001 There was a problem providing the content you requested</div><p>Article</p>',
    '<div style="display:none">CPE00001 There was a problem providing the content you requested</div><p>Article</p>',
    '<script>const error="CPE00001";</script>'+'<p>Article</p>'*4100,
    '<p>Article</p>'*4100+'<iframe src="/_Incapsula_Resource?edet=15">Request unsuccessful. Incapsula incident ID: 123-456</iframe>',
],ids=['hidden','aria-hidden','style-hidden','large-script','large-side-frame'])
def test_unconfirmed_access_hints_do_not_drop_qualified_alternatives(tmp_path,body):
    from dataclasses import replace
    import time
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    try:
        task=submit_body_download(host,paper,candidates=(candidate,replace(candidate,url=candidate.url+'?next=1')))
        assert bridge.started.wait(2)
        bridge.result.set_result(dict(kind='response',outcome='response',response=dict(
            url=candidate.url,content_type='text/html',status=200,body=body,access=None)))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2
        bridge.finish()
        assert task.future.result(2).status=='completed'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


def test_closed_unlink_fault_releases_budget_and_blocks_retry_network_until_clean(tmp_path,monkeypatch):
    from allfold.application.body_downloads import submit_body_download
    import allfold.persistence.body_files as bf
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    try:
        task=submit_body_download(host,paper,candidates=(candidate,candidate))
        assert bridge.started.wait(2)
        real=bf.os.unlink
        def denied(*args,**kwargs):raise PermissionError('controlled unlink refusal')
        with monkeypatch.context() as patch:
            patch.setattr(bf.os,'unlink',denied)
            bridge.finish('failed')
            assert task.future.result(3).status=='local_failure'
            assert not host.active and not host.current().faults
            with PaperRepository.open(workspace) as repo:
                saved=repo.get(paper.id)
                assert saved.download.output is not None and saved.download.status=='failed'
            with pytest.raises(PermissionError):submit_body_download(host,saved,candidates=(candidate,))
            assert len(bridge.calls)==1
        replacement=submit_body_download(host,saved,candidates=(candidate,))
        assert replacement.download_token.attempt==2
        # Old cancellation is scoped to its original owner.
        host.current().signal_cancel_targets((task,))
        assert not replacement.cancel_event.is_set()
        while len(bridge.calls)<2:__import__('time').sleep(.001)
        bridge.finish()
        assert replacement.future.result(3).status=='completed'
    finally:
        host.shutdown();host.join()


def test_final_database_failure_cleans_output_without_fallback_or_success(tmp_path,monkeypatch):
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    try:
        task=submit_body_download(host,paper,candidates=(candidate,candidate))
        assert bridge.started.wait(2)
        with monkeypatch.context() as patch:
            patch.setattr(PaperRepository,'complete_download',lambda *a,**k: (_ for _ in ()).throw(OSError('controlled commit failure')))
            bridge.finish()
            assert task.future.result(3).status=='local_failure'
        assert len(bridge.calls)==1 and not host.active
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            assert saved.body is None and saved.download.status=='failed' and saved.download.output is None
        assert list((workspace/'Documents').glob('*.pdf'))==[]
    finally:host.shutdown();host.join()


@pytest.mark.parametrize('kind',['legacy','download'])
def test_mutually_exclusive_reservations_and_submission_failure_settle_attempt(tmp_path,kind,monkeypatch):
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    try:
        registry=host.current();other=registry.reserve(paper.id,kind=kind)
        with pytest.raises(Exception,match='owns'):submit_body_download(host,paper,candidates=(candidate,))
        registry.release(other)
        with monkeypatch.context() as patch:
            patch.setattr(registry._scheduler,'submit',lambda *a,**k: (_ for _ in ()).throw(RuntimeError('controlled submit failure')))
            with pytest.raises(RuntimeError):submit_body_download(host,paper,candidates=(candidate,))
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            assert saved.download.status=='cancelled' and saved.download.reason=='submission-failed'
        assert bridge.calls==[] and not host.active
    finally:host.shutdown();host.join()


def test_existing_body_requires_no_new_access_capture_or_native_connection(tmp_path):
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    try:
        with PaperRepository.open(workspace) as repo:
            saved=repo.complete_body(paper.token,BodyReference(relative_path='Documents/fixture.pdf'))
        bridge.connected=False
        result=submit_body_download(host,saved,candidates=(candidate,),service_id='no-longer-present')
        assert result.status=='completed' and result.paper.body==saved.body and bridge.calls==[]
    finally:host.shutdown();host.join()


def test_cleanup_quarantines_and_restores_replacement_between_check_and_removal(tmp_path,monkeypatch):
    import allfold.persistence.body_files as bf
    with PaperRepository.create(tmp_path) as repo:
        paper=make_paper(repo);token=repo.begin_download(paper.token,lifecycle_id=uuid4())
        with ManagedBodyFiles(tmp_path,paper.id,token.attempt) as files:
            proof=files.prepare();repo.record_download_output(token,proof)
            temporary=tmp_path/proof.temporary;temporary.write_bytes(b'owned')
            moved=temporary.with_suffix('.old');original=bf._move_exclusive;swapped=False
            def race(source,destination,source_directory,destination_directory):
                nonlocal swapped
                if not swapped:
                    swapped=True;temporary.rename(moved);temporary.write_bytes(b'unrelated')
                return original(source,destination,source_directory,destination_directory)
            with monkeypatch.context() as patch:
                patch.setattr(bf,'_move_exclusive',race)
                with pytest.raises(bf.UnsafeLibraryPath):files.cleanup(proof)
            assert moved.read_bytes()==b'owned' and temporary.read_bytes()==b'unrelated'


def test_final_inode_replacement_cannot_be_completed_or_removed(tmp_path,monkeypatch):
    from allfold.application.body_downloads import submit_body_download
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    original=ManagedBodyFiles.publish
    try:
        task=submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.started.wait(2)
        def replaced(files,proof):
            size=original(files,proof)
            path=workspace/proof.target
            path.rename(path.with_suffix('.owned'))
            path.write_bytes(b'unrelated replacement')
            return size
        with monkeypatch.context() as patch:
            patch.setattr(ManagedBodyFiles,'publish',replaced)
            bridge.finish()
            assert task.future.result(3).status=='local_failure'
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            assert saved.body is None and saved.download.status=='failed'
        assert (workspace/f'Documents/{paper.id}.pdf').read_bytes()==b'unrelated replacement'
        assert not host.active
    finally:host.shutdown();host.join()


def test_admission_binds_candidates_before_concurrent_registration(tmp_path,monkeypatch):
    from allfold.application.body_downloads import submit_body_download
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier,Event
    from dataclasses import replace
    host,workspace,paper,bridge,candidate=application_host(tmp_path)
    registry=host.current();original=registry.reserve
    both,created,reused=Barrier(2),Event(),Event()
    second=replace(candidate,url='https://publisher.example.org/SECOND')
    def reserve(*args,**kwargs):
        both.wait(3)
        if kwargs['body_request'].candidates[0]==candidate:
            task=original(*args,**kwargs);created.set();assert reused.wait(3);return task
        assert created.wait(3)
        task=original(*args,**kwargs);reused.set();return task
    try:
        with monkeypatch.context() as patch,ThreadPoolExecutor(2) as pool:
            patch.setattr(registry,'reserve',reserve)
            first=pool.submit(submit_body_download,host,paper,candidates=(candidate,))
            other=pool.submit(submit_body_download,host,paper,candidates=(second,))
            task=first.result(3);assert other.result(3) is task
        assert bridge.started.wait(2)
        assert bridge.calls[0][1]['url']==candidate.url
        bridge.finish()
        assert task.future.result(3).status=='completed'
    finally:host.shutdown();host.join()


def test_old_candidate_cannot_borrow_a_primary_identity_changed_by_new_run(tmp_path):
    from allfold.application.body_downloads import submit_body_download
    from dataclasses import replace
    from allfold.pdf_rules import PdfTarget
    host,workspace,_,bridge,_=application_host(tmp_path)
    try:
        with PaperRepository.open(workspace) as repo:
            paper=make_paper(repo,'10.5555/unused')
            paper=repo.create_or_match(repo.workspace_id,direct_ids=ExternalIds(pmid='456'),metadata=PaperMetadata(title='PubMed')).paper
        target=PdfTarget(str(paper.id),direct_identities=tuple((i.namespace,i.value) for i in paper.identities))
        from allfold.pdf_rules import PdfCandidate
        candidate=PdfCandidate(target,'P1','GENERIC','generic','https://publisher.example.org/old-target')
        from allfold.application.collection_runtime import BranchSpec
        task=host.current().submit(direct_ids=ExternalIds(pmid='456',doi='10.5555/new-primary'),
            metadata=paper.metadata,branches=(),no_applicable=True)
        current=task.future.result(3)
        assert current.primary_identity!=paper.primary_identity and current.token==paper.token
        with pytest.raises(StaleWriteError,match='primary'):
            submit_body_download(host,paper,candidates=(candidate,))
        assert bridge.calls==[]
    finally:host.shutdown();host.join()
