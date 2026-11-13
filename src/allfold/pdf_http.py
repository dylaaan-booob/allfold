"""Owned, finite discovery HTTP and conditional API reads.

No Cookie jar is exported from Chromium. Public DNS answers are checked at each
HTTPX request boundary (including redirects); the OS/HTTP proxy may resolve again
when connecting, so this is not DNS pinning or a claim against DNS rebinding.
Native prepared-session operations keep their own captured access boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import ipaddress
import json
import socket
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from allfold.identifiers import valid_doi
from allfold.pdf_discovery import CandidateResult, CurrentResponse, P2Resolution, PdfSourceReadError
from allfold.pdf_rules import KnownPdfUrl, PdfRuleInputs, content_platform, iter_p2_candidates
from allfold.providers.provider_http import (ProviderReadClient, ProviderFailure,
    ProviderHTTPError, Cancelled, ProviderBudgetExceeded)
from allfold.url_safety import normalize_public_http_url


class UnsafePdfTarget(ValueError):
    pass


class PdfResponseTooLarge(ValueError):
    pass


def public_dns_addresses(host, port):
    return tuple(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM))


def check_public_request(request, *, resolver=public_dns_addresses):
    """Check the actual next request, not just a previously seen landing URL."""
    try:
        normalize_public_http_url(str(request.url))
        addresses = resolver(request.url.host, request.url.port or (443 if request.url.scheme == 'https' else 80))
        if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
            raise ValueError('Non-public DNS answer')
    except (ValueError, OSError):
        raise UnsafePdfTarget('PDF request target is not a verified public destination') from None


_SECRET_HEADERS = ('cookie', 'authorization', 'proxy-authorization', 'x-els-apikey',
    'x-els-insttoken', 'x-api-key', 'wiley-tdm-client-token')
_API_SCOPES = {
    'elsevier': ('api.elsevier.com', '/content/article/', 'X-ELS-APIKey'),
    'wiley_tdm': ('api.wiley.com', '/onlinelibrary/tdm/v1/articles/', 'Wiley-TDM-Client-Token'),
    'aps_harvest': ('harvest.aps.org', '/v2/journals/articles/', 'X-API-Key'),
}


class _FiniteReader(ProviderReadClient):
    def _decode(self, response, decode):
        if response.status_code != 200:
            raise ProviderHTTPError(self.provider, response.status_code)
        return decode(response)


class PdfHttpClient:
    """One synchronous task's client; response lifetime encloses its consumer.

    transfer receives the CURRENT streaming HTTPX response for a PDF. It is the
    later transfer layer's responsibility to report its normal terminal. Without
    that capability a PDF is pending, never falsely reported as downloaded.
    """
    def __init__(self, *, guard, cancel_event, deadline, pacing_state=None,
                 credentials=(), resolver=public_dns_addresses, **http_options):
        self._guard, self._resolver = guard, resolver
        self._credentials = dict(credentials)
        if not self._credentials.keys() <= {'ieee', 'elsevier', 'wiley_tdm', 'aps_harvest', 'springer_metadata'}:
            raise ValueError('Unknown optional PDF capability')
        self._credential = None
        self._reader = _FiniteReader('pdf-discovery', guard=guard, cancel_event=cancel_event,
            deadline=deadline, pacing_state=pacing_state, request_url_guard=self._before_request, **http_options)
        self.closed = False

    @property
    def capabilities(self):
        return frozenset(name for name, secret in self._credentials.items() if secret)

    def _before_request(self, request):
        self._reader.check_parent_deadline()
        check_public_request(request, resolver=self._resolver)
        self._reader.check_parent_deadline()
        for name in _SECRET_HEADERS:
            request.headers.pop(name, None)
        if self._credential:
            name, expected_host, prefix, header, value = self._credential
            if (request.url.scheme == 'https' and request.url.host == expected_host
                    and (request.url.port or 443) == 443 and request.url.path.startswith(prefix)):
                if header:
                    request.headers[header] = value
            elif value and value in str(request.url):
                raise UnsafePdfTarget('API credential cannot follow an unrelated redirect')

    def openalex_request_guard(self, request):
        """The exact DOI Provider shares checks but keeps its own owned client."""
        self._reader.check_parent_deadline()
        check_public_request(request, resolver=self._resolver)
        for name in ('cookie', 'proxy-authorization'):
            request.headers.pop(name, None)
        if request.url.host != 'api.openalex.org' or request.url.scheme != 'https':
            request.headers.pop('authorization', None)
        self._reader.check_parent_deadline()

    def _read(self, url, decode, *, headers=None, credential=None):
        if self.closed:
            raise RuntimeError('PDF task HTTP client is closed')
        self._reader.check_parent_deadline()
        self._credential = credential
        try:
            result = self._reader.read(lambda: self._reader.http.build_request('GET', url,
                headers={'User-Agent': 'allfold/0.1.0', **(headers or {})}), self._reader.operation(),
                decode=decode, follow_redirects=True, stream=True)
            self._reader.check_parent_deadline()
            return result
        except BaseException:
            self._reader.check_parent_deadline()
            raise
        finally:
            self._credential = None

    @staticmethod
    def bounded_response(response):
        body = bytearray()
        for chunk in response.iter_bytes():
            if len(body) + len(chunk) > 262144:
                raise PdfResponseTooLarge('Discovery response exceeds read-only parse budget')
            body.extend(chunk)
        # HTTPX response.request.url is the real final request after redirects.
        return CurrentResponse(str(response.request.url), response.headers.get('content-type', ''),
            bytes(body), response.status_code)

    def consume(self, candidate, *, transfer=None):
        headers = {}
        if candidate.referer:
            headers['Referer'] = candidate.referer
        if candidate.accept:
            headers['Accept'] = candidate.accept
        credential = None
        if candidate.credential:
            if candidate.credential not in self.capabilities or candidate.credential not in _API_SCOPES:
                return CandidateResult.failed('credential-unavailable')
            host, prefix, header = _API_SCOPES[candidate.credential]
            url = urlsplit(candidate.url)
            if url.scheme != 'https' or url.hostname != host or not url.path.startswith(prefix):
                return CandidateResult.failed('credential-scope')
            credential = (candidate.credential, host, prefix, header, self._credentials[candidate.credential])
        def decode(response):
            if response.headers.get('content-type', '').partition(';')[0].strip().lower() == 'application/pdf':
                return transfer(response, candidate) if transfer is not None else CandidateResult.pdf()
            return CandidateResult.current(self.bounded_response(response))
        try:
            return self._read(candidate.url, decode, headers=headers, credential=credential)
        except ProviderHTTPError as error:
            return CandidateResult.failed({401: 'authorization', 403: 'authorization', 402: 'quota',
                404: 'not-found'}.get(error.status, 'source-failed'))
        except (ProviderFailure, UnsafePdfTarget, PdfResponseTooLarge):
            return CandidateResult.failed('source-failed')

    def json(self, url, *, credential=None):
        def decode(response):
            current = self.bounded_response(response)
            try:
                result = json.loads(current.body)
                if not isinstance(result, dict):
                    raise ValueError('Expected an object')
                return result
            except (ValueError, UnicodeDecodeError):
                raise ProviderFailure('PDF API returned invalid JSON', kind='protocol', code='invalid-json') from None
        return self._read(url, decode, headers={'Accept': 'application/json'}, credential=credential)

    def close(self):
        if not self.closed:
            self._reader.http.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _qualified_known(inputs, url, rule, field):
    try:
        known = KnownPdfUrl(url, rule, field)
        return replace(inputs, known_pdf_urls=tuple(dict.fromkeys((*inputs.known_pdf_urls, known)))[:16])
    except ValueError:
        return inputs


def ieee_metadata_inputs(raw, target, inputs, *, rule='API03'):
    """Only an exact DOI record may supply a real article_number or PDF field."""
    if rule not in {'API03', 'API04'}:
        raise ValueError('Unsupported IEEE metadata response')
    rows = raw.get('articles') if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) > 25:
        return inputs
    for row in rows:
        if not isinstance(row, dict) or valid_doi(row.get('doi')) != target.identity_doi:
            continue
        number = str(row.get('article_number', ''))
        if number.isascii() and number.isdecimal() and 1 <= len(number) <= 16:
            inputs = replace(inputs, identifiers=tuple(dict.fromkeys((*inputs.identifiers, ('article_number', number))))[:24])
        if isinstance(row.get('pdf_url'), str):
            inputs = _qualified_known(inputs, row['pdf_url'], rule, 'pdf_url')
        break
    return inputs


def springer_metadata_inputs(raw, target, inputs):
    rows = raw.get('records') if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) > 25:
        return inputs
    for row in rows:
        if not isinstance(row, dict) or valid_doi(row.get('doi')) != target.identity_doi:
            continue
        for entry in row.get('url', ()) if isinstance(row.get('url'), list) else ():
            if isinstance(entry, dict) and entry.get('format', '').lower() == 'pdf' and isinstance(entry.get('value'), str):
                inputs = _qualified_known(inputs, entry['value'], 'API09', 'url.pdf')
        break
    return inputs


class PdfDiscoveryIO:
    """Only actual missing-input/API operations; no default platform client list."""
    def __init__(self, http, *, document_context=None, openalex_client=None):
        self.http, self.context, self._openalex = http, document_context, openalex_client

    @property
    def openalex_available(self):
        return self._openalex is not None

    def query_missing(self, target, inputs, facts):
        doi, route = target.identity_doi, target
        if not doi:
            return
        # DOI registration is useful when the content target or a routable ID is
        # missing; a confirmed platform does not force resolver traffic.
        platform = content_platform(route)
        needs_id = platform in {'sciencedirect', 'cell', 'ieee', 'oup', 'jstor'}
        if not platform or needs_id:
            try:
                raw = self.http.json('https://doi.org/api/handles/' + quote(doi, safe='/'))
                rows = raw.get('values', ())
                urls = [row.get('data', {}).get('value') for row in rows if isinstance(row, dict)
                    and row.get('type') == 'URL' and isinstance(row.get('data'), dict)] if isinstance(rows, list) else []
                url = next((value for value in urls if isinstance(value, str) and _public_url(value)), None)
                if url:
                    route = replace(target, article_url=url)
                    platform = content_platform(route)
                yield P2Resolution(inputs, url)
                if tuple(iter_p2_candidates(route, replace(inputs, target=route))):
                    return
            except (ProviderFailure, UnsafePdfTarget, PdfResponseTooLarge) as error:
                yield P2Resolution(inputs, diagnostic=_failure_code(error))
        # Only the known platforms requiring these fields, or an unresolved
        # target, need Crossref; not every publisher after a template failure.
        cached = next((f for f in facts if f.source == 'crossref'), None)
        if platform in {None, 'sciencedirect', 'cell'} and (cached is None or cached.status != 'complete'
                or any(c.refresh for c in cached.candidates)):
            try:
                raw = self.http.json('https://api.crossref.org/works/' + quote(doi, safe=''))
                row = raw.get('message')
                if isinstance(row, dict) and valid_doi(row.get('DOI')) == doi:
                    alternatives = row.get('alternative-id', ())
                    if isinstance(alternatives, list):
                        inputs = replace(inputs, alternative_ids=tuple(dict.fromkeys((*inputs.alternative_ids,
                            *(v for v in alternatives if isinstance(v, str) and len(v) <= 512))))[:24])
                    for entry in row.get('link', ()) if isinstance(row.get('link'), list) else ():
                        if isinstance(entry, dict) and entry.get('content-type', '').partition(';')[0].lower() == 'application/pdf' and isinstance(entry.get('URL'), str):
                            inputs = _qualified_known(inputs, entry['URL'], 'API02', 'link')
                    primary = row.get('resource', {}).get('primary', {}) if isinstance(row.get('resource'), dict) else {}
                    url = primary.get('URL') if isinstance(primary, dict) else None
                    if url and _public_url(url):
                        route = replace(target, article_url=url)
                        platform = content_platform(route)
                yield P2Resolution(inputs, route.article_url)
                if tuple(iter_p2_candidates(route, replace(inputs, target=route))):
                    return
            except (ProviderFailure, UnsafePdfTarget, PdfResponseTooLarge) as error:
                yield P2Resolution(inputs, diagnostic=_failure_code(error))
        if platform == 'ieee' and 'ieee' in self.http.capabilities:
            try:
                key = self.http._credentials['ieee']
                raw = self.http.json('https://ieeexploreapi.ieee.org/api/v1/search/articles?' + urlencode(
                    {'doi': doi, 'apikey': key}), credential=('ieee', 'ieeexploreapi.ieee.org', '/api/v1/', None, key))
                yield P2Resolution(ieee_metadata_inputs(raw, target, inputs), route.article_url)
            except (ProviderFailure, UnsafePdfTarget, PdfResponseTooLarge) as error:
                yield P2Resolution(inputs, diagnostic=_failure_code(error))
        if platform == 'springer' and 'springer_metadata' in self.http.capabilities:
            try:
                key = self.http._credentials['springer_metadata']
                raw = self.http.json('https://api.springernature.com/meta/v2/json?' + urlencode(
                    {'q': 'doi:' + doi, 'api_key': key}), credential=('springer_metadata', 'api.springernature.com', '/meta/v2/', None, key))
                yield P2Resolution(springer_metadata_inputs(raw, target, inputs), route.article_url)
            except (ProviderFailure, UnsafePdfTarget, PdfResponseTooLarge) as error:
                yield P2Resolution(inputs, diagnostic=_failure_code(error))

    def document(self, target):
        if self.context is None:
            return None
        from allfold.application.document_metadata import read_document_pdf_clues, DocumentMetadataFailed
        try:
            return read_document_pdf_clues(self.context, confirmed_article_url=target.article_url)
        except DocumentMetadataFailed:
            raise PdfSourceReadError('Article PDF clues were not retrieved') from None

    def reader(self, candidate, response):
        from allfold.application.document_metadata import read_document_pdf_clues, DocumentMetadataFailed
        from allfold.pdf_responses import access_limited, reader_context
        reader = reader_context(candidate, response.url)
        if self.context is None or reader is None or access_limited(response):
            return None
        try:
            return read_document_pdf_clues(self.context, confirmed_article_url=candidate.target.article_url, reader=reader)
        except DocumentMetadataFailed:
            raise PdfSourceReadError('Known reader PDF clues were not retrieved') from None

    def openalex(self, doi):
        if self._openalex is None:
            return {}
        return self._openalex.get_work_by_doi(doi)


def _public_url(value):
    try:
        return normalize_public_http_url(value)
    except ValueError:
        return None


def _failure_code(error):
    return {401: 'authorization', 403: 'authorization', 402: 'quota', 404: 'not-found'}.get(
        getattr(error, 'status', None), 'source-failed')
