"""The one-time cleanup preserves retained state and refuses uncertain databases."""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3

import pytest

from allfold.persistence.safe_write import ContentChangedError
from allfold.persistence.user_state import load_user_state, read_user_state, compare_write_user_state, UserStateError
from safety_config_helpers import current_mapping_document

spec = importlib.util.spec_from_file_location('scope_cleanup', Path(__file__).resolve().parents[1] / 'tools/remove_conference_data.py')
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def legacy_state(tmp_path):
    config, legacy, journal, service = current_mapping_document(tmp_path)
    saved = load_user_state(config)
    other = tmp_path / 'other.yaml'
    compare_write_user_state(other, saved.state, saved.revision.__class__(False, None))
    with closing(sqlite3.connect(saved.database_path)) as db, db:
        payload = json.loads(db.execute('SELECT payload FROM user_scopes WHERE config_path=?', (str(config),)).fetchone()[0])
        payload['conferences'] = [dict(id='conf_'+'1'*32, name='Synthetic Conference', abbreviation='SC', aliases=[],
                                     dblp_stream='streams/conf/example', group=journal.group, labels=[])]
        db.execute('UPDATE user_scopes SET payload=? WHERE config_path=?', (json.dumps(payload), str(config)))
        rows = db.execute('SELECT * FROM user_scopes ORDER BY config_path').fetchall()
    return config, other, saved, rows


