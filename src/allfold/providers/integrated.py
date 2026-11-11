"""Scoped HTTP discovery. Adapters retain native hits and report bounded coverage."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, timedelta
import re
from threading import Event, RLock, local
from urllib.parse import quote, urlencode

from allfold.identifiers import normalize_doi, normalize_external_id, valid_doi
from allfold.progress import ProgressEvent, ActivityUpdate, ActivityKind
from allfold.keywords import And, Or, Prefix, Phrase, Proximity
from allfold.models import ProviderWorkEvidence
from allfold.providers.provider_http import (
    Cancelled, DiscoveryError, ProviderFailure, ProviderHTTPError, ProviderReadClient, object_json,
)

DISCOVERY_PROVIDERS = ('pubmed', 'openalex')
RUN_PROVIDERS = ('wos', *DISCOVERY_PROVIDERS)
SUPPLEMENT_PROVIDERS = ('europe_pmc', 'crossref', 'arxiv', 'biorxiv', 'medrxiv')
PROVIDERS = DISCOVERY_PROVIDERS + SUPPLEMENT_PROVIDERS
BASE_URLS = {'pubmed':'https://eutils.ncbi.nlm.nih.gov/entrez/eutils', 'openalex':'https://api.openalex.org', 'europe_pmc':'https://www.ebi.ac.uk/europepmc/webservices/rest', 'crossref':'https://api.crossref.org', 'arxiv':'https://export.arxiv.org', 'biorxiv':'https://api.biorxiv.org', 'medrxiv':'https://api.biorxiv.org'}


@dataclass(frozen=True)
class SourceScope:
    kind: str
    name: str
    key: str = ''
    issns: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiscoveryResult:
    provider: str
    source: SourceScope
    status: str
    records: tuple[ProviderWorkEvidence, ...] = ()
    limitations: tuple[str, ...] = ()
    candidates: int = 0
    total: int | None = None
    created: int | None = None
    existing: int | None = None
    bindings: tuple[tuple[str, str, str], ...] = ()

    def fact(self):
        return dict(provider=self.provider, source=self.source.name, source_kind=self.source.kind,
                    status=self.status, candidates=self.candidates,
                    retained=len({(record.provenance.provider, record.provenance.record_id) for record in self.records}), total=self.total, limitations=list(self.limitations), created=self.created, existing=self.existing)


class IdentityMismatch(DiscoveryError):
    pass


class UnsupportedSource(DiscoveryError):
    pass


def _word(node):
    if isinstance(node, Proximity):
        raise DiscoveryError('Proximity search is not supported')
    words = node.value.split()
    if not words or any(not word.isalnum() for word in words):
        raise DiscoveryError('Operand cannot be converted reliably; use lexical words or phrases')
    value = ' '.join(words)
    return value + '*' if isinstance(node, Prefix) else '"' + value + '"' if isinstance(node, Phrase) else value


def compile_query(ast, provider):
    """Compile one AST into approved fields only; never interpolate raw syntax."""
    if isinstance(ast, (And, Or)):
        op = 'AND' if isinstance(ast, And) else 'OR'
        return f'({compile_query(ast.left, provider)} {op} {compile_query(ast.right, provider)})'
    value = _word(ast)
    if provider == 'pubmed':
        return f'{value}[Title/Abstract]'
    if provider == 'europe_pmc':
        raise DiscoveryError('Europe PMC is a targeted PPR completion source, not a Discovery Provider')
    return value


def _prefix(ast):
    return _prefix(ast.left) or _prefix(ast.right) if isinstance(ast, (And, Or)) else isinstance(ast, Prefix)


def _positive(value, name):
    try:
        number = int(value)
        if number < 0 or isinstance(value, bool):
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise DiscoveryError(f'Invalid {name} in provider response') from None


class DiscoveryClient:
    """One provider/host owns rate limits, bounded retry and cancellation checks."""
    def __init__(self, provider, *, api_key=None, cancel_event=None, interval=None,
                 page_size=100, progress_callback=None, **http_options):
        if provider not in PROVIDERS:
            raise ValueError('Unknown Discovery Provider')
        self.progress = progress_callback
        self._completing = False
        self._request_trace = local()
        self._completion_responses = {}
        self._exact_batch_plans = {}
        self._settlement_operations = {}
        self._settling = False
        self._progress_requests = {}
        self.provider = provider
        self.api_key = api_key
        self.cancel = cancel_event if cancel_event is not None else Event()
        self.request_guard = None
        if interval is None:
            interval = 0.11 if provider == 'pubmed' and api_key else 0.35
        self._reader = ProviderReadClient(provider, api_key=api_key, interval=interval,
            cancel_event=self.cancel, guard=lambda: self.request_guard and self.request_guard(), **http_options)
        self.page_size = max(1, min(page_size, 1000))
        self.cache = {}
        self._cache_lock = RLock()
        self._lookup_lock = RLock()
        self._openalex_full_raw = {}
        self._openalex_full_pending = {}

    @property
    def request_count(self):
        return self._reader.request_count

    @property
    def recovery_observer(self):
        return self._reader.recovery_observer

    @recovery_observer.setter
    def recovery_observer(self, observer):
        self._reader.recovery_observer = observer

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._reader.http.close()

    def check_cancel(self):
        self._reader.check_authority()

    def begin_completion(self):
        """Discovery/Work has settled; subsequent HTTP belongs to Completion."""
        self._completing = True

    @contextmanager
    def capture_transient_failures(self):
        failures = []
        self._request_trace.failures = failures
        try:
            yield failures
        finally:
            del self._request_trace.failures

    def begin_settlement(self):
        """Permit one extra dispatch for each failed completion HTTP request."""
        with self._cache_lock:
            self._settling = True
            failures = {id(self._completion_responses[key]) for key in self._settlement_operations}
            for cache in (self.cache, self._openalex_full_raw):
                for key in [key for key, value in cache.items() if id(value) in failures]:
                    del cache[key]

    def _request_activity(self, path, params):
        if not self.progress:
            return None
        native = (self.provider == 'arxiv' or self.provider in {'biorxiv', 'medrxiv'} and '/details/' in path
            or self.provider == 'europe_pmc' and str(params.get('query', '')).startswith('SRC:PPR'))
        phase = ('native-version', 'Native version verification') if native else ('base-api', 'Base API completion')
        operation, phase_label = phase if self._completing else ('http', None)
        index = None

        def report(kind, label, detail):
            nonlocal index
            if kind is ActivityKind.WORKING:
                if phase_label is None:
                    return
                if detail == 'Request dispatched':
                    with self._cache_lock:
                        index = self._progress_requests[operation] = self._progress_requests.get(operation, 0) + 1
                name = operation
            elif kind is ActivityKind.RETRYING:
                name = operation + '-retry' if phase_label else 'http_retry'
            else:
                name = operation + '-cooldown'
            self.progress(ProgressEvent(activity=ActivityUpdate(
                kind=kind, source=self.provider, operation=name,
                label=phase_label if kind is ActivityKind.WORKING else label,
                detail=detail, current=index if kind is ActivityKind.WORKING else None, unit='request',
            )))

        return report

    def request(self, path, params, *, response_format="json"):
        self.check_cancel()
        failures = getattr(self._request_trace, 'failures', None)
        if failures is None and not self._settling:
            return self._request(path, params, response_format, self._reader.operation(self._request_activity(path, params)))
        # Settlement reuses parsed responses, including successful pagination
        # prefixes, and replays only the failed prepared HTTP request.
        key = path, tuple(sorted(params.items())), response_format
        with self._cache_lock:
            value = self._completion_responses.get(key)
            final = self._settlement_operations.pop(key, None) if self._settling else None
        if value is None or final is not None:
            operation = final or self._reader.operation(self._request_activity(path, params))
            try:
                value = self._request(path, params, response_format, operation, final=final is not None)
            except DiscoveryError as error:
                value = error
            with self._cache_lock:
                self._completion_responses[key] = value
                if failures is not None and value is operation.failure and operation.can_recheck:
                    self._settlement_operations[key] = operation
        if isinstance(value, Exception):
            if failures is not None:
                with self._cache_lock:
                    if key in self._settlement_operations:
                        failures.append(key)
            raise value
        return value

    def _request(self, path, params, response_format, operation, *, final=False):
        keyed_pubmed = self.provider == 'pubmed' and self.api_key
        headers = {"Authorization": "Bearer " + self.api_key} if self.provider == 'openalex' and self.api_key else {}
        url = BASE_URLS[self.provider] + path

        def prepare():
            # NCBI accepts form POST for these reads. Keep its optional secret
            # out of request URLs and disallow redirects for keyed form data.
            if keyed_pubmed:
                return self._reader.http.build_request('POST', url, data=dict(params, api_key=self.api_key))
            return self._reader.http.build_request('GET', url, params=params, headers=headers)

        def decode(response):
            if response_format == "xml":
                return response.text
            data = object_json(self.provider, response)
            if self.provider == 'pubmed':
                from allfold.providers.pubmed import has_entrez_error
                if has_entrez_error(data):
                    raise ProviderFailure('PubMed: Entrez application error', kind='protocol',
                                          code='http_error', outcome='responded')
            return data

        return self._reader.read(prepare, operation, decode=decode,
                                 follow_redirects=not keyed_pubmed and not final, final=final)

    def discover(self, source, ast, from_date, to_date):
        """Single-scope convenience seam; Discovery always keeps complete evidence."""
        return self.discover_many((source,), ast, from_date, to_date)[0]

    def discover_many(self, scopes, ast, from_date, to_date, *, records_callback=None):
        """Merged native journal queries; callbacks contain verified page records."""
        scopes = tuple(scopes)
        if self.provider not in DISCOVERY_PROVIDERS:
            return tuple(DiscoveryResult(self.provider, scope, 'failed', limitations=(
                'Provider does not support journal Discovery; rebuild configuration from config.template.yaml',)) for scope in scopes)
        records, problems = {scope: [] for scope in scopes}, []
        try:
            compile_query(ast, self.provider)
            if any(scope.kind != 'journal' or not scope.issns for scope in scopes):
                raise DiscoveryError('Journal discovery requires valid ISSN/eISSN scopes')
            batches = self._pubmed_discovery_pages(scopes, ast, from_date, to_date) if self.provider == 'pubmed' else self._openalex_discovery_pages(scopes, ast, from_date, to_date, problems)
            seen = set()
            for page in batches:
                verified = []
                for record in page:
                    key = (record.provenance.provider, record.provenance.record_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches = [scope for scope in scopes if set(scope.issns) & set(record.journal_issns)]
                    if not matches:
                        problems.append('Incomplete: returned primary journal identity does not match followed ISSNs')
                        continue
                    record = record.model_copy(update={'provenance': record.provenance.model_copy(update={'role':'discovery'})})
                    for scope in matches:
                        records[scope].append(record.model_copy(update={'monitor_journal_issns':scope.issns}))
                    verified.append(record)
                if verified and records_callback:
                    self.check_cancel()
                    records_callback(tuple(verified))
        except Cancelled as error:
            problems.append(str(error))
        except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
            problems.append(str(error))
        cancelled = self.cancel.is_set()
        return tuple(DiscoveryResult(self.provider, scope,
            'cancelled' if cancelled else 'partial' if problems and records[scope] else 'failed' if problems else 'complete' if records[scope] else 'empty',
            tuple(records[scope]), tuple(dict.fromkeys(problems)), len(records[scope]),
            None if problems else len(records[scope])) for scope in scopes)

    def _groups(self, values, params, *, limit=100):
        group = []
        for value in dict.fromkeys(values):
            if len(urlencode(params([value]))) > 6000:
                raise DiscoveryError('Identity exceeds request URL budget')
            if group and (len(group) >= limit or len(urlencode(params([*group, value]))) > 6000):
                yield group
                group = []
            group.append(value)
        if group:
            yield group

    def _exact_batches(self, namespace, identities, capability, params, *, limit=100):
        key = namespace, tuple(identities), capability
        if self._settling and key in self._exact_batch_plans:
            return self._exact_batch_plans[key]
        missing = [value for value in identities if self.cached_lookup(namespace, value, capability) is None]
        groups = tuple(self._groups(missing, params, limit=limit))
        if getattr(self._request_trace, 'failures', None) is not None and groups:
            self._exact_batch_plans.setdefault(key, groups)
        return groups

    def _pubmed_discovery_pages(self, scopes, ast, start, end):
        from allfold.providers.pubmed import fetch_records, has_entrez_error
        expression = compile_query(ast, 'pubmed')
        def params(issns):
            return {'db':'pubmed', 'retmode':'json', 'usehistory':'y', 'retmax':9999,
                'term': '(' + ' OR '.join(value + '[ISSN]' for value in issns) + ') AND ' + expression}
        for issns in self._groups((issn for scope in scopes for issn in scope.issns), params):
            pending = [(date.fromisoformat(str(start)), date.fromisoformat(str(end)))]
            while pending:
                self.check_cancel()
                lower, upper = pending.pop(0)
                query = params(issns)
                query['term'] += f' AND ("{lower}"[Date - Publication] : "{upper}"[Date - Publication])'
                data = self.request('/esearch.fcgi', query).get('esearchresult')
                if not isinstance(data, dict) or has_entrez_error(data, queried_issns=issns):
                    raise DiscoveryError('PubMed: Entrez ESearch application error or invalid result')
                total = _positive(data.get('count'), 'ESearch count')
                if total > 9999:
                    if lower == upper:
                        raise DiscoveryError('Incomplete: PubMed daily query exceeds the 9999 PMID ESearch window; narrow journal or keyword scope')
                    middle = lower + (upper - lower) // 2
                    pending[0:0] = [(lower, middle), (middle + timedelta(days=1), upper)]
                    continue
                identifiers = data.get('idlist')
                if not isinstance(identifiers, list) or len(identifiers) != total or len(set(identifiers)) != total or any(not normalize_external_id('pmid', value) for value in identifiers):
                    raise DiscoveryError('Incomplete: PubMed ESearch PMID set is shortened or invalid')
                if not total:
                    continue
                history, key = data.get('webenv'), data.get('querykey')
                if not history or not key:
                    raise DiscoveryError('Incomplete: PubMed ESearch History Server identity is missing')
                found = set()
                for offset in range(0, total, self.page_size):
                    text = self.request('/efetch.fcgi', {'db':'pubmed', 'retmode':'xml', 'WebEnv':history,
                        'query_key':key, 'retstart':offset, 'retmax':min(self.page_size, total-offset)}, response_format='xml')
                    page = fetch_records(text)
                    ids = [record.external_ids.model_dump()['pmid'] for record in page]
                    if any(value not in identifiers or value in found for value in ids) or len(set(ids)) != len(ids):
                        raise IdentityMismatch('PubMed: unexpected or duplicate PMID in History EFetch')
                    for record in page:
                        self._remember_pubmed(record, 'fetch')
                    found.update(ids)
                    yield page
                    if len(page) != min(self.page_size, total-offset):
                        raise DiscoveryError('Incomplete: PubMed EFetch returned a shortened batch')
                if found != set(identifiers):
                    raise DiscoveryError('Incomplete: PubMed EFetch did not cover the full PMID set')

    def _openalex_discovery_pages(self, scopes, ast, start, end, problems):
        def params(issns):
            return {'filter':f'primary_location.source.issn:{"|".join(issns)},from_publication_date:{start},to_publication_date:{end}',
                'search.title_abstract_keywords' + ('.exact' if _prefix(ast) else ''):compile_query(ast, 'openalex'),
                'per_page':min(self.page_size, 100), **({'cursor':'*'} if self.api_key else {'page':1})}
        for issns in self._groups((issn for scope in scopes for issn in scope.issns), params):
            for rows in self._openalex_pages(params(issns)):
                page = []
                for raw in rows:
                    self.check_cancel()
                    try:
                        raw = self._complete_openalex(raw)
                        record = self.normalize(raw, SourceScope('journal',''))
                    except Cancelled:
                        raise
                    except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
                        problems.append(f'OpenAlex Work record: {error}')
                        continue
                    if record is not None:
                        self._remember_openalex(record)
                        page.append(record)
                yield tuple(page)

    def normalize(self, raw, source):
        from allfold.providers.discovery_evidence import normalize_openalex, normalize_europe_pmc
        normalizer = {'openalex': normalize_openalex, 'europe_pmc': normalize_europe_pmc}.get(self.provider)
        if normalizer is None:
            raise DiscoveryError('Provider normalization unavailable')
        return normalizer(raw, source)

    def _europe_pages(self, query, *, result_type="core"):
        cursor, seen, count = '*', set(), 0
        while True:
            data = self.request('/search',{'query':query,'format':'json','resultType':result_type,'pageSize':self.page_size,'cursorMark':cursor})
            total = _positive(data.get('hitCount'), 'hitCount')
            rows = data.get('resultList',{}).get('result')
            if not isinstance(rows,list):
                raise DiscoveryError('Europe PMC response is missing resultList')
            yield None, total, ()
            for raw in rows:
                count += 1
                yield raw, total, ()
            if count >= total:
                return
            cursor = data.get('nextCursorMark')
            if not rows or not cursor or cursor in seen:
                raise DiscoveryError('Incomplete: Europe PMC pagination made no progress')
            seen.add(cursor)

    def lookup(self, namespace, identifier):
        """Exact-identifier metadata lookup; no keyword discovery fallback."""
        if self.provider == 'openalex' and namespace in {'doi','openalex'} or self.provider == 'pubmed' and namespace == 'pmid':
            result = self.lookup_many(namespace, (identifier,))
            if result.status in {'failed','cancelled'}:
                raise DiscoveryError('; '.join(result.limitations))
            return result.records
        if self.provider == 'europe_pmc' and namespace in {'doi','europe_pmc','pmid','pmcid'}:
            if namespace == 'europe_pmc':
                src, key = identifier.split(':',1)
                if not src.isalnum() or not key.isalnum(): raise DiscoveryError('Invalid Europe PMC identity')
                query = f'EXT_ID:{key} AND SRC:{src}'
            else:
                if namespace == 'doi':
                    identifier = normalize_doi(identifier)
                    if not identifier or any(c in identifier for c in ('"', "\\")): raise DiscoveryError('Invalid DOI for native identifier lookup')
                elif not re.fullmatch(r'[A-Za-z0-9]+',identifier): raise DiscoveryError('Invalid identifier')
                query = f'{ {"doi":"DOI","pmid":"EXT_ID","pmcid":"PMCID"}[namespace]}:"{identifier}"'
                if namespace == 'pmid': query += ' AND SRC:MED'
            output=[]
            for raw, _, _ in self._europe_pages(query):
                if raw:
                    journal = raw.get('journalInfo',{}).get('journal',{}).get('title') or ''
                    output.append(self.normalize(raw,SourceScope('journal',journal)))
            return tuple(output)
        return ()


    def lookup_many(self, namespace, identifiers, *, capability=None):
        if self.provider == 'pubmed':
            return self._pubmed_lookup_many(namespace, identifiers, capability=capability or 'summary')
        if self.provider == 'openalex':
            return self._openalex_lookup_many(namespace, identifiers)
        return self._legacy_lookup_many(namespace, identifiers)

    def _legacy_lookup_many(self, namespace, identifiers):
        if self.provider != 'europe_pmc' or namespace != 'europe_pmc':
            raise DiscoveryError('Batch lookup is unavailable for this Provider identity')
        requested = list(dict.fromkeys(identifiers))
        records, problems = [], []
        def query(values):
            return {'query':' OR '.join(f'(EXT_ID:{value.split(":",1)[1]} AND SRC:{value.split(":",1)[0]})' for value in values)}
        try:
            valid = []
            for value in requested:
                normalized = normalize_external_id(namespace,value)
                if normalized:
                    valid.append(normalized)
                else:
                    problems.append('Invalid Europe PMC detail identity')
            for group in self._groups(valid,query):
                found = set()
                for raw,_,_ in self._europe_pages(query(group)['query']):
                    if raw is None:
                        continue
                    native = normalize_external_id(namespace,f"{raw.get('source','')}:{raw.get('id','')}")
                    if native not in group:
                        raise IdentityMismatch('Unexpected Europe PMC detail identity')
                    if native not in found:
                        journal = ((raw.get('journalInfo') or {}).get('journal') or {}).get('title') or ''
                        records.append(self.normalize(raw,SourceScope('journal',journal)))
                        found.add(native)
                problems.extend('Missing metadata details: ' + value for value in set(group)-found)
        except (DiscoveryError,ValueError,KeyError,TypeError,AttributeError) as error:
            problems.append(str(error))
        status = 'cancelled' if self.cancel.is_set() else 'partial' if problems and records else 'failed' if problems else 'complete' if records else 'empty'
        return DiscoveryResult(self.provider,SourceScope('journal',''),status,tuple(records),tuple(dict.fromkeys(problems)),len(requested))

    def resolve_pubmed_dois(self, identifiers):
        """Return only exact, unambiguous formal DOI/PMID pairs per search batch."""
        from allfold.providers.pubmed import esearch_identifiers

        if self.provider != 'pubmed':
            raise DiscoveryError('DOI to PMID resolution requires PubMed')
        requested, results = {}, {}
        for identifier in identifiers:
            doi = valid_doi(identifier) if isinstance(identifier, str) and identifier.strip() else None
            if not doi or not doi.isprintable() or any(character in doi for character in '"\\'):
                results[identifier] = DiscoveryError('Invalid DOI for PubMed Article Identifier query')
            else:
                requested[doi] = None

        def params(dois):
            return {'db': 'pubmed', 'retmode': 'json', 'retmax': 9999, 'retstart': 0,
                'term': ' OR '.join(f'"{doi}"[aid]' for doi in dois)}

        for doi in tuple(requested):
            if len(urlencode(params([doi]))) > 6000:
                results[doi] = DiscoveryError('DOI exceeds PubMed request URL budget')
                del requested[doi]
        for group in self._groups(requested, params):
            try:
                self.check_cancel()
                pmids = esearch_identifiers(self.request('/esearch.fcgi', params(group)))
                results.update(self._pubmed_doi_matches(group, pmids))
            except DiscoveryError as error:
                results.update((doi, error) for doi in group)
                if isinstance(error, Cancelled):
                    break
        return results

    def _pubmed_doi_matches(self, dois, pmids):
        if not pmids:
            return dict.fromkeys(dois, ())
        def exact_records(identifiers, capability):
            result = self.lookup_many('pmid', identifiers, capability=capability)
            if result.status == 'complete':
                return {record.external_ids.pmid: record for record in result.records}
            if result.status == 'cancelled':
                raise Cancelled('Run cancelled')
            for identifier in identifiers:
                error = self.cached_lookup('pmid', identifier, capability)
                if isinstance(error, DiscoveryError):
                    raise error
            raise DiscoveryError('; '.join(result.limitations) or f'Incomplete: PubMed DOI identity {capability} batch')

        records = exact_records(pmids, 'summary')
        if set(records) != set(pmids):
            raise DiscoveryError('Incomplete: PubMed DOI identity summaries')
        unresolved = [pmid for pmid, record in records.items()
            if not record.external_ids.doi and record.publication_type != 'preprint']
        if unresolved:
            records.update(exact_records(unresolved, 'fetch'))
        if any(record.publication_type != 'preprint' and not record.external_ids.doi for record in records.values()):
            raise DiscoveryError('Incomplete: PubMed DOI identity record lacks a direct DOI')
        if any(record.publication_type != 'preprint' and record.external_ids.doi not in dois for record in records.values()):
            raise IdentityMismatch('PubMed DOI search returned an unrequested direct DOI')
        matches = {doi: [] for doi in dois}
        for record in records.values():
            if record.publication_type != 'preprint':
                matches[record.external_ids.doi].append(record)
        return {doi: tuple(rows) if len(rows) <= 1 else
            IdentityMismatch('Multiple PubMed records have the same direct DOI') for doi, rows in matches.items()}

    def _remember_pubmed(self, record, capability):
        pmid = record.external_ids.model_dump().get('pmid')
        with self._cache_lock:
            if capability == 'fetch':
                self.cache[('pmid', pmid, 'fetch')] = (record,)
            fetched = self.cache.get(('pmid', pmid, 'fetch'))
            self.cache[('pmid', pmid, 'summary')] = fetched if isinstance(fetched, tuple) else (record,)

    def cached_lookup(self, namespace, identifier, capability='full'):
        normalized = normalize_doi(identifier) if namespace == 'doi' else normalize_external_id(namespace, identifier)
        with self._cache_lock:
            return self.cache.get((namespace, normalized, capability))

    def _pubmed_lookup_many(self, namespace, identifiers, *, capability):
        from allfold.providers.pubmed import fetch_records, summary_records
        if namespace != 'pmid' or capability not in {'summary','fetch'}:
            raise DiscoveryError('PubMed exact batches require PMID and summary/fetch capability')
        requested = list(dict.fromkeys(identifiers))
        records, problems = [], []
        with self._lookup_lock:
            valid = []
            for value in requested:
                normalized = normalize_external_id('pmid', value)
                if not normalized:
                    problems.append('Invalid PubMed PMID')
                else:
                    valid.append(normalized)
            def params(values):
                return {'db':'pubmed', 'id':','.join(values), 'retmode':'xml' if capability == 'fetch' else 'json', 'version':'2.0'}
            for group in self._exact_batches(namespace, valid, capability, params, limit=200):
                try:
                    data = self.request('/efetch.fcgi' if capability == 'fetch' else '/esummary.fcgi', params(group),
                                        response_format='xml' if capability == 'fetch' else 'json')
                    page = fetch_records(data) if capability == 'fetch' else summary_records(data)
                    found = {record.external_ids.pmid for record in page}
                    if not found.issubset(group) or len(found) != len(page):
                        raise IdentityMismatch('PubMed: unexpected or duplicate PMID in exact batch')
                    for record in page:
                        pmid = record.external_ids.pmid
                        previous = self.cached_lookup('pmid', pmid, 'summary')
                        if capability == 'fetch' and isinstance(previous, tuple) and previous:
                            known, = previous
                            if (known.external_ids.doi and record.external_ids.doi
                                    and known.external_ids.doi != record.external_ids.doi
                                    or (known.publication_type == 'preprint') != (record.publication_type == 'preprint')):
                                with self._cache_lock:
                                    self.cache['pmid', pmid, capability] = IdentityMismatch('PubMed: summary and article identities disagree')
                                continue
                            record = record.model_copy(update={
                                'external_ids': record.external_ids.model_copy(update={
                                    'doi': record.external_ids.doi or known.external_ids.doi}),
                                'dates': tuple(dict.fromkeys((*known.dates, *record.dates))),
                                'related_ids': tuple(dict.fromkeys((*known.related_ids, *record.related_ids))),
                            })
                        self._remember_pubmed(record, capability)
                    with self._cache_lock:
                        for value in set(group)-found:
                            self.cache[('pmid',value,capability)] = DiscoveryError('Incomplete: PubMed exact batch omitted PMID ' + value)
                except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
                    with self._cache_lock:
                        for value in group:
                            self.cache.setdefault(('pmid',value,capability),error)
                    if isinstance(error,Cancelled):
                        break
            for value in valid:
                cached = self.cached_lookup('pmid',value,capability)
                if isinstance(cached,Exception):
                    problems.append(str(cached))
                elif cached is not None:
                    records.extend(cached)
        unique = {record.provenance.record_id:record for record in records}
        status = 'cancelled' if self.cancel.is_set() else 'partial' if problems and unique else 'failed' if problems else 'complete' if unique else 'empty'
        return DiscoveryResult(self.provider, SourceScope('journal',''), status, tuple(unique.values()),tuple(dict.fromkeys(problems)),len(requested))

    def _openalex_pages(self, params):
        params = dict(params)
        seen, seen_ids, count, advertised = set(), set(), 0, None
        while True:
            data = self.request('/works',params)
            rows = data.get('results')
            if not isinstance(rows,list):
                raise DiscoveryError('OpenAlex response is missing results')
            total = _positive(data.get('meta',{}).get('count'),'count')
            if advertised is not None and total != advertised:
                raise DiscoveryError('Incomplete: OpenAlex advertised total changed across pages')
            advertised = total
            yield rows
            for raw in rows:
                count += 1
                native = normalize_external_id('openalex',raw.get('id')) if isinstance(raw, dict) else None
                # The consumer reports malformed individual records. They still
                # occupy a result row; pagination totals count every returned row.
                if not native:
                    continue
                if native in seen_ids:
                    raise DiscoveryError('Incomplete: OpenAlex duplicate Work across pages')
                seen_ids.add(native)
            if count > total:
                raise DiscoveryError('Incomplete: OpenAlex returned more records than advertised')
            cursor = data.get('meta',{}).get('next_cursor')
            if count == total:
                return
            if not self.api_key:
                raise DiscoveryError('Incomplete: OpenAlex cursor paging requires an optional API Key; anonymous first-page evidence retained')
            if not cursor:
                raise DiscoveryError('Truncated: OpenAlex pagination ended before advertised total')
            if not rows or cursor in seen:
                raise DiscoveryError('Incomplete: OpenAlex pagination made no progress')
            seen.add(cursor)
            params['cursor'] = cursor

    def _complete_openalex(self, raw):
        native = normalize_external_id('openalex',raw.get('id'))
        if not native:
            raise IdentityMismatch('OpenAlex returned invalid Work identity')
        shortened = raw.get('authors_count',0) > len(raw.get('authorships') or []) or raw.get('locations_count',0) > len(raw.get('locations') or [])
        with self._cache_lock:
            cached = self._openalex_full_raw.get(native)
            if isinstance(cached, dict):
                return cached
            if not shortened:
                self._openalex_full_raw[native] = raw
                return raw
            if isinstance(cached, Exception):
                raise cached
            pending = self._openalex_full_pending.get(native)
            owner = pending is None
            if owner:
                pending = self._openalex_full_pending[native] = Event()
        if not owner:
            while not pending.wait(0.1):
                self.check_cancel()
            self.check_cancel()
            with self._cache_lock:
                cached = self._openalex_full_raw[native]
            if isinstance(cached, Exception):
                raise cached
            return cached
        try:
            details = self.request('/works/' + native,{})
            if normalize_external_id('openalex',details.get('id')) != native:
                raise IdentityMismatch('OpenAlex singleton returned another Work identity')
            if details.get('authors_count',0) > len(details.get('authorships') or []) or details.get('locations_count',0) > len(details.get('locations') or []):
                raise DiscoveryError('Incomplete: OpenAlex singleton still has shortened authorships or locations')
            with self._cache_lock:
                self._openalex_full_raw[native] = details
            return details
        except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
            with self._cache_lock:
                self._openalex_full_raw.setdefault(native,error)
            raise
        finally:
            with self._cache_lock:
                self._openalex_full_pending.pop(native,None)
                pending.set()

    def _remember_openalex(self, record):
        with self._cache_lock:
            identities = [('openalex',normalize_external_id('openalex',record.external_ids.openalex))]
            identities.extend(('doi',doi) for doi in (record.external_ids.doi,*record.related_dois) if doi)
            for namespace,value in identities:
                if value:
                    key = (namespace,value,'full')
                    previous = self.cache.get(key)
                    self.cache[key] = tuple({item.provenance.record_id:item for item in (*(previous if isinstance(previous,tuple) else ()),record)}.values())

    def _openalex_lookup_many(self, namespace, identifiers):
        if namespace not in {'doi','openalex'}:
            raise DiscoveryError('OpenAlex exact batches require DOI or Work identities')
        requested, problems, records = [], [], {}
        bindings = []
        for value in identifiers:
            normalized = valid_doi(value) if namespace == 'doi' else normalize_external_id(namespace,value)
            if normalized:
                if normalized not in requested:
                    requested.append(normalized)
            else:
                problems.append('Invalid OpenAlex exact lookup identity')
        with self._lookup_lock:
            def params(values):
                field = 'doi' if namespace == 'doi' else 'openalex'
                return {'filter':field + ':' + '|'.join('https://doi.org/'+value if namespace == 'doi' else value.rsplit('/',1)[-1] for value in values),
                        'per_page':min(self.page_size,100), **({'cursor':'*'} if self.api_key else {'page':1})}
            for group in self._exact_batches(namespace, requested, 'full', params):
                found = set()
                try:
                    for page in self._openalex_pages(params(group)):
                        for raw in page:
                            raw = self._complete_openalex(raw)
                            record = self.normalize(raw,SourceScope('journal',''))
                            if record is None:
                                continue
                            returned = ({record.external_ids.doi,*record.related_dois} if namespace == 'doi' else
                                        {normalize_external_id('openalex',record.external_ids.openalex)})
                            matches = set(group) & returned
                            if not matches:
                                problems.append('OpenAlex exact batch returned an unrequested Work')
                                continue
                            self._remember_openalex(record)
                            found.update(matches)
                    with self._cache_lock:
                        for value in set(group)-found:
                            self.cache[(namespace,value,'full')] = ()
                except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
                    problems.append(str(error))
                    with self._cache_lock:
                        for value in group:
                            self.cache.setdefault((namespace,value,'full'),error)
                    if isinstance(error,Cancelled):
                        break
            for value in requested:
                cached = self.cached_lookup(namespace,value)
                if isinstance(cached,Exception):
                    problems.append(str(cached))
                elif cached is not None:
                    for record in cached:
                        records[record.provenance.record_id] = record
                        bindings.append((namespace,value,normalize_external_id('openalex',record.external_ids.openalex)))
        status = 'cancelled' if self.cancel.is_set() else 'partial' if problems and records else 'failed' if problems else 'complete' if records else 'empty'
        return DiscoveryResult(self.provider,SourceScope('journal',''),status,tuple(records.values()),tuple(dict.fromkeys(problems)),len(requested),bindings=tuple(bindings))
