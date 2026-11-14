"""Production collection plans retain real document and necessary API branches."""
import pytest

from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperMetadata, PaperRepository


def test_production_plan_has_independent_api_and_explicit_document_access(tmp_path):
    from allfold.application.collection_planner import ProductionCollectionService
    from test_integrated_run import config
    path, settings = config(tmp_path, enabled=('pubmed',))
    workspace = settings.output_dir
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/formal'),
            metadata=PaperMetadata(title='Base', journal='Test', publication_type='journal')).paper
    branches = ProductionCollectionService(None).plan(paper=paper, config=settings)
    assert [branch.name for branch in branches] == ['document', 'necessary-api']
    assert all(branch.run is not None for branch in branches)
    assert branches[0].service_id is None
    assert branches[1].service_id is None
    assert set(branches[1].providers) == {'pubmed', 'crossref', 'europe_pmc', 'arxiv', 'biorxiv', 'medrxiv'}
    assert 'openalex' not in branches[1].providers


def test_direct_preprint_pmid_and_related_work_are_necessary_purposes(tmp_path):
    from allfold.application.necessary_metadata import NecessaryRequest, necessary_requests
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.models import MetadataSource, ProviderRecordRef, ProviderWorkEvidence
    from datetime import datetime, timezone
    from test_integrated_run import config
    _, settings = config(tmp_path)
    row = ProviderWorkEvidence(provenance=MetadataSource(provider='pubmed', record_id='42',
        retrieved_at=datetime.now(timezone.utc)), external_ids=ExternalIds(pmid='42'), publication_type='preprint',
        related_ids=(ProviderRecordRef(provider='openalex', record_id='W123'),))
    assert NecessaryRequest('pubmed', 'pmid', '42', 'fetch-preprint') in necessary_requests((row,),
        root_ids={('pmid', '42')}, providers=('pubmed',))
    plan = ProductionCollectionService(None).plan(metadata=PaperMetadata(title='Preprint', publication_type='preprint'),
        identities={('pmid', '42')}, records=(row,), config=settings)
    assert 'openalex' in plan[1].providers


