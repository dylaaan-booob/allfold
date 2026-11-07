"""Parsing helpers for durable Markdown workflow state."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from pydantic import ValidationError

from allfold.config import normalize_journal_issn
from allfold.identifiers import normalize_doi, strong_identifiers, normalize_external_id, RELIABLE_NAMESPACES
from allfold.models import (
    parse_publication_date,
    ExternalIds,
    ExportAttempt,
    ExportAttemptState,
    MetadataSource,
    ProviderTopic,
    EvidenceDate,
    WorkflowStatus,
)


MISSING_ABSTRACT = "Abstract unavailable from current MVP data sources."
_ABSTRACT_END_MARKER = "<!-- allfold:abstract-end -->"
_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.+?)\s*$")
_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
_MANAGED_SECTIONS = ("abstract", "sources")


class PaperJournalAttributionState(str, Enum):
    MISSING_OR_EMPTY = "MISSING_OR_EMPTY"
    VALID = "VALID"
    MALFORMED = "MALFORMED"


@dataclass(frozen=True)
class PaperMarkdownState:
    path: Path
    original: str
    frontmatter: dict[str, Any] | None
    body: str | None
    paper_id: UUID | None
    identity_external_ids: frozenset[tuple[str, str]]
    updateable: bool
    problems: tuple[str, ...]
    title: str | None = None
    journal: str | None = None
    publication_date: str | None = None
    abstract: str | None = None
    author_keywords: tuple[str, ...] = ()
    authors: tuple[str, ...] = ()
    status: WorkflowStatus | None = None
    discovered_at: datetime | None = None
    external_ids: ExternalIds | None = None
    sources: tuple[MetadataSource, ...] = ()
    journal_attribution_state: PaperJournalAttributionState = PaperJournalAttributionState.MISSING_OR_EMPTY
    journal_issns: tuple[str, ...] = ()
    conference: str | None = None
    publication_type: str | None = None
    first_public_at: str | None = None
    indexed_terms: tuple[ProviderTopic, ...] = ()
    date_evidence: tuple[EvidenceDate, ...] = ()
    export_attempt_present: bool = False
    export_attempt: ExportAttempt | None = None

    @property
    def effective_export_attempt_state(self) -> ExportAttemptState | None:
        """Legacy metadata is readable but has no current import authority."""
        if not self.export_attempt_present:
            return None
        if self.export_attempt is None:
            raise ValueError("malformed export_attempt")
        return ExportAttemptState.UNCERTAIN

    @property
    def automatic_export_eligible(self) -> bool:
        return (self.updateable and self.status is WorkflowStatus.KEPT
                and self.external_ids is not None and bool(self.external_ids.doi)
                and self.publication_type != "preprint")

    @property
    def has_identity(self) -> bool:
        return bool(self.paper_id or self.identity_external_ids)


@dataclass(frozen=True)
class _Heading:
    index: int
    level: int
    title: str


@dataclass(frozen=True)
class BodyLayout:
    headings: tuple[_Heading, ...]
    h1_index: int | None
    sections: dict[str, tuple[int, int]]
    notes_index: int | None
    abstract: str | None
    abstract_end_marker: int | None


def normalize_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _parse_document(
    contents: str,
    *,
    loader: type[yaml.SafeLoader] = yaml.SafeLoader,
) -> tuple[dict[str, Any], str]:
    lines = contents.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ValueError("missing opening YAML frontmatter delimiter")
    closing = next(
        (
            index
            for index, line in enumerate(lines[1:], start=1)
            if line.rstrip("\r\n") in {"---", "..."}
        ),
        None,
    )
    if closing is None:
        raise ValueError("missing closing YAML frontmatter delimiter")
    try:
        frontmatter = yaml.load("".join(lines[1:closing]), Loader=loader)
    except yaml.YAMLError as error:
        raise ValueError(f"invalid YAML frontmatter: {error}") from error
    if not isinstance(frontmatter, dict):
        raise ValueError("YAML frontmatter must be a mapping")
    return frontmatter, "".join(lines[closing + 1 :])


class _IdentityLoader(yaml.SafeLoader):
    """Reject overwritten YAML keys when establishing durable identity."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        keys = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in keys
                keys.add(key)
            except TypeError as error:
                raise yaml.constructor.ConstructorError(
                    None, None, "unhashable YAML key", key_node.start_mark,
                ) from error
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    None, None, "duplicate YAML key", key_node.start_mark,
                )
        return super().construct_mapping(node, deep=deep)


