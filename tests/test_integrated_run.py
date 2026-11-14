from datetime import datetime, timezone
from dataclasses import replace

import pytest

from allfold.config import load_config, JournalConfig, render_settings_list_text
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult
from integrated_run_helpers import EmptyLookup, run_integrated
from library_helpers import read_papers, read_paper


def config(tmp_path, enabled=('pubmed','openalex')):
    path=tmp_path/'monitor.yaml'
    path.write_text('keyword_expression: learning\noutput_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-03\n')
    scope=tmp_path/'list.md'
    scope.write_text(render_settings_list_text(None,(JournalConfig(name='Test',issn='0006-341X'),),path=scope,groups=(),custom_labels=(),access_services=()))
    return path,replace(load_config(path),enabled_providers=enabled)


def evidence(provider='pubmed', doi='10.5555/formal', pmid='42', title='Native hit'):
    return ProviderWorkEvidence(title=title,journal='Test',publication_type='journal',
        external_ids=ExternalIds(doi=doi,pmid=pmid),
        provenance=MetadataSource(provider=provider,record_id=pmid or doi,retrieved_at=datetime.now(timezone.utc)))


def client_for(records, *, failed=None, calls=None):
    class Client(EmptyLookup):
        def discover_many(self,scopes,*args,records_callback=None):
            if calls is not None: calls.append(self.provider)
            if self.provider==failed: raise OSError('Isolated discovery failure')
            rows=records() if callable(records) else records
            if records_callback: records_callback(rows)
            return tuple(DiscoveryResult(self.provider,source,'complete' if rows else 'empty',rows,candidates=len(rows),total=len(rows)) for source in scopes)
    return Client


def test_run_preserves_paper_without_persisting_rediscovery(tmp_path):
    from allfold.application.workspace import load_workspace
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    rows=(evidence(),)
    factory=client_for(lambda:rows)
    assert run_integrated(path,client_factory=factory).facts.created_papers==1
    from allfold.persistence.paper_repository import PaperRepository
    saved, = read_papers(tmp_path/'workspace')
    with PaperRepository.open(tmp_path/'workspace') as repository:
        original = repository.exclude(saved.token)
    retired=tmp_path/'workspace'/'Evidence';retired.write_text('Unmanaged legacy content')
    rows=(evidence(title='Rediscovery title'),)
    result=run_integrated(path,client_factory=factory)
    assert result.facts.existing_papers==0 and result.facts.statistics['identity_targets']==0
    assert read_paper(tmp_path/'workspace', saved.id) == original
    assert retired.read_text() == 'Unmanaged legacy content'


def test_only_selected_discovery_providers_run_and_one_failure_preserves_hits(tmp_path):
    from allfold.application.integrated_run import discover_selected
    path,settings=config(tmp_path)
    calls=[]
    result=discover_selected(settings,path,client_factory=client_for((evidence(),),failed='openalex',calls=calls))
    assert sorted(calls)==['openalex','pubmed']
    assert result.status=='partial' and len(result.records)==1
    assert {r.status for r in result.providers}=={'complete','failed'}


def test_production_integrated_run_creates_doi_free_native_hit_and_preserves_saved_bytes(tmp_path):
    import httpx
    from allfold.providers.integrated import DiscoveryClient
    from allfold.application.run_summary import build_run_result_summary
    from allfold.application.run_state import read_last_run_snapshot,RunProvider
    from test_pubmed_discovery import article
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200,json={'esearchresult':{'count':'1','idlist':['42'],'webenv':'fixture','querykey':'1'}})
        assert request.url.path.endswith('efetch.fcgi')
        return httpx.Response(200,text='<PubmedArticleSet>'+article('42','0006-341X')+'</PubmedArticleSet>')
    factory=lambda provider,**kwargs:DiscoveryClient(provider,transport=httpx.MockTransport(handler),interval=0,**kwargs)
    first=run_integrated(path,client_factory=factory)
    assert first.facts.created_papers==1 and first.facts.existing_papers==0
    assert build_run_result_summary(first)['coverage_status']=='complete'
    saved, = read_papers(tmp_path/'workspace'); original=saved
    calls.clear();second=run_integrated(path,client_factory=factory)
    assert second.facts.existing_papers==1 and read_paper(tmp_path/'workspace', saved.id)==original and len(calls)==2
    latest=read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED)
    assert latest.snapshot.schema_version==6
    assert build_run_result_summary(latest)==build_run_result_summary(second)


