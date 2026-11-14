"""Pure, lazy P1/P2 PDF candidates for an already identified Paper.

These functions perform no requests and make no PDF-success claims. Consume one
candidate, report its result to the discovery coordinator, and only then advance
the iterator. Host routing uses the actual content URL rather than DOI prefixes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dataclass_field
from typing import Iterator, Literal
from urllib.parse import parse_qs, quote, unquote, urlsplit, urlunsplit

from allfold.identifiers import normalize_external_id, valid_doi
from allfold.pdf_catalog import API_CATALOG, RULE_CATALOG
from allfold.url_safety import normalize_public_http_url


ARTICLE_TYPES = frozenset({'journal-article', 'conference-paper'})


def _bounded(value: str | None, limit: int, name: str, *, required: bool = False) -> None:
    if value is None and not required:
        return
    if not isinstance(value, str) or (required and not value) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f'invalid {name}')


@dataclass(frozen=True)
class PdfTarget:
    """Immutable original target; DOI request spelling is intentionally retained."""

    paper_id: str
    doi: str | None = None
    platform: str | None = None
    content_host: str | None = None
    article_url: str | None = dataclass_field(default=None, repr=False)
    content_type: str = 'unknown'
    direct_identities: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.paper_id:
            raise ValueError('Paper binding is required')
        for value, limit, name in ((self.paper_id, 128, 'Paper binding'), (self.doi, 512, 'DOI'),
                                   (self.platform, 64, 'platform'), (self.content_host, 253, 'host'),
                                   (self.article_url, 8192, 'article URL'),
                                   (self.content_type, 64, 'content type')):
            _bounded(value, limit, name)
        if self.article_url is not None:
            normalize_public_http_url(self.article_url)
        if not isinstance(self.direct_identities, tuple) or len(self.direct_identities) > 64:
            raise ValueError('Direct Paper identities require a bounded immutable closure')
        for pair in self.direct_identities:
            if (not isinstance(pair, tuple) or len(pair) != 2
                    or not all(isinstance(value, str) for value in pair)
                    or len(pair[1]) > 512 or normalize_external_id(*pair) != pair[1]):
                raise ValueError('Direct Paper identities must be canonical reliable identities')

    @property
    def identity_doi(self) -> str | None:
        return valid_doi(self.doi)


@dataclass(frozen=True)
class PdfCandidate:
    target: PdfTarget
    stage: Literal['P1', 'P2', 'P3', 'P4', 'P5']
    rule_id: str
    platform: str
    url: str = dataclass_field(repr=False)
    reader_kind: str | None = None
    referer: str | None = dataclass_field(default=None, repr=False)
    field: str | None = None
    credential: str | None = None
    accept: str | None = None
    action: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.target, PdfTarget) or self.stage not in {'P1', 'P2', 'P3', 'P4', 'P5'}:
            raise ValueError('invalid candidate target/stage')
        for value, name in ((self.rule_id, 'rule'), (self.platform, 'platform')):
            _bounded(value, 64, name, required=True)
        _bounded(self.url, 8192, 'candidate URL', required=True)
        normalize_public_http_url(self.url)
        if self.referer is not None:
            _bounded(self.referer, 8192, 'Referer')
            normalize_public_http_url(self.referer)


# Exact content Hosts only. Aliases here are known public site Hosts, never
# institution/proxy suffix matching. Unrecognised Hosts still permit generic P3.
HOST_PLATFORMS = {
    'link.springer.com': 'springer', 'onlinelibrary.wiley.com': 'wiley',
    'www.tandfonline.com': 'taylor_francis', 'www.nejm.org': 'nejm',
    'journals.sagepub.com': 'sage', 'www.annualreviews.org': 'annual_reviews',
    'www.frontiersin.org': 'frontiers', 'dl.acm.org': 'acm',
    'projecteuclid.org': 'project_euclid', 'arc.aiaa.org': 'aiaa',
    'www.ajronline.org': 'ajr', 'www.spiedigitallibrary.org': 'spie',
    'www.science.org': 'science', 'www.pnas.org': 'pnas',
    'pubs.rsna.org': 'rsna', 'www.worldscientific.com': 'world_scientific',
    'journals.plos.org': 'plos', 'academic.oup.com': 'oup',
    'www.jstor.org': 'jstor', 'www.cell.com': 'cell',
    'www.sciencedirect.com': 'sciencedirect', 'ieeexplore.ieee.org': 'ieee',
    'www.clinicalkey.com': 'clinicalkey', 'www.nature.com': 'nature',
    'www.palgrave-journals.com': 'nature', 'iopscience.iop.org': 'iop',
    'journals.aps.org': 'aps', 'ascopubs.org': 'asco',
    'ahajournals.org': 'aha', 'www.ahajournals.org': 'aha',
    'journals.healio.com': 'healio', 'journals.uchicago.edu': 'chicago',
    'jmlr.org': 'jmlr', 'www.jmlr.org': 'jmlr',
    'proceedings.mlr.press': 'pmlr', 'pubs.acs.org': 'acs',
    'www.mdpi.com': 'mdpi',
}


def content_host(target: PdfTarget) -> str | None:
    """A real landing URL takes precedence over a stale publisher/Host hint."""
    if target.article_url:
        return urlsplit(target.article_url).hostname
    if target.content_host:
        host = target.content_host.lower()
        # Validate hints as Hosts, not arbitrary netlocs with ports or userinfo.
        if host in HOST_PLATFORMS:
            return host
    return None


def content_platform(target: PdfTarget) -> str | None:
    return HOST_PLATFORMS.get(content_host(target))


def _doi(target: PdfTarget) -> str | None:
    if not target.identity_doi:
        return None
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', target.doi.strip(), flags=re.I).strip()


def _component(value: str) -> str:
    # encodeURIComponent spelling, including literal parentheses. Preserve valid
    # escaped octets exactly; a UTF-8 decode/re-encode would corrupt values such
    # as %FF and rewrite already escaped components.
    return quote(re.sub(r'%(?![0-9a-fA-F]{2})', '%25', value), safe="~()*!.'-_%")


def _path_doi(value: str) -> str:
    # DOI multi-level suffix remains a path; query delimiters do not become URL
    # delimiters. Existing escapes are retained rather than encoded a second time.
    return quote(re.sub(r'%(?![0-9a-fA-F]{2})', '%25', value), safe="/:%~()*!.'-_$&+,;=@")


_P1 = {
    'springer': ('R001', '/content/pdf/{component}.pdf'),
    'wiley': ('R002', '/doi/pdfdirect/{doi}?download=true'),
    'taylor_francis': ('R003', '/doi/pdf/{doi}'),
    'nejm': ('R004', '/doi/pdf/{doi}'),
    'sage': ('R005', '/doi/pdf/{doi}'),
    'annual_reviews': ('R006', '/doi/pdf/{doi}'),
    'frontiers': ('R007', '/articles/{doi}/pdf'),
    'acm': ('R008', '/doi/pdf/{doi}?download=true'),
    'project_euclid': ('R009', '/journalArticle/Download?urlId={component}'),
    'aiaa': ('R010', '/doi/pdf/{doi}'),
    'ajr': ('R011', '/doi/pdf/{doi}?download=true'),
    'science': ('R014', '/doi/pdf/{doi}'),
    'pnas': ('R015', '/doi/pdf/{doi}'),
    'rsna': ('R016', '/doi/pdf/{doi}?download=true'),
    'world_scientific': ('R017', '/doi/pdf/{doi}?download=true'),
}


def iter_p1_candidates(target: PdfTarget, inputs: PdfRuleInputs | None = None) -> Iterator[PdfCandidate]:
    """Yield only eligible DOI templates, without precomputing later stages."""
    _check_inputs(target, inputs)
    doi = _doi(target)
    host, platform = content_host(target), content_platform(target)
    if not doi or target.content_type not in ARTICLE_TYPES:
        return
    if platform == 'project_euclid' and target.content_type != 'journal-article':
        return
    if platform in _P1:
        rule, expression = _P1[platform]
        yield PdfCandidate(target, 'P1', rule, platform,
                           'https://' + host + expression.format(doi=_path_doi(doi), component=_component(doi)))
        if platform == 'springer' and inputs and 'springer_in_press' in inputs.conditions:
            yield PdfCandidate(target, 'P1', 'R019', platform,
                               'https://' + host + '/content/pdf/' + _path_doi(doi) + '_reference.pdf')
    elif platform == 'spie':
        journal = target.content_type == 'journal-article'
        yield PdfCandidate(target, 'P1', 'R012' if journal else 'R013', platform,
                           'https://' + host + ('/journalArticle' if journal else '/Proceedings')
                           + '/Download?urlId=' + _component(doi))
    elif platform == 'plos' and target.content_type == 'journal-article':
        slug = _identifier(inputs, 'journal_slug')
        if slug in {'plosone', 'plosbiology', 'plosmedicine', 'ploscompbiol', 'plosgenetics',
                    'plospathogens', 'plosntds', 'plosclimate', 'ploswater', 'plosglobpublichealth',
                    'plosdigitalhealth', 'ploscomplexsystems', 'plosmentalhealth'}:
            yield PdfCandidate(target, 'P1', 'R018', platform, 'https://' + host + '/' + slug
                               + '/article/file?id=' + _component(doi) + '&type=printable')


def _check_inputs(target: PdfTarget, inputs: PdfRuleInputs | None) -> None:
    if inputs is not None and inputs.target != target:
        raise ValueError('PDF rule inputs belong to another target')


@dataclass(frozen=True)
class PdfRuleInputs:
    """Verified facts bound to this exact Paper, never ordinary metadata.sources."""

    target: PdfTarget
    identifiers: tuple[tuple[str, str], ...] = ()
    conditions: frozenset[str] = frozenset()
    alternative_ids: tuple[str, ...] = ()
    known_pdf_urls: tuple[KnownPdfUrl, ...] = ()
    clinicalkey_query: str | None = dataclass_field(default=None, repr=False)
    credentials: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.target, PdfTarget):
            raise ValueError('original PDF target binding is required')
        if not isinstance(self.identifiers, tuple) or len(self.identifiers) > 24:
            raise ValueError('identifiers must be a bounded immutable tuple')
        for pair in self.identifiers:
            if not isinstance(pair, tuple) or len(pair) != 2:
                raise ValueError('identifier entries must be immutable kind/value pairs')
            kind, value = pair
            _bounded(kind, 64, 'identifier kind', required=True)
            _bounded(value, 512, 'identifier', required=True)
        if not isinstance(self.conditions, frozenset) or len(self.conditions) > 16:
            raise ValueError('conditions must be a bounded immutable set')
        for condition in self.conditions:
            _bounded(condition, 64, 'condition', required=True)
        if not isinstance(self.alternative_ids, tuple) or len(self.alternative_ids) > 24:
            raise ValueError('alternative IDs must be a bounded immutable tuple')
        for value in self.alternative_ids:
            _bounded(value, 512, 'alternative ID', required=True)
        if not isinstance(self.known_pdf_urls, tuple) or len(self.known_pdf_urls) > 16:
            raise ValueError('PDF URLs must be a bounded immutable tuple')
        if any(not isinstance(item, KnownPdfUrl) for item in self.known_pdf_urls):
            raise ValueError('PDF URLs must have an explicit source field')
        _bounded(self.clinicalkey_query, 1024, 'ClinicalKey query')
        if self.clinicalkey_query and any(c in self.clinicalkey_query for c in '#?\\'):
            raise ValueError('invalid ClinicalKey query')
        if not isinstance(self.credentials, frozenset) or not self.credentials <= {'ieee', 'elsevier', 'wiley_tdm', 'aps_harvest', 'springer_metadata'}:
            raise ValueError('credentials contain capability names only, never credential values')


def _identifier(inputs: PdfRuleInputs | None, kind: str) -> str | None:
    return next((value for name, value in inputs.identifiers if name == kind), None) if inputs else None


@dataclass(frozen=True)
class KnownPdfUrl:
    """An explicit target PDF field, not a URL inferred from metadata.sources."""

    url: str = dataclass_field(repr=False)
    rule_id: str
    field: str
    referer: str | None = dataclass_field(default=None, repr=False)
    reader_kind: str | None = None

    def __post_init__(self) -> None:
        _bounded(self.url, 8192, 'known PDF URL', required=True)
        normalize_public_http_url(self.url)
        item = RULE_CATALOG.get(self.rule_id) or API_CATALOG.get(self.rule_id)
        if not item or item.status in {'historical', 'extension', 'non-pdf', 'reference'} or self.rule_id == 'API01':
            raise ValueError('explicit PDF source rule and field are required')
        _bounded(self.field, 128, 'PDF source field', required=True)
        _bounded(self.reader_kind, 64, 'reader kind')
        if self.referer:
            _bounded(self.referer, 8192, 'Referer')
            normalize_public_http_url(self.referer)


_PII = re.compile(r'[SB][0-9]{7}[0-9X][0-9]{7}[0-9X]')
_CELL_PII = re.compile(r'[SB][0-9]{4}-[0-9]{4}\([0-9]{2}\)[0-9]{5}-[0-9X]')
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)


def _valid_id(inputs: PdfRuleInputs | None, kinds: tuple[str, ...], pattern: re.Pattern | str) -> str | None:
    if inputs:
        return next((value for kind, value in inputs.identifiers
                     if kind in kinds and re.fullmatch(pattern, value)), None)
    return None


def _pii(target: PdfTarget, inputs: PdfRuleInputs | None) -> str | None:
    if value := _valid_id(inputs, ('pii',), _PII):
        return value
    if inputs:
        if value := next((value for value in inputs.alternative_ids if _PII.fullmatch(value)), None):
            return value
    if target.article_url:
        path = unquote(urlsplit(target.article_url).path)
        matched = re.search(r'/pii/([^/]+)(?:/|$)', path)
        if matched and _PII.fullmatch(matched[1]):
            return matched[1]
    return None


def _cell_pii(target: PdfTarget, inputs: PdfRuleInputs | None) -> str | None:
    if value := _valid_id(inputs, ('cell_pii',), _CELL_PII):
        return value
    if target.article_url:
        url = urlsplit(target.article_url)
        matched = re.fullmatch(r'/[^/]+/(?:fulltext|pdfExtended)/([^/]+)/?', unquote(url.path))
        value = matched[1] if matched else None
        if url.path == '/action/showPdf':
            value = next(iter(parse_qs(url.query).get('pii', ())), None)
        if value and _CELL_PII.fullmatch(value):
            return value
    return None


def _ieee_number(target: PdfTarget, inputs: PdfRuleInputs | None) -> str | None:
    if value := _valid_id(inputs, ('article_number', 'arnumber'), r'[0-9]{1,16}'):
        return value
    if target.article_url:
        url = urlsplit(target.article_url)
        if matched := re.fullmatch(r'/document/([0-9]{1,16})/?', url.path):
            return matched[1]
        if url.path in {'/xpl/documentDetails.jsp', '/stamp/stamp.jsp', '/stampPDF/getPDF.jsp'}:
            value = next(iter(parse_qs(url.query).get('arnumber', ())), '')
            if re.fullmatch(r'[0-9]{1,16}', value):
                return value
    return None


def _oup_resource(target: PdfTarget, inputs: PdfRuleInputs | None) -> str | None:
    if value := _valid_id(inputs, ('resource_id',), r'[0-9]{1,16}'):
        return value
    if target.article_url:
        url = urlsplit(target.article_url)
        # Canonical journal article /journal/article/volume/issue/page/resourceId;
        # article-abstract and advance-article are the same article resource kind.
        matched = re.fullmatch(r'/[^/]+/(?:article|article-abstract)/[^/]+/[^/]+/[^/]+/([0-9]{1,16})/?', url.path)
        if not matched:
            matched = re.fullmatch(r'/[^/]+/advance-article(?:-abstract)?/doi/10\.[0-9]{4,9}/.+/([0-9]{1,16})/?', url.path)
        if matched:
            return matched[1]
        if url.path == '/Citation/Download':
            query = parse_qs(url.query)
            value = next(iter(query.get('resourceId', ())), '')
            if query.get('resourceType') == ['3'] and re.fullmatch(r'[0-9]{1,16}', value):
                return value
    return None


def _jstor_stable(target: PdfTarget, inputs: PdfRuleInputs | None) -> str | None:
    value = _identifier(inputs, 'jstor_stable_id')
    if not value and target.article_url:
        if matched := re.fullmatch(r'/stable/(?!pdf(?:plus)?/)(.+?)/?', urlsplit(target.article_url).path):
            value = unquote(matched[1])
    if value and not _UUID.fullmatch(value) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._()/-]{0,255}', value):
        if all(part not in {'', '.', '..'} for part in value.split('/')):
            return value
    return None


def needs_p2_query(target: PdfTarget, inputs: PdfRuleInputs, *, known_refresh=False) -> bool:
    """One DOI/type gate for missing routable fields or a known PDF refresh."""
    if not target.identity_doi or target.content_type not in ARTICLE_TYPES:
        return False
    if known_refresh:
        return True
    platform = content_platform(target)
    required = {'sciencedirect': _pii, 'cell': _cell_pii, 'ieee': _ieee_number,
        'oup': _oup_resource, 'jstor': _jstor_stable}
    if platform in required:
        return required[platform](target, inputs) is None
    return platform is None or (platform == 'springer'
        and not any(item.rule_id == 'API09' for item in inputs.known_pdf_urls))


def _article_transform(target: PdfTarget, platform: str | None, inputs: PdfRuleInputs | None) -> tuple[str, str] | None:
    if target.article_url:
        url = urlsplit(target.article_url)
        path, rule, converted = url.path, None, None
        if platform == 'nature':
            matched = re.fullmatch(r'(/[^/]+/journal/(?:[^/]+/)+)(?:full|abs)/([^/]+)\.html', path)
            if matched:
                rule, converted = 'R028', matched[1] + 'pdf/' + matched[2] + '.pdf'
        elif platform == 'iop':
            if re.fullmatch(r'/article/10\.[0-9]{4,9}/.+', path) or re.fullmatch(r'/[0-9]{4}-[0-9]{3}[0-9X]/[0-9]+/[0-9]+/[^/]+(?:/meta)?', path):
                base = re.sub(r'/(?:meta|pdf)/?$', '', path.rstrip('/'))
                rule, converted = 'R029', base + '/pdf'
        elif platform == 'aps':
            if matched := re.fullmatch(r'/([a-z][a-z0-9-]*)/abstract/(10\.[0-9]{4,9}/.+)', path):
                rule, converted = 'R030', '/' + matched[1] + '/pdf/' + matched[2]
        elif platform in {'asco', 'aha', 'healio', 'chicago'}:
            rule, origin, destination = {
                'asco': ('R031', 'full', 'pdfdirect'), 'aha': ('R032', 'reader', 'pdf'),
                'healio': ('R033', 'epdf', 'pdf'), 'chicago': ('R034', 'full', 'pdf'),
            }[platform]
            if matched := re.fullmatch(r'/doi/' + origin + r'/(10\.[0-9]{4,9}/.+)', path):
                converted = '/doi/' + destination + '/' + matched[1]
        elif platform == 'jmlr':
            if matched := re.fullmatch(r'/papers/v([0-9]+)/([A-Za-z0-9_-]+)\.html', path):
                volume, key = matched.groups()
                rule, converted = 'R035', f'/papers/volume{volume}/{key}/{key}.pdf'
        elif platform == 'pmlr':
            if matched := re.fullmatch(r'/v([0-9]+)/([A-Za-z0-9_-]+)\.html', path):
                volume, key = matched.groups()
                rule, converted = 'R036', f'/v{volume}/{key}/{key}.pdf'
        if converted:
            # Preserve query spelling/order, filename case and existing escapes.
            # Fragment is not part of a request and is not copied to candidates.
            return rule, urlunsplit((url.scheme, url.netloc, converted, url.query, ''))
    elif doi := _doi(target):
        if platform == 'iop' and inputs and 'iop_doi_article' in inputs.conditions:
            return 'R029', 'https://iopscience.iop.org/article/' + _path_doi(doi) + '/pdf'
        if platform == 'aps' and (slug := _valid_id(inputs, ('journal_slug',), r'[a-z][a-z0-9-]{0,31}')):
            return 'R030', 'https://journals.aps.org/' + slug + '/pdf/' + _path_doi(doi)
    return None


def iter_p2_candidates(target: PdfTarget, inputs: PdfRuleInputs | None = None) -> Iterator[PdfCandidate]:
    """Yield known target PDF fields, then qualified IDs/URL conversions.

    Missing identifiers produce no request here. The outer coordinator may make
    one applicable missing-fact query and invoke this pure service with new facts.
    Reader candidates remain readers until their current response is interpreted.
    """
    _check_inputs(target, inputs)
    if target.content_type not in ARTICLE_TYPES:
        return
    host, platform = content_host(target), content_platform(target)
    if inputs:
        for known in inputs.known_pdf_urls:
            url = urlsplit(known.url)
            if url.hostname == 'journals.plos.org' and '/article/file' in url.path and 'manuscript' in parse_qs(url.query).get('type', ()):
                continue
            yield PdfCandidate(target, 'P2', known.rule_id, platform or target.platform or 'unknown',
                               known.url, known.reader_kind, known.referer, known.field)
    if platform == 'sciencedirect' and (pii := _pii(target, inputs)):
        url = 'https://' + host + '/science/article/pii/' + pii + '/pdfft'
        yield PdfCandidate(target, 'P2', 'R024', platform, url)
        yield PdfCandidate(target, 'P2', 'R024', platform, url + '?download=true')
    elif platform == 'cell' and (pii := _cell_pii(target, inputs)):
        yield PdfCandidate(target, 'P2', 'R023', platform, 'https://' + host + '/action/showPdf?pii=' + _component(pii))
    elif platform == 'ieee' and (number := _ieee_number(target, inputs)):
        yield PdfCandidate(target, 'P2', 'R025', platform,
                           'https://' + host + '/stampPDF/getPDF.jsp?tp=&arnumber=' + number + '&ref=')
        yield PdfCandidate(target, 'P2', 'R025', platform,
                           'https://' + host + '/stamp/stamp.jsp?tp=&arnumber=' + number, 'ieee_stamp')
    elif platform == 'oup' and (resource := _oup_resource(target, inputs)):
        yield PdfCandidate(target, 'P2', 'R020', platform, 'https://' + host
                           + '/Citation/Download?resourceId=' + resource + '&resourceType=3&citationFormat=2', 'oup_citation')
    elif platform == 'jstor' and (stable := _jstor_stable(target, inputs)):
        yield PdfCandidate(target, 'P2', 'R022', platform, 'https://' + host + '/stable/pdfplus/'
                           + quote(stable, safe='/().-_') + '.pdf')
    elif (platform == 'clinicalkey' and inputs
          and {'clinicalkey_access', 'clinicalkey_session_ready'} <= inputs.conditions
          and (pii := _pii(target, inputs))):
        url = 'https://' + host + '/service/content/pdf/watermarked/1-s2.0-' + pii + '.pdf'
        if inputs.clinicalkey_query:
            url += '?' + inputs.clinicalkey_query
        yield PdfCandidate(target, 'P2', 'R026', platform, url)
    if transformed := _article_transform(target, platform, inputs):
        rule, url = transformed
        yield PdfCandidate(target, 'P2', rule, platform, url)
    if inputs:
        doi = _doi(target)
        if (platform in {'sciencedirect', 'cell'} and 'elsevier' in inputs.credentials
                and 'elsevier_pdf_access' in inputs.conditions):
            pii = _pii(target, inputs) if platform == 'sciencedirect' else _cell_pii(target, inputs)
            locator = 'doi/' + _component(doi) if doi else 'pii/' + _component(pii) if pii else None
            if locator:
                yield PdfCandidate(target, 'P2', 'API06', platform,
                                   'https://api.elsevier.com/content/article/' + locator,
                                   credential='elsevier', accept='application/pdf')
        elif (doi and platform == 'wiley' and 'wiley_tdm' in inputs.credentials
              and 'wiley_tdm_access' in inputs.conditions):
            yield PdfCandidate(target, 'P2', 'API07', platform,
                               'https://api.wiley.com/onlinelibrary/tdm/v1/articles/' + _component(doi),
                               credential='wiley_tdm', accept='application/pdf')
        elif doi and platform == 'aps':
            oa = 'aps_harvest_oa' in inputs.conditions
            if oa or ('aps_harvest' in inputs.credentials and 'aps_harvest_authorized' in inputs.conditions):
                yield PdfCandidate(target, 'P2', 'API08', platform,
                                   'https://harvest.aps.org/v2/journals/articles/' + _path_doi(doi),
                                   credential=None if oa else 'aps_harvest', accept='application/pdf')
