"""Settings application boundary for monitor and journal configuration."""

from __future__ import annotations

import errno
import hashlib
import os
from contextlib import ExitStack
from dataclasses import dataclass, replace, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import SecretStr

from allfold.integrations.openalex_credentials import read_credential, write_credential, validate_key, OpenAlexCredentialError

from allfold.config import (
    AccessService,
    SettingsList, ConferenceConfig, validate_conference_configs, parse_conferences_text,
    DEFAULT_PROVIDER_ORDER,
    parse_access_services_text,
    parse_settings_list_text,
    parse_entity_registry,
    validate_entity_mapping,
    validate_access_mapping,
    ConfigurationError,
    InstitutionConfig,
    KeptWorkflowConfig,
    JournalConfig,
    render_settings_list_text,
    LoadedConfig,
    LogLevel,
    build_loaded_config,
    journal_whitelist_table,
    parse_journal_whitelist_text,
    parse_monitor_definition,
    validate_journal_storage,
    validate_runtime_config,
)
from allfold.application.journal_lookup import verify_journal
from allfold.providers.openalex import OpenAlexClient, OpenAlexError
from allfold.date_range import (
    DateRangeError,
    DateRangeSpec,
    ResolvedDateRange,
)
from allfold.persistence.safe_write import (
    CompareReadError,
    ContentChangedError,
    create_text_exclusive,
    read_text_exact,
    workspace_operation_lock,
    workspace_path_lock,
    replace_regular_text_if_unchanged as replace_text_if_unchanged,
)
from allfold.search import SearchBackendError, SearchExpressionError
from allfold.persistence.user_state import (
    ContentRevision, UserStateError, load_user_state, user_state_path,
    compare_write_user_state,
)

__all__ = [
    "ContentRevision",
    "MonitorDraft",
    "SettingsIssueSource",
    "SettingsIssue",
    "SettingsLoadResult",
    "SettingsValidationOutcome",
    "SettingsValidationResult",
    "SettingsSaveOutcome",
    "SettingsSaveResult",
    "SettingsDeletionApproval",
    "SettingsDeletionPlan",
    "plan_settings_deletions",
    "load_settings",
    "validate_settings",
    "save_settings",
]


@dataclass(frozen=True)
class MonitorDraft:
    name: str
    keyword_expression: str
    journals: tuple[JournalConfig, ...]
    date_spec: DateRangeSpec
    output_dir: Path
    log_level: LogLevel | str
    monitor_revision: ContentRevision
    journal_revision: ContentRevision
    access_services: tuple[AccessService, ...] = ()
    conferences: tuple[ConferenceConfig, ...] = ()
    groups: tuple[str, ...] = ()
    custom_labels: tuple[str, ...] = ()
    institution: InstitutionConfig | None = None
    kept_workflow: KeptWorkflowConfig = KeptWorkflowConfig()
    provider_aliases: dict[str, str] = field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    enabled_providers: tuple[str, ...] = ("openalex",)
    crossref_mailto: str = ""
    openalex_key_configured: bool = field(default=False, compare=False)
    openalex_key_revision: str = "missing"
    openalex_key_error: str = field(default="", compare=False)
    openalex_key_action: str = "keep"
    openalex_api_key: SecretStr | None = field(default=None, repr=False)


@dataclass(frozen=True)
class SettingsDeletionPlan:
    services: tuple[AccessService, ...]
    service_members: tuple[tuple[str, tuple[JournalConfig, ...]], ...]

    @property
    def required(self) -> bool:
        return bool(self.services)


@dataclass(frozen=True)
class SettingsDeletionApproval:
    monitor_revision: ContentRevision
    journal_revision: ContentRevision
    service_ids: tuple[str, ...]


def plan_settings_deletions(saved: MonitorDraft, proposed: MonitorDraft) -> SettingsDeletionPlan:
    """Derive deleted Services and detached Journals from the saved configuration."""
    remaining = {s.id for s in proposed.access_services}
    removed = tuple(s for s in saved.access_services if s.id not in remaining)
    assigned = {j.key: j.access_service_id for j in proposed.journals}
    members = tuple((s.id, tuple(j for j in saved.journals
                                if j.access_service_id == s.id and j.key in assigned
                                and assigned[j.key] is None)) for s in removed)
    return SettingsDeletionPlan(removed, members)


class SettingsIssueSource(str, Enum):
    MONITOR_CONFIG = "monitor_config"
    JOURNAL_DATA = "journal_data"
    VALIDATION = "validation"
    STORAGE = "storage"


@dataclass(frozen=True)
class SettingsIssue:
    source: SettingsIssueSource
    message: str
    field: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class SettingsLoadResult:
    config_path: Path
    journal_path: Path
    venue_whitelist: Path
    draft: MonitorDraft
    issues: tuple[SettingsIssue, ...]


class SettingsValidationOutcome(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True)
class SettingsValidationResult:
    outcome: SettingsValidationOutcome
    issues: tuple[SettingsIssue, ...]
    config: LoadedConfig | None
    resolved_date_range: ResolvedDateRange | None


