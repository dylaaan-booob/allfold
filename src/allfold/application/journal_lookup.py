"""Journal lookup and verification, using local Registry results before OpenAlex."""
from contextlib import nullcontext
from pathlib import Path
import os
import unicodedata

from allfold.config import ConfigurationError, JournalConfig, normalize_journal_issn
from allfold.persistence.journal_registry import local_candidates


def normalized_title(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def search_journals(list_path: Path, query: str, *, client=None, limit: int | None = 50) -> list[dict]:
    query = query.strip()
    if not query:
        return []
    local = local_candidates(list_path, query)
    if local:
        return local[:limit] if limit is not None else local
    from allfold.providers.openalex import OpenAlexClient, OpenAlexNotFoundError
    try:
        identifier = normalize_journal_issn(query)
    except ValueError:
        identifier = None
    with (nullcontext(client) if client is not None else
          OpenAlexClient(api_key=os.environ.get("OPENALEX_API_KEY"))) as provider:
        try:
            payloads = ([provider.get_source_by_issn(identifier)] if identifier else
                        provider.search_sources(query).get("results", []))
        except OpenAlexNotFoundError:
            return []
    results = []
    for payload in payloads:
        if payload.get("type") != "journal" or not payload.get("display_name"):
            continue
        identifiers = []
        for value in payload.get("issn") or []:
            try:
                identifiers.append(normalize_journal_issn(value))
            except (ValueError, AttributeError):
                continue
        try:
            selected = normalize_journal_issn(identifier or payload.get("issn_l") or "")
        except ValueError:
            selected = identifiers[0] if len(identifiers) == 1 else None
        if selected not in identifiers:
            continue
        # OpenAlex does not classify print/electronic media. Keep one generic ISSN.
        results.append(dict(name=payload["display_name"], issn=selected, eissn=None,
                            publisher=payload.get("host_organization_name"), sources=[], origin="openalex", identifiers=identifiers))
    return results


def verify_journal(list_path: Path, journal: JournalConfig, *, client=None) -> JournalConfig:
    candidates = search_journals(list_path, journal.key, client=client)
    matches = [c for c in candidates if set(journal.identifiers).issubset(c.get("identifiers") or {c["issn"], c["eissn"]})]
    if len(matches) != 1:
        raise ConfigurationError(f"Journal {journal.key}: select a matching ISSN/eISSN candidate",
                                 field="journals")
    candidate = matches[0]
    titles = [candidate["name"], *(s["title"] for s in candidate["sources"])]
    def normalize_title(value):
        return " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if normalize_title(journal.name) not in {normalize_title(title) for title in titles}:
        raise ConfigurationError(f"Journal {journal.key}: name differs from source titles for selected ISSN/eISSN candidate",
                                 field="journals")
    # Source titles may differ. Preserve a verified title rather than silently
    # renaming a selected/imported Journal to another source's preferred title.
    return journal


def journal_metadata(list_path: Path, journals) -> dict[str, dict]:
    metadata = {}
    for journal in journals:
        rows = local_candidates(list_path, journal.key)
        if not rows:
            from allfold.providers.openalex import OpenAlexError
            try:
                rows = search_journals(list_path, journal.key)
            except OpenAlexError as error:
                raise ConfigurationError(f"Journal {journal.key}: metadata unavailable: {error}",
                                         field="journal_registry") from error
        selected = next((r for r in rows if (r["issn"], r["eissn"]) == (journal.issn, journal.eissn)), None)
        if selected is None:
            compatible = [row for row in rows if set(journal.identifiers).issubset({row['issn'], row['eissn']})]
            if len(compatible) == 1:
                selected = compatible[0]
        metadata[journal.key] = selected or dict(publisher=None, sources=[])
    return metadata
