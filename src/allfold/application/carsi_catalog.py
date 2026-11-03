"""CARSI's public Resource Catalog, independent of configuration and AI exports."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx

from allfold.http_client import create_http_client
from allfold.persistence.resource_cache import read_snapshot, write_snapshot
from allfold.url_safety import normalize_public_http_url


CARSI_DIRECTORY_URL = "https://www.carsi.edu.cn/SPlist.html"
MAX_CARSI_HTML_BYTES = 2 * 1024 * 1024
MAX_CARSI_RECORDS = 10_000
CARSI_TIMEOUT = httpx.Timeout(8.0, connect=4.0)
CARSI_TOTAL_SECONDS = 20.0
CATALOG_KEY = "carsi:catalog:v1"
CacheStatus = Literal["fresh", "cached", "stale", "unavailable"]


class CatalogError(ValueError):
    """The official catalog was not a complete, valid Resource array."""


@dataclass(frozen=True)
class CarsiResource:
    production: str
    searchStr: str
    url: str
    sptype: str

    @property
    def access_url(self) -> str | None:
        # The official page includes outer spaces and scheme-less references.
        # Trim whitespace only; never invent a scheme or a login destination.
        try:
            return normalize_public_http_url(self.url.strip())
        except ValueError:
            return None


@dataclass(frozen=True)
class CatalogChange:
    kind: Literal["removed", "possible_rename", "identity_conflict", "changed"]
    previous_production: str
    productions: tuple[str, ...]


@dataclass(frozen=True)
class CarsiCatalog:
    resources: tuple[CarsiResource, ...]
    status: CacheStatus
    fetched_at: float | None = None
    error: str | None = None
    changes: tuple[CatalogChange, ...] = ()


class _Scripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self._active = False
        self._parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._active, self._parts = True, []

    def handle_data(self, data):
        if self._active:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._active:
            self.scripts.append("".join(self._parts))
            self._active = False


def _resources(records) -> tuple[CarsiResource, ...]:
    if not isinstance(records, list) or not 0 < len(records) <= MAX_CARSI_RECORDS:
        raise CatalogError("CARSI SPList must contain a bounded, nonempty resource array")
    resources, productions = [], set()
    for index, record in enumerate(records, start=1):
        fields = ("production", "searchStr", "url", "sptype")
        if not isinstance(record, dict) or any(not isinstance(record.get(field), str)
                                             or not record[field].strip() for field in fields):
            raise CatalogError(f"CARSI SPList resource {index} lacks required fields")
        if record["production"] in productions:
            raise CatalogError("CARSI SPList has duplicate production identity")
        productions.add(record["production"])
        url = record["url"].strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme:
                normalize_public_http_url(url)
            elif not (url.startswith("www.") and not re.search(r"\s|[<>@\\]", url)):
                raise ValueError("invalid scheme-less reference")
        except ValueError as error:
            raise CatalogError(f"CARSI SPList resource {index} has an invalid URL") from error
        if record["sptype"] not in ("1", "2"):
            raise CatalogError(f"CARSI SPList resource {index} has an unknown sptype")
        resources.append(CarsiResource(**{field: record[field] for field in fields}))
    return tuple(resources)


def parse_carsi_directory(html: str) -> tuple[CarsiResource, ...]:
    """Parse the existing official inline `var SPList=[...];` without evaluation."""
    if len(html.encode("utf-8")) > MAX_CARSI_HTML_BYTES:
        raise CatalogError("CARSI directory response exceeds size limit")
    scripts = _Scripts()
    scripts.feed(html)
    declarations = []
    for script in scripts.scripts:
        match = re.match(r"\s*var\s+SPList\s*=\s*", script)
        if match is not None:
            declarations.append(script[match.end():])
    if len(declarations) != 1:
        raise CatalogError("CARSI directory has no unique official SPList data")
    try:
        records, position = json.JSONDecoder().raw_decode(declarations[0])
    except (ValueError, TypeError) as error:
        raise CatalogError("CARSI SPList is not valid JSON data") from error
    if not declarations[0][position:].lstrip().startswith(";"):
        raise CatalogError("CARSI SPList declaration is incomplete")
    return _resources(records)


def fetch_carsi_directory(*, transport: httpx.BaseTransport | None = None) -> tuple[CarsiResource, ...]:
    """One bounded public GET. A failure never returns an empty catalog."""
    started = time.monotonic()
    try:
        with create_http_client(transport=transport, timeout=CARSI_TIMEOUT, follow_redirects=False) as client:
            with client.stream("GET", CARSI_DIRECTORY_URL, headers={
                "Accept": "text/html", "User-Agent": "allfold/0.1.0 (public CARSI catalog)",
            }) as response:
                if response.is_redirect:
                    raise CatalogError("CARSI directory redirected; refusing unexpected destination")
                if response.status_code != 200:
                    raise CatalogError(f"CARSI directory returned HTTP {response.status_code}")
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "text/html":
                    raise CatalogError("CARSI directory has an unexpected content type")
                declared = response.headers.get("content-length")
                if declared is not None:
                    try:
                        size = int(declared)
                    except ValueError as error:
                        raise CatalogError("CARSI directory has invalid Content-Length") from error
                    if not 0 <= size <= MAX_CARSI_HTML_BYTES:
                        raise CatalogError("CARSI directory exceeds size limit")
                data = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > MAX_CARSI_HTML_BYTES:
                        raise CatalogError("CARSI directory exceeds size limit")
                    if time.monotonic() - started > CARSI_TOTAL_SECONDS:
                        raise CatalogError("CARSI directory request exceeded total time limit")
    except httpx.TimeoutException as error:
        raise CatalogError("CARSI directory request timed out") from error
    except (httpx.RequestError, httpx.InvalidURL) as error:
        raise CatalogError("CARSI directory request failed") from error
    try:
        return parse_carsi_directory(data.decode("utf-8"))
    except UnicodeError as error:
        raise CatalogError("CARSI directory is not valid UTF-8") from error


def _changes(previous, current):
    changes = []
    by_name = {item.production: item for item in current}
    for old in previous:
        same = by_name.get(old.production)
        if same is not None:
            if (same.url.strip(), same.sptype) != (old.url.strip(), old.sptype):
                changes.append(CatalogChange("changed", old.production, (same.production,)))
            continue
        # Same exact destination is evidence of a possible rename, never proof
        # of user intent. Multiple products can share a host and even a URL.
        replacements = tuple(item.production for item in current
                             if item.url.strip() == old.url.strip() and item.sptype == old.sptype)
        kind = "possible_rename" if len(replacements) == 1 else "identity_conflict" if replacements else "removed"
        changes.append(CatalogChange(kind, old.production, replacements))
    return tuple(changes)


def get_carsi_catalog(cache_path: Path, *, refresh=False,
                      transport: httpx.BaseTransport | None = None) -> CarsiCatalog:
    """Reuse shared snapshots until explicit refresh; surface renames as warnings."""
    cached = read_snapshot(cache_path, CATALOG_KEY)
    previous, changes = (), ()
    if cached is not None:
        previous = _resources(cached.payload.get("resources"))
        changes = tuple(CatalogChange(item["kind"], item["previous_production"], tuple(item["productions"]))
                        for item in cached.payload.get("changes", []))
        if not refresh:
            return CarsiCatalog(previous, "cached", cached.fetched_at, changes=changes)
    try:
        resources = fetch_carsi_directory(transport=transport)
    except CatalogError as error:
        return CarsiCatalog(previous, "stale" if cached else "unavailable",
                            cached.fetched_at if cached else None, str(error), changes)
    changes = _changes(previous, resources)
    saved = write_snapshot(cache_path, CATALOG_KEY, {"resources": [asdict(item) for item in resources],
                                                   "changes": [asdict(item) for item in changes]})
    return CarsiCatalog(resources, "fresh", saved.fetched_at, changes=changes)


def validate_carsi_service(name: str, *, catalog: CarsiCatalog) -> CarsiResource:
    """Validate an exact official production; an unrelated Journal mapping is allowed."""
    matches = [item for item in catalog.resources if item.production == name]
    if len(matches) != 1:
        raise CatalogError("CARSI Service name is not in the validated official catalog")
    return matches[0]
