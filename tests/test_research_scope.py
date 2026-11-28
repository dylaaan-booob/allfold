"""Portable scope exchange through application boundaries and isolated HTTP UI."""
from pathlib import Path

import httpx
import pytest


@pytest.fixture
def empty_openalex():
    from allfold.providers.openalex import OpenAlexClient
    with OpenAlexClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"results":[]}))) as provider:
        yield provider

from allfold.application.full_markdown_import import preview_research_scope, confirm_research_scope, export_user_data
from allfold.persistence.user_state import load_user_state
from allfold.config import SettingsList, JournalConfig, AccessService
from settings_api_helpers import registry


def test_incremental_name_scope_merges_overlapping_registry_evidence_without_writes(tmp_path):
    registry(tmp_path, [
        ('Biometrics', '0006-341X', None, 'Wiley', 'Scopus', 'Active'),
        ('Biometrics', '0006-341X', '1541-0420', 'Wiley', 'SCIE', None),
        ('Biometrics', None, '1541-0420', 'Wiley', 'SSCI', None),
    ])
    config = tmp_path / 'monitor.yaml'
    config.write_text('name: test\n')
    initial = SettingsList((JournalConfig(name='Annals', issn='0090-5364'),), ('Existing',), (), ())
    from allfold.persistence.user_state import compare_write_user_state
    from allfold.persistence.user_state import ContentRevision
    compare_write_user_state(config, initial, ContentRevision(False, None))
    before = load_user_state(config)
    plan = preview_research_scope(config, tmp_path / 'list.md', '- Biometrics\n', filename='scope.md')
    assert load_user_state(config).revision == before.revision
    assert plan.rows[0].status == 'add'
    assert len(plan.rows[0].candidates) == 1
    assert len(plan.rows[0].candidates[0]['sources']) == 3
    confirm_research_scope(plan)
    saved = load_user_state(config).state
    assert saved.journals == (initial.journals[0], JournalConfig(name='Biometrics', issn='0006-341X', eissn='1541-0420'))
    assert saved.groups == ('Existing',)


def forbid_gokb():
    def unexpected(request):
        pytest.fail(f'Unexpected GOKB request: {request.url}')
    return httpx.MockTransport(unexpected)


def stub_gokb_http(monkeypatch, handler):
    from allfold.providers import gokb
    client = gokb.create_http_client
    monkeypatch.setattr(gokb, 'create_http_client',
        lambda **options: client(**(options | {'transport': httpx.MockTransport(handler)})))


def test_portable_export_import_restores_independent_services_order_and_local_ids(tmp_path):
    from allfold.persistence.user_state import compare_write_user_state, ContentRevision
    registry(tmp_path)
    source = tmp_path / 'source.yaml'
    eb = AccessService.create('EBSCO', 'http://search.ebscohost.com/')
    wos = AccessService.create('Web of Science')
    manual = AccessService.create('Project Euclid', 'https://projecteuclid.org/', access_method='manual')
    state = SettingsList((JournalConfig(name='Biometrics', issn='0006-341X', group='B', labels=('Later','First'), access_service_id=eb.id),), ('A','B','Empty'), ('First','Later','Empty'), (wos, manual, eb))
    compare_write_user_state(source, state, ContentRevision(False, None))
    exported = export_user_data(source)
    assert 'svc_' not in exported
    target = tmp_path / 'target.yaml'
    plan = preview_research_scope(target, tmp_path/'list.md', exported, filename='data.md', transport=forbid_gokb(), query_gokb=True)
    assert not target.exists()
    confirm_research_scope(plan)
    saved = load_user_state(target).state
    assert saved.groups == state.groups
    assert saved.custom_labels == state.custom_labels
    assert [(s.name,s.access_url,s.access_method) for s in saved.access_services] == [(s.name,s.access_url,s.access_method) for s in state.access_services]
    assert not ({s.id for s in saved.access_services} & {s.id for s in state.access_services})
    assert saved.journals[0].group == 'B'
    assert saved.journals[0].labels == ('Later','First')
    assert saved.journals[0].access_service_id == saved.access_services[-1].id


