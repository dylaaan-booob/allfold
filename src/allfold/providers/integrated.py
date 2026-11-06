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
from allfold.keywords import And, Or, Prefix, Phrase, Proximity, matches_fields
from allfold.models import Author, ExternalIds, MetadataSource, ProviderWorkEvidence, ProviderTopic, EvidenceDate, EvidenceDateKind

LICENSE_REDACTION = "zbMATH Open Web Interface contents unavailable due to conflicting licenses."


def available_zbmath_text(value):
    return value.strip() if isinstance(value,str) and value.strip() and value.strip()!=LICENSE_REDACTION else None


DISCOVERY_PROVIDERS = ('openalex', 'europe_pmc', 'dblp', 'zbmath')
SUPPLEMENT_PROVIDERS = ('crossref', 'arxiv', 'biorxiv', 'medrxiv')
PROVIDERS = DISCOVERY_PROVIDERS + SUPPLEMENT_PROVIDERS
BASE_URLS = {'openalex':'https://api.openalex.org', 'europe_pmc':'https://www.ebi.ac.uk/europepmc/webservices/rest', 'dblp':'https://dblp.org', 'zbmath':'https://api.zbmath.org/v1', 'crossref':'https://api.crossref.org', 'arxiv':'https://export.arxiv.org', 'biorxiv':'https://api.biorxiv.org', 'medrxiv':'https://api.biorxiv.org'}
TRANSIENT_HTTP = {500:'Internal Server Error', 502:'Bad Gateway', 503:'Service Unavailable', 504:'Gateway Timeout'}


@dataclass(frozen=True)
class SourceScope:
    kind: str
    name: str
    key: str = ''
    issns: tuple[str, ...] = ()
    stream: str | None = None


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
                    stream=self.source.stream, status=self.status, candidates=self.candidates,
                    retained=len(self.records), total=self.total, limitations=list(self.limitations))


class DiscoveryError(ValueError):
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
        op = ('&' if isinstance(ast, And) else '|') if provider == 'zbmath' else ('AND' if isinstance(ast, And) else 'OR')
        return f'({compile_query(ast.left, provider)} {op} {compile_query(ast.right, provider)})'
    value = _word(ast)
    if provider == 'europe_pmc':
        return f'(TITLE_ABS:{value} OR KW:{value})'
    if provider == 'zbmath':
        return f'(ti:{value} | ut:{value} | cc:{value})'
    return value


def _prefix(ast):
    return _prefix(ast.left) or _prefix(ast.right) if isinstance(ast, (And, Or)) else isinstance(ast, Prefix)


def _rows(value):
    return value if isinstance(value, list) else [value] if isinstance(value, dict) else []


def _positive(value, name):
    try:
        number = int(value)
        if number < 0 or isinstance(value, bool):
            raise ValueError
        return number
    except (ValueError, TypeError):
        raise DiscoveryError(f'Invalid {name} in provider response') from None


def _dblp_page(data, offset):
    result = data.get('result') if isinstance(data, dict) else None
    hits = result.get('hits') if isinstance(result, dict) else None
    if not isinstance(hits, dict):
        raise DiscoveryError('Invalid DBLP result structure')
    total = _positive(hits.get('@total'), 'total')
    computed = _positive(hits.get('@computed'), 'computed')
    first = _positive(hits.get('@first'), 'first')
    if first != offset:
        raise DiscoveryError('Incomplete: DBLP returned a repeated or unexpected first offset')
    raw = hits.get('hit')
    if raw is not None and not isinstance(raw, (list, dict)):
        raise DiscoveryError('Invalid DBLP publication list')
    rows = _rows(raw)
    if any(not isinstance(row, dict) or not isinstance(row.get('info'), dict) for row in rows):
        raise DiscoveryError('Invalid DBLP publication structure')
    if not rows and offset < min(total, computed):
        raise DiscoveryError('Incomplete: DBLP returned an empty page before the accessible total')
    return rows, total, computed


