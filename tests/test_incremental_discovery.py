from datetime import date
import httpx
import pytest
from library_helpers import capture_papers, read_papers, read_paper

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope






@pytest.mark.parametrize('invalid_batch', [None,'count','path','duplicate_ut'])
def test_native_stage_reuses_parent_slot_and_retains_first_batch_after_later_failure(tmp_path,invalid_batch):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    from dataclasses import replace
    from pathlib import Path
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService, load_config
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from integrated_run_helpers import run_integrated
    from allfold.application.run_commit import capture_run_workspace
    from allfold.diagnostics import DiagnosticStore
    from test_wos import tagged, record
    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + 'institution:\n  name: Test University\nenabled_providers: [wos]\n')
    initial = load_user_state(path)
    compare_write_user_state(path, replace(initial.state, access_services=(*initial.state.access_services,
        AccessService.create('Web of Science', 'https://www.webofscience.com/'))), initial.revision)
    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return 71

        def prepared_authority(self, saved, service_id):
            return PreparedService(self.prepared_page(saved, service_id), 'd' * 64)

    calls = []
    class Bridge:
        connected = True
        def execute(self, action, data, progress=None):
            calls.append(action)
            assert data['task_id'] == data['workflow_id'] == 'parent-run'
            future = Future()
            if action == 'release_workflow_pages': value = {'ok': True}
            elif action == 'wos_query': value = dict(page_id=71,total=3 if invalid_batch=='duplicate_ut' else 2,batch_limit=2 if invalid_batch=='duplicate_ut' else 1)
            elif data['first'] == 1:
                rows=[record(doi='10.5555/safe',ut='WOS:1')]
                if invalid_batch in {'count','duplicate_ut'}: rows.append(record(doi='10.5555/other',ut='WOS:1'))
                Path(data['filename']).write_text(tagged(rows))
                value = dict(filename='unissued' if invalid_batch=='path' else data['filename'])
            else:
                future.set_exception(ValueError('Second export failed'))
                return future
            future.set_result(value)
            return future
    slot, browser = threading.Lock(), BrowserTaskLock()
    slot.acquire()
    store = DiagnosticStore(path, root=tmp_path / 'logs')
    stage = WoSCoordinator(path, Login(), slot, bridge=Bridge(), browser_lock=browser, diagnostics=store)
    native_batches=[]
    def execute(snapshot,**kwargs):
        callback=kwargs.pop('records_callback')
        def verified(records): native_batches.append(records);callback(records)
        return stage.execute_stage(snapshot,records_callback=verified,**kwargs)
    with capture_run_workspace(path) as snapshot:
        result = run_integrated(path,workspace_snapshot=snapshot,wos_stage=execute,workflow_id='parent-run')
    assert slot.locked() and browser.owner is None
    slot.release()
    assert result.facts.created_papers == (0 if invalid_batch else 1)
    assert result.facts.details['discovery_status'] == ('failed' if invalid_batch else 'partial')
    assert len(native_batches)==(0 if invalid_batch else 1)
    assert len(result.facts.details['batches']) == (1 if invalid_batch else 2)
    assert len(store.history()['records']) == 0  # only the parent coordinator owns Run history
    workspace = load_config(path).output_dir
    assert (workspace / '.allfold' / 'last-integrated-run.json').exists()
    assert not (workspace / '.allfold' / 'last-wos-run.json').exists()


