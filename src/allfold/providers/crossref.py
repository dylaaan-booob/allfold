"""Crossref known-identifier metadata normalization; no journal discovery."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from enum import Enum
from html.parser import HTMLParser
from typing import Annotated, Any
from pydantic import Field, ValidationError, model_validator

from allfold.identifiers import normalize_doi
from allfold.models import (
    Author,
    DomainModel,
    EvidenceDate,
    EvidenceDateKind,
    ExternalIds,
    MetadataSource,
    NonEmptyStr,
    ProviderWorkEvidence,
)
_ISSN_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{3}[0-9X]$")
_ORCID_PATTERN = re.compile(
    r"^(?:https?://orcid\.org/)?\d{4}-\d{4}-\d{4}-\d{3}[\dX]/?$",
    re.IGNORECASE,
)


class CrossrefDateKind(str, Enum):
    PUBLISHED = "published"
    PUBLISHED_ONLINE = "published-online"
    PUBLISHED_PRINT = "published-print"
    ISSUED = "issued"


_CROSSREF_DATE_KINDS = {kind.value: kind for kind in CrossrefDateKind}


StrictYear = Annotated[int, Field(strict=True, ge=1, le=9999)]
StrictMonth = Annotated[int, Field(strict=True, ge=1, le=12)]
StrictDay = Annotated[int, Field(strict=True, ge=1, le=31)]


class CrossrefPartialDate(DomainModel):
    kind: CrossrefDateKind
    year: StrictYear
    month: StrictMonth | None = None
    day: StrictDay | None = None

    @model_validator(mode="after")
    def validate_partial_date(self) -> CrossrefPartialDate:
        if self.day is not None and self.month is None:
            raise ValueError("day requires month")
        if self.month is not None:
            date(self.year, self.month, self.day or 1)
        return self


class CrossrefWorkRecord(DomainModel):
    doi: NonEmptyStr
    title: NonEmptyStr | None = None
    journal: NonEmptyStr | None = None
    abstract: NonEmptyStr | None = None
    authors: tuple[Author, ...] = ()
    issns: tuple[NonEmptyStr, ...] = ()
    dates: tuple[CrossrefPartialDate, ...] = ()
    work_type: NonEmptyStr | None = None
    provenance: MetadataSource

    def to_evidence(self) -> ProviderWorkEvidence:
        return ProviderWorkEvidence(
            provenance=self.provenance,
            title=self.title,
            journal=self.journal,
            abstract=self.abstract,
            authors=self.authors,
            external_ids=ExternalIds(
                doi=self.doi,
                crossref=self.provenance.record_id,
            ),
            dates=tuple(
                EvidenceDate(
                    kind=EvidenceDateKind.PUBLISHED_ONLINE if item.kind == CrossrefDateKind.PUBLISHED_ONLINE else EvidenceDateKind.PUBLISHED,
                    source_label=item.kind.value,
                    year=item.year,
                    month=item.month,
                    day=item.day,
                )
                for item in self.dates
            ),
        )


class CrossrefRecordError(RuntimeError):
    """A known-DOI response cannot be normalized safely."""


class _AbstractTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "abstract",
        "br",
        "list-item",
        "p",
        "sec",
        "title",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit(":", maxsplit=1)[-1]

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        if self._local_name(tag) in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._local_name(tag) in self._BLOCK_TAGS:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self.parts).split())


def _first_optional_string(
    value: Any,
    field: str,
    warnings: list[str],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, list):
        warnings.append(f"invalid {field} was treated as missing")
        return None
    for item in value:
        if isinstance(item, str) and item.strip():
            return item.strip()
    warnings.append(f"invalid {field} was treated as missing")
    return None


def _normalize_abstract(value: Any, warnings: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        warnings.append("invalid abstract was treated as missing")
        return None
    try:
        parser = _AbstractTextParser()
        parser.feed(value)
        parser.close()
        abstract = parser.text()
    except (ValueError, TypeError):
        warnings.append("invalid abstract was treated as missing")
        return None
    if not abstract:
        warnings.append("invalid abstract was treated as missing")
        return None
    return abstract


def _normalize_dates(message: dict[str, Any], warnings: list[str]) -> list[CrossrefPartialDate]:
    dates: list[CrossrefPartialDate] = []
    for field, value in message.items():
        kind = _CROSSREF_DATE_KINDS.get(field)
        if kind is None:
            continue
        if not isinstance(value, dict) or not isinstance(value.get("date-parts"), list):
            warnings.append(f"invalid {kind.value} date was ignored")
            continue
        for index, parts in enumerate(value["date-parts"]):
            if (
                not isinstance(parts, list)
                or not 1 <= len(parts) <= 3
                or any(type(part) is not int for part in parts)
            ):
                warnings.append(
                    f"invalid {kind.value} date-parts entry {index} was ignored"
                )
                continue
            year = parts[0]
            month = parts[1] if len(parts) >= 2 else None
            day = parts[2] if len(parts) == 3 else None
            try:
                if month is None:
                    date(year, 1, 1)
                else:
                    date(year, month, day or 1)
            except ValueError:
                warnings.append(
                    f"invalid {kind.value} date-parts entry {index} was ignored"
                )
                continue
            dates.append(
                CrossrefPartialDate(
                    kind=kind,
                    year=year,
                    month=month,
                    day=day,
                )
            )
    return dates


def _normalize_orcid(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip()
    if not _ORCID_PATTERN.fullmatch(candidate):
        return None
    identifier = re.sub(
        r"^https?://orcid\.org/",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).rstrip("/").upper()
    digits = identifier.replace("-", "")
    total = 0
    for character in digits[:15]:
        total = (total + int(character)) * 2
    result = (12 - total % 11) % 11
    check = "X" if result == 10 else str(result)
    if digits[-1] != check:
        return None
    return f"https://orcid.org/{identifier}"


def _normalize_authors(value: Any, warnings: list[str]) -> list[Author]:
    if value is None:
        return []
    if not isinstance(value, list):
        warnings.append("invalid author list was treated as missing")
        return []
    authors: list[Author] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, dict):
            warnings.append(f"invalid author entry {index} was ignored")
            continue
        name_parts = [
            part.strip()
            for field in ("given", "family")
            if isinstance((part := entry.get(field)), str) and part.strip()
        ]
        if name_parts:
            name = " ".join(name_parts)
        else:
            raw_name = entry.get("name")
            name = (
                raw_name.strip()
                if isinstance(raw_name, str) and raw_name.strip()
                else None
            )
        if name is None:
            warnings.append(f"author entry {index} without a usable name was ignored")
            continue
        raw_orcid = entry.get("ORCID")
        orcid = _normalize_orcid(raw_orcid)
        if raw_orcid is not None and orcid is None:
            warnings.append(f"invalid ORCID for author entry {index} was ignored")
        authors.append(Author(name=name, orcid=orcid))
    return authors


def _valid_issn(value: str) -> bool:
    if not _ISSN_PATTERN.fullmatch(value):
        return False
    digits = value.replace("-", "")
    values = [10 if character == "X" else int(character) for character in digits]
    return (
        sum(
            number * weight
            for number, weight in zip(values, range(8, 0, -1), strict=True)
        )
        % 11
        == 0
    )


def _normalize_issns(message: dict[str, Any], warnings: list[str]) -> list[str]:
    candidates: list[Any] = []
    raw_issns = message.get("ISSN")
    if raw_issns is not None:
        if isinstance(raw_issns, list):
            candidates.extend(raw_issns)
        else:
            warnings.append("invalid ISSN list was treated as missing")
    normalized: set[str] = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, str):
            warnings.append(f"invalid ISSN entry {index} was ignored")
            continue
        issn = candidate.strip().upper()
        if not _valid_issn(issn):
            warnings.append(f"invalid ISSN entry {index} was ignored")
            continue
        normalized.add(issn)
    return sorted(normalized)


def _normalize_crossref_message(
    message: object,
    retrieved_at: datetime,
) -> tuple[CrossrefWorkRecord, tuple[str, ...]]:
    if not isinstance(message, dict):
        raise CrossrefRecordError("Crossref response lacks a work message")
    try:
        doi = normalize_doi(message.get("DOI"))
    except ValueError as error:
        raise CrossrefRecordError("Crossref response has an invalid DOI") from error
    if doi is None:
        raise CrossrefRecordError("Crossref response is missing its DOI")

    normalized_retrieved_at = (
        retrieved_at.astimezone(timezone.utc)
        if retrieved_at.utcoffset() is not None
        else retrieved_at
    )
    warnings: list[str] = []
    title = _first_optional_string(message.get("title"), "title", warnings)
    abstract = _normalize_abstract(message.get("abstract"), warnings)
    authors = _normalize_authors(message.get("author"), warnings)
    issns = _normalize_issns(message, warnings)
    dates = _normalize_dates(message, warnings)

    work_type_raw = message.get("type")
    if work_type_raw is None:
        work_type = None
    elif isinstance(work_type_raw, str) and work_type_raw.strip():
        work_type = work_type_raw.strip()
    else:
        warnings.append("invalid type was treated as missing")
        work_type = None

    return (
        CrossrefWorkRecord(
            doi=doi,
            title=title,
            abstract=abstract,
            authors=tuple(authors),
            issns=tuple(issns),
            dates=tuple(dates),
            work_type=work_type,
            provenance=MetadataSource(
                provider="crossref",
                record_id=doi,
                retrieved_at=normalized_retrieved_at,
            ),
        ),
        tuple(warnings),
    )


def normalize_crossref_discovered_work(
    message: object,
    retrieved_at: datetime,
) -> tuple[CrossrefWorkRecord, tuple[str, ...]]:
    """Normalize one work-list item behind the provider boundary."""

    try:
        return _normalize_crossref_message(message, retrieved_at)
    except ValidationError as error:
        raise CrossrefRecordError(
            f"Crossref provider model validation failed: {error}"
        ) from error
