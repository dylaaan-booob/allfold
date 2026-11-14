"""Pinned native incompatibility is finite and cannot gain file/network authority."""
from dataclasses import replace
import pytest
from allfold.pdf_rules import PdfCandidate, PdfTarget
from allfold.persistence.paper_repository import PaperRepository


def native_candidate():
    article='https://www.sciencedirect.com/science/article/pii/S0047259X2400006X'
    target=PdfTarget('paper-1',doi='10.5555/body',article_url=article)
    return PdfCandidate(target,'P2','R024','sciencedirect',article+'/pdfft',reader_kind='sciencedirect')


def test_unsupported_native_transport_does_not_touch_host_files_bridge_or_progress():
    from allfold.application.native_body_downloads import transfer_native
    class Forbidden:
        def __getattribute__(self,name):
            raise AssertionError('No native/file capability may be used: '+name)
        def __call__(self,*args):
            raise AssertionError('No progress is emitted without physical transfer')
    forbidden=Forbidden()
    result=transfer_native(forbidden,forbidden,forbidden,native_candidate(),forbidden)
    assert result.result.kind=='skipped' and result.result.diagnostic=='native-unsupported'
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


@pytest.mark.parametrize('signed',[False,True])
def test_native_unavailable_ends_without_creating_output_or_native_task(tmp_path,signed):
    from allfold.application.body_downloads import submit_body_download
    from test_body_downloads import application_host
    host,workspace,paper,bridge,original=application_host(tmp_path)
    candidate=replace(native_candidate(),target=replace(original.target,article_url=native_candidate().target.article_url))
    if signed:candidate=replace(candidate,url=candidate.url+'?md5=current')
    try:
        result=submit_body_download(host,paper,candidates=(candidate,)).future.result(2)
        assert result.status=='failed' and result.candidate_result.diagnostic=='native-unsupported'
        assert bridge.calls==[] and not (workspace/'Documents').exists() and not host.active
        with PaperRepository.open(workspace) as repo:
            saved=repo.get(paper.id)
            assert saved.download.status=='failed' and saved.download.reason=='native-unsupported'
            assert saved.body is None and saved.download.output is None
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()


@pytest.mark.parametrize('stream_result',['pdf','failed'])
def test_skipped_native_keeps_later_stream_and_accurate_terminal_provenance(tmp_path,stream_result):
    from allfold.application.body_downloads import submit_body_download
    from test_body_downloads import application_host
    host,workspace,paper,bridge,original=application_host(tmp_path)
    target=replace(original.target,article_url=native_candidate().target.article_url)
    native=replace(native_candidate(),target=target)
    stream=replace(original,target=target,stage='P5')
    try:
        task=submit_body_download(host,paper,candidates=(native,stream))
        assert bridge.started.wait(2)
        assert [action for action,_ in bridge.calls]==['stream_paper_body']
        assert bridge.calls[0][1]['url']==stream.url
        bridge.finish(stream_result)
        result=task.future.result(2)
        if stream_result=='pdf':
            assert result.status=='completed'
            assert result.paper.body.pdf_source=='P5' and result.paper.body.fallback_used is False
            assert (workspace/result.paper.body.relative_path).read_bytes()==b'body'
        else:
            assert result.status=='failed' and result.candidate_result.diagnostic=='native-unsupported'
            with PaperRepository.open(workspace) as repo:
                saved=repo.get(paper.id)
                assert saved.body is None and saved.download.reason=='native-unsupported'
    finally:
        if hasattr(bridge,'result') and not bridge.result.done():bridge.result.set_result(dict(kind='cancelled',outcome='cancelled'))
        host.shutdown();host.join()
