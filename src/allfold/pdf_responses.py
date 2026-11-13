"""Finite parsing of a current response, never HTML fetching or PDF validation."""
from dataclasses import replace
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from allfold.identifiers import valid_doi
from allfold.url_safety import normalize_public_http_url


class _SmallHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack = [], []

    def handle_starttag(self, tag, attrs):
        if len(self.nodes) >= 4096 or any(len(value or '') > 8192 for _, value in attrs):
            raise ValueError('Response parse budget exceeded')
        node = {'tag': tag, 'attrs': dict(attrs), 'text': '', 'parents': tuple(self.stack)}
        self.nodes.append(node)
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'input', 'embed', 'source', 'base', 'area', 'wbr', 'param', 'col'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        for node in self.stack:
            if node['tag'] in {'a', 'script', 'title'}:
                node['text'] += data
                if len(node['text']) > 131072:
                    raise ValueError('Response field budget exceeded')


def _reader_kind(candidate, actual):
    url, original = urlsplit(actual), urlsplit(candidate.url)
    query, initial = parse_qs(url.query), parse_qs(original.query)
    if url.hostname in {'www.sciencedirect.com', 'sciencedirect.com'}:
        match = re.fullmatch(r'/science/article/pii/([SB][0-9]{7}[0-9X][0-9]{7}[0-9X])/(?:pdfft|pdf)', url.path)
        if match and (match[1] in original.path or original.hostname != url.hostname):
            return 'sciencedirect'
    if (url.hostname == 'ieeexplore.ieee.org'
            and url.path in {'/stamp/stamp.jsp', '/stampPDF/getPDF.jsp'}
            and query.get('arnumber') and re.fullmatch(r'[0-9]{1,16}', query['arnumber'][0])
            and (not initial.get('arnumber') or query.get('arnumber') == initial.get('arnumber'))):
        return 'ieee'
    if (url.hostname in {'opg.optica.org', 'osapublishing.org', 'www.osapublishing.org'}
            and url.path == '/viewmedia.cfm' and query.get('uri') and len(query['uri'][0]) <= 256
            and (not initial.get('uri') or query.get('uri') == initial.get('uri'))):
        return 'optica'
    if (url.hostname == 'journals.lww.com'
            and re.fullmatch(r'/[^/]+/_layouts/15/oaks.journals/downloadpdf.aspx', url.path, re.I)
            and query.get('an') and re.fullmatch(r'[0-9]{8}-[0-9]{9}-[0-9]{5}', query['an'][0])
            and (not initial.get('an') or query.get('an') == initial.get('an'))):
        return 'lww'
    return None


def reader_context(candidate, actual=None):
    """Return only fixed native reader DTOs qualified by this exact URL chain."""
    actual = actual or candidate.url
    kind = _reader_kind(candidate, actual)
    if not kind:
        return None
    url = urlsplit(actual)
    query = parse_qs(url.query)
    identifier = (re.search(r'/pii/([^/]+)/', url.path)[1] if kind == 'sciencedirect' else
        query['arnumber' if kind == 'ieee' else 'uri' if kind == 'optica' else 'an'][0])
    source = candidate.target.article_url or candidate.url
    if urlsplit(source).hostname != url.hostname:
        source = actual  # The current response's verified HTTP redirect chain.
    return dict(rule_id={'sciencedirect': 'R024', 'ieee': 'R025', 'optica': 'R053', 'lww': 'R060'}[kind],
        platform=kind, url=actual, identifier=identifier,
        source_url=source, stage=candidate.stage)


def access_limited(response):
    if response.access or response.status in {401, 403, 407, 429}:
        return True
    text = response.body.decode('utf-8', errors='replace').lower()
    return any(marker in text for marker in ('cf-chl-', 'challenge-platform', 'g-recaptcha',
        'hcaptcha', 'verify you are human', 'checking your browser', 'access denied',
        'name="password"', "name='password'"))


def _safe_next(candidate, base, value, **extra):
    if not isinstance(value, str) or not value or len(value) > 8192:
        return None
    try:
        url = urljoin(base, value)
        normalize_public_http_url(url)
        parsed = urlsplit(url)
        if parsed.hostname == 'journals.plos.org' and 'manuscript' in parse_qs(parsed.query).get('type', ()):
            return None
        return replace(candidate, url=url, reader_kind=None, credential=None, accept=None, **extra)
    except ValueError:
        return None


def _excluded(node):
    return any(p['tag'] in {'nav', 'footer'} or p['attrs'].get('role') in {'doc-bibliography', 'doc-endnotes'}
        or re.search(r'references|related|recommend|supplement', p['attrs'].get('id', '') + ' ' + p['attrs'].get('class', ''), re.I)
        for p in (*node['parents'], node))