@pytest.mark.parametrize('next_provider', ['pubmed', 'wos'])
def test_http_run_hands_off_real_branches_and_next_run_cancel_preserves_them(tmp_path, monkeypatch, next_provider):
    from concurrent.futures import Future
    from threading import Event
    import httpx
    from fastapi.testclient import TestClient
    from allfold.providers.integrated import DiscoveryClient
    from allfold.web.app import create_app
    from allfold.application.run_state import read_last_run_snapshot, RunProvider
    from allfold.persistence.paper_repository import PaperRepository
    from test_document_metadata import envelope
    from test_pubmed_discovery import article
    from test_integrated_run import config

    path, _ = config(tmp_path, enabled=('pubmed',))
    path.write_text(path.read_text() + 'enabled_providers: [pubmed]\nfrom_month: 2026-10\nto_month: 2026-10\n')
    if next_provider == 'wos':
        from dataclasses import replace
        from allfold.config import AccessService
        from allfold.persistence.user_state import load_user_state, compare_write_user_state
        saved=load_user_state(path)
        compare_write_user_state(path,replace(saved.state,access_services=(AccessService.create(
            'Web of Science','https://www.webofscience.com/'),)),saved.revision)
    api_started, release_api, second_search, release_second = (Event() for _ in range(4))
    search_count, calls, closed = [], [], []
    def transport(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            search_count.append(request)
            if len(search_count) == 2:
                second_search.set()
                assert release_second.wait(5)
            return httpx.Response(200, json={'esearchresult': {'count':'1', 'idlist':['42'], 'webenv':'fixture', 'querykey':'1'}})
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200, text='<PubmedArticleSet>' + article('42','0006-341X','10.5555/formal') + '</PubmedArticleSet>')
        if request.url.host == 'api.openalex.org':
            return httpx.Response(200, json={'results':[], 'meta':{'count':0}})
        if request.url.host == 'api.crossref.org':
            api_started.set()
            assert release_api.wait(5)
            items = [] if 'relation.type:' in request.url.params.get('filter','') else [{'DOI':'10.5555/formal',
                'type':'journal-article', 'accepted':{'date-parts':[[2026,9,13]]}}]
            return httpx.Response(200,json={'message':{'items':items,'total-results':len(items)}})
        if request.url.host == 'www.ebi.ac.uk':
            return httpx.Response(200,json={'hitCount':0,'resultList':{'result':[]}})
        raise AssertionError(str(request.url))
    original_init, original_exit = DiscoveryClient.__init__, DiscoveryClient.__exit__
    def init(self, provider, **kwargs):
        original_init(self, provider, transport=httpx.MockTransport(transport), interval=0, **kwargs)
    def exit_client(self, *args):
        original_exit(self,*args)
        closed.append((self.provider, self))
    monkeypatch.setattr(DiscoveryClient,'__init__',init)
    monkeypatch.setattr(DiscoveryClient,'__exit__',exit_client)
    class Bridge:
        connected, closing = True, False
        def __init__(self):
            self.entered, self.future, self.cancels = Event(), Future(), []
            self.export, self.actions = Future(), []
        def execute(self, action, payload, *args, **kwargs):
            self.actions.append(action)
            if action == 'wos_query':
                done=Future();done.set_result(dict(page_id=71,total=1,batch_limit=1));return done
            if action == 'wos_export':
                second_search.set()
                return self.export
            if action == 'release_workflow_pages':
                done=Future();done.set_result({'released':True});return done
            assert action == 'extract_paper_metadata'
            self.entered.set()
            return self.future
        def cancel_task(self,*target): self.cancels.append(target)
        def cancel_workflow(self,*target): self.cancels.append(target)
        def finish_disconnected(self): pass
    bridge=Bridge()
    app=create_app(path,electron_bridge=bridge)
    if next_provider == 'wos':
        from allfold.application.coordinators.login import PreparedService
        monkeypatch.setattr(app.state.login,'prepared_authority',lambda *_: PreparedService(71,'e'*64,False))
    from contextlib import ExitStack
    def release_blocked():
        release_api.set();release_second.set()
        if not bridge.future.done(): bridge.future.set_result(envelope())
        if not bridge.export.done(): bridge.export.set_result({})
    try:
        with TestClient(app,base_url='http://localhost') as client, ExitStack() as exits:
            exits.callback(release_blocked)
            csrf=client.get('/api/ui-next/settings').json()['csrf_token']
            assert client.post('/api/ui-next/run',json={'csrf_token':csrf}).status_code == 200
            assert bridge.entered.wait(3) and api_started.wait(3)
            app.state.run_coordinator.join()
            first=client.get('/api/ui-next/run').json()
            assert first['snapshot']['status'] == 'FINISHED'
            assert first['result_summary']['created_papers'] == 1
            assert any(provider == 'pubmed' for provider,_ in closed)
            projection=client.get('/api/ui-next/workspace').json()
            papers=[paper for subject in projection['subjects'] for journal in subject['journals'] for paper in journal['papers']]
            assert len(papers) == 1
            paper=papers[0]
            assert paper['title'] == 'Native causal title'
            assert paper['collection_status'] in {'queued','running'}
            base_id=paper['id']
            first_snapshot=read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED)
            if next_provider == 'wos':
                path.write_text(path.read_text().replace('enabled_providers: [pubmed]','enabled_providers: [wos]'))
            assert client.post('/api/ui-next/run',json={'csrf_token':csrf}).status_code == 200
            assert second_search.wait(3)
            second_id=app.state.run_coordinator.snapshot().task_id
            assert client.post('/api/ui-next/run',json={'csrf_token':csrf}).status_code == 409
            assert client.post('/api/ui-next/run/cancel',json={'csrf_token':csrf,'task_id':second_id}).status_code == 200
            assert bridge.cancels == ([(second_id,)] if next_provider == 'wos' else [])
            if next_provider == 'wos':
                assert {'wos_query','wos_export'} <= set(bridge.actions)
                bridge.export.set_result({})
            release_second.set()
            app.state.run_coordinator.join()
            assert client.get('/api/ui-next/run').json()['snapshot']['status'] == 'FINISHED'
            assert read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED) == first_snapshot
            assert not bridge.future.done()
            release_api.set();bridge.future.set_result(envelope(abstract='Late DOM abstract', dates=[{'value':'2026-10-04','precision':'day'}]))
            registry=app.state.workspace_tasks.current()
            with PaperRepository.open(tmp_path/'workspace') as repository:
                captured=repository.get(__import__('uuid').UUID(base_id))
            task=registry.admit(direct_ids=ExternalIds(doi='10.5555/formal'),metadata=captured.metadata,
                branches=app.state.collection_service.plan(paper=captured))
            finished=task.future.result(5)
            assert finished.collection_status == 'completed'
            late=client.get('/api/ui-next/workspace').json()['subjects'][0]['journals'][0]['papers'][0]
            assert late['id'] == base_id and late['abstract'] == 'METHODS: Study abstract'
            assert {'2026-09-13','2026-10-04'} <= set(late['ordinary_dates'])
            assert read_last_run_snapshot(tmp_path/'workspace',RunProvider.INTEGRATED) == first_snapshot
            assert not any(request.url.path.endswith('esummary.fcgi') for request in calls)
            assert sum(request.url.path.endswith('efetch.fcgi') for request in calls) == 1
    finally:
        release_api.set();release_second.set()
        if not bridge.future.done(): bridge.future.set_result(envelope())
        if not bridge.export.done(): bridge.export.set_result({})
        app.state.workspace_tasks.shutdown();app.state.workspace_tasks.join()


