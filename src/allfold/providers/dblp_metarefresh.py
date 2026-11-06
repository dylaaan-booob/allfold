"""Recognize DBLP's bounded Anubis v1.27.0 metarefresh exchange.

Protocol reference: TecharoHQ/anubis d39e26c, lib/challenge/metarefresh.
No JavaScript execution or proof-of-work algorithms are supported.
"""
from html.parser import HTMLParser
import json
import re
from urllib.parse import parse_qs, parse_qsl, urljoin, urlsplit


VERIFY_PATH = '/.within.website/x/cmd/anubis/api/pass-challenge'


def _dblp_url(url):
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and parsed.hostname == 'dblp.org'
            and parsed.port in (None, 443) and not parsed.username
            and not parsed.password and not parsed.fragment)


def same_query(url, original):
    """Permit equivalent query escaping, but no change to its scope or page."""
    try:
        left, right = urlsplit(urljoin(original, url)), urlsplit(original)
        return (_dblp_url(left.geturl()) and _dblp_url(original)
                and left.path == right.path == '/search/publ/api'
                and sorted(parse_qsl(left.query, keep_blank_values=True))
                == sorted(parse_qsl(right.query, keep_blank_values=True)))
    except ValueError:
        return False


class _Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts, self.refreshes, self.current = {}, [], None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('id') in {'anubis_version', 'anubis_challenge'}:
            self.current = attrs['id']
            if self.current in self.scripts:
                raise ValueError('Duplicate protocol data')
            self.scripts[self.current] = ''
        if tag == 'meta' and attrs.get('http-equiv', '').lower() == 'refresh':
            self.refreshes.append(attrs.get('content', ''))

    def handle_endtag(self, tag):
        if tag == 'script':
            self.current = None

    def handle_data(self, value):
        if self.current:
            self.scripts[self.current] += value


def recovery_plan(response):
    """Return (wait_seconds, verification_url) only for an exact known exchange."""
    if response.status_code not in (200, 202) or len(response.content) > 1024 * 1024:
        return None
    original = str(response.request.url)
    if not same_query(original, original):
        return None
    try:
        page = _Page()
        page.feed(response.text)
        if json.loads(page.scripts['anubis_version']) != 'v1.27.0':
            return None
        data = json.loads(page.scripts['anubis_challenge'])
        rules, challenge = data['rules'], data['challenge']
        difficulty = rules['difficulty']
        if rules['algorithm'] != 'metarefresh' or type(difficulty) is not int or not 0 <= difficulty < 60:
            return None
        refreshes = page.refreshes + response.headers.get_list('refresh')
        plans = []
        for refresh in refreshes:
            match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*;\s*url\s*=\s*(.*?)\s*', refresh, re.I)
            if not match:
                return None
            delay = float(match[1])
            target = urljoin(original, match[2].strip('"\''))
            parsed = urlsplit(target)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if (not difficulty + 1 <= delay <= 60 or len(target) > 16384
                    or not _dblp_url(target) or parsed.path != VERIFY_PATH
                    or set(query) != {'id', 'challenge', 'redir'}
                    or any(len(values) != 1 for values in query.values())
                    or not isinstance(challenge['id'], str) or not challenge['id']
                    or not isinstance(challenge['randomData'], str) or not challenge['randomData']
                    or query['id'] != [challenge['id']]
                    or query['challenge'] != [challenge['randomData']]
                    or not same_query(query['redir'][0], original)):
                return None
            plans.append((delay, target))
        return plans[0] if plans and all(plan == plans[0] for plan in plans) else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
