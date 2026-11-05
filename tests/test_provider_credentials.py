"""Only OpenAlex has an API credential entry in ordinary Run settings."""
from dataclasses import replace

import pytest
from pydantic import SecretStr

from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
from allfold.config import load_config
from allfold.integrations.openalex_credentials import credential_path, read_credential
from safety_config_helpers import current_mapping_document


def test_retired_pubmed_credentials_are_ignored_and_preserved(tmp_path):
    config, _, _, _ = current_mapping_document(tmp_path)
    retired = config.with_suffix(".pubmed-secrets.json")
    retired.write_text("invalid legacy file; do not parse or delete")
    state = load_settings(config)
    assert not any("pubmed" in field for field in state.draft.__dataclass_fields__)
    assert retired.read_text() == "invalid legacy file; do not parse or delete"
    with pytest.raises(ValueError, match="Unknown"):
        credential_path(config, provider="pubmed")


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
    selected = ("europe_pmc", "crossref", "arxiv")
    saved = save_settings(config, replace(load_settings(config).draft, enabled_providers=selected))
    assert saved.outcome is SettingsSaveOutcome.SAVED
    assert load_settings(config).draft.enabled_providers == selected
    assert load_config(config).enabled_providers == selected
    assert "pubmed" not in config.read_text()