def parse_current_response(candidate, response):
    if response.status != 200 or access_limited(response):
        return ()
    content = response.content_type.partition(';')[0].strip().lower()
    text = response.body.decode('utf-8', errors='replace')
    actual = urlsplit(response.url)
    if (candidate.rule_id == 'API06' and actual.hostname == 'api.elsevier.com'
            and actual.path.startswith('/content/article/') and content in {'application/json', 'application/vnd.elsevier.article+json'}):
        try:
            data = json.loads(text).get('full-text-retrieval-response', {}).get('coredata', {})
            if valid_doi(data.get('prism:doi')) != candidate.target.identity_doi or not candidate.target.identity_doi:
                return ()
            entries = data.get('link')
            if not isinstance(entries, list) or len(entries) > 16:
                return ()
            result = []
            for entry in entries:
                if isinstance(entry, dict) and entry.get('@rel') == 'scidir-pdf':
                    item = _safe_next(candidate, response.url, entry.get('@href'))
                    if item and item not in result:
                        result.append(item)
            return tuple(result)
        except (ValueError, AttributeError, TypeError):
            return ()
    # This citation behavior belongs exclusively to Oxford's qualified endpoint.
    if (candidate.rule_id == 'R020' and candidate.reader_kind == 'oup_citation'
            and actual.hostname == 'academic.oup.com' and actual.path == '/Citation/Download'
            and parse_qs(actual.query).get('resourceType') == ['3']):
        match = re.search(r'\beprint\s*=\s*(?:\{([^{}]+)\}|"([^"]+)")', text, re.I)
        value = (match[1] or match[2]).strip() if match else None
        # Explicit eprint must be a PDF entry, not the citation's article URL.
        if value and re.search(r'/article-pdf/|\.pdf(?:[?#]|$)|/doi/(?:pdf|epdf)/', value, re.I):
            item = _safe_next(candidate, response.url, value)
            return (item,) if item else ()
        return ()
    if content not in {'text/html', 'application/xhtml+xml'}:
        return ()
    parser = _SmallHTML()
    try:
        parser.feed(text)
    except (ValueError, RecursionError):
        return ()
    kind = _reader_kind(candidate, response.url)
    values = []
    def add(value, **extra):
        item = _safe_next(candidate, response.url, value, **extra)
        if item and all(item.url != old.url for old in values) and len(values) < 16:
            values.append(item)
    if kind:
        frames = [node for node in parser.nodes if node['tag'] == 'frame']
        for node in parser.nodes:
            tag, attrs = node['tag'], node['attrs']
            if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh' and kind in {'sciencedirect', 'ieee'}:
                match = re.fullmatch(r'\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*[\'"]?([^\'"]+)[\'"]?\s*', attrs.get('content', ''), re.I)
                if match:
                    add(match[1].strip())
            if kind == 'sciencedirect':
                if tag == 'a' and any(p['attrs'].get('id') == 'redirect-message' for p in node['parents']):
                    add(attrs.get('href'))
                if tag == 'object' and node['parents'] and 'PdfEmbed' in node['parents'][-1]['attrs'].get('class', '').split():
                    add(attrs.get('data'))
            if kind == 'ieee' and tag in {'frame', 'iframe'}:
                add(attrs.get('src'))
            if kind == 'optica' and tag == 'frame' and frames.index(node) > 0:
                add(attrs.get('src'))
            if kind in {'sciencedirect', 'lww'} and tag == 'script' and attrs.get('type') == 'application/json':
                try:
                    data = json.loads(node['text'])
                    # Fixed data carriers only; no regex over arbitrary scripts,
                    # evaluation, graph traversal or recursive URL-key search.
                    value = (data.get('article', {}).get('pdfDownload', {}).get('urlMetadata')
                        if kind == 'sciencedirect' else data.get('pdfDownloadDetails', {}).get('pdfUrl'))
                    if isinstance(value, str):
                        add(value, **({'referer': response.url} if kind == 'lww' else {}))
                except (ValueError, AttributeError, TypeError):
                    pass
        if kind == 'optica':
            add(next(iter(parse_qs(actual.query).get('gotourl', ())), None))
        return tuple(values)
    # HTTP article HTML is eligible only with exact scholarly DOI evidence in
    # this response. Native article reads retain their stronger live binding.
    dois = {valid_doi(node['attrs'].get('content')) for node in parser.nodes
        if node['tag'] == 'meta' and (node['attrs'].get('name') or node['attrs'].get('property', '')).lower()
        in {'citation_doi', 'prism.doi', 'dc.identifier.doi'} and not _excluded(node)}
    if dois != {candidate.target.identity_doi} or not candidate.target.identity_doi:
        return ()
    for name in ('citation_pdf_url', 'fulltext_pdf_url'):
        for node in parser.nodes:
            if node['tag'] == 'meta' and (node['attrs'].get('name') or node['attrs'].get('property', '')).lower() == name:
                add(node['attrs'].get('content'))
    # Only one unambiguous main-article PDF entrance. Other article/issue and
    # supplement links are excluded before deciding ambiguity.
    generic = []
    for node in parser.nodes:
        if node['tag'] != 'a' or _excluded(node) or not any(p['tag'] in {'article', 'main'} for p in node['parents']):
            continue
        attrs = node['attrs']
        label = (node['text'] + ' ' + attrs.get('title', '')).strip()
        if re.search(r'supplement|supporting|appendix|whole issue|entire issue|other article', label + ' ' + attrs.get('href', ''), re.I):
            continue
        if re.fullmatch(r'(?:download\s+)?(?:(?:full[ -]?text|article)\s+)?pdf(?:\s+download)?', label, re.I) or attrs.get('type') == 'application/pdf':
            item = _safe_next(candidate, response.url, attrs.get('href'))
            if item and item.url not in generic:
                generic.append(item.url)
    if len(generic) == 1:
        add(generic[0])
    return tuple(values)
