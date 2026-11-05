"""Browser form adaptation for the Settings application boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from itertools import zip_longest
from pathlib import Path

from pydantic import ValidationError, SecretStr
from starlette.datastructures import FormData

from allfold.application.settings import (
    ContentRevision,
    MonitorDraft,
    SettingsIssue,
    SettingsIssueSource,
)
from allfold.config import ConferenceConfig, AccessService, InstitutionConfig, KeptWorkflowConfig, JournalConfig, LogLevel, DEFAULT_PROVIDER_ORDER, validate_provider_order, parse_journal_labels
from allfold.date_range import DateRangeSpec, DateRangeError, validate_date_range_spec
from allfold.url_safety import normalize_public_http_url


@dataclass(frozen=True)
class SettingsJournalRow:
    name: str
    issn: str = ""
    eissn: str = ""
    access_service_id: str = ""
    group: str = ""
    labels: str = ""





@dataclass(frozen=True)
class SettingsAccessServiceRow:
    id: str
    name: str
    access_url: str = ""
    access_method: str = "carsi"

    @property
    def safe_access_url(self) -> str | None:
        try:
            return normalize_public_http_url(self.access_url)
        except ValueError:
            return None


@dataclass(frozen=True)
class SettingsFormValues:
    name: str
    keyword_expression: str
    journals: tuple[SettingsJournalRow, ...]
    from_month: str
    to_month: str
    output_dir: str
    log_level: str
    monitor_revision_exists: str
    monitor_revision_digest: str
    journal_revision_exists: str
    journal_revision_digest: str
    access_services: tuple[SettingsAccessServiceRow, ...] = ()
    conferences: tuple[ConferenceConfig, ...] = ()
    groups: tuple[str, ...] = ()
    custom_labels: tuple[str, ...] = ()
    institution_name: str = ""
    institution_idp_entity_id: str = ""
    institution_use_shibboleth: bool = False
    institution_issues: tuple[SettingsIssue, ...] = ()
    auto_import_after_preparation: bool = False
    transition_delay_seconds: str = "3"
    display_name: str = ""
    zotero_target: dict | None = None
    pubmed_query_mode: str = "title_abstract"
    provider_aliases: dict[str, str] = field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    crossref_mailto: str = ""
    pubmed_key_configured: bool = False
    pubmed_key_revision: str = "missing"
    pubmed_key_error: str = ""
    pubmed_key_action: str = "keep"
    pubmed_api_key: SecretStr | None = field(default=None, repr=False)
    openalex_key_configured: bool = False
    openalex_key_revision: str = "missing"
    openalex_key_error: str = ""
    openalex_key_action: str = "keep"
    openalex_api_key: SecretStr | None = field(default=None, repr=False)


def _revision_fields(revision: ContentRevision) -> tuple[str, str]:
    return ("1" if revision.exists else "0", revision.digest or "")


def settings_form_from_draft(draft: MonitorDraft) -> SettingsFormValues:
    """Project a structured draft into browser-editable field values."""

    monitor_exists, monitor_digest = _revision_fields(draft.monitor_revision)
    journal_exists, journal_digest = _revision_fields(draft.journal_revision)
    rows = tuple(
        SettingsJournalRow(
            name=journal.name,
            issn=journal.issn or "",
            eissn=journal.eissn or "",
            access_service_id=journal.access_service_id or "",
            group=journal.group or "",
            labels="; ".join(journal.labels),
        )
        for journal in draft.journals
    )

    log_level = (
        draft.log_level.value
        if isinstance(draft.log_level, LogLevel)
        else str(draft.log_level)
    )
    return SettingsFormValues(
        name=draft.name,
        keyword_expression=draft.keyword_expression,
        pubmed_query_mode=draft.pubmed_query_mode,
        provider_order=draft.provider_order, provider_aliases=draft.provider_aliases, crossref_mailto=draft.crossref_mailto,
        openalex_key_configured=draft.openalex_key_configured, openalex_key_revision=draft.openalex_key_revision,
        openalex_key_error=draft.openalex_key_error,
        pubmed_key_configured=draft.pubmed_key_configured, pubmed_key_revision=draft.pubmed_key_revision,
        pubmed_key_error=draft.pubmed_key_error,
        journals=rows,
        conferences=draft.conferences,
        access_services=tuple(SettingsAccessServiceRow(s.id, s.name, s.access_url or "", s.access_method) for s in draft.access_services),
        groups=draft.groups,
        custom_labels=draft.custom_labels,
        from_month=draft.date_spec.from_month,
        to_month=draft.date_spec.to_month,
        output_dir=str(draft.output_dir),
        log_level=log_level,
        monitor_revision_exists=monitor_exists,
        monitor_revision_digest=monitor_digest,
        journal_revision_exists=journal_exists,
        journal_revision_digest=journal_digest,
        auto_import_after_preparation=draft.kept_workflow.auto_import_after_preparation,
        transition_delay_seconds=str(draft.kept_workflow.transition_delay_seconds),
        display_name=draft.kept_workflow.display_name or "",
        zotero_target=draft.kept_workflow.zotero_target.model_dump() if draft.kept_workflow.zotero_target else None,
        institution_name=draft.institution.name or "" if draft.institution else "",
        institution_idp_entity_id=draft.institution.idp_entity_id or "" if draft.institution else "",
        institution_use_shibboleth=draft.institution.use_shibboleth if draft.institution else False,
    )


def settings_form_from_submission(form: FormData) -> SettingsFormValues:
    """Capture submitted browser strings exactly enough for redisplay."""

    names = tuple(str(value) for value in form.getlist("journal_name"))
    issns = tuple(str(value) for value in form.getlist("journal_issn"))
    eissns = tuple(str(value) for value in form.getlist("journal_eissn"))
    services = tuple(str(value) for value in form.getlist("journal_access_service_id"))
    assignments = tuple(str(value) for value in form.getlist("journal_group"))
    labels = tuple(str(value) for value in form.getlist("journal_labels"))
    order_values = tuple(str(v) for v in form.getlist("journal_order"))
    rows = tuple(SettingsJournalRow(name, issn, eissn, service, group, label)
                 for name, issn, eissn, service, group, label in zip_longest(
                     names, issns, eissns, services, assignments, labels, fillvalue=""))
    order_is_numeric = all(item.isascii() and item.isdecimal() and len(item) <= 12 for item in order_values)
    invalid_order = bool(order_values) and (
        len(order_values) != len(rows)
        or not order_is_numeric
        or len({int(value) for value in order_values}) != len(order_values)
    )
    if order_values and not invalid_order:
        # 可视 Group 容器会改变表单节点顺序；保存仍须采用草稿原有 Journal 顺序。
        rows = tuple(row for _, row in sorted(zip((int(value) for value in order_values), rows)))

    group_names = tuple(str(value) for value in form.getlist("settings_group"))
    institution_fields = {"institution_name", "institution_idp_entity_id", "institution_use_shibboleth"}
    # Enumerate the existing editor/import contract so credential aliases cannot be ignored.
    workflow_fields = {"auto_import_after_preparation", "transition_delay_seconds", "display_name", "zotero_target"}
    supported_fields = institution_fields | workflow_fields | {
        "csrf_token", "name", "keyword_expression", "output_dir", "log_level",
        "from_month", "to_month", "crossref_mailto",
        "provider_alias_openalex", "provider_alias_crossref", "provider_alias_pubmed", "provider_alias_wos",
        "openalex_key_action", "openalex_api_key", "openalex_key_revision",
        "pubmed_query_mode", "pubmed_key_action", "pubmed_api_key", "pubmed_key_revision",
        "monitor_revision_exists", "monitor_revision_digest", "journal_revision_exists", "journal_revision_digest",
        "journal_name", "journal_issn", "journal_eissn", "journal_access_service_id", "journal_group", "journal_labels", "journal_order", "provider_order", "settings_group", "settings_custom_label",
        "conferences", "service_id", "service_name", "service_access_url", "service_access_method",
        "settings_deletion_proof", "confirm_settings_deletions",
        "markdown_file", "markdown_import_payload", "markdown_import_filename",
        "markdown_import_proof", "confirm_full_import", "import_discard", "import_choices", "query_gokb",
        "export_discard", "reload_step", "reload_word",
    }
    forbidden = any(key not in supported_fields for key in form)
    duplicate = any(len(form.getlist(key)) > 1 for key in institution_fields | workflow_fields | {"conferences"})
    service_lengths = {len(form.getlist(key)) for key in ("service_id", "service_name", "service_access_url", "service_access_method")}
    journal_lengths = {len(names), len(issns), len(eissns), len(assignments), len(services), len(labels)}
    incomplete_rows = len(journal_lengths) != 1 or len(service_lengths) != 1
    institution_issues = (
        (_form_issue("institution", "Unsupported Settings field or duplicate institution identifier. Credentials, sessions and login routes are not settings."),)
        if forbidden or duplicate else ()
    )
    if form.get("auto_import_after_preparation", "") not in {"", "1"}:
        institution_issues += (_form_issue("kept_workflow", "Invalid automatic continuation option."),)
    if form.get("institution_use_shibboleth", "") not in {"", "1"}:
        institution_issues += (_form_issue("institution.use_shibboleth", "Invalid Shibboleth login option."),)
    if incomplete_rows:
        institution_issues += (_form_issue(
            "journals/access_services", "Incomplete Journal/Access Service form rows; reload Settings before saving.",
        ),)
    if invalid_order:
        institution_issues += (_form_issue("journals", "Invalid Journal order. Reload Settings before saving."),)
    conferences = ()
    try:
        raw_conferences = json.loads(str(form.get("conferences", "[]")))
        if not isinstance(raw_conferences, list):
            raise ValueError("Conferences must be a collection")
        conferences = tuple(ConferenceConfig.model_validate(c) for c in raw_conferences)
    except (ValueError, TypeError) as error:
        institution_issues += (_form_issue("conferences", str(error)),)
    return SettingsFormValues(
        conferences=conferences,
        name=str(form.get("name", "")),
        keyword_expression=str(form.get("keyword_expression", "")),
        provider_order=tuple(str(value) for value in form.getlist("provider_order")) if "provider_order" in form else DEFAULT_PROVIDER_ORDER,
        provider_aliases={provider: str(form.get(f"provider_alias_{provider}", ""))
                          for provider in ("openalex", "crossref", "pubmed", "wos") if f"provider_alias_{provider}" in form},
        crossref_mailto=str(form.get("crossref_mailto", "")),
        openalex_key_action=str(form.get("openalex_key_action", "keep")),
        openalex_key_revision=str(form.get("openalex_key_revision", "missing")),
        openalex_api_key=SecretStr(str(form.get("openalex_api_key", ""))) if form.get("openalex_api_key") else None,
        pubmed_query_mode=str(form.get("pubmed_query_mode", "title_abstract")),
        pubmed_key_action=str(form.get("pubmed_key_action", "keep")),
        pubmed_key_revision=str(form.get("pubmed_key_revision", "missing")),
        pubmed_api_key=SecretStr(str(form.get("pubmed_api_key", ""))) if form.get("pubmed_api_key") else None,
        journals=rows,
        access_services=tuple(SettingsAccessServiceRow(identity, name, url, method) for identity, name, url, method in zip_longest(
            (str(v) for v in form.getlist("service_id")),
            (str(v) for v in form.getlist("service_name")),
            (str(v) for v in form.getlist("service_access_url")),
            (str(v) for v in form.getlist("service_access_method")), fillvalue="")),
        groups=group_names,
        custom_labels=tuple(str(value) for value in form.getlist("settings_custom_label")),
        from_month=str(form.get("from_month", "")),
        to_month=str(form.get("to_month", "")),
        output_dir=str(form.get("output_dir", "")),
        log_level=str(form.get("log_level", "")),
        monitor_revision_exists=str(form.get("monitor_revision_exists", "")),
        monitor_revision_digest=str(form.get("monitor_revision_digest", "")),
        journal_revision_exists=str(form.get("journal_revision_exists", "")),
        journal_revision_digest=str(form.get("journal_revision_digest", "")),
        institution_name=str(form.get("institution_name", "")),
        institution_idp_entity_id=str(form.get("institution_idp_entity_id", "")),
        institution_use_shibboleth=form.get("institution_use_shibboleth") == "1",
        institution_issues=institution_issues,
        auto_import_after_preparation=form.get("auto_import_after_preparation") == "1",
        transition_delay_seconds=str(form.get("transition_delay_seconds", "3")),
        display_name=str(form.get("display_name", "")),
        zotero_target=_target_from_submission(form),
    )


def _form_issue(field: str, message: str) -> SettingsIssue:
    return SettingsIssue(
        source=SettingsIssueSource.VALIDATION,
        field=field,
        message=message,
    )


def _parse_revision(
    exists_value: str,
    digest_value: str,
    *,
    field: str,
) -> tuple[ContentRevision | None, SettingsIssue | None]:
    if exists_value not in {"0", "1"}:
        return None, _form_issue(field, "Settings revision is invalid; reload Settings.")
    exists = exists_value == "1"
    digest = digest_value or None
    if not exists and digest is not None:
        return None, _form_issue(field, "Settings revision is invalid; reload Settings.")
    return ContentRevision(exists=exists, digest=digest), None


def settings_draft_from_form(
    values: SettingsFormValues,
) -> tuple[MonitorDraft | None, tuple[SettingsIssue, ...]]:
    """Construct application/domain values without reimplementing validation."""

    issues: list[SettingsIssue] = list(values.institution_issues)
    institution = None
    try:
        public = InstitutionConfig(name=values.institution_name, idp_entity_id=values.institution_idp_entity_id,
                                   use_shibboleth=values.institution_use_shibboleth)
        institution = public if public.name or public.idp_entity_id or public.use_shibboleth else None
    except ValidationError as error:
        detail = error.errors()[0]
        issues.append(_form_issue("institution." + str(detail["loc"][0]), detail["msg"]))
    try:
        kept_workflow = KeptWorkflowConfig(
            auto_import_after_preparation=values.auto_import_after_preparation,
            transition_delay_seconds=float(values.transition_delay_seconds),
            display_name=values.display_name,
            zotero_target=values.zotero_target,
        )
    except (ValueError, TypeError) as error:
        issues.append(_form_issue("kept_workflow", str(error)))
    date_spec = DateRangeSpec(values.from_month, values.to_month)
    try:
        validate_date_range_spec(date_spec)
    except DateRangeError as error:
        issues.append(_form_issue(error.field, str(error)))

    monitor_revision, issue = _parse_revision(
        values.monitor_revision_exists,
        values.monitor_revision_digest,
        field="monitor_revision",
    )
    if issue is not None:
        issues.append(issue)
    journal_revision, issue = _parse_revision(
        values.journal_revision_exists,
        values.journal_revision_digest,
        field="journal_revision",
    )
    if issue is not None:
        issues.append(issue)

    try:
        provider_order = validate_provider_order(values.provider_order)
    except ValueError as error:
        issues.append(_form_issue("provider_order", str(error)))
    access_services = []
    try:
        access_services = [AccessService(id=s.id, name=s.name, access_url=s.access_url, access_method=s.access_method)
                           for s in values.access_services]
    except ValueError as error:
        issues.append(_form_issue("access_services", str(error)))
    journals = []
    for row in values.journals:
        try:
            journals.append(JournalConfig(name=row.name, issn=row.issn or None, eissn=row.eissn or None,
                                          access_service_id=row.access_service_id or None,
                                          group=row.group.strip() or None, labels=parse_journal_labels(row.labels)))
        except ValueError as error:
            issues.append(_form_issue("journals", str(error)))

    if issues:
        return None, tuple(issues)
    assert monitor_revision is not None
    assert journal_revision is not None
    return (
        MonitorDraft(
            name=values.name,
            keyword_expression=values.keyword_expression,
            pubmed_query_mode=values.pubmed_query_mode,
            provider_order=provider_order, provider_aliases=values.provider_aliases, crossref_mailto=values.crossref_mailto,
            openalex_key_action=values.openalex_key_action, openalex_key_revision=values.openalex_key_revision,
            openalex_api_key=values.openalex_api_key,
            pubmed_key_action=values.pubmed_key_action, pubmed_key_revision=values.pubmed_key_revision,
            pubmed_api_key=values.pubmed_api_key,
            journals=tuple(journals),
            conferences=values.conferences,
            access_services=tuple(access_services),
            groups=values.groups,
            custom_labels=values.custom_labels,
            date_spec=date_spec,
            output_dir=Path(values.output_dir.strip()),
            log_level=values.log_level,
            monitor_revision=monitor_revision,
            journal_revision=journal_revision,
            institution=institution,
            kept_workflow=kept_workflow,
        ),
        (),
    )


def _target_from_submission(form):
    try:
        return json.loads(str(form.get("zotero_target", "null")))
    except (ValueError, TypeError):
        return {"invalid": True}
