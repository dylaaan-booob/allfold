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
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE).strip()
    if not doi:
        return None
    return doi.casefold()


def valid_doi(value: str | None) -> str | None:
    doi = normalize_doi(value)
    return doi if doi and re.fullmatch(r"10\.\d{4,9}/[^\s]+", doi) else None



RELIABLE_NAMESPACES = frozenset({"doi", "openalex", "arxiv", "dblp", "europe_pmc", "pmid", "pmcid", "wos", "biorxiv", "medrxiv"})


def normalize_external_id(namespace: str, value: Any) -> str | None:
    """Normalize only explicit strong identifiers; unknown namespaces are descriptive."""
    if namespace not in RELIABLE_NAMESPACES or not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if namespace in {"doi", "biorxiv", "medrxiv"}:
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
        return f"{source.upper()}:{identifier}" if separator and source.isalnum() and identifier.isalnum() else None
    if namespace == "wos":
        return value.upper() if re.fullmatch(r"WOS:[0-9]+", value, re.I) else None
    if namespace == "pmid":
        value = re.sub(r"^https?://(?:pubmed\.ncbi\.nlm\.nih\.gov/|(?:www\.)?ncbi\.nlm\.nih\.gov/pubmed/)", "", value, flags=re.I).rstrip("/")
        return value if re.fullmatch(r"[0-9]+", value) else None
    if namespace == "pmcid":
        value, is_uri = re.subn(r"^https?://(?:(?:www\.)?ncbi\.nlm\.nih\.gov/pmc/articles/|pmc\.ncbi\.nlm\.nih\.gov/articles/)", "", value, flags=re.I)
        value = value.rstrip('/').upper()
        if is_uri and value.isascii() and value.isdigit():
            value = 'PMC' + value
        return value if re.fullmatch(r"PMC[0-9]+", value) else None
    return value


def strong_identifiers(external_ids: Any, related_dois=()) -> frozenset[tuple[str, str]]:
    values = external_ids.model_dump(exclude_none=True) if hasattr(external_ids, "model_dump") else external_ids
    identities = {(namespace, normalized) for namespace, value in (values or {}).items()
                  if (normalized := normalize_external_id(namespace, value)) is not None}
    identities.update(("doi", doi) for value in related_dois if (doi := valid_doi(value)))
    for namespace, value in tuple(identities):
        if namespace == "doi" and value.startswith("10.48550/arxiv."):
            if arxiv := normalize_external_id("arxiv", value.removeprefix("10.48550/arxiv.")):
                identities.add(("arxiv", arxiv))
    return frozenset(identities)


def paper_identifiers(paper: Any) -> frozenset[tuple[str, str]]:
    identities = set(strong_identifiers(paper.external_ids, paper.related_dois))
    for alias in getattr(paper, "identity_aliases", ()):
        identities.update(strong_identifiers({alias.provider: alias.record_id}))
    return frozenset(identities)


def evidence_identifiers(record: Any) -> frozenset[tuple[str, str]]:
    identities = set(strong_identifiers(record.external_ids, record.related_dois))
    for reference in record.related_ids:
        identities.update(strong_identifiers({reference.provider: reference.record_id}))
    return frozenset(identities)


def supported_preprint_uri(value: Any) -> tuple[str, str] | None:
    """Interpret only anchored official preprint locations; never fetch a URI."""
    from urllib.parse import urlsplit
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (url.scheme not in {'http', 'https'} or url.username or url.password or url.query or url.fragment
                or url.port not in {None, 80 if url.scheme == 'http' else 443}):
            return None
    except ValueError:
        return None
    if url.hostname in {'arxiv.org', 'www.arxiv.org', 'export.arxiv.org'}:
        matched = re.fullmatch(r'/(?:abs|pdf)/(.+?)(?:\.pdf)?', url.path)
        if matched and (identifier := normalize_external_id('arxiv', matched[1])):
            return 'arxiv', identifier
    for platform in ('biorxiv', 'medrxiv'):
        if url.hostname in {platform + '.org', 'www.' + platform + '.org'}:
            matched = re.fullmatch(r'/content/(10\.1101/[A-Za-z0-9./-]+?)(?:v[0-9]+)?(?:\.full(?:\.pdf)?)?', url.path)
            if matched and (doi := valid_doi(matched[1])):
                return platform, doi
    return None
