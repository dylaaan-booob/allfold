"""The shipped registry is reproducible from unchanged offline journal sources."""
from contextlib import closing
import csv
from openpyxl import Workbook
import importlib.util
from pathlib import Path
import sqlite3

spec = importlib.util.spec_from_file_location('registry_build', Path(__file__).resolve().parents[1] / 'tools/build_journal_registry.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def database_contents(path):
    with closing(sqlite3.connect(path)) as db:
        schema = db.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        rows = db.execute('SELECT * FROM journals ORDER BY rowid').fetchall()
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
    return schema, rows


def test_shipped_registry_matches_complete_offline_build(tmp_path, monkeypatch):
    sources = builder.DATA_DIR
    expected = database_contents(sources / 'journal-registry.sqlite')
    # Private source files are absent from public CI. Exercise the complete
    # builder using all shipped source rows at its parser boundary; parser
    # behavior is checked independently with isolated source files below.
    monkeypatch.setattr(builder, 'wos_records', lambda path, source: (row for row in expected[1] if row[4] == source))
    monkeypatch.setattr(builder, 'scopus_records', lambda path: (row for row in expected[1] if row[4] == 'Scopus'))
    monkeypatch.setattr(builder, 'DATA_DIR', tmp_path)
    builder.build_registry()
    rebuilt = database_contents(tmp_path / 'journal-registry.sqlite')
    assert rebuilt == database_contents(sources / 'journal-registry.sqlite')
    assert [(kind, name) for kind, name, _ in rebuilt[0]] == [
        ('index', 'journals_eissn'), ('index', 'journals_issn'), ('table', 'journals')]
    assert len(rebuilt[1]) == 69531
    assert {row[4] for row in rebuilt[1]} == {'SCIE', 'SSCI', 'ESCI', 'AHCI', 'Scopus'}


def test_offline_source_parsers_keep_journals_identifiers_and_source_facts(tmp_path):
    path = tmp_path / 'journals.csv'
    with path.open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(['Journal title', 'ISSN', 'eISSN', 'Publisher name'])
        writer.writerow(['Journal', '0006341x', '1541-0420', 'Publisher'])
        writer.writerow(['Missing identity', '', '', 'Publisher'])
    assert list(builder.wos_records(path, 'SCIE')) == [('Journal', '0006-341X', '1541-0420', 'Publisher', 'SCIE', None)]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Scopus Sources Sep. 2026'
    sheet.append(['Source Title', 'ISSN', 'EISSN', 'Publisher', 'Source Type', 'Active or Inactive'])
    sheet.append(['Journal', '0006341x', '1541-0420', 'Publisher', 'Journal', 'Active'])
    sheet.append(['Book', '0006341x', None, 'Publisher', 'Book', 'Active'])
    workbook.save(tmp_path / 'source.xlsx')
    assert list(builder.scopus_records(tmp_path / 'source.xlsx')) == [('Journal', '0006-341X', '1541-0420', 'Publisher', 'Scopus', 'Active')]
