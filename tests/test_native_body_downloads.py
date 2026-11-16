"""Original-response bridge boundary retains one attempt and observed output proof."""
from dataclasses import replace
import pytest
from allfold.pdf_rules import PdfCandidate, PdfTarget
from allfold.persistence.paper_repository import PaperRepository


def native_candidate():
    article='https://www.sciencedirect.com/science/article/pii/S0047259X2400006X'
    target=PdfTarget('paper-1',doi='10.5555/body',article_url=article)
    return PdfCandidate(target,'P4','R024','sciencedirect',article+'/pdfft',reader_kind='sciencedirect')


def test_inapplicable_native_transport_does_not_touch_host_files_bridge_or_progress():
    from allfold.application.native_body_downloads import transfer_native
    class Forbidden:
        def __getattribute__(self,name):
            raise AssertionError('Inapplicable native transport used capability: '+name)
        def __call__(self,*args):
            raise AssertionError('No progress exists without physical transfer')
    forbidden=Forbidden()
    result=transfer_native(forbidden,forbidden,forbidden,replace(native_candidate(),rule_id='GENERIC'),forbidden)
    assert result.result.kind=='failed' and result.result.diagnostic=='native-inapplicable'
    assert result.output is None and result.final_url==''


def test_fixed_native_classification_preserves_reusable_stream_and_credential_scopes():
    from allfold.application.native_body_downloads import native_applicable
    candidate=native_candidate()
    assert native_applicable(candidate)
    assert native_applicable(replace(candidate,platform='microbiology',rule_id='R059',action='refresh_form',
        url='https://www.microbiologyresearch.org/once'))
    assert not native_applicable(replace(candidate,platform='generic',rule_id='GENERIC'))
    assert not native_applicable(replace(candidate,credential='elsevier'))
    assert not native_applicable(replace(candidate,platform='ieee',rule_id='R025',reader_kind='ieee',
        url='https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=12345'))
    assert not native_applicable(replace(candidate,action='arbitrary-script'))


def test_later_native_candidate_never_reuses_cancelled_items_private_path(tmp_path):
    import time
    from allfold.application.body_downloads import submit_body_download
    from test_body_downloads import application_host
    host,workspace,paper,bridge,original=application_host(tmp_path)
    candidate=replace(native_candidate(),target=replace(original.target,article_url=native_candidate().target.article_url))
    callbacks=[]
    execute=bridge.execute
    def capture(action,data,callback=None,**options):
        callbacks.append(callback)
        return execute(action,data,callback,**options)
    bridge.execute=capture
    try:
        task=submit_body_download(host,paper,candidates=(candidate,replace(candidate,url=candidate.url.removesuffix('/pdfft')+'/pdf')))
        assert bridge.started.wait(2)
        first=workspace/bridge.calls[0][1]['output']['temporary'];first.write_bytes(b'%PDF-first')
        info=first.stat();callbacks[0](dict(native_output_file=[info.st_dev,info.st_ino]))
        bridge.result.set_result(dict(kind='failed',outcome='failed',diagnostic_code='native-action'))
        until=time.monotonic()+2
        while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
        assert len(bridge.calls)==2
        data=bridge.calls[1][1];second=workspace/data['output']['temporary']
        assert first!=second
        second.write_bytes(b'%PDF-second');info=second.stat()
        callbacks[1](dict(native_output_file=[info.st_dev,info.st_ino]))
        first.unlink(missing_ok=True)  # Chromium's late cleanup must address only the old pathname.
        bridge.result.set_result(dict(kind='pdf',outcome='native_complete',pdf_type=True,transfer_complete=True,
            output_file=[info.st_dev,info.st_ino],final_url=data['candidate']['url']))
        result=task.future.result(2)
        assert result.status=='completed' and result.paper.body.fallback_used
        assert (workspace/result.paper.body.relative_path).read_bytes()==b'%PDF-second'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('signed',[False,True])
def test_native_attempt_uses_original_bridge_capability_then_shared_completion(tmp_path,signed):
    from allfold.application.body_downloads import submit_body_download
    from test_body_downloads import application_host
    host,workspace,paper,bridge,original=application_host(tmp_path)
    candidate=replace(native_candidate(),target=replace(original.target,article_url=native_candidate().target.article_url))
    if signed:candidate=replace(candidate,url=candidate.url+'?md5=current')
    progress=[]
    execute=bridge.execute
    def capture(action,data,callback=None,**kwargs):
        bridge.native_progress=callback
        return execute(action,data,callback,**kwargs)
    bridge.execute=capture
    try:
        task=submit_body_download(host,paper,candidates=(candidate,),progress=progress.append)
        assert bridge.started.wait(2)
        action,data=bridge.calls[0]
        assert action=='native_paper_body' and len(bridge.calls)==1
        assert data['candidate']['url']==candidate.url and data['identity']['confirmed_article_url']==candidate.target.article_url
        leaf=workspace/data['output']['temporary']
        assert data['output']['file'] is None and not leaf.exists()
        leaf.write_bytes(b'original response')
        info=leaf.stat();file=[info.st_dev,info.st_ino]
        if signed:
            bridge.native_progress(dict(native_output_file=file,received_bytes=17,total_bytes=17))
        assert 'native_output_file' not in str(progress)
        bridge.result.set_result(dict(kind='pdf',outcome='native_complete',pdf_type=True,transfer_complete=True,
            output_file=file,final_url=candidate.url,resource_closed=True))
        result=task.future.result(2)
        assert result.status=='completed' and result.paper.body.pdf_source=='P4'
        assert result.paper.body.fallback_used is False
        assert (workspace/result.paper.body.relative_path).read_bytes()==b'original response'
        assert not leaf.parent.exists() and not host.active
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('kind,diagnostic,expected',[
    ('local_failure','interrupted','local_failure'),('failed','access-blocked','completed')])
def test_native_source_refusal_continues_but_writer_failure_stops(tmp_path,kind,diagnostic,expected):
    from allfold.application.body_downloads import submit_body_download
    from test_body_downloads import application_host
    host,workspace,paper,bridge,original=application_host(tmp_path)
    candidate=replace(native_candidate(),target=replace(original.target,article_url=native_candidate().target.article_url))
    try:
        task=submit_body_download(host,paper,candidates=(candidate,replace(original,target=candidate.target)))
        assert bridge.started.wait(2)
        assert bridge.calls[0][0]=='native_paper_body'
        bridge.result.set_result(dict(kind=kind,outcome=kind,diagnostic_code=diagnostic,
            native_terminal='cancelled',native_cleanup='asynchronous'))
        if kind=='failed':
            import time
            until=time.monotonic()+2
            while len(bridge.calls)<2 and not task.future.done() and time.monotonic()<until:time.sleep(.005)
            assert len(bridge.calls)==2 and bridge.calls[-1][0]=='stream_paper_body'
            bridge.finish()
        result=task.future.result(2)
        assert result.status==expected and len(bridge.calls)==(2 if kind=='failed' else 1) and not host.active
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            if kind=='failed':
                assert saved.body is not None and saved.body.fallback_used
            else:
                assert saved.body is None and saved.download.reason==diagnostic
            assert saved.download.output is None
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()
