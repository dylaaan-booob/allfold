from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

from allfold.config import load_config, JournalConfig, render_settings_list_text
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult


def config(tmp_path, enabled=('europe_pmc','dblp')):
    path=tmp_path/'monitor.yaml'
    path.write_text('keyword_expression: learning\noutput_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-03\n')
    scope=tmp_path/'list.md'
    scope.write_text(render_settings_list_text(None,(JournalConfig(name='Test',issn='0006-341X'),),path=scope,groups=(),custom_labels=(),access_services=()))
    return path,replace(load_config(path), enabled_providers=enabled)


def test_only_selected_discovery_providers_run_and_one_failure_preserves_hits(tmp_path):
    from allfold.application.integrated_run import discover_selected
    path,settings=config(tmp_path)
    calls=[]
    class Client:
        def __init__(self,provider,**kwargs): self.provider=provider;calls.append(provider)
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def discover(self,source,*a):
            if self.provider=='dblp':return DiscoveryResult('dblp',source,'failed',limitations=('Access limited',))
            record=ProviderWorkEvidence(title='Native result',journal='Test',external_ids=ExternalIds(europe_pmc='MED:42'),provenance=MetadataSource(provider='europe_pmc',record_id='MED:42',retrieved_at=datetime.now(timezone.utc)))
            return DiscoveryResult(self.provider,source,'complete',(record,),candidates=1,total=1)
    result=discover_selected(settings,path,client_factory=Client)
    assert sorted(calls)==['dblp','europe_pmc']
    assert result.status=='partial'
    assert len(result.records)==1
    assert {r.status for r in result.providers}=={'complete','failed'}


def test_production_integrated_run_creates_doi_free_native_hit_and_preserves_saved_bytes(tmp_path):
    import httpx
    from allfold.application.integrated_run import run_integrated
    from allfold.providers.integrated import DiscoveryClient
    from allfold.application.run_summary import build_run_result_summary
    from allfold.application.run_state import read_last_run_snapshot,RunProvider
    path,settings=config(tmp_path,('europe_pmc',))
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc]\n')
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'hitCount':1,'resultList':{'result':[{'source':'MED','id':'42','title':'Native indexed term match','abstractText':'No configured literal keyword','firstPublicationDate':'2026-02-01','journalInfo':{'journal':{'title':'Test'}}}]}})
    def factory(provider,**kwargs):
        assert provider=='europe_pmc'
        return DiscoveryClient(provider,transport=httpx.MockTransport(handler),interval=0,**kwargs)
    first=run_integrated(path,client_factory=factory)
    assert first.created_papers==1 and first.matched_existing_papers==0
    assert build_run_result_summary(first)['coverage_status']=='complete'
    files=list((tmp_path/'workspace'/'Papers').glob('*.md'))
    assert len(files)==1
    original=files[0].read_bytes()
    calls.clear()
    second=run_integrated(path,client_factory=factory)
    assert second.created_papers==0 and second.matched_existing_papers==1
    assert files[0].read_bytes()==original
    assert len(calls)==1 # Existing Paper is not supplemented or rewritten.
    latest=read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED)
    assert latest.snapshot.facts.existing_papers==1


def test_constructor_failure_isolated_and_all_failed_is_never_complete(tmp_path):
    import httpx
    from allfold.application.integrated_run import run_integrated
    from allfold.providers.integrated import DiscoveryClient
    from allfold.application.run_summary import build_run_result_summary
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [openalex, europe_pmc]\n')
    def factory(provider,**kwargs):
        if provider=='openalex':raise ValueError('Credential configuration unavailable')
        return DiscoveryClient(provider,transport=httpx.MockTransport(lambda _:httpx.Response(200,json={'hitCount':0,'resultList':{'result':[]}})),interval=0,**kwargs)
    result=run_integrated(path,client_factory=factory)
    assert result.facts.details['discovery_status']=='partial'
    assert {x['status'] for x in result.facts.details['provider_runs']}=={'failed','empty'}
    path.write_text(path.read_text().replace('[openalex, europe_pmc]','[openalex]'))
    failed=run_integrated(path,client_factory=factory)
    assert build_run_result_summary(failed)['status']=='failed'


