"""On-demand GOKB Journal → Current TIPP → Platform discovery, never a Run Provider.

API contract: openlibraryenvironment/gokb ed459e44eaef207cc79502fc15855b32ecf980f9,
ApiController.find + ESSearchService.find (default flattened ES records).
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import httpx

from allfold.config import JournalConfig, normalize_journal_issn
from allfold.persistence.resource_cache import read_snapshot, write_snapshot


GOKB_FIND_URL = "https://gokb.org/gokb/api/find"
GOKB_PAGE_SIZE = 100
GOKB_MAX_WINDOW = 10_000
MAX_PAGE_BYTES = 8 * 1024 * 1024
GOKB_TIMEOUT = httpx.Timeout(10.0, connect=4.0)
GOKB_TOTAL_SECONDS = 60.0
ISSN_NAMESPACES = {"issn", "eissn", "pissn", "e-issn", "p-issn", "issn-l"}


class GokbError(ValueError):
    """Remote data was unavailable or could not establish a complete snapshot."""


@dataclass(frozen=True)
class GokbIdentifier:
    namespace: str
    value: str


@dataclass(frozen=True)
class GokbJournal:
    uuid: str
    name: str
    identifiers: tuple[GokbIdentifier, ...]
    matched_identifiers: tuple[str, ...]


@dataclass(frozen=True)
class GokbTipp:
    uuid: str
    journal_uuid: str
    platform_uuid: str
    platform_name: str
    package_uuid: str
    package_name: str
    url: str | None


@dataclass(frozen=True)
class GokbPlatform:
    uuid: str
    name: str
    primary_url: str | None


@dataclass(frozen=True)
class GokbSnapshot:
    identifiers: tuple[str, ...]
    journals: tuple[GokbJournal, ...]
    tipps: tuple[GokbTipp, ...]
    platforms: tuple[GokbPlatform, ...]


@dataclass(frozen=True)
class GokbLookup:
    snapshot: GokbSnapshot | None
    status: Literal["fresh", "cached", "stale", "unavailable"]
    fetched_at: float | None = None
    error: str | None = None

    @property
    def outcome(self) -> Literal["ok", "no_results", "unavailable"]:
        if self.snapshot is None:
            return "unavailable"
        return "ok" if self.snapshot.journals else "no_results"


def _text(record, field, *, optional=False):
    value = record.get(field)
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 8192:
        raise GokbError(f"GOKB record lacks valid {field}")
    return value


def _uuid(record, field="uuid"):
    # GOKB stores UUID as a max-2048 text field, including imported identities.
    value = _text(record, field)
    if len(value) > 2048 or any(character.isspace() for character in value):
        raise GokbError(f"GOKB record lacks valid {field}")
    return value


class GokbClient:
    """Public unauthenticated HTTP only, injectable transport and bounded pagination."""

    def __init__(self, *, transport: httpx.BaseTransport | None = None):
        self.transport = transport

    def _page(self, client, params, started):
        data = bytearray()
        with client.stream("GET", GOKB_FIND_URL, params=params, headers={
            "Accept": "application/json", "User-Agent": "allfold/0.1.0 (journal resource discovery)",
        }) as response:
            if response.status_code != 200:
                raise GokbError(f"GOKB query returned HTTP {response.status_code}")
            if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise GokbError("GOKB query has an unexpected content type")
            for chunk in response.iter_bytes(chunk_size=65536):
                data.extend(chunk)
                if len(data) > MAX_PAGE_BYTES:
                    raise GokbError("GOKB page exceeds size limit")
                if time.monotonic() - started > GOKB_TOTAL_SECONDS:
                    raise GokbError("GOKB lookup exceeded total time limit")
        try:
            payload = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise GokbError("GOKB response is not valid JSON") from error
        if not isinstance(payload, dict) or payload.get("result") != "OK" or payload.get("errors"):
            raise GokbError("GOKB query did not return a successful result")
        return payload

    def _all(self, client, params, started):
        offset, expected_count, records, seen = 0, None, [], set()
        while True:
            maximum = min(GOKB_PAGE_SIZE, GOKB_MAX_WINDOW - offset)
            payload = self._page(client, {**params, "max": maximum, "offset": offset,
                                           "sort": "uuid", "order": "asc"}, started)
            count, size, returned_offset = (payload.get(key) for key in ("count", "max", "offset"))
            if any(type(value) is not int for value in (count, size, returned_offset)):
                raise GokbError("GOKB page lacks valid count/max/offset")
            if not 0 <= count <= GOKB_MAX_WINDOW:
                raise GokbError("GOKB result exceeds the supported complete-query window")
            if size != maximum or returned_offset != offset:
                raise GokbError("GOKB page max/offset does not match the request")
            if expected_count is not None and count != expected_count:
                raise GokbError("GOKB result count changed during pagination")
            expected_count = count
            page = payload.get("records")
            if not isinstance(page, list) or len(page) != min(maximum, max(0, count - offset)):
                raise GokbError("GOKB page is incomplete")
            for record in page:
                if not isinstance(record, dict):
                    raise GokbError("GOKB result contains an invalid record")
                identity = _uuid(record)
                if identity in seen:
                    raise GokbError("GOKB pagination contains a duplicate UUID")
                if record.get("componentType") != params["componentType"]:
                    raise GokbError("GOKB result has an unexpected componentType")
                seen.add(identity)
                records.append(record)
            offset += len(page)
            if offset == count:
                return records

    def fetch(self, journal: JournalConfig) -> GokbSnapshot:
        """Fetch every local ISSN/eISSN and every linked Current TIPP before return."""
        started = time.monotonic()
        try:
            with httpx.Client(transport=self.transport, timeout=GOKB_TIMEOUT, follow_redirects=False) as client:
                journals = {}
                for identifier in journal.identifiers:
                    # A bare identifier value matches any namespace: print ISSN
                    # and electronic ISSN are both queried, never title guessing.
                    for row in self._all(client, {"componentType": "JournalInstance", "identifier": identifier}, started):
                        raw_ids = row.get("identifiers")
                        if not isinstance(raw_ids, list):
                            raise GokbError("GOKB Journal lacks identifiers")
                        ids, matched = [], set()
                        for entry in raw_ids:
                            if not isinstance(entry, dict):
                                raise GokbError("GOKB Journal has invalid identifiers")
                            namespace, value = _text(entry, "namespace"), _text(entry, "value")
                            ids.append(GokbIdentifier(namespace, value))
                            if namespace.casefold() in ISSN_NAMESPACES:
                                try:
                                    normalized = normalize_journal_issn(value)
                                except ValueError:
                                    continue
                                if normalized in journal.identifiers:
                                    matched.add(normalized)
                        if identifier not in matched:
                            raise GokbError("GOKB Journal does not match the queried ISSN/eISSN")
                        record = GokbJournal(_uuid(row), _text(row, "name"), tuple(ids), tuple(sorted(matched)))
                        previous = journals.get(record.uuid)
                        if previous is not None and previous != record:
                            raise GokbError("GOKB Journal identity changed between identifier queries")
                        journals[record.uuid] = record
                tipps, platform_ids = {}, set()
                for identity in sorted(journals):
                    for row in self._all(client, {"componentType": "TitleInstancePackagePlatform",
                                                  "linkedTitle": identity, "status": "Current"}, started):
                        if row.get("status") != "Current" or _uuid(row, "tippTitleUuid") != identity:
                            raise GokbError("GOKB TIPP is not a Current association for the queried Journal")
                        record = GokbTipp(_uuid(row), identity, _uuid(row, "hostPlatformUuid"),
                                         _text(row, "hostPlatformName"), _uuid(row, "tippPackageUuid"),
                                         _text(row, "tippPackageName"), _text(row, "url", optional=True))
                        if record.uuid in tipps:
                            raise GokbError("GOKB TIPP is linked to conflicting Journal identities")
                        tipps[record.uuid] = record
                        platform_ids.add(record.platform_uuid)
                platforms = []
                for identity in sorted(platform_ids):
                    rows = self._all(client, {"componentType": "Platform", "uuid": identity}, started)
                    if len(rows) != 1 or _uuid(rows[0]) != identity:
                        raise GokbError("GOKB Platform UUID does not resolve uniquely")
                    row = rows[0]
                    platforms.append(GokbPlatform(identity, _text(row, "name"), _text(row, "primaryUrl", optional=True)))
                return GokbSnapshot(tuple(sorted(journal.identifiers)), tuple(journals[key] for key in sorted(journals)),
                                    tuple(tipps[key] for key in sorted(tipps)), tuple(platforms))
        except httpx.TimeoutException as error:
            raise GokbError("GOKB request timed out") from error
        except (httpx.RequestError, httpx.InvalidURL) as error:
            raise GokbError("GOKB request failed") from error


def _from_cache(payload, identifiers):
    try:
        snapshot = GokbSnapshot(
            tuple(payload["identifiers"]),
            tuple(GokbJournal(item["uuid"], item["name"], tuple(GokbIdentifier(**entry) for entry in item["identifiers"]),
                              tuple(item["matched_identifiers"])) for item in payload["journals"]),
            tuple(GokbTipp(**item) for item in payload["tipps"]),
            tuple(GokbPlatform(**item) for item in payload["platforms"]),
        )
        if snapshot.identifiers != identifiers:
            raise ValueError("cache identifiers differ")
        journal_ids = [item.uuid for item in snapshot.journals]
        platform_ids = [item.uuid for item in snapshot.platforms]
        if (len(set(journal_ids)) != len(journal_ids) or len(set(platform_ids)) != len(platform_ids)
                or len({item.uuid for item in snapshot.tipps}) != len(snapshot.tipps)
                or any(item.journal_uuid not in journal_ids or item.platform_uuid not in platform_ids
                       for item in snapshot.tipps)):
            raise ValueError("cache associations differ")
        return snapshot
    except (ValueError, TypeError, KeyError) as error:
        raise GokbError("GOKB cached snapshot is invalid; existing data was preserved") from error


def get_journal_resources(cache_path: Path, journal: JournalConfig, *, refresh=False,
                          transport: httpx.BaseTransport | None = None) -> GokbLookup:
    """Only a validated complete query may replace a last-good (including empty) result."""
    identifiers = tuple(sorted(journal.identifiers))
    key = "gokb:journal:v1:" + ",".join(identifiers)
    cached = read_snapshot(cache_path, key)
    previous = _from_cache(cached.payload, identifiers) if cached else None
    if cached is not None and not refresh:
        return GokbLookup(previous, "cached", cached.fetched_at)
    try:
        snapshot = GokbClient(transport=transport).fetch(journal)
    except GokbError as error:
        return GokbLookup(previous, "stale" if cached else "unavailable", cached.fetched_at if cached else None, str(error))
    saved = write_snapshot(cache_path, key, asdict(snapshot))
    return GokbLookup(snapshot, "fresh", saved.fetched_at)
