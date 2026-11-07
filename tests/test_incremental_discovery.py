from datetime import date
import httpx

from allfold.keywords import parse_keyword_expression
from allfold.providers.integrated import DiscoveryClient, SourceScope


def test_lightweight_identity_discovery_then_batched_unknown_details():
    calls = []
    def handler(request):
        calls.append(request)
        params = request.url.params
        if params['resultType'] == 'lite':
            assert 'FIRST_PDATE:' in params['query']
            rows = [{'source': 'MED', 'id': str(n), 'doi': f'10.5555/{n}'} for n in (1, 2, 3)]
        else:
            assert 'EXT_ID:3 AND SRC:MED' in params['query']
            assert 'EXT_ID:1 ' not in params['query'] and 'EXT_ID:2 ' not in params['query']
            rows = [{'source': 'MED', 'id': '3', 'doi': '10.5555/3', 'title': 'New C', 'abstractText': 'Creation details'}]
        return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.discover_candidates(SourceScope('journal', 'Test', issns=('0006-341X',)),
            parse_keyword_expression('learning'), date(2026, 1, 1), date(2026, 3, 31))
        assert result.candidates == 3 and result.records[0].title is None
        details = client.lookup_many('europe_pmc', ['MED:3'])
    assert len(calls) == 2 and details.records[0].abstract == 'Creation details'
    assert not details.limitations


def test_unified_run_wos_first_skips_details_for_saved_rejected_and_current_wos(tmp_path):
    from datetime import datetime, timezone
    from allfold.application.integrated_run import run_integrated, IntegratedDiscovery
    from allfold.models import ExternalIds, MetadataSource, ProviderWorkEvidence
    from allfold.providers.integrated import DiscoveryResult
    from test_integrated_run import config
    from allfold.application.workspace import load_workspace
    path, _ = config(tmp_path)
    path.write_text(path.read_text() + 'enabled_providers: [europe_pmc]\n')
    events = []
    def response(request):
        events.append(('api', request.url.params['resultType']))
        if request.url.params['resultType'] == 'lite':
            rows = [{'source': 'MED', 'id': str(n), 'doi': f'10.5555/{n}'} for n in (1, 2, 3)]
        else:
            query = request.url.params['query']
            nums = [n for n in (1, 2, 3) if f'EXT_ID:{n} AND SRC:MED' in query]
            rows = [{'source': 'MED', 'id': str(n), 'doi': f'10.5555/{n}', 'title': f'Paper {n}'} for n in nums]
        return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
    def factory(provider, **kwargs):
        return DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    # Seed B through the same public create-only Run then mark it Rejected.
    def only_b(request):
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{'source': 'MED', 'id': '2', 'doi': '10.5555/2', 'title': 'Paper 2'}]}})
    run_integrated(path, client_factory=lambda provider, **kwargs: DiscoveryClient(provider, transport=httpx.MockTransport(only_b), interval=0, **kwargs))
    saved, = (tmp_path / 'workspace' / 'Papers').glob('*.md')
    saved.write_text(saved.read_text().replace('status: candidate', 'status: rejected'))
    assert 'status: rejected' in saved.read_text()
    original = saved.read_bytes()
    path.write_text(path.read_text().replace('[europe_pmc]', '[wos, europe_pmc]'))
    def wos_stage(snapshot, **kwargs):
        events.append(('wos', 'first'))
        evidence = ProviderWorkEvidence(title='WoS A', external_ids=ExternalIds(doi='10.5555/1', wos='WOS:000000000000001'),
            provenance=MetadataSource(provider='wos', record_id='WOS:000000000000001', retrieved_at=datetime.now(timezone.utc)))
        source = SourceScope('journal', 'Test', issns=('0006-341X',))
        return IntegratedDiscovery((evidence,), (DiscoveryResult('wos', source, 'complete', (evidence,), candidates=1),), 'complete')
    result = run_integrated(path, client_factory=factory, wos_stage=wos_stage)
    assert events == [('wos', 'first'), ('api', 'lite'), ('api', 'core')]
    assert result.facts.created_papers == 2 and result.facts.existing_papers == 1
    assert saved.read_bytes() == original
    assert {paper.title for paper in load_workspace(tmp_path / 'workspace').inbox} >= {'WoS A', 'Paper 3'}


