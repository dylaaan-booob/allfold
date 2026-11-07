from datetime import date, datetime, timezone
from dataclasses import replace
from pathlib import Path

import pytest

from allfold.config import load_config, JournalConfig, render_settings_list_text
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult


def config(tmp_path, enabled=('europe_pmc','openalex')):
    path=tmp_path/'monitor.yaml'
    path.write_text('keyword_expression: learning\noutput_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-03\n')
    scope=tmp_path/'list.md'
    scope.write_text(render_settings_list_text(None,(JournalConfig(name='Test',issn='0006-341X'),),path=scope,groups=(),custom_labels=(),access_services=()))
    return path,replace(load_config(path), enabled_providers=enabled)


def test_run_retains_native_hit_without_lookups_and_reuses_durable_rediscovery(tmp_path):
    import httpx
    from allfold.application.integrated_run import run_integrated
    from allfold.application.workspace import load_workspace
    from allfold.providers.integrated import DiscoveryClient
    from allfold.persistence.discovery_evidence import read_discovery_evidence
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [europe_pmc]\ncompletion_providers: [crossref, arxiv]\n')
    calls = []
    abstract = None
    def response(request):
        calls.append(request)
        assert request.url.path.endswith('/search')
        assert 'FIRST_PDATE:[2026-01-01 TO 2026-03-31]' in request.url.params['query']
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{
            'source': 'MED', 'id': '42', 'doi': '10.5555/formal', 'title': 'Native hit',
            'firstPublicationDate': '2025', 'abstractText': abstract,
            'commentCorrectionList': {'commentCorrection': [{'type': 'Preprint in', 'source': 'PPR', 'id': 'PPR7'}]},
        }]}})
    def factory(provider, **kwargs):
        assert provider == 'europe_pmc'
        return DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    first = run_integrated(path, client_factory=factory)
    assert first.facts.created_papers == 1
    paper, = load_workspace(tmp_path / 'workspace').inbox
    assert paper.publication_date == '2025' and paper.first_public_at is None
    saved, = (tmp_path / 'workspace' / 'Papers').glob('*.md')
    original = saved.read_bytes()
    abstract = 'New rediscovery evidence'
    second = run_integrated(path, client_factory=factory)
    assert second.facts.existing_papers == 1 and saved.read_bytes() == original
    handoff = read_discovery_evidence(tmp_path / 'workspace', paper.paper_id)
    assert any(record.abstract == abstract for record in handoff.records)
    assert any(reference.record_id == 'PPR:PPR7' for record in handoff.records for reference in record.related_ids)
    assert handoff.scopes[0].from_date == '2026-01-01'
    assert len(calls) == 2


def test_only_selected_discovery_providers_run_and_one_failure_preserves_hits(tmp_path):
    from allfold.application.integrated_run import discover_selected
    path,settings=config(tmp_path)
    calls=[]
    class Client:
        def __init__(self,provider,**kwargs): self.provider=provider;calls.append(provider)
        def __enter__(self):return self
        def __exit__(self,*a):pass
        def discover(self,source,*a):
            if self.provider=='openalex':return DiscoveryResult('openalex',source,'failed',limitations=('Access limited',))
            record=ProviderWorkEvidence(title='Native result',journal='Test',external_ids=ExternalIds(europe_pmc='MED:42'),provenance=MetadataSource(provider='europe_pmc',record_id='MED:42',retrieved_at=datetime.now(timezone.utc)))
            return DiscoveryResult(self.provider,source,'complete',(record,),candidates=1,total=1)
    result=discover_selected(settings,path,client_factory=Client)
    assert sorted(calls)==['europe_pmc','openalex']
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
    assert first.facts.created_papers==1 and first.facts.existing_papers==0
    assert build_run_result_summary(first)['coverage_status']=='complete'
    files=list((tmp_path/'workspace'/'Papers').glob('*.md'))
    assert len(files)==1
    original=files[0].read_bytes()
    calls.clear()
    second=run_integrated(path,client_factory=factory)
    assert second.facts.created_papers==0 and second.facts.existing_papers==1
    assert files[0].read_bytes()==original
    assert len(calls)==1 # Existing Paper is not supplemented or rewritten.
    latest=read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED)
    assert latest.snapshot.facts.existing_papers==1
    import json
    raw = json.loads(latest.path.read_text())
    assert raw['schema_version'] == 5 and 'coverage' not in raw
    assert build_run_result_summary(latest) == build_run_result_summary(second)


@pytest.mark.parametrize('failed_provider', ['openalex', 'europe_pmc'])
def test_discovery_exceptions_share_category_but_retain_provider_and_source(tmp_path, failed_provider):
    from allfold.application.integrated_run import run_integrated
    from allfold.application.run_summary import build_run_result_summary
    from allfold.application.monitor import MonitorIssueComponent
    path, _ = config(tmp_path)
    calls = []

    class Client:
        def __init__(self, provider, **kwargs):
            self.provider = provider
            calls.append(provider)
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def discover(self, source, *args):
            if self.provider == failed_provider:
                raise OSError('Isolated discovery failure')
            record = ProviderWorkEvidence(title='Surviving native hit', journal='Test',
                external_ids=ExternalIds(doi='10.5555/survivor'),
                provenance=MetadataSource(provider=self.provider, record_id='42',
                                          retrieved_at=datetime.now(timezone.utc)))
            return DiscoveryResult(self.provider, source, 'complete', (record,), candidates=1, total=1)

    result = run_integrated(path, client_factory=Client)
    assert sorted(calls) == ['europe_pmc', 'openalex']
    issue, = result.errors
    assert issue.component is MonitorIssueComponent.DISCOVERY
    assert failed_provider in issue.message and 'Test' in issue.message
    summary = build_run_result_summary(result)
    assert summary['status'] == 'incomplete' and summary['coverage_status'] == 'partial'
    assert summary['created_papers'] == 1
    assert summary['issues'][0]['category'] == 'discovery'
    assert summary['issues'][0]['message'] == issue.message
    assert {run['provider']: run['status'] for run in summary['details']['provider_runs']} == {
        provider: 'failed' if provider == failed_provider else 'complete'
        for provider in ('openalex', 'europe_pmc')}


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


