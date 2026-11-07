from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from allfold.application.integrated_run import run_integrated, IntegratedDiscovery
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult, SourceScope
from test_integrated_run import config
from integrated_run_helpers import EmptyCompletion


def record(provider, doi, **fields):
    return ProviderWorkEvidence(title='Formal '+doi, abstract='Abstract', authors=({'name':'Author'},), journal='Test',
        publication_type='journal', monitor_journal_issns=('0006-341X',), external_ids=ExternalIds(doi=doi),
        provenance=MetadataSource(provider=provider, record_id=doi, retrieved_at=datetime.now(timezone.utc)), **fields)


def test_discovery_and_work_overlap_then_tail_drains_before_completion(tmp_path):
    path, settings=config(tmp_path, ('wos','pubmed','openalex'))
    path.write_text(path.read_text()+'enabled_providers: [wos,pubmed,openalex]\n')
    entered={name:Event() for name in ('wos','pubmed','openalex')}
    located=Event()
    batches=[]
    class Client(EmptyCompletion):
        def discover_many(self, scopes, *args, records_callback=None):
            entered[self.provider].set()
            assert all(event.wait(3) for event in entered.values()), 'Discovery must overlap'
            rows=(record(self.provider, '10.5555/shared'),)
            if self.provider=='pubmed':
                records_callback(rows)
                assert located.wait(3), 'Work lookup must overlap an active producer'
                rows += (record(self.provider,'10.5555/tail'),)
                records_callback(rows[-1:])
            return (DiscoveryResult(self.provider, scopes[0], 'complete', rows,candidates=len(rows)),)
        def lookup_many(self, namespace, ids, **kwargs):
            batches.append(tuple(ids))
            located.set()
            return DiscoveryResult('openalex',SourceScope('journal',''),'empty')
    def wos(snapshot, *, records_callback=None, **kwargs):
        entered['wos'].set()
        assert all(event.wait(3) for event in entered.values())
        rows=(record('wos','10.5555/shared'),)
        records_callback(rows)
        return IntegratedDiscovery(rows,(DiscoveryResult('wos',SourceScope('journal','Test'),'complete',rows,candidates=1),),'complete')
    result=run_integrated(path,loaded_config=settings,client_factory=Client,completion_factory=EmptyCompletion,wos_stage=wos)
    assert result.facts.created_papers==2
    assert [identity for batch in batches for identity in batch]==['10.5555/shared','10.5555/tail']
    assert result.facts.statistics['integrated_deduplicated']==2
    assert result.facts.statistics['completion_targets']==2
    assert result.facts.details['completion_status']=='complete'


def test_completion_folds_related_version_dates_without_identity_or_ordinary_leak(tmp_path):
    from allfold.application.workspace import load_workspace
    from allfold.models import ProviderRecordRef, EvidenceDate, EvidenceDateKind, Author
    from test_integrated_run import client_for, evidence
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\ncompletion_providers: []\n')
    formal=evidence(doi='10.1093/nar/gkag979',pmid='42908400').model_copy(update={
        'authors':(Author(name='Formal Author'),), 'abstract':'Formal abstract',
        'related_ids':(ProviderRecordRef(provider='arxiv',record_id='2201.12345',relation='preprint'),)})
    # A saved related preprint remains an independent owner, and cannot suppress
    # creation or provide ordinary fields to the formal root.
    preprint=ProviderWorkEvidence(title='Preprint title',abstract='Preprint abstract',publication_type='preprint',
        external_ids=ExternalIds(doi='10.5555/preprint',pmid='42239170',arxiv='2201.12345'),
        provenance=MetadataSource(provider='arxiv',record_id='2201.12345',retrieved_at=datetime.now(timezone.utc),note='Native version'),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT,year=2022,month=1,day=4,first_version=True,publication_type='preprint'),))
    from allfold.canonicalize import canonicalize_records
    from allfold.persistence.materialize import materialize_papers
    materialize_papers(canonicalize_records((preprint,)).papers,tmp_path/'workspace')
    saved,=(tmp_path/'workspace'/'Papers').glob('*.md');before=saved.read_bytes()
    calls=[]
    class Completion(EmptyCompletion):
        def lookup_many(self,namespace,ids,**kwargs):
            calls.append((self.provider,namespace,tuple(ids)))
            return {identity:(preprint,) if self.provider=='arxiv' else () for identity in ids}
    result=run_integrated(path,client_factory=client_for((formal,)),completion_factory=Completion)
    papers=load_workspace(tmp_path/'workspace').papers
    created=next(paper for paper in papers if paper.external_ids.doi=='10.1093/nar/gkag979')
    assert len(papers)==2 and result.facts.created_papers==1 and saved.read_bytes()==before
    assert created.external_ids.pmid=='42908400' and created.external_ids.arxiv is None
    assert created.title=='Native hit' and created.abstract=='Formal abstract'
    assert list(created.authors)==['Formal Author']
    assert created.first_public_at=='2022-01-04'
    assert result.facts.statistics['completion_date_facts_added']==1
    assert result.facts.statistics['first_public_recorded']==1
    assert any(provider=='arxiv' for provider,_,_ in calls)
    assert not any(provider in {'biorxiv','medrxiv'} for provider,_,_ in calls)


