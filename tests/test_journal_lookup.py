"""Local Registry searches retain complete identity evidence at SQLite limits."""
import sqlite3

from allfold.application.journal_lookup import search_journals
from settings_api_helpers import registry


def test_broad_name_search_stays_within_sqlite_parameter_limit_and_keeps_related_sources(tmp_path, monkeypatch):
    registry(tmp_path, [
        ('Journal Alpha', '0006-341X', None, 'Wiley', 'Scopus', 'Active'),
        ('Biometrics', '0006-341X', '1541-0420', 'Wiley', 'SCIE', None),
        ('Biometrics electronic', None, '1541-0420', 'Wiley', 'SSCI', None),
        ('Journal Beta', '0090-5364', '1932-6157', 'IMS', 'Scopus', 'Active'),
        ('Journal Gamma', '1234-5679', '2049-3630', 'Fixture', 'Scopus', 'Active'),
    ])
    connect = sqlite3.connect
    def limited_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 8)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', limited_connection)

    found = search_journals(tmp_path / 'list.md', 'Journal', limit=None)
    assert [(row['issn'], row['eissn']) for row in found] == [
        ('0006-341X', '1541-0420'), ('0090-5364', '1932-6157'), ('1234-5679', '2049-3630'),
    ]
    assert [source['title'] for source in found[0]['sources']] == [
        'Journal Alpha', 'Biometrics', 'Biometrics electronic',
    ]
    assert search_journals(tmp_path / 'list.md', 'Journal', limit=2) == found[:2]


def test_a_pair_joining_two_components_keeps_first_source_order_and_all_evidence(tmp_path):
    registry(tmp_path, [
        ('First title', '0006-341X', None, 'Wiley', 'Scopus', 'Active'),
        ('Second title', None, '1541-0420', 'Wiley', 'Scopus', 'Active'),
        ('Connecting title', '0006-341X', '1541-0420', 'Wiley', 'SCIE', None),
    ])
    found = search_journals(tmp_path / 'list.md', 'title')
    assert len(found) == 1
    assert (found[0]['name'], found[0]['issn'], found[0]['eissn']) == ('First title', '0006-341X', '1541-0420')
    assert [source['title'] for source in found[0]['sources']] == ['First title', 'Second title', 'Connecting title']
