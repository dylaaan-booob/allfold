"""Read the bundled CARSI resource directory on first use."""

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from types import MappingProxyType

from allfold.url_safety import normalize_public_http_url


CATALOG_PATH = Path(__file__).with_name("carsi-catalog.sqlite")
_catalog_lock = Lock()
_catalog: Mapping[str, "CarsiResource"] | None = None


class CatalogError(ValueError):
    """The bundled directory or a selected resource could not be used."""


@dataclass(frozen=True)
class CarsiResource:
    production: str
    searchStr: str
    url: str
    sptype: str
    wayfless_url_template: str | None = None
    unavailable_reason: str | None = None
    entry_sources: tuple[str, ...] = ()
    entry_note: str | None = None

    @property
    def access_url(self) -> str | None:
        # Keep scheme-less references as directory evidence.
        try:
            return normalize_public_http_url(self.url.strip())
        except ValueError:
            return None


def read_carsi_catalog(path: Path) -> dict[str, CarsiResource]:
    """Load a built directory with a short-lived, read-only connection."""
    try:
        with closing(sqlite3.connect(path.absolute().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            rows = db.execute("""
                SELECT production, searchStr, url, sptype, wayfless_url_template,
                       unavailable_reason, entry_sources, entry_note
                FROM resources ORDER BY rowid
            """).fetchall()
    except sqlite3.Error as error:
        raise CatalogError("CARSI catalog could not be read") from error
    if not rows:
        raise CatalogError("CARSI catalog is empty")
    return {
        name: CarsiResource(name, search, url, sptype, template, unavailable, tuple(sources.splitlines()), note)
        for name, search, url, sptype, template, unavailable, sources, note in rows
    }


def get_carsi_catalog() -> Mapping[str, CarsiResource]:
    global _catalog
    with _catalog_lock:
        if _catalog is None:
            _catalog = MappingProxyType(read_carsi_catalog(CATALOG_PATH))
        return _catalog


def validate_carsi_service(name: str) -> CarsiResource:
    """Require an exact production name for a CARSI selection."""
    resource = get_carsi_catalog().get(name)
    if resource is None:
        raise CatalogError("CARSI Service name is not in the bundled catalog")
    return resource
