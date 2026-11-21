"""Finite parsing of a current response, never HTML fetching or PDF validation."""
from dataclasses import replace
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, unquote, urldefrag, urljoin, urlsplit

from allfold.http_access import html_access
from allfold.identifiers import valid_doi
from allfold.pdf_rules import ATYPON_HOSTS
from allfold.url_safety import normalize_public_http_url


def json_sample(body, *, partial=False, report=lambda code: None):
    """Keep complete fields/array members from one bounded JSON observation."""
    if not partial:
        try:
            return json.loads(body)
        except (ValueError, RecursionError):
            report('parse-failed')
            return None
    text = body.decode('utf-8', errors='replace')
    decoder = json.JSONDecoder()
    missing = object()
    def read(position, depth=0):
        while position < len(text) and text[position].isspace():
            position += 1
        try:
            value, end = decoder.raw_decode(text, position)
            return value, end, True
        except (ValueError, RecursionError):
            pass
        if depth >= 64 or position >= len(text) or text[position] not in '[{':
            return missing, position, False
        mapping = text[position] == '{'
        value = {} if mapping else []
        position += 1
        while position < len(text):
            while position < len(text) and text[position].isspace():
                position += 1
            if mapping:
                try:
                    key, position = decoder.raw_decode(text, position)
                except (ValueError, RecursionError):
                    break
                if not isinstance(key, str):
                    break
                while position < len(text) and text[position].isspace():
                    position += 1
                if position >= len(text) or text[position] != ':':
                    break
                position += 1
            item, position, complete = read(position, depth + 1)
            if item is not missing:
                if mapping:
                    value[key] = item
                else:
                    value.append(item)
            if not complete:
                break
            while position < len(text) and text[position].isspace():
                position += 1
            if position >= len(text) or text[position] != ',':
                break
            position += 1
        return value, position, False
    value, _, complete = read(0)
    if partial or not complete:
        report('partial-response')
    return value if value is not missing else None


def _hidden_markup(node):
    attrs = node['attrs']
    return (node.get('unsafe_scope') or 'hidden' in attrs or (attrs.get('aria-hidden') or '').strip().lower() == 'true'
        or re.search(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\b', attrs.get('style') or '', re.I))


class _ResponseHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes, self.stack = [], []
        self.has_cpe, self.has_denial, self.shell_text = False, False, False
        self.partial = False

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1] if self.stack else None
        node = {'tag': tag, 'attrs': {name: value or '' for name, value in attrs},
                'text': [], 'parent': parent, 'closed': False}
        if (tag in {'a', 'meta', 'form', 'iframe', 'frame', 'object', 'article', 'html', 'body'}
                or tag == 'script' and node['attrs'].get('type') == 'application/json'
                or parent is not None and parent['tag'] in {'body', 'html'}):
            self.nodes.append(node)
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'input', 'embed', 'source', 'base', 'area', 'wbr', 'param', 'col', 'frame'}:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]['tag'] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]['tag'] == tag:
                self.stack[index]['closed'] = True
                del self.stack[index:]
                break

    def handle_data(self, data):
        if not any(node['tag'] in {'script','style','template','noscript','head','title'} or _hidden_markup(node) for node in self.stack):
            self.has_cpe |= bool(re.search(r'\bCPE00001\b', data, re.I))
            self.has_denial |= 'there was a problem providing the content you requested' in data.lower()
            if data.strip() and not any(node['tag']=='iframe' for node in self.stack):
                self.shell_text = True
        for node in self.stack:
            if node['tag'] in {'a', 'iframe'} or node['tag'] == 'script' and node['attrs'].get('type') == 'application/json':
                node['text'].append(data)


def _ancestors(node):
    while node is not None:
        yield node
        node = node['parent']


def _node_text(node):
    return ''.join(node['text'])



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
            and re.fullmatch(r'/(?:[A-Za-z0-9_-]+/)?viewmedia\.cfm', url.path) and query.get('uri') and len(query['uri'][0]) <= 256
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
    source_parsed = urlsplit(source)
    source_query = parse_qs(source_parsed.query)
    if (source_parsed.hostname != url.hostname
            or kind == 'sciencedirect' and '/pii/' + identifier not in source_parsed.path
            or kind == 'ieee' and source_parsed.path != '/document/' + identifier and source_query.get('arnumber') != [identifier]
            or kind == 'optica' and source_query.get('uri') != [identifier]
            or kind == 'lww' and source_parsed.path.split('/')[1] != url.path.split('/')[1]):
        source = actual  # The current response's verified HTTP redirect chain.
    return dict(rule_id={'sciencedirect': 'R024', 'ieee': 'R025', 'optica': 'R053', 'lww': 'R060'}[kind],
        platform=kind, url=actual, identifier=identifier,
        source_url=source, stage=candidate.stage)


