"""Real SQLite failure, path and transaction boundaries for the independent library."""

import os
import sqlite3
import time

import pytest

from allfold.models import ExternalIds
from allfold.persistence.library_database import (
    DATABASE_NAME, SCHEMA_VERSION, LibraryBusyError, LibraryCorruptError, LibraryError,
    LibraryExistsError, LibraryMissingError, UnsafeLibraryPath, UnsupportedLibrarySchema,
)
from allfold.persistence.paper_repository import BodyReference, MetadataDelta, PaperMetadata, PaperRepository


def test_missing_and_explicit_creation_never_touch_other_state(tmp_path):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    user_state = tmp_path / ".allfold" / "user-data.sqlite"
    user_state.parent.mkdir()
    user_state.write_bytes(b"untouched user state")
    config = tmp_path / "config.yaml"
    config.write_text("original configuration")
    with pytest.raises(LibraryMissingError):
        PaperRepository.open(workspace)
    assert list(workspace.iterdir()) == []
    with PaperRepository.create(workspace) as library:
        workspace_id = library.workspace_id
        with pytest.raises(LibraryExistsError):
            PaperRepository.create(workspace)
    with PaperRepository.open(workspace) as reopened:
        assert reopened.workspace_id == workspace_id
    assert user_state.read_bytes() == b"untouched user state"
    assert config.read_text() == "original configuration"


@pytest.mark.parametrize("contents", [b"not a database", b"", b"SQLite format 3\x00truncated"])
def test_corrupt_or_uninitialized_library_is_never_replaced(tmp_path, contents):
    path = tmp_path / DATABASE_NAME
    path.write_bytes(contents)
    with pytest.raises(LibraryCorruptError):
        PaperRepository.open(tmp_path)
    with pytest.raises(LibraryExistsError):
        PaperRepository.create(tmp_path)
    assert path.read_bytes() == contents


@pytest.mark.parametrize("version", [0, SCHEMA_VERSION + 1])
def test_unknown_schema_is_refused_without_modification(tmp_path, version):
    with PaperRepository.create(tmp_path):
        pass
    path = tmp_path / DATABASE_NAME
    with sqlite3.connect(path) as connection:
        connection.execute(f"PRAGMA user_version = {version}")
    before = path.read_bytes()
    with pytest.raises(UnsupportedLibrarySchema):
        PaperRepository.open(tmp_path)
    assert path.read_bytes() == before


def test_incomplete_known_schema_is_rejected_at_open(tmp_path):
    with PaperRepository.create(tmp_path):
        pass
    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        connection.execute("DROP TABLE paper_metadata")
    before = (tmp_path / DATABASE_NAME).read_bytes()
    with pytest.raises(LibraryCorruptError):
        PaperRepository.open(tmp_path)
    assert (tmp_path / DATABASE_NAME).read_bytes() == before


@pytest.mark.parametrize("operation", ["open", "create"])
@pytest.mark.parametrize("kind", ["symlink", "hardlink", "directory", "fifo"])
@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_unsafe_main_and_sidecar_rejected_before_connect(tmp_path, operation, kind, suffix, monkeypatch):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    with PaperRepository.create(workspace):
        pass
    path = workspace / DATABASE_NAME
    candidate = path.with_name(path.name + suffix)
    if not suffix:
        path.unlink()
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain untouched")
    if kind == "symlink":
        candidate.symlink_to(outside)
    elif kind == "hardlink":
        os.link(outside, candidate)
    elif kind == "directory":
        candidate.mkdir()
    else:
        os.mkfifo(candidate)

    # A pre-connection rejection must not invoke SQLite, even for recovery.
    def forbidden_connection(*args, **kwargs):
        pytest.fail("SQLite connected before rejecting an unsafe path")

    monkeypatch.setattr(sqlite3, "connect", forbidden_connection)
    with pytest.raises(UnsafeLibraryPath):
        getattr(PaperRepository, operation)(workspace)
    assert outside.read_bytes() == b"must remain untouched"


