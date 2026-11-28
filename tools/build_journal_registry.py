"""Rebuild the standalone local journal registry from the five source lists."""

import argparse
import csv
import os
import re
import sqlite3
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
SCOPUS_COLUMNS = ("Source Title", "ISSN", "EISSN", "Publisher", "Source Type", "Active or Inactive")
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


def scopus_records(path: Path, sheet_name: str | None = None):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheets = [workbook[sheet_name]] if sheet_name is not None else workbook.worksheets
        matches = []
        for sheet in sheets:
            header = next(sheet.iter_rows(max_row=1, values_only=True), ())
            if all(header.count(name) == 1 for name in SCOPUS_COLUMNS):
                matches.append((sheet, {name: header.index(name) for name in SCOPUS_COLUMNS}))
        if not matches:
            raise ValueError(f"{path.name}: no worksheet with the required Scopus columns")
        if len(matches) > 1:
            raise ValueError(f"{path.name}: multiple worksheets have the Scopus columns; choose --scopus-sheet")
        sheet, columns = matches[0]
        rows = sheet.iter_rows(min_row=2, max_col=max(columns.values()) + 1, values_only=True)
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


def build_registry(scopus_path: Path, *, scopus_sheet: str | None = None, data_dir: Path = DATA_DIR) -> None:
    target = data_dir / "journal-registry.sqlite"
    descriptor, name = tempfile.mkstemp(
        dir=data_dir, prefix="journal-registry-", suffix=".sqlite.tmp",
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
                        INSERT_SQL, wos_records(data_dir / filename, source),
                    )
                connection.executemany(
                    INSERT_SQL, scopus_records(scopus_path, scopus_sheet),
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scopus", type=Path, help="Scopus source workbook")
    parser.add_argument("--scopus-sheet", help="Worksheet with the Scopus source columns")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR, help="WoS CSV and output directory")
    args = parser.parse_args()
    try:
        build_registry(args.scopus, scopus_sheet=args.scopus_sheet, data_dir=args.data_dir)
    except (KeyError, ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"Journal registry build failed: {error}\n")


if __name__ == "__main__":
    main()
