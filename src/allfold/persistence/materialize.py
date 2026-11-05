"""Capture-only Obsidian Markdown materialization over durable corpus state."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from contextlib import ExitStack, nullcontext
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from threading import Event
from uuid import UUID

import yaml

from allfold.identifiers import normalize_doi, strong_identifiers, paper_identifiers
from allfold.persistence.inbox import render_default_inbox_base
from allfold.persistence.markdown_state import (
    MISSING_ABSTRACT,
    PaperIdentity,
    parse_paper_identity,
    render_abstract_section,
)
from allfold.models import (
    CanonicalPaper,
    MetadataSource,
)
from allfold.persistence.naming import paper_filename
from allfold.progress import (
    ActivityKind,
    ActivityUpdate,
    ProgressCallback,
    ProgressEvent,
)
from allfold.persistence.safe_write import (
    CompareReadError,
    ContentChangedError,
    TextWriteCommittedError,
    WorkspaceOperationLock,
    WorkspaceTextDirectory,
    workspace_text_directory,
    read_text_exact,
    workspace_operation_lock,
)


class MaterializationIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class MaterializationIssue:
    path: Path
    message: str
    severity: MaterializationIssueSeverity = MaterializationIssueSeverity.ERROR


@dataclass(frozen=True)
class MaterializationResult:
    created_papers: tuple[Path, ...]
    existing_papers: tuple[Path, ...]
    issues: tuple[MaterializationIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(
            issue.severity is MaterializationIssueSeverity.ERROR
            for issue in self.issues
        )


@dataclass(frozen=True)
class _PaperMatch:
    state: PaperIdentity | None
    blocked: bool = False


@dataclass(frozen=True)
class _PaperWrite:
    path: Path
    contents: str


def _report_activity(
    callback: ProgressCallback | None,
    activity: ActivityUpdate,
) -> None:
    if callback is not None:
        callback(ProgressEvent(activity=activity))


def _yaml_frontmatter(values: dict[str, object]) -> str:
    rendered = yaml.safe_dump(values, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{rendered}\n---\n"


def _source_summary(sources: Sequence[MetadataSource]) -> str:
    if not sources:
        return "- None recorded."
    return "\n".join(
        f"- {source.provider}: {source.record_id}; "
        f"retrieved_at={source.retrieved_at.isoformat()}"
        for source in sources
    )


def render_paper_markdown(paper: CanonicalPaper) -> str:
    """Render a new Paper note without touching the filesystem."""

    doi = normalize_doi(paper.external_ids.doi)
    if not paper_identifiers(paper):
        raise ValueError("Paper requires a reliable identity")
    external_ids = paper.external_ids.model_copy(update={"doi": doi})
    workflow = paper.workflow.model_dump(mode="json")
    frontmatter: dict[str, object] = {
        "type": "paper",
        "id": str(paper.id),
        "title": paper.metadata.title,
        "authors": [author.name for author in paper.authors],
        "journal": paper.metadata.journal,
        "publication_date": paper.metadata.publication_date,
        "doi": doi,
        "related_dois": list(paper.related_dois),
        "identity_aliases": [item.model_dump(mode="json") for item in paper.identity_aliases],
        "conference": paper.metadata.conference,
        "conference_id": paper.metadata.conference_id,
        "publication_type": paper.metadata.publication_type,
        "first_public_at": paper.metadata.first_public_at,
        "accepted_at": paper.metadata.accepted_at,
        "accepted_approximate": paper.metadata.accepted_approximate,
        "date_note": paper.metadata.date_note,
        "date_evidence": [item.model_dump(mode="json", exclude_none=True) for item in paper.date_evidence],
        "indexed_terms": [item.model_dump(mode="json", exclude_none=True) for item in paper.indexed_terms],
        "openalex_id": paper.external_ids.openalex,
        "arxiv_id": paper.external_ids.arxiv,
        **({"author_keywords": list(paper.metadata.author_keywords)} if paper.metadata.author_keywords else {}),
        "status": workflow["status"],
        "discovered_at": workflow["discovered_at"],
        "external_ids": external_ids.model_dump(
            mode="json", exclude_none=False
        ),
        "sources": [source.model_dump(mode="json") for source in paper.sources],
    }
    if paper.journal_issns:
        frontmatter["journal_issns"] = list(paper.journal_issns)
    serialized = _yaml_frontmatter(frontmatter)
    if paper.metadata.publication_date is not None:
        serialized = re.sub(r"^publication_date:.*$",
                            f"publication_date: '{paper.metadata.publication_date}'", serialized, flags=re.MULTILINE)
    return (
        f"{serialized}\n"
        f"# {paper.metadata.title}\n\n"
        f"{render_abstract_section(paper.metadata.abstract)}"
        f"## Sources\n\n{_source_summary(paper.sources)}\n\n"
        "## Notes\n"
    )


def _create_file(path: Path, contents: str, directory: WorkspaceTextDirectory) -> tuple[str | None, str | None]:
    try:
        directory.create(path.name, contents)
    except TextWriteCommittedError as error:
        return "created", str(error)
    except FileExistsError:
        target = directory.path / path.name
        if target.is_file() and not target.is_symlink():
            return "existing", None
        return None, "target exists but is not a regular file"
    except (OSError, ContentChangedError, CompareReadError) as error:
        return None, str(error)
    return "created", None


def _scan_papers(
    papers_dir: Path,
    issues: list[MaterializationIssue],
) -> tuple[list[PaperIdentity], bool]:
    states: list[PaperIdentity] = []
    complete = True
    try:
        paths = sorted(papers_dir.iterdir())
    except OSError as error:
        issues.append(MaterializationIssue(papers_dir, f"cannot enumerate Papers: {error}"))
        return states, False
    for path in paths:
        if path.suffix != ".md":
            continue
        if path.is_symlink() or not path.is_file():
            issues.append(MaterializationIssue(path, "Paper target is not a regular file"))
            complete = False
            continue
        try:
            state = parse_paper_identity(path, read_text_exact(path))
        except (OSError, UnicodeError) as error:
            issues.append(MaterializationIssue(path, f"cannot read Paper: {error}"))
            complete = False
            continue
        if state is None:
            continue
        states.append(state)
        complete = complete and state.index_complete
        issues.extend(MaterializationIssue(path, problem) for problem in state.problems)
    if not complete:
        issues.append(MaterializationIssue(papers_dir, "Paper identity index is incomplete; capture blocked"))
    return states, complete


def _identity_indexes(states, papers_dir, issues):
    uuid_index: dict[UUID, set[Path]] = defaultdict(set)
    doi_index: dict[tuple[str, str], set[Path]] = defaultdict(set)
    for state in states:
        if state.paper_id is not None:
            uuid_index[state.paper_id].add(state.path)
        for identifier in state.identifiers:
            doi_index[identifier].add(state.path)

    conflicted_paths: set[Path] = set()
    for label, index in (("external identity", doi_index), ("UUID", uuid_index)):
        for identifier, paths in index.items():
            if len(paths) > 1:
                conflicted_paths.update(paths)
                issues.append(MaterializationIssue(
                    papers_dir, f"duplicate durable {label} {identifier}: "
                    + ", ".join(str(path) for path in sorted(paths)),
                ))

    return uuid_index, doi_index, conflicted_paths


@dataclass(frozen=True)
class WorkspaceIdentityIndex:
    saved: dict[str, PaperIdentity]
    blocked: frozenset[str]
    complete: bool
    issues: tuple[MaterializationIssue, ...]

    by_identifier: dict[tuple[str, str], PaperIdentity] = field(default_factory=dict)
    blocked_identifiers: frozenset[tuple[str, str]] = frozenset()

    def can_create_paper(self, paper: CanonicalPaper) -> bool:
        keys = paper_identifiers(paper)
        return self.complete and bool(keys) and not any(
            key in self.by_identifier or key in self.blocked_identifiers for key in keys)

    def can_create(self, doi: str) -> bool:
        return self.complete and doi not in self.blocked and doi not in self.saved


def read_workspace_identities(lock: WorkspaceOperationLock) -> WorkspaceIdentityIndex:
    """Invocation-local identity only; final materialization still scans again."""
    lock.verify()
    papers_dir = lock.path / "Papers"
    issues: list[MaterializationIssue] = []
    if not papers_dir.exists() and not papers_dir.is_symlink():
        return WorkspaceIdentityIndex({}, frozenset(), True, ())
    try:
        with workspace_text_directory(lock, "Papers") as directory:
            states, complete = _scan_papers(papers_dir, issues)
            directory.verify()
            lock.verify()
    except (OSError, ContentChangedError, CompareReadError) as error:
        return WorkspaceIdentityIndex({}, frozenset(), False,
            (MaterializationIssue(papers_dir, str(error)),))
    _, _, conflicts = _identity_indexes(states, papers_dir, issues)
    saved, blocked, by_identifier, blocked_identifiers = {}, set(), {}, set()
    for state in states:
        if state.problems or state.path in conflicts:
            blocked.update(state.dois)
            blocked_identifiers.update(state.identifiers)
        elif complete:
            by_identifier.update({key: state for key in state.identifiers})
            for doi in state.dois:
                saved[doi] = state
    return WorkspaceIdentityIndex(saved, frozenset(blocked), complete, tuple(issues), by_identifier, frozenset(blocked_identifiers))


def _match_papers(
    papers: Sequence[CanonicalPaper],
    states: Sequence[PaperIdentity],
    papers_dir: Path,
    issues: list[MaterializationIssue],
) -> list[_PaperMatch]:
    uuid_index, doi_index, conflicted_paths = _identity_indexes(states, papers_dir, issues)
    states_by_path = {state.path: state for state in states}

    incoming_ids: dict[tuple[str, str], int] = defaultdict(int)
    incoming_uuids: dict[UUID, int] = defaultdict(int)
    for paper in papers:
        for identifier in paper_identifiers(paper):
            incoming_ids[identifier] += 1
        incoming_uuids[paper.id] += 1

    matches: list[_PaperMatch] = []
    for paper in papers:
        keys = paper_identifiers(paper)
        if not keys:
            _warning(issues, papers_dir, f"skipped incoming Paper {paper.id} without reliable identity")
            matches.append(_PaperMatch(None, blocked=True))
            continue
        if any(incoming_ids[key] > 1 for key in keys) or incoming_uuids[paper.id] > 1:
            issues.append(MaterializationIssue(papers_dir, f"ambiguous incoming identity/UUID for Paper {paper.id}"))
            matches.append(_PaperMatch(None, blocked=True))
            continue
        candidate_paths = set(uuid_index.get(paper.id, set()))
        for key in keys:
            candidate_paths.update(doi_index.get(key, set()))
        if len(candidate_paths) > 1:
            issues.append(MaterializationIssue(papers_dir, f"ambiguous identity for incoming Paper {paper.id}: "
                          + ", ".join(str(path) for path in sorted(candidate_paths))))
            matches.append(_PaperMatch(None, blocked=True))
            continue
        if candidate_paths:
            state = states_by_path[next(iter(candidate_paths))]
            if not keys.intersection(state.identifiers):
                issues.append(MaterializationIssue(state.path, "incoming identity conflicts with durable Paper UUID"))
                matches.append(_PaperMatch(state, blocked=True))
            elif state.problems or state.path in conflicted_paths:
                matches.append(_PaperMatch(state, blocked=True))
            else:
                matches.append(_PaperMatch(state))
        else:
            matches.append(_PaperMatch(None))

    paths_to_indexes: dict[Path, list[int]] = defaultdict(list)
    for index, match in enumerate(matches):
        if match.state is not None:
            paths_to_indexes[match.state.path].append(index)
    for path, indexes in paths_to_indexes.items():
        if len(indexes) < 2:
            continue
        issues.append(
            MaterializationIssue(
                path,
                "multiple incoming Papers match the same durable Paper",
            )
        )
        for index in indexes:
            matches[index] = _PaperMatch(matches[index].state, blocked=True)
    return matches


def _warning(
    issues: list[MaterializationIssue],
    path: Path,
    message: str,
) -> None:
    issues.append(
        MaterializationIssue(
            path=path,
            message=message,
            severity=MaterializationIssueSeverity.WARNING,
        )
    )


def materialize_papers(
    papers: Sequence[CanonicalPaper],
    output_dir: Path,
    *,
    progress_callback: ProgressCallback | None = None,
    operation_lock: WorkspaceOperationLock | None = None,
    cancel_event: Event | None = None,
) -> MaterializationResult:
    """Serialize capture-only materialization with other Workspace operations."""
    try:
        ownership = (nullcontext(operation_lock) if operation_lock is not None
                     else workspace_operation_lock(output_dir, create=True))
        with ownership as lock, ExitStack() as stack:
            lock.verify()
            if lock.path != output_dir.absolute():
                raise ContentChangedError("Materialization lock targets another Workspace")
            directories = {}
            issues = []
            for name in ("Papers",):
                try:
                    directories[name] = stack.enter_context(workspace_text_directory(lock, name))
                except (OSError, ContentChangedError, CompareReadError) as error:
                    issues.append(MaterializationIssue(lock.path / name, str(error)))
            return _materialize_papers(papers, lock, directories, issues, progress_callback=progress_callback, cancel_event=cancel_event)
    except (ContentChangedError, CompareReadError, OSError) as error:
        return MaterializationResult((), (), (MaterializationIssue(output_dir, str(error)),))


def _materialize_papers(
    papers: Sequence[CanonicalPaper],
    lock: WorkspaceOperationLock,
    directories: dict[str, WorkspaceTextDirectory],
    issues: list[MaterializationIssue],
    *,
    progress_callback: ProgressCallback | None = None,
    cancel_event: Event | None = None,
) -> MaterializationResult:
    """Create new Paper notes; never rewrite saved notes."""

    output_dir = lock.path
    read_activity = ActivityUpdate(
        kind=ActivityKind.WORKING,
        source="workspace",
        operation="materialize_read",
        label="Reading workspace",
    )
    _report_activity(progress_callback, read_activity)
    papers_dir = output_dir / "Papers"
    try:
        lock.verify()
        for directory in directories.values():
            directory.verify()
    except (OSError, ContentChangedError, CompareReadError) as error:
        return MaterializationResult((), (), tuple(issues) + (MaterializationIssue(output_dir, str(error)),))
    papers_directory_issue = "Papers" not in directories

    states, identity_index_complete = (
        _scan_papers(papers_dir, issues)
        if not papers_directory_issue
        else ([], False)
    )
    matches = _match_papers(
        papers,
        states,
        papers_dir,
        issues,
    )
    _report_activity(
        progress_callback,
        replace(
            read_activity,
            label="Completed workspace read",
            detail=f"{len(states)} papers",
        ),
    )
    collision_ids = {
        state.paper_id for state in states if state.paper_id is not None
    }
    collision_ids.update(paper.id for paper in papers)

    created_papers: list[Path] = []
    existing_papers: list[Path] = []
    handled_new_paths: set[Path] = set()
    pending_paper_writes: list[_PaperWrite] = []

    preparation_activity = ActivityUpdate(
        kind=ActivityKind.WORKING,
        source="workspace",
        operation="materialize_prepare",
        label="Preparing new papers",
        current=0,
        total=len(papers),
        unit="paper",
    )
    _report_activity(progress_callback, preparation_activity)

    for paper_index, (paper, match) in enumerate(
        zip(papers, matches, strict=True)
    ):
        completed = True
        try:
            state = match.state
            if match.blocked or not identity_index_complete:
                continue
            if state is not None:
                if state.path not in existing_papers:
                    existing_papers.append(state.path)
                continue

            if papers_directory_issue:
                continue
            target = papers_dir / paper_filename(
                paper.metadata.title,
                paper.id,
                collision_ids,
            )
            if target in handled_new_paths:
                issues.append(
                    MaterializationIssue(
                        target,
                        "multiple incoming Papers resolve to the same new target",
                    )
                )
                continue
            handled_new_paths.add(target)
            if target.exists():
                if target.is_file():
                    issues.append(
                        MaterializationIssue(
                            target,
                            "occupied Paper path has no safe identity match",
                        )
                    )
                else:
                    if not any(issue.path == target for issue in issues):
                        issues.append(
                            MaterializationIssue(
                                target,
                                "Paper target exists but is not a regular file",
                            )
                        )
                continue
            try:
                contents = render_paper_markdown(paper)
            except Exception as error:
                issues.append(MaterializationIssue(target, str(error)))
                continue
            pending_paper_writes.append(_PaperWrite(target, contents))

        except BaseException:
            completed = False
            raise
        finally:
            if completed:
                # 已隔离的 blocked/no-op/error 分支也完成了这个 incoming Paper work unit。
                _report_activity(
                    progress_callback,
                    replace(
                        preparation_activity,
                        detail=paper.metadata.title,
                        current=paper_index + 1,
                    ),
                )

    write_activity = ActivityUpdate(
        kind=ActivityKind.WORKING,
        source="workspace",
        operation="materialize_write",
        label="Writing new papers",
        current=0,
        total=len(pending_paper_writes),
        unit="file",
    )
    _report_activity(progress_callback, write_activity)

    for write_index, pending in enumerate(pending_paper_writes):
        if cancel_event is not None and cancel_event.is_set():
            issues.append(MaterializationIssue(output_dir, "Run cancelled"))
            break
        completed = True
        try:
            outcome, error = _create_file(pending.path, pending.contents, directories["Papers"])
            if error is not None and outcome == "created":
                issues.append(MaterializationIssue(pending.path, error))
            if outcome == "created":
                created_papers.append(pending.path)
            elif outcome == "existing":
                issues.append(
                    MaterializationIssue(
                        pending.path,
                        "Paper path became occupied without a safe identity match",
                    )
                )
            else:
                issues.append(
                    MaterializationIssue(pending.path, error or "write failed")
                )

        except BaseException:
            completed = False
            raise
        finally:
            if completed:
                # write conflict 或 I/O failure 仍表示这一 pending write attempt 已处理完成。
                _report_activity(
                    progress_callback,
                    replace(
                        write_activity,
                        detail=pending.path.name,
                        current=write_index + 1,
                    ),
                )

    if not papers_directory_issue and not (cancel_event is not None and cancel_event.is_set()):
        inbox_path = output_dir / "Inbox.base"
        _outcome, error = _create_file(
            inbox_path,
            render_default_inbox_base(),
            WorkspaceTextDirectory(lock, lock.directory, lock.identity),
        )
        if error is not None:
            issues.append(MaterializationIssue(inbox_path, error))

    try:
        lock.verify()
        for directory in directories.values():
            directory.verify()
    except (OSError, ContentChangedError, CompareReadError) as error:
        issues.append(MaterializationIssue(output_dir, str(error)))
    return MaterializationResult(
        created_papers=tuple(created_papers),
        existing_papers=tuple(existing_papers),
        issues=tuple(issues),
    )