@pytest.mark.parametrize("operation", ["open", "create"])
def test_parent_symlink_and_traversal_are_rejected(tmp_path, operation):
    workspace = tmp_path / "Workspace"
    workspace.mkdir()
    (tmp_path / "alias").symlink_to(workspace, target_is_directory=True)
    with pytest.raises(UnsafeLibraryPath):
        getattr(PaperRepository, operation)(tmp_path / "alias")
    with pytest.raises(UnsafeLibraryPath):
        getattr(PaperRepository, operation)(workspace / ".." / "Workspace")
    assert list(workspace.iterdir()) == []


def test_creation_refuses_orphan_sidecars_without_consuming_them(tmp_path):
    journal = tmp_path / (DATABASE_NAME + "-journal")
    journal.write_bytes(b"orphaned journal")
    with pytest.raises(LibraryExistsError):
        PaperRepository.create(tmp_path)
    assert not (tmp_path / DATABASE_NAME).exists()
    assert journal.read_bytes() == b"orphaned journal"


@pytest.mark.parametrize("relative_path", [
    "/Documents/file.pdf", "../file.pdf", "Documents/../file.pdf", "Documents/./file.pdf",
    "Documents//file.pdf", "Documents/", "Documents", "file.pdf", "C:/Documents/file.pdf",
    "Documents/C:/file.pdf", "Documents\\file.pdf", "Documents/a\x00.pdf", "Documents/a\n.pdf",
])
def test_invalid_body_reference_does_not_write_or_touch_files(tmp_path, relative_path):
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"existing PDF")
    with PaperRepository.create(tmp_path) as library:
        paper = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                        metadata=PaperMetadata(title="Article")).paper
        with pytest.raises(ValueError):
            library.complete_body(paper.token, {"relative_path": relative_path})
        assert library.get(paper.id) == paper
    assert outside.read_bytes() == b"existing PDF"


def test_sql_failure_rolls_back_new_core_identities_and_field_changes(tmp_path):
    path = tmp_path / DATABASE_NAME
    with PaperRepository.create(tmp_path) as library:
        paper = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                        metadata=PaperMetadata(title="Article")).paper
        with sqlite3.connect(path) as injector:
            injector.execute("""CREATE TRIGGER fail_new_metadata BEFORE INSERT ON paper_metadata
                BEGIN SELECT RAISE(ABORT, 'injected insert failure'); END""")
            injector.execute("""CREATE TRIGGER fail_changed_metadata BEFORE UPDATE ON paper_metadata
                BEGIN SELECT RAISE(ABORT, 'injected update failure'); END""")
        with pytest.raises(LibraryError, match="injected insert failure"):
            library.create_or_match(library.workspace_id, direct_ids=ExternalIds(wos="WOS:456"),
                                    metadata=PaperMetadata(title="Must roll back"))
        with pytest.raises(LibraryError, match="injected update failure"):
            library.merge_metadata(paper.token, MetadataDelta(abstract="Must roll back"),
                                   direct_ids=ExternalIds(pmcid="PMC789"))
        assert library.list_papers() == (paper,)
        assert library.match(ExternalIds(wos="WOS:456")) is None
        assert library.match(ExternalIds(pmcid="PMC789")) is None
        with sqlite3.connect(path) as injector:
            injector.execute("DROP TRIGGER fail_new_metadata")
            injector.execute("DROP TRIGGER fail_changed_metadata")
    with PaperRepository.open(tmp_path) as reopened:
        assert reopened.get(paper.id) == paper
        assert reopened.merge_metadata(paper.token, MetadataDelta(abstract="After rollback")).metadata.abstract == "After rollback"


def test_schema_enforces_identity_uniqueness_and_foreign_keys(tmp_path):
    with PaperRepository.create(tmp_path) as library:
        first = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                        metadata=PaperMetadata(title="First")).paper
        second = library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="456"),
                                         metadata=PaperMetadata(title="Second")).paper
        with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO paper_identities VALUES ('pmid', '123', ?)", (str(second.id),))
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("INSERT INTO paper_identities VALUES ('pmid', '789', 'missing')")
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("DELETE FROM paper_core WHERE paper_id = ?", (str(first.id),))
        assert len(library.list_papers()) == 2


