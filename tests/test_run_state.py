"""Provider-specific snapshot versions, isolated from real Workspace data."""
import json
from dataclasses import replace
from datetime import date

import pytest

from allfold.application.run_state import (
    INTEGRATED_RUN_SCHEMA_VERSION, LastRunSnapshot, LastRunSnapshotWriteError,
    RecordedRunOutcome, RunFacts, RunProvider, read_last_run_snapshot, write_last_run_snapshot,
)
from allfold.date_range import ResolvedDateRange
from allfold.persistence.safe_write import workspace_operation_lock


def integrated_payload(version=6):
    payload = {
        'schema_version': version,
        'provider': 'integrated',
        'resolved_date_range': {'from_date': '2026-01-01', 'to_date': '2026-03-31'},
        'outcome': 'COMPLETED',
        'facts': {
            'finished_at': '2026-04-01T00:00:00+00:00',
            'created_papers': 2, 'existing_papers': 1,
            'statistics': {'integrated_candidates': 3, 'integrated_deduplicated': 3},
            'details': {'discovery_status': 'complete', 'provider_runs': []},
        },
    }
    if version == 4:
        payload['coverage'] = []
    return payload


def snapshot():
    return LastRunSnapshot(
        schema_version=INTEGRATED_RUN_SCHEMA_VERSION, provider=RunProvider.INTEGRATED,
        resolved_date_range=ResolvedDateRange(date(2026, 1, 1), date(2026, 3, 31)),
        outcome=RecordedRunOutcome.COMPLETED,
        facts=RunFacts.model_validate(integrated_payload()['facts']),
    )


def save_payload(tmp_path, payload):
    target = tmp_path / '.allfold' / 'last-integrated-run.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(payload))
    return target


@pytest.mark.parametrize("version", [4, 5])
def test_old_integrated_is_unsupported_without_migration_or_deletion(tmp_path, version):
    target = save_payload(tmp_path, integrated_payload(version))
    original = target.read_bytes()
    result = read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED)
    assert result.status.value == 'unsupported'
    assert '重新运行' in result.error
    assert target.read_bytes() == original
    assert sorted(tmp_path.iterdir()) == [target.parent]


def test_integrated_v6_atomic_create_and_replace_round_trip(tmp_path):
    value = snapshot()
    with workspace_operation_lock(tmp_path) as lock:
        write_last_run_snapshot(tmp_path, value, operation_lock=lock)
        target = tmp_path / '.allfold' / 'last-integrated-run.json'
        raw = json.loads(target.read_text())
        assert raw['schema_version'] == 6
        assert set(raw) == {'schema_version', 'provider', 'resolved_date_range', 'outcome', 'facts'}
        assert read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED).snapshot == value
        updated = replace(value, facts=value.facts.model_copy(update={'created_papers': 0, 'existing_papers': 3}))
        write_last_run_snapshot(tmp_path, updated, operation_lock=lock)
        assert read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED).snapshot == updated


@pytest.mark.parametrize('change', [
    {'provider': 'wos'}, {'provider': 'openalex'}, {'coverage': []},
    {'schema_version': '5'}, {'schema_version': True},
    {'outcome': 'INVALID_CONFIGURATION'},
    {'resolved_date_range': {'from_date': '2026-04-01', 'to_date': '2026-03-31'}},
    {'resolved_date_range': {'from_date': '2026-1-1', 'to_date': '2026-03-31'}},
    {'facts': {'finished_at': '2026-04-01', 'created_papers': 0, 'existing_papers': 0}},
    {'facts': {'finished_at': '2026-04-01T00:00:00Z', 'created_papers': -1, 'existing_papers': 0}},
    {'facts': {'finished_at': '2026-04-01T00:00:00Z', 'created_papers': 0, 'existing_papers': 0, 'legacy': 1}},
])
def test_current_snapshot_rejects_mismatched_or_illegal_fields(tmp_path, change):
    payload = {**integrated_payload(), **change}
    target = save_payload(tmp_path, payload)
    original = target.read_bytes()
    result = read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED)
    assert result.status.value == 'invalid' and result.error
    assert target.read_bytes() == original


@pytest.mark.parametrize('contents', ['{broken', 'null', '[]', '{}'])
def test_malformed_snapshot_is_invalid(tmp_path, contents):
    target = save_payload(tmp_path, {})
    target.write_text(contents)
    result = read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED)
    assert result.status.value == 'invalid' and result.error
    assert target.read_text() == contents


def test_missing_snapshot_read_does_not_initialize_workspace(tmp_path):
    workspace = tmp_path / 'absent'
    assert read_last_run_snapshot(workspace, RunProvider.INTEGRATED).status.value == 'not_found'
    assert not workspace.exists()


def test_read_io_failure_retains_failure_reason(tmp_path, monkeypatch):
    save_payload(tmp_path, integrated_payload())
    def fail(*args):
        raise OSError('fixture read denied')
    monkeypatch.setattr('allfold.application.run_state.read_text_exact', fail)
    result = read_last_run_snapshot(tmp_path, RunProvider.INTEGRATED)
    assert result.status.value == 'invalid'
    assert result.error == 'fixture read denied'


@pytest.mark.parametrize('link', ['snapshot', 'metadata'])
def test_snapshot_read_and_write_refuse_symlinks(tmp_path, link):
    workspace = tmp_path / 'workspace'
    outside = tmp_path / 'outside'
    workspace.mkdir()
    outside.mkdir()
    target = save_payload(outside, integrated_payload())
    original = target.read_bytes()
    if link == 'snapshot':
        (workspace / '.allfold').mkdir()
        (workspace / '.allfold' / target.name).symlink_to(target)
    else:
        (workspace / '.allfold').symlink_to(target.parent, target_is_directory=True)
    assert read_last_run_snapshot(workspace, RunProvider.INTEGRATED).status.value == 'invalid'
    with workspace_operation_lock(workspace) as lock, pytest.raises(LastRunSnapshotWriteError):
        write_last_run_snapshot(workspace, snapshot(), operation_lock=lock)
    assert target.read_bytes() == original


def test_write_failure_preserves_previous_snapshot(tmp_path, monkeypatch):
    target = save_payload(tmp_path, integrated_payload(4))
    original = target.read_bytes()
    def fail(*args, **kwargs):
        raise OSError('fixture disk full')
    monkeypatch.setattr('allfold.application.run_state.atomic_replace_text', fail)
    with pytest.raises(LastRunSnapshotWriteError, match='fixture disk full'):
        write_last_run_snapshot(tmp_path, snapshot())
    assert target.read_bytes() == original