def rows(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT * FROM user_scopes ORDER BY config_path').fetchall()


def test_cleanup_backs_up_preserves_scopes_and_advances_only_changed_revisions(tmp_path):
    config, other, saved, before = legacy_state(tmp_path)
    untouched = read_user_state(other)
    with pytest.raises(UserStateError):
        read_user_state(config)
    # The old revision is still computed from the complete old payload.
    import hashlib
    original = next(row for row in before if row[0] == str(config))
    old_revision = saved.revision.__class__(True, hashlib.sha256(f'{config}\0{original[1]}\0{original[2]}'.encode()).hexdigest())
    count, backup = cleanup.remove_conference_data(saved.database_path)
    assert count == 1 and rows(backup) == before
    assert backup.stat().st_mode & 0o777 == 0o600
    after = rows(saved.database_path)
    for old, new in zip(before, after):
        if old[0] != str(config):
            assert new == old
            continue
        expected = json.loads(old[2]); expected.pop('conferences')
        assert json.loads(new[2]) == expected
        assert new[1] == old[1] + 1 and new[0] == old[0] and new[3:] == old[3:]
    assert read_user_state(config).state == saved.state
    assert read_user_state(other) == untouched
    with pytest.raises(ContentChangedError):
        compare_write_user_state(config, saved.state, old_revision)
    assert cleanup.remove_conference_data(saved.database_path) == (0, None)
    assert rows(saved.database_path) == after
    assert len(list(saved.database_path.parent.glob('*.bak'))) == 1


@pytest.mark.parametrize('invalid', ['unknown-field', 'bad-collection', 'bad-entry', 'invalid-journal', 'duplicate-json', 'revision', 'schema', 'corrupt'])
def test_cleanup_refuses_unknown_or_damaged_data_without_partial_writes(tmp_path, invalid):
    config, other, saved, before = legacy_state(tmp_path)
    path = saved.database_path
    with closing(sqlite3.connect(path)) as db, db:
        raw = json.loads(before[0][2])
        if invalid == 'unknown-field': raw['unknown'] = []
        elif invalid == 'bad-collection': raw['conferences'] = {}
        elif invalid == 'bad-entry': raw['conferences'] = [{'id': 'unrecognized'}]
        elif invalid == 'invalid-journal': raw['journals'][0]['issn'] = 'bad'
        if invalid in {'unknown-field', 'bad-collection', 'bad-entry', 'invalid-journal'}:
            db.execute('UPDATE user_scopes SET payload=? WHERE config_path=?', (json.dumps(raw), before[0][0]))
        elif invalid == 'duplicate-json':
            db.execute('UPDATE user_scopes SET payload=? WHERE config_path=?', ('{"conferences":[],"conferences":[]}', before[0][0]))
        elif invalid == 'revision': db.execute('UPDATE user_scopes SET revision=0')
        elif invalid == 'schema': db.execute('CREATE TABLE unknown(value)')
    if invalid == 'corrupt': path.write_bytes(b'corrupt')
    original_bytes = path.read_bytes()
    with pytest.raises((ValueError, sqlite3.Error)):
        cleanup.remove_conference_data(path)
    assert path.read_bytes() == original_bytes
    assert not list(path.parent.glob('*.bak'))


def test_cleanup_rolls_back_all_scopes_after_write_failure(tmp_path, monkeypatch):
    config, other, saved, before = legacy_state(tmp_path)
    real_connect = cleanup._connect
    def connect(path):
        connection = real_connect(path)
        def deny(action, name, *args):
            return sqlite3.SQLITE_DENY if action == sqlite3.SQLITE_UPDATE else sqlite3.SQLITE_OK
        connection.set_authorizer(deny)
        return connection
    monkeypatch.setattr(cleanup, '_connect', connect)
    with pytest.raises(sqlite3.DatabaseError):
        cleanup.remove_conference_data(saved.database_path)
    assert rows(saved.database_path) == before
    backup, = saved.database_path.parent.glob('*.bak')
    assert rows(backup) == before


def test_cleanup_refuses_concurrent_revision_change(tmp_path, monkeypatch):
    config, other, saved, before = legacy_state(tmp_path)
    original_clean = cleanup._clean_payload
    changed = False
    def clean(payload):
        nonlocal changed
        if not changed:
            changed = True
            with closing(sqlite3.connect(saved.database_path)) as db, db:
                db.execute('UPDATE user_scopes SET revision=revision+1 WHERE config_path=?', (str(other),))
        return original_clean(payload)
    monkeypatch.setattr(cleanup, '_clean_payload', clean)
    with pytest.raises(ContentChangedError):
        cleanup.remove_conference_data(saved.database_path)
    after = rows(saved.database_path)
    assert [row[2] for row in after] == [row[2] for row in before]
    assert not list(saved.database_path.parent.glob('*.bak'))


def test_new_user_scope_contract_contains_only_active_collections(tmp_path):
    config, *_ = current_mapping_document(tmp_path)
    saved = load_user_state(config)
    raw = json.loads(rows(saved.database_path)[0][2])
    assert set(raw) == {'journals', 'groups', 'custom_labels', 'access_services'}


def test_deleted_settings_api_cannot_read_or_recreate_retired_sources(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from test_settings_autosave import patch_body
    config, *_ = current_mapping_document(tmp_path)
    before = load_user_state(config)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        initial = client.get('/api/ui-next/settings').json()
        assert 'conferences' not in initial['values']
        assert client.get('/api/ui-next/settings/conferences/search?q=example').status_code == 404
        response = client.post('/api/ui-next/settings/autosave', json=patch_body(initial, conferences=[]))
        assert response.status_code == 200
        assert response.json()['saved'] is False and response.json()['outcome'] == 'INVALID_DRAFT'
    assert read_user_state(config) == before


@pytest.mark.parametrize('schema', [
    '(config_path, revision, payload, migration_source, migration_digest, migrated_at)',
    cleanup.USER_SCOPES_SCHEMA.replace('PRIMARY KEY', ''),
    cleanup.USER_SCOPES_SCHEMA.replace('INTEGER NOT NULL', 'INTEGER'),
    cleanup.USER_SCOPES_SCHEMA.replace('revision INTEGER NOT NULL', 'revision INTEGER NOT NULL DEFAULT 1'),
    cleanup.USER_SCOPES_SCHEMA.replace('migrated_at TEXT)', 'migrated_at TEXT, CHECK(revision > 0))'),
])
def test_cleanup_refuses_same_columns_with_unknown_types_or_constraints(tmp_path, schema):
    config, other, saved, original = legacy_state(tmp_path)
    path = tmp_path / 'unknown.sqlite'
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE user_scopes ' + schema)
        db.executemany('INSERT INTO user_scopes VALUES (?, ?, ?, ?, ?, ?)', original)
    before = path.read_bytes()
    with pytest.raises(ValueError, match='Unknown database schema'):
        cleanup.remove_conference_data(path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob('*.bak'))
