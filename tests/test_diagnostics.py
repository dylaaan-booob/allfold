"""Public store tests use only disposable configuration/log roots."""
import io
import json
import zipfile

from allfold.diagnostics import DiagnosticStore


def bundle(store, task_id=None):
    with zipfile.ZipFile(io.BytesIO(store.export(task_id))) as archive:
        return {name: archive.read(name).decode() for name in archive.namelist()}


def test_pubmed_run_sources_survive_restart_and_export_without_credentials(tmp_path):
    config, root = tmp_path / 'config.yaml', tmp_path / 'logs'
    store = DiagnosticStore(config, root=root, runtime_id='first')
    store.begin('run', 'pubmed_run', provider='pubmed')
    store.finish('pubmed_run', 'completed', details={'run_sources': [
        {'provider': 'pubmed', 'status': 'complete', 'candidates': 2, 'created': 1,
         'existing': 1, 'problems': 0, 'api_key': 'PRIVATE_KEY', 'query': 'PRIVATE_QUERY'},
    ]})
    restarted = DiagnosticStore(config, root=root, runtime_id='second')
    record = restarted.history()['records'][0]
    assert record['provider'] == 'pubmed'
    assert record['details']['run_sources'] == [
        {'provider': 'pubmed', 'status': 'complete', 'candidates': 2, 'created': 1,
         'existing': 1, 'problems': 0},
    ]
    exported = bundle(restarted, 'pubmed_run')
    assert json.loads(exported['summary.json'])['records'][0] == record
    assert 'PRIVATE_KEY' not in ''.join(exported.values())
    assert 'PRIVATE_QUERY' not in ''.join(exported.values())


def test_history_survives_restart_and_never_promotes_an_unknown_import(tmp_path):
    config = tmp_path / 'monitor.yaml'
    config.write_text('keyword_expression: synthetic\n')
    root = tmp_path / 'logs'
    store = DiagnosticStore(config, root=root, runtime_id='runtime_first')
    store.begin('run', 'run_1', provider='crossref')
    store.finish('run_1', 'partial', statistics={'retrieved': 12, 'created': 3})
    store.finish('run_1', 'completed')  # A terminal result is immutable.
    store.begin('import', 'save_1', workflow_id='kept_1')
    restarted = DiagnosticStore(config, root=root, runtime_id='runtime_second')
    records = {record['task_id']: record for record in restarted.history()['records']}
    assert records['run_1']['outcome'] == 'partial'
    assert records['run_1']['statistics'] == {'retrieved': 12, 'created': 3}
    assert records['save_1']['outcome'] == 'uncertain'
    assert records['save_1']['details']['reason'] == 'runtime_interrupted'
    restarted.workspace_reset()
    assert all(record['before_workspace_reset'] for record in restarted.history()['records'])
    exported = bundle(restarted, 'save_1')
    assert set(exported) == {'manifest.json', 'summary.json', 'events.jsonl', 'README.md'}
    assert json.loads(exported['summary.json'])['records'][0]['outcome'] == 'uncertain'


def test_export_revalidates_native_records_and_preserves_exact_associations(tmp_path):
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='python_1')
    store.begin('import', 'paper_task', workflow_id='workflow_one')
    native = store.root / 'scopes' / store.scope_id / 'electron'
    native.mkdir(mode=0o700)
    shared = dict(schema_version=1, time='2026-11-03T01:00:00Z', source='electron',
        runtime_id='native_1', scope_id=store.scope_id, level='error', event='attachment_failed',
        workflow_id='workflow_one', task_id='paper_task', page_id=17, source_page_id=9,
        action='import_paper', stage='attachment', code='timeout', status=504,
        attachment_phase='desktop_attachment', parent='confirmed', pdf='unverified')
    records = [dict(shared, cookie='SESSION=secret', authorization='Bearer private',
                    url='https://private.invalid/?token=secret', body='private document',
                    reason='PASSWORD=secret'),
               dict(shared, workflow_id='unrelated_workflow'),
               dict(shared, scope_id='a' * 64),
               dict(shared, event='Cookie=secret'),
               dict(shared, event=['invalid'])]
    (native / 'events.0.jsonl').write_text('\n'.join(json.dumps(x) for x in records) + '\n')
    exported = bundle(store, 'paper_task')
    assert 'secret' not in ''.join(exported.values())
    events = [json.loads(line) for line in exported['events.jsonl'].splitlines()]
    native_events = [event for event in events if event['source'] == 'electron']
    assert len(native_events) == 1
    assert native_events[0]['page_id'] == 17
    assert native_events[0]['source_page_id'] == 9
    assert native_events[0]['stage'] == 'attachment'
    assert native_events[0]['parent'] == 'confirmed'
    assert native_events[0]['pdf'] == 'unverified'
    assert native_events[0]['attachment_phase'] == 'desktop_attachment'
    assert json.loads(exported['manifest.json'])['integrity']['invalid_records'] == 2


