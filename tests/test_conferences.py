"""Conference series remain distinct from journals in saved and shared scopes."""
from dataclasses import replace
import json
import sqlite3

import pytest
from allfold.config import ConferenceConfig, JournalConfig, SettingsList
from allfold.persistence.user_state import (ContentRevision, compare_write_user_state,
    read_user_state, user_state_path)
from allfold.persistence.safe_write import ContentChangedError


def conference(**updates):
    return ConferenceConfig(id='conf_00000000000000000000000000000001',
        name='International Conference on Machine Learning', abbreviation='ICML',
        aliases=('ICML',), dblp_stream='streams/conf/icml', **updates)


def test_conferences_preserve_legacy_payload_and_config_revision_isolation(tmp_path):
    first, second = tmp_path/'first.yaml', tmp_path/'second.yaml'
    old = SettingsList((JournalConfig(name='Biometrics', issn='0006-341X'),), ('Methods',), ('Follow',), ())
    initial = compare_write_user_state(first, old, ContentRevision(False, None))
    # A real persisted four-collection payload from before Conferences existed.
    with sqlite3.connect(user_state_path(first)) as db:
        payload = json.loads(db.execute('SELECT payload FROM user_scopes').fetchone()[0])
        payload.pop('conferences', None)
        db.execute('UPDATE user_scopes SET payload=?', (json.dumps(payload),))
    loaded = read_user_state(first)
    assert loaded.state == old and loaded.state.conferences == ()
    updated = compare_write_user_state(first, replace(old, conferences=(conference(group='Methods', labels=('Follow',)),)), loaded.revision)
    assert updated.state.conferences[0].dblp_stream == 'streams/conf/icml'
    assert updated.state.journals == old.journals
    assert read_user_state(second, allow_missing=True).state.conferences == ()
    with pytest.raises(ContentChangedError):
        compare_write_user_state(first, old, loaded.revision)


def test_shipped_registry_searches_series_alias_and_stable_stream_offline():
    from pathlib import Path
    from allfold.persistence.journal_registry import conference_candidates
    root = Path(__file__).resolve().parents[1]
    entries = conference_candidates(root/'list.md', '')
    assert len(entries) == 22
    assert len({c['id'] for c in entries}) == 22
    nips = conference_candidates(root/'list.md', 'NIPS')
    assert len(nips) == 1 and nips[0]['dblp_stream'] == 'streams/conf/nips'
    assert nips[0]['abbreviation'] == 'NeurIPS'
    assert not any('issn' in c or 'access_service_id' in c for c in entries)


def test_conference_settings_autosave_reorders_assigns_and_rejects_stale(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from safety_config_helpers import current_mapping_document
    from test_settings_autosave import patch_body
    from settings_api_helpers import registry
    from pathlib import Path
    import shutil
    config, _, _, _ = current_mapping_document(tmp_path)
    registry(tmp_path)
    shutil.copyfile(Path(__file__).resolve().parents[1]/'journal-lists/journal-registry.sqlite', tmp_path/'journal-lists/journal-registry.sqlite')
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        initial = client.get('/api/ui-next/settings').json()
        candidates = client.get('/api/ui-next/settings/conferences/search?q=ICML').json()['candidates']
        entry = {k:v for k,v in candidates[0].items() if k in ConferenceConfig.model_fields}
        entry.update(group='AI', labels=['Follow'])
        saved = client.post('/api/ui-next/settings/autosave', json=patch_body(initial,
            conferences=[entry], groups=[*initial['values']['groups'], 'AI'], custom_labels=[*initial['values']['custom_labels'], 'Follow'])).json()
        assert saved['saved'], saved.get('issues')
        assert saved['values']['conferences'][0]['dblp_stream'] == 'streams/conf/icml'
        assert saved['values']['conferences'][0]['labels'] == ['Follow']
        stale = client.post('/api/ui-next/settings/autosave', json=patch_body(initial, conferences=[])).json()
        assert stale['outcome'] == 'REVISION_CONFLICT'
        loaded = client.get('/api/ui-next/settings').json()
        assert loaded['values']['conferences'] == saved['values']['conferences']
        from allfold.config import load_config
        assert load_config(config).conferences[0].name == entry['name']
        only_conferences = client.post('/api/ui-next/settings/autosave', json=patch_body(loaded, journals=[])).json()
        assert only_conferences['saved'] and not only_conferences['issues'], only_conferences.get('issues')
        assert load_config(config).journals == ()
        cleared = client.post('/api/ui-next/settings/autosave', json=patch_body(only_conferences, conferences=[])).json()
        assert cleared['saved'] and cleared['values']['conferences'] == []


def test_conference_scope_preview_confirm_export_preserves_series_order_and_assignments(tmp_path):
    import shutil
    from pathlib import Path
    from allfold.application.full_markdown_import import preview_research_scope, confirm_research_scope, export_user_data
    (tmp_path/'journal-lists').mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[1]/'journal-lists/journal-registry.sqlite', tmp_path/'journal-lists/journal-registry.sqlite')
    first, second = tmp_path/'one.yaml', tmp_path/'two.yaml'
    content = '''# Research Scope
## Conferences
| Conference | DBLP Stream | Group | Labels |
| --- | --- | --- | --- |
| NeurIPS | streams/conf/nips | ML | Follow |
| ICML | streams/conf/icml | ML | Later; Follow |
'''
    preview = preview_research_scope(first, tmp_path/'list.md', content, filename='scope.md')
    assert [r.status for r in preview.rows] == ['add', 'add']
    assert read_user_state(first, allow_missing=True).state.conferences == ()
    saved = confirm_research_scope(preview).state
    assert [c.abbreviation for c in saved.conferences] == ['NeurIPS', 'ICML']
    assert saved.journals == () and saved.access_services == ()
    exported = export_user_data(first)
    imported = preview_research_scope(second, tmp_path/'list.md', exported, filename='export.md')
    assert confirm_research_scope(imported).state == saved
    again = preview_research_scope(first, tmp_path/'list.md', exported, filename='again.md')
    assert [r.status for r in again.rows] == ['skip', 'skip']
    assert again.proposed == saved
    changed = compare_write_user_state(first, replace(saved, conferences=tuple(reversed(saved.conferences))), read_user_state(first).revision)
    with pytest.raises(ContentChangedError):
        confirm_research_scope(again)
    assert read_user_state(first).state == changed.state


def test_legacy_markdown_conferences_are_not_automatically_followed(tmp_path):
    from safety_config_helpers import current_mapping_document
    from allfold.application.settings import load_settings
    from allfold.persistence.user_state import load_user_state
    config, legacy, _, _ = current_mapping_document(tmp_path)
    legacy.write_text(legacy.read_text()+'\n## Conferences\n\n- ICML\n- NeurIPS\n')
    original = legacy.read_bytes()
    assert load_user_state(config).state.conferences == ()
    assert load_settings(config).draft.conferences == ()
    assert legacy.read_bytes() == original


def test_registry_conference_table_rebuild_matches_reviewed_source(tmp_path):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('registry_builder', root/'tools/build_journal_registry.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    with sqlite3.connect(tmp_path/'registry.sqlite') as rebuilt, sqlite3.connect(root/'journal-lists/journal-registry.sqlite') as shipped:
        builder.build_conferences(rebuilt)
        assert rebuilt.execute('SELECT * FROM conferences ORDER BY position').fetchall() == shipped.execute('SELECT * FROM conferences ORDER BY position').fetchall()
