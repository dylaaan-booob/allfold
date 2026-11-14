"""Project configuration and journal whitelist loading."""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Annotated, Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator

from allfold.date_range import (
    DateRangeError,
    DateRangeSpec,
    ResolvedDateRange,
    resolve_date_range,
    validate_date_range_spec,
)
from allfold.keywords import KeywordExpression, KeywordSyntaxError, parse_keyword_expression
from allfold.url_safety import normalize_public_http_url

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_ISSN_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{3}[0-9X]$")
_HEADING_PATTERN = re.compile(r"^##\s+")
_SEPARATOR_PATTERN = re.compile(r"^:?-{3,}:?$")


class ConfigurationError(ValueError):
    """A user-facing configuration error with file and field context."""

    def __init__(
        self,
        message: str,
        *,
        field: str | None = None,
        path: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.path = path


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


DEFAULT_PROVIDER_ORDER = ("pubmed", "openalex", "europe_pmc", "crossref", "arxiv", "biorxiv", "medrxiv", "wos")
ENABLED_PROVIDERS = ("pubmed", "openalex")


def normalize_journal_labels(values: object) -> tuple[str, ...]:
    """Labels are ordered names, stored without escaping in one Markdown cell."""
    if not isinstance(values, (list, tuple)):
        raise ValueError("Journal labels must be a collection of names")
    labels = []
    for value in values:
        if (not isinstance(value, str) or not value.strip() or ";" in value
                or not _markdown_cell_safe(value) or value.splitlines() != [value]):
            raise ValueError("Label names must be nonempty and cannot contain semicolons, pipes, line breaks or control characters")
        label = value.strip()
        if label not in labels:
            labels.append(label)
    return tuple(labels)


def parse_journal_labels(value: str) -> tuple[str, ...]:
    if not _markdown_cell_safe(value) or (value and value.splitlines() != [value]):
        raise ValueError("Labels cannot contain pipes, line breaks or control characters")
    return normalize_journal_labels(value.split(";")) if value.strip() else ()


def validate_provider_order(value) -> tuple[str, ...]:
    if (not isinstance(value, (list, tuple)) or len(value) != len(DEFAULT_PROVIDER_ORDER)
            or any(not isinstance(item, str) for item in value)
            or set(value) != set(DEFAULT_PROVIDER_ORDER)):
        raise ValueError("provider_order must contain all supported Providers exactly once")
    return tuple(value)


class JournalConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: NonEmptyStr
    issn: str | None = None
    eissn: str | None = None
    access_service_id: str | None = None
    group: NonEmptyStr | None = None
    labels: tuple[str, ...] = ()

    @field_validator("labels", mode="before")
    @classmethod
    def normalize_labels(cls, value: object) -> tuple[str, ...]:
        return normalize_journal_labels(value)

    @field_validator("issn", "eissn")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return normalize_journal_issn(value) if value else None

    @field_validator("access_service_id")
    @classmethod
    def normalize_service_id(cls, value: str | None) -> str | None:
        return validate_access_service_id(value) if value else None

    @model_validator(mode="after")
    def require_identifier(self):
        if not self.identifiers:
            raise ValueError("Journal requires at least one ISSN or eISSN")
        return self

    @property
    def key(self) -> str:
        return self.issn or self.eissn

    @property
    def identifiers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(i for i in (self.issn, self.eissn) if i))


def validate_access_service_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"svc_[0-9a-f]{32}", value):
        raise ValueError("Service ID must be svc_ followed by 32 lowercase hexadecimal digits")
    return value


