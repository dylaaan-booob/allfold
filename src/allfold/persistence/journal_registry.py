"""Read-only access to the local Journal Registry."""
from contextlib import closing
from pathlib import Path
import sqlite3

from allfold.config import ConfigurationError, JournalConfig, normalize_journal_issn


def local_candidates(list_path: Path, query: str) -> list[dict]:
    path = list_path.parent / "journal-lists" / "journal-registry.sqlite"
    try:
        identifier = normalize_journal_issn(query)
    except ValueError:
        identifier = None
    condition = "issn = ? OR eissn = ?" if identifier else "instr(lower(title), lower(?)) > 0"
    parameters = (identifier, identifier) if identifier else (query,)
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute(
                # Match pairs first: a source-specific title must return the same
                # preferred title and complete evidence as an identifier lookup.
                f"WITH matching AS (SELECT DISTINCT issn, eissn FROM journals WHERE {condition}) "
                "SELECT title, journals.issn, journals.eissn, publisher, source, status "
                "FROM matching JOIN journals ON journals.issn IS matching.issn "
                "AND journals.eissn IS matching.eissn "
                "ORDER BY CASE source WHEN 'Scopus' THEN 0 WHEN 'SCIE' THEN 1 WHEN 'SSCI' THEN 2 "
                "WHEN 'ESCI' THEN 3 WHEN 'AHCI' THEN 4 ELSE 5 END, title COLLATE NOCASE",
                parameters,
            ).fetchall()
    except sqlite3.Error as error:
        raise ConfigurationError(f"Journal Registry unavailable: {path}: {error}",
                                 field="journal_registry", path=path) from error
    candidates = {}
    for title, issn, eissn, publisher, source, status in rows:
        try:
            journal = JournalConfig(name=title, issn=issn, eissn=eissn)
        except ValueError:
            continue
        pair = (journal.issn, journal.eissn)
        if pair not in candidates:
            candidates[pair] = dict(name=journal.name, issn=journal.issn, eissn=journal.eissn,
                                    publisher=publisher, sources=[], origin="registry")
        evidence = dict(source=source, title=journal.name, status=status)
        if evidence not in candidates[pair]["sources"]:
            candidates[pair]["sources"].append(evidence)
    return list(candidates.values())

