"""Authoritative, config-scoped journal state; Markdown is migration/exchange only."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import stat
import yaml

from allfold.config import (
    AccessService, ConfigurationError, JournalConfig, SettingsList,
    parse_settings_list_text, parse_monitor_definition, validate_access_mapping, validate_entity_mapping,
    validate_journal_configs, validate_journal_storage,
)
from allfold.persistence.safe_write import ContentChangedError, read_text_exact, source_file_identity


@dataclass(frozen=True)
class ContentRevision:
    exists: bool
    digest: str | None


@dataclass(frozen=True)
class UserStateSnapshot:
    config_path: Path
    database_path: Path
    state: SettingsList
    revision: ContentRevision
    migration_source: str | None = None
    migration_digest: str | None = None


class UserStateError(ConfigurationError):
    """State is unavailable or unsafe; never replace it with a legacy fallback."""


def application_data_dir(config_path: Path) -> Path:
    """Shared app data root, with an isolated fallback for external test configs."""
    config_path = config_path.resolve()
    project_root = Path(__file__).resolve().parents[3]
    root = project_root if config_path.is_relative_to(project_root) else config_path.parent
    return root / ".allfold"


def user_state_path(config_path: Path) -> Path:
    return application_data_dir(config_path) / "user-data.sqlite"


def _safe_path(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise UserStateError("User state path must not contain a symlink", path=path)
    if path.exists() and not path.is_file():
        raise UserStateError("User state must be a regular file", path=path)


def validate_user_state(state: SettingsList) -> SettingsList:
    journals = validate_journal_configs(state.journals)
    validate_journal_storage(journals)
    validate_access_mapping(journals, state.access_services)
    validate_entity_mapping(journals, state.groups, state.custom_labels)
    return SettingsList(journals, tuple(state.groups), tuple(state.custom_labels), tuple(state.access_services))


def _encode(state: SettingsList) -> str:
    state = validate_user_state(state)
    return json.dumps(dict(journals=[j.model_dump(mode="json") for j in state.journals],
                           groups=state.groups, custom_labels=state.custom_labels,
                           access_services=[s.model_dump(mode="json") for s in state.access_services]),
                      ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode(payload: str) -> SettingsList:
    raw = json.loads(payload)
    if not isinstance(raw, dict) or set(raw) != {"journals", "groups", "custom_labels", "access_services"}:
        raise ValueError("Invalid user state schema")
    if any(not isinstance(raw[k], list) for k in raw):
        raise ValueError("Invalid user state collections")
    return validate_user_state(SettingsList(
        tuple(JournalConfig.model_validate(j) for j in raw["journals"]), tuple(raw["groups"]),
        tuple(raw["custom_labels"]), tuple(AccessService.model_validate(s) for s in raw["access_services"])))


def _connect(path: Path, *, create: bool = False):
    _safe_path(path)
    if path.exists() and path.stat().st_nlink != 1:
        raise UserStateError("User state must be a single-link regular file", path=path)
    # SQLite may recover or modify sidecars even while reading the main file.
    # Validate them before opening the connection, not after its first query.
    for suffix in ("-journal", "-wal", "-shm"):
        sidecar = path.with_name(path.name + suffix)
        try:
            info = sidecar.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise UserStateError("User state sidecar must be a single-link regular file", path=sidecar)
    if create:
        path.parent.mkdir(exist_ok=True)
        _safe_path(path)
    elif not path.exists():
        raise UserStateError("User state database is missing", path=path)
    return sqlite3.connect(path.as_uri() + ("?mode=rwc" if create else "?mode=rw"), uri=True, timeout=5)


def _snapshot(config_path: Path, row) -> UserStateSnapshot:
    generation, payload, source, source_digest = row
    if not isinstance(generation, int) or generation < 1:
        raise ValueError("Invalid user state revision")
    digest = hashlib.sha256(f"{config_path}\0{generation}\0{payload}".encode()).hexdigest()
    return UserStateSnapshot(config_path, user_state_path(config_path), _decode(payload),
                             ContentRevision(True, digest), source, source_digest)


def _row(connection, config_path):
    return connection.execute("SELECT revision, payload, migration_source, migration_digest FROM user_scopes WHERE config_path = ?", (str(config_path),)).fetchone()


def read_user_state(config_path: Path, *, allow_missing: bool = False) -> UserStateSnapshot:
    config_path = config_path.resolve()
    path = user_state_path(config_path)
    try:
        _safe_path(path)
        if allow_missing and not path.exists():
            return UserStateSnapshot(config_path, path, SettingsList((), (), (), ()), ContentRevision(False, None))
        with closing(_connect(path)) as connection:
            row = _row(connection, config_path)
            if row is None:
                if allow_missing:
                    return UserStateSnapshot(config_path, path, SettingsList((), (), (), ()), ContentRevision(False, None))
                raise UserStateError("Current configuration has no user state", path=path)
            return _snapshot(config_path, row)
    except (sqlite3.Error, ValueError, OSError) as error:
        raise UserStateError(f"Unable to read user state: {error}", path=path) from error


def load_user_state(config_path: Path, legacy_path: Path | None = None) -> UserStateSnapshot:
    """Read a scope, or atomically migrate its strictly validated legacy document once."""
    config_path = config_path.resolve()
    path = user_state_path(config_path)
    try:
        if path.exists() or path.is_symlink():
            with closing(_connect(path)) as connection:
                row = _row(connection, config_path)
                if row is not None:
                    return _snapshot(config_path, row)
        if legacy_path is None:
            definition = parse_monitor_definition(config_path, yaml.safe_load(read_text_exact(config_path)))
            legacy_path = definition.venue_whitelist
        legacy_path = (legacy_path if legacy_path.is_absolute() else config_path.parent / legacy_path).absolute()
        _safe_path(legacy_path)
        identity = source_file_identity(legacy_path)
        if legacy_path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Legacy journal data exceeds the 2 MiB limit")
        contents = read_text_exact(legacy_path)
        state = parse_settings_list_text(contents, path=legacy_path)
        payload = _encode(state)
        if source_file_identity(legacy_path) != identity or read_text_exact(legacy_path) != contents:
            raise ContentChangedError("Legacy journal data changed during migration")
        source_digest = hashlib.sha256(contents.encode()).hexdigest()
        # No database is opened for creation until the complete source validates.
        with closing(_connect(path, create=True)) as connection:
            with connection:
                connection.execute("CREATE TABLE IF NOT EXISTS user_scopes (config_path TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL, migration_source TEXT, migration_digest TEXT, migrated_at TEXT)")
                connection.execute("INSERT OR IGNORE INTO user_scopes VALUES (?, 1, ?, ?, ?, ?)",
                                   (str(config_path), payload, str(legacy_path.resolve()), source_digest,
                                    datetime.now(timezone.utc).isoformat()))
                return _snapshot(config_path, _row(connection, config_path))
    except (sqlite3.Error, ValueError, OSError, ContentChangedError, yaml.YAMLError) as error:
        raise UserStateError(f"Unable to load or migrate user state: {error}", path=path) from error


def compare_write_user_state(config_path: Path, state: SettingsList,
                             expected_revision: ContentRevision) -> UserStateSnapshot:
    """Commit validated state only while this config's original revision still matches."""
    config_path = config_path.resolve()
    path = user_state_path(config_path)
    payload = _encode(state)
    try:
        create = not expected_revision.exists and not path.exists()
        with closing(_connect(path, create=create)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                if create:
                    connection.execute("CREATE TABLE IF NOT EXISTS user_scopes (config_path TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL, migration_source TEXT, migration_digest TEXT, migrated_at TEXT)")
                row = _row(connection, config_path)
                if row is None:
                    if expected_revision != ContentRevision(False, None):
                        raise ContentChangedError("User state changed after it was opened")
                    connection.execute("INSERT INTO user_scopes VALUES (?, 1, ?, NULL, NULL, NULL)", (str(config_path), payload))
                elif _snapshot(config_path, row).revision != expected_revision:
                    raise ContentChangedError("User state changed after it was opened")
                elif payload != row[1]:
                    connection.execute("UPDATE user_scopes SET revision = revision + 1, payload = ? WHERE config_path = ?", (payload, str(config_path)))
                result = _snapshot(config_path, _row(connection, config_path))
                connection.commit()
                return result
            except BaseException:
                connection.rollback()
                raise
    except (sqlite3.Error, OSError) as error:
        raise UserStateError(f"Unable to write user state: {error}", path=path) from error