@pytest.mark.parametrize('failed_provider',['openalex','pubmed'])
def test_discovery_exceptions_share_category_but_retain_provider_and_source(tmp_path,failed_provider):
    from allfold.application.run_summary import build_run_result_summary
    from allfold.application.monitor import MonitorIssueComponent
    path,_=config(tmp_path)
    result=run_integrated(path,client_factory=client_for((evidence(),),failed=failed_provider))
    issue,=result.errors
    assert issue.component is MonitorIssueComponent.DISCOVERY
    assert failed_provider in issue.message and 'Test' in issue.message
    summary=build_run_result_summary(result)
    assert summary['status']=='incomplete' and summary['coverage_status']=='partial' and summary['created_papers']==1
    assert summary['issues'][0]['category']=='discovery'


def test_constructor_failure_isolated_and_all_failed_is_never_complete(tmp_path):
    from allfold.application.run_summary import build_run_result_summary
    path,_=config(tmp_path)
    class Client(client_for(())):
        def __init__(self,provider,**kwargs):
            if provider=='openalex': raise ValueError('Credential configuration unavailable')
            super().__init__(provider,**kwargs)
    result=run_integrated(path,client_factory=Client)
    assert result.facts.details['discovery_status']=='partial'
    path.write_text(path.read_text()+'enabled_providers: [openalex]\n')
    failed=run_integrated(path,client_factory=Client)
    assert build_run_result_summary(failed)['status']=='failed'


def test_repeated_run_creates_separate_doi_with_only_a_version_relation(tmp_path):
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    formal=evidence().model_copy(update={'related_dois':('10.5555/preprint',)})
    rows=(formal,);factory=client_for(lambda:rows)
    assert run_integrated(path,client_factory=factory).facts.created_papers==1
    saved, = read_papers(tmp_path/'workspace'); before=saved
    rows=(formal,evidence(doi='10.5555/preprint',pmid='43'))
    result=run_integrated(path,client_factory=factory)
    assert result.facts.created_papers==1 and result.facts.existing_papers==1 and read_paper(tmp_path/'workspace', saved.id)==before


def test_provider_response_after_cancel_never_materializes(tmp_path):
    from threading import Event
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    cancel=Event()
    def rows(): cancel.set();return (evidence(),)
    result=run_integrated(path,client_factory=client_for(rows),cancel_event=cancel)
    assert result.outcome.value=='CANCELLED' and not read_papers(tmp_path/'workspace')


def test_saved_provider_selection_reaches_request_coordinator_and_retired_entries_reject(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from allfold.application.monitor import RunResult,RunOutcome
    from allfold.application.run_state import RunProvider,RunFacts
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    observed=[]
    def monitor(config_path,**kwargs):
        observed.append((config_path,kwargs))
        return RunResult(RunProvider.INTEGRATED,None,(),(),RunOutcome.COMPLETED,facts=RunFacts(created_papers=0,existing_papers=0,details={'discovery_status':'empty'}))
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor',monitor)
    app=create_app(path,electron_bridge=OfflineBridge())
    with TestClient(app,base_url='http://localhost') as client:
        csrf=client.get('/api/ui-next/settings').json()['csrf_token']
        assert set(client.get('/api/ui-next/run').json()['providers'])=={'integrated'}
        for old in ('openalex','crossref','pubmed'):
            assert client.post('/api/ui-next/run',json={'csrf_token':csrf,'provider':old}).status_code==422
        assert client.post('/api/ui-next/run',json={'csrf_token':csrf,'enabled_providers':['openalex']}).status_code==409
        assert client.post('/api/ui-next/run',json={'csrf_token':csrf,'enabled_providers':['pubmed']}).status_code==200
        app.state.run_coordinator._worker.join(2)
        assert observed[0][1]['loaded_config'].enabled_providers==('pubmed',)
        assert observed[0][1]['workspace_snapshot'] is not None and observed[0][1]['cancel_event'] is not None


def test_journal_run_uses_only_selected_executable_roles(tmp_path):
    from allfold.application.integrated_run import discover_selected,validate_selection
    path,settings=config(tmp_path);settings=replace(settings,enabled_providers=('openalex',))
    calls=[]
    result=discover_selected(settings,path,client_factory=client_for((),calls=calls))
    assert result.status=='empty' and calls==['openalex']
    assert all(r.source.kind=='journal' for r in result.providers)
    with pytest.raises(ValueError): validate_selection(replace(settings,enabled_providers=('europe_pmc',)))


def test_snapshot_failure_reports_actual_created_papers(tmp_path):
    from allfold.application.run_summary import build_run_result_summary
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    (tmp_path/'workspace'/'.allfold'/'last-integrated-run.json').mkdir(parents=True)
    result=run_integrated(path,client_factory=client_for((evidence(),)))
    assert result.facts.created_papers==1 and any(issue.stage=='snapshot_write' for issue in result.warnings)
    summary=build_run_result_summary(result)
    assert summary['created_papers']==1 and summary['status']=='completed_with_notices'
