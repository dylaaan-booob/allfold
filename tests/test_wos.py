from electron_test_helpers import OfflineBridge
"""Small isolated regressions; real CARSI/WoS acceptance remains user-owned."""
from allfold.application.run_state import RunProvider
from dataclasses import replace
from datetime import date
from pathlib import Path
import threading
import os

from fastapi.testclient import TestClient
import pytest

from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
from allfold.application.wos import WoSWrites, persist_wos
from allfold.config import JournalConfig
from allfold.keywords import Prefix, Proximity
from allfold.persistence.paper_repository import PaperRepository, PaperMetadata
from allfold.persistence.safe_write import TextWriteCommittedError, WorkspaceTextDirectory, workspace_operation_lock
from allfold.web.app import create_app
from allfold.application.coordinators.run_coordinator import RunCoordinator, StartOutcome
from allfold.providers.wos import compile_wos_query, WoSQueryError, combined_query, match_journal, record_paper, WoSRecords, parse_tagged, publication_date, read_export


def record(doi='10.1234/example', ut='WOS:000123456700001', **updates):
    raw = dict(DI=doi, UT=ut, TI='Old title', SO='Provider title', SN='0006-341X', PY='2026',
               AF='Fan, Jianqing', AB='Original abstract')
    raw.update(updates)
    return {key: [value] if isinstance(value, str) else value for key, value in raw.items()}


def tagged(records, ending=True):
    lines = ['FN Clarivate Analytics Web of Science', 'VR 1.0']
    for raw in records:
        lines.append('PT J')
        for key, values in raw.items():
            for index, value in enumerate(values):
                lines.append((key + ' ' if index == 0 else '   ') + value)
        lines.append('ER')
    if ending:
        lines.append('EF')
    return '\n'.join(lines) + '\n'


def paper(**updates):
    return record_paper(record(**updates), JournalConfig(name='Biometrics',issn='0006-341X'))


def test_download_reader_rejects_unissued_and_replaced_paths(tmp_path):
    relative = 'allfold-wos/run-token/batch-token.txt'
    target = tmp_path / relative
    target.parent.mkdir(parents=True)
    target.write_text(tagged([record()]))
    content, root = read_export(str(target), relative)
    assert content.startswith('FN ') and root == tmp_path
    with pytest.raises(ValueError):
        read_export(str(target), relative.replace('batch-token', 'other-token'))
    with pytest.raises(ValueError):
        read_export(str(target), relative, tmp_path / 'different-root')
    hardlink = tmp_path / 'hardlink'
    os.link(target, hardlink)
    with pytest.raises(ValueError):
        read_export(str(target), relative)
    hardlink.unlink()
    target.unlink()
    target.symlink_to(tmp_path / 'outside')
    with pytest.raises(OSError):
        read_export(str(target), relative)


def test_conflicting_direct_identity_owners_block_capture(tmp_path):
    from allfold.models import ExternalIds
    with PaperRepository.create(tmp_path) as repository:
        repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.1234/example'),
            metadata=PaperMetadata(title='DOI owner'))
        repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(wos='WOS:000123456700001'),
            metadata=PaperMetadata(title='WoS owner'))
        before = repository.list_papers()
    with workspace_operation_lock(tmp_path) as lock:
        result=persist_wos([paper()],lock,check_current=lambda:None,cancelled=lambda:False)
    assert result.conflicts==1 and result.skipped_existing_papers==0 and result.created_papers==0
    with PaperRepository.open(tmp_path) as repository:
        assert repository.list_papers() == before


def test_cancel_during_persistence_retains_committed_paper(tmp_path):
    result=WoSWrites()
    papers=[paper(AF=[]),paper(doi='10.1234/next',ut='WOS:999',AF=[])]
    with workspace_operation_lock(tmp_path,create=True) as lock, pytest.raises(InterruptedError):
        persist_wos(papers,lock,check_current=lambda:None,
                    cancelled=lambda:bool(result.created_papers),result=result)
    with PaperRepository.open(tmp_path) as repository:
        saved, = repository.list_papers()
        assert result.created_papers == 1 and result.written_paper_ids == [str(saved.id)]


