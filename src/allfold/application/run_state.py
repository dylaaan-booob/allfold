"""Durable Integrated Run facts and provider-specific snapshot versions."""

from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from allfold.application.runtime_metadata import (
    METADATA_DIRECTORY_NAME,
    metadata_directory,
)
from allfold.date_range import DateRangeError, ResolvedDateRange
from allfold.persistence.safe_write import (
    CompareReadError,
    ContentChangedError,
    WorkspaceOperationLock,
    workspace_text_directory,
    atomic_create_text,
    atomic_replace_text,
    read_text_exact,
)

INTEGRATED_RUN_SCHEMA_VERSION = 6
WOS_RUN_SCHEMA_VERSION = 4


class RunIdentifierFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    issn: str
    status: str
    records: int | None = Field(default=None, ge=0, strict=True)
    source_id: str | None = None
    message: str | None = None


class RunJournalFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    key: str
    name: str
    identifiers: tuple[RunIdentifierFact, ...]
    status: str
    records: int | None = Field(default=None, ge=0, strict=True)


class RunIssueFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    category: str
    message: str
    severity: str = "warning"
    journal: str | None = None
    issn: str | None = None


class RunFacts(BaseModel):
    """Small, durable observations, never raw Provider responses or execution logs."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    finished_at: datetime | None = None
    created_papers: int | None = Field(default=None, ge=0, strict=True)
    existing_papers: int | None = Field(default=None, ge=0, strict=True)
    journals: tuple[RunJournalFact, ...] = ()
    statistics: dict[str, int] = Field(default_factory=dict)
    issues: tuple[RunIssueFact, ...] = ()
    details: dict[str, JsonValue] = Field(default_factory=dict)


def validate_saved_facts(value: object) -> RunFacts:
    facts = RunFacts.model_validate(value)
    if facts.finished_at is None or facts.finished_at.utcoffset() is None:
        raise ValueError("snapshot completion time must include a timezone")
    if facts.created_papers is None or facts.existing_papers is None:
        raise ValueError("snapshot requires actual Paper counts")
    return facts


class RunProvider(str, Enum):
    INTEGRATED = "integrated"
    WOS = "wos"

    @property
    def label(self) -> str:
        return "Run" if self is self.INTEGRATED else "Run WoS"


def discovery_provider(provider: RunProvider) -> RunProvider:
    provider = RunProvider(provider)
    if provider is not RunProvider.INTEGRATED:
        raise ValueError("Run WoS requires its dedicated coordinator")
    return provider


class RecordedRunOutcome(str, Enum):
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"


class LastRunReadStatus(str, Enum):
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class LastRunSnapshot:
    schema_version: int
    provider: RunProvider
    resolved_date_range: ResolvedDateRange
    outcome: RecordedRunOutcome
    facts: RunFacts


@dataclass(frozen=True)
class LastRunReadResult:
    status: LastRunReadStatus
    path: Path
    snapshot: LastRunSnapshot | None = None
    error: str | None = None


class LastRunSnapshotWriteError(RuntimeError):
    """The latest-run snapshot could not be persisted safely."""

    def __init__(self, path: Path, message: str) -> None:
        super().__init__(message)
        self.path = path


def last_run_snapshot_path(output_dir: Path, provider: RunProvider) -> Path:
    provider = discovery_provider(provider)
    return output_dir / METADATA_DIRECTORY_NAME / f"last-{provider.value}-run.json"


def _require_exact_keys(
    value: object,
    *,
    label: str,
    expected: set[str],
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details: list[str] = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if extra:
            details.append(f"unexpected {', '.join(extra)}")
        raise ValueError(f"{label} has invalid fields: {'; '.join(details)}")
    return value


def _serialize_snapshot(snapshot: LastRunSnapshot) -> str:
    if snapshot.schema_version != INTEGRATED_RUN_SCHEMA_VERSION:
        raise ValueError(
            f"unsupported schema_version {snapshot.schema_version!r}"
        )
    if not isinstance(snapshot.outcome, RecordedRunOutcome):
        raise ValueError("snapshot outcome is invalid")

    provider = discovery_provider(snapshot.provider)
    validate_saved_facts(snapshot.facts)
    payload = {
        "schema_version": INTEGRATED_RUN_SCHEMA_VERSION,
        "provider": provider.value,
        "resolved_date_range": {
            "from_date": snapshot.resolved_date_range.from_date.isoformat(),
            "to_date": snapshot.resolved_date_range.to_date.isoformat(),
        },
        "outcome": snapshot.outcome.value,
        "facts": snapshot.facts.model_dump(mode="json"),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _parse_iso_date(value: object, *, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO date string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be YYYY-MM-DD")
    return parsed


def _parse_snapshot(contents: str, provider: RunProvider) -> LastRunSnapshot:
    try:
        value = json.loads(contents)
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON: {error.msg}") from error
    raw = _require_exact_keys(
        value,
        label="snapshot",
        expected={"schema_version", "provider", "resolved_date_range", "outcome", "facts"},
    )

    schema_version = raw["schema_version"]
    if type(schema_version) is not int or schema_version != INTEGRATED_RUN_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {schema_version!r}")

    if raw["provider"] != provider.value:
        raise ValueError("snapshot Provider does not match requested Provider")

    raw_range = _require_exact_keys(
        raw["resolved_date_range"],
        label="resolved_date_range",
        expected={"from_date", "to_date"},
    )
    try:
        resolved_date_range = ResolvedDateRange(
            from_date=_parse_iso_date(raw_range["from_date"], field="from_date"),
            to_date=_parse_iso_date(raw_range["to_date"], field="to_date"),
        )
    except DateRangeError as error:
        raise ValueError(str(error)) from error

    try:
        outcome = RecordedRunOutcome(raw["outcome"])
    except (TypeError, ValueError) as error:
        raise ValueError("outcome is invalid") from error

    return LastRunSnapshot(
        schema_version=schema_version,
        resolved_date_range=resolved_date_range,
        outcome=outcome,
        provider=provider,
        facts=validate_saved_facts(raw["facts"]),
    )


def write_last_run_snapshot(output_dir: Path, snapshot: LastRunSnapshot, *,
                            operation_lock: WorkspaceOperationLock | None = None) -> None:
    path = last_run_snapshot_path(output_dir, snapshot.provider)
    try:
        contents = _serialize_snapshot(snapshot)
        if operation_lock is not None:
            if operation_lock.path != output_dir.absolute():
                raise ContentChangedError("Run snapshot targets a different Workspace")
            with workspace_text_directory(operation_lock, METADATA_DIRECTORY_NAME) as directory:
                try:
                    descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                                         dir_fd=directory.directory)
                except FileNotFoundError:
                    directory.create(path.name, contents)
                else:
                    with os.fdopen(descriptor, "rb") as handle:
                        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                            raise OSError("snapshot path is not a regular file")
                        previous = handle.read().decode("utf-8")
                    directory.replace(path.name, contents, expected_contents=previous)
            return
        metadata_dir = metadata_directory(output_dir, create=True)
        assert metadata_dir is not None

        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            atomic_create_text(path, contents)
        except OSError as error:
            raise OSError(f"cannot inspect snapshot path: {error}") from error
        else:
            if not stat.S_ISREG(mode):
                raise OSError("snapshot path is not a regular file")
            atomic_replace_text(path, contents)
    except (OSError, UnicodeError, ValueError, CompareReadError, ContentChangedError) as error:
        raise LastRunSnapshotWriteError(path, str(error)) from error


def read_last_run_snapshot(output_dir: Path, provider: RunProvider) -> LastRunReadResult:
    provider = discovery_provider(provider)
    path = last_run_snapshot_path(output_dir, provider)
    try:
        metadata_dir = metadata_directory(output_dir, create=False)
    except OSError as error:
        return LastRunReadResult(
            status=LastRunReadStatus.INVALID,
            path=path,
            error=str(error),
        )
    if metadata_dir is None:
        return LastRunReadResult(
            status=LastRunReadStatus.NOT_FOUND,
            path=path,
        )

    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return LastRunReadResult(
            status=LastRunReadStatus.NOT_FOUND,
            path=path,
        )
    except OSError as error:
        return LastRunReadResult(
            status=LastRunReadStatus.INVALID,
            path=path,
            error=f"cannot inspect snapshot path: {error}",
        )
    if not stat.S_ISREG(mode):
        return LastRunReadResult(
            status=LastRunReadStatus.INVALID,
            path=path,
            error="snapshot path is not a regular file",
        )

    try:
        contents = read_text_exact(path)
        try:
            value = json.loads(contents)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON: {error.msg}") from error
        if isinstance(value, dict) and type(value.get("schema_version")) is int and value["schema_version"] < INTEGRATED_RUN_SCHEMA_VERSION:
            return LastRunReadResult(status=LastRunReadStatus.UNSUPPORTED, path=path,
                                     error="旧版运行记录，请重新运行生成结果。")
        snapshot = _parse_snapshot(contents, provider)
    except (OSError, UnicodeError, ValueError) as error:
        return LastRunReadResult(
            status=LastRunReadStatus.INVALID,
            path=path,
            error=str(error),
        )
    return LastRunReadResult(
        status=LastRunReadStatus.AVAILABLE,
        path=path,
        snapshot=snapshot,
    )
