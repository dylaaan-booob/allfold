"""Check the shipped journal data and rebuild from isolated source files."""

import csv
import importlib.util
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from openpyxl import Workbook

spec = importlib.util.spec_from_file_location('registry_build', Path(__file__).resolve().parents[1] / 'tools/build_journal_registry.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_shipped_registry_contains_indexed_journal_identities():
    path = builder.DATA_DIR / 'journal-registry.sqlite'
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert not db.execute("SELECT 1 FROM journals WHERE issn IS NULL AND eissn IS NULL LIMIT 1").fetchone()
        assert {source for source, in db.execute('SELECT DISTINCT source FROM journals')} == {
            'Scopus', *(source for source, _ in builder.WOS_FILES),
        }
        leading_columns = {column for column, in db.execute("""
            SELECT col.name FROM pragma_index_list('journals') AS idx
            JOIN pragma_index_info(idx.name) AS col ON col.seqno = 0
        """)}
        assert {'issn', 'eissn'} <= leading_columns


def test_offline_build_keeps_approved_sources_and_reads_required_scopus_columns(tmp_path):
    for source, filename in builder.WOS_FILES:
        with (tmp_path / filename).open('w', newline='', encoding='utf-8') as handle:
            writer = csv.writer(handle)
            writer.writerow(['Journal title', 'ISSN', 'eISSN', 'Publisher name'])
            writer.writerow([source + ' Journal', '0006341x', '1541-0420', 'Publisher'])
            writer.writerow(['Missing identity', '', '', 'Publisher'])
    workbook = Workbook()
    workbook.active.append(['About this workbook'])
    sheet = workbook.create_sheet('Current sources')
    sheet.append(['Publisher', 'Unrelated field', 'EISSN', 'Source Title', 'ISSN', 'Active or Inactive', 'Source Type'])
    sheet.append(['Publisher', None, '1541-0420', 'Scopus Journal', '0006341x', 'Active', 'Journal'])
    sheet.append(['Publisher', None, None, 'Book', '0006341x', 'Active', 'Book'])
    path = tmp_path / 'reviewed-sources.xlsx'
    workbook.save(path)

    builder.build_registry(path, data_dir=tmp_path)
    with closing(sqlite3.connect(tmp_path / 'journal-registry.sqlite')) as db:
        assert sorted(db.execute('SELECT * FROM journals')) == sorted([
            ('Scopus Journal', '0006-341X', '1541-0420', 'Publisher', 'Scopus', 'Active'),
            *((source + ' Journal', '0006-341X', '1541-0420', 'Publisher', source, None)
              for source, _ in builder.WOS_FILES),
        ])

    workbook.copy_worksheet(sheet).title = 'Another edition'
    workbook.save(path)
    with pytest.raises(ValueError, match='choose --scopus-sheet'):
        list(builder.scopus_records(path))
    assert list(builder.scopus_records(path, 'Current sources')) == [
        ('Scopus Journal', '0006-341X', '1541-0420', 'Publisher', 'Scopus', 'Active'),
    ]
