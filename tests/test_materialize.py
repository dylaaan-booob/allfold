from __future__ import annotations

from datetime import date, datetime, timezone
import os
from pathlib import Path
from uuid import UUID

import pytest
import yaml

import allfold.persistence.materialize as materialize_module
from allfold.persistence.inbox import render_default_inbox_base
from allfold.persistence.markdown_state import (
    PaperJournalAttributionState,
    parse_paper_state,
    serialize_document,
)
from allfold.persistence.materialize import (
    MISSING_ABSTRACT,
    MaterializationIssue,
    MaterializationIssueSeverity,
    MaterializationResult,
    materialize_papers,
    render_paper_markdown,
)
from allfold.models import (
    Author,
    CanonicalMetadata,
    CanonicalPaper,
    ExternalIds,
    MetadataSource,
    Workflow,
    WorkflowStatus,
)
from allfold.persistence.naming import paper_filename
from allfold.progress import ProgressEvent


@pytest.mark.parametrize("replacement", ["directory", "symlink", "lock", "papers"])
@pytest.mark.parametrize("phase", ["initial", "write", "after_first_write"])
def test_materialization_rejects_identity_substitution(tmp_path, replacement, phase):
    root = tmp_path / "output"
    root.mkdir()
    root.joinpath("Papers").mkdir()
    sources = tuple(
        paper(str(UUID(int=index + 1)), title=f"Paper {index}").model_copy(
            update={"external_ids": ExternalIds(doi=f"10.5555/race-{index}")}
        ) for index in range(2)
    )
    moved = tmp_path / "preserved"
    injected = False

    def substitute(event):
        nonlocal injected
        activity = event.activity
        if injected or activity is None:
            return
        trigger = (
            phase == "initial" and activity.operation == "materialize_read"
            and activity.label == "Reading workspace"
        ) or (
            phase == "write" and activity.operation == "materialize_write" and activity.current == 0
        ) or (
            phase == "after_first_write" and activity.operation == "materialize_write" and activity.current == 1
        )
        if not trigger:
            return
        injected = True
        if replacement in {"directory", "symlink"}:
            root.rename(moved)
            if replacement == "directory":
                root.mkdir()
            else:
                root.symlink_to(moved, target_is_directory=True)
        elif replacement == "papers":
            root.joinpath("Papers").rename(moved)
            root.joinpath("Papers").mkdir()
        else:
            lock = root / ".allfold-operation.lock"
            lock.rename(tmp_path / "old-lock")
            lock.touch()

    result = materialize_papers(sources, root, progress_callback=substitute)
    assert injected
    assert result.has_errors
    expected = 1 if phase == "after_first_write" else 0
    assert len(result.created_papers) == expected
    original_papers = moved / "Papers" if replacement in {"directory", "symlink"} else (
        moved if replacement == "papers" else root / "Papers"
    )
    assert len(list(original_papers.glob("*.md"))) == expected
    if replacement == "directory":
        assert not list(root.rglob("*.md"))
    elif replacement == "papers":
        assert not list(root.joinpath("Papers").glob("*.md"))


