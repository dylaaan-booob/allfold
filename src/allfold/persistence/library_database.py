"""Bounded SQLite connections and versioned schema for a Workspace Paper library."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import sqlite3
import stat
from uuid import UUID, uuid4


DATABASE_NAME = "papers.sqlite"
SCHEMA_VERSION = 1
APPLICATION_ID = 0x41464C44  # AFLD; unrelated to configuration-level UserState.


class LibraryError(Exception):
    """A library operation failed without a fallback store or destructive repair."""


class LibraryMissingError(LibraryError):
    pass


class LibraryExistsError(LibraryError):
    pass


class UnsafeLibraryPath(LibraryError):
    pass


class LibraryCorruptError(LibraryError):
    pass


class UnsupportedLibrarySchema(LibraryError):
    pass


class LibraryBusyError(LibraryError):
    pass


SCHEMA = (
    "CREATE TABLE library_info (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), workspace_id TEXT NOT NULL UNIQUE)",
    """CREATE TABLE paper_core (
        paper_id TEXT PRIMARY KEY NOT NULL,
        excluded INTEGER NOT NULL DEFAULT 0 CHECK (excluded IN (0, 1)),
        metadata_generation INTEGER NOT NULL DEFAULT 1 CHECK (metadata_generation > 0),
        operation_generation INTEGER NOT NULL DEFAULT 1 CHECK (operation_generation > 0),
        body_generation INTEGER NOT NULL DEFAULT 1 CHECK (body_generation > 0))""",
    """CREATE TABLE paper_identities (
        namespace TEXT NOT NULL, normalized_value TEXT NOT NULL,
        paper_id TEXT NOT NULL REFERENCES paper_core(paper_id) ON DELETE RESTRICT,
        PRIMARY KEY (namespace, normalized_value))""",
    "CREATE INDEX identities_by_paper ON paper_identities(paper_id)",
    """CREATE TABLE paper_metadata (
        paper_id TEXT PRIMARY KEY NOT NULL REFERENCES paper_core(paper_id) ON DELETE RESTRICT,
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        abstract_generation INTEGER NOT NULL DEFAULT 1 CHECK (abstract_generation > 0))""",
    """CREATE TABLE paper_body (
        paper_id TEXT PRIMARY KEY NOT NULL REFERENCES paper_core(paper_id) ON DELETE RESTRICT,
        relative_path TEXT NOT NULL, source_url TEXT,
        size_bytes INTEGER CHECK (size_bytes IS NULL OR size_bytes >= 0))""",
)


def _validate_paths(workspace: Path) -> Path:
    path = workspace / DATABASE_NAME
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise UnsafeLibraryPath("Library path and parents must not contain symlinks")
    if not workspace.is_dir():
        raise LibraryMissingError("An existing Workspace directory is required")
    for candidate in (path, *(path.with_name(path.name + suffix) for suffix in ("-journal", "-wal", "-shm"))):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UnsafeLibraryPath("Library and sidecars must be single-link regular files")
    return path


def _sqlite_error(error: sqlite3.Error) -> LibraryError:
    code = getattr(error, "sqlite_errorcode", 0) & 0xFF
    if code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return LibraryBusyError("Library is busy; the bounded wait expired")
    if code in {sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB}:
        return LibraryCorruptError("Library is not a valid SQLite database")
    return LibraryError(f"SQLite library operation failed: {error}")


def upgrade_schema(connection: sqlite3.Connection, version: int) -> None:
    """The explicit upgrade entry point; add only known, transactional migrations here."""
    if version > SCHEMA_VERSION:
        raise UnsupportedLibrarySchema(f"Library schema {version} is newer than supported {SCHEMA_VERSION}")
    if version < SCHEMA_VERSION:
        raise UnsupportedLibrarySchema(f"No upgrade is defined from library schema {version}")


class LibraryDatabase:
    """One thread-confined connection. Concurrent workers open separate repositories."""

    def __init__(self, workspace: Path, *, create: bool, timeout: float):
        if not 0 <= timeout <= 5:
            raise ValueError("SQLite timeout must be between zero and five seconds")
        workspace = Path(workspace).absolute()
        if ".." in workspace.parts:
            raise UnsafeLibraryPath("Workspace path must not contain traversal")
        self.workspace = workspace
        self.path = _validate_paths(workspace)
        self.connection = None
        try:
            if create:
                if any(self.path.with_name(self.path.name + suffix).exists() for suffix in ("-journal", "-wal", "-shm")):
                    raise LibraryExistsError("Creation refuses existing SQLite sidecars")
                try:
                    descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError as error:
                    raise LibraryExistsError("Library already exists; open it explicitly") from error
                os.close(descriptor)
            elif not self.path.exists():
                raise LibraryMissingError("Paper library is missing; creation must be explicit")
            _validate_paths(workspace)  # Before SQLite can recover or touch any sidecar.
            self._file_identity = self._identity()
            self.connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                                              timeout=timeout, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            self.connection.execute("PRAGMA foreign_keys = ON")
            self.connection.execute("PRAGMA synchronous = FULL")
            if create:
                with self.transaction(write=True) as connection:
                    for statement in SCHEMA:
                        connection.execute(statement)
                    connection.execute("INSERT INTO library_info VALUES (1, ?)", (str(uuid4()),))
                    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
                    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            with self.transaction() as connection:
                self.workspace_id = self._validate_schema(connection)
        except BaseException as error:
            self.close()
            if isinstance(error, sqlite3.Error):
                raise _sqlite_error(error) from error
            raise

    def _identity(self):
        return tuple((info.st_dev, info.st_ino) for info in (self.workspace.stat(), self.path.stat()))

    def _validate_schema(self, connection):
        if connection.execute("PRAGMA application_id").fetchone()[0] != APPLICATION_ID:
            raise LibraryCorruptError("Not an Allfold Paper library")
        upgrade_schema(connection, connection.execute("PRAGMA user_version").fetchone()[0])
        expected_schema = {statement.split()[2]: " ".join(statement.split()) for statement in SCHEMA}
        actual_schema = {row["name"]: " ".join(row["sql"].split()) for row in connection.execute(
            "SELECT name, sql FROM sqlite_schema WHERE type IN ('table', 'index') AND sql IS NOT NULL")}
        if actual_schema != expected_schema:
            raise LibraryCorruptError("Library schema does not match its recorded version")
        if connection.execute("PRAGMA quick_check").fetchall()[0][0] != "ok":
            raise LibraryCorruptError("Library integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise LibraryCorruptError("Library contains broken references")
        try:
            rows = connection.execute("SELECT workspace_id FROM library_info WHERE singleton = 1").fetchall()
            if len(rows) != 1:
                raise ValueError("Missing Workspace identity")
            return UUID(rows[0][0])
        except (ValueError, sqlite3.Error) as error:
            raise LibraryCorruptError("Invalid library schema or Workspace identity") from error

    @contextmanager
    def transaction(self, *, write=False):
        if self.connection is None:
            raise LibraryError("Library is closed")
        _validate_paths(self.workspace)
        if self._identity() != self._file_identity:
            raise UnsafeLibraryPath("Workspace or database was replaced after opening")
        try:
            self.connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            try:
                yield self.connection
                self.connection.commit()
            except BaseException:
                self.connection.rollback()
                raise
        except sqlite3.Error as error:
            raise _sqlite_error(error) from error

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