def test_busy_wait_is_bounded_and_connection_remains_usable(tmp_path):
    with PaperRepository.create(tmp_path, timeout=0.05) as library:
        with sqlite3.connect(tmp_path / DATABASE_NAME) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            started = time.monotonic()
            with pytest.raises(LibraryBusyError):
                library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                        metadata=PaperMetadata(title="Wait is bounded"))
            assert time.monotonic() - started < 2
            blocker.rollback()
        assert library.list_papers() == ()
        assert library.create_or_match(library.workspace_id, direct_ids=ExternalIds(pmid="123"),
                                       metadata=PaperMetadata(title="After busy")).created
    with pytest.raises(LibraryError, match="closed"):
        library.list_papers()
    library.close()
    with PaperRepository.open(tmp_path) as reopened:
        assert len(reopened.list_papers()) == 1


def test_replaced_open_database_is_rejected(tmp_path):
    with PaperRepository.create(tmp_path) as library:
        path = tmp_path / DATABASE_NAME
        path.rename(tmp_path / "original.sqlite")
        path.write_bytes(b"replacement")
        with pytest.raises(UnsafeLibraryPath):
            library.list_papers()
        assert path.read_bytes() == b"replacement"


def test_known_v1_upgrade_preserves_library_and_metadata_without_inventing_discovery(tmp_path):
    from uuid import uuid4
    from allfold.persistence.library_database import APPLICATION_ID, V1_SCHEMA

    workspace_id, paper_id = uuid4(), uuid4()
    original = PaperMetadata(title='Existing v1 title', notes='Existing notes').model_dump_json(exclude={'discovered_at'})
    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        for statement in V1_SCHEMA:
            connection.execute(statement)
        connection.execute('INSERT INTO library_info VALUES (1, ?)', (str(workspace_id),))
        connection.execute('INSERT INTO paper_core (paper_id, excluded) VALUES (?, 1)', (str(paper_id),))
        connection.execute('INSERT INTO paper_identities VALUES (?, ?, ?)', ('doi', '10.1234/main', str(paper_id)))
        connection.execute('INSERT INTO paper_metadata (paper_id, payload) VALUES (?, ?)', (str(paper_id), original))
        connection.execute('INSERT INTO paper_body VALUES (?, ?, NULL, NULL)', (str(paper_id), 'Documents/existing.pdf'))
        connection.execute(f'PRAGMA application_id = {APPLICATION_ID}')
        connection.execute('PRAGMA user_version = 1')
    with PaperRepository.open(tmp_path, expected_workspace_id=workspace_id) as repository:
        paper = repository.get(paper_id)
        assert paper.excluded and paper.metadata.notes == 'Existing notes'
        assert paper.metadata.discovered_at is None
        assert paper.primary_identity.value == '10.1234/main'
        assert paper.body.relative_path == 'Documents/existing.pdf'
    with PaperRepository.open(tmp_path) as reopened:
        assert reopened.get(paper_id) == paper


def test_invalid_v1_payload_fails_upgrade_without_partial_schema(tmp_path):
    from uuid import uuid4
    from allfold.persistence.library_database import APPLICATION_ID, V1_SCHEMA

    paper_id = str(uuid4())
    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        for statement in V1_SCHEMA:
            connection.execute(statement)
        connection.execute('INSERT INTO library_info VALUES (1, ?)', (str(uuid4()),))
        connection.execute('INSERT INTO paper_core (paper_id) VALUES (?)', (paper_id,))
        connection.execute('INSERT INTO paper_metadata (paper_id, payload) VALUES (?, ?)', (paper_id, '{"title":""}'))
        connection.execute(f'PRAGMA application_id = {APPLICATION_ID}')
        connection.execute('PRAGMA user_version = 1')
    before = (tmp_path / DATABASE_NAME).read_bytes()
    with pytest.raises(LibraryCorruptError):
        PaperRepository.open(tmp_path)
    assert (tmp_path / DATABASE_NAME).read_bytes() == before