def test_wos_batch_uses_indexed_matches_without_rescanning_saved_metadata(tmp_path, monkeypatch):
    with PaperRepository.create(tmp_path):
        pass
    full_reads = []
    original = PaperRepository.list_papers
    def read_all(repository):
        full_reads.append(True)
        return original(repository)
    monkeypatch.setattr(PaperRepository, 'list_papers', read_all)
    papers = [paper(doi=f'10.1234/incoming-{index}', ut=f'WOS:{100 + index}') for index in range(8)]
    with workspace_operation_lock(tmp_path) as lock:
        result = persist_wos(papers, lock, check_current=lambda: None, cancelled=lambda: False)
    assert result.created_papers == 8 and not result.issues
    assert len(full_reads) == 1  # Initial eligibility capture only, regardless of batch size.


def config_files(tmp_path):
    from test_a4_publisher_settings import setup
    path, venues, _ = setup(tmp_path)
    service_id = 'svc_' + 'a' * 32
    text = venues.read_text()
    heading = text.index('## Access Services')
    end = text.find('\n## ', heading + 1)
    end = len(text) if end < 0 else end
    venues.write_text(text[:end].rstrip() + f'\n| {service_id} | Web of Science |  | carsi |\n\n' + text[end:])
    with path.open('a') as stream:
        stream.write('\ninstitution:\n  name: Fixture University\n  idp_entity_id: https://idp.example/idp/shibboleth\n')
    return path, venues


@pytest.mark.parametrize(('change_after_query', 'prepared_page'),
    [(None, 71), ('comment', 71), ('unrelated', 71),
     ('journal_display', 71), ('unused_service', 71),
     ('keyword', 71), ('date', 71), ('journal_scope', 71),
     ('access', 71), ('prepared', 71), (None, None), (None, 42)])
