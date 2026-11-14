from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, Thread

import pytest

from allfold.application.integrated_run import IntegratedDiscovery
from integrated_run_helpers import run_integrated
from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
from allfold.providers.integrated import DiscoveryResult, SourceScope
from test_integrated_run import config
from integrated_run_helpers import EmptyLookup
from library_helpers import capture_papers, read_papers, read_paper


def record(provider, doi, **fields):
    return ProviderWorkEvidence(title='Formal '+doi, abstract='Abstract', authors=({'name':'Author'},), journal='Test',
        publication_type='journal', monitor_journal_issns=('0006-341X',), external_ids=ExternalIds(doi=doi),
        provenance=MetadataSource(provider=provider, record_id=doi, retrieved_at=datetime.now(timezone.utc)), **fields)


@pytest.mark.parametrize('outcome', ['complete', 'empty', 'partial', 'exception'])
def test_finished_http_sources_report_outcome_while_wos_waits(tmp_path, outcome):
    from concurrent.futures import ThreadPoolExecutor
    from test_integrated_run import evidence
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos,pubmed,openalex]\n')
    release_wos, wos_started = Event(), Event()
    settled = {provider: Event() for provider in ('pubmed', 'openalex')}
    events = []
    expected = {'pubmed': 'failed' if outcome == 'exception' else outcome, 'openalex': 'empty'}

    def progress(event):
        events.append(event)
        activity = event.activity
        if activity and activity.source in settled and activity.label.endswith(': ' + expected[activity.source]):
            settled[activity.source].set()

    class Client(EmptyLookup):
        def discover_many(self, scopes, *args, **kwargs):
            if self.provider == 'pubmed' and outcome == 'exception':
                raise OSError('Discovery transport failed')
            status = expected[self.provider]
            rows = (evidence(doi=None),) if status in {'complete', 'partial'} else ()
            return tuple(DiscoveryResult(self.provider, source, status, rows,
                limitations=('Incomplete source',) if status == 'partial' else (), candidates=len(rows)) for source in scopes)

    def wos(*args, **kwargs):
        wos_started.set()
        assert release_wos.wait(5)
        return IntegratedDiscovery((), (), 'empty')

    with ThreadPoolExecutor(max_workers=1) as worker:
        run = worker.submit(run_integrated, path, client_factory=Client, lookup_factory=EmptyLookup,
            wos_stage=wos, progress_callback=progress)
        try:
            assert wos_started.wait(2)
            assert all(signal.wait(1) for signal in settled.values()), 'Finished HTTP sources still appear active while WoS waits'
            assert not run.done()
            for provider, status in expected.items():
                terminal = [event.activity for event in events if event.activity and event.activity.source == provider][-1]
                assert terminal.label.endswith(': ' + status)
                assert terminal.current == (1 if provider == 'pubmed' and outcome in {'complete', 'partial'} else 0)
        finally:
            release_wos.set()
        run.result(timeout=5)


def test_discovery_and_work_overlap_then_tail_drains_before_identity_handoff(tmp_path):
    path, settings=config(tmp_path, ('wos','pubmed','openalex'))
    path.write_text(path.read_text()+'enabled_providers: [wos,pubmed,openalex]\n')
    entered={name:Event() for name in ('wos','pubmed','openalex')}
    located=Event()
    batches=[]
    class Client(EmptyLookup):
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
    result=run_integrated(path,loaded_config=settings,client_factory=Client,lookup_factory=EmptyLookup,wos_stage=wos)
    assert result.facts.created_papers==2
    assert [identity for batch in batches for identity in batch]==['10.5555/shared','10.5555/tail']
    assert result.facts.statistics['integrated_deduplicated']==2
    assert result.facts.statistics['identity_targets']==2
    assert result.facts.statistics['collection_admitted']==2


def test_work_response_extra_records_cannot_become_discovery_candidates(tmp_path):
    from test_integrated_run import evidence, client_for
    from allfold.application.workspace import load_workspace
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    class Helper(EmptyLookup):
        def lookup_many(self,namespace,ids,**kwargs):
            if self.provider=='openalex':
                return DiscoveryResult('openalex',SourceScope('journal',''),'complete',
                    (evidence('openalex'),evidence('openalex',doi='10.5555/unrelated',pmid='99')))
            return super().lookup_many(namespace,ids,**kwargs)
    result=run_integrated(path,client_factory=client_for((evidence(),)),lookup_factory=Helper)
    assert result.facts.created_papers==1
    assert {p.external_ids.doi for p in load_workspace(tmp_path/'workspace').papers}=={'10.5555/formal'}


