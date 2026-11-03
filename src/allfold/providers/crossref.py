"""Crossref journal discovery with metadata supplied by Manifest responses."""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from enum import Enum
from html.parser import HTMLParser
from time import monotonic
from typing import Annotated, Any
from urllib.parse import urlencode

import httpx
from pydantic import Field, ValidationError, model_validator

from allfold.config import JournalConfig
from allfold.http_client import create_http_client
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
from allfold.progress import (
    ActivityKind,
    ActivityUpdate,
    ProgressCallback,
    ProgressEvent,
)

CROSSREF_BASE_URL = "https://api.crossref.org"
CROSSREF_PAGE_SIZE = 1000
# Fixed unique-ISSN batches, each paged over the complete configured date window.
_CROSSREF_MANIFEST_BATCH_SIZE = 20
_CROSSREF_MANIFEST_FIELDS = "DOI,ISSN,type,title,abstract,author,published,published-online,published-print,issued"
_ISSN_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{3}[0-9X]$")
_RATE_LIMIT_INTERVAL_PATTERN = re.compile(r"^\s*(\d+(?:\.\d+)?)s\s*$", re.IGNORECASE)
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
                    kind=EvidenceDateKind(item.kind.value),
                    year=item.year,
                    month=item.month,
                    day=item.day,
                )
                for item in self.dates
            ),
        )


class CrossrefIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class CrossrefDiscoveryIssue:
    severity: CrossrefIssueSeverity
    stage: str
    journal: str
    issn: str
    message: str
    record_id: str | None = None
    doi: str | None = None


class CrossrefError(RuntimeError):
    """Base class for Crossref provider failures."""


class CrossrefRequestError(CrossrefError):
    """A Crossref request failed or returned invalid transport data."""


class CrossrefRecordError(CrossrefError):
    """A Crossref record cannot be normalized safely."""


def _report_activity(
    callback: ProgressCallback | None,
    activity: ActivityUpdate | None,
) -> None:
    if callback is not None and activity is not None:
        callback(ProgressEvent(activity=activity))


@dataclass
class _CrossrefPacingState:
    minimum_interval: float = 0.0
    next_allowed_at: float = 0.0


