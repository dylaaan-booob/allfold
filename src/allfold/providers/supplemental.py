"""Original-API metadata lookups for known identifiers; never discovery."""
from __future__ import annotations

from datetime import datetime, timezone
import re
from urllib.parse import quote, urlencode
from xml.etree import ElementTree

from allfold.identifiers import normalize_external_id, valid_doi, supported_preprint_uri
from allfold.models import Author, EvidenceDate, EvidenceDateKind, ExternalIds, MetadataSource, ProviderRecordRef, ProviderTopic, ProviderWorkEvidence
from allfold.providers.crossref import normalize_crossref_discovered_work
from allfold.paper_dates import date_value as _date_string, source_date as _iso_date
from allfold.providers.integrated import DiscoveryClient, DiscoveryError, IdentityMismatch, ProviderHTTPError


SAME_WORK_RELATIONS = frozenset({"is-preprint-of", "has-preprint", "is-version-of", "has-version", "is-identical-to"})


class PartialLookup(DiscoveryError):
    """A failed page must not discard verified facts from earlier pages."""
    def __init__(self, message, records=()):
        super().__init__(message)
        self.records = tuple(records)


def _first(values):
    return next((value.strip() for value in values if isinstance(value, str) and value.strip()), None) if isinstance(values, list) else None


def _native_doi_path(doi):
    """Keep the registrant separator; native routes need suffix slashes twice escaped."""
    prefix, suffix = doi.split('/', 1)
    return quote(prefix, safe='') + '/' + quote(suffix, safe='').replace('%2F', '%252F')


def _date(parts, kind):
    if not isinstance(parts, (list, tuple)) or not 1 <= len(parts) <= 3:
        return None
    try:
        return EvidenceDate(kind=kind, year=parts[0], month=parts[1] if len(parts) > 1 else None,
                            day=parts[2] if len(parts) > 2 else None)
    except ValueError:
        return None


