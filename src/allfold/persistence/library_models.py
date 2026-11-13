"""Values for the independent Paper library, without Markdown workflow state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator

from allfold.canonicalize import normalize_abstract
from allfold.identifiers import normalize_external_id
from allfold.models import (
    Author, DomainModel, EvidenceDate, EvidenceDateKind, MetadataSource, NonEmptyStr,
    ProviderRecordRef, ProviderTopic, parse_publication_date,
)


def normalize_ordinary_dates(values: tuple[str, ...]) -> tuple[str, ...]:
    """An independent set, with month precision superseded by any known day in it."""
    for value in values:
        if parse_publication_date(value) is None or len(value) not in {7, 10}:
            raise ValueError("Ordinary dates require YYYY-MM or YYYY-MM-DD precision")
    days = {value for value in values if len(value) == 10}
    day_months = {value[:7] for value in days}
    return tuple(sorted(days | {value for value in values if len(value) == 7 and value not in day_months}))


class PreprintResult(DomainModel):
    """Caller-verified related results, never direct identities or ordinary dates."""

    model_config = ConfigDict(revalidate_instances="always")

    provider: Literal["arxiv", "biorxiv", "medrxiv", "europe_pmc", "crossref"]
    identifier: NonEmptyStr
    date: str | None = None
    version: NonEmptyStr | None = None
    url: NonEmptyStr | None = None
    version_family: NonEmptyStr | None = None
    first_version: bool = False

    @field_validator("identifier")
    @classmethod
    def validate_identifier(cls, value, info):
        provider = info.data.get("provider")
        normalized = normalize_external_id("doi" if provider == "crossref" else provider, value)
        if normalized is None:
            raise ValueError("Invalid supported Preprint identifier")
        return normalized

    @field_validator("date", mode="before")
    @classmethod
    def validate_date(cls, value):
        return parse_publication_date(value)


class PaperMetadata(DomainModel):
    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)

    title: NonEmptyStr
    discovered_at: datetime | None = None
    journal: NonEmptyStr | None = None
    conference: NonEmptyStr | None = None
    publication_type: Literal["journal", "conference", "preprint"] | None = None
    publication_date: str | None = None
    abstract: str | None = None
    authors: tuple[Author, ...] = ()
    author_keywords: tuple[NonEmptyStr, ...] = ()
    journal_issns: tuple[NonEmptyStr, ...] = ()
    indexed_terms: tuple[ProviderTopic, ...] = ()
    sources: tuple[MetadataSource, ...] = ()
    ordinary_dates: tuple[str, ...] = ()
    preprints: tuple[PreprintResult, ...] = ()
    preprint_evidence: tuple[EvidenceDate, ...] = ()
    preprint_relations: tuple[ProviderRecordRef, ...] = ()
    first_public_at: str | None = None
    notes: str = ""

    @field_validator("discovered_at")
    @classmethod
    def validate_discovered_at(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError("discovered_at must include a timezone")
        return value

    @field_validator("preprint_evidence")
    @classmethod
    def validate_preprint_evidence(cls, values):
        if any(item.kind != EvidenceDateKind.PREPRINT for item in values):
            raise ValueError("Only independent Preprint proof belongs in preprint_evidence")
        return tuple(sorted(set(values), key=lambda item: item.model_dump_json()))

    @field_validator("publication_date", "first_public_at", mode="before")
    @classmethod
    def validate_publication_date(cls, value: Any) -> str | None:
        return parse_publication_date(value)

    @field_validator("abstract")
    @classmethod
    def validate_abstract(cls, value: str | None) -> str | None:
        return value if value is not None and normalize_abstract(value) else None

    @field_validator("ordinary_dates")
    @classmethod
    def validate_ordinary_dates(cls, value):
        return normalize_ordinary_dates(value)

    @field_validator("preprints")
    @classmethod
    def validate_preprints(cls, value):
        return tuple(sorted(set(value), key=lambda result: result.model_dump_json()))


class MetadataDelta(DomainModel):
    """Eligible automatic candidates only; no user notes or whole-record replacement."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)
    abstract: str | None = None
    ordinary_dates: tuple[str, ...] = ()
    preprints: tuple[PreprintResult, ...] = ()
    sources: tuple[MetadataSource, ...] = ()
    preprint_evidence: tuple[EvidenceDate, ...] = ()
    preprint_relations: tuple[ProviderRecordRef, ...] = ()
    first_public_at: str | None = None

    @field_validator("preprint_evidence")
    @classmethod
    def validate_preprint_evidence(cls, values):
        return PaperMetadata.validate_preprint_evidence(values)

    @field_validator("first_public_at", mode="before")
    @classmethod
    def validate_first_public(cls, value):
        return parse_publication_date(value)

    @field_validator("abstract")
    @classmethod
    def validate_abstract(cls, value: str | None) -> str | None:
        return value if value is not None and normalize_abstract(value) else None

    @field_validator("ordinary_dates")
    @classmethod
    def validate_ordinary_dates(cls, value):
        return normalize_ordinary_dates(value)


class BodyReference(DomainModel):
    """One logical PDF result; it conveys no filesystem or download authority."""

    model_config = ConfigDict(revalidate_instances="always", str_strip_whitespace=False)
    relative_path: str
    source_url: NonEmptyStr | None = None
    size_bytes: int | None = Field(default=None, strict=True, ge=0)

    @field_validator("relative_path")
    @classmethod
    def validate_relative_path(cls, value):
        parts = value.split("/")
        if (len(parts) < 2 or parts[0] != "Documents" or any(part in {"", ".", ".."} for part in parts)
                or "\\" in value or ":" in value or any(ord(character) < 32 for character in value)):
            raise ValueError("Body must use a managed Documents/ relative path without traversal")
        return value


@dataclass(frozen=True, order=True)
class DirectIdentity:
    namespace: str
    value: str


@dataclass(frozen=True)
class WriteToken:
    workspace_id: UUID
    paper_id: UUID
    metadata_generation: int
    operation_generation: int
    abstract_generation: int | None
    body_generation: int


@dataclass(frozen=True)
class PaperRecord:
    workspace_id: UUID
    id: UUID
    excluded: bool
    metadata_generation: int
    operation_generation: int
    abstract_generation: int | None
    body_generation: int
    identities: tuple[DirectIdentity, ...]
    metadata: PaperMetadata | None
    body: BodyReference | None
    primary_identity: DirectIdentity | None = None
    revision: int = 0

    @property
    def token(self) -> WriteToken:
        return WriteToken(self.workspace_id, self.id, self.metadata_generation,
                          self.operation_generation, self.abstract_generation, self.body_generation)


@dataclass(frozen=True)
class CreationResult:
    paper: PaperRecord
    created: bool
