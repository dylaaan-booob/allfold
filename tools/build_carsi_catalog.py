"""Build the bundled CARSI SQLite directory from reviewed UTF-8 CSV."""

import argparse
import csv
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

from allfold.application.carsi_catalog import CATALOG_PATH
from allfold.application.carsi_entry import wayfless_url
from allfold.config import InstitutionConfig
from allfold.url_safety import normalize_public_http_url


FIELDS = (
    "production", "searchStr", "url", "sptype", "wayfless_url_template",
    "unavailable_reason", "entry_sources", "entry_note",
)
SAMPLE_INSTITUTION = InstitutionConfig(
    idp_entity_id="https://idp.example/idp",
    product_tenant_id="sample/tenant",
    gale_location_id="sample",
    institution_resource_url="https://library.example/",
)


def checked_values(row):
    if None in row or any(row[field] is None for field in FIELDS):
        raise ValueError("Incomplete or misaligned CSV row")
    name, search, url, sptype, template, unavailable, sources, note = (row[field] for field in FIELDS)
    if not name or name != name.strip() or not search.strip():
        raise ValueError("A production name and search label are required")
    if sptype not in {"1", "2"}:
        raise ValueError("Unknown CARSI product type")
    reference = url.strip()
    if not normalize_public_http_url("https://" + reference if reference.startswith("www.") else reference):
        raise ValueError("A CARSI resource URL or scheme-less reference is required")
    if template:
        if unavailable:
            raise ValueError("An unavailable resource must not have a default WAYFless template")
        if any(mark in urlsplit(template).netloc for mark in "{}"):
            raise ValueError("An entry template must have a fixed host")
        example = wayfless_url(template, SAMPLE_INSTITUTION)
        if example is None or any(mark in example for mark in "{}"):
            raise ValueError("Invalid WAYFless template")
    source_urls = sources.splitlines()
    if not source_urls or not all(normalize_public_http_url(value) for value in source_urls):
        raise ValueError("HTTP(S) entry sources are required")
    return name, search, url, sptype, template or None, unavailable or None, "\n".join(source_urls), note or None


def catalog_rows(source):
    with source.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        header = reader.fieldnames or []
        if len(set(header)) != len(header) or not set(FIELDS).issubset(header):
            raise ValueError("CSV requires all CARSI catalog columns")
        names = set()
        for row in reader:
            try:
                values = checked_values(row)
                name = values[0].casefold()
                if name in names:
                    raise ValueError("Duplicate production name")
                names.add(name)
            except ValueError as error:
                raise ValueError(f"{source.name}:{reader.line_num}: {error}") from error
            yield values
        if not names:
            raise ValueError("CARSI catalog CSV is empty")


def build_catalog(source: Path, target: Path):
    if source.resolve() == target.resolve():
        raise ValueError("Choose a separate output file")
    descriptor, name = tempfile.mkstemp(dir=target.parent, prefix="carsi-catalog-", suffix=".sqlite.tmp")
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as db, db:
            db.execute("""
                CREATE TABLE resources (
                    production TEXT PRIMARY KEY NOT NULL,
                    searchStr TEXT NOT NULL,
                    url TEXT NOT NULL,
                    sptype TEXT NOT NULL,
                    wayfless_url_template TEXT,
                    unavailable_reason TEXT,
                    entry_sources TEXT NOT NULL,
                    entry_note TEXT
                )
            """)
            db.executemany("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?, ?, ?)", catalog_rows(source))
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, default=CATALOG_PATH)
    args = parser.parse_args()
    try:
        build_catalog(args.source, args.output)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f"CARSI catalog build failed: {error}\n")
    print(f"Built {args.output}")


if __name__ == "__main__":
    main()
