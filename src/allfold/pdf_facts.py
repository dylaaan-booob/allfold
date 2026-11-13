"""Bounded, non-secret PDF discovery metadata; no download or live-page authority.

Absent facts mean unknown. A complete snapshot with no candidates is distinct
from an incomplete/failed read. URLs here are reusable facts, not proof of PDF
content; expiring URLs are represented only by a typed refresh locator.
"""
from __future__ import annotations

from datetime import datetime
import re
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urldefrag, urlsplit

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from allfold.identifiers import normalize_external_id, strong_identifiers
from allfold.url_safety import normalize_public_http_url


Token = Annotated[str, StringConstraints(min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_.:-]+$')]
IdentifierValue = Annotated[str, StringConstraints(min_length=1, max_length=256, pattern=r'^[^\s\x00-\x1f\x7f]+$')]
DiscoveryStatus = Literal['complete', 'partial', 'failed']
DiscoveryDiagnostic = Literal['parse-failed', 'overflow', 'invalid-url', 'invalid-field',
    'incomplete-response', 'ephemeral-url', 'identity-mismatch']
RefreshKind = Literal['document-pdf', 'openalex-work', 'crossref-work']


class _Fact(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, revalidate_instances='always')


def ephemeral_pdf_url(value: str) -> bool:
    """Recognize common signature/session credential carriers without rewriting them."""
    for key, _ in parse_qsl(urlsplit(value).query, keep_blank_values=True):
        name = re.sub(r'[^a-z0-9]', '', key.casefold())
        if (name in {'token', 'accesstoken', 'authtoken', 'auth', 'authorization', 'signature',
                'sig', 'expires', 'expiry', 'apikey', 'key', 'credential', 'policy', 'keypairid',
                'session', 'sessionid', 'jsessionid', 'jwt', 'hmac', 'securitytoken'}
                or name.startswith(('xamz', 'xgoog'))):
            return True
    return bool(re.search(r';(?:jsessionid|sessionid)=', urlsplit(value).path, re.I))


def stable_discovery_url(value: str | None) -> str | None:
    """Keep an already public stable URL verbatim; never manufacture an unsigned URL."""
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        normalized = normalize_public_http_url(value)
        return normalized if normalized and not ephemeral_pdf_url(normalized) else None
    except ValueError:
        return None


def _stable_url(value):
    if value is not None and stable_discovery_url(value) != value:
        raise ValueError('Discovery metadata requires a stable public URL without session/signature credentials')
    return value


class PdfRefreshLocator(_Fact):
    kind: RefreshKind
    landing_url: str | None = None

    _url = field_validator('landing_url')(_stable_url)


class PdfIdentifier(_Fact):
    kind: Token
    value: IdentifierValue
    rule_id: Token


class PdfCandidateFact(_Fact):
    stage: Literal['P1', 'P2', 'P3', 'P4', 'P5']
    rule_id: Token
    url: str | None = None
    action: Literal['refresh_form', 'refresh_document', 'reader', 'post_response'] | None = None
    reader_kind: Token | None = None
    referer: str | None = None
    field: Token | None = None
    refresh: PdfRefreshLocator | None = None

    _urls = field_validator('url', 'referer')(_stable_url)

    @model_validator(mode='after')
    def require_locator(self):
        if self.url is None and self.action is None and self.refresh is None:
            raise ValueError('A PDF candidate requires a URL, fixed action or refresh locator')
        return self


def persistent_pdf_candidate(*, refresh_kind: RefreshKind, landing_url=None, **values):
    """Convert a current expiring clue to metadata without retaining its signed URL."""
    url = values.get('url')
    if url is not None:
        normalize_public_http_url(url)
        if ephemeral_pdf_url(url):
            values['url'] = None
            values['refresh'] = PdfRefreshLocator(kind=refresh_kind,
                landing_url=stable_discovery_url(landing_url))
    if values.get('referer') and stable_discovery_url(values['referer']) is None:
        values['referer'] = None
        values.setdefault('refresh', PdfRefreshLocator(kind=refresh_kind,
            landing_url=stable_discovery_url(landing_url)))
    return PdfCandidateFact(**values)


class PdfLinkFact(_Fact):
    kind: Literal['pdf', 'landing', 'jats', 'json', 'other']
    url: str
    field: Token
    content_type: Annotated[str, StringConstraints(min_length=1, max_length=128,
        pattern=r'^[A-Za-z0-9.+/-]+$')] | None = None

    _url = field_validator('url')(_stable_url)


class PdfDiscoveryFacts(_Fact):
    version: Literal[1] = 1
    source: Literal['openalex', 'crossref', 'document']
    capability: Literal['openalex-locations', 'crossref-links', 'document-pdf']
    status: DiscoveryStatus
    observed_at: datetime
    target_doi: str | None = None
    target_openalex: str | None = None
    landing_url: str | None = None
    platform: Token | None = None
    content_type: Literal['journal-article', 'conference-paper', 'preprint', 'unknown'] = 'unknown'
    identifiers: tuple[PdfIdentifier, ...] = Field(default=(), max_length=16)
    candidates: tuple[PdfCandidateFact, ...] = Field(default=(), max_length=32)
    links: tuple[PdfLinkFact, ...] = Field(default=(), max_length=16)
    diagnostics: tuple[DiscoveryDiagnostic, ...] = Field(default=(), max_length=8)

    _url = field_validator('landing_url')(_stable_url)

    @field_validator('target_doi', 'target_openalex')
    @classmethod
    def validate_identity(cls, value, info):
        if value is None:
            return None
        result = normalize_external_id('doi' if info.field_name == 'target_doi' else 'openalex', value)
        if result is None:
            raise ValueError('Invalid discovery target identity')
        return result

    @field_validator('observed_at')
    @classmethod
    def validate_observed_at(cls, value):
        if value.utcoffset() is None:
            raise ValueError('Discovery observation requires a timezone')
        return value

    @model_validator(mode='after')
    def validate_capability(self):
        if self.capability != {'openalex': 'openalex-locations', 'crossref': 'crossref-links',
                'document': 'document-pdf'}[self.source]:
            raise ValueError('Discovery capability does not belong to its source')
        if self.source != 'document' and not (self.target_doi or self.target_openalex):
            raise ValueError('A Provider snapshot requires its exact response target')
        if self.status == 'failed' and (self.candidates or self.links or self.identifiers):
            raise ValueError('Positive failed-read facts require partial status')
        if self.source == 'openalex' and len(self.candidates) > 4:
            raise ValueError('OpenAlex discovery is bounded to four PDF candidates')
        if len(self.model_dump_json().encode('utf-8')) > 65536:
            raise ValueError('Discovery snapshot exceeds payload budget')
        return self


def _ordered(*groups):
    return tuple(dict.fromkeys(item for group in groups for item in group))


def merge_discovery_facts(existing, incoming):
    """Keep one bounded snapshot per source/capability, never an attempt history."""
    output = {(item.source, item.capability): item for item in existing}
    rank = {'failed': 0, 'partial': 1, 'complete': 2}
    for new in incoming:
        key = new.source, new.capability
        old = output.get(key)
        if old is None:
            output[key] = new
            continue
        if any(left and right and left != right for left, right in (
                (old.target_doi, new.target_doi), (old.target_openalex, new.target_openalex))):
            raise ValueError('Conflicting discovery snapshot target identities')
        # A stale/partial response cannot demote complete response capability.
        # Successful facts survive empty responses and partial re-reads.
        preferred = new if (rank[new.status], new.observed_at) > (rank[old.status], old.observed_at) else old
        other = old if preferred is new else new
        candidates = _ordered(preferred.candidates, other.candidates)
        candidates = tuple(sorted(candidates, key=lambda item: (item.stage,
            0 if new.source == 'openalex' and item.field == 'best_oa_location.pdf_url' else 1)))
        if new.source == 'openalex':
            seen, unique = set(), []
            for item in candidates:
                identity = item.url if item.url else (item.refresh, item.action, item.field)
                if identity not in seen:
                    seen.add(identity)
                    unique.append(item)
            candidates = tuple(unique[:4])
        identifiers = _ordered(preferred.identifiers, other.identifiers)
        links = _ordered(preferred.links, other.links)
        overflow = len(candidates) > 32 or len(identifiers) > 16 or len(links) > 16
        # Fixed capacities retain the already qualified snapshot rather than
        # accumulating unlimited signed variants or every historical attempt.
        if overflow:
            candidates, identifiers, links = preferred.candidates, preferred.identifiers, preferred.links
        output[key] = PdfDiscoveryFacts.model_validate(preferred.model_dump() | {
            'candidates': candidates, 'identifiers': identifiers, 'links': links,
            'landing_url': preferred.landing_url or other.landing_url,
            'target_doi': preferred.target_doi or other.target_doi,
            'target_openalex': preferred.target_openalex or other.target_openalex,
            'platform': preferred.platform or other.platform,
            'diagnostics': _ordered(preferred.diagnostics, ('overflow',) if overflow else ())})
    if len(output) > 3:
        raise ValueError('Too many PDF discovery capability snapshots')
    return tuple(output.values())


def discovery_target_matches(facts, root_ids):
    """Validate a snapshot against caller-verified direct Paper identities only."""
    targets = {(namespace, value) for namespace, value in (
        ('doi', facts.target_doi), ('openalex', facts.target_openalex)) if value}
    if not targets:
        return facts.source == 'document'
    keys = set(root_ids)
    if not targets & keys:
        return False
    for namespace, value in targets:
        known = {key for kind, key in keys if kind == namespace}
        if known and value not in known:
            return False
    return True


def discovery_facts_from_records(records, root_ids, *, preprint_root=False):
    """Use only the Paper's direct identity closure; relations cannot grant ownership."""
    keys, pending, accepted = set(root_ids), list(records), []
    known_dois = {value for namespace, value in keys if namespace == 'doi'}
    while pending:
        matches = []
        for item in pending:
            ids = strong_identifiers(item.external_ids)
            doi = {value for namespace, value in ids if namespace == 'doi'}
            if (ids & keys and (preprint_root or item.publication_type != 'preprint')
                    and not (known_dois and doi - known_dois)):
                matches.append(item)
        if not matches:
            break
        for item in matches:
            pending.remove(item)
            ids = strong_identifiers(item.external_ids)
            keys.update(ids)
            known_dois.update(value for namespace, value in ids if namespace == 'doi')
            for facts in item.discovery_facts:
                targets = {(namespace, value) for namespace, value in (
                    ('doi', facts.target_doi), ('openalex', facts.target_openalex)) if value}
                if targets <= ids:
                    accepted.append(facts)
    return merge_discovery_facts((), accepted)


def openalex_discovery_facts(raw, observed_at):
    """Extract best-first PDF fields before generic MetadataSource deduplication."""
    candidates, links, diagnostics = [], [], []
    locations = raw.get('locations')
    best = raw.get('best_oa_location')
    complete = ('best_oa_location' in raw and (best is None or isinstance(best, dict))
        and isinstance(locations, list) and isinstance(raw.get('locations_count', len(locations)), int)
        and raw.get('locations_count', len(locations)) <= len(locations))
    rows = [('best_oa_location', best), *(('locations', item) for item in locations or ()
        if isinstance(locations, list))]
    seen = set()
    for field, location in rows:
        if location is None:
            continue
        if not isinstance(location, dict):
            complete = False
            continue
        landing = stable_discovery_url(location.get('landing_page_url'))
        if landing and len(links) < 16:
            link = PdfLinkFact(kind='landing', url=landing, field=field + '.landing_page_url')
            if link not in links:
                links.append(link)
        value = location.get('pdf_url')
        if value is None:
            continue
        if not isinstance(value, str):
            complete = False
            continue
        try:
            value = normalize_public_http_url(value)
            host = (urlsplit(value).hostname or '').casefold().rstrip('.') if value else ''
            if value is None or host == 'openalex.org' or host.endswith('.openalex.org'):
                continue
            value = urldefrag(value)[0]
            if value in seen:
                continue
            seen.add(value)
            if len(candidates) < 4:
                candidates.append(persistent_pdf_candidate(stage='P5', rule_id='OPENALEX', url=value,
                    field=field + '.pdf_url', refresh_kind='openalex-work', landing_url=landing))
        except ValueError:
            diagnostics.append('invalid-url')
    if not complete:
        diagnostics.append('incomplete-response')
    return PdfDiscoveryFacts(source='openalex', capability='openalex-locations',
        status='complete' if complete else 'partial', observed_at=observed_at,
        target_doi=normalize_external_id('doi', raw.get('doi')),
        target_openalex=normalize_external_id('openalex', raw.get('id')),
        content_type='preprint' if raw.get('type') in {'preprint', 'posted-content'} else 'journal-article',
        candidates=tuple(candidates), links=tuple(links), diagnostics=_ordered(diagnostics))


def crossref_discovery_facts(raw, observed_at):
    """Preserve typed exact-work links and alternative IDs from the current response."""
    identifiers, links, candidates, diagnostics = [], [], [], []
    complete = True
    alternative = raw.get('alternative-id') or []
    if not isinstance(alternative, list):
        alternative, complete = [], False
    for value in alternative:
        try:
            identifier = PdfIdentifier(kind='alternative-id', value=value, rule_id='API02')
            if identifier not in identifiers:
                if len(identifiers) == 16:
                    complete = False
                    diagnostics.append('overflow')
                    break
                identifiers.append(identifier)
        except ValueError:
            complete = False
            diagnostics.append('invalid-field')
    resources = []
    resource = raw.get('resource')
    if resource is not None:
        if isinstance(resource, dict) and isinstance(resource.get('primary'), dict):
            if value := resource['primary'].get('URL'):
                resources.append(('resource.primary.URL', value))
        else:
            complete = False
    if raw.get('URL'):
        resources.append(('URL', raw['URL']))
    for field, value in resources:
        if url := stable_discovery_url(value):
            links.append(PdfLinkFact(kind='landing', url=url, field=field))
    entries = raw.get('link') or []
    if not isinstance(entries, list):
        entries, complete = [], False
    for entry in entries:
        if not isinstance(entry, dict):
            complete = False
            continue
        url = entry.get('URL')
        content_type = entry.get('content-type')
        if not isinstance(content_type, str):
            content_type = None
        else:
            content_type = content_type.partition(';')[0].strip().casefold()
        kind = ('pdf' if content_type == 'application/pdf' else
            'jats' if content_type and ('xml' in content_type or 'jats' in content_type) else
            'json' if content_type and 'json' in content_type else 'other')
        try:
            normalized = normalize_public_http_url(url)
            if normalized is None:
                raise ValueError('Missing Crossref link URL')
            if kind == 'pdf':
                candidate = persistent_pdf_candidate(stage='P2', rule_id='API02', url=normalized,
                    field='link', refresh_kind='crossref-work')
                if candidate not in candidates:
                    if len(candidates) == 16:
                        complete = False
                        diagnostics.append('overflow')
                        break
                    candidates.append(candidate)
            if stable_discovery_url(normalized):
                link = PdfLinkFact(kind=kind, url=normalized, field='link', content_type=content_type)
                if link not in links:
                    if len(links) == 16:
                        complete = False
                        diagnostics.append('overflow')
                        break
                    links.append(link)
        except (ValueError, TypeError, AttributeError):
            complete = False
            diagnostics.append('invalid-url')
    if not complete:
        diagnostics.append('incomplete-response')
    return PdfDiscoveryFacts(source='crossref', capability='crossref-links',
        status='complete' if complete else 'partial', observed_at=observed_at,
        target_doi=normalize_external_id('doi', raw.get('DOI')),
        content_type={'journal-article': 'journal-article', 'proceedings-article': 'conference-paper',
            'posted-content': 'preprint'}.get(raw.get('type'), 'unknown'),
        identifiers=tuple(identifiers), candidates=tuple(candidates), links=tuple(links),
        diagnostics=_ordered(diagnostics))