class DiscoveryClient:
    """One provider/host owns rate limits, bounded retry and cancellation checks."""
    def __init__(self, provider, *, api_key=None, transport=None, cancel_event=None,
                 interval=None, sleep=time.sleep, max_pages=50, max_records=5000, page_size=100, pacing_state=None, progress_callback=None):
        if provider not in PROVIDERS:
            raise ValueError('Unknown Discovery Provider')
        self.progress = progress_callback
        self.provider = provider
        self.api_key = api_key
        self.cancel = cancel_event or Event()
        self.interval = (2.0 if provider == 'dblp' else 0.35) if interval is None else interval
        self.sleep = sleep
        self._access_restriction = None
        self._metarefresh_attempted = False
        self.max_pages, self.max_records, self.page_size = max_pages, max_records, min(page_size, 1000)
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

    def _dblp_metarefresh(self, response):
        if self.provider != 'dblp' or self._metarefresh_attempted:
            return response
        from allfold.providers.dblp_metarefresh import recovery_plan, same_query
        plan = recovery_plan(response)
        if plan is None:
            return response
        self._metarefresh_attempted = True
        delay, target = plan
        if self.progress:
            self.progress(ProgressEvent(activity=ActivityUpdate(kind=ActivityKind.WORKING,
                source='dblp', operation='dblp_metarefresh', label='DBLP: metarefresh verification',
                detail=f'Waiting {delay:g} seconds before resuming the original query')))
        try:
            self._wait(delay)
            verified = self._get(target, None, {}, follow_redirects=False)
            original = str(response.request.url)
            location = verified.headers.get('location')
            if verified.status_code not in (302, 303) or not location or not same_query(location, original):
                raise DiscoveryError('Verification did not return to the original query')
            resumed = self._get(original, None, {}, follow_redirects=False)
            if (resumed.status_code != 200 or 'text/html' in resumed.headers.get('content-type', '').lower()
                    or resumed.text.lstrip().lower().startswith(('<!doctype html', '<html'))):
                raise DiscoveryError('Verification did not return API metadata')
            try:
                data = resumed.json()
            except ValueError:
                raise DiscoveryError('Verification did not return JSON') from None
            _dblp_page(data, _positive(response.request.url.params.get('f', '0'), 'requested offset'))
            return resumed
        except Cancelled:
            raise
        except DiscoveryError:
            self._access_restriction = 'dblp: access limited; metarefresh recovery failed; further requests stopped for this Run'
            raise DiscoveryError(self._access_restriction) from None

    def request(self, path, params, *, response_format="json"):
        self.check_cancel()
        if self._access_restriction:
            raise DiscoveryError(self._access_restriction)
        params = dict(params)
        headers = {"Authorization":"Bearer " + self.api_key} if self.provider == "openalex" and self.api_key else {}
        for attempt in range(3):
            response = self._get(BASE_URLS[self.provider] + path, params, headers)
            response = self._dblp_metarefresh(response)
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
                if delay > 60:
                    raise ProviderHTTPError(self.provider, response.status_code,
                        detail=f'{temporary_error or "Too Many Requests"}; Retry-After exceeds this Run budget')
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
            if source.kind == 'conference' and self.provider != 'dblp':
                return DiscoveryResult(self.provider, source, 'skipped', limitations=('Conference discovery requires DBLP',))
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
                if self.provider=='zbmath' and LICENSE_REDACTION in str(raw) and 'zbMATH metadata restricted by licensing' not in limits:
                    limits.append('zbMATH metadata restricted by licensing')
                if self.provider == "dblp" and not matches_fields(ast, (raw.get("title", ""),)):
                    continue
                evidence = self.normalize(raw, source)
                if evidence is not None:
                    evidence = evidence.model_copy(update={'provenance':evidence.provenance.model_copy(update={'role':'discovery'})})
                if evidence is not None:
                    records.append(evidence)
            if records and self.provider in {'dblp','zbmath'} and ((from_date.month,from_date.day)!=(1,1) or (to_date.month,to_date.day)!=(12,31)):
                limits.append('Incomplete: year-only source dates cannot establish exact monthly coverage')
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
        if self.provider == 'zbmath':
            yield from self._zbmath_pages(source, ast, start, end)
            return
        if self.provider == 'dblp':
            yield from self._dblp_pages(source, ast, start, end)
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
        for page in range(self.max_pages):
            data = self.request('/works', params)
            rows = data.get('results')
            if not isinstance(rows, list):
                raise DiscoveryError('OpenAlex response is missing results')
            total = _positive(data.get('meta',{}).get('count'), 'count')
            yield None, total, ()
            for raw in rows:
                count += 1
                yield raw, total, ()
                if count >= self.max_records and count < total:
                    raise DiscoveryError('Truncated: application record budget reached')
            cursor = data.get('meta',{}).get('next_cursor')
            if not cursor:
                if count < total:
                    raise DiscoveryError('Truncated: pagination ended before advertised total')
                return
            if not rows or cursor in seen:
                raise DiscoveryError('Incomplete: repeated or empty page')
            seen.add(cursor); params['cursor'] = cursor
        raise DiscoveryError('Truncated: application page budget reached')

    def normalize(self, raw, source):
        if self.provider == 'europe_pmc':
            source_id, record_id = raw.get('source'), raw.get('id')
            if not source_id or not record_id or not raw.get('title'):
                raise DiscoveryError('Europe PMC record lacks source, identity or title')
            ids = {'europe_pmc':f'{source_id}:{record_id}', 'doi':normalize_doi(raw.get('doi'))}
            if source_id == 'MED': ids['pmid'] = str(record_id)
            if raw.get('pmcid'): ids['pmcid'] = raw['pmcid']
            keywords = raw.get('keywordList',{}).get('keyword',[])
            return ProviderWorkEvidence(provenance=MetadataSource(provider='europe_pmc', record_id=f'{source_id}:{record_id}', retrieved_at=datetime.now(timezone.utc),url='https://europepmc.org/article/'+quote(str(source_id),safe='')+'/'+quote(str(record_id),safe='')),
                title=raw['title'], journal=source.name or None, publication_type='preprint' if source_id == 'PPR' else 'journal', publication_date=raw.get('firstPublicationDate'), abstract=raw.get('abstractText'),
                external_ids=ExternalIds(**ids), monitor_journal_issns=source.issns,
                indexed_terms=tuple(ProviderTopic(value=k,source='europe_pmc',kind='keyword') for k in keywords if isinstance(k,str) and k) + tuple(ProviderTopic(value=k['descriptorName'],source='europe_pmc',kind='mesh') for k in raw.get('meshHeadingList',{}).get('meshHeading',[]) if k.get('descriptorName')),
                authors=tuple(Author(name=x['fullName']) for x in raw.get('authorList',{}).get('author',[]) if x.get('fullName')))
        if self.provider == 'zbmath':
            title = available_zbmath_text(raw.get('title',{}).get('title'))
            if not raw.get('id'):
                raise DiscoveryError('zbMATH record lacks identity')
            ids = {'zbmath':str(raw['id'])}
            for link in raw.get('links',[]):
                if link.get('type') == 'doi' and normalize_doi(link.get('identifier')):
                    ids['doi'] = normalize_doi(link['identifier'])
                if link.get('type') == 'arxiv' and link.get('identifier'):
                    ids['arxiv'] = link['identifier']
            return ProviderWorkEvidence(provenance=MetadataSource(provider='zbmath', record_id=str(raw['id']), retrieved_at=datetime.now(timezone.utc),url='https://zbmath.org/'+quote(str(raw['id']),safe=''),licenses=tuple(item for item in raw.get('license',[]) if isinstance(item,str) and item)),
                title=title, journal=available_zbmath_text(source.name), publication_type='preprint' if raw.get('database') == 'arXiv' else 'journal', external_ids=ExternalIds(**ids),
                publication_date=str(raw['year']) if raw.get('year') else None,
                dates=(EvidenceDate(kind=EvidenceDateKind.ISSUED,year=int(raw['year'])),) if raw.get('year') else (),
                indexed_terms=tuple(ProviderTopic(value=str(k.get('code') or k.get('text')),source='zbmath',kind='msc') for k in raw.get('msc',[]) if k.get('code') or k.get('text')) + tuple(ProviderTopic(value=k,source='zbmath',kind='keyword') for k in raw.get('keywords',[]) if available_zbmath_text(k)),
                authors=tuple(Author(name=x['name']) for x in raw.get('contributors',{}).get('authors',[]) if available_zbmath_text(x.get('name'))),
                monitor_journal_issns=source.issns)
        if self.provider == 'dblp':
            key, title = raw.get('key'), raw.get('title')
            if not key or not title:
                raise DiscoveryError('DBLP record lacks publication key or title')
            editions = raw.get('ee',[])
            editions = editions if isinstance(editions,list) else [editions]
            edition_dois = set()
            for item in editions:
                value = item.get('text') or item.get('#text') if isinstance(item,dict) else item
                if isinstance(value,str) and value.startswith(('https://doi.org/','http://doi.org/','https://dx.doi.org/','http://dx.doi.org/')):
                    doi = valid_doi(value)
                    if doi: edition_dois.add(doi)
            primary = valid_doi(raw.get('doi')) or next(iter(sorted(edition_dois)),None)
            names = raw.get('authors', {}).get('author', [])
            names = names if isinstance(names, list) else [names]
            return ProviderWorkEvidence(provenance=MetadataSource(provider='dblp', record_id=key, retrieved_at=datetime.now(timezone.utc),url='https://dblp.org/rec/'+quote(key,safe='/')),
                title=title, journal=source.name if source.kind == 'journal' else None,
                conference=source.name if source.kind == 'conference' else None, conference_id=source.key or source.stream if source.kind == 'conference' else None,
                publication_type=source.kind, publication_date=str(raw['year']) if raw.get('year') else None,
                external_ids=ExternalIds(dblp=key, doi=primary),related_dois=tuple(sorted(edition_dois-{primary})),
                dates=(EvidenceDate(kind=EvidenceDateKind.CONFERENCE_YEAR if source.kind == 'conference' else EvidenceDateKind.ISSUED,year=int(raw['year'])),) if raw.get('year') else (),
                authors=tuple(Author(name=x.get('text') if isinstance(x,dict) else x) for x in names if x),
                monitor_journal_issns=source.issns)
        if self.provider != 'openalex':
            raise DiscoveryError('Provider normalization unavailable')
        if (raw.get('primary_location') or {}).get('raw_type') == 'journal-issue':
            return None
        record_id = str(raw.get('id') or '')
        if not record_id or not raw.get('title'):
            raise DiscoveryError('OpenAlex record lacks identity or title')
        abstract = raw.get('abstract_inverted_index') or {}
        tokens = {i: word for word, positions in abstract.items() for i in positions}
        identifiers = {'openalex':record_id,'doi':normalize_doi(raw.get('doi'))}
        for namespace in ('pmid','pmcid'):
            identifier = normalize_external_id(namespace,(raw.get('ids') or {}).get(namespace))
            if identifier:
                identifiers[namespace] = identifier
        return ProviderWorkEvidence(provenance=MetadataSource(provider='openalex', record_id=record_id, retrieved_at=datetime.now(timezone.utc),url=record_id),
            title=raw['title'], journal=source.name or None, publication_type='preprint' if raw.get('type') in {'preprint','posted-content'} else 'journal', publication_date=raw.get('publication_date'),
            related_dois=tuple(sorted({doi for location in raw.get('locations',[]) if (doi:=normalize_doi(location.get('doi'))) and doi != normalize_doi(raw.get('doi'))})),
            abstract=' '.join(tokens[i] for i in sorted(tokens)) or None,
            external_ids=ExternalIds(**identifiers),
            monitor_journal_issns=source.issns,
            authors=tuple(Author(name=x['author']['display_name']) for x in raw.get('authorships',[]) if x.get('author',{}).get('display_name')))

    def _dblp_pages(self, source, ast, start, end):
        if not source.stream or not re.fullmatch(r'streams/(?:conf|journals)/[a-zA-Z0-9_/-]+',source.stream):
            raise UnsupportedSource('DBLP requires a verified source Stream mapping; this source was not queried')
        # DBLP has no reliable phrase/group syntax. Distribute into bounded CNF:
        # native whitespace AND / pipe OR generate a conservative superset,
        # then evaluate only this adapter's candidates against their titles.
        def cnf(node):
            if isinstance(node, And):
                clauses = cnf(node.left) + cnf(node.right)
            elif isinstance(node, Or):
                left, right = cnf(node.left), cnf(node.right)
                if len(left) * len(right) > 32:
                    raise DiscoveryError('DBLP expression exceeds the bounded Boolean expansion')
                clauses = [a + b for a in left for b in right]
            else:
                _word(node)
                return [[word + ('' if isinstance(node,Prefix) else '$')] for word in node.value.split()]
            if len(clauses) > 32:
                raise DiscoveryError('DBLP expression exceeds the bounded Boolean expansion')
            return clauses
        keywords = ' '.join('|'.join(dict.fromkeys(clause)) for clause in cnf(ast))
        years = '|'.join(f'year:{year}:' for year in range(start.year,end.year+1))
        query = f'streamid:{source.stream.removeprefix("streams/")}: {years} {keywords}'
        offset, seen, count = 0, set(), 0
        for page in range(self.max_pages):
            data = self.request('/search/publ/api',{'q':query,'format':'json','h':self.page_size,'f':offset})
            rows, total, computed = _dblp_page(data, offset)
            limits = ['DBLP title-only matching; year precision cannot establish exact monthly coverage']
            if computed < total:
                limits.append(f'Truncated: DBLP computed {computed} of {total} results')
            yield None, total, limits
            for row in rows:
                raw = row.get('info',{})
                key = raw.get('key') or str(raw.get('url','')).removeprefix('https://dblp.org/rec/')
                raw = dict(raw,key=key)
                if not key or key in seen:
                    raise DiscoveryError('Incomplete: DBLP repeated a publication or made no progress')
                seen.add(key); count += 1
                yield raw, total, limits
                if count >= self.max_records and count < min(total,computed):
                    raise DiscoveryError('Truncated: application record budget reached')
            offset += len(rows)
            if offset >= min(total,computed):
                return
        raise DiscoveryError('Truncated: application page budget reached')

    def _europe_pmc_pages(self, source, ast, start, end):
        if not source.issns:
            raise DiscoveryError('Europe PMC requires a journal ISSN mapping')
        query = f'({" OR ".join("ISSN:" + issn for issn in source.issns)}) AND FIRST_PDATE:[{start} TO {end}] AND {compile_query(ast, "europe_pmc")}'
        yield from self._europe_pages(query)

    def _europe_pages(self, query):
        cursor, seen, count = '*', set(), 0
        for page in range(self.max_pages):
            data = self.request('/search',{'query':query,'format':'json','resultType':'core','pageSize':self.page_size,'cursorMark':cursor})
            total = _positive(data.get('hitCount'), 'hitCount')
            rows = data.get('resultList',{}).get('result')
            if not isinstance(rows,list):
                raise DiscoveryError('Europe PMC response is missing resultList')
            yield None, total, ()
            for raw in rows:
                count += 1
                yield raw, total, ()
                if count >= self.max_records and count < total:
                    raise DiscoveryError('Truncated: application record budget reached')
            if count >= total:
                return
            cursor = data.get('nextCursorMark')
            if not rows or not cursor or cursor in seen:
                raise DiscoveryError('Incomplete: Europe PMC pagination made no progress')
            seen.add(cursor)
        raise DiscoveryError('Truncated: application page budget reached')

    def _zbmath_pages(self, source, ast, start, end):
        if not source.issns:
            raise DiscoveryError('zbMATH requires a verified journal ISSN mapping')
        serial_ids = set()
        for issn in source.issns:
            data = self.request('/serial/_search',{'search_string':'sn:' + issn,'results_per_page':100})
            rows, status = data.get('result'), data.get('status')
            if not isinstance(rows,list) or not isinstance(status,dict) or status.get('execution_bool') is not True:
                raise DiscoveryError('zbMATH serial mapping response is invalid or unsuccessful')
            for raw in rows:
                issns = [item.get('number') if isinstance(item,dict) else item for item in raw.get('issn',[])]
                if issn in issns and raw.get('id'):
                    serial_ids.add(str(raw['id']))
        if not serial_ids:
            raise UnsupportedSource('zbMATH has no verified journal serial mapping; source was not queried')
        # Several serial identities for one ISSN can be predecessor/successor or
        # translations. An ambiguous mapping cannot authorize extra sources.
        if len(serial_ids) != 1:
            raise UnsupportedSource('zbMATH journal serial mapping is ambiguous')
        query = f'se:{next(iter(serial_ids))} & py:{start.year}-{end.year} & {compile_query(ast,"zbmath")}'
        yield from self._zbmath_document_pages(query)

    def _zbmath_document_pages(self, query):
        count, seen = 0, set()
        for page in range(self.max_pages):
            data = self.request('/document/_search',{'search_string':query,'page':page,'results_per_page':self.page_size})
            status = data.get('status',{})
            if not status.get('execution_bool'):
                raise DiscoveryError('zbMATH query failed: ' + str(status.get('execution','unknown error')))
            total = _positive(status.get('nr_total_results'),'total')
            rows = data.get('result')
            if not isinstance(rows,list):
                raise DiscoveryError('zbMATH response is missing result')
            limits = ('zbMATH year precision cannot establish exact monthly coverage; review text is excluded',)
            yield None, total, limits
            for raw in rows:
                key = raw.get('id')
                if not key or key in seen:
                    raise DiscoveryError('Incomplete: zbMATH pagination made no progress')
                seen.add(key); count += 1
                yield raw, total, limits
                if count >= self.max_records and count < total:
                    raise DiscoveryError('Truncated: application record budget reached')
            if count >= total:
                return
            if not rows:
                raise DiscoveryError('Incomplete: zbMATH returned an empty page before total')
        raise DiscoveryError('Truncated: application page budget reached')

    def lookup(self, namespace, identifier):
        """Bounded exact-identifier metadata lookup; no keyword discovery fallback."""
        source = SourceScope('journal','')
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
        if self.provider == 'zbmath' and namespace in {'doi','zbmath'}:
            if namespace == 'zbmath':
                if not identifier.isdigit(): raise DiscoveryError('Invalid zbMATH ID')
                response = self.request('/document/' + identifier,{})
                rows = _rows(response.get('result'))
            else:
                identifier=normalize_doi(identifier)
                if not identifier or any(c in identifier for c in ('"', '\\')): raise DiscoveryError('Invalid DOI for native identifier lookup')
                rows = [raw for raw, _, _ in self._zbmath_document_pages(f'doi:"{identifier}"') if raw]
            return tuple(self.normalize(raw,SourceScope('journal',raw.get('source',{}).get('source') or '')) for raw in rows)
        return ()
