"""Optional provider keys are explicit secrets, separate from ordinary configuration."""
from dataclasses import replace

import pytest
from pydantic import SecretStr

from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
from allfold.config import ConfigurationError, load_config, parse_monitor_definition
from allfold.integrations.openalex_credentials import credential_path, read_credential
from safety_config_helpers import current_mapping_document


def test_optional_pubmed_credentials_use_revision_checked_explicit_storage(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    state = load_settings(config)
    assert not state.draft.pubmed_key_configured
    saved = save_settings(config, replace(state.draft, pubmed_key_action="replace",
        pubmed_api_key=SecretStr("synthetic-ncbi-key")))
    assert saved.outcome is SettingsSaveOutcome.SAVED
    assert read_credential(config, provider="pubmed")[0] == "synthetic-ncbi-key"
    assert credential_path(config, provider="pubmed").stat().st_mode & 0o777 == 0o600
    assert "synthetic-ncbi-key" not in config.read_text()
    assert "synthetic-ncbi-key" not in repr(load_settings(config))
    stale = save_settings(config, replace(state.draft, pubmed_key_action="clear"))
    assert stale.outcome is SettingsSaveOutcome.REVISION_CONFLICT
    cleared = save_settings(config, replace(load_settings(config).draft, pubmed_key_action="clear"))
    assert cleared.outcome is SettingsSaveOutcome.SAVED
    assert read_credential(config, provider="pubmed")[0] is None


def test_openalex_explicit_credentials_keep_revision_and_clear_contract(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    state = load_settings(config)
    saved = save_settings(config, replace(state.draft, openalex_key_action="replace",
                                          openalex_api_key=SecretStr("synthetic-key-123")))
    assert saved.outcome is SettingsSaveOutcome.SAVED
    key, revision = read_credential(config)
    assert key == "synthetic-key-123" and revision != "missing"
    assert credential_path(config).stat().st_mode & 0o777 == 0o600
    stale = save_settings(config, replace(state.draft, openalex_key_action="clear"))
    assert stale.outcome is SettingsSaveOutcome.REVISION_CONFLICT
    cleared = save_settings(config, replace(load_settings(config).draft, openalex_key_action="clear"))
    assert cleared.outcome is SettingsSaveOutcome.SAVED
    assert read_credential(config)[0] is None


def test_selected_providers_survive_settings_save_and_runtime_load(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    selected = ("pubmed",)
    order = ("wos", *load_settings(config).draft.provider_order[:-1])
    aliases = {"wos": "Web of Science", "crossref": "Crossref Dates"}
    saved = save_settings(config, replace(load_settings(config).draft, enabled_providers=selected,
                                          provider_order=order, provider_aliases=aliases))
    assert saved.outcome is SettingsSaveOutcome.SAVED
    assert load_settings(config).draft.enabled_providers == selected
    assert load_config(config).enabled_providers == selected
    assert load_config(config).provider_order == order
    assert load_settings(config).draft.provider_aliases == aliases
    assert "pubmed" in config.read_text()


@pytest.mark.parametrize("legacy", [{"pubmed_query_mode": "broad"}, {"pubmed_query": "cancer"},
                                     {"enabled_providers": ["europe_pmc"]}])
def test_retired_configuration_reports_explicit_new_config_guidance(tmp_path, legacy):
    with pytest.raises(ConfigurationError, match="config.template.yaml"):
        parse_monitor_definition(tmp_path / "monitor.yaml", {"keyword_expression": "causal",
            "from_month": "2026-01", "to_month": "2026-12", **legacy})


def test_provider_defaults_and_all_nonempty_discovery_combinations(tmp_path):
    from itertools import combinations
    from allfold.config import DEFAULT_PROVIDER_ORDER, ENABLED_PROVIDERS
    from allfold.web.ui_next import provider_expressions
    assert ENABLED_PROVIDERS == ('pubmed','openalex')
    assert DEFAULT_PROVIDER_ORDER[0] == 'pubmed' and 'europe_pmc' in DEFAULT_PROVIDER_ORDER
    for size in range(1,4):
        for selected in combinations(('pubmed','wos','openalex'),size):
            definition = parse_monitor_definition(tmp_path/'monitor.yaml', {'keyword_expression':'causal',
                'from_month':'2026-01','to_month':'2026-12','enabled_providers':selected})
            assert definition.enabled_providers == selected
    with pytest.raises(ConfigurationError, match='one or more'):
        parse_monitor_definition(tmp_path/'monitor.yaml', {'keyword_expression':'causal',
            'from_month':'2026-01','to_month':'2026-12','enabled_providers':[]})
    preview = provider_expressions('causal AND statist*')
    assert preview['pubmed']['expression'] == '(causal[Title/Abstract] AND statist*[Title/Abstract])'
    assert preview['europe_pmc']['expression'] is None


def test_pubmed_secret_never_enters_settings_json_or_ordinary_autosave(tmp_path):
    from fastapi.testclient import TestClient
    from allfold.web.app import create_app
    from electron_test_helpers import OfflineBridge
    config, _, _, _ = current_mapping_document(tmp_path)
    saved = save_settings(config, replace(load_settings(config).draft, pubmed_key_action='replace',
        pubmed_api_key=SecretStr('synthetic-ncbi-secret')))
    assert saved.outcome is SettingsSaveOutcome.SAVED
    with TestClient(create_app(config,electron_bridge=OfflineBridge()),base_url='http://localhost') as client:
        state = client.get('/api/ui-next/settings').json()
        assert state['values']['pubmed_key_configured'] is True
        assert 'synthetic-ncbi-secret' not in str(state)
        result = client.post('/api/ui-next/settings/autosave',json={'csrf_token':state['csrf_token'],
            'base':{key:state['values'][key] for key in ('monitor_revision_exists','monitor_revision_digest','journal_revision_exists','journal_revision_digest')},
            'changes':{'pubmed_api_key':'synthetic-ncbi-secret'}})
        assert result.status_code == 200
        assert result.json()['outcome'] == 'INVALID_DRAFT' and not result.json()['saved']
        assert read_credential(config,provider='pubmed')[0] == 'synthetic-ncbi-secret'
