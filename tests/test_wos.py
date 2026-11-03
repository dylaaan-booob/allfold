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
from allfold.persistence.markdown_state import parse_paper_state
from allfold.persistence.materialize import materialize_papers
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


def test_unsafe_doi_identity_blocks_capture(tmp_path):
    path=materialize_papers([paper()],tmp_path).created_papers[0]
    (path.parent/'duplicate.md').write_bytes(path.read_bytes())
    with workspace_operation_lock(tmp_path) as lock:
        result=persist_wos([paper()],lock,check_current=lambda:None,cancelled=lambda:False)
    assert result.conflicts==1 and result.skipped_existing_papers==0 and result.created_papers==0


def test_cancel_during_persistence_retains_committed_paper(tmp_path):
    result=WoSWrites()
    papers=[paper(AF=[]),paper(doi='10.1234/next',ut='WOS:999',AF=[])]
    with workspace_operation_lock(tmp_path,create=True) as lock, pytest.raises(InterruptedError):
        persist_wos(papers,lock,check_current=lambda:None,
                    cancelled=lambda:bool(result.created_papers),result=result)
    assert result.created_papers==1 and len(list((tmp_path/'Papers').glob('*.md')))==1


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


@pytest.mark.parametrize('change_after_query', [False, True])
def test_coordinator_preserves_saved_service_scope_and_prepared_page_across_batches(tmp_path, change_after_query):
    from concurrent.futures import Future
    from types import SimpleNamespace
    from allfold.application.browser_runtime import BrowserTaskLock
    from allfold.application.browser_services import BrowserServiceSnapshot
    from allfold.application.coordinators.preparation_coordinator import PreparationPhase
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

    class Preparation:
        def start(self, config_path, *, service, browser_owner):
            assert service.name == 'Web of Science'
            self.service = service
            return self.snapshot()
        def snapshot(self):
            return SimpleNamespace(task_id='preparation', generation=1, phase=PreparationPhase.COMPLETED,
                authorization_pending=False, message='Prepared', waiting_for_user=False)
        def wos_handoff(self, task_id, generation):
            assert (task_id, generation) == ('preparation', 1)
            return 71
        def join(self):
            pass

    class Bridge:
        connected = True
        calls = []
        def execute(self, action, data, progress=None):
            self.calls.append((action, data))
            future = Future()
            if action == 'wos_query':
                if change_after_query:
                    path.write_text(path.read_text() + '\n# changed during Query\n')
                result = dict(page_id=71, total=2, batch_limit=1)
            else:
                assert action == 'wos_export'
                Path(data['filename']).write_text(tagged([record(doi=f"10.1234/{data['first']}",
                    ut=f"WOS:{data['first']}", PD='JAN')]))
                result = dict(filename=data['filename'])
            future.set_result(result)
            return future

    bridge, prep, lock = Bridge(), Preparation(), BrowserTaskLock()
    coordinator = WoSCoordinator(path, prep, threading.Lock(), bridge=bridge, browser_lock=lock)
    coordinator.start()
    coordinator.join()
    assert [action for action, _ in bridge.calls] == (['wos_query'] if change_after_query else
                                                     ['wos_query', 'wos_export', 'wos_export'])
    assert all(data['page_id'] == 71 and data['service_id'] == prep.service.id
               and data['service_scope'] == saved.scope for _, data in bridge.calls)
    assert len({data['task_id'] for _, data in bridge.calls}) == 1
    assert coordinator.state()['snapshot']['status'] == 'FINISHED'
    assert lock.owner is None


