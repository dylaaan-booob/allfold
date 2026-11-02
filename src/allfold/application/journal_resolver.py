"""Evidence-only Journal → Platform → CARSI resolution; user state is never written."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import httpx

from allfold.application.carsi_catalog import CarsiCatalog, CarsiResource, get_carsi_catalog
from allfold.config import JournalConfig
from allfold.providers.gokb import GokbLookup, GokbPlatform, GokbSnapshot, get_journal_resources
from allfold.url_safety import normalize_public_http_url


@dataclass(frozen=True)
class MatchEvidence:
    kind: Literal["platform_host", "redirect_target_host", "production_name", "search_name"]
    value: str
    platform_uuid: str
    platform_name: str
    platform_url: str | None
    tipp_uuids: tuple[str, ...]
    journal_uuids: tuple[str, ...]
    package_names: tuple[str, ...]


@dataclass(frozen=True)
class ServiceCandidate:
    resource: CarsiResource
    reliable: bool
    evidence: tuple[MatchEvidence, ...]

    @property
    def production(self) -> str:
        return self.resource.production

    @property
    def access_url(self) -> str | None:
        return self.resource.access_url


@dataclass(frozen=True)
class JournalResolution:
    journal_key: str
    gokb: GokbLookup
    catalog: CarsiCatalog
    candidates: tuple[ServiceCandidate, ...]
    unique_candidate: ServiceCandidate | None
    status: Literal["unique", "ambiguous", "unresolved", "no_results", "unavailable"]
    warnings: tuple[str, ...] = ()


def normalized_host(url: str | None) -> str | None:
    """Exact normalized hosts only; no registrable-domain or publisher guessing."""
    if not url:
        return None
    try:
        normalize_public_http_url(url.strip())
        parsed = urlsplit(url.strip())
        host = parsed.hostname.encode("idna").decode("ascii").casefold().rstrip(".")
        if host.startswith("www."):
            host = host[4:]
        # A nonstandard port is a different origin, not equivalent host evidence.
        if parsed.port is not None and parsed.port != (443 if parsed.scheme == "https" else 80):
            host += f":{parsed.port}"
        return host
    except (ValueError, UnicodeError):
        return None


def _resource_host(resource):
    url = resource.url.strip()
    host = normalized_host(url)
    if host == "wayf.springernature.com":
        targets = parse_qs(urlsplit(url).query).get("redirect_uri", [])
        if len(targets) == 1:
            target = normalized_host(targets[0])
            if target in {"link.springer.com", "nature.com"}:
                return target, "redirect_target_host"
        # The login router itself is not the publication platform.
        return None, "redirect_target_host"
    return host, "platform_host"


def _name(value):
    return "".join(character for character in unicodedata.normalize("NFKC", value).casefold()
                   if character.isalnum())


def _matches(platform: GokbPlatform, resource: CarsiResource, snapshot: GokbSnapshot):
    platform_host = normalized_host(platform.primary_url)
    resource_host, host_kind = _resource_host(resource)
    matches = []
    if platform_host is not None and platform_host == resource_host:
        matches.append((host_kind, platform_host))
    platform_name = _name(platform.name)
    if platform_name and platform_name == _name(resource.production):
        matches.append(("production_name", platform.name))
    # searchStr also contains vendor names. Only its first product segment may
    # establish exact product-name evidence; never match vendor text in the tail.
    product = resource.searchStr.split("-", 1)[0]
    if platform_name and platform_name == _name(product):
        matches.append(("search_name", product))
    if not matches:
        return (), False
    tipps = [item for item in snapshot.tipps if item.platform_uuid == platform.uuid]
    evidence = tuple(MatchEvidence(kind, value, platform.uuid, platform.name, platform.primary_url,
                                    tuple(item.uuid for item in tipps),
                                    tuple(sorted({item.journal_uuid for item in tipps})),
                                    tuple(sorted({item.package_name for item in tipps}))) for kind, value in matches)
    conflicting_hosts = platform_host and resource_host and platform_host != resource_host
    # An ebook product stays visible, but a journal's shared host does not make
    # that specific product a reliable default. All other matching products are
    # also retained; package evidence is displayed without inventing entitlement.
    product_text = " ".join((resource.production, product, urlsplit(resource.url.strip()).path)).casefold()
    ebook = bool(re.search(r"ebooks?|e-books?|\bbooks\b|电子书", product_text))
    reliable = bool(resource.access_url and not conflicting_hosts and not ebook)
    return evidence, reliable


def match_carsi_candidates(snapshot: GokbSnapshot, catalog: CarsiCatalog) -> tuple[ServiceCandidate, ...]:
    """Return every matching product and the exact remote associations behind it."""
    candidates = []
    for resource in catalog.resources:
        evidence, reliable = [], False
        for platform in snapshot.platforms:
            matches, supported = _matches(platform, resource, snapshot)
            evidence.extend(matches)
            reliable = reliable or supported
        if evidence:
            candidates.append(ServiceCandidate(resource, reliable, tuple(evidence)))
    return tuple(sorted(candidates, key=lambda item: item.production))


def resolve_journal(config_path: Path, journal: JournalConfig, *, refresh=False,
                    transport: httpx.BaseTransport | None = None,
                    cache_path: Path | None = None) -> JournalResolution:
    """Discover candidates; a caller may adopt unique_candidate with its own CAS.

    An existing Service is never changed here. The shared cache contains only
    public data, not a Journal's manual selection or configuration identity.
    """
    if cache_path is None:
        from allfold.persistence.user_state import application_data_dir
        cache_path = application_data_dir(config_path) / "resources.sqlite"
    gokb = get_journal_resources(cache_path, journal, refresh=refresh, transport=transport)
    catalog = get_carsi_catalog(cache_path, refresh=refresh, transport=transport)
    candidates = match_carsi_candidates(gokb.snapshot, catalog) if gokb.snapshot is not None else ()
    warnings = tuple(f"CARSI {change.kind}: {change.previous_production}"
                     + (" → " + ", ".join(change.productions) if change.productions else "")
                     for change in catalog.changes)
    identity_count = len(gokb.snapshot.journals) if gokb.snapshot else 0
    conflicts = {name for change in catalog.changes if change.kind in {"possible_rename", "identity_conflict", "changed"}
                 for name in change.productions}
    unique = (candidates[0] if len(candidates) == 1 and candidates[0].reliable and identity_count == 1
              and candidates[0].production not in conflicts else None)
    if gokb.outcome == "unavailable" or catalog.status == "unavailable":
        status = "unavailable"
    elif identity_count > 1 or len(candidates) > 1:
        status = "ambiguous"
    elif gokb.outcome == "no_results":
        status = "no_results"
    elif unique is not None:
        status = "unique"
    else:
        status = "unresolved"
    return JournalResolution(journal.key, gokb, catalog, candidates, unique, status, warnings)