def test_config_revocation_stops_all_later_helper_dispatch(tmp_path):
    from test_integrated_run import evidence, client_for
    from allfold.persistence.safe_write import ContentChangedError
    import pytest
    path,_=config(tmp_path);path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    dispatched=[]
    class Helper(EmptyLookup):
        def lookup_many(self,namespace,ids,**kwargs):
            self.request_guard()
            dispatched.append(self.provider)
            if self.provider=='openalex':
                path.write_text(path.read_text()+'# changed during Work lookup\n')
                self.request_guard()
            return super().lookup_many(namespace,ids,**kwargs)
    with pytest.raises(ContentChangedError):
        run_integrated(path,client_factory=client_for((evidence(),)),lookup_factory=Helper)
    assert dispatched==['openalex'] and not read_papers(tmp_path/'workspace')


def test_selected_native_disconnect_revokes_http_but_waits_native_settlement(tmp_path):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    import httpx
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.providers.integrated import DiscoveryClient
    from allfold.web.electron_bridge import ElectronDisconnected
    path,_,_,_=current_mapping_document(tmp_path)
    path.write_text(path.read_text()+'institution:\n  name: Test University\nenabled_providers: [wos,pubmed]\n')
    initial=load_user_state(path)
    compare_write_user_state(path,replace(initial.state,access_services=(*initial.state.access_services,
        AccessService.create('Web of Science','https://www.webofscience.com/'))),initial.revision)
    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return 71

        def prepared_authority(self, saved, service_id):
            return PreparedService(self.prepared_page(saved, service_id), 'd' * 64)

    query_started, disconnected=Event(),Event()
    class Bridge:
        connected=True
        pending=Future()
        def execute(self,action,data,progress=None):
            if action == 'release_workflow_pages':
                done = Future(); done.set_result({'ok': True}); return done
            assert action=='wos_query'
            self.progress=progress
            query_started.set()
            return self.pending
    bridge=Bridge();browser=BrowserTaskLock();slot=threading.Lock();slot.acquire()
    stage=WoSCoordinator(path,Login(),slot,bridge=bridge,browser_lock=browser)
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
        client_factory=factory,lookup_factory=EmptyLookup,workflow_id='parent-run')))
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