def access_limited(response):
    if response.access or response.status in {401, 403, 407, 418, 429}:
        return True
    text = response.body.decode('utf-8', errors='replace').lower()
    if html_access(text, response.status):
        return True
    if 'cpe00001' not in text and '_incapsula_resource' not in text:
        return False
    parser = _ResponseHTML()
    try:
        parser.feed(response.body.decode('utf-8', errors='replace'))
    except (ValueError, RecursionError):
        # An incomplete scan is not proof of an access barrier. Only visible
        # paired denial evidence already observed can retain that conclusion.
        return parser.has_cpe and parser.has_denial
    if parser.has_cpe and parser.has_denial and not any(node['tag']=='article' for node in parser.nodes):
        return True
    root = next((node for node in parser.nodes if node['tag']=='body'), None)
    if root is None:
        root = next((node for node in parser.nodes if node['tag']=='html'), None)
    children = [node for node in parser.nodes if node['parent'] is root
        and node['tag']!='head']
    if not children or parser.shell_text or any(node['tag']!='iframe' for node in children):
        return False
    source = urlsplit(response.url)
    for frame in children:
        linked = urlsplit(urljoin(response.url, frame['attrs'].get('src','')))
        if ((linked.scheme,linked.netloc)==(source.scheme,source.netloc) and linked.path=='/_Incapsula_Resource'
                and re.match(r'\s*Request unsuccessful\.\s*Incapsula incident ID:',_node_text(frame),re.I)):
            return True
    return False


def _safe_next(candidate, base, value, **extra):
    if not isinstance(value, str) or not value:
        return None
    try:
        url = urljoin(base, value)
        normalize_public_http_url(url)
        parsed = urlsplit(url)
        if parsed.hostname == 'journals.plos.org' and 'manuscript' in parse_qs(parsed.query).get('type', ()):
            return None
        return replace(candidate, **({'url': url, 'reader_kind': None, 'credential': None, 'accept': None,
            'recover_access': False} | extra))
    except ValueError:
        return None


def _excluded(node):
    return any(p['tag'] in {'nav', 'footer', 'aside'} or p['attrs'].get('role') in {'doc-bibliography', 'doc-endnotes'}
        or 'hidden' in p['attrs'] or p['attrs'].get('aria-hidden') == 'true'
        or _hidden_markup(p)
        or re.search(r'references|related|recommend|supplement', ' '.join(p['attrs'].get(key, '') or ''
            for key in ('id', 'class', 'title')), re.I)
        for p in _ancestors(node))


def _body_entry(node, base, doi, attribute='href'):
    attrs = node['attrs']
    label = _node_text(node) + ' ' + attrs.get('title', '') + ' ' + attrs.get(attribute, '')
    if _excluded(node) or re.search(r'supplement|supporting|appendix|whole issue|entire issue|issue pdf|other article', label, re.I):
        return False
    for owner in _ancestors(node):
        if 'data-doi' in owner['attrs'] and valid_doi(owner['attrs']['data-doi']) != doi:
            return False
    try:
        linked = urlsplit(urljoin(base, attrs.get(attribute, '')))
    except ValueError:
        return False
    matched = re.fullmatch(r'/doi/(?:pdf|epdf|pdfplus)/(10\.[0-9]{4,9}/.+)', unquote(linked.path))
    return not matched or valid_doi(matched[1]) == doi


def oxford_citation(url):
    actual = urlsplit(url)
    query = parse_qs(actual.query)
    return (actual.hostname == 'academic.oup.com' and actual.path == '/Citation/Download'
        and query.get('resourceType') == ['3'] and re.fullmatch(r'[0-9]{1,16}',
            next(iter(query.get('resourceId', ())), '')) is not None)