class SettingsSaveOutcome(str, Enum):
    SAVED = "SAVED"
    INVALID_DRAFT = "INVALID_DRAFT"
    REVISION_CONFLICT = "REVISION_CONFLICT"
    WRITE_FAILED = "WRITE_FAILED"
    PARTIAL_SAVE = "PARTIAL_SAVE"


@dataclass(frozen=True)
class SettingsSaveResult:
    outcome: SettingsSaveOutcome
    validation: SettingsValidationResult
    state: SettingsLoadResult
    issues: tuple[SettingsIssue, ...]
    journal_written: bool
    monitor_written: bool
    monitor_revision: ContentRevision
    journal_revision: ContentRevision
    openalex_key_written: bool = False


@dataclass(frozen=True)
class _FileSnapshot:
    revision: ContentRevision
    contents: str | None
    issue: SettingsIssue | None


@dataclass(frozen=True)
class _DraftFields:
    name: str
    venue_whitelist: Path
    keyword_expression: str
    output_dir: Path
    date_spec: DateRangeSpec
    log_level: LogLevel | str
    institution: InstitutionConfig | None = None
    kept_workflow: KeptWorkflowConfig = KeptWorkflowConfig()
    provider_aliases: dict[str, str] = field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    enabled_providers: tuple[str, ...] = ("openalex",)
    crossref_mailto: str = ""


def _digest(contents: str) -> str:
    return hashlib.sha256(contents.encode("utf-8")).hexdigest()


def _read_snapshot(
    path: Path,
    *,
    source: SettingsIssueSource,
) -> _FileSnapshot:
    try:
        if any(candidate.is_symlink() for candidate in (path, *path.parents)):
            raise OSError("Settings storage path must not contain a symlink")
        if path.exists() and not path.is_file():
            raise OSError("Settings storage must be a regular file")
        contents = read_text_exact(path)
    except FileNotFoundError:
        return _FileSnapshot(
            revision=ContentRevision(exists=False, digest=None),
            contents=None,
            issue=None,
        )
    except UnicodeError as error:
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digest = None
        return _FileSnapshot(
            revision=ContentRevision(exists=True, digest=digest),
            contents=None,
            issue=SettingsIssue(
                source=source,
                message=f"file is not valid UTF-8: {error}",
                path=path,
            ),
        )
    except OSError as error:
        return _FileSnapshot(
            revision=ContentRevision(exists=path.exists(), digest=None),
            contents=None,
            issue=SettingsIssue(
                source=source,
                message=f"unable to read file: {error}",
                path=path,
            ),
        )
    return _FileSnapshot(
        revision=ContentRevision(exists=True, digest=_digest(contents)),
        contents=contents,
        issue=None,
    )


def _default_fields(config_path: Path) -> _DraftFields:
    return _DraftFields(
        name=config_path.stem,
        venue_whitelist=Path("list.md"),
        keyword_expression="",
        output_dir=Path("workspace"),
        date_spec=DateRangeSpec(date.today().strftime("%Y-%m"), date.today().strftime("%Y-%m")),
        log_level=LogLevel.INFO,
    )


def _recovery_fields(config_path: Path, raw: Any) -> _DraftFields:
    defaults = _default_fields(config_path)
    if not isinstance(raw, dict):
        return defaults

    name = raw.get("name")
    keyword = raw.get("keyword_expression")
    venue = raw.get("venue_whitelist")
    output = raw.get("output_dir")
    log_level = raw.get("log_level")
    try:
        institution = InstitutionConfig.model_validate(raw["institution"]) if raw.get("institution") is not None else None
    except ValueError:
        institution = None  # Never project invalid or sensitive institution data.

    try:
        kept_workflow = KeptWorkflowConfig.model_validate(raw.get("kept_workflow", {}))
    except ValueError:
        kept_workflow = defaults.kept_workflow

    recovered_name = name.strip() if isinstance(name, str) else defaults.name
    recovered_keyword = (
        keyword.strip() if isinstance(keyword, str) else defaults.keyword_expression
    )
    recovered_venue = (
        Path(venue) if isinstance(venue, str) and venue.strip() else defaults.venue_whitelist
    )
    recovered_output = (
        Path(output) if isinstance(output, str) and output.strip() else defaults.output_dir
    )
    if isinstance(log_level, str):
        try:
            recovered_log: LogLevel | str = LogLevel(log_level.upper())
        except ValueError:
            recovered_log = log_level
    else:
        recovered_log = defaults.log_level

    recovered_date = DateRangeSpec(
        raw.get("from_month", defaults.date_spec.from_month),
        raw.get("to_month", defaults.date_spec.to_month),
    )

    return _DraftFields(
        name=recovered_name,
        venue_whitelist=recovered_venue,
        keyword_expression=recovered_keyword,
        output_dir=recovered_output,
        date_spec=recovered_date,
        log_level=recovered_log,
        institution=institution,
        kept_workflow=kept_workflow,
        provider_order=raw.get("provider_order", defaults.provider_order),
        enabled_providers=raw.get("enabled_providers", defaults.enabled_providers),
        provider_aliases=raw.get("provider_aliases", {}) if isinstance(raw.get("provider_aliases", {}), dict) else {},
        crossref_mailto=raw.get("crossref_mailto", "") if isinstance(raw.get("crossref_mailto", ""), str) else "",
    )