class CrossrefClient:
    """Own one pooled HTTP client; close it after each execution, usually with `with`."""

    def __init__(
        self,
        *,
        mailto: str | None = None,
        base_url: str = CROSSREF_BASE_URL,
        timeout: float = 30,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mailto = mailto.strip() if mailto and mailto.strip() else None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http_client = create_http_client(
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )
        self._sleep = sleep
        self._pacing_state = _CrossrefPacingState()

    def close(self) -> None:
        self._http_client.close()

    def __enter__(self) -> CrossrefClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _update_rate_limit(
        self, headers: Any, pacing: _CrossrefPacingState, request_started_at: float,
    ) -> None:
        if headers is None or not hasattr(headers, "get"):
            return
        raw_limit = headers.get("X-Rate-Limit-Limit")
        raw_interval = headers.get("X-Rate-Limit-Interval")
        if not isinstance(raw_limit, str) or not isinstance(raw_interval, str):
            return
        try:
            limit = int(raw_limit.strip())
        except ValueError:
            return
        match = _RATE_LIMIT_INTERVAL_PATTERN.fullmatch(raw_interval)
        if limit <= 0 or match is None:
            return
        interval = float(match.group(1))
        if not math.isfinite(interval) or interval <= 0:
            return
        delay = interval / limit
        if not math.isfinite(delay) or delay <= 0:
            return
        pacing.minimum_interval = delay
        pacing.next_allowed_at = request_started_at + delay

    def _wait_for_request(
        self,
        pacing: _CrossrefPacingState,
        *,
        retry_at: float | None,
        retry_reason: str,
        progress_callback: ProgressCallback | None,
        activity: ActivityUpdate | None,
    ) -> None:
        deadline = max(pacing.next_allowed_at, retry_at or 0.0)
        delay = max(0.0, deadline - monotonic())
        retrying = retry_at is not None
        if delay <= 0 and not retrying:
            return
        if activity is not None:
            detail = (
                f"{retry_reason} · backoff {delay:g}s"
                if retrying else f"provider pacing {delay:g}s"
            )
            _report_activity(
                progress_callback,
                replace(
                    activity,
                    kind=ActivityKind.RETRYING if retrying else ActivityKind.WAITING,
                    label=("Retrying Crossref request" if retrying
                           else "Waiting for Crossref rate limit"),
                    detail=(
                        f"{activity.detail} · {detail}" if activity.detail else detail
                    ),
                ),
            )
        # Activity reporting and response handling also consume deadline time.
        remaining = max(0.0, deadline - monotonic())
        if remaining > 0:
            self._sleep(remaining)


    def get_manifest_page(
        self, issns: Sequence[str], from_date: date, to_date: date, *,
        cursor: str = "*", progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        if not issns or len(issns) > _CROSSREF_MANIFEST_BATCH_SIZE:
            raise ValueError("manifest ISSN batch must be nonempty and internally bounded")
        if from_date > to_date:
            raise ValueError("from_date must not be after to_date")
        if any(not _valid_issn(issn) for issn in issns):
            raise ValueError("manifest requires normalized valid ISSNs")
        filters = [f"issn:{issn}" for issn in issns]
        filters += [f"from-pub-date:{from_date.isoformat()}", f"until-pub-date:{to_date.isoformat()}"]
        params = {"filter": ",".join(filters), "select": _CROSSREF_MANIFEST_FIELDS,
                  "rows": str(CROSSREF_PAGE_SIZE), "cursor": cursor}
        return self._request_json("/v1/works", params, progress_callback=progress_callback,
                                  activity=ActivityUpdate(kind=ActivityKind.WORKING, source="crossref",
                                      operation="manifest", label="Retrieving Crossref manifest",
                                      detail=f"{', '.join(issns)} · {from_date} .. {to_date}", unit="work"))


    def _request_json(
        self,
        path: str,
        params: dict[str, str],
        *,
        progress_callback: ProgressCallback | None = None,
        activity: ActivityUpdate | None = None,
    ) -> dict[str, Any]:
        query = dict(params)
        if self.mailto is not None:
            query["mailto"] = self.mailto
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "Accept": "application/json",
            "User-Agent": "allfold/0.1.0",
        }

        pacing = self._pacing_state
        retry_at = None
        retry_reason = ""
        for attempt in range(3):
            self._wait_for_request(
                pacing, retry_at=retry_at, retry_reason=retry_reason,
                progress_callback=progress_callback, activity=activity,
            )
            attempt_number = attempt + 1
            if activity is not None:
                _report_activity(
                    progress_callback,
                    replace(
                        activity,
                        kind=ActivityKind.WORKING,
                        label="Requesting Crossref",
                        detail=(
                            f"{activity.detail} · attempt {attempt_number}/3"
                            if activity.detail
                            else f"attempt {attempt_number}/3"
                        ),
                    ),
                )
            request_started_at = monotonic()
            pacing.next_allowed_at = request_started_at + pacing.minimum_interval
            try:
                response = self._http_client.get(url, headers=headers, timeout=self.timeout)
                self._update_rate_limit(response.headers, pacing, request_started_at)
                response.raise_for_status()
                payload = json.loads(response.content)
                if not isinstance(payload, dict):
                    raise CrossrefRequestError(
                        "Crossref returned a non-object JSON response"
                    )
                if activity is not None:
                    _report_activity(
                        progress_callback,
                        replace(
                            activity,
                            kind=ActivityKind.WORKING,
                            label="Received Crossref response",
                            detail=(
                                f"{activity.detail} · attempt {attempt_number}/3"
                                if activity.detail
                                else f"attempt {attempt_number}/3"
                            ),
                        ),
                    )
                return payload
            except httpx.HTTPStatusError as error:
                status_code = error.response.status_code
                if (status_code == 429 or status_code >= 500) and attempt < 2:
                    retry_at = request_started_at + 2**attempt
                    retry_reason = f"HTTP {status_code}"
                    continue
                raise CrossrefRequestError(
                    f"Crossref request failed with HTTP {status_code}"
                ) from error
            except httpx.RequestError as error:
                if attempt < 2:
                    retry_at = request_started_at + 2**attempt
                    retry_reason = "transport failure"
                    continue
                raise CrossrefRequestError(
                    f"Crossref request failed: {error}"
                ) from error
            except (json.JSONDecodeError, UnicodeDecodeError) as error:
                raise CrossrefRequestError("Crossref returned invalid JSON") from error

        raise AssertionError("unreachable")


@dataclass(frozen=True)
class CrossrefManifestMember:
    doi: str
    issns: tuple[str, ...]
    records: tuple[CrossrefWorkRecord, ...]
    work_type: str | None = None
    type_conflict: bool = False

    def __post_init__(self) -> None:
        if normalize_doi(self.doi) != self.doi or not re.fullmatch(r"10\.\d{4,9}/\S+", self.doi):
            raise ValueError("manifest DOI must already be normalized")
        if self.issns != tuple(sorted(set(self.issns))) or any(not _valid_issn(i) for i in self.issns):
            raise ValueError("manifest ISSNs must be normalized, sorted and unique")


@dataclass(frozen=True)
class CrossrefManifestUnit:
    issn: str
    members: tuple[CrossrefManifestMember, ...]
    complete: bool
    issues: tuple[str, ...] = ()


def _crossref_work_list(payload: dict[str, Any]) -> list[Any]:
    if payload.get("status") != "ok" or payload.get("message-type") != "work-list":
        raise CrossrefRequestError("Crossref batch response has an invalid envelope")
    message = payload.get("message")
    if not isinstance(message, dict) or not isinstance(message.get("items"), list):
        raise CrossrefRequestError("Crossref batch response lacks a valid items list")
    return message["items"]


def normalize_crossref_manifest_member(
    item: object, retrieved_at: datetime,
) -> tuple[CrossrefManifestMember, tuple[str, ...]]:
    record, warnings = normalize_crossref_discovered_work(item, retrieved_at)
    try:
        return CrossrefManifestMember(record.doi, record.issns, (record,), record.work_type), warnings
    except ValueError as error:
        raise CrossrefRecordError("Crossref manifest has an invalid DOI") from error


def _merge_manifest_members(
    members: Sequence[CrossrefManifestMember],
) -> tuple[tuple[CrossrefManifestMember, ...], tuple[str, ...]]:
    merged: dict[str, CrossrefManifestMember] = {}
    issues: list[str] = []
    for member in members:
        previous = merged.get(member.doi)
        if previous is None:
            merged[member.doi] = member
        else:
            kinds = {kind for kind in (previous.work_type, member.work_type) if kind is not None}
            conflict = previous.type_conflict or member.type_conflict or len(kinds) > 1
            if len(kinds) > 1:
                issues.append(f"conflicting Crossref types for {member.doi}")
            merged[member.doi] = CrossrefManifestMember(
                member.doi, tuple(sorted(set(previous.issns) | set(member.issns))),
                previous.records + tuple(record for record in member.records if record not in previous.records),
                next(iter(kinds)) if len(kinds) == 1 and not conflict else None, conflict,
            )
    return tuple(merged.values()), tuple(issues)


def _read_manifest_page(
    payload: dict[str, Any], issns: Sequence[str], retrieved_at: datetime,
) -> tuple[tuple[CrossrefManifestMember, ...], int, tuple[str, ...], bool]:
    items = _crossref_work_list(payload)
    members, issues = [], []
    valid = True
    for item in items:
        try:
            member, warnings = normalize_crossref_manifest_member(item, retrieved_at)
            issues.extend(warnings)
            if not set(member.issns).intersection(issns):
                raise CrossrefRecordError("Crossref manifest member cannot map to a queried ISSN")
            members.append(member)
        except CrossrefRecordError as error:
            valid = False
            issues.append(str(error))
    merged, conflicts = _merge_manifest_members(members)
    return merged, len(items), tuple(issues) + conflicts, valid


def retrieve_crossref_manifests(
    client: CrossrefClient, issns: Sequence[str], from_date: date, to_date: date, *,
    retrieved_at: datetime | None = None,
    progress_callback: ProgressCallback | None = None,
) -> tuple[CrossrefManifestUnit, ...]:
    """Page fixed ISSN batches over one date window, retaining partial evidence."""
    if from_date > to_date:
        raise ValueError("from_date must not be after to_date")
    ordered = tuple(dict.fromkeys(issns))
    timestamp = retrieved_at or datetime.now(timezone.utc)
    result = []
    for offset in range(0, len(ordered), _CROSSREF_MANIFEST_BATCH_SIZE):
        group = ordered[offset:offset + _CROSSREF_MANIFEST_BATCH_SIZE]
        members, issues, seen = (), [], set()
        complete = True
        cursor = "*"
        while True:
            seen.add(cursor)
            try:
                payload = client.get_manifest_page(group, from_date, to_date, cursor=cursor,
                                                   progress_callback=progress_callback)
                page, raw_count, warnings, page_valid = _read_manifest_page(payload, group, timestamp)
                members, conflicts = _merge_manifest_members((*members, *page))
                issues.extend((*warnings, *conflicts))
                complete = complete and page_valid
                # Termination uses raw item count, before DOI deduplication or record rejection.
                if raw_count < CROSSREF_PAGE_SIZE:
                    break
                next_cursor = payload["message"].get("next-cursor")
                if not isinstance(next_cursor, str) or not next_cursor.strip():
                    raise CrossrefRequestError("Crossref manifest lacks a valid next cursor")
                if next_cursor in seen:
                    raise CrossrefRequestError("Crossref returned a repeated cursor")
                cursor = next_cursor
            except CrossrefError as error:
                complete = False
                issues.append(str(error))
                break
        result.extend(CrossrefManifestUnit(
            issn, tuple(member for member in members if issn in member.issns), complete, tuple(issues),
        ) for issn in group)
    return tuple(result)


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


@dataclass(frozen=True)
class CrossrefJournalQuery:
    journal: JournalConfig
    query_issns: tuple[str, ...]


def plan_crossref_queries(journals: Sequence[JournalConfig]) -> tuple[CrossrefJournalQuery, ...]:
    """Use only configured ISSN/eISSN, independent of OpenAlex Source aliases."""
    return tuple(CrossrefJournalQuery(j, j.identifiers) for j in journals)
