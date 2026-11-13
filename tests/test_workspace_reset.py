"""A8 destruction tests use disposable, synthetic Workspaces only."""
from __future__ import annotations
from electron_test_helpers import OfflineBridge

from allfold.application.run_state import RunProvider
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

import allfold.application.workspace_reset as reset
from allfold.application.workspace_reset import ResetRefused, execute_reset, preview_reset
from allfold.models import ExternalIds
from allfold.persistence.paper_repository import PaperRepository
from allfold.persistence.library_models import PaperMetadata
from allfold.web.app import create_app


@pytest.fixture
def dedicated(tmp_path: Path):
    config = tmp_path / "monitor.yaml"
    config.write_text(
        "name: Synthetic Monitor\nvenue_whitelist: list.md\nkeyword_expression: causal\n"
        "output_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-01\nlog_level: INFO\n", encoding="utf-8",
    )
    (tmp_path / "list.md").write_text(
        '# Venues\n\n## Journals\n\n| Journal | ISSN | eISSN | Access Service ID | Group | Labels |\n| --- | --- | --- | --- | --- | --- |\n| Biometrics | 0006-341X |  |  |  |  |\n\n## Groups\n\n| Group |\n| --- |\n\n## Custom Labels\n\n| Label |\n| --- |\n\n## Access Services\n\n| Service ID | Service | Access URL | Access Method |\n| --- | --- | --- | --- |\n', encoding="utf-8",
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with PaperRepository.create(workspace) as repository:
        paper = repository.create_or_match(repository.workspace_id, direct_ids=ExternalIds(doi='10.5555/synthetic'),
            metadata=PaperMetadata(title='Synthetic Research', abstract='Abstract')).paper
        repository.exclude(paper.token)
    (workspace / ".obsidian").mkdir()
    (workspace / ".obsidian" / "app.json").write_text('{"personal":true}', encoding="utf-8")
    (workspace / "monitor.yaml").write_text("protected local configuration", encoding="utf-8")
    (workspace / "list.md").write_text("protected list", encoding="utf-8")
    return config, workspace


@pytest.mark.parametrize('name', ['/', str(Path.home()), str(Path.cwd()), '/tmp', '/Users', '/Library', '.'])
def test_dangerous_target_refuses_before_delete(tmp_path, name):
    config = tmp_path / 'monitor.yaml'
    config.write_text(f'keyword_expression: causal\noutput_dir: {name}\n')
    with pytest.raises(ResetRefused): preview_reset(config)


def test_public_root_replaced_immediately_before_rmtree_is_preserved(dedicated, monkeypatch):
    config, workspace = dedicated
    plan = preview_reset(config)
    held = config.parent / 'original'
    original = reset.shutil.rmtree
    def replace(*args, **kwargs):
        if workspace.exists():
            workspace.rename(held)
        workspace.mkdir()
        (workspace / 'private.txt').write_text('replacement user directory')
        return original(*args, **kwargs)
    replace.avoids_symlink_attacks = True
    monkeypatch.setattr(reset.shutil, 'rmtree', replace)
    with (workspace / 'papers.sqlite').open('rb') as confirmed_paper:
        result = execute_reset(config, plan)
        assert os.fstat(confirmed_paper.fileno()).st_nlink == 0
    assert (workspace / 'private.txt').read_text() == 'replacement user directory'
    assert not result.success
    if held.exists(): assert (held / 'papers.sqlite').exists()


@pytest.mark.parametrize('linked', ['workspace', 'ancestor'])
def test_target_and_ancestor_links_never_delete_external_files(tmp_path, linked):
    config = tmp_path / 'monitor.yaml'
    outside = tmp_path / 'external'; outside.mkdir()
    (outside / 'workspace').mkdir()
    (outside / 'workspace' / 'private.txt').write_text('untouched')
    target = tmp_path / 'workspace'
    target.symlink_to(outside / 'workspace' if linked == 'workspace' else outside, target_is_directory=True)
    value = 'workspace' if linked == 'workspace' else 'workspace/workspace'
    config.write_text(f'keyword_expression: causal\noutput_dir: {value}\n')
    with pytest.raises(ResetRefused): preview_reset(config)
    assert (outside / 'workspace' / 'private.txt').read_text() == 'untouched'


def test_links_inside_workspace_are_removed_without_following(dedicated):
    config, workspace = dedicated
    outside = config.parent / 'external'; outside.mkdir()
    (outside / 'private.txt').write_text('untouched')
    (workspace / 'directory-link').symlink_to(outside, target_is_directory=True)
    (workspace / 'file-link').symlink_to(outside / 'private.txt')
    (workspace / 'broken-link').symlink_to(outside / 'missing')
    assert execute_reset(config, preview_reset(config)).success
    assert (outside / 'private.txt').read_text() == 'untouched'


@pytest.mark.parametrize('change', ['config', 'directory', 'symlink'])
def test_stale_confirmation_does_not_delete_another_target(dedicated, change):
    config, workspace = dedicated
    plan = preview_reset(config)
    outside = config.parent / 'other'; outside.mkdir()
    (outside / 'private.txt').write_text('untouched')
    if change == 'config':
        config.write_text(config.read_text().replace('output_dir: workspace', 'output_dir: other'))
    else:
        workspace.rename(config.parent / 'original')
        if change == 'directory':
            workspace.mkdir(); (workspace / 'replacement').write_text('untouched')
        else: workspace.symlink_to(outside, target_is_directory=True)
    result = execute_reset(config, plan)
    assert not result.success
    assert not result.workspace_invalidated
    assert (outside / 'private.txt').read_text() == 'untouched'
    if change == 'directory': assert (workspace / 'replacement').read_text() == 'untouched'


def test_partial_delete_error_is_failure_without_retry(dedicated, monkeypatch):
    config, workspace = dedicated
    plan = preview_reset(config)
    removed = workspace / 'remove-me'; removed.write_text('included')
    calls = []
    def fail(name, *, dir_fd):
        calls.append(name)
        captured = next(config.parent.glob('.allfold-reset-*/workspace'))
        (captured / 'remove-me').unlink()
        raise OSError('synthetic deletion failure')
    monkeypatch.setattr(reset.shutil, 'rmtree', fail)
    fail.avoids_symlink_attacks = True
    result = execute_reset(config, plan)
    assert not result.success and calls == ['workspace']
    assert result.workspace_invalidated
    captured = next(config.parent.glob('.allfold-reset-*/workspace'))
    assert not (captured / 'remove-me').exists() and (captured / 'papers.sqlite').exists()
    assert not workspace.exists() and str(captured.parent) in result.message
    assert 'permanently deleted' in result.message and 'no recovery or automatic retry' in result.message


def test_unsafe_external_lock_reports_failure_without_deletion(dedicated, monkeypatch):
    from allfold.persistence.safe_write import CompareReadError
    config, workspace = dedicated
    def refuse(_path):
        raise CompareReadError('Workspace path lock is not a safe empty regular file')
    monkeypatch.setattr(reset, 'workspace_path_lock', refuse)
    result = execute_reset(config, preview_reset(config))
    assert not result.success and 'Workspace path lock' in result.message
    assert (workspace / 'papers.sqlite').exists()


def reset_data(client):
    state = client.get('/api/ui-next/settings').json()
    preview = client.get('/api/ui-next/settings/reset-preview').json()
    return {'csrf_token': state['csrf_token'], 'reset_token': preview['reset_token'],
            'reset_word': 'RESET'}


def test_external_lock_remains_exclusive_after_workspace_is_deleted(dedicated):
    from allfold.application.monitor import run_monitor
    from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
    from allfold.persistence.safe_write import ContentChangedError
    from allfold.application.coordinators.run_coordinator import RunCoordinator, StartOutcome
    config, workspace = dedicated
    program = """from pathlib import Path
import sys
import allfold.application.workspace_reset as reset
config=Path(sys.argv[1]); plan=reset.preview_reset(config)
original=reset.shutil.rmtree
def hold(*args, **kwargs):
    original(*args, **kwargs)
    print('TREE_DELETED_LOCK_HELD', flush=True)
    sys.stdin.readline()
hold.avoids_symlink_attacks=True
reset.shutil.rmtree=hold
print(reset.execute_reset(config,plan).success, flush=True)
"""
    child = subprocess.Popen([sys.executable, '-c', program, str(config)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == 'TREE_DELETED_LOCK_HELD'
        assert not workspace.exists()
        with pytest.raises(ContentChangedError): run_monitor(config, provider="integrated")
        assert RunCoordinator(config).start(RunProvider.INTEGRATED).outcome is StartOutcome.START_FAILED
        assert save_settings(config, load_settings(config).draft).outcome is SettingsSaveOutcome.WRITE_FAILED
        assert not execute_reset(config, preview_reset(config)).success
        assert not workspace.exists()
    finally:
        out,_=child.communicate(input='\n',timeout=10)
    assert child.returncode==0 and out.strip()=='True'


@pytest.mark.parametrize('owner', ['commit'])
def test_other_process_commit_blocks_reset(dedicated, owner):
    config, workspace = dedicated
    program = """from pathlib import Path
import sys
from allfold.persistence.safe_write import workspace_operation_lock
from allfold.application.monitor import run_monitor
config=Path(sys.argv[1]); workspace=Path(sys.argv[2])
if sys.argv[3]=='commit':
 from allfold.application.run_commit import capture_run_workspace, commit_run_workspace
 with capture_run_workspace(config) as snapshot:
  with commit_run_workspace(snapshot):
   print('OWNED',flush=True);sys.stdin.readline()
"""
    child=subprocess.Popen([sys.executable,'-c',program,str(config),str(workspace),owner],
                           stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
    try:
        assert child.stdout.readline().strip()=='OWNED'
        assert not execute_reset(config,preview_reset(config)).success
        assert (workspace/'papers.sqlite').exists()
    finally:
        child.communicate(input='\n',timeout=10)
    assert child.returncode==0