@pytest.mark.parametrize("operation", ["import", "choose"])
def test_verified_carsi_production_reuses_saved_service_and_local_url(tmp_path, operation):
    from dataclasses import replace
    from safety_config_helpers import current_mapping_document
    from allfold.application.journal_services import choose_journal_service
    from allfold.application.settings import load_settings
    from allfold.persistence.user_state import compare_write_user_state

    config, path, journal, _ = current_mapping_document(tmp_path)
    initial = load_user_state(config)
    local = AccessService.create('EBSCO', 'https://library.example.org/ebsco')
    before = compare_write_user_state(config, replace(initial.state,
        access_services=(*initial.state.access_services, local)), initial.revision)
    if operation == 'import':
        source = '| Journal | Service | Access URL | Access Method |\n| --- | --- | --- | --- |\n| Annals | EBSCO | https://untrusted.example.org/login | carsi |\n'
        plan = preview_research_scope(config, path, source, filename='scope.md', query_gokb=True, transport=forbid_gokb())
        assert plan.rows[0].service_status == 'verified'
        assert load_user_state(config) == before
        saved = confirm_research_scope(plan)
        selected = saved.state.journals[-1]
    else:
        saved = choose_journal_service(config, journal.key, method='carsi', name='EBSCO',
            expected_revision=before.revision, expected_monitor_revision=load_settings(config).draft.monitor_revision)
        selected = saved.state.journals[0]
    assert selected.access_service_id == local.id
    assert saved.state.access_services == before.state.access_services
    assert load_user_state(config).state.access_services[-1] == local


@pytest.mark.parametrize("operation", ["import", "choose"])
@pytest.mark.parametrize(("saved_method", "chosen_method", "name"), [
    ('manual', 'carsi', 'EBSCO'),
    ('carsi', 'manual', 'EBSCO'),
    ('manual', 'manual', 'EBSCO'),
    ('carsi', 'carsi', 'ebsco'),
])
def test_service_reuse_preserves_method_manual_url_and_exact_production_boundaries(
        tmp_path, operation, saved_method, chosen_method, name):
    from dataclasses import replace
    from safety_config_helpers import current_mapping_document
    from allfold.application.journal_services import choose_journal_service
    from allfold.application.settings import load_settings
    from allfold.persistence.user_state import compare_write_user_state

    config, path, journal, _ = current_mapping_document(tmp_path)
    initial = load_user_state(config)
    local = AccessService.create('EBSCO', 'https://library.example.org/ebsco', access_method=saved_method)
    before = compare_write_user_state(config, replace(initial.state,
        access_services=(*initial.state.access_services, local)), initial.revision)
    if operation == 'import':
        source = f'| Journal | Service | Access URL | Access Method |\n| --- | --- | --- | --- |\n| Annals | {name} | https://other.example.org/ | {chosen_method} |\n'
        plan = preview_research_scope(config, path, source, filename='scope.md', transport=forbid_gokb())
        assert plan.rows[0].service_status == 'invalid'
        assert plan.rows[0].journal.access_service_id is None
        assert plan.proposed.access_services == before.state.access_services
    else:
        with pytest.raises(ValueError):
            choose_journal_service(config, journal.key, method=chosen_method, name=name, url='https://other.example.org/',
                expected_revision=before.revision, expected_monitor_revision=load_settings(config).draft.monitor_revision)
    assert load_user_state(config) == before


def test_new_imported_carsi_service_uses_official_url_instead_of_imported_url(tmp_path):
    registry(tmp_path)
    source = '| Journal | Service | Access URL | Access Method |\n| --- | --- | --- | --- |\n| Annals | EBSCO | https://untrusted.example.org/login | carsi |\n'
    plan = preview_research_scope(tmp_path / 'monitor.yaml', tmp_path / 'list.md', source,
        filename='scope.md', transport=forbid_gokb())
    assert plan.rows[0].service_status == 'verified'
    assert plan.proposed.access_services[0].access_url == 'http://search.ebscohost.com/'


