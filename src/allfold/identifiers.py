"""Shared external-identifier normalization."""

from __future__ import annotations

import re
from typing import Any


def normalize_doi(value: Any) -> str | None:
    """Normalize a DOI without imposing syntax beyond the existing provider contract."""

    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid DOI")
    doi = value.strip()
    prefix = "https://doi.org/"
    if doi.casefold().startswith(prefix):
        doi = doi[len(prefix) :].strip()
    if not doi:
        return None
    return doi.casefold()


def valid_doi(value: str | None) -> str | None:
    doi = normalize_doi(value)
    return doi if doi and re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi) else None



RELIABLE_NAMESPACES = frozenset({"doi", "openalex", "arxiv", "dblp", "europe_pmc", "zbmath", "pmid", "pmcid", "wos"})


def normalize_external_id(namespace: str, value: Any) -> str | None:
    """Normalize only explicit strong identifiers; unknown namespaces are descriptive."""
    if namespace not in RELIABLE_NAMESPACES or not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if namespace == "doi":
        return valid_doi(value)
    if namespace == "openalex":
        value = value.removeprefix("https://openalex.org/").upper()
        return value if re.fullmatch(r"W[0-9]+", value) else None
    if namespace == "arxiv":
        value = re.sub(r"^https?://arxiv\.org/abs/", "", value)
        value = re.sub(r"v[0-9]+$", "", value)
        return value if re.fullmatch(r"(?:[0-9]{4}\.[0-9]{4,5}|[a-z-]+(?:\.[A-Z]{2})?/[0-9]{7})", value) else None
    if namespace == "dblp":
        return re.sub(r"^https?://dblp\.org/rec/", "", value).removesuffix(".html")
    if namespace == "europe_pmc":
        source, separator, identifier = value.partition(":")
        return f"{source.upper()}:{identifier}" if separator and source and identifier else None
    if namespace == "wos":
        return value.upper() if re.fullmatch(r"WOS:[0-9]+", value, re.I) else None
    return value.upper() if namespace == "pmcid" else value


def strong_identifiers(external_ids: Any, related_dois=()) -> frozenset[tuple[str, str]]:
    values = external_ids.model_dump(exclude_none=True) if hasattr(external_ids, "model_dump") else external_ids
    identities = {(namespace, normalized) for namespace, value in (values or {}).items()
                  if (normalized := normalize_external_id(namespace, value)) is not None}
    identities.update(("doi", doi) for value in related_dois if (doi := valid_doi(value)))
    return frozenset(identities)


def paper_identifiers(paper: Any) -> frozenset[tuple[str, str]]:
    identities = set(strong_identifiers(paper.external_ids, paper.related_dois))
    for alias in getattr(paper, "identity_aliases", ()):
        if value := normalize_external_id(alias.provider, alias.record_id):
            identities.add((alias.provider, value))
    return frozenset(identities)
