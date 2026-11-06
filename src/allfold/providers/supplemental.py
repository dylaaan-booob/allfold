"""Original-API metadata lookups for known identifiers; never discovery."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import quote
from xml.etree import ElementTree

from allfold.identifiers import normalize_external_id, valid_doi
from allfold.models import Author, EvidenceDate, EvidenceDateKind, ExternalIds, MetadataSource, ProviderRecordRef, ProviderTopic, ProviderWorkEvidence
from allfold.providers.crossref import normalize_crossref_discovered_work
from allfold.paper_dates import date_value as _date_string, source_date as _iso_date
from allfold.providers.integrated import DiscoveryClient, DiscoveryError, IdentityMismatch


SAME_WORK_RELATIONS = frozenset({"is-preprint-of", "has-preprint", "is-version-of", "has-version", "is-identical-to"})


def _first(values):
    return next((value.strip() for value in values if isinstance(value, str) and value.strip()), None) if isinstance(values, list) else None


def _date(parts, kind):
    if not isinstance(parts, (list, tuple)) or not 1 <= len(parts) <= 3:
        return None
    try:
        return EvidenceDate(kind=kind, year=parts[0], month=parts[1] if len(parts) > 1 else None,
                            day=parts[2] if len(parts) > 2 else None)
    except ValueError:
        return None




class SupplementalClient(DiscoveryClient):
    """Share discovery's selected-provider HTTP pacing, proxy, retry and cancel."""
    def __init__(self, provider, *, mailto="", **kwargs):
        if provider == "arxiv":
            kwargs.setdefault("interval", 3.0)
        super().__init__(provider, **kwargs)
        self.mailto = mailto
        self._details_cache = {}

    def lookup(self, namespace, identifier):
        if self.provider == "crossref" and namespace == "doi":
            return self._crossref(identifier)
        if self.provider == "arxiv" and namespace == "arxiv":
            return self._arxiv(identifier)
        if self.provider in {"biorxiv", "medrxiv"} and namespace == "doi":
            return self._biorxiv(identifier)
        return ()

    def _arxiv(self, identifier):
        identifier = normalize_external_id("arxiv", identifier)
        if not identifier:
            raise DiscoveryError("arXiv lookup requires a known arXiv ID")
        content = self.request("/api/query", {"id_list": identifier, "max_results": 1}, response_format="xml")
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            raise DiscoveryError("arXiv returned invalid Atom metadata") from None
        if root.tag != "{http://www.w3.org/2005/Atom}feed":
            raise DiscoveryError("arXiv response is not an Atom feed")
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        records = []
        for entry in root.findall("a:entry", ns):
            url = entry.findtext("a:id", "", ns)
            if normalize_external_id("arxiv", url) != identifier:
                raise IdentityMismatch("arXiv response does not match requested identity")
            published = _iso_date(entry.findtext("a:published", "", ns)[:10], EvidenceDateKind.PREPRINT)
            if published:
                published = published.model_copy(update={"first_version": True, "version": "v1", "publication_type": "preprint"})
            doi = valid_doi(entry.findtext("arxiv:doi", None, ns))
            version = re.search(r"v\d+$", url)
            records.append(ProviderWorkEvidence(
                provenance=MetadataSource(provider="arxiv", record_id=identifier,
                    retrieved_at=datetime.now(timezone.utc), role="supplement", url=url,
                    version=version.group(0) if version else None),
                external_ids=ExternalIds(arxiv=identifier), related_dois=(doi,) if doi else (),
                title=" ".join(entry.findtext("a:title", "", ns).split()) or None,
                abstract=" ".join(entry.findtext("a:summary", "", ns).split()) or None,
                authors=tuple(Author(name=name) for item in entry.findall("a:author", ns)
                              if (name := item.findtext("a:name", "", ns).strip())),
                publication_type="preprint", publication_date=_date_string(published) if published else None,
                dates=(published,) if published else (),
                indexed_terms=tuple(ProviderTopic(value=item.attrib["term"], source="arxiv", kind="category")
                                    for item in entry.findall("a:category", ns) if item.attrib.get("term")),
            ))
        return tuple(records)

    def _collection(self, path):
        data = self.request(path, {})
        messages = data.get("messages", [])
        if any(str(item.get("status", "")).casefold() not in {"ok", "no posts found", "no results found"}
               for item in messages if isinstance(item, dict)):
            raise DiscoveryError(f"{self.provider}: identifier lookup failed")
        rows = data.get("collection")
        if rows is None and any("no " in str(item.get("status", "")).casefold()
                                for item in messages if isinstance(item, dict)):
            return []
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DiscoveryError(f"{self.provider}: invalid identifier metadata collection")
        return rows

    def _bio_record(self, row, doi):
        if valid_doi(row.get("doi")) != doi:
            raise IdentityMismatch(f"{self.provider}: response DOI does not match requested identity")
        if row.get("server") and str(row["server"]).casefold() != self.provider:
            raise DiscoveryError(f"{self.provider}: response came from a different preprint server")
        published = valid_doi(row.get("published"))
        posted = _iso_date(row.get("date"), EvidenceDateKind.PREPRINT)
        if posted:
            posted = posted.model_copy(update={"first_version": str(row.get("version")) == "1", "publication_type": "preprint"})
        version = str(row.get("version", "")).strip() or None
        return ProviderWorkEvidence(
            provenance=MetadataSource(provider=self.provider, record_id=doi + (":" + version if version else ""),
                retrieved_at=datetime.now(timezone.utc), role="supplement", version=version,
                url=f"https://api.biorxiv.org/details/{self.provider}/{quote(doi, safe='/')}/na/json"),
            external_ids=ExternalIds(doi=doi), related_dois=(published,) if published else (),
            title=row.get("title") or None, abstract=row.get("abstract") or None,
            authors=tuple(Author(name=name.strip()) for name in str(row.get("authors") or "").split(";") if name.strip()),
            publication_type="preprint", publication_date=_date_string(posted) if posted else None,
            dates=(posted,) if posted else (),
            indexed_terms=(ProviderTopic(value=row["category"], source=self.provider, kind="category"),) if row.get("category") else (),
        )

    def _bio_details(self, doi):
        # This client lives for one operation, including all selected Papers.
        # Embedded publication lookups and direct preprint lookups share results.
        if doi not in self._details_cache:
            try:
                self._details_cache[doi] = tuple(self._bio_record(row, doi) for row in
                    self._collection(f"/details/{self.provider}/{quote(doi, safe='/')}/na/json"))
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                self._details_cache[doi] = error
        result = self._details_cache[doi]
        if isinstance(result, Exception):
            raise result
        return result

    def _biorxiv(self, identifier):
        doi = valid_doi(identifier)
        if not doi:
            raise DiscoveryError(f"{self.provider}: lookup requires a valid DOI")
        encoded = quote(doi, safe="/")
        if doi.startswith("10.1101/"):
            return self._bio_details(doi)
        rows = self._collection(f"/pubs/{self.provider}/{encoded}/na/json")
        records, seen = [], set()
        for row in rows:
            preprint = valid_doi(row.get("preprint_doi") or row.get("biorxiv_doi"))
            formal = valid_doi(row.get("published_doi"))
            if not preprint or formal != doi:
                raise IdentityMismatch(f"{self.provider}: publication relation does not match requested DOI")
            platform = str(row.get("preprint_platform", "")).casefold()
            if platform and platform != self.provider:
                raise DiscoveryError(f"{self.provider}: relation names another preprint server")
            if preprint in seen:
                continue
            seen.add(preprint)
            online = _iso_date(row.get("published_date"), EvidenceDateKind.PUBLISHED_ONLINE)
            records.append(ProviderWorkEvidence(
                provenance=MetadataSource(provider=self.provider, record_id=preprint + ":publication",
                    retrieved_at=datetime.now(timezone.utc), role="supplement",
                    url=f"https://api.biorxiv.org/pubs/{self.provider}/{encoded}/na/json"),
                external_ids=ExternalIds(doi=doi), related_dois=(preprint,),
                related_ids=(ProviderRecordRef(provider=self.provider, record_id=preprint, relation='preprint'),),
                journal=row.get("published_journal") or None, publication_type="journal",
                publication_date=_date_string(online) if online else None,
                dates=(online,) if online else (),
            ))
            records.extend(self._bio_details(preprint))
        return tuple(records)

    def _crossref(self, identifier):
        doi = valid_doi(identifier)
        if not doi:
            raise DiscoveryError("Crossref lookup requires a valid DOI")
        data = self.request("/works/" + quote(doi, safe="/"), {"mailto": self.mailto} if self.mailto else {})
        raw = data.get("message")
        if not isinstance(raw, dict) or valid_doi(raw.get("DOI")) != doi:
            raise IdentityMismatch("Crossref response DOI does not match requested identity")
        item, _ = normalize_crossref_discovered_work(raw, datetime.now(timezone.utc))
        record = item.to_evidence()
        preprint = raw.get("type") == "posted-content"
        conference = raw.get("type") == "proceedings-article"
        publication_type = ('preprint' if preprint else 'conference' if conference else
                            'journal' if raw.get('type') == 'journal-article' else None)
        dates = list(record.dates)
        for name, kind in (("accepted", EvidenceDateKind.ACCEPTED), ("posted", EvidenceDateKind.PREPRINT)):
            if name == "accepted" and preprint:
                continue  # A platform's acceptance of posted content is not journal acceptance.
            container = raw.get(name) or {}
            parts = container.get("date-parts", []) if isinstance(container, dict) else []
            if parts and (value := _date(parts[0], kind)):
                dates.append(value.model_copy(update={"publication_type": publication_type,
                    "first_version": preprint and kind == EvidenceDateKind.PREPRINT and str(raw.get("version")) in {"1", "v1"}}))
        related, refs = set(), set()
        relations = raw.get("relation") or {}
        for kind in SAME_WORK_RELATIONS:
            for relation in relations.get(kind, []) if isinstance(relations, dict) else ():
                if relation.get("id-type") == "doi" and (value := valid_doi(relation.get("id"))):
                    related.add(value)
                    if kind == 'has-preprint':
                        refs.add(ProviderRecordRef(provider='doi', record_id=value, relation='preprint'))
        source = MetadataSource(provider="crossref", record_id=doi, retrieved_at=datetime.now(timezone.utc),
                                role="supplement", url="https://api.crossref.org/works/" + quote(doi, safe="/"))
        publication = next((value for kind in (EvidenceDateKind.PUBLISHED_ONLINE, EvidenceDateKind.PUBLISHED_PRINT,
                                               EvidenceDateKind.PUBLISHED, EvidenceDateKind.ISSUED)
                            for value in dates if value.kind == kind), None)
        return (record.model_copy(update={
            "provenance": source, "related_dois": tuple(sorted(related - {doi})), "dates": tuple(dates),
            "related_ids": tuple(sorted(refs, key=lambda ref: (ref.provider, ref.record_id))),
            "publication_type": publication_type,
            "journal": None if preprint or conference else _first(raw.get("container-title")),
            "conference": (raw.get("event") or {}).get("name") if conference else None,
            "publication_date": _date_string(publication) if publication else None,
        }),)