def test_repeated_run_matches_separate_doi_aliases_to_one_saved_paper(tmp_path):
    from allfold.application.integrated_run import run_integrated
    path, _ = config(tmp_path, ('europe_pmc',))
    path.write_text(path.read_text() + 'enabled_providers: [europe_pmc]\n')
    formal = ProviderWorkEvidence(
        title='Formal paper', journal='Test',
        external_ids=ExternalIds(doi='10.5555/formal', europe_pmc='MED:42'),
        related_dois=('10.5555/preprint',),
        provenance=MetadataSource(provider='europe_pmc', record_id='MED:42',
                                  retrieved_at=datetime.now(timezone.utc)),
    )
    records = (formal,)
    calls = []

    class Client:
        def __init__(self, provider, **kwargs):
            assert provider == 'europe_pmc'
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def discover(self, source, *args):
            calls.append('discover')
            return DiscoveryResult('europe_pmc', source, 'complete', records,
                                   candidates=len(records), total=len(records))
        def lookup(self, *args):
            raise AssertionError('Already discovered or saved identities need no supplement')

    first = run_integrated(path, client_factory=Client)
    assert first.facts.created_papers == 1 and not first.errors
    saved, = (tmp_path / 'workspace' / 'Papers').glob('*.md')
    before = saved.read_bytes()
    records = tuple(formal.model_copy(update={
        'title': 'Later metadata', 'external_ids': ExternalIds(doi=doi),
        'related_dois': (),
        'provenance': formal.provenance.model_copy(update={'record_id': str(index)}),
    }) for index, doi in enumerate(('10.5555/formal', '10.5555/preprint')))
    second = run_integrated(path, client_factory=Client)
    assert not second.errors
    assert second.facts.created_papers == 0 and second.facts.existing_papers == 1
    assert saved.read_bytes() == before
    assert calls == ['discover', 'discover']


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
    from allfold.application.monitor import RunResult,RunOutcome
    from allfold.application.run_state import RunProvider,RunFacts
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc]\n')
    observed=[]
    def monitor(config_path,**kwargs):
        observed.append((config_path,kwargs))
        return RunResult(RunProvider.INTEGRATED,None,(),(),RunOutcome.COMPLETED,facts=RunFacts(created_papers=0,existing_papers=0,details={'discovery_status':'empty'}))
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
        started=client.post('/api/ui-next/run',json={'csrf_token':csrf,'enabled_providers':['europe_pmc']})
        assert started.status_code==200
        app.state.run_coordinator._worker.join(2)
        assert observed[0][1]['loaded_config'].enabled_providers==('europe_pmc',)
        assert observed[0][1]['workspace_snapshot'] is not None
        assert observed[0][1]['cancel_event'] is not None


def test_conferences_and_vetted_journal_use_only_their_executable_roles(tmp_path):
    from allfold.application.integrated_run import discover_selected,validate_selection
    from allfold.config import ConferenceConfig
    path,settings=config(tmp_path)
    settings=replace(settings, enabled_providers=('openalex',),journals=(JournalConfig(name='JMLR',issn='1532-4435'),),conferences=(ConferenceConfig(id='conf_'+'1'*32,name='ICML',abbreviation='ICML',dblp_stream='streams/conf/icml'),))
    scopes=validate_selection(settings)
    assert len(scopes)==1 and scopes[0].kind=='journal'
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
    assert calls==[('openalex','journal')]
    missing=replace(settings,enabled_providers=('openalex',))
    partial=discover_selected(missing,path,client_factory=Client)
    assert partial.status=='empty'
    assert all(r.source.kind=='journal' for r in partial.providers)


def test_snapshot_failure_reports_actual_created_papers(tmp_path):
    import httpx
    from allfold.application.integrated_run import run_integrated
    from allfold.providers.integrated import DiscoveryClient
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc]\n')
    (tmp_path/'workspace'/'.allfold'/'last-integrated-run.json').mkdir(parents=True)
    def handler(request):
        return httpx.Response(200,json={'hitCount':1,'resultList':{'result':[{'source':'MED','id':'44','title':'Native hit'}]}})
    def factory(provider,**kwargs):return DiscoveryClient(provider,transport=httpx.MockTransport(handler),interval=0,**kwargs)
    result=run_integrated(path,client_factory=factory)
    assert result.facts.created_papers==1
    assert any(issue.stage=='snapshot_write' for issue in result.warnings)
    assert len(list((tmp_path/'workspace'/'Papers').glob('*.md')))==1
    from allfold.application.run_summary import build_run_result_summary
    summary = build_run_result_summary(result)
    assert summary['created_papers'] == 1 and summary['existing_papers'] == 0
    assert summary['status'] == 'completed_with_notices'
    assert summary['issues'][0]['category'] == 'snapshot_write'