def test_openalex_batches_all_unknown_ids_maps_unordered_pages_and_reports_missing():
    identifiers = [f'W{n}' for n in range(1, 206)]
    requested = []
    def handler(request):
        values = request.url.params['filter'].removeprefix('openalex:').split('|')
        requested.extend(values)
        assert len(values) <= 100
        rows = [{'id': f'https://openalex.org/{value}', 'title': f'Title {value}', 'type': 'article'}
                for value in reversed(values) if value != 'W203']
        # An unrelated record must not be associated by position.
        rows.append({'id': 'https://openalex.org/W9999', 'title': 'Wrong identity'})
        return httpx.Response(200, json={'meta': {'count': len(rows), 'next_cursor': None}, 'results': rows})
    with DiscoveryClient('openalex', transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.lookup_many('openalex', identifiers)
    assert requested == identifiers
    assert len(result.records) == 204
    assert {record.external_ids.openalex.rsplit('/', 1)[-1] for record in result.records} == set(identifiers) - {'W203'}
    assert result.status == 'partial'
    assert client.cached_lookup('openalex','W203') == ()
    assert 'OpenAlex exact batch returned an unrequested Work' in result.limitations


def test_openalex_shortened_detail_lists_use_exact_singleton_and_keep_whole_authors():
    calls = []
    def handler(request):
        calls.append(request.url.path)
        raw = {'id': 'https://openalex.org/W1', 'title': 'Complete byline', 'authors_count': 101,
            'authorships': [{'author': {'display_name': f'Author {n}'}} for n in range(101 if request.url.path.endswith('/W1') else 100)],
            'locations_count': 0, 'locations': []}
        return httpx.Response(200, json=raw if request.url.path.endswith('/W1') else {'meta': {'count': 1}, 'results': [raw]})
    with DiscoveryClient('openalex', transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.lookup_many('openalex', ['W1'])
    assert calls == ['/works', '/works/W1']
    assert len(result.records[0].authors) == 101 and not result.limitations






def test_direct_identifiers_matching_two_saved_owners_are_reported_and_skipped(tmp_path):
    from test_integrated_run import config
    from integrated_run_helpers import run_integrated
    path, _ = config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [pubmed]\n')
    from test_integrated_run import evidence, client_for
    ambiguous = False
    def rows():
        return (evidence(doi='10.5555/1',pmid='2'),) if ambiguous else tuple(
            evidence(doi=f'10.5555/{n}',pmid=str(n)) for n in (1,2))
    factory=client_for(rows)
    assert run_integrated(path, client_factory=factory).facts.created_papers == 2
    before = read_papers(tmp_path/'workspace')
    ambiguous = True
    result = run_integrated(path, client_factory=factory)
    assert result.facts.created_papers == result.facts.existing_papers == 0
    assert any('different Papers' in issue.message for issue in result.errors)
    assert result.facts.statistics['conflicts'] == 1
    assert all(str(p.id) in result.errors[0].message for p in before)
    assert read_papers(tmp_path/'workspace') == before


def test_unified_history_retains_sanitized_source_and_native_hints(tmp_path):
    from datetime import datetime, timezone
    from allfold.application.history import finish_run
    from allfold.application.monitor import RunResult, RunOutcome
    from allfold.application.run_state import RunProvider, RunFacts
    from allfold.diagnostics import DiagnosticStore
    path = tmp_path/'monitor.yaml'
    path.write_text('')
    store = DiagnosticStore(path, root=tmp_path/'logs')
    store.begin('run', 'run-history', provider='integrated')
    result = RunResult(RunProvider.INTEGRATED, None, (), (), RunOutcome.COMPLETED_WITH_WARNINGS,
        RunFacts(finished_at=datetime.now(timezone.utc), created_papers=1, existing_papers=2,
            statistics={'integrated_candidates':3, 'unmatched_journal_records':1},
            details={'discovery_status':'partial', 'provider_runs':[
                {'provider':'wos','source':'PRIVATE_JOURNAL','status':'partial','candidates':2,'created':0,'existing':2,'limitations':['PRIVATE_FAILURE']},
                {'provider':'openalex','source':'PRIVATE_JOURNAL','status':'complete','candidates':1,'created':1,'existing':0,'limitations':[]}],
                'batches':[{'first':1,'last':2,'complete':True},{'first':3,'last':4,'complete':False}], 'date_warnings':[{'PD':'PRIVATE_DATE'}]}))
    finish_run(store, 'run-history', result, provider='integrated')
    item, = store.history()['records']
    assert item['details']['run_sources'][0] == {'provider':'wos','status':'partial','candidates':2,'created':0,'existing':2,'problems':1}
    assert item['details']['wos_checks'] == {'batches':2,'completed_batches':1,'journal_hints':0,'date_hints':1,'unmatched_records':1}
    assert 'PRIVATE_' not in str(item)


import pytest

@pytest.mark.parametrize('cancelled', [False, True])
def test_wos_failure_allows_selected_apis_but_parent_cancel_stops_them(tmp_path, cancelled):
    from threading import Event
    from test_integrated_run import config
    from allfold.application.integrated_run import IntegratedDiscovery
    from integrated_run_helpers import run_integrated
    from allfold.providers.integrated import DiscoveryResult
    path, _ = config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [wos, pubmed]\n')
    cancel = Event()
    calls = []
    def stage(snapshot, **kwargs):
        if cancelled: cancel.set()
        result = DiscoveryResult('wos', SourceScope('journal','Test'), 'cancelled' if cancelled else 'failed', limitations=('Native export could not be verified',))
        return IntegratedDiscovery((), (result,), result.status)
    from test_integrated_run import evidence, client_for
    class Client(client_for((evidence(),),calls=calls)):
        def discover_many(self,*args,**kwargs):
            if cancel.is_set():
                return ()
            return super().discover_many(*args,**kwargs)
    factory=Client
    result = run_integrated(path, wos_stage=stage, client_factory=factory, cancel_event=cancel)
    assert not cancelled or result.facts.created_papers == 0
    assert cancelled or calls == ['pubmed']
    assert result.facts.created_papers == (0 if cancelled else 1)
    assert result.facts.details['discovery_status'] == ('cancelled' if cancelled else 'partial')


def test_openalex_journal_issue_is_excluded_before_creation_detail_lookup(tmp_path):
    from integrated_run_helpers import run_integrated
    from allfold.application.monitor import RunOutcome
    from test_integrated_run import config
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [openalex]\n')
    calls = []
    def response(request):
        calls.append(request.url.path)
        if request.url.path.startswith('/sources/'):
            return httpx.Response(200, json={'id': 'https://openalex.org/S1', 'issn': ['0006-341X']})
        return httpx.Response(200, json={'meta': {'count': 1}, 'results': [{
            'id': 'https://openalex.org/W1', 'doi': '10.5555/issue', 'title': 'Learning special issue',
            'type': 'other', 'primary_location': {'raw_type': 'journal-issue','source':{'id':'https://openalex.org/S1','issn':['0006-341X']}}}]})
    result = run_integrated(path, client_factory=lambda provider, **kwargs:
        DiscoveryClient(provider, interval=0, transport=httpx.MockTransport(response), **kwargs))
    assert calls == ['/works']
    assert result.outcome == RunOutcome.COMPLETED
    assert not result.errors and result.facts.created_papers == 0
    assert result.facts.details['provider_runs'][0]['candidates'] == 0


@pytest.mark.parametrize('existing_owner',[False,True])
@pytest.mark.parametrize('split_batches',[False,True])
def test_unified_wos_quarantines_conflicting_ut_before_creation(tmp_path,existing_owner,split_batches):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    from dataclasses import replace
    from pathlib import Path
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService, load_config
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import PreparedService
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from integrated_run_helpers import run_integrated
    from allfold.application.workspace import load_workspace
    from allfold.providers.wos import record_paper
    from test_wos import tagged, record
    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + 'institution:\n  name: Test University\nenabled_providers: [wos]\n')
    initial = load_user_state(path)
    compare_write_user_state(path, replace(initial.state, access_services=(*initial.state.access_services,
        AccessService.create('Web of Science', 'https://www.webofscience.com/'))), initial.revision)
    settings = load_config(path)
    workspace = settings.output_dir
    rows = [record(doi='10.5555/a', ut='WOS:1'), record(doi='10.5555/b', ut='WOS:1'),
            record(doi='10.5555/safe', ut='WOS:2')]
    if existing_owner:
        saved = record_paper(rows[0], settings.journals[0])
        original, = capture_papers((saved,), workspace)
        original_record = original
    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return 71

        def prepared_authority(self, saved, service_id):
            return PreparedService(self.prepared_page(saved, service_id), 'd' * 64)

    class Bridge:
        connected = True
        def execute(self, action, data, progress=None):
            future = Future()
            if action == 'release_workflow_pages':
                value = {'ok': True}
            elif action == 'wos_query':
                value = dict(page_id=71,total=3,batch_limit=1 if split_batches else 500)
            else:
                exports=([rows[2],rows[0],rows[1]][data['first']-1:data['last']] if split_batches else rows)
                Path(data['filename']).write_text(tagged(exports))
                value = dict(filename=data['filename'])
            future.set_result(value)
            return future
    stage = WoSCoordinator(path, Login(), threading.Lock(), bridge=Bridge(), browser_lock=BrowserTaskLock())
    result = run_integrated(path, wos_stage=stage.execute_stage, workflow_id='parent-run')
    assert result.facts.created_papers == 1
    assert result.facts.details['discovery_status'] == 'partial'
    assert stage.task['writes'].conflicts == 2
    papers = load_workspace(workspace).papers
    assert {paper.external_ids.doi for paper in papers} == ({'10.5555/a', '10.5555/safe'} if existing_owner else {'10.5555/safe'})
    safe = next(paper for paper in papers if paper.external_ids.doi == '10.5555/safe')
    assert safe.external_ids.wos == 'WOS:2'
    assert not (workspace / 'Evidence').exists()
    if existing_owner:
        assert read_paper(workspace, original.id) == original_record