def _monitor_fields(
    config_path: Path,
    snapshot: _FileSnapshot,
) -> tuple[_DraftFields, tuple[SettingsIssue, ...]]:
    if not snapshot.revision.exists:
        return _default_fields(config_path), (
            SettingsIssue(
                source=SettingsIssueSource.MONITOR_CONFIG,
                message="monitor config file is missing",
                path=config_path,
            ),
        )
    if snapshot.contents is None:
        assert snapshot.issue is not None
        return _default_fields(config_path), (snapshot.issue,)

    try:
        raw = yaml.safe_load(snapshot.contents)
    except yaml.YAMLError as error:
        return _default_fields(config_path), (
            SettingsIssue(
                source=SettingsIssueSource.MONITOR_CONFIG,
                message=f"invalid YAML: {error}",
                path=config_path,
            ),
        )

    try:
        definition = parse_monitor_definition(config_path, raw)
    except ConfigurationError as error:
        return _recovery_fields(config_path, raw), (
            SettingsIssue(
                source=SettingsIssueSource.MONITOR_CONFIG,
                message=str(error),
                field=error.field,
                path=config_path,
            ),
        )

    return (
        _DraftFields(
            name=definition.name,
            venue_whitelist=definition.venue_whitelist,
            keyword_expression=definition.keyword_expression,
            output_dir=definition.output_dir,
            date_spec=definition.date_spec,
            log_level=definition.log_level,
            institution=definition.institution,
            kept_workflow=definition.kept_workflow,
            enabled_providers=definition.enabled_providers,
            provider_order=definition.provider_order, provider_aliases=definition.provider_aliases, crossref_mailto=definition.crossref_mailto,
        ),
        (),
    )


def _journal_storage(contents: str, path: Path) -> tuple[tuple[JournalConfig, ...], ConfigurationError | None]:
    """Keep unambiguous valid rows visible when another row is damaged."""
    try:
        return parse_journal_whitelist_text(contents, path=path), None
    except ConfigurationError as error:
        if sum(line.strip() == "## Journals" for line in contents.splitlines()) > 1:
            raise
        recovered = []
        try:
            columns, rows = journal_whitelist_table(contents, path=path)
        except ConfigurationError:
            rows, columns = (), 0
        header = "## Journals\n\n| Journal | ISSN | eISSN | Access Service ID | Group | Labels |\n| --- | --- | --- | --- | --- | --- |\n"
        for _, row in rows:
            try:
                recovered.extend(parse_journal_whitelist_text(header + row + "\n", path=path))
            except ConfigurationError:
                continue
        unique = tuple(j for j in recovered if all(
            sum(identifier in other.identifiers for other in recovered) == 1 for identifier in j.identifiers
        ))
        return unique, error


def _journal_path(config_path: Path, fields: _DraftFields) -> Path:
    # Retain the lexical path so snapshot checks can reject symlink substitution.
    value = fields.venue_whitelist
    return value.absolute() if value.is_absolute() else (config_path.parent / value).absolute()