def test_http_import_confirm_binds_the_preview_without_querying_gokb_again(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from safety_config_helpers import current_mapping_document
    from settings_api_helpers import form
    config, legacy, _, _ = current_mapping_document(tmp_path)
    from test_resource_resolver import gokb_transport, title
    gokb = gokb_transport(titles=[title(identifier='0090-5364')])
    requests = []
    def handler(request):
        requests.append(request.url.params['componentType'])
        return gokb.handle_request(request)
    stub_gokb_http(monkeypatch, handler)

    original_legacy = legacy.read_bytes()
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        state = client.get('/api/ui-next/settings').json()
        source = b'- Annals\n- Biometrics\n'
        before = load_user_state(config)
        preview = client.post('/settings/import/preview', data=form(state) | {'query_gokb': 'yes'},
            files={'markdown_file':('scope.md', source)}).json()
        assert preview['import_plan'], preview['message']
        assert [r['status'] for r in preview['import_plan']['rows']] == ['add','skip']
        assert preview['import_plan']['rows'][0]['resolution']['status'] == 'unique'
        assert requests == ['JournalInstance', 'TitleInstancePackagePlatform', 'Platform']
        assert load_user_state(config).revision == before.revision
        confirmation = form(state) | dict(markdown_import_payload=preview['import_payload'], markdown_import_filename='scope.md', markdown_import_proof=preview['import_proof'], confirm_full_import='yes')
        tampered = client.post('/settings/import/confirm', data=confirmation | {'import_choices':'{"0":{"skip":true}}'}).json()
        assert not tampered['saved']
        assert load_user_state(config).revision == before.revision
        saved = client.post('/settings/import/confirm', data=confirmation).json()
        assert saved['saved'], saved['message']
        assert [j['name'] for j in saved['values']['journals']] == ['Biometrics','Annals']
        assert saved['values']['journals'][0]['access_service_id'] == state['values']['journals'][0]['access_service_id']
        assigned = next(service for service in saved['values']['access_services']
                        if service['id'] == saved['values']['journals'][1]['access_service_id'])
        assert assigned['name'] == 'Springer Link'
        assert requests == ['JournalInstance', 'TitleInstancePackagePlatform', 'Platform']
        assert not client.post('/settings/import/confirm', data=confirmation).json()['saved']
        assert client.post('/settings/export-ai-mapping-pack', data=form(saved)).status_code == 404
        exported = client.post('/settings/export', data=form(saved))
        assert exported.status_code == 200 and 'svc_' not in exported.text
    assert legacy.read_bytes() == original_legacy


def test_ambiguous_and_substring_names_require_choice_and_corrected_identifiers_are_verified(tmp_path, empty_openalex):
    registry(tmp_path, [
        ('Annals', '0090-5364', None, 'IMS', 'Scopus', 'Active'),
        ('Annals', '1932-6157', None, 'IMS', 'SCIE', None),
        ('Biometrics', '0006-341X', None, 'Wiley', 'SCIE', None),
    ])
    config = tmp_path/'target.yaml'
    source = '# Research Scope\n\n- Annals\n- Biom\n- Unknown title\n'
    first = preview_research_scope(config, tmp_path/'list.md', source, filename='scope.md', client=empty_openalex)
    assert [r.status for r in first.rows] == ['unresolved','unresolved','unresolved']
    assert not (tmp_path/'.allfold').exists()
    corrected = preview_research_scope(config, tmp_path/'list.md', source, filename='scope.md', choices={
        '0': {'candidate': {'issn': '0090-5364', 'eissn': None}},
        '1': {'journal':'Biometrics','issn':'0006-341X'},
        '2': {'journal':'Biometrics','issn':'0006-3411'},
    })
    assert [r.status for r in corrected.rows] == ['add','add','unresolved']
    confirm_research_scope(corrected)
    assert [j.key for j in load_user_state(config).state.journals] == ['0090-5364','0006-341X']


@pytest.mark.parametrize('eissn', ['1541-0420', '0090-5364'])
@pytest.mark.parametrize('source', [
    '- Biometrics\n',
    '| Journal | ISSN |\n| --- | --- |\n| Biometrics | 0006-341X |\n',
])
def test_ambiguous_candidates_sharing_print_issn_can_select_either_complete_pair(tmp_path, eissn, source):
    registry(tmp_path, [
        ('Biometrics', '0006-341X', '1541-0420', 'Wiley', 'SCIE', None),
        ('Biometrics', '0006-341X', '0090-5364', 'Wiley', 'Scopus', 'Active'),
    ])
    config, path = tmp_path / 'target.yaml', tmp_path / 'list.md'
    first = preview_research_scope(config, path, source, filename='scope.md')
    assert first.rows[0].status == 'unresolved'
    assert len(first.rows[0].candidates) == 2
    assert not (tmp_path / '.allfold').exists()
    chosen = preview_research_scope(config, path, source, filename='scope.md', choices={
        '0': {'candidate': {'issn': '0006-341X', 'eissn': eissn}},
    })
    assert chosen.rows[0].status == 'add', chosen.rows[0].messages
    expected = JournalConfig(name='Biometrics', issn='0006-341X', eissn=eissn)
    assert chosen.rows[0].journal == expected
    confirm_research_scope(chosen)
    assert load_user_state(config).state.journals == (expected,)


def test_invalid_supplied_service_and_remote_failure_do_not_block_identified_journal(tmp_path):
    import httpx
    registry(tmp_path)
    def offline(request):
        raise httpx.ConnectError('offline', request=request)
    source = '| Journal | ISSN | Service | Access Method |\n| --- | --- | --- | --- |\n| Biometrics | 0006-341X | Definitely invented | carsi |\n| Annals | 0090-5364 | Library | manual |\n'
    config = tmp_path/'target.yaml'
    plan = preview_research_scope(config, tmp_path/'list.md', source, filename='scope.md', query_gokb=True, transport=httpx.MockTransport(offline))
    assert [r.status for r in plan.rows] == ['add','add']
    assert [r.service_status for r in plan.rows] == ['invalid','invalid']
    assert all(r.resolution.status == 'unavailable' for r in plan.rows)
    confirm_research_scope(plan)
    assert not load_user_state(config).state.access_services
    assert all(j.access_service_id is None for j in load_user_state(config).state.journals)


def test_explicit_import_service_choices_take_precedence_over_gokb(tmp_path):
    registry(tmp_path)
    source = ('| Journal | ISSN | Service |\n| --- | --- | --- |\n'
              '| Annals | 0090-5364 | EBSCO |\n| Biometrics | 0006-341X | EBSCO |\n')
    plan = preview_research_scope(tmp_path / 'target.yaml', tmp_path / 'list.md', source, filename='scope.md',
        choices={'0': {'unresolved': True}, '1': {'service': 'Invented Service', 'access method': 'carsi'}},
        query_gokb=True, transport=forbid_gokb())
    assert [row.service_status for row in plan.rows] == ['unresolved', 'invalid']
    assert all(row.status == 'add' and row.journal.access_service_id is None for row in plan.rows)


def test_http_discovery_and_carsi_save_are_separate_and_preserve_scope(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from safety_config_helpers import current_mapping_document
    from settings_api_helpers import form
    from test_resource_resolver import gokb_transport, title

    config, _, journal, original_service = current_mapping_document(tmp_path)
    other_config = tmp_path / 'other.yaml'
    other_config.write_bytes(config.read_bytes())
    untouched = load_user_state(other_config)
    gokb = gokb_transport(titles=[title(identifier=journal.key)])
    calls, offline = [], False
    def handler(request):
        calls.append(request.url.params['componentType'])
        if offline:
            raise httpx.ConnectError('fixture offline', request=request)
        return gokb.handle_request(request)
    stub_gokb_http(monkeypatch, handler)

    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        state = client.get('/api/ui-next/settings').json()
        base = '/api/ui-next/settings/journals/' + journal.key
        catalog = client.post('/api/ui-next/settings/catalog', data={'csrf_token': state['csrf_token']}).json()
        assert any(row['production'] == 'EBSCO' for row in catalog['resources'])
        assert calls == []
        evidence = client.post(base + '/resolve', data={'csrf_token': state['csrf_token']}).json()
        assert evidence['status'] == 'unique'
        assert evidence['candidates'][0]['evidence'][0]['tipp_uuids'] == ['tipp-0']
        candidate = evidence['unique_candidate']['resource']
        assert load_user_state(config).state.journals[0].access_service_id == original_service.id
        assert client.post(base + '/service', data=form(state) | {
            'selection_method': 'unresolved', 'csrf_token': 'wrong'}).status_code == 403
        assert client.post(base + '/service', data=form(state) | {
            'selection_method': 'carsi', 'selection_name': 'Invented Service'}).status_code == 409
        selected = client.post(base + '/service', data=form(state) | {
            'selection_method': 'carsi', 'selection_name': candidate['production'],
            'selection_url': 'https://untrusted.example/login'}).json()
        assert selected.get('saved'), selected
        saved = load_user_state(config).state
        assigned = next(s for s in saved.access_services if s.id == saved.journals[0].access_service_id)
        assert assigned.name == 'Springer Link'
        assert assigned.access_url == next(row['url'].strip() for row in catalog['resources'] if row['production'] == assigned.name)
        assert calls == ['JournalInstance', 'TitleInstancePackagePlatform', 'Platform']

        # A stale Settings form cannot replace the explicit choice.
        assert client.post(base + '/service', data=form(state) | {'selection_method': 'unresolved'}).status_code == 409
        unresolved = client.post(base + '/service', data=form(selected) | {'selection_method': 'unresolved'}).json()
        assert unresolved['saved'] and not unresolved['values']['journals'][0]['access_service_id']
        offline = True
        failed = client.post(base + '/resolve', data={'csrf_token': state['csrf_token']}).json()
        assert failed['status'] == 'unavailable' and failed['error'] and failed['unique_candidate'] is None
        chosen = client.post(base + '/service', data=form(unresolved) | {
            'selection_method': 'carsi', 'selection_name': 'EBSCO'}).json()
        assert chosen['saved']
        assert calls == ['JournalInstance', 'TitleInstancePackagePlatform', 'Platform', 'JournalInstance']
        assert client.post(base + '/service', data=form(chosen) | {
            'selection_method': 'manual', 'selection_name': 'Library', 'selection_url': 'http://127.0.0.1/'}).status_code == 409
        manual = client.post(base + '/service', data=form(chosen) | {
            'selection_method': 'manual', 'selection_name': 'Euclid', 'selection_url': 'https://projecteuclid.org/'}).json()
        assert manual['saved']
    assert load_user_state(other_config) == untouched


def test_http_import_rejects_concurrent_state_and_yaml_edits(tmp_path):
    from dataclasses import replace
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    from safety_config_helpers import current_mapping_document
    from settings_api_helpers import form
    from allfold.persistence.user_state import compare_write_user_state
    config, _, _, _ = current_mapping_document(tmp_path)
    with TestClient(create_app(config, electron_bridge=OfflineBridge()), base_url='http://localhost') as client:
        state = client.get('/api/ui-next/settings').json()
        preview = client.post('/settings/import/preview', data=form(state), files={'markdown_file':('scope.md',b'- Annals\n')}).json()
        data = form(state) | dict(markdown_import_payload=preview['import_payload'],markdown_import_filename='scope.md',markdown_import_proof=preview['import_proof'],confirm_full_import='yes')
        snapshot = load_user_state(config)
        edited = replace(snapshot.state, groups=(*snapshot.state.groups,'Concurrent'))
        compare_write_user_state(config,edited,snapshot.revision)
        assert not client.post('/settings/import/confirm',data=data).json()['saved']
        state = client.get('/api/ui-next/settings').json()
        preview = client.post('/settings/import/preview', data=form(state), files={'markdown_file':('scope.md',b'- Annals\n')}).json()
        data = form(state) | dict(markdown_import_payload=preview['import_payload'],markdown_import_filename='scope.md',markdown_import_proof=preview['import_proof'],confirm_full_import='yes')
        config.write_bytes(config.read_bytes()+b'# concurrent edit\n')
        assert not client.post('/settings/import/confirm',data=data).json()['saved']
        assert [j.name for j in load_user_state(config).state.journals] == ['Biometrics']


def test_legacy_import_remints_foreign_ids_and_skips_existing_fields(tmp_path):
    from allfold.config import render_settings_list_text
    from safety_config_helpers import current_mapping_document
    config, path, existing, old_service = current_mapping_document(tmp_path)
    old = load_user_state(config)
    foreign = AccessService(id=old_service.id, name='EBSCO', access_url='https://search.ebscohost.com/')
    imported = (existing.model_copy(update={'name':'Biometrics','group':'Changed','labels':('New',),'access_service_id':foreign.id}),
                JournalConfig(name='Annals',issn='0090-5364',group='Changed',labels=('New',),access_service_id=foreign.id))
    source = render_settings_list_text(None, imported, path=path, groups=('Changed',), custom_labels=('New',),access_services=(foreign,))
    plan = preview_research_scope(config,path,source,filename='legacy.md',transport=forbid_gokb())
    assert [r.status for r in plan.rows] == ['skip','add']
    confirm_research_scope(plan)
    saved = load_user_state(config).state
    assert saved.journals[0] == existing
    assert saved.access_services[0] == old_service
    assert saved.journals[1].access_service_id != foreign.id
    assert next(s for s in saved.access_services if s.id==saved.journals[1].access_service_id).name == 'EBSCO'


def test_settings_uses_catalog_url_and_preserves_its_service_mapping_across_school_changes(tmp_path):
    from dataclasses import replace
    from safety_config_helpers import current_mapping_document
    from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
    from allfold.config import InstitutionConfig

    config, _, journal, service = current_mapping_document(tmp_path)
    draft = load_settings(config).draft
    # An unchanged saved Service can still be kept after leaving the catalog.
    saved = save_settings(config, replace(draft, name='Updated monitor'))
    assert saved.outcome == SettingsSaveOutcome.SAVED
    draft = saved.state.draft
    invalid = replace(draft, access_services=(service.model_copy(update={'name': 'ebsco'}),))
    assert save_settings(config, invalid).outcome == SettingsSaveOutcome.INVALID_DRAFT
    valid = replace(draft, access_services=(service.model_copy(update={
        'name': 'EBSCO', 'access_url': 'https://untrusted.example/login'}),))
    result = save_settings(config, valid)
    assert result.outcome == SettingsSaveOutcome.SAVED
    assert result.state.draft.access_services[0].name == 'EBSCO'
    assert result.state.draft.access_services[0].access_url == 'http://search.ebscohost.com/'
    assert result.state.draft.access_services[0].id == service.id
    stored = load_user_state(config)
    assert stored.state.journals[0].access_service_id == journal.access_service_id

    changed_school = replace(result.state.draft, institution=InstitutionConfig(
        name='Other University', idp_entity_id='https://other-school.example/idp', use_shibboleth=True))
    assert save_settings(config, changed_school).outcome == SettingsSaveOutcome.SAVED
    assert load_user_state(config) == stored


def test_existing_identity_skips_before_metadata_lookup_and_cross_journal_overlap_is_conflict(tmp_path):
    from safety_config_helpers import current_mapping_document
    from allfold.persistence.user_state import compare_write_user_state
    from dataclasses import replace
    config,path,journal,_ = current_mapping_document(tmp_path)
    initial=load_user_state(config)
    compare_write_user_state(config,replace(initial.state,journals=(journal,JournalConfig(name='Annals',issn='0090-5364'))),initial.revision)
    source='| Journal | ISSN | eISSN |\n| --- | --- | --- |\n| Altered imported name | 0006-341X | |\n| Conflicting identity | 0006-341X | 0090-5364 |\n'
    plan=preview_research_scope(config,path,source,filename='scope.md')
    assert [r.status for r in plan.rows] == ['skip','conflict']
    assert plan.proposed == load_user_state(config).state


def test_openalex_fallback_verifies_both_identifiers_without_guessing_media(tmp_path):
    from allfold.providers.openalex import OpenAlexClient
    registry(tmp_path)
    def handle(request):
        return httpx.Response(200, json={'id':'https://openalex.org/S1','type':'journal','display_name':'Remote Journal','issn':['1234-5679','2345-6787'],'issn_l':'1234-5679'})
    with OpenAlexClient(transport=httpx.MockTransport(handle)) as provider:
        plan=preview_research_scope(tmp_path/'new.yaml',tmp_path/'list.md','| Name | ISSN | eISSN |\n| --- | --- | --- |\n| Remote Journal | 1234-5679 | 2345-6787 |\n',filename='scope.md',client=provider)
    assert plan.rows[0].status == 'add'
    assert plan.rows[0].journal.identifiers == ('1234-5679','2345-6787')


@pytest.mark.parametrize('heading', ['# Conferences', '## Conferences', '### CONFERENCES'])
def test_unknown_legacy_section_is_ignored_without_changing_input_or_scope(tmp_path, heading):
    from safety_config_helpers import current_mapping_document
    config, legacy, *_ = current_mapping_document(tmp_path)
    original = legacy.read_bytes()
    saved = load_user_state(config)
    text = export_user_data(config) + f'\n{heading}\n\n- Retired series\n\n| Bad | Legacy | Table |\n| invalid |\n'
    preview = preview_research_scope(config, legacy, text, filename='legacy.md')
    assert preview.proposed == saved.state
    assert all(row.status == 'skip' for row in preview.rows)
    confirmed = confirm_research_scope(preview)
    assert confirmed.revision == saved.revision
    assert legacy.read_bytes() == original
    assert '## Conferences' not in export_user_data(config)