def test_coordinator_preserves_saved_service_scope_and_prepared_page_across_batches(
    tmp_path, change_after_query, prepared_page,
):
    from concurrent.futures import Future
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.browser_services import BrowserServiceSnapshot
    from allfold.application.coordinators.login import ServicePreparation
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator

    from safety_config_helpers import current_mapping_document
    from allfold.config import AccessService
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + 'institution:\n  name: Test University\n')
    initial = load_user_state(path)
    compare_write_user_state(path, replace(initial.state, access_services=(*initial.state.access_services,
        AccessService.create('Web of Science', 'https://www.webofscience.com/'))), initial.revision)
    saved = BrowserServiceSnapshot.read(path)

    refused = change_after_query in {'keyword', 'date', 'journal_scope', 'access'}

    class Login:
        def prepared_page(self, saved, service_id):
            assert any(service.id == service_id and service.name == "Web of Science" for service in saved.services)
            return prepared_page
        def prepared_authority(self, saved, service_id):
            return ServicePreparation(status='Opened', page_id=prepared_page) if prepared_page is not None else None


    recovery = [{'recovery_action': 'page_refresh', 'count': 1, 'outcome': 'recovered',
        'first': {'stage': 'navigation', 'code': 'load_failed', 'net_code': -100},
        'last': {'stage': 'navigation', 'page_id': 71}}]

    class Bridge:
        connected = True
        calls = []
        cleanup_dispatched = threading.Event()
        cleanup_result = Future()
        def execute(self, action, data, progress=None, **kwargs):
            self.calls.append((action, data))
            future = Future()
            if action == 'release_workflow_pages':
                self.cleanup_dispatched.set()
                return self.cleanup_result
            elif action == 'wos_query':
                if change_after_query in {'journal_display', 'unused_service', 'journal_scope', 'access'}:
                    current = load_user_state(path)
                    if change_after_query == 'unused_service':
                        state = replace(current.state, access_services=(*current.state.access_services,
                            AccessService.create('Unrelated', 'https://unrelated.example/')))
                    elif change_after_query == 'access':
                        state = replace(current.state, access_services=tuple(s.model_copy(update={
                            'access_url': 'https://changed.example/'}) if s.name == 'Web of Science' else s
                            for s in current.state.access_services))
                    else:
                        update = {'name': 'Display alias'} if change_after_query == 'journal_display' else {'issn': '0090-5364'}
                        state = replace(current.state, journals=tuple(j.model_copy(update=update) for j in current.state.journals))
                    compare_write_user_state(path, state, current.revision)
                elif change_after_query:
                    text = path.read_text()
                    if change_after_query == 'keyword':
                        text = text.replace('keyword_expression: causal', 'keyword_expression: inference')
                    elif change_after_query == 'date':
                        text = text.replace('to_month: 2026-01', 'to_month: 2026-02')
                    elif change_after_query == 'unrelated':
                        text += '\nlog_level: DEBUG\nworkflow:\n  managed_page_global_limit: 8\n'
                    else:
                        text += '\n# changed during Query\n'
                    path.write_text(text)
                result = dict(page_id=72 if change_after_query == 'prepared' else 71, total=2, batch_limit=1, recovery=recovery)
            else:
                assert action == 'wos_export'
                Path(data['filename']).write_text(tagged([record(doi=f"10.1234/{data['first']}",
                    ut=f"WOS:{data['first']}", PD='JAN')]))
                if data['first'] == 2:
                    assert data['page_id'] == 73
                result = dict(filename=data['filename'], page_id=73)
            future.set_result(result)
            return future

    bridge, login, lock = Bridge(), Login(), BrowserTaskLock()
    from allfold.diagnostics import DiagnosticStore
    store = DiagnosticStore(path, root=tmp_path / "logs")
    coordinator = WoSCoordinator(path, login, threading.Lock(), bridge=bridge, browser_lock=lock, diagnostics=store)
    start = coordinator.start()
    try:
        assert bridge.cleanup_dispatched.wait(2)
        assert coordinator.running and lock.owners
        with pytest.raises(ValueError, match='already active'):
            coordinator.start()
    finally:
        bridge.cleanup_result.set_result({'released': True})
        coordinator.join()
    assert [action for action, _ in bridge.calls] == (['wos_query', 'release_workflow_pages'] if refused else
                                                     ['wos_query', 'wos_export', 'wos_export', 'release_workflow_pages'])
    assert bridge.calls[-1][1] == {'workflow_id': start['snapshot']['task_id'], 'task_id': start['snapshot']['task_id']}
    query = bridge.calls[0][1]
    assert query['service_entry']['resource_name'] == 'Web of Science'
    assert [data['page_id'] for _, data in bridge.calls[1:-1]] == (
        [] if refused else [72 if change_after_query == 'prepared' else 71, 73])
    assert all(data['service_id'] == next(s.id for s in saved.services if s.name == 'Web of Science')
               and data['service_scope'] == saved.scope for _, data in bridge.calls[:-1])
    assert len({data['task_id'] for _, data in bridge.calls}) == 1
    assert all(data['workflow_id'] == start['snapshot']['task_id'] for _,data in bridge.calls)
    assert store.history()['records'][0]['task_id'] == start['snapshot']['task_id']
    assert store.history()['records'][0]['outcome'] == ('failed' if refused else 'completed')
    assert store.history()['records'][0]['details']['recovery'] == recovery
    assert coordinator.state()['snapshot']['status'] == 'FINISHED'
    assert lock.owner is None
    if not refused:
        import json
        from allfold.application.run_state import (
            INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshot, RecordedRunOutcome, RunFacts,
            write_last_run_snapshot,
        )
        from allfold.application.run_summary import build_run_result_summary
        from allfold.date_range import ResolvedDateRange
        from allfold.config import load_config
        workspace = load_config(path).output_dir
        target = workspace / '.allfold' / 'last-wos-run.json'
        original = target.read_bytes()
        value = json.loads(original)
        assert value['schema_version'] == 4
        write_last_run_snapshot(workspace, LastRunSnapshot(
            INTEGRATED_RUN_SCHEMA_VERSION, RunProvider.INTEGRATED,
            ResolvedDateRange(date(2026, 1, 1), date(2026, 1, 31)), RecordedRunOutcome.COMPLETED,
            RunFacts.model_validate(value['result']['facts'])))
        restarted = WoSCoordinator(path, login, threading.Lock(), bridge=bridge, browser_lock=lock)
        restored = restarted.state()['latest']
        assert restored == value
        summary = build_run_result_summary(restored)
        assert summary['status'] == 'completed' and summary['coverage_status'] == 'complete'
        assert summary['statistics']['returned_records'] == 2
        assert len(summary['details']['batches']) == 2
        assert summary['journals']
        assert target.read_bytes() == original
        assert [action for action, _ in bridge.calls] == ['wos_query', 'wos_export', 'wos_export', 'release_workflow_pages']