@pytest.mark.parametrize('revocation', ['disconnect', 'configuration'])
def test_work_guard_settles_native_before_parent_cancel_or_authority_error(tmp_path, monkeypatch, revocation):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    import httpx
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.application.coordinators.run_coordinator import RunCoordinator
    from allfold.providers.integrated import DiscoveryClient
    from allfold.web.electron_bridge import ElectronDisconnected
    from allfold.diagnostics import DiagnosticStore
    from test_pubmed_discovery import article
    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + 'institution:\n  name: Test University\nenabled_providers: [wos,pubmed]\n')
    initial = load_user_state(path)
    compare_write_user_state(path, replace(initial.state, access_services=(*initial.state.access_services,
        AccessService.create('Web of Science', 'https://www.webofscience.com/'))), initial.revision)
    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return 71

        def prepared_authority(self, saved, service_id):
            return PreparedService(self.prepared_page(saved, service_id), 'd' * 64)

    query_started, revoked, guard_entered = Event(), Event(), Event()
    class Bridge:
        connected = True
        pending = Future()
        def execute(self, action, data, progress=None):
            if action == 'release_workflow_pages':
                done = Future(); done.set_result({'ok': True}); return done
            assert action == 'wos_query'
            query_started.set()
            return self.pending
    bridge, browser, slot = Bridge(), BrowserTaskLock(), threading.Lock()
    store = DiagnosticStore(path, root=tmp_path / 'logs')
    native = WoSCoordinator(path, Login(), slot, bridge=bridge, browser_lock=browser, diagnostics=store)
    authority_checks = []
    check_authority = native.check_dispatch_authority
    def check(cancel):
        before = cancel.is_set()
        check_authority(cancel)
        if revoked.is_set():
            authority_checks.append((cancel, before, cancel.is_set()))
            guard_entered.set()
    native.check_dispatch_authority = check
    calls, streamed = [], []
    def response(request):
        assert not revoked.is_set(), 'No HTTP may dispatch after authority revocation'
        calls.append(request.url.path)
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': ['41'],
                'webenv': 'fixture-history', 'querykey': '1'}})
        assert request.url.path.endswith('efetch.fcgi')
        return httpx.Response(200, text='<PubmedArticleSet>' + article('41', '0006-341X', '10.5555/formal') + '</PubmedArticleSet>')
    class Discovery(DiscoveryClient):
        def discover_many(self, scopes, *args, records_callback=None):
            def verified(rows):
                assert query_started.wait(3)
                streamed.extend(row.external_ids.doi for row in rows)
                if revocation == 'disconnect':
                    bridge.connected = False
                else:
                    path.write_text(path.read_text() + '# changed before Work guard\n')
                revoked.set()
                records_callback(rows)
            return super().discover_many(scopes, *args, records_callback=verified)
    def factory(provider, **kwargs):
        return Discovery(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    def monitor(config_path, **kwargs):
        kwargs.pop('provider')
        return run_integrated(config_path, client_factory=factory, lookup_factory=EmptyLookup, **kwargs)
    monkeypatch.setattr('allfold.application.coordinators.run_coordinator.run_monitor', monitor)
    coordinator = RunCoordinator(path, run_slot=slot, diagnostics=store)
    coordinator.wos_stage = native
    coordinator.start()
    try:
        assert guard_entered.wait(3)
        assert authority_checks[0][0].wait(3)
        assert authority_checks[0][1:] == ((False, True) if revocation == 'disconnect' else (False, False))
        assert streamed == ['10.5555/formal'] and len(calls) == 2
        assert coordinator.snapshot().worker_alive and slot.locked() and browser.owner is not None
        assert not bridge.pending.done()
        pending_history = store.history()['records']
        assert len(pending_history) == 1 and pending_history[0]['outcome'] == 'running'
    finally:
        if not bridge.pending.done():
            bridge.pending.set_exception(ElectronDisconnected('Controlled native settlement'))
        coordinator.join()
    settled = coordinator.snapshot()
    assert not settled.worker_alive and not slot.locked() and browser.owner is None
    if revocation == 'disconnect':
        assert settled.unexpected_error is None
        assert settled.result.outcome.value == 'CANCELLED' and settled.result.facts.created_papers == 0
        assert settled.result.facts.statistics['integrated_candidates'] == 1
    else:
        assert settled.result is None and settled.unexpected_error.category == 'ContentChangedError'
    history = store.history()['records']
    assert len(history) == 1 and history[0]['outcome'] == ('cancelled' if revocation == 'disconnect' else 'failed')
    assert not read_papers(tmp_path / 'workspace')
    assert not (tmp_path / 'workspace' / '.allfold' / 'last-integrated-run.json').exists()
    assert not (tmp_path / 'workspace' / '.allfold' / 'last-wos-run.json').exists()


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
        return EmptyLookup(provider,**kwargs)
    formal=evidence(doi='10.1093/nar/gkag979',pmid='42908400')
    result=run_integrated(path,client_factory=client_for((formal,)),lookup_factory=helper)
    paper,=load_workspace(tmp_path/'workspace').papers
    assert result.facts.created_papers==1 and len(calls)==1
    assert paper.external_ids.doi=='10.1093/nar/gkag979' and paper.external_ids.pmid=='42908400'
    assert paper.external_ids.openalex is None and paper.title=='Native hit'
    assert result.facts.statistics['identity_requests']==0  # Work cache reuse is not another HTTP request.


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


@pytest.mark.parametrize('failed_path', [None, 'esearch.fcgi', 'esummary.fcgi'])
def test_run_resolves_formal_dois_once_and_persists_pubmed_history(tmp_path, failed_path):
    import httpx
    from allfold.application.workspace import load_workspace
    from allfold.providers.integrated import DiscoveryClient

    found = '10.1093/bioinformatics/btag793'
    unmatched = '10.1093/jrsssb/qkag130'
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    rows = (record('wos', found), record('pubmed', found), record('wos', unmatched))
    calls = []

    def handler(request):
        calls.append(request)
        if failed_path and request.url.path.endswith(failed_path):
            assert not read_papers(tmp_path / 'workspace')
            if sum(call.url.path.endswith(failed_path) for call in calls) <= 3:
                raise httpx.ReadTimeout('fixture timeout')
        if request.url.path.endswith('esearch.fcgi'):
            assert request.url.params['term'] == f'"{found}"[aid] OR "{unmatched}"[aid]'
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': ['42925410']}})
        assert request.url.path.endswith('esummary.fcgi')
        assert request.url.params['id'] == '42925410'
        return httpx.Response(200, json={'result': {'uids': ['42925410'], '42925410': {
            'uid': '42925410', 'articleids': [{'idtype': 'doi', 'value': found}],
            'history': [{'pubstatus': 'received', 'date': '2026/01/06'}]}}})

    def factory(provider, *, mailto='', **kwargs):
        if provider == 'pubmed':
            return DiscoveryClient(provider, transport=httpx.MockTransport(handler), interval=0, sleep=lambda _: None, **kwargs)
        return EmptyLookup(provider)

    def wos(*args, **kwargs):
        return IntegratedDiscovery(rows, (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', rows, candidates=len(rows)),), 'complete')

    run = run_integrated(path, wos_stage=wos, lookup_factory=factory)
    papers = {paper.external_ids.doi: paper for paper in load_workspace(tmp_path / 'workspace').papers}
    assert run.facts.created_papers == 2 and set(papers) == {found, unmatched}
    assert papers[found].external_ids.pmid == '42925410'
    assert papers[found].ordinary_dates == ('2026-01-06',)
    assert papers[unmatched].external_ids.model_dump().get('pmid') is None
    assert len(calls) == run.facts.statistics['identity_requests'] == (5 if failed_path else 2)
    assert run.facts.statistics['pmid_resolution_no_match'] == 1

    calls.clear()
    rerun = run_integrated(path, wos_stage=wos, lookup_factory=factory)
    assert rerun.facts.created_papers == 0 and rerun.facts.existing_papers == 2
    assert calls == []


def test_resolved_pmid_counts_existing_doi_free_paper_for_discovery_source(tmp_path):
    import httpx

    from allfold.canonicalize import canonicalize_records
    from allfold.providers.integrated import DiscoveryClient
    from test_integrated_run import evidence

    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    workspace = tmp_path / 'workspace'
    saved, = capture_papers(canonicalize_records((evidence(doi=None, pmid='42'),)).papers, workspace)
    original = saved
    formal = record('wos', '10.5555/formal')

    def handler(request):
        if request.url.path.endswith('esearch.fcgi'):
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': ['42']}})
        assert request.url.path.endswith('esummary.fcgi')
        return httpx.Response(200, json={'result': {'uids': ['42'], '42': {
            'uid': '42', 'articleids': [{'idtype': 'doi', 'value': '10.5555/formal'}]}}})

    def factory(provider, *, mailto='', **kwargs):
        if provider == 'pubmed':
            return DiscoveryClient(provider, transport=httpx.MockTransport(handler), interval=0, **kwargs)
        return EmptyLookup(provider)

    def wos(*args, **kwargs):
        return IntegratedDiscovery((formal,), (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', (formal,), candidates=1),), 'complete')

    run = run_integrated(path, wos_stage=wos, lookup_factory=factory)
    assert run.facts.created_papers == 0 and run.facts.existing_papers == 1
    matched=read_paper(workspace, saved.id)
    assert matched.id == original.id and matched.metadata.title == original.metadata.title
    assert matched.collection_status in {'completed','failed'}
    assert ('doi','10.5555/formal') in {(item.namespace,item.value) for item in matched.identities}
    assert run.facts.details['provider_runs'][0]['existing'] == 1
    assert run.facts.details['provider_totals'][0]['existing'] == 1


@pytest.mark.parametrize('known_pmid', [False, True])
def test_europe_pmc_conflicting_formal_doi_cannot_enrich_pmid_owner(tmp_path, known_pmid):
    import httpx

    from allfold.application.workspace import load_workspace
    from allfold.models import EvidenceDate, EvidenceDateKind
    from allfold.providers.integrated import DiscoveryClient
    from allfold.providers.supplemental import SupplementalClient

    doi, pmid = '10.5555/formal', '42'
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    formal = record('pubmed' if known_pmid else 'wos', doi)
    if known_pmid:
        formal = formal.model_copy(update={'external_ids': ExternalIds(doi=doi, pmid=pmid),
            'dates': (EvidenceDate(kind=EvidenceDateKind.RECEIVED, year=2026, month=1, day=6),)})
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith('esearch.fcgi'):
            assert not known_pmid
            return httpx.Response(200, json={'esearchresult': {'count': '1', 'idlist': [pmid]}})
        if request.url.path.endswith('esummary.fcgi'):
            return httpx.Response(200, json={'result': {'uids': [pmid], pmid: {
                'uid': pmid, 'articleids': [{'idtype': 'doi', 'value': doi}],
                'history': [{'pubstatus': 'received', 'date': '2026/01/06'}]}}})
        if 'SRC:PPR' in request.url.params['query']:
            return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{
                'source': 'PPR', 'id': 'PPR1', 'title': 'Unrelated preprint', 'versionNumber': '1',
                'firstPublicationDate': '2024-03-02'}]}})
        assert request.url.params['query'] == 'SRC:MED AND HAS_PREPRINT:Y AND (EXT_ID:42)'
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{
            'source': 'MED', 'id': pmid, 'title': 'Other journal article', 'doi': '10.5555/unrelated',
            'firstPublicationDate': '2025-02-03', 'commentCorrectionList': {'commentCorrection': [
                {'type': 'Preprint in', 'source': 'PPR', 'id': 'PPR1'}]}}]}})

    def factory(provider, **kwargs):
        if provider == 'pubmed':
            kwargs.pop('mailto')
            return DiscoveryClient(provider, interval=0, transport=httpx.MockTransport(handler), **kwargs)
        if provider == 'europe_pmc':
            kwargs.pop('api_key')
            return SupplementalClient(provider, interval=0, transport=httpx.MockTransport(handler), **kwargs)
        return EmptyLookup(provider)

    def wos(*args, **kwargs):
        return IntegratedDiscovery((formal,), (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', (formal,), candidates=1),), 'complete')

    run = run_integrated(path, wos_stage=wos, lookup_factory=factory)
    paper, = load_workspace(tmp_path / 'workspace').papers
    assert run.facts.created_papers == 1
    assert paper.external_ids.doi == doi and paper.external_ids.pmid == pmid
    assert paper.first_public_at is None
    assert paper.ordinary_dates == ('2026-01-06',)
    assert not any(source.provider == 'europe_pmc' for source in paper.sources)
    assert not any('SRC:PPR' in request.url.params.get('query', '') for request in calls)
    assert paper.record.collection_status == 'failed'
    assert any(branch.name == 'necessary-api' and branch.state == 'failed' for branch in paper.record.collection.branches)


@pytest.mark.parametrize('resolution', ['matched', 'unmatched', 'saved_doi_free'])
def test_wos_reported_pmid_needs_exact_pubmed_confirmation_for_a_formal_doi(tmp_path, resolution):
    import httpx

    from allfold.application.workspace import load_workspace
    from allfold.canonicalize import canonicalize_records
    from allfold.providers.integrated import DiscoveryClient
    from allfold.providers.supplemental import SupplementalClient
    from test_integrated_run import evidence

    doi, reported_pmid, verified_pmid = '10.5555/formal', '42', '43'
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [wos]\n')
    formal = record('wos', doi).model_copy(update={'external_ids': ExternalIds(doi=doi, pmid=reported_pmid)})
    if resolution == 'saved_doi_free':
        capture_papers(canonicalize_records((evidence(doi=None, pmid=reported_pmid),)).papers, tmp_path / 'workspace')
    calls = []

    def handler(request):
        endpoint = request.url.path.rsplit('/', 1)[-1]
        calls.append(endpoint)
        if endpoint == 'esearch.fcgi':
            assert request.url.params['term'] == f'"{doi}"[aid]'
            matches = [verified_pmid] if resolution == 'matched' else []
            return httpx.Response(200, json={'esearchresult': {'count': str(len(matches)), 'idlist': matches}})
        if endpoint == 'search':
            assert request.url.params['query'] == 'SRC:MED AND HAS_PREPRINT:Y AND (EXT_ID:43)'
            return httpx.Response(200, json={'hitCount': 0, 'resultList': {'result': []}})
        assert endpoint == 'esummary.fcgi'
        assert request.url.params['id'] == verified_pmid
        return httpx.Response(200, json={'result': {'uids': [verified_pmid], verified_pmid: {
            'uid': verified_pmid, 'articleids': [{'idtype': 'doi', 'value': doi}]}}})

    def factory(provider, **kwargs):
        if provider == 'pubmed':
            kwargs.pop('mailto')
            return DiscoveryClient(provider, interval=0, transport=httpx.MockTransport(handler), **kwargs)
        if provider == 'europe_pmc':
            kwargs.pop('api_key')
            return SupplementalClient(provider, interval=0, transport=httpx.MockTransport(handler), **kwargs)
        return EmptyLookup(provider)

    def wos(*args, **kwargs):
        return IntegratedDiscovery((formal,), (DiscoveryResult('wos', SourceScope('journal', 'Test'),
            'complete', (formal,), candidates=1),), 'complete')

    run = run_integrated(path, wos_stage=wos, lookup_factory=factory)
    paper, = load_workspace(tmp_path / 'workspace').papers
    if resolution == 'saved_doi_free':
        assert run.facts.created_papers == 0
        assert run.facts.statistics['conflicts'] == 1
        assert paper.external_ids.model_dump().get('pmid') == reported_pmid
    else:
        assert run.facts.created_papers == run.facts.details['provider_totals'][0]['created'] == 1
        assert paper.external_ids.doi == doi
        assert paper.external_ids.model_dump().get('pmid') == (verified_pmid if resolution == 'matched' else None)
    assert set(calls) == ({'esearch.fcgi', 'esummary.fcgi', 'search'} if resolution == 'matched' else {'esearch.fcgi'})