def test_native_stage_reuses_parent_slot_and_retains_first_batch_after_later_failure(tmp_path):
    import threading
    from concurrent.futures import Future
    from types import SimpleNamespace
    from dataclasses import replace
    from pathlib import Path
    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService, load_config
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.preparation_coordinator import PreparationPhase
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.application.integrated_run import run_integrated
    from allfold.application.run_commit import capture_run_workspace
    from allfold.diagnostics import DiagnosticStore
    from test_wos import tagged, record
    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + 'institution:\n  name: Test University\nenabled_providers: [wos]\n')
    initial = load_user_state(path)
    compare_write_user_state(path, replace(initial.state, access_services=(*initial.state.access_services,
        AccessService.create('Web of Science', 'https://www.webofscience.com/'))), initial.revision)
    class Preparation:
        def start(self, path, **kwargs):
            assert kwargs['workflow_id'] == kwargs['parent_task_id'] == 'parent-run'
            return self.snapshot()
        def snapshot(self):
            return SimpleNamespace(task_id='prep', generation=1, phase=PreparationPhase.COMPLETED,
                authorization_pending=False, message='Ready', waiting_for_user=False)
        def wos_handoff(self, *args): return 71
        def join(self): pass
    calls = []
    class Bridge:
        connected = True
        def execute(self, action, data, progress=None):
            calls.append(action)
            assert data['task_id'] == data['workflow_id'] == 'parent-run'
            future = Future()
            if action == 'wos_query': value = dict(page_id=71, total=2, batch_limit=1)
            elif data['first'] == 1:
                Path(data['filename']).write_text(tagged([record(doi='10.5555/safe', ut='WOS:1')]))
                value = dict(filename=data['filename'])
            else:
                future.set_exception(ValueError('Second export failed'))
                return future
            future.set_result(value)
            return future
    slot, browser = threading.Lock(), BrowserTaskLock()
    slot.acquire()
    store = DiagnosticStore(path, root=tmp_path / 'logs')
    stage = WoSCoordinator(path, Preparation(), slot, bridge=Bridge(), browser_lock=browser, diagnostics=store)
    with capture_run_workspace(path) as snapshot:
        result = run_integrated(path, workspace_snapshot=snapshot, wos_stage=stage.execute_stage, workflow_id='parent-run')
    assert slot.locked() and browser.owner is None
    slot.release()
    assert result.facts.created_papers == 1 and result.facts.details['discovery_status'] == 'partial'
    assert len(result.facts.details['batches']) == 2
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
    assert 'Missing creation details: W203' in result.limitations
    assert 'Unexpected detail record identity' in result.limitations


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


def test_lightweight_discovery_does_not_discard_valid_records_after_bad_candidate():
    def handler(request):
        return httpx.Response(200, json={'hitCount': 3, 'resultList': {'result': [
            {'source': 'MED', 'id': '1'}, {'id': 'bad'}, {'source': 'MED', 'id': '3'}]}})
    with DiscoveryClient('europe_pmc', transport=httpx.MockTransport(handler), interval=0) as client:
        result = client.discover_candidates(SourceScope('journal', 'Test', issns=('0006-341X',)),
            parse_keyword_expression('learning'), date(2026, 1, 1), date(2026, 3, 31))
    assert result.status == 'partial' and result.candidates == 3
    assert [record.external_ids.europe_pmc for record in result.records] == ['MED:1', 'MED:3']


