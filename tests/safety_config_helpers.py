"""Journal identity and direct Access Service configuration contracts."""
from dataclasses import replace
from pathlib import Path

import pytest

from allfold.application.settings import load_settings, save_settings, SettingsSaveOutcome
from allfold.config import (
    AccessService, ConfigurationError, JournalConfig, load_config,
    parse_settings_list_text, render_settings_list_text, validate_access_mapping,
)
from settings_api_helpers import registry

A, B = "0006-341X", "0090-5364"
# Provider identifiers are fixture metadata, never configured Publisher entities.
P1, P2 = "https://openalex.org/P1", "https://openalex.org/P2"


def monitor(tmp_path):
    path = tmp_path / "monitor.yaml"
    path.write_text("name: Test Monitor\nvenue_whitelist: list.md\nkeyword_expression: causal\n"
                    "output_dir: workspace\nfrom_month: 2026-01\nto_month: 2026-01\n")
    return path


def document(tmp_path, contents):
    path = tmp_path / "list.md"
    path.write_text(contents)
    return path


def current_mapping_document(tmp_path):
    service = AccessService.create("University Library", "https://library.example.org")
    journal = JournalConfig(name="Biometrics", issn=A, access_service_id=service.id, group="Statistics")
    config = monitor(tmp_path)
    path = document(tmp_path, render_settings_list_text(
        None, (journal,), access_services=(service,), path=tmp_path / "list.md", groups=("Statistics",), custom_labels=())
        + "\n## Conferences\n\nUser-maintained conference notes.\n")
    registry(tmp_path)
    return config, path, journal, service