@dataclass(frozen=True)
class PaperIdentity:
    path: Path
    paper_id: UUID | None
    dois: frozenset[str]
    problems: tuple[str, ...]
    index_complete: bool
    identifiers: frozenset[tuple[str, str]] = frozenset()
    primary_doi: str | None = None


def parse_paper_identity(path: Path, contents: str) -> PaperIdentity | None:
    """Read only identity for capture-only matching; matching uses invocation-local identity.

    Full Paper validation remains independent and governs manual/export writes.
    Complete means every reliable identity in this candidate could be enumerated,
    not that its identity is unambiguous or its schema is supported.
    """
    try:
        frontmatter, _body = _parse_document(contents, loader=_IdentityLoader)
    except ValueError as error:
        return PaperIdentity(path, None, frozenset(), (str(error),), False)
    if frontmatter.get("type") != "paper":
        if isinstance(frontmatter.get("type"), str) and not any(
            key in frontmatter for key in ("doi", "external_ids", "id")
        ):
            return None
        return PaperIdentity(
            path, None, frozenset(), ("cannot determine Paper type/identity",), False,
        )

    problems: list[str] = []
    try:
        paper_id = UUID(str(frontmatter.get("id")))
    except (TypeError, ValueError, AttributeError):
        paper_id = None
        problems.append("id must be a valid UUID")
    complete = True
    raw_ids = frontmatter.get("external_ids")
    if raw_ids is not None and not isinstance(raw_ids, dict):
        problems.append("external_ids must be a mapping to establish identity")
        complete = False
        raw_ids = {}
    values = [("doi", frontmatter.get("doi"))]
    values.extend(
        ("external_ids.doi", value) for key, value in (raw_ids or {}).items()
        if isinstance(key, str) and key.strip().casefold() == "doi"
    )
    dois: set[str] = set()
    for field, raw in values:
        if raw is None:
            continue
        try:
            doi = normalize_doi(raw) if isinstance(raw, str) else None
        except ValueError:
            doi = None
        if doi is None or not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi):
            problems.append(f"{field} is not a valid DOI")
            complete = False
        else:
            dois.add(doi)
    primary_doi = next(iter(dois), None)
    if len(dois) > 1:
        problems.append("conflicting durable DOI identifiers")
    retired = sorted({'related_dois', 'identity_aliases'} & frontmatter.keys())
    if retired:
        problems.append('Incompatible legacy Paper identity fields (' + ', '.join(retired)
            + '); back up and explicitly rebuild through Settings → Reset → Workspace; no automatic migration')
        complete = False
    canonical_ids = {}
    for namespace, identifier in (raw_ids or {}).items():
        if not isinstance(namespace, str) or not namespace.strip():
            problems.append("external_ids contains an invalid namespace")
            complete = False
            continue
        namespace = namespace.strip().casefold()
        if identifier is None:
            continue
        normalized = normalize_external_id(namespace, identifier)
        if namespace in RELIABLE_NAMESPACES and (not isinstance(identifier, str) or not identifier.strip()):
            problems.append(f"external_ids.{namespace} is invalid")
            complete = False
        if normalized:
            canonical_ids[namespace] = normalized
    # Both fields directly assert identity. Preserve every conflicting DOI in
    # the blocked index so neither can later be mistaken for a new work.
    identifiers = strong_identifiers(canonical_ids) | frozenset(
        key for doi in dois for key in strong_identifiers({'doi': doi}))
    if not identifiers:
        problems.append("cannot establish reliable Paper identity")
        complete = False
    if "conference_id" in frontmatter or any(str(key).strip().casefold() == "dblp" for key in (raw_ids or {})):
        problems.append("Incompatible legacy Paper identity fields; back up Workspace and explicitly Reset before rebuilding")
        complete = False
    if "versions" in frontmatter or "preferred_version" in frontmatter:
        problems.append("unsupported pre-v0.5.2 Paper version schema")
    if "zotero_key" in frontmatter or frontmatter.get("status") == "in_zotero":
        problems.append("Incompatible legacy Paper schema (in_zotero/zotero_key); no automatic migration")
    return PaperIdentity(path, paper_id, frozenset(dois), tuple(problems), complete, identifiers, primary_doi)