def test_logs_reset_is_one_use_configuration_and_file_identity_bound(tmp_path):
    import pytest
    from allfold.diagnostics import DiagnosticRefused
    config = tmp_path / 'config.yaml'
    config.write_text('keyword_expression: synthetic\n')
    store = DiagnosticStore(config, root=tmp_path / 'logs', runtime_id='runtime_one')
    store.begin('run', 'run_one')
    plan = store.preview_reset()
    config.write_text('keyword_expression: changed\n')
    with pytest.raises(DiagnosticRefused):
        store.reset(plan)
    assert len(store.history()['records']) == 1
    plan = store.preview_reset()
    assert store.reset(plan)['success']
    assert store.history()['records'] == []
    with pytest.raises(DiagnosticRefused):
        store.reset(plan)
    store.begin('run', 'after_reset')
    assert store.history()['records'][0]['task_id'] == 'after_reset'
    plan = store.preview_reset()
    history = store.root / 'scopes' / store.scope_id / 'python' / 'history.json'
    history.rename(history.with_name('preserved-original'))
    history.write_text('replacement private file')
    with pytest.raises(DiagnosticRefused):
        store.reset(plan)
    assert history.read_text() == 'replacement private file'


def test_logs_confirmation_survives_wait_and_remains_single_use(tmp_path, monkeypatch):
    import pytest
    from types import SimpleNamespace
    import allfold.diagnostics as diagnostics
    from allfold.diagnostics import DiagnosticRefused
    clock = [1.0]
    monkeypatch.setattr(diagnostics, 'time', SimpleNamespace(monotonic=lambda: clock[0]), raising=False)
    config = tmp_path / 'config.yaml'
    config.write_text('keyword_expression: synthetic\n')
    store = DiagnosticStore(config, root=tmp_path / 'logs')
    store.begin('run', 'run_one')
    plan = store.preview_reset()
    clock[0] += 90 * 24 * 60 * 60
    store.validate_reset(plan)
    assert store.reset(plan)['success']
    assert store.history()['records'] == []
    with pytest.raises(DiagnosticRefused):
        store.reset(plan)


def test_bounded_history_rotation_and_native_failure_remain_visible_after_restart(tmp_path):
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='first',
                            max_file_bytes=1024, max_files=2, max_history=3)
    for index in range(20):
        task = f'run_{index}'
        store.begin('run', task)
        store.finish(task, 'completed', details={'results': [
            {'paper_id': '12345678-aaaa-4aaa-8aaa-aaaaaaaaaaaa', 'outcome': 'confirmed',
             'pdf_outcome': 'unverified', 'reason': 'pdf_unverified',
             'diagnostic': {'stage': 'navigation', 'code': 'timeout'},
             'title': 'private research title'}]})
    store.native_status({'available': False, 'incomplete': True, 'write_failures': 2,
                         'cookie': 'secret'})
    current = store.history()
    assert len(current['records']) == 3
    assert current['integrity']['native']['incomplete']
    assert current['records'][0]['details']['results'][0]['pdf_outcome'] == 'unverified'
    restarted = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='second',
                                max_file_bytes=1024, max_files=2, max_history=3)
    data = bundle(restarted)
    manifest = json.loads(data['manifest.json'])
    assert manifest['integrity']['rotated_files'] > 0
    assert manifest['integrity']['evicted_history'] == 17
    assert 'private research title' not in ''.join(data.values())
    files = list((store.root / 'scopes' / store.scope_id / 'python').glob('events*'))
    assert len(files) == 2
    assert all(path.stat().st_size <= 1024 for path in files)


def test_symlinks_and_replaced_roots_never_redirect_writes_or_deletion(tmp_path):
    import pytest
    from allfold.diagnostics import DiagnosticRefused
    outside = tmp_path / 'outside'
    outside.mkdir()
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='runtime')
    current = store.root / 'scopes' / store.scope_id / 'python' / 'events.jsonl'
    original = current.read_bytes()
    private = outside / 'private.txt'
    private.write_bytes(original)
    current.unlink()
    current.symlink_to(private)
    assert not store.event('workflow_finished', {'task_id': 'safe', 'outcome': 'completed'})
    assert private.read_bytes() == original
    with pytest.raises((DiagnosticRefused, OSError)):
        store.preview_reset()
    assert store.history()['integrity']['write_failed']
    store.root.rename(tmp_path / 'original-logs')
    store.root.symlink_to(outside, target_is_directory=True)
    assert not store.event('app_started')
    assert private.read_bytes() == original


def test_disk_write_failure_keeps_business_outcome_and_safe_memory_warning(tmp_path, monkeypatch, capsys):
    import allfold.diagnostics as diagnostics
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='runtime')
    store.begin('import', 'save')
    def full(*args, **kwargs):
        raise OSError('disk full with PRIVATE_TOKEN')
    monkeypatch.setattr(diagnostics.os, 'replace', full)
    assert not store.finish('save', 'confirmed', details={'pdf_outcome': 'unverified'})
    history = store.history()
    assert history['records'][0]['outcome'] == 'confirmed'
    assert history['integrity']['write_failed']
    assert 'PRIVATE_TOKEN' not in capsys.readouterr().err
    assert json.loads(bundle(store)['manifest.json'])['integrity']['write_failed']