def test_provider_response_after_cancel_never_materializes(tmp_path):
    import httpx
    from threading import Event
    from allfold.application.integrated_run import run_integrated
    from allfold.providers.integrated import DiscoveryClient
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc]\n')
    cancel=Event()
    def handler(request):
        cancel.set()
        return httpx.Response(200,json={'hitCount':1,'resultList':{'result':[{'source':'MED','id':'42','title':'Late response'}]}})
    def factory(provider,**kwargs):return DiscoveryClient(provider,transport=httpx.MockTransport(handler),interval=0,**kwargs)
    result=run_integrated(path,client_factory=factory,cancel_event=cancel)
    assert result.outcome.value=='CANCELLED'
    assert not list((tmp_path/'workspace'/'Papers').glob('*.md'))


def test_saved_provider_selection_reaches_request_coordinator_and_retired_entries_reject(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from allfold.application.monitor import RunResult,RunOutcome,MonitorStatistics
    from allfold.application.run_state import RunProvider,RunFacts
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc, crossref]\n')
    observed=[]
    def monitor(config_path,**kwargs):
        observed.append((config_path,kwargs))
        return RunResult(RunProvider.INTEGRATED,None,0,0,0,(),(),RunOutcome.COMPLETED,MonitorStatistics(),facts=RunFacts(created_papers=0,existing_papers=0,details={'discovery_status':'empty'}))
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor',monitor)
    app=create_app(path,electron_bridge=OfflineBridge())
    with TestClient(app,base_url='http://localhost') as client:
        csrf=client.get('/api/ui-next/settings').json()['csrf_token']
        state=client.get('/api/ui-next/run').json()
        assert set(state['providers'])=={'integrated','wos'}
        for old in ('openalex','crossref','pubmed'):
            assert client.post('/api/ui-next/run',json={'csrf_token':csrf,'provider':old}).status_code==422
        mismatch=client.post('/api/ui-next/run',json={'csrf_token':csrf,'enabled_providers':['openalex']})
        assert mismatch.status_code==409
        started=client.post('/api/ui-next/run',json={'csrf_token':csrf,'enabled_providers':['europe_pmc','crossref']})
        assert started.status_code==200
        app.state.run_coordinator._worker.join(2)
        assert observed[0][1]['loaded_config'].enabled_providers==('europe_pmc','crossref')
        assert observed[0][1]['workspace_snapshot'] is not None
        assert observed[0][1]['cancel_event'] is not None


def test_conferences_and_vetted_journal_use_only_their_executable_roles(tmp_path):
    from allfold.application.integrated_run import discover_selected,validate_selection
    from allfold.config import ConferenceConfig
    path,settings=config(tmp_path)
    settings=replace(settings, enabled_providers=('openalex','dblp'),journals=(JournalConfig(name='JMLR',issn='1532-4435'),),conferences=(ConferenceConfig(id='conf_'+'1'*32,name='ICML',abbreviation='ICML',dblp_stream='streams/conf/icml'),))
    scopes=validate_selection(settings)
    assert scopes[0].stream=='streams/journals/jmlr'
    calls=[]
    class Client:
        def __init__(self,provider,**kwargs):self.provider=provider
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def discover(self,source,*args):
            calls.append((self.provider,source.kind))
            return DiscoveryResult(self.provider,source,'empty')
    result=discover_selected(settings,path,client_factory=Client)
    assert result.status=='empty'
    assert sorted(calls)==[('dblp','conference'),('dblp','journal'),('openalex','journal')]
    missing=replace(settings,enabled_providers=('openalex',))
    partial=discover_selected(missing,path,client_factory=Client)
    assert partial.status=='partial'
    assert any(r.source.kind=='conference' and r.status=='skipped' for r in partial.providers)
