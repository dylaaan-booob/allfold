"""Shared, replace-on-success external snapshots. No configuration or user choices."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import time


APPLICATION_ID = 0x41465243  # AFRC; deliberately separate from user-data.sqlite.
SCHEMA_VERSION = 1
MAX_SNAPSHOT_BYTES = 32 * 1024 * 1024


class ResourceCacheError(ValueError):
    """The cache path or contents cannot safely be used."""


@dataclass(frozen=True)
class CachedResource:
    payload: dict
    fetched_at: float


def _check_path(path: Path, *, create: bool) -> None:
    # Do not normalize away a symlink followed by '..'. This cache is outside
    # Workspace and must not accidentally write through a substituted path.
    for parent in reversed(path.absolute().parents):
        try:
            info = parent.lstat()
        except FileNotFoundError:
            if not create:
                continue
            parent.mkdir()
            info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise ResourceCacheError("Resource cache parent is not a real directory")
    try:
        target = path.lstat()
    except FileNotFoundError:
        target = None
    if target is not None and (not stat.S_ISREG(target.st_mode) or target.st_nlink != 1):
        raise ResourceCacheError("Resource cache is not a single-link regular file")
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        if sidecar.is_symlink():
            raise ResourceCacheError("Resource cache sidecar cannot be a symlink")


@contextmanager
def _database(path: Path, *, create: bool):
    path = Path(path).absolute()
    _check_path(path, create=create)
    if not path.exists() and not create:
        yield None
        return
    new = False
    if not path.exists():
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
            new = True
    connection = None
    try:
        connection = sqlite3.connect(path.as_uri() + "?mode=rw", uri=True, timeout=5)
        identity = path.lstat()
        _check_path(path, create=False)
        app_id = connection.execute("PRAGMA application_id").fetchone()[0]
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if new:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TABLE snapshots (key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at REAL NOT NULL)")
            connection.execute(f"PRAGMA application_id={APPLICATION_ID}")
            connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
        elif app_id != APPLICATION_ID or version != SCHEMA_VERSION:
            raise ResourceCacheError("Resource cache has an unknown schema; existing data was preserved")
        yield connection
        _check_path(path, create=False)
        if not os.path.samestat(identity, path.lstat()):
            raise ResourceCacheError("Resource cache location changed")
    except (OSError, sqlite3.Error) as error:
        raise ResourceCacheError("Resource cache cannot be safely read or written") from error
    finally:
        if connection is not None:
            connection.close()


def read_snapshot(path: Path, key: str) -> CachedResource | None:
    """Read without creating a missing database. Domain modules validate payloads."""
    with _database(path, create=False) as connection:
        if connection is None:
            return None
        row = connection.execute("SELECT payload, fetched_at FROM snapshots WHERE key=?", (key,)).fetchone()
        if row is None:
            return None
        if len(row[0].encode("utf-8")) > MAX_SNAPSHOT_BYTES:
            raise ResourceCacheError("Resource cache snapshot exceeds size limit")
        try:
            payload = json.loads(row[0])
            fetched_at = float(row[1])
        except (ValueError, TypeError) as error:
            raise ResourceCacheError("Resource cache contains an invalid snapshot") from error
        if not isinstance(payload, dict):
            raise ResourceCacheError("Resource cache contains an invalid snapshot")
        return CachedResource(payload, fetched_at)


def write_snapshot(path: Path, key: str, payload: dict) -> CachedResource:
    """Atomically publish one already-validated, complete external snapshot."""
    encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise ResourceCacheError("Resource cache snapshot exceeds size limit")
    fetched_at = time()
    with _database(path, create=True) as connection:
        with connection:
            connection.execute("INSERT INTO snapshots(key, payload, fetched_at) VALUES(?, ?, ?) "
                               "ON CONFLICT(key) DO UPDATE SET payload=excluded.payload, fetched_at=excluded.fetched_at",
                               (key, encoded, fetched_at))
    return CachedResource(payload, fetched_at)