def test_replaced_regular_log_file_is_not_overwritten_by_stale_writer(tmp_path):
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='runtime')
    current = store.root / 'scopes' / store.scope_id / 'python' / 'events.jsonl'
    current.rename(current.with_name('saved-events'))
    current.write_text('replacement private file')
    assert not store.event('app_started')
    assert current.read_text() == 'replacement private file'


def test_concurrent_recording_and_reset_keep_other_configuration_and_exported_files(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    root = tmp_path / 'logs'
    first = DiagnosticStore(tmp_path / 'one.yaml', root=root, runtime_id='one')
    second = DiagnosticStore(tmp_path / 'two.yaml', root=root, runtime_id='two')
    second.begin('import', 'other_save')
    second.finish('other_save', 'uncertain')
    def work(index):
        first.begin('run', f'run_{index}')
        first.finish(f'run_{index}', 'completed')
    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, range(30)))
    assert len(first.history()['records']) == 30
    exported = tmp_path / 'downloaded.zip'
    exported.write_bytes(first.export())
    assert first.reset(first.preview_reset())['success']
    assert len(second.history()['records']) == 1
    assert json.loads(bundle(second)['summary.json'])['records'][0]['outcome'] == 'uncertain'
    assert zipfile.is_zipfile(exported)


def test_effective_level_filters_optional_details_but_keeps_business_results(tmp_path, monkeypatch):
    monkeypatch.setenv('ALLFOLD_LOG_LEVEL', 'error')
    store = DiagnosticStore(tmp_path / 'config.yaml', root=tmp_path / 'logs', runtime_id='one', level='debug')
    assert store.level == 'error'
    store.set_level('debug')
    store.event('translator_http', {'status': 200}, level='info')
    store.begin('run', 'run_one')
    store.finish('run_one', 'completed')
    data = bundle(store)
    events = [json.loads(line) for line in data['events.jsonl'].splitlines()]
    assert 'translator_http' not in {event['event'] for event in events}
    assert 'workflow_finished' in {event['event'] for event in events}
    assert store.history()['records'][0]['outcome'] == 'completed'


def test_recent_export_uses_one_seven_day_utc_window_but_task_export_keeps_older_evidence(tmp_path, monkeypatch):
    import allfold.diagnostics as diagnostics

    clock = ['2020-01-01T00:00:00.000Z']
    monkeypatch.setattr(diagnostics, '_now', lambda: clock[0])
    config, root = tmp_path / 'config.yaml', tmp_path / 'logs'
    store = DiagnosticStore(config, root=root, runtime_id='old_runtime')
    store.begin('run', 'old_task')
    store.finish('old_task', 'completed')
    clock[0] = '2026-10-27T09:59:59.999Z'
    store.begin('run', 'before_boundary')
    store.finish('before_boundary', 'completed')
    clock[0] = '2026-10-27T10:00:00.000Z'
    store.begin('run', 'at_boundary')
    store.finish('at_boundary', 'completed')
    clock[0] = '2026-11-03T09:00:00.000Z'
    restarted = DiagnosticStore(config, root=root, runtime_id='current_runtime')
    restarted.begin('run', 'recent_task')
    restarted.finish('recent_task', 'partial')
    clock[0] = '2026-11-03T10:00:00.001Z'
    restarted.begin('run', 'future_task')
    restarted.finish('future_task', 'completed')
    export_times = []
    def export_time():
        export_times.append(True)
        return '2026-11-03T10:00:00.000Z'
    monkeypatch.setattr(diagnostics, '_now', export_time)

    recent = bundle(restarted)
    assert len(export_times) == 1
    manifest = json.loads(recent['manifest.json'])
    assert manifest['exported_at'] == '2026-11-03T10:00:00.000Z'
    assert manifest['collection_range'] == {
        'from': '2026-10-27T10:00:00.000Z', 'to': '2026-11-03T10:00:00.000Z',
        'days': 7, 'intentionally_limited': True}
    assert manifest['integrity']['range_excluded_history'] == 3
    assert manifest['integrity']['range_excluded_events'] > 0
    records = json.loads(recent['summary.json'])['records']
    assert {record['task_id'] for record in records} == {'at_boundary', 'recent_task'}
    events = [json.loads(line) for line in recent['events.jsonl'].splitlines()]
    assert {event['task_id'] for event in events if 'task_id' in event} == {'at_boundary', 'recent_task'}
    assert manifest['retained_runtime_ids'] == ['current_runtime', 'old_runtime']

    explicit = bundle(restarted, 'old_task')
    assert {record['task_id'] for record in json.loads(explicit['summary.json'])['records']} == {'old_task'}
    assert any(event['runtime_id'] == 'old_runtime' for event in
               (json.loads(line) for line in explicit['events.jsonl'].splitlines()))
    assert json.loads(explicit['manifest.json'])['collection_range'] is None