def test_completion_failure_keeps_discovered_paper_and_reports_partial(tmp_path):
    from test_integrated_run import client_for, evidence
    from allfold.application.run_summary import build_run_result_summary
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    class Failure(EmptyCompletion):
        def lookup_many(self,namespace,ids,**kwargs):
            if self.provider=='crossref': raise ValueError('Controlled provider failure')
            return super().lookup_many(namespace,ids,**kwargs)
        def lookup_preprints(self,ids): raise ValueError('Controlled reverse failure')
    result=run_integrated(path,client_factory=client_for((evidence(),)),completion_factory=Failure)
    assert result.facts.created_papers==1 and result.facts.details['completion_status']=='partial'
    assert build_run_result_summary(result)['coverage_status']=='partial'


@pytest.mark.parametrize('linked_type', ['preprint', 'journal'])
def test_formal_abstract_gap_fetches_pubmed_despite_complete_bound_preprint(tmp_path, linked_type):
    import httpx
    from allfold.application.workspace import load_workspace
    from allfold.models import Author, EvidenceDate, EvidenceDateKind, ProviderRecordRef
    from allfold.providers.integrated import DiscoveryClient
    from test_pubmed_discovery import article
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    formal = record('wos', '10.1093/nar/gkag979').model_copy(update={
        'abstract': None, 'authors': (Author(name='WoS One'), Author(name='WoS Two')),
        'external_ids': ExternalIds(doi='10.1093/nar/gkag979', pmid='42908400')})
    anchor = ProviderWorkEvidence(publication_type='journal', external_ids=ExternalIds(doi='10.1093/nar/gkag979'),
        related_ids=(ProviderRecordRef(provider='openalex', record_id='W1'),),
        provenance=MetadataSource(provider='openalex', record_id='W1:binding', retrieved_at=datetime.now(timezone.utc)))
    preprint = ProviderWorkEvidence(title='Preprint title', abstract='Preprint abstract',
        authors=(Author(name='Preprint Author'),), publication_type=linked_type,
        external_ids=ExternalIds(doi='10.5555/preprint', pmid='42239170', arxiv='2201.12345', openalex='W1'),
        provenance=MetadataSource(provider='openalex', record_id='W1', retrieved_at=datetime.now(timezone.utc)))
    native_proof = ProviderWorkEvidence(publication_type='preprint',
        external_ids=ExternalIds(doi='10.5555/preprint', pmid='42239170', arxiv='2201.12345'),
        provenance=MetadataSource(provider='arxiv', record_id='2201.12345', retrieved_at=datetime.now(timezone.utc)),
        dates=(EvidenceDate(kind=EvidenceDateKind.PREPRINT, year=2022, month=1, day=2,
            first_version=True, publication_type='preprint'),))
    capabilities, paths, native_calls = [], [], []
    def response(request):
        paths.append(request)
        if request.url.path.endswith('efetch.fcgi'):
            return httpx.Response(200, text='<PubmedArticleSet>' + article(
                '42908400', '0006-341X', '10.1093/nar/gkag979') + '</PubmedArticleSet>')
        return httpx.Response(200, json={'result': {'uids': ['42908400'], '42908400': {'uid': '42908400'}}})
    class Pubmed(DiscoveryClient):
        def lookup_many(self, namespace, ids, **kwargs):
            capabilities.append(kwargs.get('capability'))
            return super().lookup_many(namespace, ids, **kwargs)
    class Helper(EmptyCompletion):
        def lookup_many(self, namespace, ids, **kwargs):
            if self.provider in {'arxiv', 'biorxiv', 'medrxiv'}:
                native_calls.append((self.provider, tuple(ids)))
            if self.provider == 'openalex':
                return {identity: (anchor, preprint, native_proof) for identity in ids}
            return super().lookup_many(namespace, ids, **kwargs)
        def lookup(self, namespace, identity):
            if self.provider in {'arxiv', 'biorxiv', 'medrxiv'}:
                native_calls.append((self.provider, identity))
            return ()
    def factory(provider, **kwargs):
        kwargs.pop('mailto', None)
        return Pubmed(provider, transport=httpx.MockTransport(response), interval=0, **kwargs) if provider == 'pubmed' else Helper(provider)
    def wos(*args, **kwargs):
        return IntegratedDiscovery((formal,), (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', (formal,), candidates=1),), 'complete')
    result = run_integrated(path, completion_factory=factory, wos_stage=wos)
    created, = load_workspace(tmp_path / 'workspace').papers
    assert capabilities == ['fetch'] and all(request.url.path.endswith('efetch.fcgi') for request in paths)
    assert [request.url.params['id'] for request in paths] == ['42908400']
    assert result.facts.created_papers == 1 and created.abstract == 'METHODS: Study abstract'
    assert created.title == 'Formal 10.1093/nar/gkag979' and list(created.authors) == ['WoS One', 'WoS Two']
    assert created.external_ids.doi == '10.1093/nar/gkag979' and created.external_ids.pmid == '42908400'
    assert created.external_ids.arxiv is None and created.external_ids.openalex is None
    assert created.first_public_at == '2022-01-02'
    assert native_calls == []


@pytest.mark.parametrize('provider', ['arxiv', 'biorxiv', 'medrxiv', 'europe_pmc'])
@pytest.mark.parametrize('cancel_native', [False, True])
def test_completion_http_activity_distinguishes_base_pages_and_blocked_native_verification(tmp_path, provider, cancel_native):
    import httpx
    from allfold.models import ProviderRecordRef
    from allfold.progress import ProgressStage
    from allfold.providers.supplemental import SupplementalClient
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    native_id = {'arxiv': '2201.12345', 'europe_pmc': 'PPR:PPR1'}.get(provider, '10.1101/123456')
    rows = tuple(record('wos', doi, related_ids=(ProviderRecordRef(provider=provider, record_id=native_id,
        relation='preprint'),)) for doi in ['10.5555/one', '10.5555/two'])
    entered, release, cancel = Event(), Event(), Event()
    events, calls, results, failures = [], [], [], []
    def response(request):
        calls.append(request)
        if request.url.host == 'api.crossref.org':
            if 'relation.type:' in request.url.params['filter']:
                return httpx.Response(200, json={'message': {'total-results': 0, 'items': []}})
            doi = '10.5555/one' if request.url.params['cursor'] == '*' else '10.5555/two'
            return httpx.Response(200, json={'message': {'total-results': 2, 'next-cursor': 'page-two',
                'items': [{'DOI': doi, 'type': 'journal-article', 'title': [doi]}]}})
        entered.set()
        assert release.wait(5), 'Test must release the native response'
        if provider == 'arxiv':
            return httpx.Response(200, text='''<feed xmlns="http://www.w3.org/2005/Atom"><entry>
                <id>http://arxiv.org/abs/2201.12345v1</id><title>Preprint</title>
                <published>2022-01-02T00:00:00Z</published></entry></feed>''')
        if provider == 'europe_pmc':
            assert 'SRC:PPR' in request.url.params['query']
            return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{
                'source': 'PPR', 'id': 'PPR1', 'title': 'Preprint', 'firstPublicationDate': '2022-01-02', 'versionNumber': 1}]}})
        assert request.url.path.startswith('/details/' + provider + '/')
        return httpx.Response(200, json={'messages': [{'status': 'ok'}], 'collection': [{
            'doi': native_id, 'server': provider, 'title': 'Preprint', 'date': '2022-01-02', 'version': '1'}]})
    def factory(name, **kwargs):
        if name not in {'crossref', provider}:
            return EmptyCompletion(name)
        kwargs.pop('api_key', None)
        return SupplementalClient(name, transport=httpx.MockTransport(response), interval=0, page_size=1, **kwargs)
    def wos(*args, **kwargs):
        return IntegratedDiscovery(rows, (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', rows, candidates=2),), 'complete')
    def execute():
        try:
            results.append(run_integrated(path, completion_factory=factory, wos_stage=wos,
                progress_callback=events.append, cancel_event=cancel))
        except Exception as error:
            failures.append(error)
    worker = Thread(target=execute)
    worker.start()
    try:
        assert entered.wait(3), 'Native version request must start'
        native = [event.activity for event in events if event.activity and event.activity.operation == 'native-version']
        assert native and native[-1].source == provider and native[-1].label == 'Native version verification'
        assert native[-1].detail == 'Request dispatched' and native[-1].current == 1
        base = [event.activity for event in events if event.activity and event.activity.operation == 'base-api'
            and event.activity.detail == 'Response received']
        assert len(base) == 3 and all(activity.label == 'Base API completion' for activity in base)
        assert sorted(activity.current for activity in base) == [1, 2, 3]
        assert not any(event.stage == ProgressStage.UPDATING_WORKSPACE for event in events)
        if cancel_native:
            cancel.set()
    finally:
        release.set()
        worker.join(5)
    assert not worker.is_alive() and not failures
    result, = results
    assert result.facts.created_papers == (0 if cancel_native else 2)
    assert result.facts.statistics['completion_requests'] == len(calls) == 4
    dispatches = [event.activity for event in events if event.activity and event.activity.detail == 'Request dispatched']
    responses = [event.activity for event in events if event.activity and event.activity.detail == 'Response received']
    assert len(dispatches) == 4 and len(responses) == (3 if cancel_native else 4)
    if not cancel_native:
        native_done = next(index for index, event in enumerate(events) if event.activity and
            event.activity.operation == 'native-version' and event.activity.detail == 'Response received')
        saved = next(index for index, event in enumerate(events) if event.stage == ProgressStage.UPDATING_WORKSPACE)
        assert native_done < saved


def test_work_response_extra_records_cannot_become_discovery_candidates(tmp_path):
    from test_integrated_run import evidence, client_for
    from allfold.application.workspace import load_workspace
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    class Helper(EmptyCompletion):
        def lookup_many(self,namespace,ids,**kwargs):
            if self.provider=='openalex':
                return DiscoveryResult('openalex',SourceScope('journal',''),'complete',
                    (evidence('openalex'),evidence('openalex',doi='10.5555/unrelated',pmid='99')))
            return super().lookup_many(namespace,ids,**kwargs)
    result=run_integrated(path,client_factory=client_for((evidence(),)),completion_factory=Helper)
    assert result.facts.created_papers==1
    assert {p.external_ids.doi for p in load_workspace(tmp_path/'workspace').papers}=={'10.5555/formal'}


def test_config_revocation_stops_all_later_helper_dispatch(tmp_path):
    from test_integrated_run import evidence, client_for
    from allfold.persistence.safe_write import ContentChangedError
    import pytest
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    dispatched=[]
    class Helper(EmptyCompletion):
        def lookup_many(self,namespace,ids,**kwargs):
            self.request_guard()
            dispatched.append(self.provider)
            if self.provider=='openalex':
                path.write_text(path.read_text()+'# changed during Work lookup\n')
                self.request_guard()
            return super().lookup_many(namespace,ids,**kwargs)
    with pytest.raises(ContentChangedError):
        run_integrated(path,client_factory=client_for((evidence(),)),completion_factory=Helper)
    assert dispatched==['openalex'] and not list((tmp_path/'workspace'/'Papers').glob('*.md'))


def test_selected_native_disconnect_revokes_http_but_waits_native_settlement(tmp_path):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    import httpx
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.preparation_coordinator import PreparationPhase
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.providers.integrated import DiscoveryClient
    from allfold.web.electron_bridge import ElectronDisconnected
    path,_,_,_=current_mapping_document(tmp_path)
    path.write_text(path.read_text()+'institution:\n  name: Test University\nenabled_providers: [wos,pubmed]\n')
    initial=load_user_state(path)
    compare_write_user_state(path,replace(initial.state,access_services=(*initial.state.access_services,
        AccessService.create('Web of Science','https://www.webofscience.com/'))),initial.revision)
    class Preparation:
        def start(self,*args,**kwargs): return self.snapshot()
        def snapshot(self): return SimpleNamespace(task_id='prep',generation=1,phase=PreparationPhase.COMPLETED,
            authorization_pending=False,message='Ready',waiting_for_user=False)
        def wos_handoff(self,*args): return 71
        def join(self): pass
    query_started, disconnected=Event(),Event()
    class Bridge:
        connected=True
        pending=Future()
        def execute(self,action,data,progress=None):
            assert action=='wos_query'
            self.progress=progress
            query_started.set()
            return self.pending
    bridge=Bridge();browser=BrowserTaskLock();slot=threading.Lock();slot.acquire()
    stage=WoSCoordinator(path,Preparation(),slot,bridge=bridge,browser_lock=browser)
    calls=[]
    def response(request):
        calls.append(request.url.path)
        assert query_started.wait(3)
        bridge.connected=False
        bridge.progress({'message':'Electron disconnected; waiting for application shutdown, no replay'})
        disconnected.set()
        return httpx.Response(200,json={'esearchresult':{'count':'0','idlist':[]}})
    def factory(provider,**kwargs):return DiscoveryClient(provider,transport=httpx.MockTransport(response),interval=0,**kwargs)
    results=[]
    worker=Thread(target=lambda:results.append(run_integrated(path,wos_stage=stage.execute_stage,
        client_factory=factory,completion_factory=EmptyCompletion,workflow_id='parent-run')))
    worker.start()
    assert disconnected.wait(3)
    assert worker.is_alive() and browser.owner is not None and slot.locked()
    assert not bridge.pending.done()  # Revocation cannot settle or replay native authority.
    bridge.pending.set_exception(ElectronDisconnected('Controlled disconnect'))
    worker.join(3)
    assert not worker.is_alive() and browser.owner is None and slot.locked()
    assert results[0].outcome.value=='CANCELLED' and calls==['/entrez/eutils/esearch.fcgi']
    assert results[0].facts.created_papers==0
    slot.release()


def test_parent_shutdown_keeps_slot_until_run_worker_settles(tmp_path,monkeypatch):
    from allfold.application.coordinators.run_coordinator import RunCoordinator
    from allfold.application.monitor import RunResult,RunOutcome
    from allfold.application.run_state import RunProvider,RunFacts
    path,_=config(tmp_path)
    entered,release=Event(),Event()
    events=[]
    def monitor(*args,**kwargs):
        entered.set()
        assert release.wait(3)
        assert kwargs['cancel_event'].is_set()
        events.append('settled')
        return RunResult(RunProvider.INTEGRATED,None,(),(),RunOutcome.CANCELLED,RunFacts())
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor',monitor)
    import threading
    slot=threading.Lock();coordinator=RunCoordinator(path,run_slot=slot)
    coordinator.start();assert entered.wait(3)
    coordinator.shutdown()
    joining=Thread(target=coordinator.join);joining.start()
    assert slot.locked() and joining.is_alive()
    release.set();joining.join(3)
    assert events==['settled'] and not slot.locked() and not coordinator.snapshot().worker_alive


def test_exact_work_location_with_preprint_top_pmid_is_only_association(tmp_path):
    import httpx
    from allfold.providers.integrated import DiscoveryClient
    from test_integrated_run import evidence,client_for
    from allfold.application.workspace import load_workspace
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    raw={'id':'https://openalex.org/W7223175244','doi':'https://doi.org/10.1101/2026.04.01.123456',
        'type':'preprint','title':'Merged preprint title','ids':{'pmid':'https://pubmed.ncbi.nlm.nih.gov/42239170/'},
        'locations_count':1,'locations':[{'landing_page_url':'https://doi.org/10.1093/nar/gkag979',
            'source':{'id':'https://openalex.org/S1'}}]}
    calls=[]
    def response(request):
        calls.append(request)
        return httpx.Response(200,json={'results':[raw],'meta':{'count':1}})
    def helper(provider,**kwargs):
        if provider=='openalex':
            kwargs.pop('mailto',None)
            return DiscoveryClient(provider,transport=httpx.MockTransport(response),interval=0,**kwargs)
        return EmptyCompletion(provider,**kwargs)
    formal=evidence(doi='10.1093/nar/gkag979',pmid='42908400')
    result=run_integrated(path,client_factory=client_for((formal,)),completion_factory=helper)
    paper,=load_workspace(tmp_path/'workspace').papers
    assert result.facts.created_papers==1 and len(calls)==1
    assert paper.external_ids.doi=='10.1093/nar/gkag979' and paper.external_ids.pmid=='42908400'
    assert paper.external_ids.openalex is None and paper.title=='Native hit'
    assert result.facts.statistics['completion_requests']==0  # Work cache reuse is not another HTTP request.


def test_completion_counts_physical_shared_batch_requests_and_preserves_notes(tmp_path):
    import httpx
    from allfold.providers.supplemental import SupplementalClient
    from allfold.models import EvidenceDate,EvidenceDateKind
    from test_integrated_run import evidence,client_for
    from allfold.application.workspace import load_workspace
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    rows=(evidence(doi='10.5555/a',pmid='1'),evidence(doi='10.5555/b',pmid='2'))
    calls=[]
    def response(request):
        calls.append(request)
        filters=request.url.params['filter']
        items=[] if 'relation.type:' in filters else [{'DOI':doi,'title':['Crossref title'],
            'accepted':{'date-parts':[[2025,12,2]]},'published-online':{'date-parts':[[2026,1,4]]}}
            for doi in ('10.5555/a','10.5555/b')]
        return httpx.Response(200,json={'message':{'items':items,'total-results':len(items)}})
    def helper(provider,**kwargs):
        if provider=='crossref':
            kwargs.pop('api_key',None)
            return SupplementalClient(provider,transport=httpx.MockTransport(response),interval=0,**kwargs)
        return EmptyCompletion(provider,**kwargs)
    result=run_integrated(path,client_factory=client_for(rows),completion_factory=helper)
    assert result.facts.created_papers==2 and result.facts.statistics['completion_targets']==2
    assert result.facts.statistics['completion_requests']==len(calls)==2
    assert result.facts.statistics['completion_date_facts_added']==4
    assert all(paper.title=='Native hit' for paper in load_workspace(tmp_path/'workspace').papers)


def test_formal_metadata_priority_and_relation_notes_are_stable():
    from allfold.canonicalize import completion_metadata
    from test_integrated_run import evidence
    from allfold.models import Author
    rows=tuple(evidence(provider,pmid='42',title=provider+' title').model_copy(update={
        'authors':(Author(name=provider+' author'),),
        'provenance':evidence(provider).provenance.model_copy(update={'role':'supplement' if provider=='pubmed' else 'discovery'})})
        for provider in ('openalex','pubmed'))
    for records in (rows,tuple(reversed(rows))):
        paper=completion_metadata(records)
        assert paper.metadata.title=='pubmed title'
        assert [author.name for author in paper.authors]==['pubmed author']
    notes=tuple(evidence('europe_pmc').model_copy(update={'provenance':evidence('europe_pmc').provenance.model_copy(
        update={'note':note})}) for note in ('Matched by title and first author','Verified source','Matched by title and first author'))
    for records in (notes,tuple(reversed(notes))):
        source,=completion_metadata(records).sources
        assert source.note=='Matched by title and first author; Verified source'