def test_all_lightweight_sources_are_gathered_before_one_creation_detail_source(tmp_path):
    from test_integrated_run import config
    from allfold.application.integrated_run import run_integrated
    from allfold.application.workspace import load_workspace
    path, _ = config(tmp_path)
    calls = []
    def response(request):
        if request.url.host == 'api.openalex.org':
            if request.url.path.startswith('/sources/'):
                return httpx.Response(200, json={'id': 'https://openalex.org/S1', 'issn': ['0006-341X']})
            if 'select' in request.url.params:
                calls.append('oa-lite')
                assert set(request.url.params['select'].split(',')) == {'id','doi','ids','type','primary_location','locations','locations_count'}
                rows = [{'id': 'https://openalex.org/W3', 'doi': '10.5555/3', 'ids': {'pmid': '3'}, 'type': 'article'}]
            else:
                calls.append('oa-core')
                assert 'epmc-lite' in calls
                rows = [{'id': 'https://openalex.org/W3', 'doi': '10.5555/3', 'title': 'One creation detail'}]
            return httpx.Response(200, json={'meta': {'count': len(rows)}, 'results': rows})
        assert request.url.params['resultType'] == 'lite'
        calls.append('epmc-lite')
        return httpx.Response(200, json={'hitCount': 1, 'resultList': {'result': [{'source': 'MED', 'id': '3', 'doi': '10.5555/3'}]}})
    result = run_integrated(path, client_factory=lambda provider, **kwargs: DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs))
    assert result.facts.created_papers == 1 and not result.errors
    assert calls.count('oa-core') == 1 and len(calls) == 3
    paper, = load_workspace(tmp_path/'workspace').inbox
    assert paper.title == 'One creation detail'
    assert all(run['created'] == 1 for run in result.facts.details['provider_runs'])


def test_ambiguous_rediscovery_does_not_distribute_facts_to_two_saved_owners(tmp_path):
    from test_integrated_run import config
    from allfold.application.integrated_run import run_integrated
    path, _ = config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [europe_pmc]\n')
    ambiguous = False
    def response(request):
        if ambiguous:
            assert request.url.params['resultType'] == 'lite'
            rows = [{'source': 'MED', 'id': '1', 'doi': '10.5555/1',
                'commentCorrectionList': {'commentCorrection': [{'type': 'Preprint in', 'source': 'MED', 'id': '2', 'doi': '10.5555/2'}]}}]
        else:
            rows = [{'source': 'MED', 'id': str(n), 'doi': f'10.5555/{n}', 'title': f'Paper {n}'} for n in (1, 2)]
        return httpx.Response(200, json={'hitCount': len(rows), 'resultList': {'result': rows}})
    factory = lambda provider, **kwargs: DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    assert run_integrated(path, client_factory=factory).facts.created_papers == 2
    files = [*(tmp_path/'workspace'/'Papers').glob('*.md'), *(tmp_path/'workspace'/'Evidence').glob('*.json')]
    before = {p: p.read_bytes() for p in files}
    ambiguous = True
    result = run_integrated(path, client_factory=factory)
    assert result.facts.created_papers == result.facts.existing_papers == 0
    assert any('Ambiguous' in issue.message for issue in result.errors)
    assert {p: p.read_bytes() for p in files} == before


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
    from allfold.application.integrated_run import IntegratedDiscovery, run_integrated
    from allfold.providers.integrated import DiscoveryResult
    path, _ = config(tmp_path)
    path.write_text(path.read_text()+'enabled_providers: [wos, europe_pmc]\n')
    cancel = Event()
    calls = []
    def stage(snapshot, **kwargs):
        if cancelled: cancel.set()
        result = DiscoveryResult('wos', SourceScope('journal','Test'), 'cancelled' if cancelled else 'failed', limitations=('Native export could not be verified',))
        return IntegratedDiscovery((), (result,), result.status)
    def response(request):
        calls.append(request.url.params['resultType'])
        return httpx.Response(200, json={'hitCount':1,'resultList':{'result':[{'source':'MED','id':'3','title':'Surviving API paper'}]}})
    def factory(provider, **kwargs):
        assert not cancel.is_set()
        return DiscoveryClient(provider, transport=httpx.MockTransport(response), interval=0, **kwargs)
    result = run_integrated(path, wos_stage=stage, client_factory=factory, cancel_event=cancel)
    assert calls == ([] if cancelled else ['lite','core'])
    assert result.facts.created_papers == (0 if cancelled else 1)
    assert result.facts.details['discovery_status'] == ('cancelled' if cancelled else 'partial')
