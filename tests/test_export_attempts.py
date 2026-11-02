"""Transient Import identity tests; old persistent Import tests remain in Git history."""
from __future__ import annotations

import pytest

from allfold.application.export_attempts import (
    ExportAttemptError, reserve_export_attempt, validate_export_reservation,
)
from allfold.persistence.safe_write import ContentChangedError, workspace_operation_lock
from electron_test_helpers import paper, state, edit


def test_transient_reservation_never_changes_source(tmp_path):
    value, path = paper(tmp_path, "a")
    original = path.read_bytes()
    first = reserve_export_attempt(tmp_path, value.id)
    second = reserve_export_attempt(tmp_path, value.id)
    assert first.attempt.attempt_id != second.attempt.attempt_id
    assert path.read_bytes() == original
    assert not state(path).export_attempt_present
    validate_export_reservation(first)
    validate_export_reservation(second)


@pytest.mark.parametrize("change", ["body", "status", "doi", "inode", "path"])
def test_frozen_identity_and_revision_reject_changed_paper(tmp_path, change):
    value, path = paper(tmp_path, "a")
    reservation = reserve_export_attempt(tmp_path, value.id)
    if change == "body":
        path.write_text(path.read_text() + "\nHuman edit")
    elif change == "status":
        edit(path, status="rejected")
    elif change == "doi":
        edit(path, external_ids={"doi": "10.5555/changed"})
    elif change == "inode":
        moved = path.with_suffix(".old")
        path.rename(moved)
        path.write_bytes(moved.read_bytes())
    else:
        path.rename(path.with_name("renamed.md"))
    with pytest.raises((ExportAttemptError, ContentChangedError, OSError)):
        validate_export_reservation(reservation)


def test_cross_process_slot_is_excluded_by_existing_flock(tmp_path):
    value, path = paper(tmp_path, "a")
    with workspace_operation_lock(tmp_path):
        # Production batch owns the same POSIX flock. A second coordinator or
        # different process cannot independently start a save for this Workspace.
        with pytest.raises(ContentChangedError):
            reserve_export_attempt(tmp_path, value.id)