def _assertion_date(value, kind, **fields):
    """Crossmark dates are literal history values, never free-text extraction."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if date := _iso_date(value, kind, **fields):
        return date
    for pattern in ('%d %B %Y', '%d %b %Y', '%B %d, %Y', '%b %d, %Y', '%B %Y', '%b %Y'):
        try:
            parsed = datetime.strptime(value, pattern)
            return _iso_date(parsed.strftime('%Y-%m' if '%d' not in pattern else '%Y-%m-%d'), kind, **fields)
        except ValueError:
            continue
    return None


def _history_assertions(raw, publication_type):
    for assertion in raw.get('assertion') or ():
        if not isinstance(assertion, dict):
            continue
        # Exact event names prevent deposit/registration/indexing statements
        # containing "accepted" from being reinterpreted as journal history.
        labels = [str(assertion.get(field) or '').strip() for field in ('name', 'label')]
        event = next((kind for label in labels for kind in (EvidenceDateKind.RECEIVED, EvidenceDateKind.ACCEPTED)
            if re.sub(r'[^a-z]', '', label.casefold()) in {kind.value, kind.value + 'date', 'date' + kind.value}), None)
        if event is None or publication_type == 'preprint':
            continue
        group = assertion.get('group') or {}
        group_name = str(group.get('name') or group.get('label') or '') if isinstance(group, dict) else ''
        if re.search(r'deposit|regist|index|database|license|copyright', ' '.join([group_name, labels[1]]), re.IGNORECASE):
            continue
        label = ':'.join(['assertion', group_name, *labels])
        if date := _assertion_date(assertion.get('value'), event, source_label=label, publication_type=publication_type):
            yield date




class SupplementalClient(DiscoveryClient):
    """Share discovery's selected-provider HTTP pacing, proxy, retry and cancel."""
    def __init__(self, provider, *, mailto="", **kwargs):
        if provider == "arxiv":
            kwargs.setdefault("interval", 3.0)
        super().__init__(provider, **kwargs)
        self.mailto = mailto
        self._details_cache = {}

    def lookup(self, namespace, identifier):
        if self.provider == 'europe_pmc':
            result = self._europe_many(namespace, (identifier,)).get(identifier, ())
            if isinstance(result, Exception):
                raise result
            return result
        if self.provider == "crossref" and namespace == "doi":
            return self._crossref(identifier)
        if self.provider == "arxiv" and namespace == "arxiv":
            return self._arxiv(identifier)
        if self.provider in {"biorxiv", "medrxiv"} and namespace == "doi":
            doi = valid_doi(identifier)
            if not doi:
                raise DiscoveryError(f"{self.provider}: native details require a valid DOI")
            return self._bio_details(doi)
        return ()

    def _arxiv(self, identifier):
        normalized = normalize_external_id('arxiv', identifier)
        if not normalized:
            raise DiscoveryError('arXiv lookup requires a known arXiv ID')
        result = self.lookup_many('arxiv', (normalized,))[normalized]
        if isinstance(result, Exception):
            raise result
        return result

    def lookup_many(self, namespace, identifiers):
        if self.provider == 'crossref' and namespace == 'doi':
            return self._crossref_many(identifiers)
        if self.provider == 'europe_pmc':
            return self._europe_many(namespace, identifiers)
        if self.provider != 'arxiv' or namespace != 'arxiv':
            raise ValueError('Batch lookup requires arXiv identities')
        results, ids = {}, []
        for value in identifiers:
            key = normalize_external_id('arxiv', value)
            if not key:
                results[value] = DiscoveryError('arXiv lookup requires a known arXiv ID')
            elif key not in ids:
                ids.append(key)
        # 200 is a local transport group size, not a result or API ceiling.
        # Draining every group also keeps legacy IDs within a modest URL size.
        for offset in range(0, len(ids), 200):
            group = ids[offset:offset + 200]
            try:
                content = self.request('/api/query', {'id_list': ','.join(group), 'max_results': len(group)}, response_format='xml')
                records, wrong, failures = self._arxiv_feed(content, set(group))
                for key in group:
                    if key in failures:
                        results[key] = failures[key]
                        continue
                    matches = [record for record in records if record.external_ids.arxiv == key]
                    # Repeated identical entries are harmless. Conflicting duplicate
                    # identities cannot be silently selected by response order.
                    unique = {record.model_dump_json(exclude={'provenance': {'retrieved_at'}}): record for record in matches}
                    results[key] = (IdentityMismatch('arXiv returned conflicting duplicate identities') if len(unique) > 1 else
                        tuple(unique.values()) if unique else
                        IdentityMismatch('arXiv response contains an unexpected identity') if wrong else ())
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                for key in group:
                    results[key] = error
        return results

    def _europe_many(self, namespace, identifiers):
        """Formal PMID association batches and exact preprint IDs only."""
        from allfold.providers.integrated import SourceScope
        from allfold.providers.discovery_evidence import normalize_europe_pmc
        requested = []
        for value in dict.fromkeys(identifiers):
            key = normalize_external_id(namespace, value)
            if not key or namespace == 'europe_pmc' and not key.startswith('PPR:'):
                raise DiscoveryError('Europe PMC completion requires a formal PMID or known preprint identity')
            if namespace == 'doi' and any(char in key for char in '\\"'):
                raise DiscoveryError('Invalid DOI in Europe PMC preprint query')
            requested.append(key)
        def query(group):
            if namespace == 'pmid':
                return 'SRC:MED AND HAS_PREPRINT:Y AND (' + ' OR '.join('EXT_ID:' + value for value in group) + ')'
            if namespace == 'europe_pmc':
                return 'SRC:PPR AND (' + ' OR '.join('EXT_ID:' + value.partition(':')[2] for value in group) + ')'
            if namespace == 'doi':
                return 'SRC:PPR AND (' + ' OR '.join('DOI:"' + value + '"' for value in group) + ')'
            raise DiscoveryError('Europe PMC ordinary formal metadata lookup is not a completion path')
        groups, group = [], []
        for key in requested:
            if group and (len(group) >= 100 or len(urlencode({'query': query([*group, key])})) > 6000):
                groups.append(group)
                group = []
            if len(urlencode({'query': query([key])})) > 6000:
                raise DiscoveryError('Europe PMC identity exceeds request URL budget')
            group.append(key)
        if group:
            groups.append(group)
        results = {}
        for group in groups:
            found, seen = {key: [] for key in group}, set()
            try:
                for raw, _, _ in self._europe_pages(query(group)):
                    if raw is None:
                        continue
                    key = (normalize_external_id('doi', raw.get('doi')) if namespace == 'doi' else
                        str(raw.get('id')) if namespace == 'pmid' and raw.get('source') == 'MED' else
                        f"{raw.get('source')}:{raw.get('id')}")
                    if key not in found:
                        raise IdentityMismatch('Europe PMC batch returned an unexpected identity')
                    identity = raw.get('source'), raw.get('id')
                    if identity in seen:
                        raise DiscoveryError('Incomplete: Europe PMC returned a duplicate result identity')
                    seen.add(identity)
                    journal = (raw.get('journalInfo') or {}).get('journal') or {}
                    record = normalize_europe_pmc(raw, SourceScope('journal', journal.get('title') or ''))
                    found[key].append(record)
                results.update((key, tuple(records)) for key, records in found.items())
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                results.update((key, PartialLookup(str(error), records) if records else error) for key, records in found.items())
        return results

    def _doi_groups(self, identifiers, field, extra=()):
        group = []
        for raw in dict.fromkeys(identifiers):
            value = valid_doi(raw)
            if not value or any(char in value for char in ',\\"'):
                raise DiscoveryError('Invalid DOI for exact Crossref filter')
            candidate = [*group, value]
            filters = ','.join([*extra, *(field + ':' + item for item in candidate)])
            if group and (len(candidate) > 100 or len(urlencode({'filter': filters})) > 6000):
                yield group
                group = []
            if len(urlencode({'filter': field + ':' + value})) > 6000:
                raise DiscoveryError('Crossref identity exceeds request URL budget')
            group.append(value)
        if group:
            yield group

    def _crossref_pages(self, filters):
        cursor, cursors, count, total = '*', set(), 0, None
        while True:
            params = {'filter': filters, 'rows': min(self.page_size, 1000), 'cursor': cursor}
            if self.mailto:
                params['mailto'] = self.mailto
            data = self.request('/works', params)
            message = data.get('message')
            if not isinstance(message, dict) or not isinstance(message.get('items'), list):
                raise DiscoveryError('Crossref response is missing work-list items')
            expected = message.get('total-results')
            if type(expected) is not int or expected < 0:
                raise DiscoveryError('Crossref response has invalid total-results')
            if total is not None and expected != total:
                raise DiscoveryError('Incomplete: Crossref result total changed during pagination')
            total = expected
            rows = message['items']
            if count + len(rows) > total:
                raise DiscoveryError('Crossref returned more records than its reported total')
            for raw in rows:
                count += 1
                if not isinstance(raw, dict):
                    raise DiscoveryError('Crossref returned an invalid work item')
                yield raw
            if count >= total:
                return
            next_cursor = message.get('next-cursor')
            if not rows or not isinstance(next_cursor, str) or next_cursor in cursors or next_cursor == cursor:
                raise DiscoveryError('Incomplete: Crossref pagination made no progress')
            cursors.add(cursor)
            cursor = next_cursor

    def _crossref_many(self, identifiers):
        results = {}
        for group in self._doi_groups(identifiers, 'doi'):
            found = {doi: [] for doi in group}
            try:
                for raw in self._crossref_pages(','.join('doi:' + doi for doi in group)):
                    doi = valid_doi(raw.get('DOI'))
                    if doi not in found:
                        raise IdentityMismatch('Crossref batch returned an unexpected DOI')
                    found[doi].extend(self._crossref_record(raw))
                results.update((doi, tuple(records)) for doi, records in found.items())
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                results.update((doi, PartialLookup(str(error), records) if records else error) for doi, records in found.items())
        return results

    def lookup_preprints(self, identifiers):
        """Reverse only explicit is-preprint-of edges, mapped to their target DOI.

        Repeated relation.object filters are OR; relation.type is ANDed. The
        response relation is still checked because filters can match separate
        relation entries in the same work.
        """
        results = {}
        for group in self._doi_groups(identifiers, 'relation.object', ('relation.type:is-preprint-of',)):
            found, seen = {doi: [] for doi in group}, set()
            try:
                filters = ','.join(['relation.type:is-preprint-of', *('relation.object:' + doi for doi in group)])
                for raw in self._crossref_pages(filters):
                    preprint = valid_doi(raw.get('DOI'))
                    if not preprint:
                        raise IdentityMismatch('Crossref reverse relation lacks a valid subject DOI')
                    relation = raw.get('relation') or {}
                    targets = {valid_doi(item.get('id')) for item in relation.get('is-preprint-of', ())
                        if isinstance(item, dict) and item.get('id-type') == 'doi'}
                    targets &= set(group)
                    if not targets:
                        raise IdentityMismatch('Crossref reverse result lacks the requested explicit target relation')
                    records = self._crossref_record(raw)
                    for target in sorted(targets):
                        if (target, preprint) in seen:
                            continue
                        seen.add((target, preprint))
                        # A formal anchor authenticates binding before the linked
                        # preprint details; it cannot replace formal identity.
                        found[target].append(ProviderWorkEvidence(
                            provenance=records[0].provenance.model_copy(update={'record_id': target + ':reverse:' + preprint}),
                            external_ids=ExternalIds(doi=target), publication_type='journal',
                            related_dois=(preprint,), related_ids=(ProviderRecordRef(provider='doi', record_id=preprint, relation='preprint'),)))
                        found[target].extend(records)
                results.update((doi, tuple(records)) for doi, records in found.items())
            except (ValueError, OSError, RuntimeError, TypeError, AttributeError) as error:
                results.update((doi, PartialLookup(str(error), records) if records else error) for doi, records in found.items())
        return results

    def _arxiv_feed(self, content, requested):
        try:
            root = ElementTree.fromstring(content)
        except ElementTree.ParseError:
            raise DiscoveryError("arXiv returned invalid Atom metadata") from None
        if root.tag != "{http://www.w3.org/2005/Atom}feed":
            raise DiscoveryError("arXiv response is not an Atom feed")
        ns = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
        records, wrong, failures = [], False, {}
        for entry in root.findall("a:entry", ns):
            url = entry.findtext("a:id", "", ns)
            identifier = normalize_external_id('arxiv', url)
            if identifier not in requested:
                wrong = True
                continue
            try:
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
                    abstract=entry.findtext("a:summary", "", ns).strip() or None,
                    authors=tuple(Author(name=name) for item in entry.findall("a:author", ns)
                                  if (name := item.findtext("a:name", "", ns).strip())),
                    publication_type="preprint", publication_date=_date_string(published) if published else None,
                    dates=(published,) if published else (),
                    indexed_terms=tuple(ProviderTopic(value=item.attrib["term"], source="arxiv", kind="category")
                                        for item in entry.findall("a:category", ns) if item.attrib.get("term")),
                ))
            except (ValueError, TypeError, AttributeError) as error:
                failures[identifier] = error
        return tuple(records), wrong, failures

    def _collection(self, path, *, doi):
        try:
            data = self.request(path, {})
        except ProviderHTTPError as error:
            if error.status == 404:
                return []
            raise
        messages = data.get("messages", [])
        no_match = {"no posts found", "no results found", f"preprint for doi {doi} not found"}
        if not isinstance(messages, list) or not messages or any(not isinstance(item, dict) for item in messages):
            raise DiscoveryError(f"{self.provider}: invalid identifier lookup status")
        statuses = {str(item.get("status", "")).strip().casefold() for item in messages}
        if statuses - {"ok", *no_match}:
            raise DiscoveryError(f"{self.provider}: identifier lookup failed")
        rows = data.get("collection")
        if statuses & no_match:
            if rows is None or rows == []:
                return []
            raise DiscoveryError(f"{self.provider}: identifier not-found status conflicts with returned metadata")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise DiscoveryError(f"{self.provider}: invalid identifier metadata collection")
        return rows

    def _bio_record(self, row, doi):
        if valid_doi(row.get("doi")) != doi:
            raise IdentityMismatch(f"{self.provider}: response DOI does not match requested identity")
        if row.get("server") and str(row["server"]).casefold() != self.provider:
            raise DiscoveryError(f"{self.provider}: response came from a different preprint server")
        published = valid_doi(row.get("published") or None)
        posted = _iso_date(row.get("date"), EvidenceDateKind.PREPRINT)
        if posted:
            posted = posted.model_copy(update={"first_version": str(row.get("version")) == "1", "publication_type": "preprint"})
        version = str(row.get("version", "")).strip() or None
        return ProviderWorkEvidence(
            provenance=MetadataSource(provider=self.provider, record_id=doi + (":" + version if version else ""),
                retrieved_at=datetime.now(timezone.utc), role="supplement", version=version,
                url=f"https://api.biorxiv.org/details/{self.provider}/{_native_doi_path(doi)}/na/json"),
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
            self._details_cache[doi] = tuple(self._bio_record(row, doi) for row in
                self._collection(f"/details/{self.provider}/{_native_doi_path(doi)}/na/json", doi=doi))
        return self._details_cache[doi]

    def lookup_published_preprints(self, identifier):
        """Follow explicit native publication relations for a formal DOI."""
        doi = valid_doi(identifier)
        if self.provider not in {"biorxiv", "medrxiv"} or not doi:
            raise DiscoveryError("Publication lookup requires a native preprint server and a valid formal DOI")
        encoded = _native_doi_path(doi)
        rows = self._collection(f"/pubs/{self.provider}/{encoded}/na/json", doi=doi)
        relations = {}
        for row in rows:
            preprint = valid_doi(row.get("preprint_doi") or row.get("biorxiv_doi"))
            legacy_preprint = valid_doi(row["biorxiv_doi"]) if row.get("biorxiv_doi") else None
            formal = valid_doi(row.get("published_doi"))
            if not preprint or preprint == doi or formal != doi or legacy_preprint and legacy_preprint != preprint:
                raise IdentityMismatch(f"{self.provider}: publication relation does not match requested DOI")
            platform = str(row.get("preprint_platform") or "").strip().casefold()
            if platform and platform != self.provider:
                raise IdentityMismatch(f"{self.provider}: relation names another preprint server")
            relations.setdefault(preprint, row)
        records = []
        for preprint, row in relations.items():
            versions = self._bio_details(preprint)
            if any(version.related_dois and version.related_dois != (doi,) for version in versions):
                raise IdentityMismatch(f"{self.provider}: preprint details name another published DOI")
            online = _iso_date(row.get("published_date"), EvidenceDateKind.PUBLISHED_ONLINE, source_label="published_date")
            records.append(ProviderWorkEvidence(
                provenance=MetadataSource(provider=self.provider, record_id=preprint + ":publication",
                    retrieved_at=datetime.now(timezone.utc), role="supplement",
                    url=f"https://api.biorxiv.org/pubs/{self.provider}/{encoded}/na/json"),
                external_ids=ExternalIds(doi=doi), related_dois=(preprint,),
                related_ids=(ProviderRecordRef(provider=self.provider, record_id=preprint, relation='preprint'),),
                journal=row.get("published_journal") or None, publication_type="journal",
                publication_date=None,
                dates=(online,) if online else (),
            ))
            records.extend(versions)
        return tuple(records)

    def _crossref(self, identifier):
        doi = valid_doi(identifier)
        if not doi:
            raise DiscoveryError("Crossref lookup requires a valid DOI")
        data = self.request("/works/" + quote(doi, safe="/"), {"mailto": self.mailto} if self.mailto else {})
        raw = data.get("message")
        if not isinstance(raw, dict) or valid_doi(raw.get("DOI")) != doi:
            raise IdentityMismatch("Crossref response DOI does not match requested identity")
        return self._crossref_record(raw)

    def _crossref_record(self, raw):
        doi = valid_doi(raw.get('DOI'))
        if not doi:
            raise IdentityMismatch('Crossref work lacks valid DOI identity')
        item, _ = normalize_crossref_discovered_work(raw, datetime.now(timezone.utc))
        record = item.to_evidence()
        preprint = raw.get("type") == "posted-content"
        conference = raw.get("type") == "proceedings-article"
        publication_type = ('preprint' if preprint else 'conference' if conference else
                            'journal' if raw.get('type') == 'journal-article' else None)
        dates = list(record.dates)
        dates.extend(_history_assertions(raw, publication_type))
        for name, kind in (("accepted", EvidenceDateKind.ACCEPTED), ("posted", EvidenceDateKind.PREPRINT)):
            if name == "accepted" and preprint:
                continue  # A platform's acceptance of posted content is not journal acceptance.
            container = raw.get(name) or {}
            parts = container.get("date-parts", []) if isinstance(container, dict) else []
            if parts and (value := _date(parts[0], kind)):
                dates.append(value.model_copy(update={"source_label": name, "publication_type": publication_type,
                    "first_version": False}))
        related, refs = set(), set()
        relations = raw.get("relation") or {}
        for kind in SAME_WORK_RELATIONS:
            entries = relations.get(kind, []) if isinstance(relations, dict) else []
            for relation in entries if isinstance(entries, list) else ():
                if not isinstance(relation, dict):
                    continue
                target = None
                raw_id = relation.get('id')
                if relation.get('id-type') == 'doi' and isinstance(raw_id, str) and (value := valid_doi(raw_id)):
                    target = 'doi', value
                elif relation.get('id-type') == 'arxiv' and (value := normalize_external_id('arxiv', raw_id)):
                    target = 'arxiv', value
                elif relation.get('id-type') == 'uri':
                    target = supported_preprint_uri(raw_id)
                    if target is None and isinstance(raw_id, str):
                        from urllib.parse import urlsplit
                        try:
                            uri = urlsplit(raw_id)
                            if (uri.scheme in {'http','https'} and uri.hostname in {'doi.org','dx.doi.org'}
                                    and not uri.username and not uri.password and not uri.query and not uri.fragment
                                    and uri.port in {None, 80 if uri.scheme == 'http' else 443}
                                    and (value := valid_doi(uri.path.lstrip('/')))):
                                target = 'doi', value
                        except ValueError:
                            pass
                if target is None:
                    continue
                namespace, value = target
                if namespace in {'doi','biorxiv','medrxiv'}:
                    related.add(value)
                role = ('preprint' if kind == 'has-preprint' else
                    'version' if preprint and kind in {'is-version-of','has-version'} else None)
                refs.add(ProviderRecordRef(provider=namespace, record_id=value, relation=role))
        # A DOI prefix does not distinguish bioRxiv from medRxiv. Explicit
        # publisher metadata can direct native lookup without asserting v1.
        platform = str(raw.get('publisher') or '').strip().casefold()
        if preprint and doi.startswith(('10.1101/', '10.64898/')) and platform in {'biorxiv','medrxiv'}:
            refs.add(ProviderRecordRef(provider=platform, record_id=doi, relation='preprint'))
        source = MetadataSource(provider="crossref", record_id=doi, retrieved_at=datetime.now(timezone.utc),
                                role="supplement", version=str(raw.get('version') or '').strip() or None,
                                url="https://api.crossref.org/works/" + quote(doi, safe="/"))
        publication = next((value for label in ('published', 'published-print', 'issued')
                            for value in dates if value.kind == EvidenceDateKind.PUBLISHED and value.source_label == label), None)
        return (record.model_copy(update={
            "provenance": source, "related_dois": tuple(sorted(related - {doi})), "dates": tuple(dates),
            "related_ids": tuple(sorted(refs, key=lambda ref: (ref.provider, ref.record_id))),
            "publication_type": publication_type,
            "journal": None if preprint or conference else _first(raw.get("container-title")),
            "conference": (raw.get("event") or {}).get("name") if conference else None,
            "publication_date": _date_string(publication) if publication else None,
        }),)