def load_settings(config_path: Path) -> SettingsLoadResult:
    """Load an editable Settings state without requiring valid runtime config."""

    config_path = config_path.resolve()
    monitor_snapshot = _read_snapshot(
        config_path,
        source=SettingsIssueSource.MONITOR_CONFIG,
    )
    fields, monitor_issues = _monitor_fields(config_path, monitor_snapshot)
    journal_path = _journal_path(config_path, fields)
    journal_snapshot = _read_journal_snapshot(config_path, journal_path)

    journal_issues: list[SettingsIssue] = [journal_snapshot.issue] if journal_snapshot.issue else []
    journals: tuple[JournalConfig, ...] = ()
    access_services: tuple[AccessService, ...] = ()
    conferences: tuple[ConferenceConfig, ...] = ()
    groups: tuple[str, ...] = ()
    custom_labels: tuple[str, ...] = ()
    if not journal_snapshot.revision.exists:
        journal_issues.append(
            SettingsIssue(
                source=SettingsIssueSource.JOURNAL_DATA,
                message="journal data file is missing",
                path=journal_path,
            )
        )
    elif journal_snapshot.contents is None:
        assert journal_snapshot.issue is not None
    else:
        contents = journal_snapshot.contents
        # 单个受管理区段损坏时，保留其他区段以及 Journals 中仍可信的行；
        # 联合 Schema 校验仅决定是否允许保存，不应清空可展示的数据。
        try:
            journals, damage = _journal_storage(contents, journal_path)
            if damage is not None:
                journal_issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(damage), field="journals", path=journal_path))
        except ConfigurationError as error:
            journal_issues.append(
                SettingsIssue(
                    source=SettingsIssueSource.JOURNAL_DATA,
                    message=str(error),
                    field="journals",
                    path=journal_path,
                )
            )
        # Only the successful SQLite projection owns Conferences. Legacy Markdown
        # is left untouched and is never used for automatic Conference migration.
        if journal_snapshot.issue is None:
            try:
                conferences = parse_conferences_text(contents, path=journal_path)
            except ConfigurationError as error:
                journal_issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error), field="conferences", path=journal_path))
        headings = {line.strip() for line in contents.splitlines()}
        if "## Access Services" in headings:
            try:
                access_services = parse_access_services_text(contents, path=journal_path)
            except ConfigurationError as error:
                journal_issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error), field="access_services", path=journal_path))
        for labels in (False, True):
            try:
                names = parse_entity_registry(contents, path=journal_path, labels=labels)
                if labels:
                    custom_labels = names
                else:
                    groups = names
            except ConfigurationError as error:
                journal_issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error),
                                                    field=error.field, path=journal_path))
        if not journal_issues:
            try:
                parse_settings_list_text(contents, path=journal_path)
            except ConfigurationError as error:
                journal_issues.append(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error),
                                                    field=error.field, path=journal_path))

    credentials = {}
    for provider in ("openalex",):
        try:
            key, key_revision = read_credential(config_path, provider=provider)
            configured, error_text = key is not None, ""
            del key
        except OpenAlexCredentialError as error:
            configured, key_revision, error_text = False, "unreadable", str(error)
        credentials.update({f"{provider}_key_configured": configured,
                            f"{provider}_key_revision": key_revision, f"{provider}_key_error": error_text})
    draft = MonitorDraft(
        **credentials,
        name=fields.name,
        keyword_expression=fields.keyword_expression,
        journals=journals,
        conferences=conferences,
        access_services=access_services,
        groups=groups,
        custom_labels=custom_labels,
        date_spec=fields.date_spec,
        output_dir=fields.output_dir,
        log_level=fields.log_level,
        monitor_revision=monitor_snapshot.revision,
        journal_revision=journal_snapshot.revision,
        institution=fields.institution,
        kept_workflow=fields.kept_workflow,
        enabled_providers=fields.enabled_providers,
        provider_order=fields.provider_order, provider_aliases=fields.provider_aliases, crossref_mailto=fields.crossref_mailto,
    )
    return SettingsLoadResult(
        config_path=config_path,
        journal_path=journal_path,
        venue_whitelist=fields.venue_whitelist,
        draft=draft,
        issues=tuple((*monitor_issues, *journal_issues)),
    )


def _read_journal_snapshot(config_path: Path, legacy_path: Path) -> _FileSnapshot:
    """Project SQLite for existing editor/exchange adapters; never read it as authority."""
    try:
        snapshot = load_user_state(config_path, legacy_path)
        state = snapshot.state
        contents = render_settings_list_text(None, state.journals, path=legacy_path,
                                            groups=state.groups, custom_labels=state.custom_labels,
                                            access_services=state.access_services, conferences=state.conferences)
        return _FileSnapshot(snapshot.revision, contents, None)
    except ConfigurationError as error:
        # Invalid initial Markdown can still be inspected, but its issue blocks Save.
        path = user_state_path(config_path)
        legacy = _read_snapshot(legacy_path, source=SettingsIssueSource.JOURNAL_DATA) if not path.exists() else None
        return _FileSnapshot(ContentRevision(True, None) if legacy is None else legacy.revision,
                             legacy.contents if legacy else None,
                             SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error),
                                           field=error.field, path=path))


def _draft_monitor_mapping(
    draft: MonitorDraft,
    *,
    venue_whitelist: Path,
) -> dict[str, object]:
    raw: dict[str, object] = {
        "name": draft.name,
        "venue_whitelist": venue_whitelist,
        "keyword_expression": draft.keyword_expression,
        "enabled_providers": draft.enabled_providers,
        "provider_order": draft.provider_order,
        "provider_aliases": draft.provider_aliases,
        "crossref_mailto": draft.crossref_mailto,
        "output_dir": draft.output_dir,
        "log_level": draft.log_level,
    }
    raw["from_month"] = draft.date_spec.from_month
    raw["to_month"] = draft.date_spec.to_month
    raw["institution"] = draft.institution
    raw["kept_workflow"] = draft.kept_workflow
    return raw


