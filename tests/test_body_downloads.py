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
        self.calls.append((action,data));self.result=Future();self.started.set();return self.result
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