def test_journal_name_does_not_grant_service_and_ambiguous_issn_keeps_base(tmp_path):
    from dataclasses import replace
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.config import JournalConfig
    from test_integrated_run import config
    _, settings=config(tmp_path)
    settings=replace(settings,journals=(JournalConfig(name='Test',issn='0006-341X',access_service_id='svc_'+'a'*32),))
    planner=ProductionCollectionService(None)
    unbound=planner.plan(metadata=PaperMetadata(title='Name only',journal='Test'),
        identities={('doi','10.5555/formal')},config=settings)
    assert unbound[0].service_id is None
    settings=replace(settings,journals=(*settings.journals,
        JournalConfig(name='Other',issn='0006-341X',access_service_id='svc_'+'b'*32)))
    branches=planner.plan(metadata=PaperMetadata(title='Base',journal='Test',journal_issns=('0006-341X',)),
        identities={('doi','10.5555/formal')},config=settings)
    assert branches[0].skip_reason is None and branches[0].run is not None


def test_ambiguous_service_fails_document_without_losing_base_or_api(tmp_path):
    from dataclasses import replace
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.application.collection_runtime import WorkspaceRegistry
    from allfold.application.task_clients import IndependentClientFactory
    from allfold.config import JournalConfig
    from integrated_run_helpers import EmptyLookup
    from test_integrated_run import config
    path,settings=config(tmp_path)
    settings=replace(settings,journals=tuple(JournalConfig(name=name,issn='0006-341X',access_service_id='svc_'+token*32)
        for name,token in (('First','a'),('Second','b'))))
    metadata=PaperMetadata(title='Readable base',journal_issns=('0006-341X',))
    branches=ProductionCollectionService(None).plan(metadata=metadata,
        identities={('doi','10.5555/formal')},config=settings)
    workspace=tmp_path/'workspace';workspace.mkdir()
    with PaperRepository.create(workspace): pass
    factory=IndependentClientFactory(path,client_factory=EmptyLookup)
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    host=WorkspaceTaskHost(path,factory=factory)
    registry=host.current()
    try:
        task=registry.submit(direct_ids=ExternalIds(doi='10.5555/formal'),metadata=metadata,branches=branches)
        settled=task.future.result(3)
        assert settled.metadata.title == 'Readable base' and settled.collection_status == 'failed'
        assert {branch.name:branch.state for branch in settled.collection.branches} == {
            'document':'failed','necessary-api':'completed'}
    finally:
        registry.shutdown();registry.join();factory.close()


