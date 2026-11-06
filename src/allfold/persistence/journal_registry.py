"""Read-only access to the local Journal Registry."""
from contextlib import closing
from itertools import batched
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
                related = set()
                # Both media bind the batch. Broad title searches can return
                # more identifiers than SQLite permits in one statement.
                for batch in batched(ids, connection.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER) // 2):
                    marks = ",".join("?" for _ in batch)
                    related.update(connection.execute(
                        f"SELECT title, issn, eissn, publisher, source, status FROM journals "
                        f"WHERE issn IN ({marks}) OR eissn IN ({marks})", (*batch, *batch),
                    ).fetchall())
                extra = related - seen
                if not extra:
                    break
                seen.update(extra)
            priority = {name: index for index, name in enumerate(("Scopus", "SCIE", "SSCI", "ESCI", "AHCI"))}
            rows = sorted(seen, key=lambda row: (priority.get(row[4], 5), row[0].casefold(), row[1] or "", row[2] or ""))
    except sqlite3.Error as error:
        raise ConfigurationError(f"Journal Registry unavailable: {path}: {error}",
                                 field="journal_registry", path=path) from error
    components, by_identifier = {}, {}
    for position, (title, issn, eissn, publisher, source, status) in enumerate(rows):
        try:
            journal = JournalConfig(name=title, issn=issn, eissn=eissn)
        except ValueError:
            continue
        # At most two identifier lookups, preserving the first source's order
        # when a newly encountered pair joins previously separate components.
        overlaps = sorted({by_identifier[value] for value in journal.identifiers if value in by_identifier})
        if overlaps:
            position = overlaps[0]
            component = components[position]
            for other_position in overlaps[1:]:
                other = components.pop(other_position)
                component["identifiers"].update(other["identifiers"])
                component["records"].extend(other["records"])
                for value in other["identifiers"]:
                    by_identifier[value] = position
        else:
            component = {"identifiers": set(), "records": []}
            components[position] = component
        component["identifiers"].update(journal.identifiers)
        component["records"].append((journal, publisher, source, status))
        for value in journal.identifiers:
            by_identifier[value] = position
    candidates = []
    for component in components.values():
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


def conference_candidates(list_path: Path, query: str) -> list[dict]:
    """Search only the shipped, read-only series registry, without network fallback."""
    import json
    path = list_path.parent / "journal-lists" / "journal-registry.sqlite"
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True)) as connection:
            rows = connection.execute("SELECT payload FROM conferences ORDER BY position").fetchall()
        entries = [json.loads(row[0]) for row in rows]
    except (sqlite3.Error, ValueError) as error:
        raise ConfigurationError(f"Conference Registry unavailable: {path}: {error}",
                                 field="conference_registry", path=path) from error
    needle = query.strip().casefold()
    return [entry for entry in entries if any(needle in value.casefold() for value in
        (entry['id'], entry['name'], entry['abbreviation'], entry['dblp_stream'], *entry['aliases']))]