class AccessService(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: NonEmptyStr
    access_url: str | None = None
    access_method: Literal["carsi", "manual"] = "carsi"

    @classmethod
    def create(cls, name: str, access_url: str | None = None, *,
               access_method: Literal["carsi", "manual"] = "carsi") -> AccessService:
        return cls(id="svc_" + uuid.uuid4().hex, name=name, access_url=access_url,
                   access_method=access_method)

    @field_validator("id")
    @classmethod
    def normalize_identity(cls, value: str) -> str:
        return validate_access_service_id(value)

    @field_validator("access_url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        return normalize_public_http_url(value)


class InstitutionConfig(BaseModel):
    """Public preparation context only; never a route or access proof."""

    model_config = ConfigDict(extra="forbid", frozen=True, revalidate_instances="always")
    name: str | None = None
    idp_entity_id: str | None = None
    use_shibboleth: bool = False

    @field_validator("name", "idp_entity_id", mode="before")
    @classmethod
    def optional_public_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("must be public text")
        if any(unicodedata.category(c).startswith("C") for c in value):
            raise ValueError("control and invisible characters are forbidden")
        return value.strip() or None

    @field_validator("name")
    @classmethod
    def public_name(cls, value: str | None) -> str | None:
        if value is not None and (len(value) > 120 or not all(
            unicodedata.category(c)[0] in "LNM" or c in " .,'()-_（）" for c in value
        )):
            raise ValueError("use at most 120 letters, numbers, spaces or name punctuation")
        return value

    @field_validator("idp_entity_id")
    @classmethod
    def public_entity_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 512 or not value.isascii():
            raise ValueError("use a public HTTPS entity ID or URN, at most 512 ASCII characters")
        if re.fullmatch(r"urn:[A-Za-z0-9][A-Za-z0-9._-]*:[A-Za-z0-9._:-]+", value):
            return value
        normalize_public_http_url(value)
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.query or parsed.fragment
                or any(c in value for c in "?%#<>'\"")):
            raise ValueError("entity ID must use HTTPS without query, fragment or encoded payload")
        return value


DEFAULT_PREPARE_SERVICE_CONCURRENCY = 5
WORKFLOW_CONCURRENCY_FIELDS = (
    "prepare_service_concurrency", "managed_page_service_limit", "managed_page_global_limit",
    "pdf_concurrency",
)


class WorkflowConfig(BaseModel):
    """Prepare workers and Session-wide physical managed page capacities."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    prepare_service_concurrency: int = Field(default=DEFAULT_PREPARE_SERVICE_CONCURRENCY, strict=True, ge=1, le=5)
    managed_page_service_limit: int = Field(default=4, strict=True, ge=3, le=16)
    managed_page_global_limit: int = Field(default=16, strict=True, ge=4, le=64)
    pdf_concurrency: int = Field(default=2, strict=True, ge=1, le=8)

class _Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: NonEmptyStr | None = None
    venue_whitelist: Path | None = None
    keyword_expression: NonEmptyStr
    output_dir: Path | None = None
    from_month: str
    to_month: str
    log_level: LogLevel = LogLevel.INFO
    institution: InstitutionConfig | None = None
    workflow: WorkflowConfig = WorkflowConfig()
    enabled_providers: tuple[str, ...] = ENABLED_PROVIDERS
    provider_aliases: dict[str, str] = Field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    crossref_mailto: str = ""

    @field_validator("enabled_providers", mode="before")
    @classmethod
    def valid_enabled(cls, value):
        if not isinstance(value, (list, tuple)) or not value or any(item not in (*ENABLED_PROVIDERS, "wos") for item in value) or len(set(value)) != len(value):
            raise ValueError("enabled_providers must list one or more unique PubMed, WoS or OpenAlex Provider IDs")
        return tuple(value)

    @field_validator("provider_order", mode="before")
    @classmethod
    def valid_provider_order(cls, value):
        return validate_provider_order(value)

    @field_validator("provider_aliases")
    @classmethod
    def valid_aliases(cls, value):
        if set(value) - set(DEFAULT_PROVIDER_ORDER):
            raise ValueError("Unknown Provider ID")
        if any(not alias.strip() or len(alias) > 120 or any(ord(c) < 32 for c in alias) for alias in value.values()):
            raise ValueError("Provider aliases must contain 1 to 120 printable characters")
        return {key: alias.strip() for key, alias in value.items()}

    @field_validator("crossref_mailto")
    @classmethod
    def valid_contact(cls, value):
        if value and (not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) or len(value) > 254):
            raise ValueError("Enter a valid Crossref contact email")
        return value

    @field_validator("institution")
    @classmethod
    def empty_institution(cls, value: InstitutionConfig | None) -> InstitutionConfig | None:
        return value if value is not None and (value.name or value.idp_entity_id or value.use_shibboleth) else None

    @field_validator(
        "name",
        "venue_whitelist",
        "keyword_expression",
        "output_dir",
        "from_month",
        "to_month",
        "log_level",
        mode="before",
    )
    @classmethod
    def reject_explicit_null(cls, value: Any) -> Any:
        if value is None:
            raise ValueError("must not be null")
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> Any:
        return value.upper() if isinstance(value, str) else value


@dataclass(frozen=True)
class LoadedConfig:
    name: str
    venue_whitelist: Path
    keyword_expression: str
    keyword_ast: KeywordExpression
    output_dir: Path
    date_spec: DateRangeSpec
    log_level: LogLevel
    journals: tuple[JournalConfig, ...]
    institution: InstitutionConfig | None = None
    workflow: WorkflowConfig = WorkflowConfig()
    enabled_providers: tuple[str, ...] = ENABLED_PROVIDERS
    provider_aliases: dict[str, str] = field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    crossref_mailto: str = ""
    user_state_revision: str | None = None


@dataclass(frozen=True)
class MonitorDefinition:
    """Validated monitor fields before config-relative paths are resolved."""

    name: str
    venue_whitelist: Path
    keyword_expression: str
    keyword_ast: KeywordExpression
    output_dir: Path
    date_spec: DateRangeSpec
    log_level: LogLevel
    institution: InstitutionConfig | None = None
    workflow: WorkflowConfig = WorkflowConfig()
    enabled_providers: tuple[str, ...] = ENABLED_PROVIDERS
    provider_aliases: dict[str, str] = field(default_factory=dict)
    provider_order: tuple[str, ...] = DEFAULT_PROVIDER_ORDER
    crossref_mailto: str = ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConfigurationError(f"{path}: unable to read file: {error}") from error


def parse_journal_table_cells(
    line: str,
    path: Path,
    line_number: int,
    columns: int | None = None,
) -> tuple[str, ...]:
    """Read cells from an explicit Journal table schema."""
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        raise ConfigurationError(
            f"{path}:{line_number}: expected a Markdown table row"
        )
    cells = tuple(cell.strip() for cell in stripped[1:-1].split("|"))
    if len(cells) not in ((4, 6) if columns is None else (columns,)):
        expected = "4 or 6" if columns is None else str(columns)
        raise ConfigurationError(
            f"{path}:{line_number}: expected {expected} table columns, found {len(cells)}"
        )
    return cells


def _valid_issn_checksum(issn: str) -> bool:
    digits = issn.replace("-", "")
    values = [10 if character == "X" else int(character) for character in digits]
    return sum(value * weight for value, weight in zip(values, range(8, 0, -1))) % 11 == 0


def normalize_journal_issn(raw: str) -> str:
    """Normalize one configured ISSN and validate its checksum."""
    issn = raw.strip().upper().replace("-", "")
    issn = f"{issn[:4]}-{issn[4:]}"
    if not _ISSN_PATTERN.fullmatch(issn):
        raise ValueError(f"invalid ISSN/EISSN {raw!r}; expected NNNN-NNNN")
    if not _valid_issn_checksum(issn):
        raise ValueError(f"invalid ISSN/EISSN checksum for {issn!r}")
    return issn


def _journal_error(
    message: str,
    *,
    path: Path | None = None,
    line_number: int | None = None,
) -> ConfigurationError:
    if path is not None and line_number is not None:
        rendered = f"{path}:{line_number}: {message}"
    elif path is not None:
        rendered = f"{path}: {message}"
    else:
        rendered = message
    return ConfigurationError(rendered, field="journals", path=path)


def validate_journal_configs(
    journals: Sequence[JournalConfig],
    *,
    path: Path | None = None,
    line_numbers: Sequence[int] | None = None,
) -> tuple[JournalConfig, ...]:
    """Validate and normalize the shared journal-domain constraints."""

    if line_numbers is not None and len(line_numbers) != len(journals):
        raise ValueError("line_numbers must correspond to journals")

    identities: dict[str, int | None] = {}
    normalized: list[JournalConfig] = []
    for index, journal in enumerate(journals):
        line_number = line_numbers[index] if line_numbers is not None else None
        try:
            item = JournalConfig.model_validate(journal.model_dump())
        except ValueError as error:
            raise _journal_error(str(error), path=path, line_number=line_number) from error
        for identifier in item.identifiers:
            if identifier in identities:
                first = identities[identifier]
                suffix = f"; first seen at line {first}" if first is not None else ""
                raise _journal_error(f"duplicate or conflicting ISSN/eISSN {identifier!r}{suffix}",
                                     path=path, line_number=line_number)
            identities[identifier] = line_number
        normalized.append(item)
    return tuple(normalized)


def journal_whitelist_table(
    contents: str,
    *,
    path: Path,
) -> tuple[int, tuple[tuple[int, str], ...]]:
    """Validate the Journals table structure and return numbered raw data rows."""

    lines = contents.splitlines()
    journal_headings = [
        index for index, line in enumerate(lines) if line.strip() == "## Journals"
    ]
    if len(journal_headings) != 1:
        raise ConfigurationError(
            f"{path}: expected exactly one '## Journals' section, found {len(journal_headings)}"
        )

    start = journal_headings[0] + 1
    section: list[tuple[int, str]] = []
    for index in range(start, len(lines)):
        line = lines[index]
        if _HEADING_PATTERN.match(line.strip()):
            break
        if line.strip():
            section.append((index + 1, line))

    if len(section) < 2:
        raise ConfigurationError(f"{path}:{start + 1}: Journals table is missing")

    header_line, header = section[0]
    header_cells = parse_journal_table_cells(header, path, header_line)
    if header_cells != ("Journal", "ISSN", "eISSN", "Access Service ID", "Group", "Labels"):
        raise ConfigurationError(
            f"{path}:{header_line}: expected '| Journal | ISSN | eISSN | Access Service ID | Group | Labels |'"
        )
    columns = len(header_cells)

    separator_line, separator = section[1]
    separator_cells = parse_journal_table_cells(separator, path, separator_line, columns)
    if not all(_SEPARATOR_PATTERN.fullmatch(cell) for cell in separator_cells):
        raise ConfigurationError(
            f"{path}:{separator_line}: invalid Markdown table separator"
        )

    return columns, tuple(section[2:])


def parse_journal_whitelist_text(contents: str, *, path: Path) -> tuple[JournalConfig, ...]:
    """Read the direct Journal → Access Service configuration."""
    columns, rows = journal_whitelist_table(contents, path=path)
    journals, numbers = [], []
    for number, row in rows:
        name, issn, eissn, service, group, labels = parse_journal_table_cells(row, path, number, columns)
        try:
            journals.append(JournalConfig(name=name, issn=issn or None, eissn=eissn or None,
                                          access_service_id=service or None, group=group or None,
                                          labels=parse_journal_labels(labels)))
        except ValueError as error:
            raise _journal_error(str(error), path=path, line_number=number) from error
        numbers.append(number)
    return validate_journal_configs(journals, path=path, line_numbers=numbers)


def parse_journal_whitelist(path: Path) -> tuple[JournalConfig, ...]:
    path = path.resolve()
    return parse_journal_whitelist_text(_read_text(path), path=path)


def validate_journal_storage(journals: Sequence[JournalConfig]) -> None:
    """Validate constraints of the current Markdown table storage adapter."""

    for journal in journals:
        try:
            normalize_journal_labels(journal.labels)
        except ValueError as error:
            raise ConfigurationError(str(error), field="journals") from error
        for field, value in (("name", journal.name), ("group", journal.group)):
            if value is None:
                continue
            unsafe = not _markdown_cell_safe(value)
            if field == "group" and value.splitlines() != [value]:
                unsafe = True
            if unsafe:
                raise ConfigurationError(
                    (
                        f"journal {field} {value!r} cannot be represented in the "
                        "current Markdown journal table"
                    ),
                    field="journals",
                )


def _markdown_cell_safe(value: str) -> bool:
    return (
        "|" not in value
        and "\n" not in value
        and "\r" not in value
        and all(not unicodedata.category(char).startswith("C") for char in value)
    )


def render_journal_whitelist_text(
    existing_contents: str | None,
    journals: Sequence[JournalConfig],
    *,
    path: Path,
) -> str:
    """Render only the current Journals section while preserving other content."""

    normalized = validate_journal_configs(journals)
    validate_journal_storage(normalized)
    lines = (existing_contents or "").splitlines(keepends=True)
    headings = [
        index
        for index, line in enumerate(lines)
        if line.rstrip("\r\n").strip() == "## Journals"
    ]
    if len(headings) > 1:
        raise ConfigurationError(
            f"{path}: expected at most one '## Journals' section, found {len(headings)}",
            field="journals",
            path=path,
        )

    start = headings[0] if headings else len(lines)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].lstrip().startswith("## "):
            end = index
            break

    rows = ["## Journals", "", "| Journal | ISSN | eISSN | Access Service ID | Group | Labels |", "| --- | --- | --- | --- | --- | --- |"]
    for journal in normalized:
        rows.append(f"| {journal.name} | {journal.issn or ''} | {journal.eissn or ''} | {journal.access_service_id or ''} | {journal.group or ''} | {'; '.join(journal.labels)} |")
    section = "\n".join(rows) + "\n\n"
    if existing_contents is None:
        return "# List\n\n" + section

    if not headings:
        prefix = existing_contents
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        return prefix + section

    return "".join(lines[:start]) + section + "".join(lines[end:])


def _format_validation_error(path: Path, error: ValidationError) -> ConfigurationError:
    detail = error.errors()[0]
    field = ".".join(str(part) for part in detail["loc"]) or "configuration"
    return ConfigurationError(
        f"{path}: field {field!r}: {detail['msg']}",
        field=field,
        path=path,
    )


def resolve_config_path(config_path: Path, value: Path | None, default_name: str) -> Path:
    candidate = value if value is not None else Path(default_name)
    if not candidate.is_absolute():
        candidate = config_path.parent / candidate
    return candidate.resolve()


def parse_monitor_definition(path: Path, raw: Any) -> MonitorDefinition:
    """Validate monitor fields and apply config-file defaults without I/O."""

    path = path.resolve()
    if not isinstance(raw, dict):
        raise ConfigurationError(
            f"{path}: configuration must be a YAML mapping",
            path=path,
        )

    if (any(isinstance(key, str) and key.startswith("pubmed") for key in raw)
            or isinstance(raw.get("enabled_providers"), (list, tuple)) and "europe_pmc" in raw["enabled_providers"]
            or "provider_order" in raw and (not isinstance(raw["provider_order"], (list,tuple))
                or any(not isinstance(item, str) for item in raw["provider_order"])
                or set(raw["provider_order"]) != set(DEFAULT_PROVIDER_ORDER))):
        raise ConfigurationError(
            "Obsolete Provider roles or configuration fields. Back up and rebuild the YAML from "
            "config.template.yaml; choose PubMed, WoS and/or OpenAlex for Discovery. "
            "Europe PMC is now targeted PPR completion only. Existing Workspace, user-state and credentials are preserved.",
            field="enabled_providers", path=path,
        )

    try:
        settings = _Settings.model_validate(raw)
    except ValidationError as error:
        raise _format_validation_error(path, error) from error

    date_spec = DateRangeSpec(settings.from_month, settings.to_month)
    try:
        validate_date_range_spec(date_spec)
    except DateRangeError as error:
        raise ConfigurationError(
            f"{path}: field {error.field!r}: {error}",
            field=error.field,
            path=path,
        ) from error

    try:
        keyword_ast = parse_keyword_expression(settings.keyword_expression)
    except KeywordSyntaxError as error:
        raise ConfigurationError(
            f"{path}: field 'keyword_expression': {error}",
            field="keyword_expression",
            path=path,
        ) from error

    return MonitorDefinition(
        name=settings.name if settings.name is not None else path.stem,
        venue_whitelist=(
            settings.venue_whitelist
            if settings.venue_whitelist is not None
            else Path("list.md")
        ),
        keyword_expression=settings.keyword_expression,
        keyword_ast=keyword_ast,
        output_dir=(
            settings.output_dir
            if settings.output_dir is not None
            else Path("workspace")
        ),
        date_spec=date_spec,
        log_level=settings.log_level,
        institution=settings.institution,
        workflow=settings.workflow,
        enabled_providers=settings.enabled_providers,
        provider_order=settings.provider_order, provider_aliases=settings.provider_aliases, crossref_mailto=settings.crossref_mailto,
    )


def build_loaded_config(
    path: Path,
    definition: MonitorDefinition,
    journals: Sequence[JournalConfig],
) -> LoadedConfig:
    """Resolve paths and journal-domain rules into the runtime config model."""

    path = path.resolve()
    normalized_journals = validate_journal_configs(journals)
    return LoadedConfig(
        name=definition.name,
        venue_whitelist=resolve_config_path(
            path,
            definition.venue_whitelist,
            "list.md",
        ),
        keyword_expression=definition.keyword_expression,
        keyword_ast=definition.keyword_ast,
        output_dir=resolve_config_path(path, definition.output_dir, "workspace"),
        date_spec=definition.date_spec,
        log_level=definition.log_level,
        journals=normalized_journals,
        institution=definition.institution,
        workflow=definition.workflow,
        enabled_providers=definition.enabled_providers,
        provider_order=definition.provider_order, provider_aliases=definition.provider_aliases, crossref_mailto=definition.crossref_mailto,
    )


def validate_runtime_keyword(config: LoadedConfig) -> None:
    """Validate shared input without requiring a SQLite search extension."""

    parse_keyword_expression(config.keyword_expression)


def resolve_runtime_date(
    config: LoadedConfig,
    *,
    today: date,
    date_spec: DateRangeSpec | None = None,
) -> ResolvedDateRange:
    """Resolve the effective runtime date policy with production semantics."""

    return resolve_date_range(
        date_spec if date_spec is not None else config.date_spec,
        today=today,
    )


def validate_runtime_config(
    config: LoadedConfig,
    *,
    today: date,
) -> ResolvedDateRange:
    """Run deterministic runtime checks shared by Monitor and Settings."""

    validate_runtime_keyword(config)
    return resolve_runtime_date(config, today=today)


def load_config(path: Path) -> LoadedConfig:
    path = path.resolve()
    contents = _read_text(path)
    try:
        raw = yaml.safe_load(contents)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        location = f":{mark.line + 1}:{mark.column + 1}" if mark is not None else ""
        raise ConfigurationError(
            f"{path}{location}: invalid YAML: {error}",
            path=path,
        ) from error

    definition = parse_monitor_definition(path, raw)
    # Retain the lexical source until migration has rejected symlinks.
    whitelist = definition.venue_whitelist
    if not whitelist.is_absolute():
        whitelist = path.parent / whitelist
    try:
        # Normal Runs read only the local authoritative state, without Resolver/network work.
        from allfold.persistence.user_state import load_user_state
        snapshot = load_user_state(path, whitelist)
        journals = snapshot.state.journals
    except ConfigurationError as error:
        raise ConfigurationError(
            f"{path}: field 'venue_whitelist': {error}",
            field="venue_whitelist",
            path=path,
        ) from error
    return replace(build_loaded_config(path, definition, journals), user_state_revision=snapshot.revision.digest)


def validate_access_services(services: Sequence[AccessService]) -> tuple[AccessService, ...]:
    normalized: list[AccessService] = []
    identities: set[str] = set()
    names: set[str] = set()
    for service in services:
        try:
            item = AccessService.model_validate(service.model_dump())
        except ValueError as error:
            raise ConfigurationError(str(error), field="access_services") from error
        name_key = item.name.strip().casefold()
        if item.id in identities:
            raise ConfigurationError(f"duplicate Access Service ID {item.id}", field="access_services")
        if name_key in names:
            raise ConfigurationError(f"conflicting Access Service name {item.name!r}", field="access_services")
        if any(not _markdown_cell_safe(value) for value in (item.name, item.access_url) if value is not None):
            raise ConfigurationError("Access Service content cannot be represented in Markdown", field="access_services")
        identities.add(item.id)
        names.add(name_key)
        normalized.append(item)
    return tuple(normalized)


def validate_access_mapping(journals: Sequence[JournalConfig], services: Sequence[AccessService]) -> None:
    identities = {service.id for service in validate_access_services(services)}
    for journal in validate_journal_configs(journals):
        if journal.access_service_id is not None and journal.access_service_id not in identities:
            raise ConfigurationError(
                f"Journal {journal.key} references unknown Access Service {journal.access_service_id}",
                field="access_services",
            )


def _managed_rows(contents: str, path: Path, section_name: str, columns: tuple[str, ...] | None = None
                  ) -> tuple[tuple[str, ...], tuple[tuple[int, tuple[str, ...]], ...]] | None:
    lines = contents.splitlines()
    headings = [i for i, line in enumerate(lines) if line.strip() == f"## {section_name}"]
    if len(headings) > 1:
        raise ConfigurationError(f"duplicate {section_name} section", path=path)
    if not headings:
        return None
    start = headings[0] + 1
    section: list[tuple[int, str]] = []
    for i in range(start, len(lines)):
        if _HEADING_PATTERN.match(lines[i].strip()):
            break
        if lines[i].strip():
            section.append((i + 1, lines[i]))
    if len(section) < 2:
        raise ConfigurationError(f"{path}: {section_name} table is missing", path=path)
    header = parse_journal_table_cells(section[0][1], path, section[0][0], len(columns) if columns else None)
    if columns is not None and header != columns:
        raise ConfigurationError(f"{path}: invalid {section_name} table header", path=path)
    separator = parse_journal_table_cells(section[1][1], path, section[1][0], len(header))
    if not all(_SEPARATOR_PATTERN.fullmatch(cell) for cell in separator):
        raise ConfigurationError(f"{path}: invalid {section_name} table separator", path=path)
    return header, tuple(
        (number, parse_journal_table_cells(line, path, number, len(header)))
        for number, line in section[2:]
    )


def parse_access_services_text(contents: str, *, path: Path) -> tuple[AccessService, ...]:
    section = _managed_rows(contents, path, "Access Services")
    if section is None:
        raise ConfigurationError(f"{path}: missing Access Services section", field="access_services", path=path)
    if section[0] != ("Service ID", "Service", "Access URL", "Access Method"):
        raise ConfigurationError(f"{path}: invalid Access Services header", field="access_services", path=path)
    result: list[AccessService] = []
    for number, cells in section[1]:
        identity, name, url = cells[:3]
        try:
            result.append(AccessService(id=identity, name=name, access_url=url or None,
                                        access_method=cells[3]))
        except ValueError as error:
            raise ConfigurationError(f"{path}:{number}: {error}", field="access_services", path=path) from error
    return validate_access_services(result)


@dataclass(frozen=True)
class SettingsList:
    journals: tuple[JournalConfig, ...]
    groups: tuple[str, ...]
    custom_labels: tuple[str, ...]
    access_services: tuple[AccessService, ...]


def validate_entity_names(names: Sequence[str], *, labels: bool = False) -> tuple[str, ...]:
    field = "custom_labels" if labels else "groups"
    seen = set()
    for name in names:
        if (not isinstance(name, str) or not name.strip() or name != name.strip()
                or not _markdown_cell_safe(name) or name.splitlines() != [name]
                or (labels and ";" in name)):
            raise ConfigurationError(f"Invalid {field} name: {name!r}", field=field)
        key = name if labels else name.casefold()
        if key in seen:
            raise ConfigurationError(f"Duplicate {field} name: {name}", field=field)
        seen.add(key)
    return tuple(names)


def parse_entity_registry(contents: str, *, path: Path, labels: bool = False) -> tuple[str, ...]:
    section_name, column = ("Custom Labels", "Label") if labels else ("Groups", "Group")
    section = _managed_rows(contents, path, section_name, (column,))
    if section is None:
        raise ConfigurationError(f"Missing {section_name} section", path=path,
                                 field="custom_labels" if labels else "groups")
    return validate_entity_names(tuple(cells[0] for _, cells in section[1]), labels=labels)


def validate_entity_mapping(journals: Sequence[JournalConfig], groups: Sequence[str],
                            custom_labels: Sequence[str]) -> None:
    validate_entity_names(groups)
    validate_entity_names(custom_labels, labels=True)
    for journal in journals:
        if journal.group is not None and journal.group not in groups:
            raise ConfigurationError(f"Journal {journal.name}: unknown Group {journal.group!r}", field="groups")
        for label in journal.labels:
            if label not in custom_labels:
                raise ConfigurationError(f"Journal {journal.name}: unknown Custom Label {label!r}", field="custom_labels")


def parse_settings_list_text(contents: str, *, path: Path) -> SettingsList:
    if any(line.strip() == "## Publishers" for line in contents.splitlines()):
        raise ConfigurationError("Publishers configuration is no longer supported", path=path)
    journals = parse_journal_whitelist_text(contents, path=path)
    services = parse_access_services_text(contents, path=path)
    groups = parse_entity_registry(contents, path=path)
    labels = parse_entity_registry(contents, path=path, labels=True)
    validate_journal_storage(journals)
    validate_access_mapping(journals, services)
    validate_entity_mapping(journals, groups, labels)
    return SettingsList(journals, groups, labels, services)


def render_settings_list_text(existing_contents: str | None, journals: Sequence[JournalConfig],
                              *, path: Path, groups: Sequence[str], custom_labels: Sequence[str],
                              access_services: Sequence[AccessService]) -> str:
    """Render changed managed tables; preserve unchanged tables and all other text."""
    journals = validate_journal_configs(journals)
    validate_journal_storage(journals)
    services = validate_access_services(access_services)
    validate_access_mapping(journals, services)
    validate_entity_mapping(journals, groups, custom_labels)
    target = existing_contents if existing_contents is not None else "# List\n\n"
    sections = (
        ("Journals", journals, parse_journal_whitelist_text,
         render_journal_whitelist_text(None, journals, path=path).split("# List\n\n", 1)[1]),
        ("Groups", tuple(groups), lambda text, **kw: parse_entity_registry(text, **kw),
         "## Groups\n\n| Group |\n| --- |\n" + "".join(f"| {name} |\n" for name in groups) + "\n"),
        ("Custom Labels", tuple(custom_labels), lambda text, **kw: parse_entity_registry(text, labels=True, **kw),
         "## Custom Labels\n\n| Label |\n| --- |\n" + "".join(f"| {name} |\n" for name in custom_labels) + "\n"),
        ("Access Services", services, parse_access_services_text,
         "## Access Services\n\n| Service ID | Service | Access URL | Access Method |\n| --- | --- | --- | --- |\n"
         + "".join(f"| {s.id} | {s.name} | {s.access_url or ''} | {s.access_method} |\n" for s in services) + "\n"),
    )
    for name, values, parser, replacement in sections:
        lines = target.splitlines(keepends=True)
        indexes = [i for i, line in enumerate(lines) if line.strip() == f"## {name}"]
        if len(indexes) > 1:
            raise ConfigurationError(f"duplicate {name} section", path=path)
        if indexes:
            if parser(target, path=path) == values:
                continue
            begin = indexes[0]
            finish = next((i for i in range(begin + 1, len(lines))
                           if _HEADING_PATTERN.match(lines[i].strip())), len(lines))
        else:
            begin = len(lines)
            finish = begin
        prefix = "".join(lines[:begin])
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n" if prefix.endswith("\n") else "\n\n"
        target = prefix + replacement + "".join(lines[finish:])
    return target