def serialize_document(frontmatter: dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
    ).rstrip()
    return f"---\n{rendered}\n---\n{body}"


def _heading_title(value: str) -> str:
    return re.sub(r"[ \t]+#+[ \t]*$", "", value).strip()


def _contains_markdown_h2(value: str) -> bool:
    fence_character: str | None = None
    fence_length = 0
    for line in value.splitlines():
        fence = _FENCE.match(line)
        if fence_character is not None:
            marker = fence.group(1) if fence is not None else ""
            trailing = line[fence.end() :].strip() if fence is not None else ""
            if (
                marker.startswith(fence_character)
                and len(marker) >= fence_length
                and not trailing
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        heading = _HEADING.match(line)
        if heading is not None and len(heading.group(1)) == 2:
            return True
    return False


def render_abstract_section(abstract: str | None) -> str:
    abstract_text = MISSING_ABSTRACT if abstract is None else abstract
    marker = (
        f"\n{_ABSTRACT_END_MARKER}"
        if _contains_markdown_h2(abstract_text)
        else ""
    )
    return f"## Abstract\n\n{abstract_text}{marker}\n\n"


def analyze_body(body: str) -> BodyLayout:
    lines = body.splitlines(keepends=True)
    headings: list[_Heading] = []
    abstract_end_markers: list[int] = []
    fence_character: str | None = None
    fence_length = 0
    for index, line in enumerate(lines):
        fence = _FENCE.match(line)
        if fence_character is not None:
            marker = fence.group(1) if fence is not None else ""
            trailing = line[fence.end() :].strip() if fence is not None else ""
            if (
                marker.startswith(fence_character)
                and len(marker) >= fence_length
                and not trailing
            ):
                fence_character = None
                fence_length = 0
            continue
        if fence is not None:
            marker = fence.group(1)
            fence_character = marker[0]
            fence_length = len(marker)
            continue
        if line.strip() == _ABSTRACT_END_MARKER:
            abstract_end_markers.append(index)
            continue
        heading = _HEADING.match(line.rstrip("\r\n"))
        if heading is not None:
            headings.append(
                _Heading(
                    index=index,
                    level=len(heading.group(1)),
                    title=_heading_title(heading.group(2)),
                )
            )
    if fence_character is not None:
        raise ValueError("unclosed fenced code block")
    if len(abstract_end_markers) > 1:
        raise ValueError("multiple managed Abstract end markers")

    abstract_end_marker = (
        abstract_end_markers[0] if abstract_end_markers else None
    )
    marked_abstract_heading: _Heading | None = None
    if abstract_end_marker is not None:
        marked_candidates = [
            heading
            for heading in headings
            if heading.level == 2
            and normalize_text(heading.title) == "abstract"
            and heading.index < abstract_end_marker
        ]
        if not marked_candidates:
            raise ValueError("managed Abstract end marker has no Abstract heading")
        marked_abstract_heading = marked_candidates[0]
        headings = [
            heading
            for heading in headings
            if not (
                marked_abstract_heading.index < heading.index < abstract_end_marker
            )
        ]

    h1_indexes = [heading.index for heading in headings if heading.level == 1]
    if len(h1_indexes) > 1:
        raise ValueError("multiple primary H1 headings")
    sections: dict[str, tuple[int, int]] = {}
    notes_indexes: list[int] = []
    for position, heading in enumerate(headings):
        if heading.level != 2:
            continue
        normalized = normalize_text(heading.title)
        if normalized == "notes":
            notes_indexes.append(heading.index)
        if normalized not in _MANAGED_SECTIONS:
            continue
        if normalized in sections:
            raise ValueError(f"duplicate managed section {heading.title!r}")
        end = len(lines)
        for candidate in headings[position + 1 :]:
            if candidate.level <= 2:
                end = candidate.index
                break
        sections[normalized] = (heading.index, end)

    if marked_abstract_heading is not None:
        marker_end = abstract_end_marker + 1
        if marker_end < len(lines) and not lines[marker_end].strip():
            marker_end += 1
        sections["abstract"] = (marked_abstract_heading.index, marker_end)

    abstract: str | None = None
    if "abstract" in sections:
        start, end = sections["abstract"]
        content_end = abstract_end_marker if abstract_end_marker is not None else end
        value = "".join(lines[start + 1 : content_end]).strip("\r\n")
        abstract = None if value == MISSING_ABSTRACT else value
    return BodyLayout(
        headings=tuple(headings),
        h1_index=h1_indexes[0] if h1_indexes else None,
        sections=sections,
        notes_index=notes_indexes[0] if len(notes_indexes) == 1 else None,
        abstract=abstract,
        abstract_end_marker=abstract_end_marker,
    )


def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        raise ValueError("discovered_at must be an ISO datetime")
    if parsed.utcoffset() is None:
        raise ValueError("discovered_at must include a timezone")
    return parsed


def _identity_external_ids(
    frontmatter: dict[str, Any],
    problems: list[str],
) -> tuple[set[tuple[str, str]], dict[str, str | None]]:
    identities: set[tuple[str, str]] = set()
    values: dict[str, str | None] = {}
    raw = frontmatter.get("external_ids", {})
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        problems.append("external_ids must be a mapping")
        raw = {}
    for namespace, identifier in raw.items():
        if not isinstance(namespace, str) or not namespace.strip():
            problems.append("external_ids contains an invalid namespace")
            continue
        normalized_namespace = namespace.strip().casefold()
        if identifier is None and normalized_namespace in {
            "openalex",
            "doi",
            "arxiv",
            "crossref",
        }:
            values[normalized_namespace] = None
            continue
        if not isinstance(identifier, str) or not identifier.strip():
            problems.append(f"external_ids.{namespace} must be a non-empty string")
            continue
        normalized_identifier = identifier.strip()
        if normalized_namespace == "doi":
            try:
                normalized_identifier = normalize_doi(normalized_identifier) or ""
            except ValueError:
                normalized_identifier = ""
        if not normalized_identifier:
            problems.append(f"external_ids.{namespace} is invalid")
            continue
        if normalized_namespace == "doi":
            identities.add((normalized_namespace, normalized_identifier))
        previous = values.get(normalized_namespace)
        if previous is not None and previous != identifier.strip():
            problems.append(f"external_ids has conflicting {normalized_namespace} values")
        values[normalized_namespace] = identifier.strip()

    for field, namespace in (
        ("doi", "doi"),
    ):
        identifier = frontmatter.get(field)
        if identifier is None:
            continue
        if not isinstance(identifier, str) or not identifier.strip():
            problems.append(f"{field} must be a non-empty string or null")
            continue
        normalized_identifier = identifier.strip()
        if namespace == "doi":
            try:
                normalized_identifier = normalize_doi(normalized_identifier) or ""
            except ValueError:
                normalized_identifier = ""
        if not normalized_identifier:
            problems.append(f"{field} is invalid")
            continue
        if namespace == "doi":
            identities.add((namespace, normalized_identifier))
        previous = values.get(namespace)
        if previous is not None and previous != identifier.strip():
            previous_normalized = normalize_external_id(namespace, previous) or previous.strip()
            normalized_identifier = normalize_external_id(namespace, normalized_identifier) or normalized_identifier
            if previous_normalized != normalized_identifier:
                problems.append(f"{field} conflicts with external_ids.{namespace}")
        values[namespace] = identifier.strip()
    return identities, values


def _parse_authors(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("authors must be a list of names")
    if any(not isinstance(name, str) or not name.strip() for name in value):
        raise ValueError("authors must contain only non-empty names")
    if any("[[" in name or "]]" in name or name.strip().startswith(("Authors/", "Authors\\"))
           for name in value):
        raise ValueError("authors must contain names without Author links or paths")
    return tuple(value)


def _parse_journal_attribution(
    frontmatter: dict[str, Any],
) -> tuple[PaperJournalAttributionState, tuple[str, ...]]:
    """Parse optional venue context independently of core Paper safety."""
    state = PaperJournalAttributionState
    if "journal_issns" not in frontmatter:
        return state.MISSING_OR_EMPTY, ()
    raw = frontmatter["journal_issns"]
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        return state.MALFORMED, ()
    if not raw:
        return state.MISSING_OR_EMPTY, ()
    try:
        identities = tuple(sorted({normalize_journal_issn(item) for item in raw}))
    except ValueError:
        return state.MALFORMED, ()
    return state.VALID, identities


def parse_paper_state(
    path: Path,
    contents: str,
) -> PaperMarkdownState | None:
    try:
        frontmatter, body = _parse_document(contents)
    except ValueError as error:
        return PaperMarkdownState(
            path=path,
            original=contents,
            frontmatter=None,
            body=None,
            paper_id=None,
            identity_external_ids=frozenset(),
            updateable=False,
            problems=(str(error),),
        )
    if frontmatter.get("type") != "paper":
        return None

    journal_attribution_state, journal_issns = _parse_journal_attribution(frontmatter)
    problems: list[str] = []
    paper_id: UUID | None = None
    try:
        paper_id = UUID(str(frontmatter.get("id")))
    except (TypeError, ValueError, AttributeError):
        problems.append("id must be a valid UUID")

    identity_external_ids, external_values = _identity_external_ids(
        frontmatter, problems
    )
    if "conference_id" in frontmatter or "dblp" in external_values:
        problems.append("Incompatible legacy Paper identity fields; back up Workspace and explicitly Reset before rebuilding")
    if "versions" in frontmatter or "preferred_version" in frontmatter:
        problems.append("unsupported pre-v0.5.2 Paper version schema")

    sources: list[MetadataSource] = []
    raw_sources = frontmatter.get("sources", [])
    if not isinstance(raw_sources, list):
        problems.append("sources must be a list")
        raw_sources = []
    for index, raw in enumerate(raw_sources):
        try:
            sources.append(MetadataSource.model_validate(raw))
        except ValidationError as error:
            problems.append(f"sources[{index}] is invalid: {error.errors()[0]['msg']}")

    evidence_fields = {}
    for name, model in (("date_evidence", EvidenceDate), ("indexed_terms", ProviderTopic)):
        raw = frontmatter.get(name, [])
        try:
            if not isinstance(raw, list):
                raise ValueError(f"{name} must be a list")
            evidence_fields[name] = tuple(model.model_validate(item) for item in raw)
        except (ValueError, ValidationError) as error:
            problems.append(f"{name} is invalid: {error}")
            evidence_fields[name] = ()

    title = frontmatter.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append("title must be a non-empty string")
        title = None
    journal = frontmatter.get("journal")
    if journal is not None and (not isinstance(journal, str) or not journal.strip()):
        problems.append("journal must be a non-empty string or null")
        journal = None
    for name in ("conference",):
        if frontmatter.get(name) is not None and (not isinstance(frontmatter[name], str) or not frontmatter[name].strip()):
            problems.append(f"{name} must be a non-empty string or null")
    date_fields = {}
    for name in ("first_public_at",):
        try:
            date_fields[name] = parse_publication_date(frontmatter.get(name))
        except ValueError as error:
            problems.append(f"{name}: {error}")
    if frontmatter.get("publication_type") not in {None, "journal", "conference", "preprint"}:
        problems.append("invalid publication_type")
    try:
        publication_date = parse_publication_date(frontmatter.get("publication_date"))
    except ValueError as error:
        problems.append(str(error))
        publication_date = None

    raw_keywords = frontmatter.get("author_keywords", [])
    if not isinstance(raw_keywords, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_keywords
    ):
        problems.append("author_keywords must be a list of non-empty strings")
        keywords: tuple[str, ...] = ()
    else:
        keywords = tuple(item.strip() for item in raw_keywords)

    try:
        authors = _parse_authors(frontmatter.get("authors"))
    except ValueError as error:
        problems.append(str(error))
        authors = ()
    try:
        status = WorkflowStatus(frontmatter.get("status"))
    except (TypeError, ValueError):
        problems.append("status is invalid")
        status = None
    try:
        discovered_at = _parse_datetime(frontmatter.get("discovered_at"))
    except (TypeError, ValueError) as error:
        problems.append(str(error))
        discovered_at = None
    if "zotero_key" in frontmatter or frontmatter.get("status") == "in_zotero":
        problems.append("Incompatible legacy Paper schema (in_zotero/zotero_key); export is disabled. No automatic migration.")

    try:
        external_ids = ExternalIds.model_validate(external_values)
    except ValidationError as error:
        problems.append(f"external_ids is invalid: {error.errors()[0]['msg']}")
        external_ids = None
    if external_ids is not None:
        doi = normalize_doi(external_ids.doi)
        if doi is not None and not re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi):
            problems.append("current Paper has an invalid DOI")
        else:
            external_ids = external_ids.model_copy(update={"doi": doi})
    identity = parse_paper_identity(path, contents)
    if identity is not None:
        problems.extend(problem for problem in identity.problems if problem not in problems)
        identity_external_ids = set(identity.identifiers)
    export_attempt_present = "export_attempt" in frontmatter
    export_attempt = None
    if export_attempt_present:
        try:
            export_attempt = ExportAttempt.model_validate(frontmatter["export_attempt"])
        except (ValidationError, ValueError):
            # 历史字段原样保存；畸形旧记录不得阻断当前 Kept 导入。
            export_attempt = None
    try:
        layout = analyze_body(body)
        abstract = layout.abstract
    except ValueError as error:
        problems.append(str(error))
        abstract = None

    return PaperMarkdownState(
        path=path,
        original=contents,
        frontmatter=frontmatter,
        body=body,
        paper_id=paper_id,
        identity_external_ids=frozenset(identity_external_ids),
        updateable=not problems,
        problems=tuple(problems),
        title=title.strip() if title is not None else None,
        journal=journal.strip() if journal is not None else None,
        publication_date=publication_date,
        abstract=abstract,
        author_keywords=keywords,
        authors=authors,
        status=status,
        discovered_at=discovered_at,
        external_ids=external_ids,
        sources=tuple(sources),
        journal_attribution_state=journal_attribution_state,
        journal_issns=journal_issns,
        conference=frontmatter.get("conference"),
        publication_type=frontmatter.get("publication_type"),
        first_public_at=date_fields.get("first_public_at"),
        indexed_terms=evidence_fields["indexed_terms"],
        date_evidence=evidence_fields["date_evidence"],
        export_attempt_present=export_attempt_present,
        export_attempt=export_attempt,
    )
