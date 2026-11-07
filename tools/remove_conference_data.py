"""One-time, explicitly invoked removal of retired scope data; never run at startup."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from allfold.config import normalize_journal_labels
from allfold.persistence.safe_write import ContentChangedError, source_file_identity
from allfold.persistence.user_state import _connect, _decode

_COLUMNS = ('config_path', 'revision', 'payload', 'migration_source', 'migration_digest', 'migrated_at')
_FIELDS = {'id', 'name', 'abbreviation', 'aliases', 'dblp_stream', 'group', 'labels'}


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field; refusing cleanup')
        result[key] = value
    return result


def _clean_payload(payload):
    raw = json.loads(payload, object_pairs_hook=_object)
    if not isinstance(raw, dict):
        raise ValueError('Unknown user state structure')
    if 'conferences' not in raw:
        _decode(payload)
        return None
    entries = raw.pop('conferences')
    cleaned = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    state = _decode(cleaned)  # All retained data must validate before any write.
    if not isinstance(entries, list):
        raise ValueError('Invalid retired scope collection')
    ids, streams = set(), set()
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != _FIELDS
                or not isinstance(entry['id'], str) or not re.fullmatch(r'conf_[0-9a-f]{32}', entry['id'])
                or not isinstance(entry['dblp_stream'], str) or not re.fullmatch(r'streams/conf/[a-z0-9_-]+', entry['dblp_stream'])):
            raise ValueError('Unknown retired scope entry')
        for key in ('name', 'abbreviation'):
            text = entry[key]
            if not isinstance(text, str) or not text.strip() or any(c in text for c in '|\r\n\x00'):
                raise ValueError('Invalid retired scope text')
        normalize_journal_labels(entry['aliases'])
        labels = normalize_journal_labels(entry['labels'])
        if entry['group'] is not None and (not isinstance(entry['group'], str) or entry['group'] not in state.groups):
            raise ValueError('Invalid retired scope Group')
        if any(label not in state.custom_labels for label in labels):
            raise ValueError('Invalid retired scope Label')
        if entry['id'] in ids or entry['dblp_stream'] in streams:
            raise ValueError('Duplicate retired scope identity')
        ids.add(entry['id'])
        streams.add(entry['dblp_stream'])
    return cleaned


def _rows(connection):
    schema = connection.execute("SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
    if schema != [('table', 'user_scopes')]:
        raise ValueError('Unknown database schema; refusing cleanup')
    if tuple(row[1] for row in connection.execute('PRAGMA table_info(user_scopes)')) != _COLUMNS:
        raise ValueError('Unknown user_scopes schema')
    if connection.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise ValueError('Database integrity check failed')
    rows = connection.execute('SELECT * FROM user_scopes ORDER BY config_path').fetchall()
    for config_path, revision, payload, source, digest, migrated_at in rows:
        if (not isinstance(config_path, str) or str(Path(config_path).resolve()) != config_path
                or type(revision) is not int or revision < 1 or not isinstance(payload, str)
                or any(value is not None and not isinstance(value, str) for value in (source, digest, migrated_at))):
            raise ValueError('Invalid scope identity or revision')
    return rows


def _backup(path, expected):
    descriptor, name = tempfile.mkstemp(prefix=path.name + '.before-scope-cleanup-', suffix='.bak', dir=path.parent)
    os.close(descriptor)  # mkstemp creates a private, non-overwriting backup.
    backup = Path(name)
    try:
        with closing(_connect(path)) as source, closing(sqlite3.connect(backup)) as destination:
            source.backup(destination)
            if _rows(destination) != expected:
                raise ContentChangedError('Backup does not match the captured database')
    except BaseException:
        backup.unlink(missing_ok=True)
        raise
    return backup


def remove_conference_data(path: Path):
    """Keep all scopes/retained values; compare captured rows under one write lock.

    The backup includes the complete original database. Each changed scope advances
    its generation exactly once so the normal content revision rejects stale writes.
    """
    path = path.absolute()
    with closing(_connect(path)) as connection:
        identity = source_file_identity(path)
        original = _rows(connection)
        changes = [(row, cleaned) for row in original if (cleaned := _clean_payload(row[2])) is not None]
        connection.execute('BEGIN IMMEDIATE')
        try:
            if source_file_identity(path) != identity or _rows(connection) != original:
                raise ContentChangedError('User state changed after cleanup preflight')
            if not changes:
                connection.rollback()
                return 0, None
            backup = _backup(path, original)
            for row, cleaned in changes:
                cursor = connection.execute('UPDATE user_scopes SET payload = ?, revision = revision + 1 WHERE config_path = ? AND revision = ? AND payload = ?',
                                            (cleaned, row[0], row[1], row[2]))
                if cursor.rowcount != 1:
                    raise ContentChangedError('User state revision changed during cleanup')
            if source_file_identity(path) != identity:
                raise ContentChangedError('User state file changed during cleanup')
            connection.commit()
            return len(changes), backup
        except BaseException:
            connection.rollback()
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('database', type=Path, help='Exact user-data.sqlite to clean; all other data is preserved')
    args = parser.parse_args()
    count, backup = remove_conference_data(args.database)
    print(f'Updated scopes: {count}')
    if backup:
        print(f'Recoverable backup: {backup}')