def validate_settings(
    config_path: Path,
    draft: MonitorDraft,
) -> SettingsValidationResult:
    """Validate an unsaved draft using the runtime deterministic rule boundary."""

    config_path = config_path.resolve()
    monitor_snapshot = _read_snapshot(
        config_path,
        source=SettingsIssueSource.MONITOR_CONFIG,
    )
    storage_fields, _ = _monitor_fields(config_path, monitor_snapshot)
    try:
        definition = parse_monitor_definition(
            config_path,
            _draft_monitor_mapping(
                draft,
                venue_whitelist=storage_fields.venue_whitelist,
            ),
        )
        for provider in ("openalex",):
            action = getattr(draft, f"{provider}_key_action")
            secret = getattr(draft, f"{provider}_api_key")
            if action not in {"keep", "replace", "clear"}:
                raise ConfigurationError("Invalid API Key action", field=f"{provider}_api_key")
            if action == "replace" and not validate_key(secret.get_secret_value() if secret else None, provider=provider):
                raise ConfigurationError("API Key has an invalid format", field=f"{provider}_api_key")
        validate_access_mapping(draft.journals, draft.access_services)
        config = build_loaded_config(config_path, definition, draft.journals, draft.conferences)
        validate_journal_storage(config.journals)
        validate_entity_mapping(draft.journals, draft.groups, draft.custom_labels)
        validate_entity_mapping(validate_conference_configs(draft.conferences), draft.groups, draft.custom_labels)
        resolved = validate_runtime_config(config, today=date.today())
    except ConfigurationError as error:
        return SettingsValidationResult(
            outcome=SettingsValidationOutcome.INVALID,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.VALIDATION,
                    message=str(error),
                    field=error.field,
                    path=error.path or config_path,
                ),
            ),
            config=None,
            resolved_date_range=None,
        )
    except SearchExpressionError as error:
        return SettingsValidationResult(
            outcome=SettingsValidationOutcome.INVALID,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.VALIDATION,
                    message=str(error),
                    field="keyword_expression",
                    path=config_path,
                ),
            ),
            config=None,
            resolved_date_range=None,
        )
    except SearchBackendError as error:
        return SettingsValidationResult(
            outcome=SettingsValidationOutcome.INVALID,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.VALIDATION,
                    message=str(error),
                    field="keyword_expression",
                    path=config_path,
                ),
            ),
            config=None,
            resolved_date_range=None,
        )
    except DateRangeError as error:
        return SettingsValidationResult(
            outcome=SettingsValidationOutcome.INVALID,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.VALIDATION,
                    message=str(error),
                    field=error.field,
                    path=config_path,
                ),
            ),
            config=None,
            resolved_date_range=None,
        )

    return SettingsValidationResult(
        outcome=SettingsValidationOutcome.VALID,
        issues=(),
        config=config,
        resolved_date_range=resolved,
    )


def _render_monitor_yaml(
    draft: MonitorDraft,
    *,
    venue_whitelist: Path,
) -> str:
    values: dict[str, object] = {
        "name": draft.name,
        "venue_whitelist": str(venue_whitelist),
        "keyword_expression": draft.keyword_expression,
        "enabled_providers": list(draft.enabled_providers),
        "provider_order": list(draft.provider_order),
        "provider_aliases": draft.provider_aliases,
        "crossref_mailto": draft.crossref_mailto,
        "output_dir": str(draft.output_dir),
    }
    values["from_month"] = draft.date_spec.from_month
    values["to_month"] = draft.date_spec.to_month
    values["log_level"] = (
        draft.log_level.value
        if isinstance(draft.log_level, LogLevel)
        else str(draft.log_level)
    )
    if draft.institution is not None and (draft.institution.name or draft.institution.idp_entity_id or draft.institution.use_shibboleth):
        values["institution"] = draft.institution.model_dump(exclude_none=True)
    values["kept_workflow"] = draft.kept_workflow.model_dump(exclude_none=True)
    return yaml.safe_dump(values, sort_keys=False, allow_unicode=True)


def _write_snapshot_target(
    path: Path,
    contents: str,
    snapshot: _FileSnapshot,
) -> None:
    if snapshot.revision.exists:
        if snapshot.contents is None:
            raise CompareReadError("existing file could not be read exactly")
        replace_text_if_unchanged(
            path,
            contents,
            expected_contents=snapshot.contents,
        )
    else:
        create_text_exclusive(path, contents)


def _result_from_state(
    *,
    outcome: SettingsSaveOutcome,
    validation: SettingsValidationResult,
    state: SettingsLoadResult,
    issues: tuple[SettingsIssue, ...],
    journal_written: bool,
    monitor_written: bool,
) -> SettingsSaveResult:
    return SettingsSaveResult(
        outcome=outcome,
        validation=validation,
        state=state,
        issues=issues,
        journal_written=journal_written,
        monitor_written=monitor_written,
        monitor_revision=state.draft.monitor_revision,
        journal_revision=state.draft.journal_revision,
    )


