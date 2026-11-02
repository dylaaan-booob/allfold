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
                f"SELECT title, issn, eissn, publisher, source, status FROM journals WHERE {condition}",
                parameters,
            ).fetchall()
            # Expand the connected identifier component, including one-medium
            # records from another source. The shipped database remains read-only.
            seen = set(rows)
            while rows:
                ids = {value for row in seen for value in row[1:3] if value}
                if not ids:
                    break
                marks = ",".join("?" for _ in ids)
                related = connection.execute(
                    f"SELECT title, issn, eissn, publisher, source, status FROM journals "
                    f"WHERE issn IN ({marks}) OR eissn IN ({marks})", (*ids, *ids),
                ).fetchall()
                extra = set(related) - seen
                if not extra:
                    break
                seen.update(extra)
            priority = {name: index for index, name in enumerate(("Scopus", "SCIE", "SSCI", "ESCI", "AHCI"))}
            rows = sorted(seen, key=lambda row: (priority.get(row[4], 5), row[0].casefold(), row[1] or "", row[2] or ""))
    except sqlite3.Error as error:
        raise ConfigurationError(f"Journal Registry unavailable: {path}: {error}",
                                 field="journal_registry", path=path) from error
    components = []
    for title, issn, eissn, publisher, source, status in rows:
        try:
            journal = JournalConfig(name=title, issn=issn, eissn=eissn)
        except ValueError:
            continue
        overlaps = [component for component in components if component["identifiers"] & set(journal.identifiers)]
        if overlaps:
            component = overlaps[0]
            for other in overlaps[1:]:
                component["identifiers"].update(other["identifiers"])
                component["records"].extend(other["records"])
                components.remove(other)
        else:
            component = {"identifiers": set(), "records": []}
            components.append(component)
        component["identifiers"].update(journal.identifiers)
        component["records"].append((journal, publisher, source, status))
    candidates = []
    for component in components:
        records = component["records"]
        # More than two connected identifiers cannot fit the existing Journal
        # model safely. Keep each pair visible for an explicit choice.
        pairs = list(dict.fromkeys((j.issn, j.eissn) for j, *_ in records))
        if len(component["identifiers"]) <= 2:
            first = next((j for j, *_ in records if len(j.identifiers) == 2), records[0][0])
            primary = first.issn or first.eissn
            secondary = next((value for value in sorted(component["identifiers"]) if value != primary), None)
            pairs = [(primary, secondary)] if secondary else [(first.issn, first.eissn)]
        for issn, eissn in pairs:
            first, publisher, *_ = records[0]
            sources = []
            for journal, _, source, status in records:
                evidence = dict(source=source, title=journal.name, status=status)
                if evidence not in sources:
                    sources.append(evidence)
            candidates.append(dict(name=first.name, issn=issn, eissn=eissn,
                                   publisher=publisher, sources=sources, origin="registry",
                                   identity_conflict=len(component["identifiers"]) > 2))
    return candidates