def test_base_does_not_seal_first_public_before_reverse_and_new_native_family(tmp_path):
    from concurrent.futures import Future
    from threading import Event
    import httpx
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.application.integrated_run import run_integrated
    from allfold.application.provider_lookup import provider_client
    from allfold.application.task_clients import IndependentClientFactory
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.application.run_commit import capture_run_workspace
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    from integrated_run_helpers import EmptyLookup
    from test_integrated_run import config, evidence, client_for
    from test_document_metadata import envelope
    path,_=config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    formal=evidence().model_copy(update={
        'related_ids':(ProviderRecordRef(provider='arxiv',record_id='2201.12345',relation='preprint'),),
        'dates':(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,month=1,day=2,
            provider='arxiv',record_id='2201.12345',publication_type='preprint',first_version=True),)})
    reversed_started,release_reverse,native_started,release_native=(Event() for _ in range(4))
    def response(request):
        if request.url.path.startswith('/details/'):
            native_started.set();assert release_native.wait(5)
            return httpx.Response(200,json={'messages':[{'status':'ok'}],'collection':[{
                'doi':'10.64898/earlier','server':'medrxiv','published':'10.5555/formal','version':'1','date':'2019-01-02'}]})
        if 'relation.type:' in request.url.params.get('filter',''):
            reversed_started.set();assert release_reverse.wait(5)
            rows=[{'DOI':'10.64898/earlier','type':'posted-content','publisher':'medrxiv',
                'relation':{'is-preprint-of':[{'id-type':'doi','id':'10.5555/formal'}]}}]
        elif request.url.params.get('filter') == 'doi:10.5555/formal':
            rows=[{'DOI':'10.5555/formal','type':'journal-article'}]
        else:
            rows=[{'DOI':'10.64898/earlier','type':'posted-content','publisher':'medrxiv'}]
        return httpx.Response(200,json={'message':{'items':rows,'total-results':len(rows)}})
    def factory(provider,**kwargs):
        if provider in {'crossref','medrxiv'}:
            return provider_client(provider,transport=httpx.MockTransport(response),interval=0,**kwargs)
        return EmptyLookup(provider,**kwargs)
    class Bridge:
        def execute(self,action,*args,**kwargs):
            future=Future();future.set_result({'released':True} if action=='release_workflow_pages' else envelope());return future
        def cancel_task(self,*args): pass
    with capture_run_workspace(path): pass
    clients=IndependentClientFactory(path,client_factory=factory)
    host=WorkspaceTaskHost(path,factory=clients,bridge=Bridge())
    try:
        result=run_integrated(path,client_factory=client_for((formal,)),lookup_factory=EmptyLookup,workspace_tasks=host)
        assert result.facts.created_papers == 1 and reversed_started.wait(3)
        with PaperRepository.open(tmp_path/'workspace') as repository:
            base,=repository.list_papers()
        assert base.metadata.first_public_at is None and base.metadata.preprint_evidence
        release_reverse.set();assert native_started.wait(3)
        with PaperRepository.open(tmp_path/'workspace') as repository:
            assert repository.get(base.id).metadata.first_public_at is None
        captured=host.current().admit(direct_ids=ExternalIds(doi='10.5555/formal'),metadata=base.metadata,
            branches=ProductionCollectionService(host).plan(paper=base))
        release_native.set()
        completed=captured.future.result(5)
        assert completed.collection_status == 'completed'
        assert completed.id == base.id and completed.metadata.first_public_at == '2019-01-02'
    finally:
        release_reverse.set();release_native.set();host.shutdown();host.join()


def test_complete_foreground_capabilities_reuse_first_public_without_requests(tmp_path):
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.application.necessary_metadata import NecessaryRequest, VerifiedResponse
    from allfold.canonicalize import completion_metadata
    from allfold.models import EvidenceDate, EvidenceDateKind, ProviderRecordRef
    from test_necessary_metadata import record, execute
    from test_integrated_run import config
    formal=record(title='Formal',journal='Test',related_ids=(ProviderRecordRef(
        provider='arxiv',record_id='2201.12345',relation='preprint'),))
    import httpx
    from allfold.providers.supplemental import SupplementalClient
    atom='<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>http://arxiv.org/abs/2201.12345v3</id><published>2022-01-02T00:00:00Z</published></entry></feed>'
    with SupplementalClient('arxiv',interval=0,transport=httpx.MockTransport(lambda _:httpx.Response(200,text=atom))) as parser:
        native_records=parser.lookup('arxiv','2201.12345')
    records=(formal,*native_records)
    exact=VerifiedResponse(NecessaryRequest('crossref','doi','10.5555/formal','exact'),(formal,))
    reverse=VerifiedResponse(NecessaryRequest('crossref','doi','10.5555/formal','reverse'),())
    native=VerifiedResponse(NecessaryRequest('arxiv','arxiv','2201.12345','native'),native_records)
    roots={('doi','10.5555/formal')}
    planner=ProductionCollectionService(None)
    canonical=completion_metadata(records)
    partial=planner.base_metadata(canonical,identities=roots,records=records,facts=(exact,
        VerifiedResponse(native.request,native_records,complete=False)))
    assert partial.first_public_at is None
    complete=planner.base_metadata(canonical,identities=roots,records=records,facts=(exact,reverse,native))
    assert complete.first_public_at == '2022-01-02'
    _,settings=config(tmp_path)
    api=planner.plan(metadata=complete,identities=roots,records=records,facts=(exact,reverse,native),config=settings)[1]
    saved,clients=execute(tmp_path,api,metadata=complete,
        transport=lambda _: pytest.fail('Complete foreground capability was requested twice'))
    assert saved.metadata.first_public_at == '2022-01-02' and saved.collection_status == 'completed'
    assert clients == []


