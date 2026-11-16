"""Current HTML response evidence; no fetching, browser handoff or client state."""
from html.parser import HTMLParser
import re
from urllib.parse import urlsplit


class _AccessHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.title = ''
        self.heading = ''
        self.content = False
        self.password = False
        self.frame = False
        self.captcha = False
        self.options = False
        self.orchestrator = False
        self.anubis = False

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        hidden = (any(item[1] for item in self.stack) or 'hidden' in attrs
            or attrs.get('aria-hidden', '').lower() == 'true'
            or bool(re.search(r'(?:display\s*:\s*none|visibility\s*:\s*(?:hidden|collapse))\b', attrs.get('style', ''), re.I)))
        if tag == 'script':
            self.orchestrator |= bool(re.search(r'/cdn-cgi/challenge-platform/[^\s"\'<>]*orchestrate/chl_page/', attrs.get('src', '')))
            self.anubis |= attrs.get('id') == 'anubis_challenge' and attrs.get('type') == 'application/json'
        if tag == 'iframe' and not hidden:
            self.frame = True
            url = urlsplit(attrs.get('src', ''))
            self.captcha |= (bool(re.search(r'(^|\.)(hcaptcha\.com|recaptcha\.net|google\.com)$', url.hostname or ''))
                and ('captcha' in url.path))
        if tag == 'input' and not hidden and attrs.get('type', '').lower() == 'password':
            self.password = True
        if tag not in {'input', 'meta', 'link', 'img', 'br', 'hr', 'embed', 'source', 'base', 'area', 'wbr', 'param', 'col'}:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        tags = [tag for tag, _ in self.stack]
        if 'script' in tags:
            self.options |= bool(re.search(r'\b_cf_chl_opt\s*=\s*\{', data))
            return
        if 'title' in tags:
            self.title += data
        if any(hidden for _, hidden in self.stack) or any(tag in tags for tag in ('style', 'template', 'noscript', 'head')):
            return
        if any(tag in tags for tag in ('h1', 'h2')):
            self.heading += data
        if 'article' in tags and data.strip():
            self.content = True


def html_access(body: str, status: int = 200) -> str | None:
    """Conservative fallback when no authoritative response header is available."""
    parser = _AccessHTML()
    try:
        parser.feed(body)
    except (ValueError, RecursionError):
        return None
    title = parser.title.strip()
    if parser.content:
        return None
    if ((re.match(r'^(Just a moment|Attention Required)(?:[.!…\s]|$)', title, re.I)
            and (status >= 400 or parser.options or parser.orchestrator))
            or parser.options and parser.orchestrator):
        return 'cloudflare'
    if parser.anubis and re.match(r'^Making sure you.re not a bot', title, re.I):
        return 'anubis'
    if (parser.captcha or parser.frame and re.match(r'^(Verify you are human|Are you a robot|Human verification)', title, re.I)):
        return 'verification'
    if parser.password and re.match(r'^(Sign in|Log in|Login|Authentication)\b', title or parser.heading, re.I):
        return 'login'
    return None