def save_settings(
    config_path: Path, draft: MonitorDraft, *, client: OpenAlexClient | None = None,
    deletion_approval: SettingsDeletionApproval | None = None,
) -> SettingsSaveResult:
    """Workspace-path changes share exclusion with batch/Run/decisions."""
    state = load_settings(config_path)
    def workspace_path(value):
        return Path(os.path.abspath(value if value.is_absolute() else config_path.absolute().parent / value))
    old, new = workspace_path(state.draft.output_dir), workspace_path(draft.output_dir)
    try:
        with ExitStack() as stack:
            locks = []
            for path in sorted({old, new}):
                if path.exists() or path.is_symlink():
                    locks.append(stack.enter_context(workspace_operation_lock(path)))
                else:
                    # Reset owns absent targets too; existence cannot bypass exclusion.
                    stack.enter_context(workspace_path_lock(path))
            changed_keys = [provider for provider in ("openalex",)
                            if getattr(draft, f"{provider}_key_action") != "keep"]
            for provider in changed_keys:
                try:
                    _, actual = read_credential(config_path, provider=provider)
                    if actual != getattr(draft, f"{provider}_key_revision"):
                        raise ContentChangedError("Credentials changed; reload Settings")
                except (OpenAlexCredentialError, ContentChangedError) as error:
                    return _result_from_state(outcome=SettingsSaveOutcome.REVISION_CONFLICT,
                        validation=validate_settings(config_path, draft), state=load_settings(config_path),
                        issues=(SettingsIssue(SettingsIssueSource.STORAGE, str(error), field=f"{provider}_api_key"),),
                        journal_written=False, monitor_written=False)
            result = _save_settings(config_path, draft, client=client, operation_locks=tuple(locks),
                                    deletion_approval=deletion_approval)
            if result.outcome is not SettingsSaveOutcome.SAVED:
                return result
            written = {}
            for provider in changed_keys:
                action = getattr(draft, f"{provider}_key_action")
                secret = getattr(draft, f"{provider}_api_key")
                target_key = secret.get_secret_value() if action == "replace" and secret else None
                revision = getattr(draft, f"{provider}_key_revision")
                try:
                    for lock in locks:
                        lock.verify()
                    write_credential(config_path, provider=provider, action=action, key=target_key, revision=revision)
                except (OpenAlexCredentialError, ContentChangedError, CompareReadError, OSError) as error:
                    committed = False
                    try:
                        actual_key, actual_revision = read_credential(config_path, provider=provider)
                        committed = actual_revision != revision and actual_key == target_key
                    except OpenAlexCredentialError:
                        pass
                    written[f"{provider}_key_written"] = committed
                    partial = result.journal_written or result.monitor_written or any(written.values())
                    outcome = SettingsSaveOutcome.PARTIAL_SAVE if partial else (
                        SettingsSaveOutcome.REVISION_CONFLICT if isinstance(error, ContentChangedError) else SettingsSaveOutcome.WRITE_FAILED)
                    return replace(result, outcome=outcome, state=load_settings(config_path), **written,
                        issues=(SettingsIssue(SettingsIssueSource.STORAGE,
                            f"{provider} API Key save did not finish; reload and reconcile Settings", field=f"{provider}_api_key"),))
                written[f"{provider}_key_written"] = True
            return replace(result, state=load_settings(config_path), **written)

    except (CompareReadError, ContentChangedError, OSError) as error:
        invalid_path = isinstance(error, OSError) and error.errno in (errno.ELOOP, errno.ENOTDIR)
        return _result_from_state(
            outcome=SettingsSaveOutcome.INVALID_DRAFT if invalid_path else SettingsSaveOutcome.WRITE_FAILED,
            validation=validate_settings(config_path, draft),
            state=load_settings(config_path),
            issues=(SettingsIssue(SettingsIssueSource.STORAGE, f"Workspace path change refused: {error}"),),
            journal_written=False, monitor_written=False,
        )