@pytest.mark.parametrize('edit', ['comment', 'journal_display', 'keyword', 'access', 'read_interleave'])
def test_wos_retains_original_run_scope_across_unrelated_edits(tmp_path, monkeypatch, edit):
    from concurrent.futures import Future
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.coordinators.login import ServicePreparation
    from allfold.application.coordinators.wos_coordinator import WoSCoordinator
    from allfold.application.run_commit import capture_run_workspace
    from allfold.config import AccessService
    from allfold.persistence.safe_write import ContentChangedError
    from allfold.persistence.user_state import load_user_state, compare_write_user_state
    from safety_config_helpers import current_mapping_document

    path, _, _, _ = current_mapping_document(tmp_path)
    path.write_text(path.read_text() + '\nenabled_providers: [wos]\n')
    state = load_user_state(path)
    wos = AccessService.create('Web of Science', 'https://www.webofscience.com/')
    compare_write_user_state(path, replace(state.state, access_services=(*state.state.access_services, wos)), state.revision)
    class Login:
        def prepared_authority(self, saved, service_id):
            return ServicePreparation(status='Opened', page_id=71)
    class Bridge:
        connected = True
        calls = []
        def execute(self, action, data, progress=None, **kwargs):
            self.calls.append((action, data))
            future = Future()
            future.set_result(dict(page_id=71, total=0, batch_limit=0) if action == 'wos_query' else {'released': True})
            return future
    bridge = Bridge()
    coordinator = WoSCoordinator(path, Login(), threading.Lock(), bridge=bridge, browser_lock=BrowserTaskLock())
    if edit == 'read_interleave':
        from allfold.application.coordinators import wos_coordinator
        original_load = wos_coordinator.load_config
        edited = False
        def read_then_edit(config_path):
            nonlocal edited
            loaded = original_load(config_path)
            if not edited:
                edited = True
                current = load_user_state(config_path)
                compare_write_user_state(config_path, replace(current.state,
                    groups=(*current.state.groups, 'Unrelated group')), current.revision)
            return loaded
        # Schedule an actual independent DB edit between the two admission reads.
        monkeypatch.setattr(wos_coordinator, 'load_config', read_then_edit)
        coordinator.start()
        coordinator.join()
        assert not coordinator.task['result']['issues']
        assert coordinator.task['config'].user_state_revision != load_user_state(path).revision.digest
        assert [action for action, _ in bridge.calls] == ['wos_query', 'release_workflow_pages']
        return
    with capture_run_workspace(path) as snapshot:
        if edit in {'journal_display', 'access'}:
            saved = load_user_state(path)
            update = replace(saved.state, journals=tuple(j.model_copy(update={'name': 'Display alias'}) for j in saved.state.journals)) if edit == 'journal_display' else replace(saved.state,
                access_services=tuple(s.model_copy(update={'access_url': 'https://changed.example/'}) if s.id == wos.id else s
                    for s in saved.state.access_services))
            compare_write_user_state(path, update, saved.revision)
        else:
            path.write_text(path.read_text().replace('keyword_expression: causal', 'keyword_expression: inference')
                if edit == 'keyword' else path.read_text() + '\n# changed before parent native stage\n')
        if edit in {'keyword', 'access'}:
            with pytest.raises(ContentChangedError):
                coordinator.execute_stage(snapshot, cancel_event=threading.Event())
            assert not bridge.calls
        else:
            assert coordinator.execute_stage(snapshot, cancel_event=threading.Event()).status == 'empty'
            assert coordinator.task['config'] is snapshot.config
            assert [action for action, _ in bridge.calls] == ['wos_query', 'release_workflow_pages']