def parse_current_response(candidate, response, *, report=lambda code: None):
    if response.partial:
        report('partial-response')
    if response.status in {301, 302, 303, 307, 308} and response.redirect_url:
        # This is an observed ordinary GET response, not an inferred publisher
        # relationship or permission to forward explicit credentials. Main
        # validates the destination URL/DNS before its next Session request.
        item = _safe_next(candidate, response.url, response.redirect_url)
        return (item,) if item else ()
    if response.status != 200 or access_limited(response):
        return ()
    content = response.content_type.partition(';')[0].strip().lower()
    text = response.body.decode('utf-8', errors='replace')
    actual = urlsplit(response.url)
    if candidate.rule_id == 'R073' and candidate.field == 'ebsco_download_link':
        # This was a link from the verified record's PDF field. A JSON
        # indirection needs its actual URL field, regardless of Content-Type.
        if not text.lstrip().startswith('{'):
            return ()
        value = json_sample(response.body, partial=response.partial, report=report)
        item = _safe_next(candidate, response.url, value.get('url')) if isinstance(value, dict) else None
        return (item,) if item else ()
    if (candidate.rule_id == 'API06' and actual.hostname == 'api.elsevier.com'
            and actual.path.startswith('/content/article/') and text.lstrip().startswith('{')):
        try:
            data = json_sample(response.body, partial=response.partial, report=report).get('full-text-retrieval-response', {}).get('coredata', {})
            if valid_doi(data.get('prism:doi')) != candidate.target.identity_doi or not candidate.target.identity_doi:
                return ()
            entries = data.get('link')
            if not isinstance(entries, list):
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
    if oxford_citation(response.url):
        match = re.search(r'\beprint\s*=\s*(?:\{([^{}]+)\}|"([^"]+)")', text, re.I)
        value = (match[1] or match[2]).strip() if match else None
        # Explicit eprint must be a PDF entry, not the citation's article URL.
        if value and re.search(r'/article-pdf/|\.pdf(?:[?#]|$)|/doi/(?:pdf|epdf)/', value, re.I):
            item = _safe_next(candidate, response.url, value)
            return (item,) if item else ()
        return ()
    if content not in {'text/html', 'application/xhtml+xml'} and not text.lstrip().startswith('<'):
        return ()
    parser = _ResponseHTML()
    try:
        parser.feed(text)
    except (ValueError, RecursionError):
        parser.partial = True
    if response.partial and parser.stack:
        last = parser.stack[-1]
        if last['tag'] == 'script' and last['attrs'].get('type') == 'application/json':
            # HTMLParser holds unclosed script data until an end tag. The
            # fixed JSON carrier can still contain complete earlier fields.
            last['text'].append(parser.rawdata)
    if parser.partial:
        report('partial-response')
    nodes = parser.nodes
    # A main-record conflict overrides even an already qualified Reader route.
    dois = {valid_doi(node['attrs'].get('content')) for node in nodes
        if node['tag'] == 'meta' and (node['attrs'].get('name') or node['attrs'].get('property', '')).lower()
        in {'citation_doi', 'prism.doi', 'dc.identifier.doi'} and any(p['tag'] == 'head' for p in _ancestors(node['parent']))}
    dois.discard(None)
    wanted = candidate.target.identity_doi
    if wanted and dois and dois != {wanted}:
        return ()
    kind = _reader_kind(candidate, response.url)
    values = []
    def add(value, **extra):
        item = _safe_next(candidate, response.url, value, article_verified=True, **extra)
        if item and all(item.url != old.url for old in values):
            values.append(item)
    if kind:
        frames = [node for node in nodes if node['tag'] == 'frame']
        for node in nodes:
            tag, attrs = node['tag'], node['attrs']
            if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh' and kind in {'sciencedirect', 'ieee'}:
                match = re.fullmatch(r'\s*\d+(?:\.\d+)?\s*;\s*url\s*=\s*[\'"]?([^\'"]+)[\'"]?\s*', attrs.get('content', ''), re.I)
                if match:
                    add(match[1].strip())
            if kind == 'sciencedirect':
                if tag == 'a' and any(p['attrs'].get('id') == 'redirect-message' for p in _ancestors(node['parent'])):
                    add(attrs.get('href'))
                if tag == 'object' and node['parent'] is not None and 'PdfEmbed' in node['parent']['attrs'].get('class', '').split():
                    add(attrs.get('data'))
            if kind == 'ieee' and tag in {'frame', 'iframe'}:
                add(attrs.get('src'))
            if kind == 'optica' and tag == 'frame' and any(
                    old['parent'] is node['parent']
                    for old in frames[:frames.index(node)]):
                add(attrs.get('src'))
            if kind in {'sciencedirect', 'lww'} and tag == 'script' and attrs.get('type') == 'application/json':
                try:
                    data = json_sample(_node_text(node).encode(), partial=not node['closed'], report=report)
                    # Fixed data carriers only; no regex over arbitrary scripts,
                    # evaluation, graph traversal or recursive URL-key search.
                    value = (data.get('article', {}).get('pdfDownload', {}).get('urlMetadata')
                        if kind == 'sciencedirect' else data.get('pdfDownloadDetails', {}).get('pdfUrl'))
                    if isinstance(value, str):
                        add(value, **({'referer': response.url} if kind == 'lww' else {}))
                except (ValueError, AttributeError, TypeError, RecursionError):
                    report('parse-failed')
        if kind == 'optica':
            add(next(iter(parse_qs(actual.query).get('gotourl', ())), None))
        return tuple(values)
    # An observed article relationship can carry through later HTML.
    actual_doi = re.search(r'/doi/(?:abs/|full/|pdf/|epdf/|pdfplus/)?(10\.[0-9]{4,9}/.+)$', unquote(actual.path))
    article = candidate.target.article_url
    established = (candidate.article_verified
        or bool(article and urldefrag(article)[0] == urldefrag(response.url)[0])
        or bool(actual_doi and valid_doi(actual_doi[1]) == wanted and wanted))
    if not (wanted and dois or established):
        return ()
    for name in ('citation_pdf_url', 'fulltext_pdf_url'):
        for node in nodes:
            if (node['tag'] == 'meta' and any(p['tag'] == 'head' for p in _ancestors(node['parent']))
                    and (node['attrs'].get('name') or node['attrs'].get('property', '')).lower() == name):
                add(node['attrs'].get('content'))
    host = actual.hostname or ''
    silverchair = host in {'pubs.acs.org', 'pubs.aip.org', 'jamanetwork.com',
        'pubs.geoscienceworld.org', 'academic.oup.com'} or any(host == root or host.endswith('.' + root)
            for root in ('rupress.org', 'ashpublications.org', 'arvojournals.org'))
    atypon = host in ATYPON_HOSTS
    for node in nodes:
        tag, attrs = node['tag'], node['attrs']
        label = _node_text(node) + ' ' + attrs.get('title', '') + ' ' + attrs.get('href', '')
        if not _body_entry(node, response.url, candidate.target.identity_doi,
                'data-article-url' if host == 'jamanetwork.com' and attrs.get('id') == 'pdf-link' else 'action' if tag == 'form' else 'href'):
            continue
        classes = attrs.get('class', '').split()
        if tag == 'a':
            selected = (silverchair and 'article-pdfLink' in classes
                or (host == 'nature.com' or host.endswith('.nature.com')) and attrs.get('data-track-action') == 'download pdf'
                or host in {'degruyterbrill.com', 'www.degruyterbrill.com'} and 'downloadPdf' in classes
                or host in {'emerald.com', 'www.emerald.com'} and 'intent_pdf_link' in classes
                or host in {'opg.optica.org', 'osapublishing.org', 'www.osapublishing.org'} and attrs.get('id') == 'link-pdf'
                or (host == 'elifesciences.org' or host.endswith('.elifesciences.org'))
                    and any('article-download-list' in p['attrs'].get('class', '').split() for p in _ancestors(node['parent']))
                    and re.search(r'\bpdf\b', label, re.I))
            if selected:
                add(attrs.get('href'))
            if host == 'jamanetwork.com' and attrs.get('id') == 'pdf-link':
                add(attrs.get('data-article-url'))
            if atypon and isinstance(attrs.get('href'), str):
                linked = urlsplit(urljoin(response.url, attrs['href']))
                matched = re.fullmatch(r'/doi/(?:pdf|epdf|pdfplus)/(10\.[0-9]{4,9}/.+)', linked.path)
                if matched and linked.hostname == host and valid_doi(matched[1]) == candidate.target.identity_doi:
                    add(attrs['href'])
        if (tag == 'form' and (host == 'microbiologyresearch.org' or host.endswith('.microbiologyresearch.org'))
                and 'ft-download-content__form--pdf' in classes
                and any('download-pdf' in p['attrs'].get('class', '').split() for p in _ancestors(node['parent']))):
            add(attrs.get('action'), action='refresh_form')
    # Only one unambiguous main-article PDF entrance. Other article/issue and
    # supplement links are excluded before deciding ambiguity.
    generic = []
    for node in nodes:
        if node['tag'] != 'a' or not _body_entry(node, response.url, candidate.target.identity_doi) or not any(p['tag'] in {'article', 'main'} for p in _ancestors(node['parent'])):
            continue
        attrs = node['attrs']
        label = (_node_text(node) + ' ' + attrs.get('title', '')).strip()
        if re.search(r'supplement|supporting|appendix|whole issue|entire issue|other article', label + ' ' + attrs.get('href', ''), re.I):
            continue
        if (response.partial or parser.partial) and not node['closed'] and attrs.get('type') != 'application/pdf':
            continue
        if re.fullmatch(r'(?:download\s+)?(?:(?:full[ -]?text|article)\s+)?pdf(?:\s+download)?', label, re.I) or attrs.get('type') == 'application/pdf':
            item = _safe_next(candidate, response.url, attrs.get('href'))
            if item and item.url not in generic:
                generic.append(item.url)
    if len(generic) == 1:
        add(generic[0])
    return tuple(values)