def _save_settings(
    config_path: Path,
    draft: MonitorDraft,
    *, client: OpenAlexClient | None = None, operation_locks: tuple = (),
    deletion_approval: SettingsDeletionApproval | None = None,
) -> SettingsSaveResult:
    """Validate and persist SQLite state and YAML with explicit partial-save semantics."""

    config_path = config_path.absolute()
    validation = validate_settings(config_path, draft)
    if validation.outcome is SettingsValidationOutcome.INVALID:
        state = load_settings(config_path)
        return _result_from_state(
            outcome=SettingsSaveOutcome.INVALID_DRAFT,
            validation=validation,
            state=state,
            issues=validation.issues,
            journal_written=False,
            monitor_written=False,
        )

    stored_state = load_settings(config_path)
    journal_path = stored_state.journal_path

    monitor_snapshot = _read_snapshot(
        config_path,
        source=SettingsIssueSource.MONITOR_CONFIG,
    )
    journal_snapshot = _read_journal_snapshot(config_path, journal_path)
    read_issues = tuple(
        issue
        for issue in (monitor_snapshot.issue, journal_snapshot.issue)
        if issue is not None
    )
    if read_issues:
        state = load_settings(config_path)
        return _result_from_state(
            outcome=SettingsSaveOutcome.WRITE_FAILED,
            validation=validation,
            state=state,
            issues=read_issues,
            journal_written=False,
            monitor_written=False,
        )

    if (
        monitor_snapshot.revision != draft.monitor_revision
        or journal_snapshot.revision != draft.journal_revision
    ):
        state = load_settings(config_path)
        return _result_from_state(
            outcome=SettingsSaveOutcome.REVISION_CONFLICT,
            validation=validation,
            state=state,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.STORAGE,
                    message="Settings files changed after they were opened",
                ),
            ),
            journal_written=False,
            monitor_written=False,
        )

    storage_fields, _ = _monitor_fields(config_path, monitor_snapshot)
    list_unchanged = (
        (draft.journals, draft.access_services, draft.groups, draft.custom_labels, draft.conferences)
        == (stored_state.draft.journals, stored_state.draft.access_services,
            stored_state.draft.groups, stored_state.draft.custom_labels, stored_state.draft.conferences)
    )
    # 缺失的 Monitor 可以由用户明确提交的有效 Draft 首次创建；
    # 已存在但损坏的 Monitor，以及任何 Journal/Mapping 问题都不能借此覆盖。
    blocking_issues = tuple(
        issue for issue in stored_state.issues
        if not (
            not monitor_snapshot.revision.exists
            and issue.source is SettingsIssueSource.MONITOR_CONFIG
            and issue.message == "monitor config file is missing"
        )
    )
    # 可信行恢复仅用于展示；损坏磁盘不能经普通 Save 修复。
    try:
        if blocking_issues:
            raise ConfigurationError("Settings storage has unresolved issues; reload or repair explicitly")
        if journal_snapshot.contents is None:
            raise ConfigurationError("journal configuration is missing")
        parse_settings_list_text(journal_snapshot.contents, path=journal_path)
        deletion_plan = plan_settings_deletions(stored_state.draft, draft)
        if deletion_plan.required:
            expected = SettingsDeletionApproval(
                draft.monitor_revision, draft.journal_revision,
                tuple(s.id for s in deletion_plan.services),
            )
            if deletion_approval != expected:
                raise ConfigurationError("Deletion requires current Settings Preview/Confirm",
                                         field="access_services")
    except ConfigurationError as error:
        return _result_from_state(
            outcome=SettingsSaveOutcome.INVALID_DRAFT, validation=validation,
            state=stored_state,
            issues=(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error),
                                  field=error.field, path=journal_path),),
            journal_written=False, monitor_written=False,
        )

    try:
        if not list_unchanged:
            draft = _resolve_settings_targets(config_path, draft, journal_snapshot, storage_fields, client,
                                             deletion_approval=deletion_approval)
            validation = validate_settings(config_path, draft)
        if validation.outcome is SettingsValidationOutcome.INVALID:
            raise ConfigurationError("; ".join(i.message for i in validation.issues))
        if validation.config is not None:
            draft = replace(draft, institution=validation.config.institution,
                            kept_workflow=validation.config.kept_workflow)
    except (ConfigurationError, OpenAlexError, ValueError) as error:
        return _result_from_state(
            outcome=SettingsSaveOutcome.INVALID_DRAFT, validation=validation,
            state=load_settings(config_path),
            issues=(SettingsIssue(SettingsIssueSource.VALIDATION, str(error)),),
            journal_written=False, monitor_written=False,
        )

    # Provider work is transient. Recheck BOTH original revisions before any write.
    monitor_snapshot = _read_snapshot(config_path, source=SettingsIssueSource.MONITOR_CONFIG)
    journal_snapshot = _read_journal_snapshot(config_path, journal_path)
    if monitor_snapshot.revision != draft.monitor_revision or journal_snapshot.revision != draft.journal_revision:
        return _result_from_state(
            outcome=SettingsSaveOutcome.REVISION_CONFLICT, validation=validation,
            state=load_settings(config_path),
            issues=(SettingsIssue(SettingsIssueSource.STORAGE, "Settings files changed during metadata resolution"),),
            journal_written=False, monitor_written=False,
        )
    try:
        # 数据归属决定写入目标。纯用户状态编辑不触及 YAML。
        journal_changed = (
            (draft.journals, draft.access_services, draft.groups, draft.custom_labels, draft.conferences)
            != (stored_state.draft.journals, stored_state.draft.access_services,
                stored_state.draft.groups, stored_state.draft.custom_labels, stored_state.draft.conferences)
        )
        monitor_changed = (
            not monitor_snapshot.revision.exists
            or bool({"wos_query", "wos_query_mode", "wos_service_id"} & set(yaml.safe_load(monitor_snapshot.contents) or {}))
            or _draft_monitor_mapping(draft, venue_whitelist=storage_fields.venue_whitelist)
            != _draft_monitor_mapping(stored_state.draft, venue_whitelist=storage_fields.venue_whitelist)
        )
        journal_target = (
            render_settings_list_text(journal_snapshot.contents, draft.journals,
                                      groups=draft.groups, custom_labels=draft.custom_labels,
                                      access_services=draft.access_services, conferences=draft.conferences, path=journal_path)
            if journal_changed else journal_snapshot.contents
        )
        monitor_target = (
            _render_monitor_yaml(draft, venue_whitelist=storage_fields.venue_whitelist)
            if monitor_changed else monitor_snapshot.contents
        )
        journal_changed = journal_changed and journal_target != journal_snapshot.contents
        monitor_changed = monitor_changed and monitor_target != monitor_snapshot.contents
    except ConfigurationError as error:
        return _result_from_state(
            outcome=SettingsSaveOutcome.INVALID_DRAFT, validation=validation,
            state=load_settings(config_path), issues=(SettingsIssue(SettingsIssueSource.JOURNAL_DATA, str(error)),),
            journal_written=False, monitor_written=False,
        )

    try:
        for lock in operation_locks:
            lock.verify()
        # State-only Save still checks the monitor revision at the actual write boundary.
        if journal_changed and _read_snapshot(
            config_path, source=SettingsIssueSource.MONITOR_CONFIG,
        ).revision != draft.monitor_revision:
            raise ContentChangedError("monitor config changed before journal data write")
        if journal_changed:
            compare_write_user_state(config_path,
                SettingsList(draft.journals, draft.groups, draft.custom_labels, draft.access_services, draft.conferences),
                journal_snapshot.revision)
    except (ContentChangedError, FileExistsError) as error:
        state = load_settings(config_path)
        return _result_from_state(
            outcome=SettingsSaveOutcome.REVISION_CONFLICT,
            validation=validation,
            state=state,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.STORAGE,
                    message=f"Settings revision conflict before journal data write: {error}",
                ),
            ),
            journal_written=False,
            monitor_written=False,
        )
    except (CompareReadError, OSError, UserStateError) as error:
        state = load_settings(config_path)
        # A storage error can follow commit; reload the scope to report the actual result.
        committed = journal_changed and not state.issues and (
            state.draft.journals, state.draft.groups, state.draft.custom_labels, state.draft.access_services, state.draft.conferences
        ) == (draft.journals, draft.groups, draft.custom_labels, draft.access_services, draft.conferences)
        return _result_from_state(
            outcome=SettingsSaveOutcome.PARTIAL_SAVE if committed else SettingsSaveOutcome.WRITE_FAILED,
            validation=validation,
            state=state,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.JOURNAL_DATA,
                    message=f"unable to finish journal data write: {error}",
                    path=journal_path,
                ),
            ),
            journal_written=committed,
            monitor_written=False,
        )

    try:
        for lock in operation_locks:
            lock.verify()
        if not journal_changed and _read_journal_snapshot(config_path, journal_path).revision != draft.journal_revision:
            raise ContentChangedError("journal data changed before monitor configuration write")
        if monitor_changed:
            _write_snapshot_target(config_path, monitor_target, monitor_snapshot)
    except (ContentChangedError, FileExistsError) as error:
        state = load_settings(config_path)
        return _result_from_state(
            outcome=SettingsSaveOutcome.PARTIAL_SAVE if journal_changed else SettingsSaveOutcome.REVISION_CONFLICT,
            validation=validation,
            state=state,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.MONITOR_CONFIG,
                    message=f"monitor config changed before it could be written: {error}",
                    path=config_path,
                ),
            ),
            journal_written=journal_changed,
            monitor_written=False,
        )
    except (CompareReadError, OSError) as error:
        state = load_settings(config_path)
        committed = monitor_changed and state.draft.monitor_revision.digest == _digest(monitor_target)
        return _result_from_state(
            outcome=SettingsSaveOutcome.PARTIAL_SAVE if journal_changed or committed else SettingsSaveOutcome.WRITE_FAILED,
            validation=validation,
            state=state,
            issues=(
                SettingsIssue(
                    source=SettingsIssueSource.MONITOR_CONFIG,
                    message=f"unable to finish monitor config write: {error}",
                    path=config_path,
                ),
            ),
            journal_written=journal_changed,
            monitor_written=committed,
        )

    state = load_settings(config_path)
    return _result_from_state(
        outcome=SettingsSaveOutcome.SAVED,
        validation=validation,
        state=state,
        issues=state.issues,
        journal_written=journal_changed,
        monitor_written=monitor_changed,
    )


