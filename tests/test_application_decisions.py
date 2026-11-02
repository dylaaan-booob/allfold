from __future__ import annotations

import inspect
import os
import stat
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
import httpx
import yaml

import allfold.application.decisions as decisions
import allfold.persistence.safe_write as safe_write_module
from allfold.application.decisions import (
    DecisionOutcome,
    keep_paper,
    reject_paper,
)
from allfold.persistence.markdown_state import parse_paper_state
from allfold.persistence.materialize import render_paper_markdown
from allfold.models import (
    Author,
    CanonicalMetadata,
    CanonicalPaper,
    ExternalIds,
    MetadataSource,
    Workflow,
    WorkflowStatus,
)
from allfold.persistence.safe_write import ContentChangedError
from allfold.integrations.zotero_local import LOCAL_API_BASE, ZoteroLocalClient


NOW = datetime(2026, 9, 22, 10, 0, tzinfo=timezone.utc)


def write_paper(
    output_dir: Path,
    paper_id: UUID,
    *,
    filename: str = "paper.md",
    status: WorkflowStatus = WorkflowStatus.CANDIDATE,
    title: str = "Decision Paper",
) -> Path:
    paper = CanonicalPaper(
        id=paper_id,
        metadata=CanonicalMetadata(
            title=title,
            journal="Biometrics",
            publication_date=date(2026, 9, 20),
            abstract="Decision abstract.",
            author_keywords=("statistics", "decisions"),
        ),
        external_ids=ExternalIds.model_validate(
            {
                "doi": "10.5555/decision",
                "openalex": "https://openalex.org/W-DECISION",
                "pmid": "12345678",
            }
        ),
        authors=(Author(name="Ada Author"),),
        sources=(
            MetadataSource(
                provider="openalex",
                record_id="https://openalex.org/W-DECISION",
                retrieved_at=NOW,
            ),
        ),
        workflow=Workflow(
            status=status,
            discovered_at=NOW,
        ),
    )
    path = output_dir / "Papers" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_paper_markdown(paper),
        encoding="utf-8",
    )
    return path


def document_parts(path: Path) -> tuple[dict[str, object], str]:
    opening, payload, body = path.read_text(encoding="utf-8").split("---", maxsplit=2)
    assert opening == ""
    values = yaml.safe_load(payload)
    assert isinstance(values, dict)
    return values, body


def replace_frontmatter(path: Path, **updates: object) -> None:
    values, body = document_parts(path)
    values.update(updates)
    rendered = yaml.safe_dump(values, sort_keys=False, allow_unicode=True).rstrip()
    path.write_text(f"---\n{rendered}\n---{body}", encoding="utf-8")


def test_status_only_mutation_preserves_unknown_frontmatter_and_complete_human_body(
    tmp_path: Path,
) -> None:
    paper_id = UUID("22222222-2222-4222-8222-222222222222")
    path = write_paper(
        tmp_path,
        paper_id,
        status=WorkflowStatus.CANDIDATE,

    )
    values, body = document_parts(path)
    values["custom_field"] = {"nested": ["retain", 3]}
    body = (
        body
        + "\nFree-form prose.\n"
        + "\n## Notes\n\nHuman note.\n\n"
        + "### Note child\n\nKeep child.\n\n"
        + "## Custom Section\n\n~~~text\nstatus: not workflow\n~~~\n"
    )
    rendered = yaml.safe_dump(values, sort_keys=False, allow_unicode=True).rstrip()
    path.write_text(f"---\n{rendered}\n---{body}", encoding="utf-8")
    before_frontmatter, before_body = document_parts(path)

    result = keep_paper(tmp_path, paper_id, WorkflowStatus.CANDIDATE)

    after_frontmatter, after_body = document_parts(path)
    assert result.outcome is DecisionOutcome.UPDATED
    assert after_frontmatter["status"] == "kept"
    assert after_frontmatter["custom_field"] == {"nested": ["retain", 3]}
    assert "versions" not in after_frontmatter and "preferred_version" not in after_frontmatter
    assert after_frontmatter["sources"] == before_frontmatter["sources"]
    assert after_frontmatter["title"] == before_frontmatter["title"]
    assert after_frontmatter["journal"] == before_frontmatter["journal"]
    assert after_frontmatter["discovered_at"] == before_frontmatter["discovered_at"]
    assert "zotero_key" not in after_frontmatter
    before_frontmatter.pop("status")
    after_frontmatter.pop("status")
    assert after_frontmatter == before_frontmatter
    assert after_body == before_body


