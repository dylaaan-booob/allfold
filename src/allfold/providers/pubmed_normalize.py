"""PubMed XML identity and publication metadata, without network or persistence."""
from __future__ import annotations

import calendar
import re
import xml.etree.ElementTree as ET
from datetime import datetime

from allfold.identifiers import valid_doi
from allfold.config import JournalConfig, normalize_journal_issn
from allfold.models import (
    Author, EvidenceDate, EvidenceDateKind, ExternalIds, MetadataSource, ProviderWorkEvidence,
)


def text(node: ET.Element | None) -> str:
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def identity(article: ET.Element) -> tuple[str, frozenset[str]]:
    pmid = text(article.find("./MedlineCitation/PMID"))
    primary = article.findall('./PubmedData/ArticleIdList/ArticleId[@IdType="doi"]')
    fallback = article.findall('./MedlineCitation/Article/ELocationID[@EIdType="doi"]')
    primary_dois = {doi for item in primary if (doi := valid_doi(text(item)))}
    fallback_dois = {doi for item in fallback if item.get("ValidYN") != "N" and (doi := valid_doi(text(item)))}
    # A second valid DOI is an identity conflict even when the preferred source exists.
    return pmid, frozenset(primary_dois | fallback_dois)


def match_journal(article: ET.Element, journals: tuple[JournalConfig, ...]) -> JournalConfig | None:
    nodes = article.findall("./MedlineCitation/Article/Journal/ISSN")
    nodes += article.findall("./MedlineCitation/MedlineJournalInfo/ISSNLinking")
    identifiers = set()
    for node in nodes:
        try:
            identifiers.add(normalize_journal_issn(text(node)))
        except ValueError:
            pass
    matches = [journal for journal in journals if identifiers.intersection(journal.identifiers)]
    return matches[0] if len(matches) == 1 else None


def _date(node: ET.Element | None) -> EvidenceDate | None:
    if node is None:
        return None
    year = text(node.find("Year"))
    month = text(node.find("Month"))
    day = text(node.find("Day"))
    if not year:
        raw = text(node.find("MedlineDate"))
        years = set(re.findall(r"\b[12][0-9]{3}\b", raw))
        if len(years) != 1:
            return None
        year = next(iter(years))
        if re.match(r"^\d{4}\s*[-/]\s*\d{2}(?:\b|$)", raw):
            return None  # A shortened second year is still a year range.
        if not raw.startswith(year):
            return EvidenceDate(kind=EvidenceDateKind.PUBLISHED, year=int(year))
        # Only an unambiguous single month/day can refine a textual date.
        tail = raw[4:].strip()
        match = re.fullmatch(r"([A-Za-z]+|[0-9]{1,2})(?:\s+([0-9]{1,2}))?", tail)
        month, day = (match[1], match[2] or "") if match else ("", "")
    months = {name.casefold(): index for index, name in enumerate(calendar.month_abbr) if name}
    months.update({name.casefold(): index for index, name in enumerate(calendar.month_name) if name})
    if month and not month.isdecimal():
        month = str(months.get(month.casefold(), ""))
        day = day if month else ""
    try:
        return EvidenceDate(kind=EvidenceDateKind.PUBLISHED, year=int(year),
                            month=int(month) if month else None, day=int(day) if day and month else None)
    except ValueError:
        return None


def publication_date(article: ET.Element) -> EvidenceDate | None:
    node = article.find("./MedlineCitation/Article")
    if node is None:
        return None
    printed = _date(node.find("./Journal/JournalIssue/PubDate"))
    electronic = next((value for item in node.findall('ArticleDate[@DateType="Electronic"]')
                       if (value := _date(item)) is not None), None)
    if node.get("PubModel") in {"Electronic", "Electronic-Print", "Electronic-eCollection"}:
        preferred = electronic or printed
    else:
        preferred = printed or electronic
    if preferred is not None:
        return preferred
    history = article.findall("./PubmedData/History/PubMedPubDate")
    for status in ("epublish", "ppublish"):
        for item in history:
            if item.get("PubStatus") == status and (value := _date(item)) is not None:
                return value
    return None


def normalize_article(article: ET.Element, *, pmid: str, doi: str, journal: JournalConfig,
                      retrieved_at: datetime) -> ProviderWorkEvidence:
    node = article.find("./MedlineCitation/Article")
    authors = []
    for item in node.findall("./AuthorList/Author") if node is not None else ():
        name = text(item.find("CollectiveName"))
        if not name:
            given = text(item.find("ForeName")) or text(item.find("Initials"))
            name = " ".join(part for part in (given, text(item.find("LastName")), text(item.find("Suffix"))) if part)
        if name:
            authors.append(Author(name=name))
    abstracts = []
    for item in node.findall("./Abstract/AbstractText") if node is not None else ():
        content = text(item)
        label = item.get("Label") or item.get("NlmCategory")
        if content:
            abstracts.append(f"{label}: {content}" if label and label != "UNASSIGNED" else content)
    keywords = tuple(dict.fromkeys(text(item) for item in article.findall("./MedlineCitation/KeywordList/Keyword") if text(item)))
    selected_date = publication_date(article)
    return ProviderWorkEvidence(
        provenance=MetadataSource(provider="pubmed", record_id=pmid, retrieved_at=retrieved_at),
        title=text(node.find("ArticleTitle")) or None if node is not None else None,
        journal=journal.name, abstract="\n\n".join(abstracts) or None, authors=tuple(authors),
        author_keywords=keywords, external_ids=ExternalIds(doi=doi, pubmed=pmid),
        dates=(selected_date,) if selected_date else (), monitor_journal_issns=(journal.key,),
    )