def _resolve_settings_targets(config_path: Path, draft: MonitorDraft, snapshot: _FileSnapshot,
                              fields: _DraftFields, client: OpenAlexClient | None,
                              *, deletion_approval: SettingsDeletionApproval | None = None) -> MonitorDraft:
    list_path = _journal_path(config_path, fields)
    persisted = parse_journal_whitelist_text(snapshot.contents, path=list_path)
    saved = {(j.issn, j.eissn): j for j in persisted}
    from allfold.application.carsi_catalog import get_carsi_catalog, validate_carsi_service, CatalogError
    from allfold.persistence.user_state import application_data_dir
    old_services = {service.id: service for service in parse_access_services_text(snapshot.contents, path=list_path)}
    catalog = None
    for service in draft.access_services:
        old = old_services.get(service.id)
        if service.access_method == "carsi" and (old is None or (old.name, old.access_method) != (service.name, service.access_method)):
            if catalog is None:
                catalog = get_carsi_catalog(application_data_dir(config_path) / "resources.sqlite")
            try:
                validate_carsi_service(service.name, catalog=catalog)
            except CatalogError as error:
                raise ConfigurationError(str(error), field="access_services") from error
        elif service.access_method == "manual" and service != old and not service.access_url:
            raise ConfigurationError("Manual Service requires a public HTTP(S) URL", field="access_services")
    journals = []
    for journal in draft.journals:
        old = saved.get((journal.issn, journal.eissn))
        if old is not None and journal.name == old.name:
            journals.append(journal)
        else:
            journals.append(verify_journal(list_path, journal, client=client))
    return replace(draft, journals=tuple(journals))
