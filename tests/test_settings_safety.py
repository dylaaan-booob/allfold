"""Settings creation and multi-file compare-and-swap safety."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

import allfold.application.settings as settings_module
from allfold.application.settings import (
    ContentRevision, SettingsIssueSource, SettingsSaveOutcome, load_settings, save_settings,
)
from allfold.config import (
    AccessService, JournalConfig, load_config,
    parse_settings_list_text, render_settings_list_text,
)
from allfold.web.app import create_app
from allfold.web.settings_form import (
    settings_draft_from_form, settings_form_from_draft, settings_form_from_submission,
)
from safety_config_helpers import A, B, P1, P2, current_mapping_document


def stamp(path: Path):
    info = path.stat()
    return path.read_bytes(), info.st_ino, info.st_mtime_ns


def start(tmp_path: Path):
    config, path, journal, service = current_mapping_document(tmp_path)
    return config, path, load_settings(config).draft


def missing_monitor(tmp_path: Path):
    config, path, _ = start(tmp_path)
    config.unlink()
    opened = load_settings(config)
    assert opened.draft.monitor_revision == ContentRevision(exists=False, digest=None)
    assert len(opened.issues) == 1
    assert opened.issues[0].source is SettingsIssueSource.MONITOR_CONFIG
    return config, path, replace(
        opened.draft, name="Recovered Monitor", keyword_expression="causal",
    )


def test_creation_race_at_exclusive_write_boundary_preserves_external_file(tmp_path: Path, monkeypatch):
    config, path, draft = missing_monitor(tmp_path)
    before_list = stamp(path)
    original_write = settings_module._write_snapshot_target
    def create_externally_before_save(target, contents, snapshot):
        if target == config:
            assert not snapshot.revision.exists
            config.write_text("name: External writer\n", encoding="utf-8")
        return original_write(target, contents, snapshot)
    monkeypatch.setattr(settings_module, "_write_snapshot_target", create_externally_before_save)

    result = save_settings(config, draft)

    assert result.outcome is SettingsSaveOutcome.REVISION_CONFLICT
    assert not result.journal_written and not result.monitor_written
    assert config.read_text() == "name: External writer\n"
    assert stamp(path) == before_list


def test_corrupt_existing_monitor_is_not_replaced_by_recovered_defaults(tmp_path: Path):
    config, path, draft = missing_monitor(tmp_path)
    config.write_text("venue_whitelist: [\n", encoding="utf-8")
    opened = load_settings(config)
    assert opened.draft.monitor_revision.exists
    assert any(issue.source is SettingsIssueSource.MONITOR_CONFIG for issue in opened.issues)
    before_list, before_monitor = stamp(path), stamp(config)

    rejected = save_settings(config, replace(
        opened.draft, name="Repaired?", keyword_expression="causal",
    ))

    assert rejected.outcome is SettingsSaveOutcome.INVALID_DRAFT
    assert not rejected.journal_written and not rejected.monitor_written
    assert (stamp(path), stamp(config)) == (before_list, before_monitor)


def form_data(values):
    entries = [
        ("name", values.name), ("keyword_expression", values.keyword_expression),
        ("output_dir", values.output_dir), ("log_level", values.log_level),
        ("from_month", values.from_month), ("to_month", values.to_month),
        ("monitor_revision_exists", values.monitor_revision_exists),
        ("monitor_revision_digest", values.monitor_revision_digest),
        ("journal_revision_exists", values.journal_revision_exists),
        ("journal_revision_digest", values.journal_revision_digest),
        ("institution_name", values.institution_name),
        ("institution_idp_entity_id", values.institution_idp_entity_id),
        ("institution_use_shibboleth", "1" if values.institution_use_shibboleth else ""),
    ]
    entries.extend(("settings_group", name) for name in values.groups)
    entries.extend(("settings_custom_label", name) for name in values.custom_labels)
    for j in values.journals:
        entries.extend((("journal_name",j.name),("journal_issn",j.issn),("journal_eissn",j.eissn),
                        ("journal_group",j.group),("journal_labels",j.labels),("journal_access_service_id",j.access_service_id)))
    for s in values.access_services:
        entries.extend((("service_id", s.id), ("service_name", s.name), ("service_access_url", s.access_url), ("service_access_method", s.access_method)))
    return FormData(entries)


def test_monitor_conflict_after_target_preparation_blocks_journal_write(tmp_path: Path, monkeypatch):
    config, path, draft = start(tmp_path)
    draft = replace(draft, access_services=(
        draft.access_services[0].model_copy(update={"access_url": "https://example.org/edited"}),))
    journal_before = stamp(path)
    original_render = settings_module.render_settings_list_text
    def render(*args, **kwargs):
        target = original_render(*args, **kwargs)
        config.write_bytes(config.read_bytes() + b"# concurrent monitor edit\n")
        return target
    monkeypatch.setattr(settings_module, "render_settings_list_text", render)
    result = save_settings(config, draft)
    assert result.outcome is SettingsSaveOutcome.REVISION_CONFLICT
    assert not result.journal_written and not result.monitor_written
    assert stamp(path) == journal_before


def test_second_file_cas_conflict_reports_written_list(tmp_path: Path, monkeypatch):
    config, path, draft = start(tmp_path)
    draft = replace(draft, name="Edited Monitor", access_services=(
        draft.access_services[0].model_copy(update={"access_url": "https://example.org/edited"}),))
    original = settings_module.compare_write_user_state
    def change_monitor_after_state(config_path, state, revision):
        saved = original(config_path, state, revision)
        config.write_bytes(config.read_bytes() + b"# concurrent monitor edit\n")
        return saved
    monkeypatch.setattr(settings_module, "compare_write_user_state", change_monitor_after_state)
    result = save_settings(config, draft)
    assert result.outcome is SettingsSaveOutcome.PARTIAL_SAVE
    assert result.journal_written and not result.monitor_written
    assert result.state.draft.access_services[0].access_url == "https://example.org/edited"
    assert result.state.draft.name != "Edited Monitor"