def test_duplicate_uuid_is_invalid_and_mutates_neither_file(tmp_path: Path) -> None:
    paper_id = UUID("44444444-4444-4444-8444-444444444444")
    first = write_paper(tmp_path, paper_id, filename="one.md")
    second = tmp_path / "Papers" / "two.md"
    second.write_bytes(first.read_bytes())
    before = {first: first.read_bytes(), second: second.read_bytes()}

    result = reject_paper(tmp_path, paper_id, WorkflowStatus.CANDIDATE)

    assert result.outcome is DecisionOutcome.INVALID_PAPER
    assert "multiple locations" in result.message
    assert {path: path.read_bytes() for path in before} == before


def test_symlink_candidate_for_requested_uuid_is_rejected_without_mutating_target(
    tmp_path: Path,
) -> None:
    paper_id = UUID("66666666-6666-4666-8666-666666666666")
    outside = write_paper(tmp_path / "outside", paper_id)
    papers_dir = tmp_path / "workspace" / "Papers"
    papers_dir.mkdir(parents=True)
    link = papers_dir / "linked.md"
    link.symlink_to(outside)
    before = outside.read_bytes()

    result = keep_paper(
        tmp_path / "workspace",
        paper_id,
        WorkflowStatus.CANDIDATE,
    )

    assert result.outcome is DecisionOutcome.INVALID_PAPER
    assert result.path == link
    assert "symlink" in result.message
    assert outside.read_bytes() == before


@pytest.mark.parametrize(('disk_status', 'expected_status', 'action'), ((WorkflowStatus.KEPT, WorkflowStatus.CANDIDATE, keep_paper),))
def test_expected_status_mismatch_is_state_conflict(
    disk_status: WorkflowStatus,
    expected_status: WorkflowStatus,
    action: object,
    tmp_path: Path,
) -> None:
    paper_id = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    path = write_paper(tmp_path, paper_id, status=disk_status)
    before = path.read_bytes()

    result = action(tmp_path, paper_id, expected_status)  # type: ignore[operator]

    assert result.outcome is DecisionOutcome.STATE_CONFLICT
    assert result.current_status is disk_status
    assert path.read_bytes() == before


def test_compare_before_replace_race_keeps_external_edit_and_reports_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd")
    path = write_paper(tmp_path, paper_id)

    def concurrent_edit(
        target: Path,
        contents: str,
        *,
        expected_contents: str,
        **identity,
    ) -> None:
        assert target == path
        assert expected_contents == path.read_text(encoding="utf-8")
        external = expected_contents + "\nExternal edit remains.\n"
        path.write_text(external, encoding="utf-8")
        raise ContentChangedError("target changed after it was read")

    monkeypatch.setattr(
        decisions,
        "_replace_regular_text_at_identity",
        concurrent_edit,
    )

    result = keep_paper(tmp_path, paper_id, WorkflowStatus.CANDIDATE)

    contents = path.read_text(encoding="utf-8")
    assert result.outcome is DecisionOutcome.STATE_CONFLICT
    assert "External edit remains." in contents
    assert document_parts(path)[0]["status"] == "candidate"


def test_atomic_replace_failure_is_io_failure_and_preserves_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paper_id = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    path = write_paper(tmp_path, paper_id)
    before = path.read_bytes()

    def fail_replace(source: object, destination: object, **kwargs) -> None:
        raise OSError("replace denied")

    monkeypatch.setattr(safe_write_module.os, "replace", fail_replace)

    result = keep_paper(tmp_path, paper_id, WorkflowStatus.CANDIDATE)

    assert result.outcome is DecisionOutcome.IO_FAILURE
    assert "replace denied" in result.message
    assert path.read_bytes() == before
    assert tuple(path.parent.glob(f".{path.name}.*.tmp")) == ()


