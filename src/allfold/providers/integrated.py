"""Scoped HTTP discovery. Adapters retain native hits and report bounded coverage."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
import time
from threading import Event
from urllib.parse import quote

import httpx

from allfold.http_client import create_http_client
from allfold.identifiers import normalize_doi, normalize_external_id, valid_doi
from allfold.progress import ProgressEvent, ActivityUpdate, ActivityKind
from allfold.keywords import And, Or, Prefix, Phrase, Proximity
from allfold.models import ProviderWorkEvidence

DISCOVERY_PROVIDERS = ('openalex', 'europe_pmc')
SUPPLEMENT_PROVIDERS = ('crossref', 'arxiv', 'biorxiv', 'medrxiv')
PROVIDERS = DISCOVERY_PROVIDERS + SUPPLEMENT_PROVIDERS
BASE_URLS = {'openalex':'https://api.openalex.org', 'europe_pmc':'https://www.ebi.ac.uk/europepmc/webservices/rest', 'crossref':'https://api.crossref.org', 'arxiv':'https://export.arxiv.org', 'biorxiv':'https://api.biorxiv.org', 'medrxiv':'https://api.biorxiv.org'}
TRANSIENT_HTTP = {500:'Internal Server Error', 502:'Bad Gateway', 503:'Service Unavailable', 504:'Gateway Timeout'}


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

    def fact(self):
        return dict(provider=self.provider, source=self.source.name, source_kind=self.source.kind,
                    status=self.status, candidates=self.candidates,
                    retained=len(self.records), total=self.total, limitations=list(self.limitations))


class DiscoveryError(ValueError):
    pass


class IdentityMismatch(DiscoveryError):
    pass


class ProviderHTTPError(DiscoveryError):
    def __init__(self, provider, status, *, detail=None):
        super().__init__(f'{provider}: HTTP {status}' + (f' ({detail})' if detail else ''))
        self.status = status


class UnsupportedSource(DiscoveryError):
    pass


class Cancelled(DiscoveryError):
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
    if provider == 'europe_pmc':
        return f'(TITLE_ABS:{value} OR KW:{value})'
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
    def __init__(self, provider, *, api_key=None, transport=None, cancel_event=None,
                 interval=None, sleep=time.sleep, page_size=100, pacing_state=None, progress_callback=None):
        if provider not in PROVIDERS:
            raise ValueError('Unknown Discovery Provider')
        self.progress = progress_callback
        self.provider = provider
        self.api_key = api_key
        self.cancel = cancel_event or Event()
        self.interval = 0.35 if interval is None else interval
        self.sleep = sleep
        self._access_restriction = None
        self.page_size = min(page_size, 1000)
        self.http = create_http_client(transport=transport, timeout=30, follow_redirects=True)
        self.pacing_state = pacing_state if pacing_state is not None else {}
        self.host = httpx.URL(BASE_URLS[provider]).host

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.http.close()

    def check_cancel(self):
        if self.cancel.is_set():
            raise Cancelled('Run cancelled')

    def _wait(self, seconds):
        self.check_cancel()
        if self.sleep is time.sleep:
            if self.cancel.wait(seconds):
                raise Cancelled('Run cancelled')
        else:
            self.sleep(seconds)
        self.check_cancel()

    def _get(self, url, params, headers, *, follow_redirects=True):
        self.check_cancel()
        delay = self.interval - (time.monotonic() - self.pacing_state.get(self.host, 0.0))
        if delay > 0:
            self._wait(delay)
        self.pacing_state[self.host] = time.monotonic()
        try:
            response = self.http.get(url, params=params, headers=headers, follow_redirects=follow_redirects)
        except httpx.HTTPError as error:
            raise DiscoveryError(f'{self.provider}: network request failed ({type(error).__name__})') from None
        self.check_cancel()
        return response

    def request(self, path, params, *, response_format="json"):
        self.check_cancel()
        if self._access_restriction:
            raise DiscoveryError(self._access_restriction)
        params = dict(params)
        headers = {"Authorization":"Bearer " + self.api_key} if self.provider == "openalex" and self.api_key else {}
        for attempt in range(3):
            response = self._get(BASE_URLS[self.provider] + path, params, headers)
            temporary_error = TRANSIENT_HTTP.get(response.status_code)
            html = ('text/html' in response.headers.get('content-type','').lower()
                    or response.text.lstrip().lower().startswith(('<!doctype html','<html')))
            # HTML is also used for ordinary gateway/service errors. A known
            # challenge is an access restriction, regardless of its HTTP status.
            challenge = html and any(marker in response.text.lower() for marker in (
                'anubis', 'captcha', 'cf-chl-', 'challenge-platform',
                'verify you are human', 'checking your browser',
            ))
            if challenge or (html and response.status_code == 202):
                kind = 'Anubis verification' if 'anubis' in response.text.lower() else 'an HTML verification page'
                self._access_restriction = (f'{self.provider}: access limited by {kind} (HTTP {response.status_code}); '
                                            'further automatic requests to this provider are stopped for this Run')
                raise DiscoveryError(self._access_restriction)
            if (response.status_code == 429 or temporary_error) and attempt < 2:
                default_delay = 5 * (2 ** attempt) if temporary_error else 1
                retry = response.headers.get('retry-after', str(default_delay))
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()
                    except (ValueError, TypeError):
                        delay = default_delay
                if not math.isfinite(delay):
                    delay = default_delay
                if self.progress:
                    self.progress(ProgressEvent(activity=ActivityUpdate(
                        kind=ActivityKind.RETRYING, source=self.provider, operation='http_retry',
                        label=f'{self.provider}: HTTP {response.status_code} {temporary_error or "Too Many Requests"}',
                        detail=f'Retry {attempt + 2}/3 in {max(0, delay):g} seconds',
                    )))
                self._wait(max(0, delay))
                continue
            if temporary_error:
                raise ProviderHTTPError(self.provider, response.status_code, detail=f'{temporary_error} after 3 attempts')
            if response.status_code != 200:
                raise ProviderHTTPError(self.provider, response.status_code)
            if html:
                raise DiscoveryError(f'{self.provider}: unexpected HTML response instead of API metadata')
            if response_format == "xml":
                return response.text
            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError
                return data
            except ValueError:
                raise DiscoveryError(f'{self.provider}: invalid JSON response') from None
        raise DiscoveryError(f'{self.provider}: rate limited')

    def discover(self, source, ast, from_date, to_date):
        if self.provider not in DISCOVERY_PROVIDERS:
            return DiscoveryResult(self.provider, source, "skipped", limitations=("Metadata-only Provider",))
        records, limits, candidates, total = [], [], 0, None
        try:
            if source.kind != 'journal':
                return DiscoveryResult(self.provider, source, 'skipped', limitations=('Only journal discovery is supported',))
            compile_query(ast,self.provider)  # Capability validation precedes source-resolution HTTP.
            pages = self._pages(source, ast, from_date, to_date)
            for raw, page_total, page_limits in pages:
                total = page_total
                limits.extend(item for item in page_limits if item not in limits)
                if raw is None:
                    if self.progress:
                        self.progress(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                            operation='discovery:'+source.key,label=self.provider+' records',source=self.provider,
                            detail=source.name,current=candidates,total=total,unit='work')))
                    continue
                candidates += 1
                evidence = self.normalize(raw, source)
                if evidence is not None:
                    evidence = evidence.model_copy(update={'provenance':evidence.provenance.model_copy(update={'role':'discovery'})})
                if evidence is not None:
                    records.append(evidence)
            status = 'partial' if any(x.startswith(('Truncated:', 'Incomplete:')) for x in limits) else 'complete' if records else 'empty'
        except UnsupportedSource as error:
            limits.append(str(error)); status = 'skipped'
        except Cancelled as error:
            limits.append(str(error)); status = 'cancelled'
        except (DiscoveryError, ValueError, KeyError, TypeError, AttributeError) as error:
            limits.append(str(error)); status = 'partial' if candidates else 'failed'
        return DiscoveryResult(self.provider, source, status, tuple(records), tuple(dict.fromkeys(limits)), candidates, total)

    def _pages(self, source, ast, start, end):
        if self.provider == 'europe_pmc':
            yield from self._europe_pmc_pages(source, ast, start, end)
            return
        if self.provider != 'openalex':
            raise DiscoveryError('Provider adapter unavailable')
        if not source.issns:
            raise DiscoveryError('OpenAlex requires a journal ISSN mapping')
        ids = []
        for issn in source.issns:
            try:
                item = self.request('/sources/issn:' + quote(issn, safe=''), {})
            except ProviderHTTPError as error:
                if error.status != 404:
                    raise
                yield None, None, (f'Incomplete: OpenAlex has no Source mapping for ISSN {issn} (HTTP 404)',)
                continue
            if issn not in item.get('issn', []) or not re.fullmatch(r'https://openalex.org/S\d+', str(item.get('id',''))):
                raise DiscoveryError('OpenAlex returned an unverified journal mapping')
            ids.append(item['id'].rsplit('/',1)[-1])
        if not ids:
            raise DiscoveryError('OpenAlex has no verified Source mapping for this Journal')
        ids = sorted(set(ids))
        params = {'filter':f'primary_location.source.id:{"|".join(ids)},from_publication_date:{start},to_publication_date:{end}',
                  'search.title_abstract_keywords' + ('.exact' if _prefix(ast) else ''):compile_query(ast, 'openalex'),
                  'per_page':self.page_size, 'cursor':'*'}
        seen, count = set(), 0
        while True:
            data = self.request('/works', params)
            rows = data.get('results')
            if not isinstance(rows, list):
                raise DiscoveryError('OpenAlex response is missing results')
            total = _positive(data.get('meta',{}).get('count'), 'count')
            yield None, total, ()
            for raw in rows:
                count += 1
                yield raw, total, ()
            cursor = data.get('meta',{}).get('next_cursor')
            if not cursor:
                if count < total:
                    raise DiscoveryError('Truncated: pagination ended before advertised total')
                return
            if not rows or cursor in seen:
                raise DiscoveryError('Incomplete: repeated or empty page')
            seen.add(cursor); params['cursor'] = cursor

    def normalize(self, raw, source):
        from allfold.providers.discovery_evidence import normalize_openalex, normalize_europe_pmc
        normalizer = {'openalex': normalize_openalex, 'europe_pmc': normalize_europe_pmc}.get(self.provider)
        if normalizer is None:
            raise DiscoveryError('Provider normalization unavailable')
        return normalizer(raw, source)

    def _europe_pmc_pages(self, source, ast, start, end):
        if not source.issns:
            raise DiscoveryError('Europe PMC requires a journal ISSN mapping')
        query = f'({" OR ".join("ISSN:" + issn for issn in source.issns)}) AND FIRST_PDATE:[{start} TO {end}] AND {compile_query(ast, "europe_pmc")}'
        yield from self._europe_pages(query)

    def _europe_pages(self, query):
        cursor, seen, count = '*', set(), 0
        while True:
            data = self.request('/search',{'query':query,'format':'json','resultType':'core','pageSize':self.page_size,'cursorMark':cursor})
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
        if self.provider == 'openalex' and namespace in {'doi','openalex'}:
            target = 'https://doi.org/' + identifier if namespace == 'doi' else identifier.rsplit('/',1)[-1]
            raw = self.request('/works/' + quote(target,safe='/:'),{})
            venue = (raw.get('primary_location') or {}).get('source') or {}
            evidence = self.normalize(raw,SourceScope('journal',venue.get('display_name') or ''))
            return (evidence,) if evidence is not None else ()
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