def test_public_retry_service_checks_exact_attempt_and_only_pending_api_access(tmp_path):
    from concurrent.futures import Future
    import httpx
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.collection_planner import ProductionCollectionService
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.provider_lookup import provider_client
    from allfold.application.run_commit import capture_run_workspace
    from allfold.application.task_clients import IndependentClientFactory
    from allfold.application.workspace_tasks import WorkspaceTaskHost
    from allfold.persistence.paper_repository import StaleWriteError
    from safety_config_helpers import current_mapping_document
    from test_document_metadata import envelope
    from integrated_run_helpers import EmptyLookup
    path,_,_,_=current_mapping_document(tmp_path)
    with capture_run_workspace(path): pass
    fail_api=[True]
    def response(request):
        return httpx.Response(400) if fail_api[0] else httpx.Response(200,json={'message':{'items':[],'total-results':0}})
    def factory(provider,**kwargs):
        return (provider_client(provider,transport=httpx.MockTransport(response),interval=0,**kwargs)
            if provider=='crossref' else EmptyLookup(provider,**kwargs))
    class Login:
        available=True
        captures=0
        def prepared_authority(self,*args):
            self.captures+=1
            return PreparedService(71,'e'*64,False) if self.available else None
    class Bridge:
        document_calls=0
        def execute(self,action,*args,**kwargs):
            future=Future()
            if action!='release_workflow_pages': self.document_calls+=1
            future.set_result({'released':True} if action=='release_workflow_pages' else envelope())
            return future
        def cancel_task(self,*args): pass
    login,bridge=Login(),Bridge()
    host=WorkspaceTaskHost(path,login=login,bridge=bridge,browser_lock=BrowserTaskLock(),
        factory=IndependentClientFactory(path,client_factory=factory))
    service=ProductionCollectionService(host)
    metadata=PaperMetadata(title='Base',journal_issns=('0006-341X',))
    try:
        registry=host.current()
        task=registry.submit(direct_ids=ExternalIds(doi='10.5555/formal'),metadata=metadata,
            branches=service.plan(metadata=metadata,identities={('doi','10.5555/formal')}))
        failed=task.future.result(3)
        assert failed.collection_status=='failed'
        assert {branch.name:branch.state for branch in failed.collection.branches} == {
            'document':'completed','necessary-api':'failed'}
        login.available=False;capture_count=login.captures
        with pytest.raises(StaleWriteError):
            service.check_retry(failed.id,workspace_id=failed.workspace_id,expected_token=failed.token,expected_attempt=2)
        assert service.check_retry(failed.id,workspace_id=failed.workspace_id,
            expected_token=failed.token,expected_attempt=1) == failed
        with PaperRepository.open(tmp_path/'workspace') as repository:
            assert repository.get(failed.id)==failed
        fail_api[0]=False
        retried=service.retry(failed.id,workspace_id=failed.workspace_id,
            expected_token=failed.token,expected_attempt=1).future.result(3)
        assert retried.collection_status=='completed' and retried.collection.attempt==2
        assert bridge.document_calls==1 and login.captures==capture_count
    finally:
        host.shutdown();host.join()