NOW = datetime(2026, 9, 18, 8, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize("status", list(WorkflowStatus))
def test_capture_only_preserves_saved_paper_and_author_names(tmp_path, status):
    source = paper(str(UUID(int=7001)), authors=(Author(name="Ada", openalex_id="A9"),))
    first = materialize_papers((source,), tmp_path)
    target = first.created_papers[0]
    target.write_bytes(target.read_bytes().replace(b"status: candidate", f"status: {status.value}".encode())
                       + b"\n## Human section\n\nKeep this.\n")
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    inbox = (tmp_path / "Inbox.base").read_bytes()
    incoming = source.model_copy(update={
        "id": UUID(int=7002),
        "metadata": source.metadata.model_copy(update={"title": "Changed title", "abstract": "New abstract"}),
        "authors": (Author(name="New author", openalex_id="A99"),),
        "external_ids": ExternalIds(doi="https://doi.org/10.5555/EXAMPLE", openalex="W999"),
        "sources": (MetadataSource(provider="crossref", record_id="new", retrieved_at=NOW),),
        "journal_issns": ("0006-341X",),
    })

    result = materialize_papers((incoming,), tmp_path)

    assert result.existing_papers == (target,)
    assert not result.issues and not result.created_papers
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before
    assert (tmp_path / "Inbox.base").read_bytes() == inbox


def test_concurrent_path_occupation_never_overwrites_or_claims_saved(tmp_path, monkeypatch):
    source = paper(str(UUID(int=7015)), authors=(Author(name="Ada", openalex_id="A15"),))
    real_create = materialize_module.WorkspaceTextDirectory.create
    occupied = []

    def create(directory, name, contents):
        if not occupied and directory.name == "Papers":
            path = directory.path / name
            text = "occupied by another actor\n"
            path.write_text(text)
            occupied.append((path, text))
        return real_create(directory, name, contents)

    monkeypatch.setattr(materialize_module.WorkspaceTextDirectory, "create", create)
    result = materialize_papers((source,), tmp_path)
    assert result.has_errors and not result.created_papers and not result.existing_papers
    assert occupied and occupied[0][0].read_text() == occupied[0][1]


def test_saved_capture_never_calls_replace_and_preserves_concurrent_human_edit(tmp_path, monkeypatch):
    source = paper(str(UUID(int=7016)))
    first = materialize_papers((source,), tmp_path)
    path = first.created_papers[0]
    before = path.read_bytes()
    edited = before + b"\n## Versions\n\nHuman discussion.\n"

    def fail_replace(*args, **kwargs):
        raise AssertionError("Capture must not replace an existing note")

    def progress(event):
        if event.activity and event.activity.label == "Completed workspace read":
            path.write_bytes(edited)

    monkeypatch.setattr(materialize_module.WorkspaceTextDirectory, "replace", fail_replace)
    incoming = source.model_copy(update={"metadata": source.metadata.model_copy(update={"title": "Changed"})})
    result = materialize_papers((incoming,), tmp_path, progress_callback=progress)
    assert not result.issues and result.existing_papers == (path,)
    assert path.read_bytes() == edited


def paper(
    identifier: str,
    *,
    title: str = "A Materialized Paper",
    authors: tuple[Author, ...] = (Author(name="Ada Author"),),
    abstract: str | None = "Complete abstract with every original detail.",
) -> CanonicalPaper:
    return CanonicalPaper(
        id=UUID(identifier),
        metadata=CanonicalMetadata(
            title=title,
            journal="Biometrics",
            publication_date=date(2026, 9, 17),
            abstract=abstract,
            author_keywords=("statistics", "multiview"),
        ),
        external_ids=ExternalIds.model_validate(
            {
                "openalex": "https://openalex.org/W123",
                "doi": "10.5555/example",
                "arxiv": "2609.01234",
                "crossref": "10.5555/example",
                "pmid": "12345678",
            }
        ),
        authors=authors,
        sources=(
            MetadataSource(
                provider="openalex",
                record_id="https://openalex.org/W123",
                retrieved_at=NOW,
            ),
        ),
        workflow=Workflow(
            status=WorkflowStatus.CANDIDATE,
            discovered_at=NOW,
        ),
    )


def author_paper(
    identifier: str,
    *,
    title: str,
    publication_date: date | None,
    external_doi: str | None = None,
    author: Author = Author(name="Ada Author"),
    shared_record_id: str = "shared-work",
) -> CanonicalPaper:
    return CanonicalPaper(
        id=UUID(identifier),
        metadata=CanonicalMetadata(
            title=title,
            journal="Biometrics",
            publication_date=publication_date,
            abstract=f"{title} abstract",
            author_keywords=(title.casefold(),),
        ),
        external_ids=ExternalIds(doi=external_doi or "10.5555/author"),
        authors=(author,),
        sources=(
            MetadataSource(
                provider="openalex",
                record_id=shared_record_id,
                retrieved_at=NOW,
            ),
        ),
        workflow=Workflow(discovered_at=NOW),
    )


def frontmatter(contents: str) -> dict[str, object]:
    opening, payload, _body = contents.split("---", maxsplit=2)
    assert opening == ""
    parsed = yaml.safe_load(payload)
    assert isinstance(parsed, dict)
    return parsed


def with_journal_attribution(contents: str, yaml_value: str | None) -> str:
    if yaml_value is None:
        return contents
    return contents.replace("type: paper\n", f"type: paper\njournal_issns: {yaml_value}\n", 1)


@pytest.mark.parametrize("mode", ["duplicate_doi", "uuid_doi_split", "uuid_retarget"])
def test_durable_doi_and_uuid_conflicts_fail_closed(tmp_path, mode):
    initial = paper("42345678-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    first = materialize_papers((initial,), tmp_path)
    path, = first.created_papers
    if mode != "uuid_retarget":
        other = initial.model_copy(update={"id": UUID(int=903), "external_ids": ExternalIds(
            doi="10.5555/example" if mode == "duplicate_doi" else "10.5555/other")})
        other_path = tmp_path / "Papers" / "other.md"
        other_path.write_text(render_paper_markdown(other))
    incoming = initial.model_copy(update={
        "id": UUID(int=904) if mode == "duplicate_doi" else initial.id,
        "external_ids": ExternalIds(doi="10.5555/example" if mode == "duplicate_doi" else "10.5555/other"),
        "authors": (Author(name="Unrelated Author"),),
    })
    before = {p: p.read_bytes() for p in tmp_path.rglob("*.md")}
    result = materialize_papers((incoming,), tmp_path)
    assert result.has_errors and not result.created_papers
    assert {p: p.read_bytes() for p in tmp_path.rglob("*.md")} == before


