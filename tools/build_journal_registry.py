"""Rebuild the standalone local journal registry from the five source lists."""

import csv
import os
import re
import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

from openpyxl import load_workbook


DATA_DIR = Path(__file__).resolve().parents[1] / "journal-lists"
WOS_FILES = (
    ("SCIE", "Science Citation Index Expanded (SCIE).csv"),
    ("SSCI", "Social Sciences Citation Index (SSCI).csv"),
    ("ESCI", "Emerging Sources Citation Index (ESCI).csv"),
    ("AHCI", "Arts & Humanities Citation Index (AHCI).csv"),
)
INSERT_SQL = """
    INSERT INTO journals (title, issn, eissn, publisher, source, status)
    VALUES (?, ?, ?, ?, ?, ?)
"""


def normalize_issn(value: str | None, location: str) -> str | None:
    if value is None or not value.strip():
        return None
    compact = value.strip().replace("-", "").upper()
    if not re.fullmatch(r"[0-9]{7}[0-9X]", compact):
        raise ValueError(f"{location}: invalid ISSN {value!r}")
    return f"{compact[:4]}-{compact[4:]}"


def wos_records(path: Path, source: str):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            location = f"{path.name}: line {reader.line_num}"
            issn = normalize_issn(row["ISSN"], location)
            eissn = normalize_issn(row["eISSN"], location)
            if issn is not None or eissn is not None:
                yield (
                    row["Journal title"], issn, eissn,
                    row["Publisher name"], source, None,
                )


def scopus_records(path: Path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        rows = workbook["Scopus Sources Sep. 2026"].iter_rows(values_only=True)
        header = next(rows)
        columns = {
            name: header.index(name)
            for name in (
                "Source Title", "ISSN", "EISSN", "Publisher",
                "Source Type", "Active or Inactive",
            )
        }
        for line, row in enumerate(rows, start=2):
            if row[columns["Source Type"]] != "Journal":
                continue
            location = f"{path.name}: row {line}"
            issn = normalize_issn(row[columns["ISSN"]], location)
            eissn = normalize_issn(row[columns["EISSN"]], location)
            if issn is not None or eissn is not None:
                yield (
                    row[columns["Source Title"]], issn, eissn,
                    row[columns["Publisher"]], "Scopus",
                    row[columns["Active or Inactive"]],
                )
    finally:
        workbook.close()


def build_registry() -> None:
    target = DATA_DIR / "journal-registry.sqlite"
    descriptor, name = tempfile.mkstemp(
        dir=DATA_DIR, prefix="journal-registry-", suffix=".sqlite.tmp",
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as connection:
            with connection:
                connection.execute("""
                    CREATE TABLE journals (
                        title TEXT, issn TEXT, eissn TEXT,
                        publisher TEXT, source TEXT, status TEXT
                    )
                """)
                for source, filename in WOS_FILES:
                    connection.executemany(
                        INSERT_SQL, wos_records(DATA_DIR / filename, source),
                    )
                connection.executemany(
                    INSERT_SQL, scopus_records(DATA_DIR / "ext_list_Sep_2026.xlsx"),
                )
                connection.execute("CREATE INDEX journals_issn ON journals (issn)")
                connection.execute("CREATE INDEX journals_eissn ON journals (eissn)")
                counts = connection.execute(
                    "SELECT source, COUNT(*) FROM journals GROUP BY source ORDER BY source"
                ).fetchall()
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    print(f"Database: {target}")
    print(f"Total: {sum(count for _, count in counts):,}")
    for source, count in counts:
        print(f"{source}: {count:,}")


if __name__ == "__main__":
    try:
        if sys.argv[1:]:
            raise ValueError("Usage: build_journal_registry.py")
        else:
            build_registry()
    except Exception as error:
        print(f"Journal registry build failed: {error}", file=sys.stderr)
        sys.exit(1)
