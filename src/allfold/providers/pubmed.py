"""Native PubMed query compilation and serial E-utilities discovery."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import time
import xml.etree.ElementTree as ET

import httpx

from allfold.config import JournalConfig, normalize_journal_issn
from allfold.coverage import CoverageComponent, CoverageStatus, CoverageUnit
from allfold.http_client import create_http_client
from allfold.models import ProviderWorkEvidence
from allfold.progress import ActivityKind, ActivityUpdate, ProgressEvent
from allfold.providers.pubmed_normalize import identity, match_journal, normalize_article, text


class PubMedQueryError(ValueError):
    def __init__(self, message: str, position: int = 0):
        self.position = position
        super().__init__(f"{message} at column {position + 1}")


def compile_pubmed_query(mode: str, query) -> str:
    from allfold.keywords import parse_keyword_expression, compile_native_expression
    try:
        expression = parse_keyword_expression(query) if isinstance(query, str) else query
        return compile_native_expression(expression, provider="pubmed", mode=mode)
    except ValueError as error:
        raise PubMedQueryError(str(error), getattr(error, "position", 0)) from error


def combined_query(compiled: str, journals, from_date: date, to_date: date) -> str:
    identifiers = sorted({identifier for journal in journals for identifier in journal.identifiers})
    if not identifiers:
        raise PubMedQueryError("No configured Journals")
    venues = " OR ".join(f"{identifier}[ta]" for identifier in identifiers)
    return f"({compiled}) AND ({venues}) AND ({from_date:%Y/%m/%d}:{to_date:%Y/%m/%d}[dp])"


class PubMedError(ValueError):
    pass


@dataclass(frozen=True)
class PubMedIssue:
    stage: str
    message: str
    severity: str = "warning"
    record_id: str | None = None
    phrase: str | None = None
    issn: str | None = None


@dataclass(frozen=True)
class PubMedDiscovery:
    records: tuple[ProviderWorkEvidence, ...]
    issues: tuple[PubMedIssue, ...]
    coverage: tuple[CoverageUnit, ...]
    search_total: int
    fetched_records: int
    failed_batches: int
    skipped: dict[str, int]


class PubMedClient:
    def __init__(self, *, api_key=None, transport=None, sleep=time.sleep, monotonic=time.monotonic,
                 progress_callback=None):
        self._key = api_key
        self._sleep, self._clock = sleep, monotonic
        self._interval = .11 if api_key else .34
        self._last_request = None
        self._progress = progress_callback
        self._http = create_http_client(timeout=30, transport=transport)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._http.close()

    def activity(self, label, *, kind=ActivityKind.WORKING, current=None, total=None):
        if self._progress:
            self._progress(ProgressEvent(activity=ActivityUpdate(kind=kind, operation="pubmed_discovery",
                label=label, source="pubmed", current=current, total=total, unit="work")))

    def safe_message(self, value):
        return value.replace(self._key, "[redacted]") if self._key else value

    def request(self, utility, **params):
        params.update(db="pubmed", retmode="xml", tool="allfold")
        if self._key:
            params["api_key"] = self._key
        for attempt in range(3):
            if self._last_request is not None:
                wait = self._interval - (self._clock() - self._last_request)
                if wait > 0:
                    self._sleep(wait)
            self._last_request = self._clock()
            retry_after = 0
            try:
                response = self._http.post(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/{utility}.fcgi", data=params)
                if response.status_code == 200:
                    return response.content
                retry = response.status_code == 429 or 500 <= response.status_code < 600
                message = f"PubMed {utility}: HTTP {response.status_code}"
                header = response.headers.get("Retry-After", "")
                if retry and header:
                    try:
                        retry_after = max(0, float(header))
                    except ValueError:
                        try:
                            retry_after = max(0, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
                        except (ValueError, TypeError, OverflowError):
                            pass
            except httpx.TransportError:
                retry, message = True, f"PubMed {utility}: network request failed"
            if not retry or attempt == 2:
                # Do not include request bodies, raw HTTP errors or echoed API keys.
                raise PubMedError(message)
            self.activity(f"Retrying {utility} ({attempt + 1}/2)", kind=ActivityKind.RETRYING)
            self._sleep(max(retry_after, 2 ** attempt))


def discover_pubmed(client: PubMedClient, journals: tuple[JournalConfig, ...], compiled: str,
                    from_date: date, to_date: date, *, can_create) -> PubMedDiscovery:
    issues, articles = [], []
    pending = [(combined_query(compiled, journals, from_date, to_date), None)]
    search_total = fetched = failed_batches = 0
    successful_search = False
    incomplete = False
    expected_pmids = set()
    phrases_not_found = set()
    retrieved_at = datetime.now(timezone.utc)
    while pending:
        query, parent_count = pending.pop()
        try:
            client.activity("Searching PubMed")
            root = ET.fromstring(client.request("esearch", term=query, usehistory="y", retmax=9999))
            search_diagnostics = root.findall(".//ErrorList/*")
            # ESearch can return valid results and History alongside PhraseNotFound.
            phrases_not_found.update(text(item) for item in search_diagnostics if item.tag == "PhraseNotFound")
            errors = root.findall(".//ERROR") + [item for item in search_diagnostics if item.tag != "PhraseNotFound"]
            if root.tag != "eSearchResult" or errors:
                raise PubMedError(client.safe_message("; ".join(text(item) for item in errors) or "Invalid PubMed ESearch response"))
            count = int(root.findtext("Count", "-1"))
            ids = [text(item) for item in root.findall("./IdList/Id")]
            if count < 0 or any(not item.isdecimal() for item in ids):
                raise PubMedError("Invalid PubMed ESearch count or PMID")
            for item in root.findall("./WarningList/*"):
                issues.append(PubMedIssue("search_warning", client.safe_message(text(item))))
            if parent_count is None:
                search_total = count
            if parent_count is not None and count >= parent_count:
                raise PubMedError("PubMed range split did not reduce the result set; coverage is incomplete")
            successful_search = True
            # PubMed currently clamps retmax=10000 to 9999 (ESearch warning).
            if count >= 10000:
                numbers = sorted({int(item) for item in ids})
                if len(numbers) < 2:
                    raise PubMedError("Cannot split PubMed results above 10,000; no usable PMID sample")
                pivot = numbers[(len(numbers) - 1) // 2]
                pending.append((f"({query}) NOT (1:{pivot}[uid])", count))
                pending.append((f"({query}) AND (1:{pivot}[uid])", count))
                continue
            expected = set(ids)
            if len(expected) != count:
                raise PubMedError("PubMed ESearch returned an incomplete PMID list")
            expected_pmids.update(expected)
            if not count:
                continue
            webenv, key = root.findtext("WebEnv"), root.findtext("QueryKey")
            if not webenv or not key:
                raise PubMedError("PubMed ESearch omitted History Server identity")
            returned = set()
            for start in range(0, count, 200):
                try:
                    client.activity(f"Fetching PubMed {start + 1}–{min(start + 200, count)}", current=start, total=count)
                    payload = client.request("efetch", WebEnv=webenv, query_key=key, retstart=start, retmax=200)
                    parser = ET.XMLPullParser(events=("end",))
                    parse_error = None
                    try:
                        parser.feed(payload)
                        parser.close()
                    except ET.ParseError:
                        parse_error = "Malformed or truncated PubMed XML batch"
                    batch = []
                    try:
                        for _, item in parser.read_events():
                            if item.tag == "PubmedArticle":
                                batch.append(item)
                    except ET.ParseError:
                        parse_error = "Malformed or truncated PubMed XML batch"
                    for article in batch:
                        pmid, _ = identity(article)
                        if pmid not in expected:
                            parse_error = "PubMed EFetch returned an unexpected or missing PMID"
                            continue
                        returned.add(pmid)
                        articles.append(article)
                        fetched += 1
                    if len(batch) < min(200, count - start):
                        parse_error = parse_error or "PubMed EFetch returned a short batch"
                    if parse_error:
                        raise PubMedError(parse_error)
                except PubMedError as error:
                    incomplete = True
                    failed_batches += 1
                    issues.append(PubMedIssue("fetch", str(error), "error"))
            missing = expected - returned
            if missing:
                incomplete = True
                issues.append(PubMedIssue("missing_records", f"PubMed EFetch omitted {len(missing)} of {count} expected PMIDs", "error"))
        except (PubMedError, ET.ParseError, ValueError) as error:
            incomplete = True
            issues.append(PubMedIssue("search", client.safe_message(str(error)), "error"))

    for phrase in sorted(phrases_not_found):
        safe_phrase = client.safe_message(phrase)
        try:
            identifier = normalize_journal_issn(phrase)
        except ValueError:
            identifier = None
        if not any(identifier in journal.identifiers for journal in journals):
            identifier = None
        issues.append(PubMedIssue("phrase_not_found",
            "PubMed ESearch PhraseNotFound: " + safe_phrase, phrase=safe_phrase, issn=identifier))

    if not incomplete and len(expected_pmids) != search_total:
        incomplete = True
        issues.append(PubMedIssue("search_count_changed",
            "PubMed result count changed across range queries; coverage is incomplete", "error"))

    # Finish all discovery before materialization, so late identity conflicts block writes.
    by_pmid = defaultdict(set)
    for article in articles:
        pmid, dois = identity(article)
        by_pmid[pmid].update(dois)
    conflicts = {pmid for pmid, dois in by_pmid.items() if len(dois) > 1}
    for pmid in sorted(conflicts):
        issues.append(PubMedIssue("doi_conflict", "Conflicting DOI values for one PubMed PMID; no Paper created", "error", pmid))
    records, skipped = [], Counter()
    for article in articles:
        pmid, dois = identity(article)
        if pmid in conflicts:
            continue
        if not dois:
            skipped["missing_doi"] += 1
            continue
        doi = next(iter(dois))
        if not can_create(doi):
            skipped["existing_or_blocked_doi"] += 1
            continue
        journal = match_journal(article, journals)
        if journal is None:
            skipped["unmapped_or_ambiguous_journal"] += 1
            continue
        evidence = normalize_article(article, pmid=pmid, doi=doi, journal=journal, retrieved_at=retrieved_at)
        if not evidence.title:
            skipped["missing_title"] += 1
            continue
        records.append(evidence)
    for reason, count in sorted(skipped.items()):
        issues.append(PubMedIssue("skipped", f"PubMed skipped {count} records: {reason}"))
    status = CoverageStatus.PARTIAL if incomplete and successful_search else CoverageStatus.FAILED if incomplete else CoverageStatus.COMPLETE
    return PubMedDiscovery(tuple(records), tuple(issues),
        (CoverageUnit("pubmed", CoverageComponent.PUBMED_DISCOVERY, status),), search_total, fetched,
        failed_batches, dict(skipped))
